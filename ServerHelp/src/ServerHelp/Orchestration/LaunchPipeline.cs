using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Threading;
using ServerHelp.Core;
using ServerHelp.Mc;
using ServerHelp.Net;
using ServerHelp.Sys;
using ServerHelp.Tunnel;

namespace ServerHelp.Orchestration
{
    public sealed class PipelineStep
    {
        public string TitleFa = "";
        public string TitleEn = "";
        public StepState State = StepState.Pending;
        public string Detail = "";
        public int ElapsedMs;

        public string Title { get { return L.T(TitleFa, TitleEn); } }

        public override string ToString()
        {
            string line = Title + " — " + L.T(StateTextFa, StateTextEn);
            if (!string.IsNullOrEmpty(Detail)) line += " (" + Detail + ")";
            return line;
        }

        public string StateTextFa
        {
            get
            {
                switch (State)
                {
                    case StepState.Done: return "انجام شد";
                    case StepState.Warn: return "هشدار";
                    case StepState.Fail: return "ناموفق";
                    case StepState.Skip: return "رد شد";
                    default: return "در حال انجام";
                }
            }
        }

        public string StateTextEn
        {
            get
            {
                switch (State)
                {
                    case StepState.Done: return "done";
                    case StepState.Warn: return "warning";
                    case StepState.Fail: return "failed";
                    case StepState.Skip: return "skipped";
                    default: return "working";
                }
            }
        }
    }

    public sealed class LaunchReport
    {
        public string Strategy = "";          // direct | warp | proxy | dns | none
        public bool TunnelUp;
        public bool HostsApplied;
        public string ChosenIp = "";
        public List<string> ResolvedIps = new List<string>();
        public int DirectPing = -1;
        public int TunnelPing = -1;
        public string EndpointUsed = "";
        public LoginVerdict Verdict = LoginVerdict.Unknown;
        public string VerdictMessage = "";
        public long ElapsedMs;
        public bool WithinBudget = true;
        public string Error = "";
        public List<string> Warnings = new List<string>();
        public int GamePid = -1;

        // ---- the chosen connection
        public string ConnectionUsed = "";     // name of the entry that was picked
        public string ConnectionKind = "";     // its kind, translated
        public int ConnectionDelayMs = -1;
        /// <summary>True when the game itself has to use the local SOCKS port (-DsocksProxy*).</summary>
        public bool ProxyOnlyMode;
        public int ProxyPort;
        /// <summary>Every tested candidate with its result, for the report tab.</summary>
        public List<string> Candidates = new List<string>();
        public bool LeakGuardArmed;
        public string LeakGuardNote = "";
    }

    /// <summary>
    /// The whole "pick a version and press play" flow: diagnose the network, decide whether a
    /// tunnel is needed, tune the machine, bring the tunnel up, verify it against the real server
    /// and only then start the game.
    /// </summary>
    public sealed class LaunchPipeline
    {
        public const int BudgetMs = 60000;

        public event Action<PipelineStep> StepChanged;
        public event Action<string> Progress;
        public event Action<LaunchReport> Finished;

        public readonly LaunchReport Report = new LaunchReport();
        public readonly SystemOptimizer Optimizer = new SystemOptimizer();
        public readonly SingBoxRunner Tunnel = new SingBoxRunner();
        public readonly GameLauncher Game = new GameLauncher();

        public string SocksPortTag = "";
        public int SocksPort = 22345;
        public int ClashPort = 22346;
        public string ClashSecret = "";
        public bool KeepTunnel;
        public bool AutoRestore;
        public bool KillSwitch;

        private volatile bool _cancel;
        private readonly List<string> _hostsNames = new List<string>();
        private readonly List<string> _routesAdded = new List<string>();
        private readonly List<string> _blackholes = new List<string>();
        private string _tunName = "ServerHelp";
        private Thread _leakGuard;
        private volatile bool _leakStopped;
        private SelectedRoute _selectedRoute;
        private ConnectionEntry _dnsEntry;
        private readonly List<string> _routedIps = new List<string>();

        public void Cancel() { _cancel = true; }
        public bool Cancelled { get { return _cancel; } }

        public bool TunnelRunning { get { return Tunnel.IsRunning; } }
        public bool GameRunning { get { return Game.IsRunning; } }

        // ------------------------------------------------------------------ main

        public void Run(AppSettings settings, ServerProfile server, McVersion version, string gameDir, string javaPath)
        {
            var watch = Stopwatch.StartNew();
            KeepTunnel = settings.KeepTunnelAfterGame;
            AutoRestore = settings.AutoRestoreOnExit;
            KillSwitch = settings.KillSwitch;
            _cancel = false;
            _blackholes.Clear();
            try
            {
                RunCore(settings, server, version, gameDir, javaPath);
            }
            catch (Exception ex)
            {
                Report.Error = ex.Message;
                Log.Error("pipeline failed", ex);
                Step("خطای غیرمنتظره", "Unexpected failure", StepState.Fail, ex.Message, 0);
            }
            watch.Stop();
            Report.ElapsedMs = watch.ElapsedMilliseconds;
            Report.WithinBudget = Report.ElapsedMs <= BudgetMs;
            Log.Info("pipeline finished in " + Report.ElapsedMs + " ms (budget " + BudgetMs + " ms)");
            Action<LaunchReport> handler = Finished;
            if (handler != null) { try { handler(Report); } catch { } }
        }

        private void RunCore(AppSettings settings, ServerProfile server, McVersion version, string gameDir, string javaPath)
        {
            // ---------------------------------------------------------- 1. preflight
            var watch = Stopwatch.StartNew();
            if (version == null) { Step("انتخاب نسخه", "Version selection", StepState.Fail, L.T("نسخه‌ای انتخاب نشده", "no version selected"), 0); return; }
            string javaCheck = Shell.FileExists(javaPath) ? L.T("Java پیدا شد", "Java found") : L.T("Java پیدا نشد", "Java not found");
            Step("بررسی پیش‌نیازها", "Preflight", Shell.FileExists(javaPath) ? StepState.Done : StepState.Warn,
                version.Id + " • " + javaCheck, (int)watch.ElapsedMilliseconds);

            // ---------------------------------------------------------- 2. network diagnosis
            watch.Restart();
            Notify(L.T("تشخیص وضعیت شبکه…", "Diagnosing the network…"));
            var candidates = new List<string>();
            string host = server.PreferDomain || string.IsNullOrEmpty(server.DirectIp) ? server.Host : server.DirectIp;

            if (server.PreferDomain && !string.IsNullOrEmpty(server.Host))
            {
                foreach (string ip in NetUtil.ResolveSimple(server.Host)) AddUnique(candidates, ip);
                if (candidates.Count == 0)
                {
                    string doh = NetUtil.ResolveDoh("https://1.1.1.1/dns-query", server.Host, 5000);
                    if (string.IsNullOrEmpty(doh)) doh = NetUtil.ResolveDoh("https://8.8.8.8/resolve", server.Host, 5000);
                    if (!string.IsNullOrEmpty(doh))
                    {
                        AddUnique(candidates, doh);
                        Report.Warnings.Add(L.T("DNS سیستم جواب نداد؛ از DNS امن استفاده شد.", "system DNS failed, a secure resolver answered."));
                    }
                }
            }
            if (!string.IsNullOrEmpty(server.DirectIp)) AddUnique(candidates, server.DirectIp);
            Report.ResolvedIps = new List<string>(candidates);
            if (candidates.Count == 0)
                candidates.Add("");

            string bestIp = "";
            int bestPing = -1;
            McStatus bestStatus = null;
            int directVerdict = -1;
            foreach (string ip in candidates)
            {
                if (_cancel) return;
                if (string.IsNullOrEmpty(ip)) continue;
                IPAddress parsed;
                if (!IPAddress.TryParse(ip, out parsed)) continue;
                int rtt;
                int verdict = NetUtil.TcpProbe(parsed, server.Port, Math.Min(3000, settings.ConnectTimeoutMs), out rtt);
                if (verdict == 0 || verdict == 3)
                {
                    var status = McPing.Status(ip, server.Port, Math.Min(4000, settings.ConnectTimeoutMs), null);
                    if (status != null && status.Ok && (bestStatus == null || status.LatencyMs < bestPing || bestPing < 0))
                    {
                        bestIp = ip;
                        bestPing = status.LatencyMs;
                        bestStatus = status;
                        directVerdict = verdict;
                    }
                    else if (verdict == 3 && directVerdict < 0)
                    {
                        directVerdict = 3;
                    }
                }
                else if (directVerdict < 0) directVerdict = verdict;
            }

            if (bestStatus != null)
            {
                Step("تشخیص شبکه", "Network diagnosis", StepState.Done,
                    L.T("اتصال مستقیم سالم است: ", "direct connection works: ") + bestIp + " • " + L.N(bestPing) + L.T("ms", " ms") +
                    (string.IsNullOrEmpty(bestStatus.Motd) ? "" : " • " + bestStatus.Motd), (int)watch.ElapsedMilliseconds);
            }
            else
            {
                string symptom = directVerdict == 3
                    ? L.T("اتصال مستقیم بسته می‌شود (نشانه فیلتر روی IP/SNI)", "the direct connection is reset (IP/SNI filtering)")
                    : directVerdict == 2
                        ? L.T("اتصال مستقیم زمان‌بندی می‌شود (احتمال فیلتر)", "the direct connection times out (likely filtered)")
                        : directVerdict == 1
                            ? L.T("پورت بسته است (سرور خاموش یا پورت اشتباه)", "the port is closed (server down or wrong port)")
                            : L.T("وضعیت نامشخص", "unknown state");
                Step("تشخیص شبکه", "Network diagnosis", StepState.Warn, symptom, (int)watch.ElapsedMilliseconds);
                Report.Warnings.Add(symptom);
            }
            Report.DirectPing = bestPing;
            Report.ChosenIp = bestIp;

            // ---------------------------------------------------------- 3. strategy
            bool needTunnel = false;
            string strategy = "none";
            switch (settings.Tunnel)
            {
                case TunnelMode.Off:
                    strategy = "none";
                    break;
                case TunnelMode.DnsOnly:
                    strategy = "dns";
                    break;
                case TunnelMode.Warp:
                    needTunnel = true;
                    strategy = "warp";
                    break;
                default:
                    needTunnel = bestStatus == null;   // auto: only when the direct path is broken
                    strategy = needTunnel ? "warp" : "none";
                    break;
            }

            // A connection the user entered (or pinned) takes part in the decision: it may replace
            // the automatic WARP route, fix name resolution, or simply be reported as unavailable.
            List<ConnectionEntry> candidatesToTest = ConnectionCandidates(settings, out string pinnedName);
            if (settings.Tunnel != TunnelMode.Off && candidatesToTest.Count > 0)
            {
                SelectedRoute route = SelectRoute(settings, server, candidatesToTest, pinnedName, Math.Min(4000, settings.ConnectTimeoutMs));
                if (route != null && route.Entry != null)
                {
                    if (route.Entry.Info.IsResolver)
                    {
                        strategy = "dns";
                        needTunnel = false;
                        _dnsEntry = route.Entry;
                    }
                    else
                    {
                        needTunnel = true;
                        strategy = route.Entry.Kind == ConnectionKind.Warp ? "warp" : "proxy";
                        _selectedRoute = route;
                    }
                }
                else if (pinnedName.Length > 0 && _dnsEntry == null)
                {
                    Report.Warnings.Add(L.T("اتصال انتخابی شما کار نکرد؛ مسیر خودکار امتحان می‌شود.",
                                            "the connection you pinned did not work, the automatic route is used instead."));
                }
            }
            Report.Strategy = strategy;

            // ---------------------------------------------------------- 4. system tuning
            watch.Restart();
            Notify(L.T("بهینه‌سازی سیستم…", "Tuning the system…"));
            Optimizer.TunnelExePath = Shell.FileExists(AppPaths.SingBoxExe) ? AppPaths.SingBoxExe : "";
            Optimizer.JavaExePath = javaPath;
            Optimizer.Run(settings, delegate (OptimizationStep s)
            {
                var step = new PipelineStep();
                step.TitleFa = "بهینه‌سازی: " + s.TitleFa;
                step.TitleEn = "tuning: " + s.TitleEn;
                step.State = s.State;
                step.Detail = s.Detail;
                step.ElapsedMs = s.ElapsedMs;
                Emit(step);
            });

            // ---------------------------------------------------------- 5. tunnel
            if (needTunnel && !_cancel)
            {
                bool tunnelOk = strategy == "proxy"
                    ? PrepareProxyRoute(settings, server, candidates)
                    : PrepareTunnel(settings, server, candidates);
                if (!tunnelOk)
                {
                    if (settings.AllowRouteFallback && strategy == "proxy")
                    {
                        Report.Warnings.Add(L.T("مسیر انتخابی کار نکرد؛ تونل WARP امتحان می‌شود.",
                                                "the chosen route did not work, the WARP tunnel is tried instead."));
                        _selectedRoute = null;
                        tunnelOk = PrepareTunnel(settings, server, candidates);
                    }
                    if (!tunnelOk)
                    {
                        strategy = "dns";
                        Report.Strategy = "dns";
                        Report.Warnings.Add(L.T("تونل برپا نشد؛ به حالت DNS/هاست سوییچ شد.", "the tunnel could not be established, falling back to DNS/hosts mode."));
                    }
                }
            }
            Report.Strategy = strategy;

            // ---------------------------------------------------------- 6. name resolution fix
            if (settings.UseHostsFile && settings.Tunnel != TunnelMode.Off && !_cancel)
            {
                // A DNS server the user entered is used first: a poisoned system resolver is one of
                // the reasons the game cannot reach the server at all.
                if (_dnsEntry != null)
                {
                    watch.Restart();
                    var answer = Net.DnsClient.Resolve(_dnsEntry.DnsUrl, server.Host, Math.Min(5000, settings.ConnectTimeoutMs));
                    Report.Candidates.Add(_dnsEntry.Name + " [" + _dnsEntry.Info.Title + "] → " + answer.Summary);
                    if (answer.Ok)
                    {
                        foreach (string ip in answer.Addresses) AddUnique(Report.ResolvedIps, ip);
                        if (string.IsNullOrEmpty(bestIp)) bestIp = answer.First;
                        _dnsEntry.LastDelayMs = answer.ElapsedMs;
                        _dnsEntry.LastStatus = L.T("رزولو شد", "resolved");
                        Step(L.T("رزولوشن با DNS انتخابی", "Resolve with the chosen DNS"), L.T("رزولوشن با DNS انتخابی", "Resolve with the chosen DNS"),
                            StepState.Done, _dnsEntry.DnsUrl + " → " + string.Join(", ", answer.Addresses.ToArray()) +
                            " • " + L.N(answer.ElapsedMs) + " ms", (int)watch.ElapsedMilliseconds);
                    }
                    else
                    {
                        Step(L.T("رزولوشن با DNS انتخابی", "Resolve with the chosen DNS"), L.T("رزولوشن با DNS انتخابی", "Resolve with the chosen DNS"),
                            StepState.Warn, _dnsEntry.DnsUrl + " → " + answer.Error, (int)watch.ElapsedMilliseconds);
                    }
                }

                string pinIp = Report.TunnelUp && !string.IsNullOrEmpty(Report.ChosenIp) ? Report.ChosenIp : bestIp;
                if (string.IsNullOrEmpty(pinIp) && Report.ResolvedIps.Count > 0) pinIp = Report.ResolvedIps[0];
                bool systemResolutionOk = false;
                foreach (string ip in NetUtil.ResolveSimple(server.Host)) if (ip == pinIp) systemResolutionOk = true;
                if (!string.IsNullOrEmpty(pinIp) && (!systemResolutionOk || settings.Tunnel == TunnelMode.Warp))
                {
                    watch.Restart();
                    string error;
                    if (HostsFile.Apply(server.Host, pinIp, out error))
                    {
                        _hostsNames.Add(server.Host);
                        Report.HostsApplied = true;
                        Step("تثبیت آدرس سرور (hosts)", "Pin the server address (hosts)", StepState.Done,
                            server.Host + " → " + pinIp, (int)watch.ElapsedMilliseconds);
                    }
                    else
                    {
                        Step("تثبیت آدرس سرور (hosts)", "Pin the server address (hosts)", StepState.Warn, error, (int)watch.ElapsedMilliseconds);
                    }
                }
            }

            // ---------------------------------------------------------- 7. login probe
            if (!_cancel && settings.LoginProbe)
            {
                watch.Restart();
                Socks5Client proxy = Report.TunnelUp ? new Socks5Client("127.0.0.1", SocksPort, 6000) : null;
                string message;
                LoginVerdict verdict = McPing.LoginProbe(host, server.Port, settings.Nickname, Math.Min(6000, settings.ConnectTimeoutMs), proxy, out message);
                Report.Verdict = verdict;
                Report.VerdictMessage = message;
                StepState state = verdict == LoginVerdict.OnlineMode ? StepState.Warn
                    : verdict == LoginVerdict.Failed ? StepState.Warn : StepState.Done;
                Step("آزمایش ورود به سرور", "Server login test", state, message, (int)watch.ElapsedMilliseconds);
                if (verdict == LoginVerdict.OnlineMode)
                    Report.Warnings.Add(L.T("این سرور پریمیوم است؛ لانچ آفلاین جواب نمی‌دهد.", "this server is premium-only; offline launching will not work."));
            }

            // ---------------------------------------------------------- 8. launch
            watch.Restart();
            Notify(L.T("آماده‌سازی اجرای بازی…", "Preparing the launch…"));
            string buildError;
            var extraJvmArgs = new List<string>();
            if (Report.ProxyOnlyMode && Report.ProxyPort > 0)
            {
                // Without a TUN interface the game has to be pointed at the local SOCKS port.
                extraJvmArgs.Add("-DsocksProxyHost=127.0.0.1");
                extraJvmArgs.Add("-DsocksProxyPort=" + Report.ProxyPort);
                extraJvmArgs.Add("-Djava.net.preferIPv4Stack=true");
            }
            LaunchPlan plan = LaunchBuilder.Build(version, javaPath, gameDir, settings.Nickname, server, settings, settings.QuickPlay, extraJvmArgs, out buildError);
            if (plan == null)
            {
                Step("ساخت فرمان اجرا", "Build launch command", StepState.Fail, buildError, (int)watch.ElapsedMilliseconds);
                Report.Error = buildError;
                return;
            }
            string detail = L.N(plan.Classpath.Split(';').Length) + L.T(" کتابخانه", " libraries");
            if (plan.Profile != null && plan.Profile.HeapMb > 0)
                detail += " • " + plan.Profile.Loader + " • " + plan.Profile.HeapMb + " MB" +
                          (plan.Profile.G1 ? " • G1GC" : " • CMS");
            if (plan.MissingLibraries > 0) detail += " • " + L.N(plan.MissingLibraries) + L.T(" فایل جاافتاده", " missing files");
            foreach (string note in plan.Notes) detail += " • " + note;
            Step("ساخت فرمان اجرا", "Build launch command", plan.MissingLibraries > 0 ? StepState.Warn : StepState.Done,
                detail, (int)watch.ElapsedMilliseconds);

            if (_cancel) return;
            watch.Restart();
            string startError;
            if (!Game.Start(plan, out startError))
            {
                Step("اجرای بازی", "Start the game", StepState.Fail, startError, (int)watch.ElapsedMilliseconds);
                Report.Error = startError;
                return;
            }
            Report.GamePid = Game.Pid;
            if (Report.ProxyOnlyMode && Report.ProxyPort > 0)
                plan.Notes.Add(L.T("بازی از پورت SOCKS محلی استفاده می‌کند", "the game uses the local SOCKS port"));
            StartLeakGuard(settings, _routedIps);
            Thread.Sleep(600);
            if (settings.SetJavaPriority && Game.Pid > 0)
                ProcessTuner.SetPriorityById(Game.Pid, ProcessPriorityClass.AboveNormal);
            Step("اجرای بازی", "Start the game", StepState.Done,
                "pid " + Game.Pid + L.T(" • اولویت بالا", " • high priority"), (int)watch.ElapsedMilliseconds);

            if (Report.TunnelUp)
            {
                var tunnelStep = new PipelineStep();
                tunnelStep.TitleFa = "وضعیت نهایی";
                tunnelStep.TitleEn = "Final state";
                tunnelStep.State = StepState.Done;
                tunnelStep.Detail = L.T("بازی از داخل تونل اجرا شد • ", "running through the tunnel • ") +
                                    L.N(Report.TunnelPing) + L.T(" میلی‌ثانیه", " ms") +
                                    (string.IsNullOrEmpty(Report.EndpointUsed) ? "" : " • " + Report.EndpointUsed);
                Emit(tunnelStep);
            }
        }

        private bool PrepareTunnel(AppSettings settings, ServerProfile server, List<string> serverIps)
        {
            var watch = Stopwatch.StartNew();
            Notify(L.T("برپاسازی تونل Cloudflare WARP…", "Setting up the Cloudflare WARP tunnel…"));

            string error;
            if (!Tunnel.EnsureBinaries(true, Notify, out error))
            {
                Step("آماده‌سازی موتور تونل", "Prepare tunnel engine", StepState.Fail, error, (int)watch.ElapsedMilliseconds);
                return false;
            }

            // 1. scan for the fastest reachable anycast addresses
            watch.Restart();
            int probeTimeout = Math.Min(settings.ScanTimeoutMs, 2500);
            var scan = EndpointScanner.Scan(probeTimeout, null, Notify);
            var best = WarpEndpoints.PickBest(scan.Endpoints, Math.Max(2, settings.MaxEndpoints));
            var withPorts = EndpointScanner.WithPortVariants(best, 2);
            Step("اسکن سرورهای WARP", "Scan WARP endpoints", scan.Reachable > 0 ? StepState.Done : StepState.Warn,
                L.N(scan.Reachable) + L.T(" از ", " of ") + L.N(scan.Probed) + L.T(" آدرس پاسخ داد • ", " addresses answered • ") +
                L.N(scan.ElapsedMs / 1000.0, 1) + L.T("s", "s") + " • " + L.T("بهترین: ", "best: ") +
                (best.Count > 0 ? best[0].Address + " (" + best[0].Score + "ms)" : "-"),
                (int)scan.ElapsedMs);

            if (_cancel) return false;

            // 2. WARP identity: cached or freshly registered
            watch.Restart();
            WarpCredentials credentials = WarpAccount.Load();
            if (credentials == null)
            {
                Notify(L.T("ساخت حساب WARP…", "Creating a WARP account…"));
                string priv, pub;
                string keyError;
                if (!Tunnel.GenerateKeyPair(out priv, out pub, out keyError))
                {
                    Step("حساب WARP", "WARP account", StepState.Fail, keyError, (int)watch.ElapsedMilliseconds);
                    return false;
                }
                credentials = WarpAccount.Register(priv, pub, out error);
                if (credentials == null)
                {
                    Step("حساب WARP", "WARP account", StepState.Fail, error, (int)watch.ElapsedMilliseconds);
                    return false;
                }
            }
            Step("حساب WARP", "WARP account", StepState.Done, credentials.Summary, (int)watch.ElapsedMilliseconds);

            // 3. configuration, validated by sing-box itself before it runs
            watch.Restart();
            ClashSecret = Guid.NewGuid().ToString("N").Substring(0, 16);
            var plan = new TunnelPlan();
            plan.Credentials = credentials;
            plan.Endpoints = withPorts;
            plan.ServerIps = new List<string>();
            foreach (string ip in serverIps)
            {
                IPAddress parsed;
                if (IPAddress.TryParse(ip, out parsed) && parsed.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                    plan.ServerIps.Add(ip);
            }
            plan.SocksPort = SocksPort;
            plan.ClashController = "127.0.0.1:" + ClashPort;
            plan.ClashSecret = ClashSecret;
            _tunName = plan.TunName;

            string json = SingBoxConfig.Build(plan);
            System.IO.File.WriteAllText(AppPaths.SingBoxConfig, json, new System.Text.UTF8Encoding(false));
            string checkOutput;
            bool includeTun = true;
            if (!Tunnel.Check(AppPaths.SingBoxConfig, out checkOutput))
            {
                // retry without the TUN interface: a missing driver should not kill the session
                includeTun = false;
                plan.IncludeTun = false;
                json = SingBoxConfig.Build(plan);
                System.IO.File.WriteAllText(AppPaths.SingBoxConfig, json, new System.Text.UTF8Encoding(false));
                if (!Tunnel.Check(AppPaths.SingBoxConfig, out checkOutput))
                {
                    Step("ساخت کانفیگ تونل", "Build tunnel config", StepState.Fail, checkOutput, (int)watch.ElapsedMilliseconds);
                    return false;
                }
            }
            Step("ساخت کانفیگ تونل", "Build tunnel config", StepState.Done,
                L.N(plan.Endpoints.Count) + L.T(" سرور WARP", " WARP endpoints") +
                (includeTun ? "" : L.T(" • بدون TUN (فقط پروکسی)", " • no TUN (proxy only)")), (int)watch.ElapsedMilliseconds);

            // 4. run it
            watch.Restart();
            if (!Tunnel.Start(AppPaths.SingBoxConfig, out error))
            {
                Step("اجرای تونل", "Start the tunnel", StepState.Fail, error, (int)watch.ElapsedMilliseconds);
                return false;
            }
            Step("اجرای تونل", "Start the tunnel", StepState.Done, "pid " + Tunnel.Pid, (int)watch.ElapsedMilliseconds);

            // 5. wait for the interface (and make sure the route really is there)
            if (includeTun)
            {
                watch.Restart();
                int index = -1;
                for (int i = 0; i < 20 && index <= 0 && !_cancel; i++)
                {
                    Thread.Sleep(300);
                    index = RouteTable.InterfaceIndex(_tunName);
                }
                if (index > 0)
                {
                    string tunAddress = "172.19.19.1";
                    bool allRouted = true;
                    foreach (string ip in plan.ServerIps)
                    {
                        if (!RouteTable.HasHostRoute(ip))
                        {
                            string routeError;
                            if (!RouteTable.AddHostRoute(ip, tunAddress, index, out routeError)) allRouted = false;
                            else _routesAdded.Add(ip);
                        }
                    }
                    Step("مسیر شبکه تونل", "Tunnel route", allRouted ? StepState.Done : StepState.Warn,
                        L.T("اینترفیس ", "interface ") + _tunName + " #" + index + L.T(" • فقط ترافیک سرور از تونل می‌رود",
                        " • only the server traffic is tunnelled"), (int)watch.ElapsedMilliseconds);
                }
                else
                {
                    Step("مسیر شبکه تونل", "Tunnel route", StepState.Warn,
                        L.T("اینترفیس TUN بالا نیامد (درایور wintun؟)", "the TUN interface did not appear (wintun driver?)"), (int)watch.ElapsedMilliseconds);
                }
            }

            // 6. verify: the real game path through the tunnel
            watch.Restart();
            var proxy = new Socks5Client("127.0.0.1", SocksPort, 6000);
            McStatus throughTunnel = null;
            foreach (string ip in plan.ServerIps)
            {
                if (_cancel) break;
                throughTunnel = McPing.Status(ip, server.Port, 6000, proxy);
                if (throughTunnel != null && throughTunnel.Ok) { Report.ChosenIp = ip; break; }
                Thread.Sleep(250);
            }
            if (throughTunnel != null && throughTunnel.Ok)
            {
                Report.TunnelUp = true;
                Report.TunnelPing = throughTunnel.LatencyMs;
                Report.Strategy = "warp";
                Report.ConnectionUsed = L.T("تونل WARP کلادفلر", "Cloudflare WARP tunnel");
                Report.ConnectionKind = ConnectionKindInfo.Of(ConnectionKind.Warp).Title;
                Report.ConnectionDelayMs = throughTunnel.LatencyMs;
                foreach (string ip in plan.ServerIps) AddUnique(_routedIps, ip);
                string selected = ClashApi.Selected("127.0.0.1:" + ClashPort, ClashSecret,
                                                    string.IsNullOrEmpty(plan.ResolvedTag) ? plan.GroupTag : plan.ResolvedTag);
                Report.EndpointUsed = string.IsNullOrEmpty(selected) ? "" : selected;
                Step("تأیید تونل با پینگ واقعی بازی", "Verify the tunnel on the real game path", StepState.Done,
                    L.N(throughTunnel.LatencyMs) + L.T(" میلی‌ثانیه", " ms") +
                    (string.IsNullOrEmpty(selected) ? "" : " • " + selected) +
                    (string.IsNullOrEmpty(throughTunnel.Motd) ? "" : " • " + throughTunnel.Motd),
                    (int)watch.ElapsedMilliseconds);
                TrackEndpointDelays();
                return true;
            }

            string reason = throughTunnel != null ? throughTunnel.Error : "no answer";
            Step("تأیید تونل با پینگ واقعی بازی", "Verify the tunnel on the real game path", StepState.Fail, reason, (int)watch.ElapsedMilliseconds);
            Tunnel.Stop();
            return false;
        }

        /// <summary>Asks the Clash API for per endpoint latency; the numbers land in the log/UI.</summary>
        private void TrackEndpointDelays()
        {
            try
            {
                var thread = new Thread(delegate ()
                {
                    string controller = "127.0.0.1:" + ClashPort;
                    var names = ClashApi.Names(controller, ClashSecret);
                    foreach (string name in names)
                    {
                        if (!name.StartsWith("warp-", StringComparison.Ordinal)) continue;
                        int delay = ClashApi.Delay(controller, ClashSecret, name, "https://cp.cloudflare.com/generate_204", 3000);
                        if (delay > 0) Log.Info("endpoint " + name + " → " + delay + " ms");
                    }
                });
                thread.IsBackground = true;
                thread.Start();
            }
            catch { }
        }

        // ------------------------------------------------------------------ connections

        private sealed class SelectedRoute
        {
            public ConnectionEntry Entry;
            public int DelayMs = -1;
            public string Label = "";
        }

        /// <summary>Enabled entries the run may use; a pinned name narrows it down to that one.</summary>
        private List<ConnectionEntry> ConnectionCandidates(AppSettings settings, out string pinnedName)
        {
            var list = new List<ConnectionEntry>();
            pinnedName = settings.PinnedConnection == null ? "" : settings.PinnedConnection.Trim();
            foreach (ConnectionEntry entry in settings.Connections)
            {
                if (!entry.Enabled) continue;
                if (pinnedName.Length == 0)
                {
                    // In automatic mode an entry counts when it can carry the game or resolve
                    // names; Telegram proxies are measured in the Connections tab only.
                    if (!entry.UseForGame && !entry.Info.IsResolver) continue;
                }
                else if (!Matches(entry, pinnedName)) continue;
                list.Add(entry);
            }
            return list;
        }

        private static bool Matches(ConnectionEntry entry, string name)
        {
            return string.Equals(entry.Name, name, StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(entry.Id, name, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Picks the route for this run: a pinned entry when the user chose one, otherwise the
        /// fastest entry that answers, with a working DNS server collected on the way.
        /// </summary>
        private SelectedRoute SelectRoute(AppSettings settings, ServerProfile server, List<ConnectionEntry> candidates,
                                          string pinnedName, int timeoutMs)
        {
            var watch = Stopwatch.StartNew();
            Notify(L.T("تست اتصالات…", "Testing the connections…"));

            var results = new System.Collections.Concurrent.ConcurrentDictionary<string, ConnectionTestResult>();
            var jobs = new List<Action>();
            foreach (ConnectionEntry entry in candidates)
            {
                ConnectionEntry local = entry;
                // WARP and the started route kinds are not probed here: they are brought up when the
                // launch actually needs them, which keeps the one minute budget intact.
                if (local.Kind == ConnectionKind.Warp && pinnedName.Length == 0) continue;
                bool quick = local.Kind == ConnectionKind.Warp || local.Kind == ConnectionKind.WireGuard ||
                             local.Kind == ConnectionKind.SingBoxOutbound || local.Kind == ConnectionKind.SingBoxConfig;
                jobs.Add(delegate
                {
                    ConnectionTestResult result = ConnectionTester.Test(local, server.Host, server.Port, timeoutMs, quick);
                    results[local.Id] = result;
                });
            }
            if (jobs.Count > 0) NetUtil.RunParallel(jobs, 8, timeoutMs + 2500);

            SelectedRoute best = null;
            ConnectionEntry bestResolver = null;
            int bestResolverDelay = int.MaxValue;
            foreach (ConnectionEntry entry in candidates)
            {
                ConnectionTestResult result;
                if (!results.TryGetValue(entry.Id, out result))
                {
                    if (entry.Kind == ConnectionKind.Warp)
                        Report.Candidates.Add(entry.Name + " [" + entry.Info.Title + "] — " +
                                              (pinnedName.Length > 0 ? L.T("انتخاب‌شده", "pinned") : L.T("مسیر پیش‌فرض خودکار", "automatic fallback")));
                    continue;
                }
                if (result.Ok) { entry.LastDelayMs = result.DelayMs; entry.LastStatus = result.Status; }
                else { entry.LastStatus = result.Status; entry.LastError = result.Detail; }
                string line = entry.Name + " [" + entry.Info.Title + "] — " +
                              (result.Ok ? L.T("کار کرد", "works") : L.T("کار نکرد", "failed")) +
                              (result.DelayMs > 0 ? " • " + result.DelayMs + " ms" : "") +
                              (string.IsNullOrEmpty(result.Detail) ? "" : " • " + result.Detail);
                Report.Candidates.Add(line);
                Log.Info("connection test: " + line);

                if (!result.Ok) continue;
                if (entry.Info.IsResolver)
                {
                    if (result.DelayMs > 0 && result.DelayMs < bestResolverDelay)
                    {
                        bestResolverDelay = result.DelayMs;
                        bestResolver = entry;
                    }
                    continue;
                }
                if (!result.CanCarryGame || !entry.CanCarryGame) continue;
                if (best == null || (result.DelayMs > 0 && result.DelayMs < best.DelayMs))
                {
                    best = new SelectedRoute();
                    best.Entry = entry;
                    best.DelayMs = result.DelayMs;
                    best.Label = entry.Name + " • " + result.DelayMs + " ms";
                }
            }

            if (bestResolver != null) _dnsEntry = bestResolver;

            if (pinnedName.Length > 0)
            {
                // The user asked for one specific connection: it is used whenever it answered,
                // even when it is not the fastest.
                ConnectionEntry pinned = null;
                foreach (ConnectionEntry entry in candidates) if (Matches(entry, pinnedName)) { pinned = entry; break; }
                if (pinned == null)
                {
                    Step(L.T("اتصال انتخابی", "Chosen connection"), L.T("اتصال انتخابی", "Chosen connection"),
                        StepState.Warn, L.T("پیدا نشد: ", "not found: ") + pinnedName, (int)watch.ElapsedMilliseconds);
                    return null;
                }
                ConnectionTestResult pinnedResult;
                bool known = results.TryGetValue(pinned.Id, out pinnedResult);
                if (known && !pinnedResult.Ok && !settings.AllowRouteFallback)
                {
                    Step(L.T("اتصال انتخابی", "Chosen connection"), L.T("اتصال انتخابی", "Chosen connection"),
                        StepState.Warn, L.T("پاسخ نداد ولی طبق تنظیمات استفاده می‌شود: ", "did not answer, but it is used as configured: ") +
                        pinnedResult.Detail, (int)watch.ElapsedMilliseconds);
                }
                else if (known && !pinnedResult.Ok)
                {
                    Step(L.T("اتصال انتخابی", "Chosen connection"), L.T("اتصال انتخابی", "Chosen connection"),
                        StepState.Warn, pinnedResult.Status + " • " + pinnedResult.Detail, (int)watch.ElapsedMilliseconds);
                    return null;
                }
                var chosen = new SelectedRoute();
                chosen.Entry = pinned;
                chosen.DelayMs = known ? pinnedResult.DelayMs : -1;
                chosen.Label = pinned.Name + (chosen.DelayMs > 0 ? " • " + chosen.DelayMs + " ms" : "");
                Step(L.T("اتصال انتخابی", "Chosen connection"), L.T("اتصال انتخابی", "Chosen connection"),
                    StepState.Done, chosen.Label + " • " + pinned.Info.Title, (int)watch.ElapsedMilliseconds);
                return chosen;
            }

            if (best != null)
            {
                Step(L.T("بهترین اتصال", "Best connection"), L.T("بهترین اتصال", "Best connection"), StepState.Done,
                    best.Label + " • " + best.Entry.Info.Title, (int)watch.ElapsedMilliseconds);
            }
            else
            {
                Report.Candidates.Add(L.T("هیچ اتصال آماده‌ای جواب نداد؛ مسیر WARP خودکار امتحان می‌شود.",
                                          "no ready connection answered; the automatic WARP route is tried."));
            }
            return best;
        }

        /// <summary>Brings a user connection up in front of the game (proxy, WireGuard or pasted config).</summary>
        private bool PrepareProxyRoute(AppSettings settings, ServerProfile server, List<string> serverIps)
        {
            var watch = Stopwatch.StartNew();
            SelectedRoute route = _selectedRoute;
            if (route == null || route.Entry == null) return false;
            ConnectionEntry entry = route.Entry;
            Notify(L.T("برپاسازی مسیر انتخابی…", "Bringing the chosen route up…"));

            string error;
            if (!Tunnel.EnsureBinaries(true, Notify, out error))
            {
                Step(L.T("آماده‌سازی موتور تونل", "Prepare tunnel engine"), L.T("آماده‌سازی موتور تونل", "Prepare tunnel engine"),
                    StepState.Fail, error, (int)watch.ElapsedMilliseconds);
                return false;
            }

            // ---- 1. a complete config the user pasted: it is used exactly as it is
            if (entry.Kind == ConnectionKind.SingBoxConfig)
            {
                watch.Restart();
                string configPath = AppPaths.SingBoxConfig;
                System.IO.File.WriteAllText(configPath, entry.Config, new System.Text.UTF8Encoding(false));
                string output;
                if (!Tunnel.Check(configPath, out output))
                {
                    Step(L.T("کانفیگ ارسالی", "The pasted config"), L.T("کانفیگ ارسالی", "The pasted config"),
                        StepState.Fail, output, (int)watch.ElapsedMilliseconds);
                    return false;
                }
                if (!Tunnel.Start(configPath, out error))
                {
                    Step(L.T("اجرای کانفیگ", "Run the config"), L.T("اجرای کانفیگ", "Run the config"),
                        StepState.Fail, error, (int)watch.ElapsedMilliseconds);
                    return false;
                }
                int socksPort = entry.LocalSocksPort > 0 ? entry.LocalSocksPort : ConnectionParser.FindSocksPort(Json.ParseObject(entry.Config));
                if (socksPort <= 0)
                {
                    Step(L.T("اجرای کانفیگ", "Run the config"), L.T("اجرای کانفیگ", "Run the config"), StepState.Fail,
                        L.T("این کانفیگ inbound لوکال (socks/mixed) ندارد، پس بازی نمی‌تواند از آن عبور کند.",
                            "this config has no local socks/mixed inbound, so the game cannot go through it."),
                        (int)watch.ElapsedMilliseconds);
                    Tunnel.Stop();
                    return false;
                }
                Report.TunnelUp = true;
                Report.ProxyOnlyMode = true;
                Report.ProxyPort = socksPort;
                Report.ConnectionUsed = entry.Name;
                Report.ConnectionKind = entry.Info.Title;
                Report.ConnectionDelayMs = 0;
                TrackEndpointDelays();
                Step(L.T("کانفیگ دستی بالا آمد", "The pasted config is up"), L.T("کانفیگ دستی بالا آمد", "The pasted config is up"),
                    StepState.Done, entry.Name + " • socks 127.0.0.1:" + socksPort, (int)watch.ElapsedMilliseconds);
                return true;
            }

            // ---- 2. our own instrumented config: the chosen outbound in front of the game
            watch.Restart();
            var ips = new List<string>();
            foreach (string ip in serverIps)
            {
                IPAddress parsed;
                if (IPAddress.TryParse(ip, out parsed) && parsed.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                    ips.Add(ip);
            }
            if (ips.Count == 0)
            {
                Step(L.T("آدرس سرور بازی", "Game server address"), L.T("آدرس سرور بازی", "Game server address"), StepState.Fail,
                    L.T("آدرس IPv4 سرور پیدا نشد؛ مسیر پروکسی ممکن نیست.", "no IPv4 address for the server was found; a proxy route is not possible."),
                    (int)watch.ElapsedMilliseconds);
                return false;
            }

            ClashSecret = Guid.NewGuid().ToString("N").Substring(0, 16);
            var plan = new TunnelPlan();
            plan.ServerIps = ips;
            plan.SocksPort = SocksPort;
            plan.ClashController = "127.0.0.1:" + ClashPort;
            plan.ClashSecret = ClashSecret;
            plan.LogPath = AppPaths.SingBoxLog;

            string primaryTag;
            try
            {
                primaryTag = ConnectionRoute.TagFor(entry);
                if (entry.Kind == ConnectionKind.WireGuard)
                    plan.ExtraEndpoints.Add(ConnectionRoute.BuildEndpoint(entry, primaryTag));
                else
                    plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(entry, primaryTag));
            }
            catch (Exception ex)
            {
                Step(L.T("کانفیگ اتصال", "Connection config"), L.T("کانفیگ اتصال", "Connection config"), StepState.Fail,
                    ex.Message, (int)watch.ElapsedMilliseconds);
                return false;
            }
            plan.MemberTags.Add(primaryTag);

            // Every other working proxy joins as a failover member: sing-box itself then keeps the
            // fastest one and switches when one dies.
            if (settings.ProxyFailover)
            {
                int added = 1;
                foreach (string line in Report.Candidates)
                {
                    if (added >= 4) break;
                    foreach (ConnectionEntry other in settings.Connections)
                    {
                        if (added >= 4) break;
                        if (other == entry || !other.Enabled || !other.CanCarryGame) continue;
                        if (!line.StartsWith(other.Name + " [", StringComparison.Ordinal)) continue;
                        if (line.IndexOf(L.T("کار کرد", "works"), StringComparison.Ordinal) < 0) continue;
                        if (other.Kind != ConnectionKind.Socks5 && other.Kind != ConnectionKind.Http) continue;
                        string tag = ConnectionRoute.TagFor(other);
                        try
                        {
                            plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(other, tag));
                            plan.MemberTags.Add(tag);
                            added++;
                        }
                        catch { }
                        break;
                    }
                }
            }
            plan.BuildUrlTest = plan.MemberTags.Count > 1;
            plan.RouteTag = primaryTag;   // the picked route wins; the group only carries the extras

            string json = SingBoxConfig.Build(plan);
            if (plan.MemberTags.Count > 1)
            {
                // With several members the traffic goes through the automatic group so a dead proxy
                // cannot take the session down.
                plan.RouteTag = "";
                json = SingBoxConfig.Build(plan);
            }

            bool includeTun = true;
            System.IO.File.WriteAllText(AppPaths.SingBoxConfig, json, new System.Text.UTF8Encoding(false));
            string checkOutput;
            if (!Tunnel.Check(AppPaths.SingBoxConfig, out checkOutput))
            {
                includeTun = false;
                plan.IncludeTun = false;
                plan.RouteTag = plan.MemberTags.Count > 1 ? "" : primaryTag;
                json = SingBoxConfig.Build(plan);
                System.IO.File.WriteAllText(AppPaths.SingBoxConfig, json, new System.Text.UTF8Encoding(false));
                if (!Tunnel.Check(AppPaths.SingBoxConfig, out checkOutput))
                {
                    Step(L.T("ساخت کانفیگ مسیر", "Build the route config"), L.T("ساخت کانفیگ مسیر", "Build the route config"),
                        StepState.Fail, checkOutput, (int)watch.ElapsedMilliseconds);
                    return false;
                }
            }
            Step(L.T("ساخت کانفیگ مسیر", "Build the route config"), L.T("ساخت کانفیگ مسیر", "Build the route config"),
                StepState.Done, entry.Name + (includeTun ? "" : L.T(" • بدون TUN (فقط پروکسی)", " • no TUN (proxy only)")),
                (int)watch.ElapsedMilliseconds);

            watch.Restart();
            if (!Tunnel.Start(AppPaths.SingBoxConfig, out error))
            {
                Step(L.T("اجرای مسیر", "Start the route"), L.T("اجرای مسیر", "Start the route"), StepState.Fail,
                    error, (int)watch.ElapsedMilliseconds);
                return false;
            }
            Step(L.T("اجرای مسیر", "Start the route"), L.T("اجرای مسیر", "Start the route"), StepState.Done,
                "pid " + Tunnel.Pid, (int)watch.ElapsedMilliseconds);

            // ---- 3. the route has to carry the real game traffic, not just open a port
            watch.Restart();
            var proxy = new Socks5Client("127.0.0.1", SocksPort, Math.Min(6000, settings.ConnectTimeoutMs));
            McStatus through = null;
            foreach (string ip in ips)
            {
                if (_cancel) break;
                through = McPing.Status(ip, server.Port, Math.Min(6000, settings.ConnectTimeoutMs), proxy);
                if (through != null && through.Ok) { Report.ChosenIp = ip; break; }
                Thread.Sleep(200);
            }

            bool tcpPath = false;
            if (through == null || !through.Ok)
            {
                foreach (string ip in ips)
                {
                    try
                    {
                        using (System.Net.Sockets.Socket socket = proxy.Connect(ip, server.Port)) socket.Close();
                        tcpPath = true;
                        Report.ChosenIp = ip;
                        break;
                    }
                    catch { }
                }
            }

            if (through != null && through.Ok)
            {
                Report.TunnelUp = true;
                Report.TunnelPing = through.LatencyMs;
                Report.ConnectionDelayMs = through.LatencyMs;
            }
            else if (tcpPath)
            {
                Report.TunnelUp = true;
                Report.TunnelPing = -1;
                Report.ConnectionDelayMs = -1;
                Report.Warnings.Add(L.T("سرور به پینگ Minecraft از این مسیر جواب نداد، ولی اتصال TCP برقرار است.",
                                        "the server did not answer the Minecraft ping through this route, but the TCP connection works."));
            }
            else
            {
                Step(L.T("تأیید مسیر", "Verify the route"), L.T("تأیید مسیر", "Verify the route"), StepState.Fail,
                    through != null ? through.Error : L.T("سرور از این مسیر پاسخ نداد", "the server did not answer through this route"),
                    (int)watch.ElapsedMilliseconds);
                Tunnel.Stop();
                return false;
            }

            Report.ConnectionUsed = entry.Name;
            Report.ConnectionKind = entry.Info.Title;
            Report.ProxyOnlyMode = !includeTun;
            Report.ProxyPort = includeTun ? 0 : SocksPort;
            foreach (string ip in ips) AddUnique(_routedIps, ip);

            // ---- 4. the routes that make the split tunnel work
            if (includeTun)
            {
                watch.Restart();
                int index = -1;
                for (int i = 0; i < 20 && index <= 0 && !_cancel; i++)
                {
                    Thread.Sleep(300);
                    index = RouteTable.InterfaceIndex(plan.TunName);
                }
                bool allRouted = index > 0;
                if (index > 0)
                {
                    foreach (string ip in ips)
                    {
                        if (RouteTable.HasHostRoute(ip)) continue;
                        string routeError;
                        if (RouteTable.AddHostRoute(ip, plan.TunAddress.Split('/')[0], index, out routeError)) _routesAdded.Add(ip);
                        else allRouted = false;
                    }
                }
                Step(L.T("مسیر شبکه", "Network route"), L.T("مسیر شبکه", "Network route"),
                    allRouted ? StepState.Done : StepState.Warn,
                    index > 0
                        ? L.T("اینترفیس ", "interface ") + plan.TunName + " #" + index + L.T(" • فقط ترافیک سرور از این مسیر می‌رود",
                                                                                            " • only the server traffic uses this route")
                        : L.T("اینترفیس TUN بالا نیامد؛ بازی با پروکسی محلی اجرا می‌شود",
                              "the TUN interface did not appear; the game will use the local proxy"),
                    (int)watch.ElapsedMilliseconds);
            }

            TrackEndpointDelays();
            Step(L.T("مسیر انتخابی آماده است", "The chosen route is ready"), L.T("مسیر انتخابی آماده است", "The chosen route is ready"), StepState.Done,
                entry.Name + " • " + entry.Info.Title + (Report.TunnelPing > 0 ? " • " + Report.TunnelPing + " ms" : ""),
                (int)watch.ElapsedMilliseconds);
            return true;
        }

        /// <summary>
        /// Watches the route while the game plays. When the tunnel dies and the kill switch is on,
        /// the server addresses are blackholed and the game is closed so nothing leaks.
        /// </summary>
        private void StartLeakGuard(AppSettings settings, List<string> serverIps)
        {
            if (!KillSwitch)
            {
                Report.LeakGuardNote = L.T("خاموش (در تنظیمات روشن کنید)", "off (enable it in Settings)");
                return;
            }
            if (!Report.TunnelUp) return;

            var ips = new List<string>();
            foreach (string ip in serverIps) if (!string.IsNullOrEmpty(ip)) ips.Add(ip);
            bool watchRoutes = !Report.ProxyOnlyMode && ips.Count > 0;
            _leakStopped = false;

            var thread = new Thread(delegate ()
            {
                Log.Info("leak guard armed (routes=" + watchRoutes + ", ips=" + ips.Count + ")");
                while (!_leakStopped && Game.IsRunning)
                {
                    Thread.Sleep(2000);
                    if (_leakStopped) break;
                    bool dead = !Tunnel.IsRunning;
                    if (!dead && watchRoutes)
                    {
                        foreach (string ip in ips) if (!RouteTable.HasHostRoute(ip)) { dead = true; break; }
                    }
                    if (!dead) continue;

                    Log.Warn("leak guard: the route died while the game is running");
                    Report.Warnings.Add(L.T("مسیر تونل قطع شد؛ برای جلوگیری از لو رفتن IP، بازی بسته می‌شود.",
                                            "the tunnel died; the game is being closed to avoid leaking your address."));
                    Report.LeakGuardNote = L.T("فعال شد: مسیر قطع شد و بازی بسته شد", "triggered: the route died and the game was closed");
                    foreach (string ip in ips)
                    {
                        string error;
                        if (RouteTable.AddBlackhole(ip, out error)) _blackholes.Add(ip);
                        else Log.Warn("blackhole failed for " + ip + ": " + error);
                    }
                    try { Game.Kill(); } catch (Exception ex) { Log.Warn("leak guard kill: " + ex.Message); }
                    break;
                }
            });
            thread.IsBackground = true;
            thread.Start();
            Report.LeakGuardArmed = true;
            Report.LeakGuardNote = watchRoutes
                ? L.T("فعال: مسیرها و پروسه تونل پایش می‌شوند", "armed: routes and the tunnel process are watched")
                : L.T("فعال: پروسه تونل پایش می‌شود", "armed: the tunnel process is watched");
        }

        // ------------------------------------------------------------------ helpers

        private void Step(string fa, string en, StepState state, string detail, int ms)
        {
            var step = new PipelineStep();
            step.TitleFa = fa;
            step.TitleEn = en;
            step.State = state;
            step.Detail = detail ?? "";
            step.ElapsedMs = ms;
            Emit(step);
        }

        private void Emit(PipelineStep step)
        {
            Log.Info("step: " + step.ToString());
            Action<PipelineStep> handler = StepChanged;
            if (handler != null) { try { handler(step); } catch { } }
        }

        private void Notify(string text)
        {
            Action<string> handler = Progress;
            if (handler != null) { try { handler(text); } catch { } }
        }

        private static void AddUnique(List<string> list, string value)
        {
            if (string.IsNullOrEmpty(value)) return;
            foreach (string existing in list) if (existing == value) return;
            list.Add(value);
        }

        // ------------------------------------------------------------------ teardown

        /// <summary>Removes every trace of this session, optionally leaving the tunnel up.</summary>
        public void Shutdown(bool keepTunnel)
        {
            _leakStopped = true;
            try
            {
                if (!keepTunnel) Tunnel.Stop();
            }
            catch (Exception ex) { Log.Warn("tunnel shutdown: " + ex.Message); }

            // A black hole left behind would cut the user off from the server, so it is removed
            // before anything else.
            foreach (string ip in _blackholes) RouteTable.DeleteHostRoute(ip);
            _blackholes.Clear();
            foreach (string ip in _routesAdded) RouteTable.DeleteHostRoute(ip);
            _routesAdded.Clear();
            _routedIps.Clear();
            if (_hostsNames.Count > 0) HostsFile.Remove();
            _hostsNames.Clear();
            Optimizer.Restore(delegate (string message) { Log.Info(message); });
        }
    }
}

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
        public string Strategy = "";          // direct | warp | dns | none
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

        private volatile bool _cancel;
        private readonly List<string> _hostsNames = new List<string>();
        private readonly List<string> _routesAdded = new List<string>();
        private string _tunName = "ServerHelp";

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
            _cancel = false;
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
                bool tunnelOk = PrepareTunnel(settings, server, candidates);
                if (!tunnelOk && strategy == "warp")
                {
                    strategy = "dns";
                    Report.Warnings.Add(L.T("تونل برپا نشد؛ به حالت DNS/هاست سوییچ شد.", "the tunnel could not be established, falling back to DNS/hosts mode."));
                }
            }

            // ---------------------------------------------------------- 6. name resolution fix
            if (settings.UseHostsFile && settings.Tunnel != TunnelMode.Off && !_cancel)
            {
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
            LaunchPlan plan = LaunchBuilder.Build(version, javaPath, gameDir, settings.Nickname, server, settings, settings.QuickPlay, out buildError);
            if (plan == null)
            {
                Step("ساخت فرمان اجرا", "Build launch command", StepState.Fail, buildError, (int)watch.ElapsedMilliseconds);
                Report.Error = buildError;
                return;
            }
            string detail = L.N(plan.Classpath.Split(';').Length) + L.T(" کتابخانه", " libraries");
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
                string selected = ClashApi.Selected("127.0.0.1:" + ClashPort, ClashSecret, "warp-auto");
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
            try
            {
                if (!keepTunnel) Tunnel.Stop();
            }
            catch (Exception ex) { Log.Warn("tunnel shutdown: " + ex.Message); }

            foreach (string ip in _routesAdded) RouteTable.DeleteHostRoute(ip);
            _routesAdded.Clear();
            if (_hostsNames.Count > 0) HostsFile.Remove();
            _hostsNames.Clear();
            Optimizer.Restore(delegate (string message) { Log.Info(message); });
        }
    }
}

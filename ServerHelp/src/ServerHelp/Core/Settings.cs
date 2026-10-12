using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace ServerHelp.Core
{
    public sealed class ServerProfile
    {
        public string Name = "SMP";
        public string Host = "smp3.mcsh.io";
        public int Port = 11005;
        /// <summary>Optional fixed address used when the domain cannot be resolved (bypass mode).</summary>
        public string DirectIp = "163.5.201.3";
        public bool PreferDomain = true;

        public string Endpoint
        {
            get { return Host + ":" + Port.ToString(System.Globalization.CultureInfo.InvariantCulture); }
        }

        public ServerProfile Clone()
        {
            return new ServerProfile
            {
                Name = this.Name,
                Host = this.Host,
                Port = this.Port,
                DirectIp = this.DirectIp,
                PreferDomain = this.PreferDomain
            };
        }

        public string Summary
        {
            get
            {
                if (PreferDomain || string.IsNullOrEmpty(DirectIp)) return Endpoint;
                return DirectIp + ":" + Port.ToString(System.Globalization.CultureInfo.InvariantCulture);
            }
        }
    }

    public enum TunnelMode
    {
        /// <summary>Diagnose first: no tunnel when direct play already works, DNS fix when only DNS is blocked.</summary>
        Auto = 0,
        /// <summary>Always bring the Cloudflare WARP tunnel up.</summary>
        Warp = 1,
        /// <summary>Never tunnel; only fix name resolution.</summary>
        DnsOnly = 2,
        /// <summary>Touch nothing network related.</summary>
        Off = 3
    }

    public sealed class AppSettings
    {
        public int Version = 1;
        public string Language = L.Fa;
        public string Nickname = "";
        public string VersionsDir = "";          // empty => auto detect
        public string GameDirOverride = "";      // empty => <mc dir>
        public string JavaPathOverride = "";

        public List<ServerProfile> Servers = new List<ServerProfile>();
        public string ActiveServer = "SMP";

        public TunnelMode Tunnel = TunnelMode.Auto;
        public bool UseHostsFile = true;
        public int MaxEndpoints = 10;            // WARP endpoints kept in the auto group
        public int ScanTimeoutMs = 3500;

        public bool OptimizeSystem = true;
        /// <summary>Opt-in on purpose: switching the Windows power plan changes a system wide
        /// setting, so the user has to ask for it explicitly.</summary>
        public bool HighPerformancePowerPlan = false;
        public bool TrimMemory = true;
        public bool CloseBackgroundApps = false;
        public bool SetJavaPriority = true;
        /// <summary>Multimedia/network throttling tweaks + DNS cache flush (all reversible).</summary>
        public bool TuneNetwork = true;
        public bool AddFirewallRules = true;
        public bool TimerResolution = true;

        public bool UseAikarFlags = true;
        public int MaxHeapMb = 0;                // 0 => automatic
        public string ExtraJvmArgs = "";
        public bool QuickPlay = true;             // join the server straight away
        public bool OpenGlPipeline = false;       // -Dsun.java2d.opengl=true for stubborn Intel drivers

        public bool AutoRestoreOnExit = true;
        public bool KeepTunnelAfterGame = false;
        public bool MinimizeWhilePlaying = true;
        public bool CloseAppWhenGameExits = false;

        public bool GaugesOnDashboard = true;
        public int ConnectTimeoutMs = 6000;
        /// <summary>Runs a real login to learn whether the server is premium-only.</summary>
        public bool LoginProbe = true;

        // ---- connections the user entered (proxies, DNS, VPN configs, pasted sing-box configs)
        public List<ConnectionEntry> Connections = new List<ConnectionEntry>();
        /// <summary>Name (or id) of the connection to use; empty means "pick the best one".</summary>
        public string PinnedConnection = "";
        /// <summary>Second hop of a pinned relay chain (empty = a single hop).</summary>
        public string PinnedChainHop = "";
        /// <summary>Send name lookups through the chosen route instead of the local DNS.</summary>
        public bool DnsThroughTunnel = true;
        /// <summary>How many two hop relay chains the route optimiser tries.</summary>
        public int OptimiseChains = 4;
        /// <summary>Fragment the TLS handshake of every route by default (SNI filtering).</summary>
        public bool FragmentTls = false;
        /// <summary>Re-measure the connections in the background every N minutes (0 = off).</summary>
        public int RetestMinutes = 0;
        /// <summary>When the chosen route fails, keep going with the automatic one.</summary>
        public bool AllowRouteFallback = true;
        /// <summary>Group every working proxy so sing-box itself fails over to the fastest one.</summary>
        public bool ProxyFailover = true;
        /// <summary>Close the game and blackhole the server when the tunnel dies mid session.</summary>
        public bool KillSwitch = false;
        public int ConnectionTestTimeoutMs = 3000;

        public ServerProfile GetActiveServer()
        {
            if (Servers.Count == 0) Servers.Add(DefaultServer());
            foreach (var s in Servers)
                if (string.Equals(s.Name, ActiveServer, StringComparison.OrdinalIgnoreCase)) return s;
            return Servers[0];
        }

        public static ServerProfile DefaultServer()
        {
            return new ServerProfile();
        }

        public AppSettings Clone()
        {
            var c = (AppSettings)MemberwiseClone();
            c.Servers = new List<ServerProfile>();
            foreach (var s in Servers) c.Servers.Add(s.Clone());
            c.Connections = new List<ConnectionEntry>();
            foreach (var entry in Connections) c.Connections.Add(entry.Clone());
            return c;
        }

        /// <summary>Every connection entry, for the UI.</summary>
        public ConnectionEntry FindConnection(string nameOrId)
        {
            if (string.IsNullOrEmpty(nameOrId)) return null;
            foreach (ConnectionEntry entry in Connections)
                if (string.Equals(entry.Name, nameOrId, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(entry.Id, nameOrId, StringComparison.OrdinalIgnoreCase)) return entry;
            return null;
        }

        public static AppSettings Default()
        {
            var s = new AppSettings();
            s.Servers.Add(DefaultServer());
            foreach (ConnectionEntry entry in DefaultConnections()) s.Connections.Add(entry);
            return s;
        }

        /// <summary>
        /// Ships with the automatic WARP tunnel and two secure resolvers as ready made entries, so
        /// the Connections tab explains itself and the DNS fallback is visible instead of hidden.
        /// </summary>
        public static List<ConnectionEntry> DefaultConnections()
        {
            var list = new List<ConnectionEntry>();

            var warp = ConnectionEntry.Create(L.T("تونل WARP کلادفلر (خودکار)", "Cloudflare WARP tunnel (automatic)"), ConnectionKind.Warp);
            warp.Notes = L.T("اسکن خودکار کم‌پینگ‌ترین آدرس کلادفلر و ساخت حساب WARP بدون ثبت‌نام.",
                             "Scans for the lowest ping Cloudflare address and creates a free WARP account.");
            list.Add(warp);

            var cloudflare = ConnectionEntry.Create("Cloudflare DNS", ConnectionKind.Dns);
            cloudflare.DnsUrl = "https://cloudflare-dns.com/dns-query";
            cloudflare.UseForGame = false;
            list.Add(cloudflare);

            var google = ConnectionEntry.Create("Google DNS", ConnectionKind.Dns);
            google.DnsUrl = "https://dns.google/resolve";
            google.UseForGame = false;
            list.Add(google);

            return list;
        }
    }

    public static class SettingsStore
    {
        public static AppSettings Load()
        {
            try
            {
                if (!File.Exists(AppPaths.SettingsFile)) return AppSettings.Default();
                string text = File.ReadAllText(AppPaths.SettingsFile, Encoding.UTF8);
                var d = Json.ParseObject(text);
                var s = AppSettings.Default();
                s.Servers.Clear();

                s.Version = Json.GetInt(d, "version", 1);
                s.Language = Json.GetStr(d, "language", s.Language);
                s.Nickname = Json.GetStr(d, "nickname", s.Nickname);
                s.VersionsDir = Json.GetStr(d, "versionsDir", s.VersionsDir);
                s.GameDirOverride = Json.GetStr(d, "gameDirOverride", s.GameDirOverride);
                s.JavaPathOverride = Json.GetStr(d, "javaPathOverride", s.JavaPathOverride);
                s.ActiveServer = Json.GetStr(d, "activeServer", s.ActiveServer);

                s.Tunnel = (TunnelMode)Json.GetInt(d, "tunnel", (int)s.Tunnel);
                s.UseHostsFile = Json.GetBool(d, "useHostsFile", s.UseHostsFile);
                s.MaxEndpoints = Clamp(Json.GetInt(d, "maxEndpoints", s.MaxEndpoints), 1, 24);
                s.ScanTimeoutMs = Clamp(Json.GetInt(d, "scanTimeoutMs", s.ScanTimeoutMs), 800, 20000);

                s.OptimizeSystem = Json.GetBool(d, "optimizeSystem", s.OptimizeSystem);
                s.HighPerformancePowerPlan = Json.GetBool(d, "highPerformancePowerPlan", s.HighPerformancePowerPlan);
                s.TrimMemory = Json.GetBool(d, "trimMemory", s.TrimMemory);
                s.CloseBackgroundApps = Json.GetBool(d, "closeBackgroundApps", s.CloseBackgroundApps);
                s.SetJavaPriority = Json.GetBool(d, "setJavaPriority", s.SetJavaPriority);
                s.TuneNetwork = Json.GetBool(d, "tuneNetwork", s.TuneNetwork);
                s.AddFirewallRules = Json.GetBool(d, "addFirewallRules", s.AddFirewallRules);
                s.TimerResolution = Json.GetBool(d, "timerResolution", s.TimerResolution);

                s.UseAikarFlags = Json.GetBool(d, "useAikarFlags", s.UseAikarFlags);
                s.OpenGlPipeline = Json.GetBool(d, "openGlPipeline", s.OpenGlPipeline);
                s.MaxHeapMb = Clamp(Json.GetInt(d, "maxHeapMb", s.MaxHeapMb), 0, 65536);
                s.ExtraJvmArgs = Json.GetStr(d, "extraJvmArgs", s.ExtraJvmArgs);
                s.QuickPlay = Json.GetBool(d, "quickPlay", s.QuickPlay);

                s.AutoRestoreOnExit = Json.GetBool(d, "autoRestoreOnExit", s.AutoRestoreOnExit);
                s.KeepTunnelAfterGame = Json.GetBool(d, "keepTunnelAfterGame", s.KeepTunnelAfterGame);
                s.MinimizeWhilePlaying = Json.GetBool(d, "minimizeWhilePlaying", s.MinimizeWhilePlaying);
                s.CloseAppWhenGameExits = Json.GetBool(d, "closeAppWhenGameExits", s.CloseAppWhenGameExits);
                s.GaugesOnDashboard = Json.GetBool(d, "gaugesOnDashboard", s.GaugesOnDashboard);
                s.ConnectTimeoutMs = Clamp(Json.GetInt(d, "connectTimeoutMs", s.ConnectTimeoutMs), 1000, 30000);
                s.LoginProbe = Json.GetBool(d, "loginProbe", s.LoginProbe);

                s.PinnedConnection = Json.GetStr(d, "pinnedConnection", s.PinnedConnection);
                s.PinnedChainHop = Json.GetStr(d, "pinnedChainHop", s.PinnedChainHop);
                s.DnsThroughTunnel = Json.GetBool(d, "dnsThroughTunnel", s.DnsThroughTunnel);
                s.OptimiseChains = Clamp(Json.GetInt(d, "optimiseChains", s.OptimiseChains), 0, 12);
                s.FragmentTls = Json.GetBool(d, "fragmentTls", s.FragmentTls);
                s.RetestMinutes = Clamp(Json.GetInt(d, "retestMinutes", s.RetestMinutes), 0, 720);
                s.AllowRouteFallback = Json.GetBool(d, "allowRouteFallback", s.AllowRouteFallback);
                s.ProxyFailover = Json.GetBool(d, "proxyFailover", s.ProxyFailover);
                s.KillSwitch = Json.GetBool(d, "killSwitch", s.KillSwitch);
                s.ConnectionTestTimeoutMs = Clamp(Json.GetInt(d, "connectionTestTimeoutMs", s.ConnectionTestTimeoutMs), 700, 20000);

                var connections = Json.Arr(Json.Get(d, "connections"));
                if (connections != null)
                {
                    // An empty list stays empty: the user may have removed every entry on purpose.
                    s.Connections.Clear();
                    foreach (object o in connections)
                    {
                        var entry = ConnectionEntry.Read(Json.Obj(o));
                        if (entry != null) s.Connections.Add(entry);
                    }
                }

                var servers = Json.Arr(Json.Get(d, "servers"));
                if (servers != null)
                {
                    foreach (object o in servers)
                    {
                        var sd = Json.Obj(o);
                        if (sd == null) continue;
                        var sp = new ServerProfile();
                        sp.Name = Json.GetStr(sd, "name", sp.Name);
                        sp.Host = Json.GetStr(sd, "host", sp.Host);
                        sp.Port = Clamp(Json.GetInt(sd, "port", sp.Port), 1, 65535);
                        sp.DirectIp = Json.GetStr(sd, "directIp", sp.DirectIp);
                        sp.PreferDomain = Json.GetBool(sd, "preferDomain", sp.PreferDomain);
                        if (!string.IsNullOrWhiteSpace(sp.Host)) s.Servers.Add(sp);
                    }
                }
                if (s.Servers.Count == 0) s.Servers.Add(AppSettings.DefaultServer());
                return s;
            }
            catch (Exception ex)
            {
                Log.Error("settings load failed, using defaults", ex);
                return AppSettings.Default();
            }
        }

        private static int Clamp(int v, int min, int max)
        {
            if (v < min) return min;
            if (v > max) return max;
            return v;
        }

        public static void Save(AppSettings s)
        {
            try
            {
                AppPaths.EnsureAll();
                var w = new JsonWriter(true);
                w.StartObject();
                w.Prop("version", s.Version);
                w.Prop("language", s.Language);
                w.Prop("nickname", s.Nickname);
                w.Prop("versionsDir", s.VersionsDir);
                w.Prop("gameDirOverride", s.GameDirOverride);
                w.Prop("javaPathOverride", s.JavaPathOverride);
                w.Prop("activeServer", s.ActiveServer);
                w.Prop("tunnel", (int)s.Tunnel);
                w.Prop("useHostsFile", s.UseHostsFile);
                w.Prop("maxEndpoints", s.MaxEndpoints);
                w.Prop("scanTimeoutMs", s.ScanTimeoutMs);
                w.Prop("optimizeSystem", s.OptimizeSystem);
                w.Prop("highPerformancePowerPlan", s.HighPerformancePowerPlan);
                w.Prop("trimMemory", s.TrimMemory);
                w.Prop("closeBackgroundApps", s.CloseBackgroundApps);
                w.Prop("setJavaPriority", s.SetJavaPriority);
                w.Prop("tuneNetwork", s.TuneNetwork);
                w.Prop("addFirewallRules", s.AddFirewallRules);
                w.Prop("timerResolution", s.TimerResolution);
                w.Prop("useAikarFlags", s.UseAikarFlags);
                w.Prop("openGlPipeline", s.OpenGlPipeline);
                w.Prop("maxHeapMb", s.MaxHeapMb);
                w.Prop("extraJvmArgs", s.ExtraJvmArgs);
                w.Prop("quickPlay", s.QuickPlay);
                w.Prop("autoRestoreOnExit", s.AutoRestoreOnExit);
                w.Prop("keepTunnelAfterGame", s.KeepTunnelAfterGame);
                w.Prop("minimizeWhilePlaying", s.MinimizeWhilePlaying);
                w.Prop("closeAppWhenGameExits", s.CloseAppWhenGameExits);
                w.Prop("gaugesOnDashboard", s.GaugesOnDashboard);
                w.Prop("connectTimeoutMs", s.ConnectTimeoutMs);
                w.Prop("loginProbe", s.LoginProbe);
                w.Prop("pinnedConnection", s.PinnedConnection);
                w.Prop("pinnedChainHop", s.PinnedChainHop);
                w.Prop("dnsThroughTunnel", s.DnsThroughTunnel);
                w.Prop("optimiseChains", s.OptimiseChains);
                w.Prop("fragmentTls", s.FragmentTls);
                w.Prop("retestMinutes", s.RetestMinutes);
                w.Prop("allowRouteFallback", s.AllowRouteFallback);
                w.Prop("proxyFailover", s.ProxyFailover);
                w.Prop("killSwitch", s.KillSwitch);
                w.Prop("connectionTestTimeoutMs", s.ConnectionTestTimeoutMs);

                w.Name("connections").StartArray();
                foreach (ConnectionEntry entry in s.Connections) entry.WriteTo(w);
                w.EndArray();

                w.Name("servers").StartArray();
                foreach (var sp in s.Servers)
                {
                    w.StartObject();
                    w.Prop("name", sp.Name);
                    w.Prop("host", sp.Host);
                    w.Prop("port", sp.Port);
                    w.Prop("directIp", sp.DirectIp);
                    w.Prop("preferDomain", sp.PreferDomain);
                    w.EndObject();
                }
                w.EndArray();
                w.EndObject();

                File.WriteAllText(AppPaths.SettingsFile, w.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Log.Error("settings save failed", ex);
            }
        }
    }
}

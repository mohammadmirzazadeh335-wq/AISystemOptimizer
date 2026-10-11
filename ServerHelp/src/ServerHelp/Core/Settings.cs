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
        public bool HighPerformancePowerPlan = true;
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

        public bool AutoRestoreOnExit = true;
        public bool KeepTunnelAfterGame = false;
        public bool MinimizeWhilePlaying = true;
        public bool CloseAppWhenGameExits = false;

        public bool GaugesOnDashboard = true;
        public int ConnectTimeoutMs = 6000;
        /// <summary>Runs a real login to learn whether the server is premium-only.</summary>
        public bool LoginProbe = true;

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
            return c;
        }

        public static AppSettings Default()
        {
            var s = new AppSettings();
            s.Servers.Add(DefaultServer());
            return s;
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

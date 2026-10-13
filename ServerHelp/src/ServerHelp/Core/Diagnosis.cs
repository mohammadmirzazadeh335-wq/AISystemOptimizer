using System;
using System.Collections.Generic;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>
    /// Builds the one file a user can hand over when something does not work: what this machine is,
    /// how the app is configured, what the last run did, and the log. Writing it down is much better
    /// than describing symptoms from memory, and the file is built so it is safe to send: it carries
    /// the names, kinds and addresses of the connections - never a password, an MTProto secret, a
    /// WireGuard private key or a pasted configuration. The self test pins exactly that.
    /// </summary>
    public static class Diagnosis
    {
        public static string Build(string appVersion, bool admin, AppSettings settings, string lastRun, string logTail)
        {
            var sb = new StringBuilder();
            sb.AppendLine("Server Help - diagnosis report");
            sb.AppendLine("==============================");
            sb.AppendLine("app version   : " + (appVersion ?? ""));
            sb.AppendLine("written       : " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture));
            sb.AppendLine("running as    : " + (admin ? "administrator" : "normal user (TUN, routes and the hosts file need admin)"));
            sb.AppendLine("windows       : " + SafeOsText());
            sb.AppendLine("data folder   : " + AppPaths.Data);
            sb.AppendLine("note          : passwords, secrets and private keys are NOT in this file. It is safe to share.");
            sb.AppendLine();

            if (settings == null)
            {
                sb.AppendLine("(no settings could be read)");
                sb.AppendLine();
            }
            else
            {
                sb.AppendLine("--- settings ---");
                sb.AppendLine("language          : " + (settings.Language == L.En ? "English" : "فارسی"));
                sb.AppendLine("tunnel mode       : " + settings.Tunnel);
                sb.AppendLine("kill switch       : " + Yes(settings.KillSwitch));
                sb.AppendLine("dns through tunnel: " + Yes(settings.DnsThroughTunnel));
                sb.AppendLine("fragment TLS      : " + Yes(settings.FragmentTls));
                sb.AppendLine("hosts file pin    : " + Yes(settings.UseHostsFile));
                sb.AppendLine("pin connection    : " + (string.IsNullOrEmpty(settings.PinnedConnection) ? "(automatic)" : settings.PinnedConnection));
                sb.AppendLine("pin chain hop     : " + (string.IsNullOrEmpty(settings.PinnedChainHop) ? "(none)" : settings.PinnedChainHop));
                sb.AppendLine("retest minutes    : " + settings.RetestMinutes);
                sb.AppendLine("game folder       : " + Blank(settings.GameDirOverride));
                sb.AppendLine("versions folder   : " + Blank(settings.VersionsDir));
                sb.AppendLine("java override     : " + Blank(settings.JavaPathOverride));
                sb.AppendLine("nickname          : " + Blank(settings.Nickname));
                sb.AppendLine("tune the system   : " + Yes(settings.OptimizeSystem) +
                              " (power plan=" + Yes(settings.HighPerformancePowerPlan) +
                              ", network=" + Yes(settings.TuneNetwork) +
                              ", firewall=" + Yes(settings.AddFirewallRules) +
                              ", memory=" + Yes(settings.TrimMemory) +
                              ", timer=" + Yes(settings.TimerResolution) +
                              ", jvm flags=" + Yes(settings.UseAikarFlags) +
                              ", java priority=" + Yes(settings.SetJavaPriority) + ")");
                sb.AppendLine("auto restore      : " + Yes(settings.AutoRestoreOnExit) +
                              ", keep tunnel=" + Yes(settings.KeepTunnelAfterGame) +
                              ", close app after game=" + Yes(settings.CloseAppWhenGameExits));
                sb.AppendLine();

                sb.AppendLine("--- servers (" + (settings.Servers == null ? 0 : settings.Servers.Count) + ") ---");
                if (settings.Servers != null)
                {
                    foreach (ServerProfile server in settings.Servers)
                    {
                        if (server == null) continue;
                        sb.AppendLine("  " + Blank(server.Name) + "  |  " + Blank(server.Host) + ":" + server.Port +
                                      "  |  ip: " + Blank(server.DirectIp) +
                                      "  |  prefer domain: " + Yes(server.PreferDomain));
                    }
                }
                sb.AppendLine();

                List<ConnectionEntry> entries = settings.Connections == null ? new List<ConnectionEntry>() : settings.Connections;
                sb.AppendLine("--- connections (" + entries.Count + ") ---");
                foreach (ConnectionEntry entry in entries)
                {
                    if (entry == null) continue;
                    sb.AppendLine("  " + Blank(entry.Name) + "  [" + entry.Info.Title + "]");
                    sb.AppendLine("      target      : " + Blank(entry.Target));
                    sb.AppendLine("      on / for game: " + Yes(entry.Enabled) + " / " + Yes(entry.UseForGame));
                    sb.AppendLine("      last test   : " + (string.IsNullOrEmpty(entry.LastTestUtc) ? "(never)" : entry.TestedText()) +
                                  "  " + Blank(entry.StatusText));
                    if (entry.LastError.Length > 0) sb.AppendLine("      last error  : " + entry.LastError);
                    string quality = entry.QualityText();
                    if (quality.Length > 0) sb.AppendLine("      quality     : " + quality);
                    if (entry.Notes.Length > 0) sb.AppendLine("      notes       : " + entry.Notes);
                }
                sb.AppendLine();
            }

            sb.AppendLine("--- last run ---");
            sb.AppendLine(string.IsNullOrEmpty(lastRun) ? "(no run in this session yet)" : lastRun.TrimEnd());
            sb.AppendLine();

            sb.AppendLine("--- log (last lines) ---");
            sb.AppendLine(string.IsNullOrEmpty(logTail) ? "(the log is empty)" : logTail.TrimEnd());
            return sb.ToString();
        }

        private static string Yes(bool value) { return value ? "yes" : "no"; }

        private static string Blank(string value) { return string.IsNullOrEmpty(value) ? "(not set)" : value; }

        private static string SafeOsText()
        {
            try { return Environment.OSVersion.VersionString; }
            catch { return ""; }
        }
    }
}

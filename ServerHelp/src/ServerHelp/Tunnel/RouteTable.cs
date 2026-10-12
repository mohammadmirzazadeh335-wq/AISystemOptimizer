using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Tunnel
{
    /// <summary>
    /// Reads and edits the IPv4 routing table. Only single host routes for the game server are
    /// touched, so the rest of the system keeps its normal path.
    /// </summary>
    public static class RouteTable
    {
        public static string Dump()
        {
            var result = Shell.Run("route", "print -4", 15000);
            return result.All;
        }

        /// <summary>Index of a network interface by it's display name (for example "ServerHelp").</summary>
        public static int InterfaceIndex(string name)
        {
            try
            {
                foreach (string raw in Dump().Replace("\r\n", "\n").Split('\n'))
                {
                    int marker = raw.IndexOf("......", StringComparison.Ordinal);
                    if (marker < 0) continue;
                    string left = raw.Substring(0, marker).Trim();
                    string right = raw.Substring(marker + 6).Trim();
                    if (!string.Equals(right, name, StringComparison.OrdinalIgnoreCase)) continue;
                    int dots = left.IndexOf("...", StringComparison.Ordinal);
                    string indexPart = dots > 0 ? left.Substring(0, dots).Trim() : left;
                    int index;
                    if (int.TryParse(indexPart, out index)) return index;
                }
            }
            catch (Exception ex) { Log.Debug("interface index lookup failed: " + ex.Message); }
            return -1;
        }

        /// <summary>True when a /32 route for the given address is already present.</summary>
        public static bool HasHostRoute(string ip)
        {
            try
            {
                foreach (string line in Dump().Replace("\r\n", "\n").Split('\n'))
                {
                    string[] parts = line.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length < 5) continue;
                    if (parts[0] == ip && parts[1] == "255.255.255.255") return true;
                }
            }
            catch { }
            return false;
        }

        public static bool AddHostRoute(string ip, string gateway, int interfaceIndex, out string error)
        {
            error = "";
            if (HasHostRoute(ip)) return true;

            var attempts = new List<string>();
            if (!string.IsNullOrEmpty(gateway) && interfaceIndex > 0)
                attempts.Add("add " + ip + " mask 255.255.255.255 " + gateway + " if " + interfaceIndex + " metric 1");
            if (interfaceIndex > 0)
                attempts.Add("add " + ip + " mask 255.255.255.255 0.0.0.0 if " + interfaceIndex + " metric 1");
            if (!string.IsNullOrEmpty(gateway))
                attempts.Add("add " + ip + " mask 255.255.255.255 " + gateway + " metric 1");
            attempts.Add("add " + ip + " mask 255.255.255.255 " + (string.IsNullOrEmpty(gateway) ? "0.0.0.0" : gateway) + " metric 1");

            foreach (string command in attempts)
            {
                var result = Shell.Run("route", command, 10000);
                if (result.Ok || HasHostRoute(ip))
                {
                    Log.Info("host route added: " + ip + " (route " + command + ")");
                    return true;
                }
                error = result.All;
            }
            Log.Warn("could not add a host route for " + ip + ": " + error);
            return false;
        }

        public static void DeleteHostRoute(string ip)
        {
            try
            {
                if (!HasHostRoute(ip)) return;
                Shell.Run("route", "delete " + ip, 10000);
                Log.Info("host route removed: " + ip);
            }
            catch (Exception ex) { Log.Debug("route delete failed: " + ex.Message); }
        }

        /// <summary>
        /// Sends one address into a black hole (a /32 route over the loopback interface). Used by
        /// the kill switch: when the tunnel is gone it is better for the game to have no route at
        /// all than to leak the real address to the server.
        /// </summary>
        public static bool AddBlackhole(string ip, out string error)
        {
            error = "";
            try
            {
                int loopback = -1;
                foreach (string raw in Dump().Replace("\r\n", "\n").Split('\n'))
                {
                    int marker = raw.IndexOf("......", StringComparison.Ordinal);
                    if (marker < 0) continue;
                    string right = raw.Substring(marker + 6).Trim();
                    if (right.IndexOf("Loopback", StringComparison.OrdinalIgnoreCase) < 0 &&
                        right.IndexOf("Loopback Pseudo", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    string left = raw.Substring(0, marker).Trim();
                    int dots = left.IndexOf("...", StringComparison.Ordinal);
                    string indexPart = dots > 0 ? left.Substring(0, dots).Trim() : left;
                    int parsed;
                    if (int.TryParse(indexPart, out parsed)) { loopback = parsed; break; }
                }
                if (loopback <= 0)
                {
                    error = L.T("اینترفیس loopback پیدا نشد", "the loopback interface was not found");
                    return false;
                }
                var result = Shell.Run("route", "add " + ip + " mask 255.255.255.255 0.0.0.0 if " + loopback + " metric 1", 10000);
                if (result.Ok)
                {
                    Log.Info("kill switch: " + ip + " blackholed");
                    return true;
                }
                error = result.All;
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        /// <summary>
        /// Removes the /32 routes over the loopback interface that a previous session left behind when
        /// the kill switch fired and the app was killed before it could clean up. Without this the
        /// server address would stay blocked (until the next reboot) with nothing saying why. Only the
        /// addresses handed in are touched, so a route the user set up is never removed.
        /// </summary>
        public static List<string> CleanLeftoverBlackholes(IEnumerable<string> ips)
        {
            var cleaned = new List<string>();
            try
            {
                string dump = Dump().Replace("\r\n", "\n");
                foreach (string ip in ips)
                {
                    if (string.IsNullOrEmpty(ip)) continue;
                    bool blackholed = false;
                    foreach (string line in dump.Split('\n'))
                    {
                        string[] parts = line.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length < 5) continue;
                        if (parts[0] != ip || parts[1] != "255.255.255.255") continue;
                        if (parts[3].IndexOf("Loopback", StringComparison.OrdinalIgnoreCase) < 0 &&
                            parts[3] != "127.0.0.1") continue;
                        blackholed = true;
                        break;
                    }
                    if (!blackholed) continue;
                    Shell.Run("route", "delete " + ip, 10000);
                    cleaned.Add(ip);
                    Log.Info("leftover kill switch route removed: " + ip);
                }
            }
            catch (Exception ex) { Log.Debug("leftover route cleanup failed: " + ex.Message); }
            return cleaned;
        }

        /// <summary>Best guess of the machine's normal gateway (used only for diagnostics).</summary>
        public static string DefaultGateway()
        {
            try
            {
                string best = "";
                int bestMetric = int.MaxValue;
                foreach (string line in Dump().Replace("\r\n", "\n").Split('\n'))
                {
                    string[] parts = line.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length < 5) continue;
                    if (parts[0] != "0.0.0.0" || parts[1] != "0.0.0.0") continue;
                    int metric;
                    if (!int.TryParse(parts[4], out metric)) metric = 9999;
                    if (metric < bestMetric) { bestMetric = metric; best = parts[2]; }
                }
                return best;
            }
            catch { return ""; }
        }
    }

    /// <summary>Adds/removes the hosts-file line that pins the server name to the tunnelled address.</summary>
    public static class HostsFile
    {
        public static readonly string Path =
            System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "drivers", "etc", "hosts");

        private const string Begin = "# >>> ServerHelp (managed block, do not edit) >>>";
        private const string End = "# <<< ServerHelp <<<";

        public static bool IsApplied(string hostname, string ip)
        {
            try
            {
                if (!File.Exists(Path)) return false;
                foreach (string line in File.ReadAllLines(Path, Encoding.UTF8))
                {
                    string t = line.Trim();
                    if (t.StartsWith(ip + " ", StringComparison.OrdinalIgnoreCase) &&
                        t.EndsWith(hostname, StringComparison.OrdinalIgnoreCase)) return true;
                }
            }
            catch { }
            return false;
        }

        public static bool Apply(string hostname, string ip, out string error)
        {
            error = "";
            try
            {
                if (IsApplied(hostname, ip)) return true;
                string content = File.Exists(Path) ? File.ReadAllText(Path, Encoding.UTF8) : "";
                string stripped = StripBlock(content);
                Backup(content);

                var sb = new StringBuilder(stripped.TrimEnd());
                sb.AppendLine();
                sb.AppendLine();
                sb.AppendLine(Begin);
                sb.AppendLine(ip + " " + hostname);
                sb.AppendLine(End);
                File.WriteAllText(Path, sb.ToString(), new UTF8Encoding(false));
                Log.Info("hosts entry set: " + ip + " " + hostname);
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Error("could not write the hosts file", ex);
                return false;
            }
        }

        public static void Remove()
        {
            try
            {
                if (!File.Exists(Path)) return;
                string content = File.ReadAllText(Path, Encoding.UTF8);
                if (content.IndexOf(Begin, StringComparison.Ordinal) < 0) return;
                File.WriteAllText(Path, StripBlock(content), new UTF8Encoding(false));
                Log.Info("hosts entry removed");
            }
            catch (Exception ex) { Log.Warn("could not clean the hosts file: " + ex.Message); }
        }

        private static string StripBlock(string content)
        {
            var sb = new StringBuilder();
            bool inside = false;
            string[] lines = content.Replace("\r\n", "\n").Split('\n');
            foreach (string line in lines)
            {
                string t = line.Trim();
                if (t.StartsWith(Begin, StringComparison.Ordinal)) { inside = true; continue; }
                if (t.StartsWith(End, StringComparison.Ordinal)) { inside = false; continue; }
                if (inside) continue;
                sb.AppendLine(line);
            }
            return sb.ToString();
        }

        private static void Backup(string content)
        {
            try
            {
                AppPaths.EnsureAll();
                string name = "hosts-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".bak";
                File.WriteAllText(System.IO.Path.Combine(AppPaths.Backups, name), content, new UTF8Encoding(false));
            }
            catch { }
        }
    }
}

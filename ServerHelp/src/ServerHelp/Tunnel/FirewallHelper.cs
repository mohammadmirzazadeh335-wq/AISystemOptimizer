using System;
using ServerHelp.Core;

namespace ServerHelp.Tunnel
{
    /// <summary>
    /// A silently blocked executable is a classic "why can't I join?" cause, so the tunnel engine
    /// and the game runtime get an explicit allow rule instead of a pending firewall prompt.
    /// </summary>
    public static class FirewallHelper
    {
        public static bool EnsureProgramAllowed(string ruleName, string programPath, out string error)
        {
            error = "";
            try
            {
                if (string.IsNullOrEmpty(programPath) || !Shell.FileExists(programPath))
                {
                    error = "program path missing";
                    return false;
                }
                RemoveRule(ruleName);
                bool inOk = AddRule(ruleName, programPath, "in");
                bool outOk = AddRule(ruleName, programPath, "out");
                if (inOk && outOk)
                {
                    Log.Info("firewall rule ready: " + ruleName);
                    return true;
                }
                error = "netsh refused the rule";
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Warn("firewall rule failed: " + ex.Message);
                return false;
            }
        }

        private static bool AddRule(string ruleName, string programPath, string direction)
        {
            string args = "advfirewall firewall add rule name=" + Shell.Quote(ruleName + " (" + direction + ")") +
                          " dir=" + direction + " action=allow program=" + Shell.Quote(programPath) +
                          " enable=yes profile=any";
            var result = Shell.Run("netsh", args, 15000);
            return result.Ok;
        }

        public static void RemoveRule(string ruleName)
        {
            Shell.Run("netsh", "advfirewall firewall delete rule name=" + Shell.Quote(ruleName), 10000);
        }
    }
}

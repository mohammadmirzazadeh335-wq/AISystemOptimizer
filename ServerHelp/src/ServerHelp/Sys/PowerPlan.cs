using System;
using System.Collections.Generic;
using ServerHelp.Core;

namespace ServerHelp.Sys
{
    /// <summary>Switches the active Windows power plan and can put the previous one back.</summary>
    public static class PowerPlan
    {
        /// <summary>Locale independent powercfg aliases: SCHEME_MIN = High performance.</summary>
        public const string HighPerformance = "SCHEME_MIN";
        public const string Balanced = "SCHEME_BALANCED";
        public const string PowerSaver = "SCHEME_MAX";

        public static string ActiveScheme()
        {
            try
            {
                var result = Shell.Run("powercfg", "/getactivescheme", 10000);
                if (!result.Ok) return "";
                // "Power Scheme GUID: 381b4222-...  (Balanced)"
                int colon = result.StdOut.IndexOf(':');
                if (colon < 0) return "";
                string rest = result.StdOut.Substring(colon + 1).Trim();
                int space = rest.IndexOf(' ');
                if (space > 0) rest = rest.Substring(0, space);
                return rest.Trim();
            }
            catch { return ""; }
        }

        public static string ActiveSchemeName()
        {
            try
            {
                var result = Shell.Run("powercfg", "/getactivescheme", 10000);
                if (!result.Ok) return "";
                int open = result.StdOut.IndexOf('(');
                int close = result.StdOut.LastIndexOf(')');
                if (open >= 0 && close > open) return result.StdOut.Substring(open + 1, close - open - 1).Trim();
                return result.StdOut.Trim();
            }
            catch { return ""; }
        }

        public static bool Set(string aliasOrGuid, out string error)
        {
            error = "";
            var result = Shell.Run("powercfg", "/setactive " + aliasOrGuid, 15000);
            if (result.Ok)
            {
                Log.Info("power plan set to " + aliasOrGuid + " (" + ActiveSchemeName() + ")");
                return true;
            }
            error = result.All;
            Log.Warn("could not set power plan " + aliasOrGuid + ": " + error);
            return false;
        }

        /// <summary>Adds the Ultimate Performance plan when it is missing, then returns its GUID.
        /// <paramref name="created"/> says whether this call was the one that added it, so Restore can
        /// take it away again and leave the machine's power options exactly as they were.</summary>
        public static string EnsureUltimate(out bool created)
        {
            const string ultimate = "e9a42b02-d5df-448d-aa00-03f14749eb61";
            created = false;
            try
            {
                var list = Shell.Run("powercfg", "/list", 15000);
                if (list.StdOut.IndexOf(ultimate, StringComparison.OrdinalIgnoreCase) >= 0) return ultimate;
                Shell.Run("powercfg", "-duplicatescheme " + ultimate, 15000);
                var again = Shell.Run("powercfg", "/list", 15000);
                if (again.StdOut.IndexOf(ultimate, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    created = true;
                    Log.Info("ultimate performance plan created");
                    return ultimate;
                }
            }
            catch (Exception ex) { Log.Debug("ultimate plan unavailable: " + ex.Message); }
            return "";
        }

        public static string EnsureUltimate()
        {
            bool ignored;
            return EnsureUltimate(out ignored);
        }

        /// <summary>Deletes a power plan (used to take back the Ultimate plan this app created).</summary>
        public static bool Delete(string guid)
        {
            if (string.IsNullOrEmpty(guid)) return false;
            try
            {
                var result = Shell.Run("powercfg", "-delete " + guid, 15000);
                if (!result.Ok) Log.Warn("could not delete power plan " + guid + ": " + result.All);
                return result.Ok;
            }
            catch (Exception ex) { Log.Warn("power plan delete failed: " + ex.Message); return false; }
        }

        public static List<string> List()
        {
            var plans = new List<string>();
            try
            {
                var result = Shell.Run("powercfg", "/list", 15000);
                foreach (string line in result.StdOut.Replace("\r\n", "\n").Split('\n'))
                {
                    string t = line.Trim();
                    if (t.Length > 0) plans.Add(t);
                }
            }
            catch { }
            return plans;
        }
    }
}

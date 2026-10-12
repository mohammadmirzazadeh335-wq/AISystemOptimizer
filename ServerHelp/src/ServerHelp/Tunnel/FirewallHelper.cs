using System;
using System.Collections.Generic;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Tunnel
{
    /// <summary>One firewall rule as Windows reports it (read-only view).</summary>
    public sealed class FirewallRule
    {
        public string Name = "";
        public string Direction = "";
        public string Program = "";
    }

    /// <summary>
    /// A rule this app created: the exact name plus the program it was written for, so the uninstall
    /// path can take back precisely that rule and nothing else.
    /// </summary>
    public sealed class CreatedRule
    {
        public string Name = "";
        public string Program = "";
        public CreatedRule(string name, string program) { Name = name; Program = program; }
    }

    /// <summary>
    /// A silently blocked executable is a classic "why can't I join?" cause, so the tunnel engine
    /// and the game runtime get an explicit allow rule instead of a pending firewall prompt.
    ///
    /// The rules on the machine belong to the user, not to this app, so nothing is deleted blindly:
    /// every name is looked up read-only first, a name another program is already using is left
    /// alone and our rule is added under a free name, and the restore path deletes only the exact
    /// rules this app created - and only while they still point at the program they were made for.
    /// When Windows cannot be asked (no PowerShell / no firewall module) the app falls back to the
    /// plain add/remove it used before and says so in the log.
    /// </summary>
    public static class FirewallHelper
    {
        public static bool EnsureProgramAllowed(string ruleName, string programPath, out string error,
                                                List<CreatedRule> created)
        {
            error = "";
            try
            {
                if (string.IsNullOrEmpty(programPath) || !Shell.FileExists(programPath))
                {
                    error = "program path missing";
                    return false;
                }
                string inName = PickName(ruleName + " (in)", programPath);
                string outName = PickName(ruleName + " (out)", programPath);
                bool inOk = AddRule(inName, programPath, "in");
                bool outOk = AddRule(outName, programPath, "out");
                if (!inOk || !outOk)
                {
                    error = "netsh refused the rule";
                    return false;
                }
                Remember(created, inName, programPath);
                Remember(created, outName, programPath);
                Log.Info("firewall rules ready: " + inName + " / " + outName);
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Warn("firewall rule failed: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Removes one rule this app created. It is skipped when the rule has since been re-pointed
        /// at another program - at that point it is the user's rule, not ours.
        /// </summary>
        public static bool RemoveCreatedRule(CreatedRule rule)
        {
            if (rule == null || string.IsNullOrEmpty(rule.Name)) return false;
            List<FirewallRule> known = Query(new string[] { rule.Name });
            if (known == null)
            {
                Log.Warn("could not check \"" + rule.Name + "\" before removing it; removing by name");
            }
            else
            {
                FirewallRule exact = Exact(known, rule.Name);
                if (exact == null)
                {
                    Log.Debug("firewall rule already gone: " + rule.Name);
                    return false;
                }
                if (!SameProgram(exact.Program, rule.Program))
                {
                    Log.Warn("not removing \"" + rule.Name + "\": it now points at " + exact.Program);
                    return false;
                }
            }
            RemoveRule(rule.Name);
            return true;
        }

        /// <summary>Read-only: is there a rule carrying exactly this name?</summary>
        public static bool RuleExists(string exactName)
        {
            List<FirewallRule> known = Query(new string[] { exactName });
            return known != null && Exact(known, exactName) != null;
        }

        /// <summary>
        /// Read-only lookup of the rules Windows has for exactly these names. Returns null when
        /// Windows cannot be asked at all, so callers can tell "there is no such rule" from
        /// "no answer" instead of guessing.
        /// </summary>
        public static List<FirewallRule> Query(IEnumerable<string> names)
        {
            var wanted = new List<string>();
            foreach (string name in names) if (!string.IsNullOrEmpty(name)) wanted.Add(name);
            if (wanted.Count == 0) return new List<FirewallRule>();

            var script = new StringBuilder();
            script.Append("$ErrorActionPreference='Stop';");
            script.Append("foreach($n in @(");
            for (int i = 0; i < wanted.Count; i++)
            {
                if (i > 0) script.Append(',');
                script.Append("'").Append(wanted[i].Replace("'", "''")).Append("'");
            }
            script.Append(")){");
            script.Append("foreach($r in @(Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue)){");
            script.Append("$p='';");
            script.Append("try{$a=@($r | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue);");
            script.Append("if($a.Count -gt 0){$p=[string]$a[0].Program}}catch{}");
            script.Append("$r.DisplayName + '|' + $r.Direction + '|' + $p}}");

            // -EncodedCommand: base64 keeps the script out of the command line quoting rules entirely.
            string encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script.ToString()));
            Shell.Result result = Shell.Run("powershell.exe",
                "-NoProfile -NonInteractive -EncodedCommand " + encoded, 20000);
            if (!result.Ok)
            {
                Log.Debug("firewall query unavailable: " + result.All);
                return null;
            }
            return ParseQueryOutput(result.StdOut);
        }

        /// <summary>
        /// Turns the "name|direction|program" lines the lookup prints into rules. Kept as its own
        /// method so the self test can pin the format on a machine where there is no firewall to ask.
        /// </summary>
        public static List<FirewallRule> ParseQueryOutput(string text)
        {
            var rules = new List<FirewallRule>();
            if (string.IsNullOrEmpty(text)) return rules;
            foreach (string raw in text.Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0) continue;
                string[] parts = line.Split('|');
                if (parts.Length < 3) continue;
                var rule = new FirewallRule();
                rule.Name = parts[0].Trim();
                rule.Direction = parts[1].Trim();
                rule.Program = parts[2].Trim();
                if (rule.Name.Length > 0) rules.Add(rule);
            }
            return rules;
        }

        /// <summary>
        /// Picks a name that is genuinely free. A rule that already carries the wanted name and
        /// points at this same program is a leftover from an earlier run of this app and is
        /// replaced; one that points anywhere else belongs to the user, so it is kept untouched and
        /// our rule goes in under a numbered name instead.
        /// </summary>
        private static string PickName(string wanted, string programPath)
        {
            FirewallRule existing = Exact(Query(new string[] { wanted }), wanted);
            if (existing == null) return wanted;                       // free, or Windows could not be asked
            if (SameProgram(existing.Program, programPath))
            {
                RemoveRule(wanted);
                return wanted;
            }
            for (int i = 2; i <= 9; i++)
            {
                string alternative = wanted + " (" + i + ")";
                if (!RuleExists(alternative))
                {
                    Log.Warn("firewall rule \"" + wanted + "\" belongs to " + existing.Program +
                             "; keeping it and using \"" + alternative + "\" instead");
                    return alternative;
                }
            }
            Log.Warn("firewall rule \"" + wanted + "\" belongs to " + existing.Program +
                     " and no alternative name is free; replacing it");
            RemoveRule(wanted);
            return wanted;
        }

        private static FirewallRule Exact(List<FirewallRule> rules, string name)
        {
            if (rules == null) return null;
            foreach (FirewallRule rule in rules)
                if (string.Equals(rule.Name, name, StringComparison.OrdinalIgnoreCase)) return rule;
            return null;
        }

        internal static bool SameProgram(string a, string b)
        {
            if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b)) return false;
            return string.Equals(a.Trim().Trim('"'), b.Trim().Trim('"'), StringComparison.OrdinalIgnoreCase);
        }

        private static void Remember(List<CreatedRule> created, string name, string programPath)
        {
            if (created == null) return;
            foreach (CreatedRule rule in created)
                if (string.Equals(rule.Name, name, StringComparison.OrdinalIgnoreCase)) return;
            created.Add(new CreatedRule(name, programPath));
        }

        private static bool AddRule(string ruleName, string programPath, string direction)
        {
            string args = "advfirewall firewall add rule name=" + Shell.Quote(ruleName) +
                          " dir=" + direction + " action=allow program=" + Shell.Quote(programPath) +
                          " enable=yes profile=any";
            var result = Shell.Run("netsh", args, 15000);
            return result.Ok;
        }

        /// <summary>Deletes one exact rule name. Only ever called with a name this app checked first.</summary>
        public static void RemoveRule(string ruleName)
        {
            Shell.Run("netsh", "advfirewall firewall delete rule name=" + Shell.Quote(ruleName), 10000);
        }
    }
}

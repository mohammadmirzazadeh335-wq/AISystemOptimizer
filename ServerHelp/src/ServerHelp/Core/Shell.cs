using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>Process helpers. Every external command in this app goes through here.</summary>
    public static class Shell
    {
        public sealed class Result
        {
            public int ExitCode;
            public string StdOut = "";
            public string StdErr = "";
            public bool TimedOut;

            public string All { get { return (StdOut + "\n" + StdErr).Trim(); } }
            public bool Ok { get { return !TimedOut && ExitCode == 0; } }
        }

        /// <summary>Runs a command and waits. Never throws: a failure is reported in the result.</summary>
        public static Result Run(string fileName, string arguments, int timeoutMs, bool hidden = true)
        {
            var r = new Result();
            try
            {
                var psi = new ProcessStartInfo(fileName, arguments)
                {
                    UseShellExecute = false,
                    CreateNoWindow = hidden,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                    WindowStyle = hidden ? ProcessWindowStyle.Hidden : ProcessWindowStyle.Normal
                };
                using (var p = new Process())
                {
                    p.StartInfo = psi;
                    var so = new StringBuilder();
                    var se = new StringBuilder();
                    p.OutputDataReceived += delegate (object s, DataReceivedEventArgs e) { if (e.Data != null) so.AppendLine(e.Data); };
                    p.ErrorDataReceived += delegate (object s, DataReceivedEventArgs e) { if (e.Data != null) se.AppendLine(e.Data); };
                    if (!p.Start())
                    {
                        r.StdErr = "failed to start " + fileName;
                        return r;
                    }
                    p.BeginOutputReadLine();
                    p.BeginErrorReadLine();
                    if (!p.WaitForExit(timeoutMs))
                    {
                        r.TimedOut = true;
                        try { p.Kill(); } catch { }
                    }
                    else
                    {
                        // give the async readers a moment to flush
                        p.WaitForExit(2000);
                    }
                    r.ExitCode = SafeExitCode(p);
                    r.StdOut = so.ToString().Trim();
                    r.StdErr = se.ToString().Trim();
                }
            }
            catch (Exception ex)
            {
                r.ExitCode = -1;
                r.StdErr = ex.GetType().Name + ": " + ex.Message;
            }
            return r;
        }

        private static int SafeExitCode(Process p)
        {
            try { return p.ExitCode; } catch { return -1; }
        }

        /// <summary>Windows argument quoting (CommandLineToArgvW rules).</summary>
        public static string Quote(string arg)
        {
            if (arg == null) arg = "";
            if (arg.Length > 0 && arg.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0) return arg;
            var sb = new StringBuilder();
            sb.Append('"');
            for (int i = 0; i < arg.Length; i++)
            {
                int backslashes = 0;
                while (i < arg.Length && arg[i] == '\\') { backslashes++; i++; }
                if (i == arg.Length)
                {
                    sb.Append('\\', backslashes * 2);
                    break;
                }
                if (arg[i] == '"')
                {
                    sb.Append('\\', backslashes * 2 + 1);
                    sb.Append('"');
                }
                else
                {
                    sb.Append('\\', backslashes);
                    sb.Append(arg[i]);
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        public static string JoinArgs(System.Collections.Generic.IEnumerable<string> args)
        {
            var sb = new StringBuilder();
            foreach (string a in args)
            {
                if (sb.Length > 0) sb.Append(' ');
                sb.Append(Quote(a));
            }
            return sb.ToString();
        }

        public static bool FileExists(string path)
        {
            try { return !string.IsNullOrEmpty(path) && File.Exists(path); } catch { return false; }
        }

        /// <summary>Copy of the system default browser style "does this file look runnable" check.</summary>
        public static string HumanSize(long bytes)
        {
            if (bytes < 1024) return bytes.ToString(CultureInfo.InvariantCulture) + " B";
            double kb = bytes / 1024.0;
            if (kb < 1024) return kb.ToString("0.#", CultureInfo.InvariantCulture) + " KB";
            double mb = kb / 1024.0;
            if (mb < 1024) return mb.ToString("0.#", CultureInfo.InvariantCulture) + " MB";
            return (mb / 1024.0).ToString("0.##", CultureInfo.InvariantCulture) + " GB";
        }
    }
}

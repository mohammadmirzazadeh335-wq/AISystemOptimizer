using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    /// <summary>Starts javaw.exe with the generated command line and watches the game process.</summary>
    public sealed class GameLauncher
    {
        private Process _process;
        private StreamWriter _log;

        public event Action<string> OutputLine;
        public event Action<int> Exited;

        public int Pid
        {
            get
            {
                try { return _process != null && !_process.HasExited ? _process.Id : -1; }
                catch { return -1; }
            }
        }

        public bool IsRunning
        {
            get
            {
                try { return _process != null && !_process.HasExited; }
                catch { return false; }
            }
        }

        public DateTime StartedAt = DateTime.MinValue;

        /// <summary>How long the game ran. Empty until it has been started.</summary>
        public TimeSpan RanFor
        {
            get
            {
                try
                {
                    if (StartedAt == DateTime.MinValue) return TimeSpan.Zero;
                    TimeSpan ran = DateTime.Now - StartedAt;
                    return ran > TimeSpan.Zero ? ran : TimeSpan.Zero;
                }
                catch { return TimeSpan.Zero; }
            }
        }

        /// <summary>
        /// The first line of the game's own log that names a problem, or "" when it only printed normal
        /// startup lines. This is what turns "the game closed by itself" into something a user can act
        /// on: a wrong Java version or a JVM flag its build does not know says exactly that in here.
        /// </summary>
        public static string FirstProblemLine(string logTail)
        {
            if (string.IsNullOrEmpty(logTail)) return "";
            foreach (string raw in logTail.Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0) continue;
                if (line.StartsWith("[ServerHelp]", StringComparison.OrdinalIgnoreCase)) continue;
                string lower = line.ToLowerInvariant();
                if (lower.IndexOf("unrecognized") >= 0 || lower.IndexOf("unsupported") >= 0 ||
                    lower.IndexOf("could not") >= 0 || lower.IndexOf("cannot ") >= 0 ||
                    lower.IndexOf("failed") >= 0 || lower.IndexOf("exception") >= 0 ||
                    lower.IndexOf("error") >= 0)
                    return line.Length <= 300 ? line : line.Substring(0, 300) + "…";
            }
            return "";
        }

        /// <summary>
        /// True when a Java window process is alive, which for this app in practice means the game is
        /// still running - the launcher starts <c>javaw.exe</c> and nothing else. The startup cleanup
        /// asks this before it stops a leftover tunnel: cutting off a game that is still being played
        /// would be a much worse side effect than leaving one process for the user to close.
        /// </summary>
        public static bool LooksRunning()
        {
            try
            {
                foreach (Process process in Process.GetProcessesByName("javaw"))
                {
                    try { if (!process.HasExited) return true; }
                    catch { }
                }
            }
            catch { }
            return false;
        }

        public bool Start(LaunchPlan plan, out string error)
        {
            error = "";
            try
            {
                var psi = new ProcessStartInfo(plan.JavaExe, plan.Arguments)
                {
                    WorkingDirectory = plan.WorkingDirectory,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                var process = new Process();
                process.StartInfo = psi;
                process.EnableRaisingEvents = true;
                process.OutputDataReceived += delegate (object s, DataReceivedEventArgs e) { Handle(e.Data); };
                process.ErrorDataReceived += delegate (object s, DataReceivedEventArgs e) { Handle(e.Data); };
                process.Exited += delegate
                {
                    int code = -1;
                    try { code = process.ExitCode; } catch { }
                    Log.Info("game exited with code " + code);
                    Action<int> handler = Exited;
                    if (handler != null) { try { handler(code); } catch { } }
                    CloseLog();
                };

                AppPaths.EnsureAll();
                _log = new StreamWriter(new FileStream(AppPaths.GameLog,
                    FileMode.Create, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8);
                _log.AutoFlush = true;

                if (!process.Start())
                {
                    // the log was opened for a process that never came up: closing it here keeps the
                    // file handle from being held until the next garbage collection
                    error = L.T("اجرای بازی ممکن نشد.", "Could not start the game.");
                    CloseLog();
                    return false;
                }
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                _process = process;
                StartedAt = DateTime.Now;
                Log.Info("game started, pid " + process.Id);
                return true;
            }
            catch (Exception ex)
            {
                error = ex.GetType().Name + ": " + ex.Message;
                Log.Error("game start failed", ex);
                return false;
            }
        }

        private void Handle(string line)
        {
            if (line == null) return;
            try { if (_log != null) _log.WriteLine(line); } catch { }
            Action<string> handler = OutputLine;
            if (handler != null) { try { handler(line); } catch { } }
            if (line.IndexOf("error", StringComparison.OrdinalIgnoreCase) >= 0 ||
                line.IndexOf("exception", StringComparison.OrdinalIgnoreCase) >= 0)
                Log.Warn("[game] " + line);
        }

        public void Kill()
        {
            try
            {
                if (_process != null && !_process.HasExited)
                {
                    _process.Kill();
                    Log.Info("game process terminated by request");
                }
            }
            catch { }
            try { if (_process != null) _process.Dispose(); } catch { }
            _process = null;
            CloseLog();
        }

        private void CloseLog()
        {
            try { if (_log != null) { _log.Flush(); _log.Dispose(); _log = null; } } catch { }
        }

        /// <summary>Process id of the java runtime that is actually running the client.</summary>
        public int FindJavaPid()
        {
            try
            {
                if (IsRunning) return _process.Id;
            }
            catch { }
            return -1;
        }
    }
}

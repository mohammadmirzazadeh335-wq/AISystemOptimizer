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
                _log = new StreamWriter(new FileStream(Path.Combine(AppPaths.Logs, "minecraft.log"),
                    FileMode.Create, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8);
                _log.AutoFlush = true;

                if (!process.Start())
                {
                    error = L.T("اجرای بازی ممکن نشد.", "Could not start the game.");
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

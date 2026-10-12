using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using ServerHelp.Core;
using ServerHelp.Net;

namespace ServerHelp.Tunnel
{
    /// <summary>
    /// A throwaway sing-box instance used to test one connection for real: it is started with a
    /// configuration that only opens a local SOCKS port (no TUN, no routes, no hosts, no firewall),
    /// so measuring a delay never changes anything on the machine.
    /// </summary>
    public sealed class ProbeTunnel : IDisposable
    {
        private Process _process;
        private string _configPath;
        private string _logPath;

        public int SocksPort { get; private set; }
        public string LastError = "";
        public string LogTail { get { return string.IsNullOrEmpty(_logPath) ? "" : LogFileTail(_logPath, 4000); } }

        /// <summary>Ports handed out to probes so a probe can never collide with the live session.</summary>
        private static int _next = 22460;

        public static int NextPort()
        {
            for (int attempt = 0; attempt < 200; attempt++)
            {
                int candidate = System.Threading.Interlocked.Increment(ref _next);
                if (candidate > 22560) { System.Threading.Interlocked.Exchange(ref _next, 22460); candidate = 22461; }
                if (IsFree(candidate)) return candidate;
            }
            return 22470;
        }

        public static bool IsFree(int port)
        {
            try
            {
                var listener = new TcpListener(IPAddress.Loopback, port);
                listener.Start();
                listener.Stop();
                return true;
            }
            catch { return false; }
        }

        /// <summary>
        /// Starts sing-box with the given configuration, moving its SOCKS inbound onto
        /// <paramref name="socksPort"/>. Returns false with a reason when it did not come up.
        /// </summary>
        public static bool TryStart(string configJson, int socksPort, int waitMs, out ProbeTunnel tunnel, out string error)
        {
            tunnel = null;
            error = "";

            if (!File.Exists(AppPaths.SingBoxExe))
            {
                error = L.T("موتور تونل (sing-box) موجود نیست؛ اول یک‌بار برنامه را اجرا کنید تا دانلود شود.",
                            "the tunnel engine (sing-box) is not available yet; run the app once so it can be fetched.");
                return false;
            }

            var probe = new ProbeTunnel();
            probe.SocksPort = socksPort;
            string id = Guid.NewGuid().ToString("N").Substring(0, 8);
            probe._configPath = Path.Combine(AppPaths.Cache, "probe-" + id + ".json");
            probe._logPath = Path.Combine(AppPaths.Logs, "probe-" + id + ".log");
            AppPaths.EnsureAll();

            try
            {
                // The configuration is validated first: a broken config must not look like a
                // broken proxy.
                File.WriteAllText(probe._configPath, configJson, new UTF8Encoding(false));
                var check = Shell.Run(AppPaths.SingBoxExe, "check -c " + Shell.Quote(probe._configPath), 20000);
                if (!check.Ok)
                {
                    error = L.T("کانفیگ پذیرفته نشد: ", "the configuration was rejected: ") + Shorten(check.All);
                    probe.Cleanup();
                    return false;
                }

                var psi = new ProcessStartInfo(AppPaths.SingBoxExe, "run -c " + Shell.Quote(probe._configPath))
                {
                    WorkingDirectory = AppPaths.Bin,
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
                var stderr = new StringBuilder();
                process.OutputDataReceived += delegate (object s, DataReceivedEventArgs e) { if (e.Data != null) stderr.AppendLine(e.Data); };
                process.ErrorDataReceived += delegate (object s, DataReceivedEventArgs e) { if (e.Data != null) stderr.AppendLine(e.Data); };
                if (!process.Start())
                {
                    error = L.T("اجرای موتور تونل ممکن نشد", "the tunnel engine could not be started");
                    probe.Cleanup();
                    return false;
                }
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                probe._process = process;

                // wait for the local SOCKS port to answer
                int waited = 0;
                while (waited < waitMs)
                {
                    if (process.HasExited)
                    {
                        error = L.T("تونل آزمایشی بلافاصله بسته شد: ", "the test tunnel exited immediately: ") + Shorten(stderr.ToString());
                        probe.Cleanup();
                        return false;
                    }
                    if (NetUtil.TcpPing(IPAddress.Loopback, socksPort, 400) > 0)
                    {
                        tunnel = probe;
                        return true;
                    }
                    System.Threading.Thread.Sleep(200);
                    waited += 200;
                }
                error = L.T("پورت محلی تونل بالا نیامد", "the local tunnel port never came up");
                probe.Cleanup();
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                probe.Cleanup();
                return false;
            }
        }

        /// <summary>Process id, or -1.</summary>
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

        public void Stop()
        {
            try
            {
                if (_process != null && !_process.HasExited)
                {
                    _process.Kill();
                    _process.WaitForExit(4000);
                }
            }
            catch (Exception ex) { Log.Debug("probe stop: " + ex.Message); }
            try { if (_process != null) _process.Dispose(); } catch { }
            _process = null;
            Cleanup();
        }

        public void Dispose()
        {
            Stop();
        }

        private void Cleanup()
        {
            try { if (!string.IsNullOrEmpty(_configPath) && File.Exists(_configPath)) File.Delete(_configPath); } catch { }
        }

        private static string Shorten(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            text = text.Replace("\r", " ").Replace("\n", " ").Trim();
            return text.Length <= 300 ? text : text.Substring(0, 300) + "…";
        }

        private static string LogFileTail(string path, int maxChars)
        {
            try
            {
                if (!File.Exists(path)) return "";
                string text = File.ReadAllText(path);
                return text.Length <= maxChars ? text : text.Substring(text.Length - maxChars);
            }
            catch { return ""; }
        }
    }
}

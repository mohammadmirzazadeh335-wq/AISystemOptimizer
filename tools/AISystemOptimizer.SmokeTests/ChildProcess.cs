using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

namespace AISystemOptimizer.SmokeTests
{
    /// <summary>
    /// Throwaway child processes used to test the application against something it is allowed to touch.
    ///
    /// The harness never terminates, closes or suspends a process it did not start. Everything that
    /// tests a destructive code path - the graceful close, the identity guard, the executor - is done
    /// against one of these.
    /// </summary>
    public static class ChildProcess
    {
        /// <summary>
        /// A long-lived process with no window and no output, used as a stand-in for a background
        /// helper. `ping` against the loopback address is used because it is present on every Windows
        /// installation, needs no input (unlike `timeout`, which refuses redirected input) and consumes
        /// no measurable CPU.
        /// </summary>
        public static Process SpawnQuiet(int seconds = 120)
        {
            try
            {
                var info = new ProcessStartInfo
                {
                    FileName = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                    Arguments = $"/c ping -n {seconds} 127.0.0.1 > nul",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                var process = Process.Start(info);

                if (process == null)
                    return null;

                // Wait until the pid is genuinely alive before the caller measures it.
                var started = CheckRunner.WaitUntil(() => !process.HasExited, TimeSpan.FromSeconds(5), 50);

                if (!started)
                {
                    try { process.Kill(); } catch { }
                    process.Dispose();
                    return null;
                }

                return process;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// A process that burns CPU for a while, so a per-process CPU reading has something to measure.
        /// </summary>
        public static Process SpawnBusy()
        {
            try
            {
                var info = new ProcessStartInfo
                {
                    FileName = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                    Arguments = "/c \"for /l %i in (1,1,2000000000) do @rem\"",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                var process = Process.Start(info);

                if (process == null)
                    return null;

                Thread.Sleep(400);
                return process;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// A windowed application, used to test the graceful-close path and the "in use" protection.
        /// </summary>
        public static Process SpawnWithWindow(string fileName, string arguments = "")
        {
            try
            {
                var info = new ProcessStartInfo
                {
                    FileName = fileName,
                    Arguments = arguments,
                    UseShellExecute = false
                };

                return Process.Start(info);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// End a child process without leaving anything behind. Used only on processes this harness
        /// started.
        /// </summary>
        public static void Abandon(Process process)
        {
            if (process == null)
                return;

            try
            {
                if (!process.HasExited)
                    process.Kill(entireProcessTree: true);
            }
            catch
            {
                // Already gone.
            }

            try { process.Dispose(); } catch { }
        }
    }
}

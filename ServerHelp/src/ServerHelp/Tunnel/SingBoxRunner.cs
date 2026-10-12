using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Tunnel
{
    /// <summary>
    /// Owns the bundled sing-box helper: unpacks it, generates keys, validates the configuration
    /// and runs/stops the tunnel process.
    /// </summary>
    public sealed class SingBoxRunner
    {
        public const string PinnedVersion = "1.14.3";

        /// <summary>
        /// sha256 of the archives this build accepts, read from the GitHub release asset digests and
        /// from the hash wintun.net publishes. The release workflow checks the same values before it
        /// bundles the engine; the app checks them again when it has to download one at run time, so a
        /// swapped archive is refused instead of being unpacked and run.
        /// </summary>
        public const string SingBoxZipSha256 = "d8b86ef58936dba9230ec6a57ffa4243933f3c14ef4809828b6c553440ed1518";
        public const string WintunZipSha256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51";
        public const string SingBoxZipUrl =
            "https://github.com/SagerNet/sing-box/releases/download/v" + PinnedVersion +
            "/sing-box-" + PinnedVersion + "-windows-amd64.zip";
        public const string WintunZipUrl = "https://www.wintun.net/builds/wintun-0.14.1.zip";

        private Process _process;
        private readonly object _gate = new object();
        private string _configPath = "";

        public int LastExitCode = int.MinValue;
        public string LastExitTime = "";
        public string LastStdErr = "";

        public bool IsRunning
        {
            get
            {
                lock (_gate)
                {
                    try { return _process != null && !_process.HasExited; }
                    catch { return false; }
                }
            }
        }

        public int Pid
        {
            get
            {
                lock (_gate)
                {
                    try { return _process != null && !_process.HasExited ? _process.Id : -1; }
                    catch { return -1; }
                }
            }
        }

        public bool HasSingBox { get { return File.Exists(AppPaths.SingBoxExe); } }
        public bool HasWintun { get { return File.Exists(AppPaths.WintunDll); } }

        /// <summary>Makes sure sing-box.exe (and wintun.dll, needed for the TUN interface) exist.</summary>
        public bool EnsureBinaries(bool allowDownload, Action<string> report, out string error)
        {
            error = "";
            AppPaths.EnsureAll();

            if (!File.Exists(AppPaths.SingBoxExe))
            {
                if (ExtractEmbedded("ServerHelp.bin.sing-box.exe", AppPaths.SingBoxExe))
                {
                    Log.Info("sing-box extracted from the bundled copy");
                    if (report != null) report(L.T("موتور تونل از نسخه همراه برنامه باز شد.", "Tunnel engine unpacked from the bundled copy."));
                }
                else if (allowDownload)
                {
                    try
                    {
                        if (report != null) report(L.T("دانلود موتور تونل (sing-box)…", "Downloading tunnel engine (sing-box)…"));
                        DownloadZipEntry(SingBoxZipUrl, "sing-box.exe", AppPaths.SingBoxExe, SingBoxZipSha256);
                        Log.Info("sing-box downloaded from " + SingBoxZipUrl);
                    }
                    catch (Exception ex)
                    {
                        error = L.T("دانلود sing-box ناموفق بود: ", "Could not download sing-box: ") + ex.Message;
                        Log.Error("sing-box download failed", ex);
                        return false;
                    }
                }
                else
                {
                    error = L.T("فایل sing-box.exe پیدا نشد.", "sing-box.exe was not found.");
                    return false;
                }
            }

            if (!File.Exists(AppPaths.WintunDll))
            {
                if (ExtractEmbedded("ServerHelp.bin.wintun.dll", AppPaths.WintunDll))
                {
                    Log.Info("wintun.dll extracted from the bundled copy");
                }
                else if (allowDownload)
                {
                    try
                    {
                        if (report != null) report(L.T("دانلود درایور شبکه (wintun)…", "Downloading network driver (wintun)…"));
                        DownloadZipEntry(WintunZipUrl, "wintun.dll", AppPaths.WintunDll, WintunZipSha256);
                        Log.Info("wintun.dll downloaded from " + WintunZipUrl);
                    }
                    catch (Exception ex)
                    {
                        // Not fatal: the tunnel can still run in proxy mode, and sing-box itself may
                        // find a wintun.dll elsewhere.
                        Log.Warn("wintun.dll download failed: " + ex.Message);
                    }
                }
            }
            return true;
        }

        private static bool ExtractEmbedded(string resourceName, string targetPath)
        {
            try
            {
                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream stream = asm.GetManifestResourceStream(resourceName))
                {
                    if (stream == null) return false;
                    Directory.CreateDirectory(Path.GetDirectoryName(targetPath));
                    using (var file = new FileStream(targetPath, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        var buffer = new byte[81920];
                        int read;
                        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0) file.Write(buffer, 0, read);
                    }
                    string hash = Sha256(targetPath);
                    Log.Info(Path.GetFileName(targetPath) + " written (" + Shell.HumanSize(new FileInfo(targetPath).Length) + ", sha256 " + hash.Substring(0, 16) + "…)");
                    return true;
                }
            }
            catch (Exception ex)
            {
                Log.Warn("could not extract " + resourceName + ": " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Downloads one file out of a release archive, after checking the archive against the hash
        /// this build pins. <paramref name="expectedSha256"/> may be empty for an archive with no pin.
        /// </summary>
        private static void DownloadZipEntry(string zipUrl, string entryName, string targetPath, string expectedSha256)
        {
            string tempZip = Path.Combine(AppPaths.Cache, "download-" + Guid.NewGuid().ToString("N").Substring(0, 8) + ".zip");
            Directory.CreateDirectory(AppPaths.Cache);
            try
            {
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                using (var client = new HttpClient())
                {
                    client.Timeout = TimeSpan.FromMinutes(5);
                    var task = client.GetByteArrayAsync(zipUrl);
                    task.Wait(300000);
                    File.WriteAllBytes(tempZip, task.Result);
                }
                if (!string.IsNullOrEmpty(expectedSha256))
                {
                    string actual = Sha256(tempZip);
                    if (!string.Equals(actual, expectedSha256, StringComparison.OrdinalIgnoreCase))
                    {
                        Log.Error("downloaded archive failed its sha256 check (got " + actual + ", want " +
                                  expectedSha256 + ")");
                        throw new Exception(L.T("هش فایل دانلود‌شده با مقدار مورد انتظار نمی‌خواند؛ فایل استفاده نشد.",
                                                "the downloaded file did not match the pinned hash, so it was not used."));
                    }
                    Log.Info("archive verified against the pinned sha256 (" + actual.Substring(0, 16) + "…)");
                }
                using (var archive = ZipFile.OpenRead(tempZip))
                {
                    ZipArchiveEntry found = null;
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        if (!string.Equals(Path.GetFileName(entry.FullName), entryName, StringComparison.OrdinalIgnoreCase)) continue;
                        // This app is 64 bit only, so an amd64 build always wins over arm64/x86 and
                        // over any nested legacy-windows-7 folder.
                        bool preferred = IsAmd64Entry(entry.FullName);
                        if (found == null || (preferred && !IsAmd64Entry(found.FullName))) found = entry;
                    }
                    if (found == null) throw new Exception(entryName + " is not inside the archive");
                    Directory.CreateDirectory(Path.GetDirectoryName(targetPath));
                    found.ExtractToFile(targetPath, true);
                }
            }
            finally
            {
                try { if (File.Exists(tempZip)) File.Delete(tempZip); } catch { }
            }
        }

        /// <summary>
        /// Kills a tunnel engine that an earlier session left behind. A crash takes the window with it,
        /// but not the child process - and such an engine still holds the machine's routing and the
        /// user's configuration. Only processes whose command line points at a configuration of ours
        /// are touched, and this runs while the app holds its single-instance lock, so nothing that
        /// belongs to a session in use can be hit. Returns how many were stopped.
        /// </summary>
        public static int KillStrayEngines()
        {
            int killed = 0;
            try
            {
                var script = new StringBuilder();
                script.Append("$ErrorActionPreference='Stop';");
                script.Append("foreach($p in @(Get-CimInstance Win32_Process -Filter \"Name='sing-box.exe'\")){");
                script.Append("$p.ProcessId.ToString() + '|' + [string]$p.CommandLine}");
                string encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script.ToString()));
                Shell.Result result = Shell.Run("powershell.exe",
                    "-NoProfile -NonInteractive -EncodedCommand " + encoded, 20000);
                if (!result.Ok)
                {
                    Log.Debug("stray engine check unavailable: " + result.All);
                    return 0;
                }
                foreach (int pid in OurEnginePids(result.StdOut))
                {
                    try
                    {
                        using (var process = System.Diagnostics.Process.GetProcessById(pid))
                        {
                            process.Kill();
                            killed++;
                            Log.Warn("stopped a tunnel engine left behind by an earlier run (pid " + pid + ")");
                        }
                    }
                    catch (Exception ex) { Log.Debug("could not stop pid " + pid + ": " + ex.Message); }
                }
            }
            catch (Exception ex) { Log.Debug("stray engine cleanup failed: " + ex.Message); }
            return killed;
        }

        /// <summary>
        /// The pids in a "pid|command line" listing that belong to this app: the command line has to
        /// point at a configuration inside our own data folder, and at a name only this app creates.
        /// Anything else that happens to be called sing-box.exe belongs to somebody else and is left
        /// alone. Kept separate from the lookup so the self test can pin that decision.
        /// </summary>
        public static List<int> OurEnginePids(string processList)
        {
            var pids = new List<int>();
            if (string.IsNullOrEmpty(processList)) return pids;
            string data = AppPaths.Data;
            foreach (string raw in processList.Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0) continue;
                int bar = line.IndexOf('|');
                if (bar <= 0) continue;
                int pid;
                if (!int.TryParse(line.Substring(0, bar).Trim(), out pid) || pid <= 0) continue;
                string command = line.Substring(bar + 1).Trim();
                if (command.IndexOf(data, StringComparison.OrdinalIgnoreCase) < 0) continue;
                bool ours = command.IndexOf("serverhelp-singbox.json", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            command.IndexOf("probe-", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!ours) continue;
                if (command.IndexOf(".json", StringComparison.OrdinalIgnoreCase) < 0) continue;
                pids.Add(pid);
            }
            return pids;
        }

        private static bool IsAmd64Entry(string fullName)
        {
            return fullName.IndexOf("amd64", StringComparison.OrdinalIgnoreCase) >= 0 ||
                   fullName.IndexOf("x64", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        public static string Sha256(string path)
        {
            try
            {
                using (var sha = SHA256.Create())
                using (var stream = File.OpenRead(path))
                {
                    byte[] hash = sha.ComputeHash(stream);
                    var sb = new StringBuilder();
                    foreach (byte b in hash) sb.Append(b.ToString("x2"));
                    return sb.ToString();
                }
            }
            catch { return ""; }
        }

        /// <summary>Generates a WireGuard key pair with sing-box itself (no crypto code of our own).</summary>
        public bool GenerateKeyPair(out string privateKey, out string publicKey, out string error)
        {
            privateKey = ""; publicKey = ""; error = "";
            var result = Shell.Run(AppPaths.SingBoxExe, "generate wg-keypair", 15000);
            if (!result.Ok)
            {
                error = L.T("تولید کلید ناموفق بود: ", "key generation failed: ") + result.All;
                return false;
            }
            foreach (string line in result.All.Replace("\r\n", "\n").Split('\n'))
            {
                if (line.StartsWith("PrivateKey:", StringComparison.Ordinal)) privateKey = line.Substring(11).Trim();
                if (line.StartsWith("PublicKey:", StringComparison.Ordinal)) publicKey = line.Substring(10).Trim();
            }
            if (privateKey.Length == 0 || publicKey.Length == 0)
            {
                error = L.T("خروجی تولید کلید قابل خواندن نبود: ", "unreadable key output: ") + result.All;
                return false;
            }
            return true;
        }

        /// <summary>Asks sing-box to validate a configuration before we start it.</summary>
        public bool Check(string configPath, out string output)
        {
            var result = Shell.Run(AppPaths.SingBoxExe, "check -c " + Shell.Quote(configPath), 20000);
            output = result.All;
            if (!result.Ok)
            {
                Log.Error("sing-box check failed: " + output);
                return false;
            }
            Log.Info("sing-box config check passed");
            return true;
        }

        public bool Start(string configPath, out string error)
        {
            error = "";
            Stop();
            try
            {
                var psi = new ProcessStartInfo(AppPaths.SingBoxExe, "run -c " + Shell.Quote(configPath))
                {
                    WorkingDirectory = AppPaths.Bin,   // wintun.dll must sit next to the exe
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
                process.OutputDataReceived += delegate (object s, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Log.Debug("[sing-box] " + e.Data);
                };
                process.ErrorDataReceived += delegate (object s, DataReceivedEventArgs e)
                {
                    if (e.Data != null)
                    {
                        LastStdErr = e.Data;
                        Log.Warn("[sing-box] " + e.Data);
                    }
                };
                if (!process.Start())
                {
                    error = L.T("اجرای sing-box ممکن نشد.", "Could not start sing-box.");
                    return false;
                }
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                lock (_gate) { _process = process; _configPath = configPath; }
                Log.Info("sing-box started, pid " + process.Id + ", config " + configPath);

                // A tunnel that dies within the first second is a configuration/permission problem,
                // so surface it right away instead of letting the caller guess.
                if (process.WaitForExit(900))
                {
                    error = L.T("تونل بلافاصله بسته شد: ", "the tunnel exited immediately: ") + LastStdErr;
                    lock (_gate) { _process = null; }
                    return false;
                }
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Error("sing-box start failed", ex);
                return false;
            }
        }

        public void Stop()
        {
            Process process;
            lock (_gate)
            {
                process = _process;
                _process = null;
            }
            if (process == null) return;
            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                    process.WaitForExit(5000);
                }
                LastExitCode = 0;
            }
            catch (Exception ex) { Log.Debug("stop: " + ex.Message); }
            try { process.Dispose(); } catch { }
            Log.Info("sing-box stopped");
        }

        /// <summary>Detects a tunnel that died on its own, so the UI can react.</summary>
        public bool DiedUnexpectedly(out string message)
        {
            message = "";
            Process process;
            lock (_gate) { process = _process; }
            if (process == null) return false;
            try
            {
                if (!process.HasExited) return false;
                LastExitCode = process.ExitCode;
                LastExitTime = DateTime.Now.ToString("HH:mm:ss");
                message = L.T("تونل بسته شد (کد ", "the tunnel exited (code ") + LastExitCode + ") " + LastStdErr;
                lock (_gate) { _process = null; }
                return true;
            }
            catch { return false; }
        }

        public string ConfigPath { get { return _configPath; } }
    }
}

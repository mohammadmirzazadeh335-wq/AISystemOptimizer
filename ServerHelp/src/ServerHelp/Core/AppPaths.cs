using System;
using System.IO;
using System.Reflection;

namespace ServerHelp.Core
{
    /// <summary>All file locations the app owns. Nothing is written outside this folder.</summary>
    public static class AppPaths
    {
        public static string Data
        {
            get
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "ServerHelp");
                return dir;
            }
        }

        public static string Bin { get { return Path.Combine(Data, "bin"); } }
        public static string Logs { get { return Path.Combine(Data, "logs"); } }
        public static string Backups { get { return Path.Combine(Data, "backups"); } }
        public static string Cache { get { return Path.Combine(Data, "cache"); } }

        public static string SettingsFile { get { return Path.Combine(Data, "settings.json"); } }
        /// <summary>Where the headless self test leaves its report for the build to read.</summary>
        public static string SelfTestReport { get { return Path.Combine(Data, "selftest.txt"); } }
        public static string WarpAccountFile { get { return Path.Combine(Data, "warp-account.json"); } }

        public static string SingBoxExe { get { return Path.Combine(Bin, "sing-box.exe"); } }
        public static string WintunDll { get { return Path.Combine(Bin, "wintun.dll"); } }
        public static string SingBoxConfig { get { return Path.Combine(Bin, "serverhelp-singbox.json"); } }
        public static string SingBoxLog { get { return Path.Combine(Logs, "sing-box.log"); } }
        public static string AppLog { get { return Path.Combine(Logs, "serverhelp.log"); } }
        /// <summary>Everything the game itself printed, kept so a launch that died can explain itself.</summary>
        public static string GameLog { get { return Path.Combine(Logs, "minecraft.log"); } }
        /// <summary>The written-down state of the machine and the app, made to be handed over.</summary>
        public static string DiagnosisFile { get { return Path.Combine(Logs, "diagnosis.txt"); } }

        public static string ExeDir
        {
            get
            {
                try
                {
                    var asm = Assembly.GetExecutingAssembly();
                    string loc = asm.Location;
                    if (!string.IsNullOrEmpty(loc)) return Path.GetDirectoryName(loc);
                }
                catch { }
                return Environment.CurrentDirectory;
            }
        }

        /// <summary>
        /// Removes throwaway files earlier runs left behind: a check copy written just before the
        /// machine was switched off, a half-downloaded archive, a probe log. Only files this app
        /// creates there are touched, and only ones older than an hour, so a second copy of the app
        /// that is measuring something right now keeps its own files.
        /// </summary>
        public static int CleanThrowaways()
        {
            return Sweep(Cache, new string[] { "probe-*.json", "probe-check-*.json", "download-*.zip" }) +
                   Sweep(Logs, new string[] { "probe-*.log" });
        }

        private static int Sweep(string folder, string[] patterns)
        {
            int removed = 0;
            try
            {
                if (!Directory.Exists(folder)) return 0;
                DateTime cutoff = DateTime.Now.AddHours(-1);
                foreach (string pattern in patterns)
                {
                    foreach (string path in Directory.GetFiles(folder, pattern))
                    {
                        try
                        {
                            if (File.GetLastWriteTime(path) > cutoff) continue;
                            File.Delete(path);
                            removed++;
                        }
                        catch { }
                    }
                }
            }
            catch { }
            return removed;
        }

        public static void EnsureAll()
        {
            Directory.CreateDirectory(Data);
            Directory.CreateDirectory(Bin);
            Directory.CreateDirectory(Logs);
            Directory.CreateDirectory(Backups);
            Directory.CreateDirectory(Cache);
        }
    }
}

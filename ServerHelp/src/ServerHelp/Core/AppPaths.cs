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

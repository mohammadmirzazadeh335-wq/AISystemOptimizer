using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    public sealed class JavaInstall
    {
        public string Path = "";       // javaw.exe
        public string JavaExe = "";    // java.exe, used for version checks
        public int Major;
        public string Version = "";
        public string Source = "";

        public string Display
        {
            get { return "Java " + (Major > 0 ? Major.ToString() : "?") + "  —  " + Path; }
        }
    }

    /// <summary>Finds Java runtimes: the ones TLauncher ships, Program Files installs and the registry.</summary>
    public static class JavaLocator
    {
        public static List<JavaInstall> Discover(string gameDir, string overridePath)
        {
            var found = new List<JavaInstall>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            if (!string.IsNullOrEmpty(overridePath))
            {
                var custom = FromJavaw(overridePath, "settings");
                if (custom != null) Add(found, seen, custom);
            }

            // 1. runtimes bundled with the launcher / inside the game folder
            if (!string.IsNullOrEmpty(gameDir))
            {
                foreach (string sub in new string[] { "runtime", "jre", "java", "bin" })
                {
                    string root = Path.Combine(gameDir, sub);
                    ScanForJavaw(root, 5, "game folder", found, seen);
                }
            }

            // 2. Program Files style installs
            string[] roots = new string[]
            {
                @"C:\Program Files\Java", @"C:\Program Files (x86)\Java",
                @"C:\Program Files\Eclipse Adoptium", @"C:\Program Files (x86)\Eclipse Adoptium",
                @"C:\Program Files\Microsoft", @"C:\Program Files\Zulu",
                @"C:\Program Files\BellSoft", @"C:\Program Files\Amazon Corretto",
                @"C:\Program Files\Semeru", @"C:\Program Files\Temurin",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Eclipse Adoptium"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Microsoft"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs"),
                @"C:\Program Files\Minecraft Launcher\runtime",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), ".minecraft", "runtime")
            };
            foreach (string root in roots) ScanForJavaw(root, 4, "installed", found, seen);

            // 3. registry
            Add(found, seen, FromRegistry(@"SOFTWARE\JavaSoft\JRE"));
            Add(found, seen, FromRegistry(@"SOFTWARE\JavaSoft\JDK"));
            Add(found, seen, FromRegistry(@"SOFTWARE\JavaSoft\Java Runtime Environment"));
            Add(found, seen, FromRegistry(@"SOFTWARE\JavaSoft\Java Development Kit"));
            Add(found, seen, FromRegistry(@"SOFTWARE\Eclipse Adoptium\JDK"));
            Add(found, seen, FromRegistry(@"SOFTWARE\Microsoft\JDK"));
            Add(found, seen, FromRegistry(@"SOFTWARE\Azul Systems\Zulu"));
            Add(found, seen, FromRegistry(@"SOFTWARE\Amazon Corretto\JDK"));

            // 4. PATH
            var where = Shell.Run("where", "javaw.exe", 8000);
            if (where.Ok)
            {
                foreach (string line in where.StdOut.Replace("\r\n", "\n").Split('\n'))
                {
                    string path = line.Trim();
                    if (path.Length == 0) continue;
                    Add(found, seen, FromJavaw(path, "PATH"));
                }
            }

            foreach (JavaInstall java in found)
            {
                if (java.Major == 0)
                {
                    string exe = java.JavaExe;
                    if (!Shell.FileExists(exe)) exe = Path.Combine(Path.GetDirectoryName(java.Path), "java.exe");
                    java.Major = ReadMajor(exe);
                }
            }
            found.Sort(delegate (JavaInstall a, JavaInstall b) { return a.Major.CompareTo(b.Major); });
            return found;
        }

        private static void Add(List<JavaInstall> list, HashSet<string> seen, JavaInstall java)
        {
            if (java == null || string.IsNullOrEmpty(java.Path)) return;
            string key;
            try { key = Path.GetFullPath(java.Path); } catch { key = java.Path; }
            if (!seen.Add(key)) return;
            list.Add(java);
        }

        private static void ScanForJavaw(string root, int depth, string source, List<JavaInstall> found, HashSet<string> seen)
        {
            try
            {
                if (string.IsNullOrEmpty(root) || !Directory.Exists(root) || depth < 0) return;
                string direct = Path.Combine(root, "bin", "javaw.exe");
                if (File.Exists(direct)) Add(found, seen, FromJavaw(direct, source));
                foreach (string dir in Directory.GetDirectories(root))
                {
                    if (depth == 0) continue;
                    ScanForJavaw(dir, depth - 1, source, found, seen);
                }
            }
            catch { }
        }

        private static JavaInstall FromJavaw(string javawPath, string source)
        {
            try
            {
                if (string.IsNullOrEmpty(javawPath)) return null;
                string normalized = javawPath.Trim().Trim('"');
                if (!Shell.FileExists(normalized))
                {
                    string alt = Path.Combine(normalized, "bin", "javaw.exe");
                    if (Shell.FileExists(alt)) normalized = alt;
                    else return null;
                }
                var java = new JavaInstall();
                java.Path = normalized;
                java.Source = source;
                string dir = Path.GetDirectoryName(normalized);
                java.JavaExe = Path.Combine(dir, "java.exe");
                return java;
            }
            catch { return null; }
        }

        private static JavaInstall FromRegistry(string keyPath)
        {
            try
            {
                foreach (RegistryKey root in new RegistryKey[] { Registry.LocalMachine, Registry.CurrentUser })
                {
                    foreach (bool view64 in new bool[] { true, false })
                    {
                        using (RegistryKey key = OpenKey(root, keyPath, view64))
                        {
                            if (key == null) continue;
                            foreach (string versionName in key.GetSubKeyNames())
                            {
                                using (RegistryKey version = key.OpenSubKey(versionName))
                                {
                                    if (version == null) continue;
                                    string home = version.GetValue("JavaHome") as string;
                                    if (string.IsNullOrEmpty(home))
                                    {
                                        string msi = version.GetValue("Path") as string;
                                        if (!string.IsNullOrEmpty(msi)) home = msi;
                                    }
                                    if (string.IsNullOrEmpty(home)) continue;
                                    var java = FromJavaw(Path.Combine(home, "bin", "javaw.exe"), "registry");
                                    if (java != null) return java;
                                }
                            }
                        }
                        string sub = keyPath + @"\hotspot\MSI";
                        using (RegistryKey msiKey = OpenKey(root, sub, view64))
                        {
                            if (msiKey != null)
                            {
                                string path = msiKey.GetValue("Path") as string;
                                if (!string.IsNullOrEmpty(path))
                                {
                                    var java = FromJavaw(Path.Combine(path, "bin", "javaw.exe"), "registry");
                                    if (java != null) return java;
                                }
                            }
                        }
                    }
                }
            }
            catch { }
            return null;
        }

        private static RegistryKey OpenKey(RegistryKey root, string path, bool view64)
        {
            try
            {
                if (view64) return root.OpenSubKey(path);
                if (!path.StartsWith("SOFTWARE", StringComparison.OrdinalIgnoreCase)) return null;
                return root.OpenSubKey(@"SOFTWARE\WOW6432Node" + path.Substring("SOFTWARE".Length));
            }
            catch { return null; }
        }

        /// <summary>Parses the major version out of "java -version" output.</summary>
        public static int ReadMajor(string javaExePath)
        {
            try
            {
                if (string.IsNullOrEmpty(javaExePath) || !Shell.FileExists(javaExePath)) return 0;
                var result = Shell.Run(javaExePath, "-version", 12000);
                string text = result.All;
                Match match = Regex.Match(text, "version \"([^\"]+)\"");
                if (!match.Success) match = Regex.Match(text, "openjdk (\\S+)");
                if (!match.Success) return 0;
                string version = match.Groups[1].Value;
                if (version.StartsWith("1.")) version = version.Substring(2);
                int dot = version.IndexOf('.');
                string major = dot > 0 ? version.Substring(0, dot) : version;
                int value;
                return int.TryParse(major, out value) ? value : 0;
            }
            catch { return 0; }
        }

        public static JavaInstall PickBest(List<JavaInstall> installs, int requiredMajor)
        {
            if (installs == null || installs.Count == 0) return null;
            if (requiredMajor > 0)
            {
                JavaInstall best = null;
                foreach (JavaInstall java in installs)
                {
                    if (java.Major < requiredMajor) continue;
                    if (best == null || java.Major < best.Major) best = java;   // closest newer version
                }
                if (best != null) return best;
                // nothing new enough: return the newest we have and let the caller warn
                JavaInstall newest = installs[0];
                foreach (JavaInstall java in installs) if (java.Major > newest.Major) newest = java;
                return newest;
            }
            // legacy version without a javaVersion field: 8 fits best, otherwise the lowest modern one
            int[] preference = new int[] { 8, 11, 17, 16, 7 };
            foreach (int major in preference)
            {
                foreach (JavaInstall java in installs) if (java.Major == major) return java;
            }
            return installs[0];
        }
    }
}

using System;
using System.Collections.Generic;
using System.IO;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    public sealed class McVersion
    {
        public string Id = "";
        public string Folder = "";
        public string JsonPath = "";
        public string JarPath = "";
        public string Type = "";
        public int RequiredJavaMajor = 0;
        public string AssetIndex = "";
        public bool HasJson;
        public string Error = "";

        public long JarSize
        {
            get
            {
                try { return Shell.FileExists(JarPath) ? new FileInfo(JarPath).Length : 0; }
                catch { return 0; }
            }
        }

        public string Display
        {
            get
            {
                string label = Id;
                if (!string.IsNullOrEmpty(Type) && Type != "release") label += "  [" + Type + "]";
                return label;
            }
        }

        public string Detail
        {
            get
            {
                var parts = new List<string>();
                if (RequiredJavaMajor > 0) parts.Add("Java " + RequiredJavaMajor + "+");
                if (JarSize > 0) parts.Add(Shell.HumanSize(JarSize));
                if (!HasJson) parts.Add(L.T("بدون فایل نسخه", "no version json"));
                if (!string.IsNullOrEmpty(Error)) parts.Add(Error);
                return string.Join("  |  ", parts.ToArray());
            }
        }
    }

    /// <summary>Finds the installed Minecraft versions (TLauncher keeps them in .minecraft\versions).</summary>
    public static class VersionScanner
    {
        public static List<string> CandidateRoots()
        {
            var roots = new List<string>();
            try
            {
                string roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                roots.Add(Path.Combine(roaming, ".minecraft"));
                roots.Add(Path.Combine(roaming, "minecraft"));
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                roots.Add(Path.Combine(local, ".minecraft"));
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                roots.Add(Path.Combine(profile, "AppData", "Roaming", ".minecraft"));
                roots.Add(Path.Combine(profile, "AppData", "Roaming", "minecraft"));
                roots.Add(Path.Combine(profile, ".minecraft"));
                // TLauncher portable layouts
                roots.Add(Path.Combine(roaming, "TLauncher"));
                roots.Add(Path.Combine(profile, "Desktop", ".minecraft"));
            }
            catch { }
            return roots;
        }

        /// <summary>First existing game directory, or an empty string.</summary>
        public static string DetectGameDir(string overrideDir)
        {
            if (!string.IsNullOrEmpty(overrideDir) && Directory.Exists(overrideDir)) return overrideDir;
            foreach (string root in CandidateRoots())
            {
                try
                {
                    if (Directory.Exists(root) && Directory.Exists(Path.Combine(root, "versions"))) return root;
                }
                catch { }
            }
            return "";
        }

        public static string ResolveVersionsDir(string gameDir, string overrideDir)
        {
            if (!string.IsNullOrEmpty(overrideDir))
            {
                string candidate = overrideDir;
                if (Directory.Exists(candidate)) return candidate;
            }
            string dir = DetectGameDir(gameDir);
            if (!string.IsNullOrEmpty(dir)) return Path.Combine(dir, "versions");
            return "";
        }

        public static List<McVersion> Scan(string versionsDir)
        {
            var list = new List<McVersion>();
            if (string.IsNullOrEmpty(versionsDir) || !Directory.Exists(versionsDir)) return list;

            string[] subfolders;
            try { subfolders = Directory.GetDirectories(versionsDir); }
            catch (Exception ex)
            {
                Log.Warn("cannot read " + versionsDir + ": " + ex.Message);
                return list;
            }

            foreach (string folder in subfolders)
            {
                var version = new McVersion();
                version.Folder = folder;
                version.Id = Path.GetFileName(folder);
                version.JsonPath = Path.Combine(folder, version.Id + ".json");
                version.JarPath = Path.Combine(folder, version.Id + ".jar");

                if (!Shell.FileExists(version.JsonPath))
                {
                    // some launchers name the json differently, take the first json in the folder
                    try
                    {
                        string[] jsons = Directory.GetFiles(folder, "*.json");
                        if (jsons.Length > 0) version.JsonPath = jsons[0];
                    }
                    catch { }
                }

                version.HasJson = Shell.FileExists(version.JsonPath);
                if (version.HasJson)
                {
                    try
                    {
                        var d = Json.ParseObject(File.ReadAllText(version.JsonPath, System.Text.Encoding.UTF8));
                        version.Type = Json.GetStr(d, "type", "");
                        string id = Json.GetStr(d, "id", version.Id);
                        if (!string.IsNullOrEmpty(id)) version.Id = id;

                        var javaVersion = Json.Obj(Json.Get(d, "javaVersion"));
                        if (javaVersion != null) version.RequiredJavaMajor = Json.GetInt(javaVersion, "majorVersion", 0);

                        var assetIndex = Json.Obj(Json.Get(d, "assetIndex"));
                        if (assetIndex != null) version.AssetIndex = Json.GetStr(assetIndex, "id", "");

                        // the folder name and the json id can differ (TLauncher modpacks); keep both paths valid
                        string jsonJar = Path.Combine(folder, Json.GetStr(d, "id", version.Id) + ".jar");
                        if (Shell.FileExists(jsonJar)) version.JarPath = jsonJar;
                    }
                    catch (Exception ex)
                    {
                        version.Error = L.T("فایل نسخه خوانده نشد", "version json could not be read");
                        Log.Warn("bad version json " + version.JsonPath + ": " + ex.Message);
                    }
                }
                else
                {
                    version.Error = L.T("بدون فایل نسخه", "no version json");
                }
                list.Add(version);
            }

            list.Sort(delegate (McVersion a, McVersion b) { return string.Compare(a.Id, b.Id, StringComparison.OrdinalIgnoreCase); });
            return list;
        }

        /// <summary>Nickname TLauncher remembers, so the user does not have to retype it.</summary>
        public static string GuessNickname(string gameDir)
        {
            try
            {
                if (string.IsNullOrEmpty(gameDir)) return "";
                string[] candidates = new string[]
                {
                    Path.Combine(gameDir, "TLauncherAdditional.json"),
                    Path.Combine(gameDir, "launcher_profiles.json"),
                    Path.Combine(gameDir, "TLauncherProfiles.json")
                };
                foreach (string file in candidates)
                {
                    if (!Shell.FileExists(file)) continue;
                    string text = File.ReadAllText(file, System.Text.Encoding.UTF8);
                    var d = Json.Obj(Json.Parse(text));
                    if (d == null) continue;
                    string nick = Json.GetStr(d, "username", null);
                    if (string.IsNullOrEmpty(nick)) nick = Json.GetStr(d, "name", null);
                    if (!string.IsNullOrEmpty(nick)) return nick;
                    var profiles = Json.Obj(Json.Get(d, "profiles"));
                    if (profiles != null)
                    {
                        foreach (var kv in profiles)
                        {
                            var pd = Json.Obj(kv.Value);
                            if (pd == null) continue;
                            string remember = Json.GetStr(pd, "name", null);
                            if (!string.IsNullOrEmpty(remember) && remember != "Latest release") return remember;
                        }
                    }
                }
            }
            catch (Exception ex) { Log.Debug("nickname guess failed: " + ex.Message); }
            return "";
        }
    }
}

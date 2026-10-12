using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Text.RegularExpressions;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    public sealed class LaunchPlan
    {
        public string JavaExe = "";
        public string Arguments = "";
        public string WorkingDirectory = "";
        public string VersionId = "";
        public string Nickname = "";
        public List<string> Notes = new List<string>();
        public string Classpath = "";
        public string NativesDir = "";
        public int MissingLibraries;
        public int DownloadedLibraries;

        public GamePlan Profile;                 // what we decided for this version (shown in the UI)

        public string CommandLine { get { return JavaExe + " " + Arguments; } }
    }

    /// <summary>
    /// Turns a version json into a real launch command: libraries, natives, assets, arguments and
    /// the JVM flags that keep the client smooth (Aikar's flags, memory sizing, UTF-8 for chat).
    /// </summary>
    public static class LaunchBuilder
    {
        public static LaunchPlan Build(McVersion version, string javawPath, string gameDir, string nickname,
                                       ServerProfile server, AppSettings settings, bool quickPlay, out string error)
        {
            return Build(version, javawPath, gameDir, nickname, server, settings, quickPlay, null, out error);
        }

        public static LaunchPlan Build(McVersion version, string javawPath, string gameDir, string nickname,
                                       ServerProfile server, AppSettings settings, bool quickPlay,
                                       List<string> extraJvmArgs, out string error)
        {
            return Build(version, javawPath, gameDir, nickname, server, settings, quickPlay, extraJvmArgs,
                         new GamePlan(), out error);
        }

        public static LaunchPlan Build(McVersion version, string javawPath, string gameDir, string nickname,
                                       ServerProfile server, AppSettings settings, bool quickPlay,
                                       List<string> extraJvmArgs, GamePlan precomputed, out string error)
        {
            error = "";
            var plan = new LaunchPlan();
            plan.JavaExe = javawPath;
            plan.WorkingDirectory = gameDir;
            plan.VersionId = version.Id;
            plan.Nickname = nickname;

            try
            {
                var root = Json.ParseObject(File.ReadAllText(version.JsonPath, Encoding.UTF8));

                // Forge / Fabric / OptiFine profiles only describe their own layer and point at a
                // parent version; the chain has to be merged or the client jar and the vanilla
                // libraries would be missing and the game would not start.
                string versionsDir = Path.GetDirectoryName(version.Folder);
                if (string.IsNullOrEmpty(versionsDir)) versionsDir = Path.Combine(gameDir, "versions");
                string inheritedJar;
                List<string> inheritedNotes;
                root = VersionResolver.Merge(root, versionsDir, out inheritedJar, out inheritedNotes);
                foreach (string note in inheritedNotes) plan.Notes.Add(note);

                string mainClass = Json.GetStr(root, "mainClass", "");
                if (string.IsNullOrEmpty(mainClass)) { error = L.T("فایل نسخه ناقص است (mainClass ندارد)", "version json is incomplete (no mainClass)"); return null; }

                string librariesDir = Path.Combine(gameDir, "libraries");
                string assetsDir = Path.Combine(gameDir, "assets");
                string nativesDir = Path.Combine(gameDir, "ServerHelp-natives", version.Id);
                plan.NativesDir = nativesDir;
                try
                {
                    if (Directory.Exists(nativesDir)) Directory.Delete(nativesDir, true);
                    Directory.CreateDirectory(nativesDir);
                }
                catch (Exception ex) { Log.Warn("natives folder: " + ex.Message); }

                // ---------------------------------------------------------- libraries
                var classpath = new List<string>();
                string versionJar = !string.IsNullOrEmpty(inheritedJar) ? inheritedJar
                                    : (Shell.FileExists(version.JarPath) ? version.JarPath : Path.Combine(version.Folder, version.Id + ".jar"));

                var libraries = Json.Arr(Json.Get(root, "libraries"));
                if (libraries != null)
                {
                    foreach (object item in libraries)
                    {
                        var library = Json.Obj(item);
                        if (library == null) continue;
                        if (!Allowed(Json.Arr(Json.Get(library, "rules")), null)) continue;

                        string relative = RelativeFromDownloads(library);
                        if (string.IsNullOrEmpty(relative)) relative = RelativeFromName(Json.GetStr(library, "name", ""));
                        if (string.IsNullOrEmpty(relative)) continue;

                        string fullPath = Path.Combine(librariesDir, relative.Replace('/', Path.DirectorySeparatorChar));
                        if (Shell.FileExists(fullPath))
                        {
                            if (!classpath.Contains(fullPath)) classpath.Add(fullPath);
                        }
                        else
                        {
                            plan.MissingLibraries++;
                            string url = ArtifactUrl(library);
                            if (!string.IsNullOrEmpty(url))
                            {
                                if (DownloadFile(url, fullPath)) { plan.DownloadedLibraries++; classpath.Add(fullPath); }
                            }
                        }

                        // legacy native bundles (the "natives" object) have to be unpacked
                        var natives = Json.Obj(Json.Get(library, "natives"));
                        if (natives != null)
                        {
                            string classifier = Json.GetStr(natives, "windows", null);
                            if (!string.IsNullOrEmpty(classifier))
                                ExtractNatives(library, classifier, nativesDir, librariesDir, plan);
                        }
                    }
                }

                if (!Shell.FileExists(versionJar))
                {
                    string clientUrl = Json.GetStr(Json.Obj(Json.Get(Json.Obj(Json.Get(root, "downloads")), "client")), "url", "");
                    if (!string.IsNullOrEmpty(clientUrl) && DownloadFile(clientUrl, versionJar))
                        plan.Notes.Add(L.T("فایل کلاینت دانلود شد", "client jar downloaded"));
                }
                if (Shell.FileExists(versionJar) && !classpath.Contains(versionJar)) classpath.Add(versionJar);
                else if (!Shell.FileExists(versionJar)) plan.Notes.Add(L.T("فایل کلاینت پیدا نشد", "client jar missing"));
                plan.Classpath = string.Join(";", classpath.ToArray());

                // ---------------------------------------------------------- placeholders
                string offlineUuid = Net.McPing.OfflineUuid(string.IsNullOrEmpty(nickname) ? "Player" : nickname);
                string assetIndex = version.AssetIndex;
                if (string.IsNullOrEmpty(assetIndex))
                {
                    var ai = Json.Obj(Json.Get(root, "assetIndex"));
                    if (ai != null) assetIndex = Json.GetStr(ai, "id", version.Id);
                    if (string.IsNullOrEmpty(assetIndex)) assetIndex = version.Id;
                }

                var values = new Dictionary<string, string>(StringComparer.Ordinal);
                values["${auth_player_name}"] = string.IsNullOrEmpty(nickname) ? "Player" : nickname;
                values["${version_name}"] = version.Id;
                values["${game_directory}"] = gameDir;
                values["${assets_root}"] = assetsDir;
                values["${assets_index_name}"] = assetIndex;
                values["${auth_uuid}"] = offlineUuid;
                values["${auth_access_token}"] = "0";
                values["${auth_session}"] = "0";
                values["${user_type}"] = "msa";
                values["${version_type}"] = string.IsNullOrEmpty(version.Type) ? "release" : version.Type;
                values["${user_properties}"] = "{}";
                values["${natives_directory}"] = nativesDir;
                values["${launcher_name}"] = "ServerHelp";
                values["${launcher_version}"] = "1.0.0";
                values["${classpath}"] = plan.Classpath;
                values["${classpath_separator}"] = ";";
                values["${library_directory}"] = librariesDir;
                values["${resolution_width}"] = "";
                values["${resolution_height}"] = "";
                values["${quickPlayPath}"] = "";
                values["${quickPlaySingleplayer}"] = "";
                values["${quickPlayMultiplayer}"] = "";
                values["${quickPlayRealms}"] = "";
                values["${clientid}"] = "serverhelp";
                values["${auth_xuid}"] = "0";

                var features = new Dictionary<string, bool>(StringComparer.Ordinal);
                features["is_demo_user"] = false;
                features["has_custom_resolution"] = false;
                features["has_quick_plays_support"] = quickPlay;
                features["is_quick_play_singleplayer"] = false;
                features["is_quick_play_multiplayer"] = quickPlay;
                features["is_quick_play_realms"] = false;

                var gameArgs = new List<string>();
                var jvmArgs = new List<string>();

                var arguments = Json.Obj(Json.Get(root, "arguments"));
                if (arguments != null)
                {
                    AddArguments(jvmArgs, Json.Arr(Json.Get(arguments, "jvm")), values, features);
                    AddArguments(gameArgs, Json.Arr(Json.Get(arguments, "game")), values, features);
                }
                else
                {
                    string legacy = Json.GetStr(root, "minecraftArguments", "");
                    if (!string.IsNullOrEmpty(legacy))
                    {
                        foreach (string piece in SplitQuoted(legacy)) gameArgs.Add(Replace(piece, values));
                    }
                }

                // ---------------------------------------------------------- our own JVM flags
                if (!string.IsNullOrEmpty(nativesDir)) jvmArgs.Insert(0, "-Djava.library.path=" + nativesDir);
                jvmArgs.Insert(0, "-Dorg.lwjgl.system.SharedLibraryExtractPath=" + nativesDir);
                jvmArgs.Insert(0, "-Dio.netty.native.workdir=" + nativesDir);
                jvmArgs.Insert(0, "-Dfile.encoding=UTF-8");

                int javaMajor = JavaLocator.ReadMajor(javawPath);
                if (javaMajor <= 0 && version != null) javaMajor = version.RequiredJavaMajor;
                var libraryNames = new List<string>();
                if (libraries != null)
                    foreach (object item in libraries)
                    {
                        var lib = Json.Obj(item);
                        if (lib != null) libraryNames.Add(Json.GetStr(lib, "name", ""));
                    }

                // ---- one version aware profile decides memory, collector and the loader flags
                GamePlan profile = precomputed;
                if (profile == null || profile.Flags.Count == 0 && profile.HeapMb == 0)
                    profile = GameProfiler.Build(version, settings, server, gameDir, javaMajor, libraryNames);
                if (!settings.UseAikarFlags)
                {
                    // The profiler already keeps the tuning flags out when this is off, so the preview
                    // in the UI matches the command line. This is the safety net for a profile that was
                    // built somewhere else - except for a switch the user ticked himself.
                    profile.Flags.Clear();
                    if (settings.OpenGlPipeline) profile.Flags.Add("-Dsun.java2d.opengl=true");
                }
                List<string> wanted = GameProfiler.Deduplicate(jvmArgs, profile.Flags);
                if (wanted.Count < profile.Flags.Count)
                    profile.Applied.Add(L.T("پرچم‌های تکراری کانفیگ نسخه نادیده گرفته شد",
                                            "flags the version config already sets were skipped"));
                jvmArgs.InsertRange(0, wanted);
                jvmArgs.Insert(0, "-Xms" + profile.InitialHeapMb + "M");
                jvmArgs.Insert(0, "-Xmx" + profile.HeapMb + "M");
                plan.Profile = profile;
                // Extra flags from the pipeline (for example the local SOCKS port of a proxy route,
                // which the game needs when no TUN interface could be created).
                if (extraJvmArgs != null)
                {
                    foreach (string extra in extraJvmArgs)
                        if (!string.IsNullOrEmpty(extra)) jvmArgs.Insert(0, extra);
                }
                if (!string.IsNullOrEmpty(settings.ExtraJvmArgs))
                {
                    foreach (string extra in SplitQuoted(settings.ExtraJvmArgs)) jvmArgs.Insert(0, extra);
                }
                plan.Notes.Add(L.T("حافظه: ", "RAM: ") + L.N(profile.HeapMb) + " MB");

                // ---------------------------------------------------------- server entry
                if (quickPlay && server != null)
                {
                    // --quickPlayMultiplayer exists since 1.20; older clients use --server/--port and
                    // would refuse to start when handed an argument they do not know.
                    bool useQuickPlay = VersionResolver.SupportsQuickPlay(version.Id);
                    string host = server.PreferDomain || string.IsNullOrEmpty(server.DirectIp) ? server.Host : server.DirectIp;
                    if (useQuickPlay)
                    {
                        string target = host + ":" + server.Port.ToString(CultureInfo.InvariantCulture);
                        gameArgs.Add("--quickPlayMultiplayer");
                        gameArgs.Add(target);
                    }
                    else
                    {
                        gameArgs.Add("--server");
                        gameArgs.Add(host);
                        gameArgs.Add("--port");
                        gameArgs.Add(server.Port.ToString(CultureInfo.InvariantCulture));
                    }
                    plan.Notes.Add(L.T("ورود خودکار به ", "auto join ") + server.Endpoint);
                }

                // ---------------------------------------------------------- assemble
                var all = new List<string>();
                all.AddRange(jvmArgs);
                all.Add("-cp");
                all.Add(plan.Classpath);
                all.Add(mainClass);
                all.AddRange(gameArgs);

                var sb = new StringBuilder();
                foreach (string arg in all)
                {
                    if (arg == null) continue;
                    if (arg.Length == 0) continue;
                    if (sb.Length > 0) sb.Append(' ');
                    sb.Append(Shell.Quote(arg));
                }
                plan.Arguments = sb.ToString();
                Log.Info("launch plan: java=" + javawPath + " version=" + version.Id + " libs=" + classpath.Count +
                         " missing=" + plan.MissingLibraries + " downloaded=" + plan.DownloadedLibraries);
                return plan;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Error("could not build the launch command", ex);
                return null;
            }
        }

        // ------------------------------------------------------------------ helpers

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct MemoryStatusEx
        {
            public uint Length;
            public uint MemoryLoad;
            public ulong TotalPhys;
            public ulong AvailPhys;
            public ulong TotalPageFile;
            public ulong AvailPageFile;
            public ulong TotalVirtual;
            public ulong AvailVirtual;
            public ulong AvailExtendedVirtual;
        }

        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = false)]
        private static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx buffer);

        public static long TotalPhysicalMemoryBytes()
        {
            try
            {
                var status = new MemoryStatusEx();
                status.Length = (uint)System.Runtime.InteropServices.Marshal.SizeOf(typeof(MemoryStatusEx));
                if (GlobalMemoryStatusEx(ref status)) return (long)status.TotalPhys;
            }
            catch { }
            return 0;
        }

        public static int RecommendHeapMb()
        {
            try
            {
                long totalMb = TotalPhysicalMemoryBytes() / (1024 * 1024);
                if (totalMb <= 0) return 2048;
                if (totalMb < 6000) return 1536;
                if (totalMb < 8000) return 2048;
                if (totalMb < 12000) return 3072;
                if (totalMb < 16000) return 4096;
                return 6144;
            }
            catch { return 2048; }
        }

        public static List<string> AikarFlags()
        {
            return new List<string>(new string[]
            {
                "-XX:+UseG1GC",
                "-XX:+ParallelRefProcEnabled",
                "-XX:MaxGCPauseMillis=40",
                "-XX:+UnlockExperimentalVMOptions",
                "-XX:+DisableExplicitGC",
                "-XX:G1NewSizePercent=30",
                "-XX:G1MaxNewSizePercent=40",
                "-XX:G1HeapRegionSize=8M",
                "-XX:G1ReservePercent=20",
                "-XX:G1HeapWastePercent=5",
                "-XX:G1MixedGCCountTarget=4",
                "-XX:InitiatingHeapOccupancyPercent=15",
                "-XX:G1MixedGCLiveThresholdPercent=90",
                "-XX:G1RSetUpdatingPauseTimePercent=5",
                "-XX:SurvivorRatio=32",
                "-XX:+PerfDisableSharedMem",
                "-XX:MaxTenuringThreshold=1",
                "-Daikars.new.flags=true"
            });
        }

        private static string RelativeFromDownloads(Dictionary<string, object> library)
        {
            var downloads = Json.Obj(Json.Get(library, "downloads"));
            if (downloads == null) return "";
            var artifact = Json.Obj(Json.Get(downloads, "artifact"));
            if (artifact == null) return "";
            return Json.GetStr(artifact, "path", "");
        }

        private static string ArtifactUrl(Dictionary<string, object> library)
        {
            var downloads = Json.Obj(Json.Get(library, "downloads"));
            if (downloads == null) return "";
            var artifact = Json.Obj(Json.Get(downloads, "artifact"));
            if (artifact == null) return "";
            return Json.GetStr(artifact, "url", "");
        }

        private static string RelativeFromName(string name)
        {
            try
            {
                if (string.IsNullOrEmpty(name)) return "";
                string[] parts = name.Split(':');
                if (parts.Length < 3) return "";
                string extension = parts.Length > 3 ? parts[3] : "jar";
                string group = parts[0].Replace('.', '/');
                return group + "/" + parts[1] + "/" + parts[2] + "/" + parts[1] + "-" + parts[2] + "." + extension;
            }
            catch { return ""; }
        }

        private static void ExtractNatives(Dictionary<string, object> library, string classifier, string nativesDir,
                                           string librariesDir, LaunchPlan plan)
        {
            try
            {
                var downloads = Json.Obj(Json.Get(library, "downloads"));
                if (downloads == null) return;
                var classifiers = Json.Obj(Json.Get(downloads, "classifiers"));
                if (classifiers == null) return;
                var info = Json.Obj(Json.Get(classifiers, classifier));
                if (info == null) return;
                string relative = Json.GetStr(info, "path", "");
                if (string.IsNullOrEmpty(relative)) return;
                string jar = Path.Combine(librariesDir, relative.Replace('/', Path.DirectorySeparatorChar));
                if (!Shell.FileExists(jar))
                {
                    string url = Json.GetStr(info, "url", "");
                    if (!string.IsNullOrEmpty(url)) DownloadFile(url, jar);
                }
                if (!Shell.FileExists(jar)) return;

                var exclude = new List<string>(new string[] { "META-INF/" });
                var extract = Json.Obj(Json.Get(library, "extract"));
                if (extract != null)
                {
                    var list = Json.StrList(Json.Get(extract, "exclude"));
                    if (list.Count > 0) exclude = list;
                }

                using (var archive = ZipFile.OpenRead(jar))
                {
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        if (string.IsNullOrEmpty(entry.Name)) continue;
                        bool skip = false;
                        foreach (string prefix in exclude)
                            if (entry.FullName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) skip = true;
                        if (skip) continue;
                        if (!entry.Name.EndsWith(".dll", StringComparison.OrdinalIgnoreCase) &&
                            !entry.Name.EndsWith(".so", StringComparison.OrdinalIgnoreCase) &&
                            !entry.Name.Contains(".")) continue;
                        string target = Path.Combine(nativesDir, entry.Name);
                        try { entry.ExtractToFile(target, true); }
                        catch { }
                    }
                }
            }
            catch (Exception ex) { Log.Debug("natives extract: " + ex.Message); }
        }

        private static bool DownloadFile(string url, string targetPath)
        {
            try
            {
                if (string.IsNullOrEmpty(url)) return false;
                string attempt = url;
                if (attempt.Contains("://")) attempt = attempt.Replace("http://", "https://");
                Directory.CreateDirectory(Path.GetDirectoryName(targetPath));
                var task = Net.NetUtil.Http.GetByteArrayAsync(attempt);
                if (!task.Wait(20000)) return false;
                File.WriteAllBytes(targetPath, task.Result);
                Log.Info("downloaded " + Path.GetFileName(targetPath));
                return true;
            }
            catch (Exception ex)
            {
                Log.Warn("library download failed (" + url + "): " + ex.Message);
                return false;
            }
        }

        private static void AddArguments(List<string> target, List<object> source, Dictionary<string, string> values,
                                         Dictionary<string, bool> features)
        {
            if (source == null) return;
            foreach (object item in source)
            {
                if (item is string)
                {
                    string text = Replace((string)item, values);
                    if (!string.IsNullOrEmpty(text)) target.Add(text);
                    continue;
                }
                var obj = Json.Obj(item);
                if (obj == null) continue;
                if (!Allowed(Json.Arr(Json.Get(obj, "rules")), features)) continue;
                object value = Json.Get(obj, "value");
                if (value is string)
                {
                    string text = Replace((string)value, values);
                    if (!string.IsNullOrEmpty(text)) target.Add(text);
                }
                else
                {
                    var list = Json.Arr(value);
                    if (list != null)
                    {
                        foreach (object entry in list)
                        {
                            if (!(entry is string)) continue;
                            string text = Replace((string)entry, values);
                            if (!string.IsNullOrEmpty(text)) target.Add(text);
                        }
                    }
                }
            }
        }

        private static string Replace(string text, Dictionary<string, string> values)
        {
            if (string.IsNullOrEmpty(text)) return text;
            foreach (var kv in values)
            {
                if (text.IndexOf(kv.Key, StringComparison.Ordinal) >= 0)
                    text = text.Replace(kv.Key, kv.Value);
            }
            // an argument that was nothing but a placeholder we do not know about gets dropped
            if (text.StartsWith("${", StringComparison.Ordinal) && text.EndsWith("}", StringComparison.Ordinal)) return "";
            return text;
        }

        /// <summary>Vanilla rule evaluation, including os and feature conditions.</summary>
        public static bool Allowed(List<object> rules, Dictionary<string, bool> features)
        {
            if (rules == null || rules.Count == 0) return true;
            bool result = false;
            foreach (object item in rules)
            {
                var rule = Json.Obj(item);
                if (rule == null) continue;
                if (!RuleMatches(rule, features)) continue;
                result = string.Equals(Json.GetStr(rule, "action", "allow"), "allow", StringComparison.OrdinalIgnoreCase);
            }
            return result;
        }

        private static bool RuleMatches(Dictionary<string, object> rule, Dictionary<string, bool> features)
        {
            var os = Json.Obj(Json.Get(rule, "os"));
            if (os != null)
            {
                string name = Json.GetStr(os, "name", "");
                if (!string.IsNullOrEmpty(name) &&
                    !string.Equals(name, "windows", StringComparison.OrdinalIgnoreCase)) return false;
                string arch = Json.GetStr(os, "arch", "");
                if (!string.IsNullOrEmpty(arch))
                {
                    bool x64 = Environment.Is64BitOperatingSystem;
                    if (string.Equals(arch, "x86", StringComparison.OrdinalIgnoreCase) && x64) return false;
                    if (string.Equals(arch, "x86_64", StringComparison.OrdinalIgnoreCase) && !x64) return false;
                }
                string version = Json.GetStr(os, "version", "");
                if (!string.IsNullOrEmpty(version) && !VersionMatches(version)) return false;
            }

            var feat = Json.Obj(Json.Get(rule, "features"));
            if (feat != null && features != null)
            {
                foreach (var kv in feat)
                {
                    bool required = kv.Value is bool ? (bool)kv.Value : false;
                    bool actual;
                    if (!features.TryGetValue(kv.Key, out actual)) actual = false;
                    if (required != actual) return false;
                }
            }
            return true;
        }

        private static bool VersionMatches(string expression)
        {
            try
            {
                string osVersion = Environment.OSVersion.Version.ToString();
                Match match = Regex.Match(expression, "^\\s*(>=|<=|>|<|=)?\\s*([0-9.]+)");
                if (!match.Success) return true;   // unknown pattern: do not block the argument
                string op = match.Groups[1].Value;
                string wanted = match.Groups[2].Value;
                Version a = ParseVersion(osVersion);
                Version b = ParseVersion(wanted);
                if (a == null || b == null) return true;
                int cmp = a.CompareTo(b);
                switch (op)
                {
                    case ">=": return cmp >= 0;
                    case "<=": return cmp <= 0;
                    case ">": return cmp > 0;
                    case "<": return cmp < 0;
                    case "=": return cmp == 0;
                    default: return true;
                }
            }
            catch { return true; }
        }

        private static Version ParseVersion(string text)
        {
            try
            {
                string[] parts = text.Split('.');
                var numbers = new List<int>();
                foreach (string part in parts)
                {
                    int value;
                    if (!int.TryParse(part, out value)) break;
                    numbers.Add(value);
                }
                while (numbers.Count < 4) numbers.Add(0);
                return new Version(numbers[0], numbers[1], numbers[2], numbers[3]);
            }
            catch { return null; }
        }

        public static List<string> SplitQuoted(string text)
        {
            var result = new List<string>();
            if (string.IsNullOrEmpty(text)) return result;
            var current = new StringBuilder();
            bool inQuotes = false;
            foreach (char c in text)
            {
                if (c == '"') { inQuotes = !inQuotes; continue; }
                if (c == ' ' && !inQuotes)
                {
                    if (current.Length > 0) { result.Add(current.ToString()); current.Length = 0; }
                    continue;
                }
                current.Append(c);
            }
            if (current.Length > 0) result.Add(current.ToString());
            return result;
        }
    }
}

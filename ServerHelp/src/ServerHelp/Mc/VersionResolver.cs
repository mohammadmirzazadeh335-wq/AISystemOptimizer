using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    /// <summary>
    /// TLauncher ships modded profiles (Forge / Fabric / OptiFine) whose version json only describes
    /// its own libraries and points at a parent with "inheritsFrom". Starting the game from such a
    /// json alone would miss the real main class, the vanilla libraries and the client jar, so the
    /// chain is merged here the same way the official launcher does it.
    /// </summary>
    public static class VersionResolver
    {
        /// <summary>Merges a version json with its inheritsFrom parents and reports the client jar.</summary>
        public static Dictionary<string, object> Merge(Dictionary<string, object> child, string versionsDir,
                                                      out string clientJar, out List<string> notes)
        {
            clientJar = "";
            notes = new List<string>();

            var chain = new List<Dictionary<string, object>>();
            var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var current = child;
            string firstJsonPath = null;

            while (current != null)
            {
                chain.Add(current);
                string parent = Json.GetStr(current, "inheritsFrom", "");
                if (string.IsNullOrEmpty(parent)) break;
                string parentJson = Path.Combine(versionsDir, parent, parent + ".json");
                if (!Shell.FileExists(parentJson)) parentJson = FirstJsonIn(Path.Combine(versionsDir, parent));
                if (string.IsNullOrEmpty(parentJson) || !visited.Add(parentJson)) break;
                var d = null as Dictionary<string, object>;
                try { d = Json.ParseObject(File.ReadAllText(parentJson, Encoding.UTF8)); }
                catch (Exception ex) { Log.Warn("parent version " + parent + " could not be read: " + ex.Message); }
                if (d == null) break;
                if (chain.Count == 1) firstJsonPath = parentJson;
                current = d;
            }

            if (chain.Count > 1) notes.Add(L.T("نسخه ترکیبی (", "inherited profile (") + Json.GetStr(child, "inheritsFrom", "") + ")");

            // ---------------------------------------------------------------- merge (child wins)
            var merged = new Dictionary<string, object>(StringComparer.Ordinal);
            for (int i = chain.Count - 1; i >= 0; i--)
            {
                var layer = chain[i];
                foreach (var pair in layer)
                {
                    string key = pair.Key;
                    if (key == "libraries" || key == "arguments")
                    {
                        // handled below
                        continue;
                    }
                    if (key == "inheritsFrom") continue;
                    if (pair.Value == null) continue;
                    merged[key] = pair.Value;
                }
            }

            // libraries: keep the parent order, let the child override by artifact name
            var libraries = new List<object>();
            var indexByName = new Dictionary<string, int>(StringComparer.Ordinal);
            for (int i = chain.Count - 1; i >= 0; i--)
            {
                var list = Json.Arr(Json.Get(chain[i], "libraries"));
                if (list == null) continue;
                foreach (object item in list)
                {
                    var lib = Json.Obj(item);
                    if (lib == null) continue;
                    string name = Json.GetStr(lib, "name", "");
                    if (name.Length == 0) { libraries.Add(item); continue; }
                    int existing;
                    if (indexByName.TryGetValue(name, out existing)) libraries[existing] = item;
                    else { indexByName[name] = libraries.Count; libraries.Add(item); }
                }
            }
            merged["libraries"] = libraries;

            // arguments: parent first, then the child (that is what the official launcher does)
            var jvm = new List<object>();
            var game = new List<object>();
            bool hasArguments = false;
            for (int i = chain.Count - 1; i >= 0; i--)
            {
                var args = Json.Obj(Json.Get(chain[i], "arguments"));
                if (args == null) continue;
                hasArguments = true;
                var j = Json.Arr(Json.Get(args, "jvm"));
                if (j != null) jvm.AddRange(j);
                var g = Json.Arr(Json.Get(args, "game"));
                if (g != null) game.AddRange(g);
            }
            if (hasArguments)
            {
                var arguments = new Dictionary<string, object>(StringComparer.Ordinal);
                if (jvm.Count > 0) arguments["jvm"] = jvm;
                if (game.Count > 0) arguments["game"] = game;
                merged["arguments"] = arguments;
            }

            // ---------------------------------------------------------------- client jar
            for (int i = 0; i < chain.Count; i++)
            {
                string layerId = Json.GetStr(chain[i], "id", "");
                if (string.IsNullOrEmpty(layerId)) continue;
                string candidate = Path.Combine(Path.Combine(versionsDir, layerId), layerId + ".jar");
                if (Shell.FileExists(candidate)) { clientJar = candidate; break; }
            }
            if (string.IsNullOrEmpty(clientJar) && !string.IsNullOrEmpty(firstJsonPath))
            {
                string parentId = Json.GetStr(chain[1], "id", "");
                if (parentId.Length > 0)
                {
                    string candidate = Path.Combine(Path.GetDirectoryName(firstJsonPath), parentId + ".jar");
                    if (Shell.FileExists(candidate)) clientJar = candidate;
                }
            }

            return merged;
        }

        private static string FirstJsonIn(string folder)
        {
            try
            {
                if (!Directory.Exists(folder)) return "";
                string[] files = Directory.GetFiles(folder, "*.json");
                return files.Length > 0 ? files[0] : "";
            }
            catch { return ""; }
        }

        /// <summary>Turns "1.21.1-forge-51.0.33" or "fabric-loader-0.15.11-1.20.1" into a version number.</summary>
        public static bool TryParseGameVersion(string id, out int major, out int minor)
        {
            major = 0; minor = 0;
            if (string.IsNullOrEmpty(id)) return false;
            var match = System.Text.RegularExpressions.Regex.Match(id, @"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?");
            if (!match.Success) return false;
            // "fabric-loader-0.15.11-1.20.1" and "forge-51.0.33-1.21.1" hide the game version later in
            // the string, so scan every match and prefer one that looks like a Minecraft release.
            var all = System.Text.RegularExpressions.Regex.Matches(id, @"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?");
            foreach (System.Text.RegularExpressions.Match m in all)
            {
                int a = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                int b = int.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
                if (a == 1 && b >= 0 && b <= 30) { major = a; minor = b; return true; }
            }
            major = int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture);
            minor = int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture);
            return true;
        }

        /// <summary>True when the client understands --quickPlayMultiplayer (Minecraft 1.20 and newer).</summary>
        public static bool SupportsQuickPlay(string versionId)
        {
            int major, minor;
            if (!TryParseGameVersion(versionId, out major, out minor)) return false;
            if (major > 1) return true;
            return minor >= 20;
        }
    }
}

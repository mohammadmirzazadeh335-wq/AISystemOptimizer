using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using ServerHelp.Core;

namespace ServerHelp.Mc
{
    /// <summary>
    /// The optimisation decision for one Minecraft version on this machine: how much memory to
    /// give it, which collector, which loader specific flags, what is broken in the folder.
    /// Everything here is a visible list of reasons, so the user can see what the app will do
    /// before pressing play instead of trusting a black box.
    /// </summary>
    public sealed class GamePlan
    {
        public string VersionId = "";
        public string Loader = "vanilla";
        public int JavaMajor;
        public int HeapMb;
        public int InitialHeapMb;
        public bool G1;
        public bool FlagsOn = true;         // false when "JVM tuning flags" is switched off
        public List<string> Flags = new List<string>();       // what we add to the JVM
        public List<string> Applied = new List<string>();     // human readable "why"
        public List<string> Warnings = new List<string>();
        public int LibrariesPresent;
        public int LibrariesMissing;
        public bool AssetsReady = true;
        public bool NativesReady = true;

        /// <summary>A short block of text for the UI and the log.</summary>
        public string Summary()
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine(L.T("نسخه: ", "version: ") + VersionId + " • " + Loader);
            sb.AppendLine(L.T("حافظه: ", "memory: ") + HeapMb + " MB (" + L.T("شروع ", "initial ") + InitialHeapMb + " MB)" +
                          (FlagsOn ? " • " + (G1 ? "G1GC" : "CMS") : ""));
            if (JavaMajor > 0) sb.AppendLine(L.T("جاوا: ", "java: ") + JavaMajor);
            sb.AppendLine(L.T("کتابخانه: ", "libraries: ") + LibrariesPresent + L.T(" آماده", " ready") +
                          (LibrariesMissing > 0 ? L.T(" • ", " • ") + LibrariesMissing + L.T(" جاافتاده (خودکار دانلود می‌شود)",
                                                                                        " missing (downloaded automatically)") : ""));
            if (!AssetsReady) sb.AppendLine(L.T("هشدار: پوشه assets کامل نیست؛ بازی ممکن است دیر لود شود.",
                                                "warning: the assets folder looks incomplete; the game may load slowly."));
            if (!NativesReady) sb.AppendLine(L.T("هشدار: فایل‌های native نسخه پیدا نشد.",
                                                 "warning: the version's native files were not found."));
            foreach (string warning in Warnings) sb.AppendLine("⚠ " + warning);
            foreach (string applied in Applied) sb.AppendLine("• " + applied);
            return sb.ToString().TrimEnd();
        }
    }

    /// <summary>Decides the launch profile for a version: loader, memory, collector and flags.</summary>
    public static class GameProfiler
    {
        /// <summary>Which mod loader a version folder carries, guessed from its id and its libraries.</summary>
        public static string DetectLoader(McVersion version, List<string> libraryNames)
        {
            string text = (version == null ? "" : version.Id + " " + version.Type) .ToLowerInvariant();
            string joined = libraryNames == null ? "" : string.Join(" ", libraryNames.ToArray()).ToLowerInvariant();
            if (text.Contains("neoforge") || joined.Contains("neoforge")) return "neoforge";
            if (text.Contains("forge") || joined.Contains("net.minecraftforge")) return "forge";
            if (text.Contains("quilt") || joined.Contains("quiltmc")) return "quilt";
            if (text.Contains("fabric") || joined.Contains("fabricmc")) return "fabric";
            if (text.Contains("optifine") || joined.Contains("optifine")) return "optifine";
            if (text.Contains("labymod") || joined.Contains("labymod")) return "labymod";
            return "vanilla";
        }

        private static bool IsModded(string loader)
        {
            return loader != "vanilla";
        }

        /// <summary>Builds the plan. <paramref name="libraryNames"/> may be null (then only the id is used).</summary>
        public static GamePlan Build(McVersion version, AppSettings settings, ServerProfile server, string gameDir,
                                     int javaMajor, List<string> libraryNames)
        {
            var plan = new GamePlan();
            plan.VersionId = version == null ? "" : version.Id;
            plan.JavaMajor = javaMajor;
            plan.Loader = DetectLoader(version, libraryNames);
            bool modded = IsModded(plan.Loader);
            if (modded) plan.Applied.Add(L.T("مود/لودر شناسایی شد: ", "mod loader detected: ") + plan.Loader);
            // "JVM tuning flags" (settings -> optimisation): with it off the game only gets the memory,
            // so the plan the user reads is exactly what the launcher will really do.
            bool flagsOn = settings == null || settings.UseAikarFlags;
            plan.FlagsOn = flagsOn;

            // ---- memory -----------------------------------------------------------------
            long ramMb = Math.Max(1024, LaunchBuilder.TotalPhysicalMemoryBytes() / (1024 * 1024));
            int heap = settings.MaxHeapMb > 0 ? settings.MaxHeapMb : LaunchBuilder.RecommendHeapMb();
            if (settings.MaxHeapMb <= 0 && modded) heap += 1024;
            int ceiling = (int)Math.Max(1024, ramMb * 3 / 5);        // never eat more than 60% of the machine
            if (heap > ceiling)
            {
                plan.Applied.Add(L.T("سقف حافظه رعایت شد (۶۰٪ رم سیستم)", "memory capped at 60% of the system RAM"));
                heap = ceiling;
            }
            if (heap > 8192)
            {
                heap = 8192;                                          // past this G1 gets slower, not faster
                plan.Applied.Add(L.T("حافظه روی ۸ گیگ بسته شد؛ بیشترش برای ماینکرفت ضرر دارد",
                                     "memory capped at 8 GB; more makes Minecraft slower, not faster"));
            }
            if (heap < 1024) heap = 1024;
            plan.HeapMb = heap;
            plan.InitialHeapMb = Math.Max(512, Math.Min(heap, heap / 2));
            if (modded && heap < 3072)
                plan.Warnings.Add(L.T("برای نسخه موددار ۳ گیگ یا بیشتر بهتر است (تنظیمات → حافظه).",
                                      "a modded version is happier with 3 GB or more (settings -> memory)."));

            // ---- collector --------------------------------------------------------------
            // Aikar style G1 everywhere there is a modern Java; old clients on Java 8 keep CMS,
            // which is what they were tuned for and what gives the lowest pause on tiny heaps.
            bool legacy = javaMajor > 0 && javaMajor <= 8 && VersionResolver.CompareVersions(plan.VersionId, "1.12.2") <= 0;
            plan.G1 = flagsOn && !legacy;
            if (flagsOn && legacy)
            {
                plan.Applied.Add(L.T("نسخه قدیمی روی Java 8: جمع‌کننده CMS (پایدارتر برای ۱.۱۲ و قدیمی‌تر)",
                                     "old version on Java 8: CMS collector (steadier for 1.12 and older)"));
                plan.Flags.Add("-XX:+UseParNewGC");
                plan.Flags.Add("-XX:+UseConcMarkSweepGC");
                plan.Flags.Add("-XX:+CMSParallelRemarkEnabled");
                plan.Flags.Add("-XX:MaxGCPauseMillis=50");
                plan.Flags.Add("-XX:+UseStringDeduplication");
            }
            else if (flagsOn)
            {
                plan.Applied.Add(L.T("پرچم‌های Aikar برای G1GC (کمترین لگ در بازی)", "Aikar style G1GC flags (the least in game stutter)"));
                plan.Flags.AddRange(LaunchBuilder.AikarFlags());
            }

            // ---- Java version specific --------------------------------------------------
            if (flagsOn && javaMajor >= 18)
            {
                plan.Flags.Add("-Dstdout.encoding=UTF-8");
                plan.Flags.Add("-Dstderr.encoding=UTF-8");
                plan.Applied.Add(L.T("Java 18+ : کدگذاری خروجی روی UTF-8 تنظیم شد (چت فارسی)",
                                     "Java 18+: console encoding forced to UTF-8 (Persian chat)"));
            }
            if (javaMajor > 0 && javaMajor < 9 && VersionResolver.CompareVersions(plan.VersionId, "1.13") >= 0)
                plan.Warnings.Add(L.T("این نسخه با Java 8 هم اجرا می‌شود ولی Java 11+ روان‌تر است.",
                                      "this version runs on Java 8, but Java 11+ feels smoother."));

            // ---- loader specific --------------------------------------------------------
            if (flagsOn && (plan.Loader == "forge" || plan.Loader == "neoforge"))
            {
                plan.Flags.Add("-Dfml.earlyprogresswindow=false");
                plan.Applied.Add(L.T("پنجره پیشرفت اولیه Forge خاموش شد (شروع سریع‌تر)",
                                     "Forge's early splash window is off (faster start)"));
                plan.Flags.Add("-Dfml.readTimeout=180");
                plan.Applied.Add(L.T("مهلت شبکه Forge بیشتر شد (مناسب اینترنت کند/فیلتر)",
                                     "Forge's network timeout raised (slow or filtered connections)"));
            }
            if (plan.Loader == "labymod")
                plan.Warnings.Add(L.T("LabyMod تنظیمات گرافیکی خودش را دارد؛ اگر بازی کند بود، از داخل خودش کم کنید.",
                                      "LabyMod has its own graphics settings; if it feels slow, turn things down inside it."));

            // ---- network ----------------------------------------------------------------
            bool serverIsIpv4 = true;
            if (server != null)
            {
                string target = string.IsNullOrEmpty(server.DirectIp) ? server.Host : server.DirectIp;
                System.Net.IPAddress parsed;
                serverIsIpv4 = !System.Net.IPAddress.TryParse(target, out parsed) ||
                               parsed.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork;
            }
            if (flagsOn && serverIsIpv4)
            {
                plan.Flags.Add("-Djava.net.preferIPv4Stack=true");
                plan.Applied.Add(L.T("IPv4 ترجیح داده می‌شود (از قطعی‌های IPv6 جلوگیری می‌کند)",
                                    "IPv4 is preferred (avoids the usual IPv6 join failures)"));
            }

            // ---- optional graphics switch ----------------------------------------------
            if (settings.OpenGlPipeline)
            {
                plan.Flags.Add("-Dsun.java2d.opengl=true");
                plan.Applied.Add(L.T("خط لوله OpenGL جاوا روشن شد (به بعضی درایورهای اینتل کمک می‌کند)",
                                     "the Java OpenGL pipeline is on (helps some Intel drivers)"));
            }

            // ---- folder sanity ----------------------------------------------------------
            Inspect(version, gameDir, plan);
            if (ramMb < 6000 && plan.HeapMb >= 3072)
                plan.Warnings.Add(L.T("رم سیستم کم است؛ اگر ویندوز کند شد حافظه بازی را کمتر کنید.",
                                      "the system RAM is small; lower the game memory if Windows starts swapping."));
            if (!flagsOn)
                plan.Applied.Add(L.T("پرچم‌های JVM خاموش است (تنظیمات → بهینه‌سازی)؛ فقط حافظه تنظیم می‌شود",
                                     "JVM flags are off (settings -> optimisation); only the memory is tuned"));
            return plan;
        }

        /// <summary>Checks the version folder: libraries, assets and natives, without downloading anything.</summary>
        public static void Inspect(McVersion version, string gameDir, GamePlan plan)
        {
            if (version == null || plan == null) return;
            try
            {
                if (!string.IsNullOrEmpty(gameDir))
                {
                    string assets = Path.Combine(gameDir, "assets");
                    string index = Path.Combine(assets, "indexes", version.AssetIndex + ".json");
                    string objects = Path.Combine(assets, "objects");
                    plan.AssetsReady = (version.AssetIndex.Length == 0 && !Directory.Exists(assets))
                                      || (Shell.FileExists(index) && Directory.Exists(objects));
                }

                string natives = Path.Combine(version.Folder, version.Id + "-natives");
                plan.NativesReady = Directory.Exists(natives) || plan.Loader == "vanilla";
            }
            catch { }
        }

        /// <summary>Removes the flags from a list that another source already set (TLauncher jsons add some).</summary>
        public static List<string> Deduplicate(List<string> existing, List<string> wanted)
        {
            var result = new List<string>();
            if (wanted == null) return result;
            foreach (string flag in wanted)
            {
                if (string.IsNullOrEmpty(flag)) continue;
                string key = FlagKey(flag);
                bool clash = false;
                foreach (string present in existing)
                {
                    if (present == null) continue;
                    if (present == flag) { clash = true; break; }
                    if (key.Length > 0 && FlagKey(present) == key) { clash = true; break; }
                }
                if (!clash) result.Add(flag);
            }
            return result;
        }

        /// <summary>The part of a JVM flag that must be unique (-Xmx, -Xms, -Dkey=, -XX:Flag=).</summary>
        public static string FlagKey(string flag)
        {
            if (string.IsNullOrEmpty(flag)) return "";
            if (flag.StartsWith("-D", StringComparison.Ordinal))
            {
                int equals = flag.IndexOf('=');
                return equals > 0 ? flag.Substring(0, equals + 1) : flag;
            }
            if (flag.StartsWith("-XX:", StringComparison.Ordinal))
            {
                string body = flag.Substring(4);
                if (body.StartsWith("+", StringComparison.Ordinal) || body.StartsWith("-", StringComparison.Ordinal))
                    return flag;                                  // +Flag / -Flag are unique by name
                int equals = body.IndexOf('=');
                return equals > 0 ? "-XX:" + body.Substring(0, equals + 1) : flag;
            }
            if (flag.StartsWith("-Xmx", StringComparison.Ordinal) || flag.StartsWith("-Xms", StringComparison.Ordinal) ||
                flag.StartsWith("-Xss", StringComparison.Ordinal))
                return flag.Substring(0, 4);
            return "";                                            // everything else may repeat
        }
    }
}

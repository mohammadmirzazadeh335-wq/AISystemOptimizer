using System;
using System.Linq;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using AISystemOptimizer.Core.Constants;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Application configuration settings
    /// </summary>
    public class AppConfig
    {
        #region General Settings

        /// <summary>
        /// Application version
        /// </summary>
        public string Version { get; set; } = "1.0.0";

        /// <summary>
        /// Whether to check for updates on startup
        /// </summary>
        public bool CheckForUpdates { get; set; } = true;

        /// <summary>
        /// Whether to run at Windows startup
        /// </summary>
        public bool RunAtStartup { get; set; } = false;

        /// <summary>
        /// Whether to minimize to tray on close
        /// </summary>
        public bool MinimizeToTray { get; set; } = true;

        /// <summary>
        /// Whether to show notifications
        /// </summary>
        public bool ShowNotifications { get; set; } = true;

        /// <summary>
        /// Whether to play sounds
        /// </summary>
        public bool PlaySounds { get; set; } = true;

        /// <summary>
        /// Language/locale
        /// </summary>
        public string Language { get; set; } = "en-US";

        #endregion

        #region UI Settings

        /// <summary>
        /// Whether to use dark mode
        /// </summary>
        public bool DarkMode { get; set; } = true;

        /// <summary>
        /// Whether to use animations
        /// </summary>
        public bool UseAnimations { get; set; } = true;

        /// <summary>
        /// Whether to use Fluent Design effects
        /// </summary>
        public bool UseFluentDesign { get; set; } = true;

        /// <summary>
        /// Window transparency level (0-100)
        /// </summary>
        public int WindowTransparency { get; set; } = 95;

        /// <summary>
        /// Default view on startup
        /// </summary>
        public string DefaultView { get; set; } = "Dashboard";

        /// <summary>
        /// Whether to show advanced options
        /// </summary>
        public bool ShowAdvancedOptions { get; set; } = false;

        #endregion

        #region Optimization Settings

        /// <summary>
        /// Default optimization mode
        /// </summary>
        public OptimizationMode DefaultOptimizationMode { get; set; } = OptimizationMode.Manual;

        /// <summary>
        /// Target RAM usage percentage (0-100)
        /// </summary>
        public int TargetRamUsage { get; set; } = 35;

        /// <summary>
        /// Whether to enable automatic optimization
        /// </summary>
        public bool AutoOptimizeEnabled { get; set; } = false;

        /// <summary>
        /// Auto-optimize interval in minutes
        /// </summary>
        public int AutoOptimizeInterval { get; set; } = 30;

        /// <summary>
        /// Whether to auto-optimize when system is idle
        /// </summary>
        public bool AutoOptimizeOnIdle { get; set; } = true;

        /// <summary>
        /// Idle detection threshold in seconds
        /// </summary>
        public int IdleThreshold { get; set; } = 60;

        /// <summary>
        /// Minimum RAM usage to trigger optimization
        /// </summary>
        public int MinRamUsageToOptimize { get; set; } = 50;

        /// <summary>
        /// Minimum CPU usage to trigger optimization
        /// </summary>
        public int MinCpuUsageToOptimize { get; set; } = 10;

        /// <summary>
        /// Whether to optimize on battery power
        /// </summary>
        public bool OptimizeOnBattery { get; set; } = true;

        /// <summary>
        /// Whether to use aggressive optimization on battery
        /// </summary>
        public bool AggressiveOnBattery { get; set; } = false;

        /// <summary>
        /// Skip the per-core CPU sampling pass (faster scans, less detail).
        /// </summary>
        public bool ScanSkipCpuSampling { get; set; } = false;

        /// <summary>
        /// Power mode that should be active when the machine is plugged in.
        /// </summary>
        public PowerMode PreferredPowerModeOnAc { get; set; } = PowerMode.HighPerformance;

        /// <summary>
        /// Power mode that should be active when the machine runs on battery.
        /// </summary>
        public PowerMode PreferredPowerModeOnBattery { get; set; } = PowerMode.PowerSaver;

        /// <summary>
        /// Whether the application may adjust power settings at all.
        /// </summary>
        public bool ManagePowerSettings { get; set; } = false;

        /// <summary>
        /// Number of seconds a scan result stays valid before the UI refreshes it.
        /// </summary>
        public int ScanCacheSeconds { get; set; } = 5;

        #endregion

        #region AI Settings

        /// <summary>
        /// Whether AI analysis is enabled
        /// </summary>
        public bool AiEnabled { get; set; } = true;

        /// <summary>
        /// AI model to use
        /// </summary>
        public string AiModel { get; set; } = "llama3.2:3b";

        /// <summary>
        /// AI provider (Local, Ollama, etc.)
        /// </summary>
        public string AiProvider { get; set; } = "Ollama";

        /// <summary>
        /// Ollama server URL
        /// </summary>
        public string OllamaServerUrl { get; set; } = "http://localhost:11434";

        /// <summary>
        /// Whether the AI server is allowed to be somewhere other than this machine.
        ///
        /// False by default, and deliberately so. The optimiser sends its process, service and start-up
        /// inventory to the AI server as prompt context; that is the user's system information, and it
        /// should not be able to leave the machine because of an unnoticed configuration default. A
        /// loopback address is always permitted. Enabling this permits a private-network address only -
        /// a public internet address is refused whatever this is set to.
        /// </summary>
        public bool AllowRemoteAiServer { get; set; } = false;

        /// <summary>
        /// AI confidence threshold (0-1)
        /// </summary>
        public float AiConfidenceThreshold { get; set; } = 0.7f;

        /// <summary>
        /// Whether to require user confirmation for AI recommendations
        /// </summary>
        public bool RequireAiConfirmation { get; set; } = true;

        /// <summary>
        /// Maximum number of concurrent AI requests
        /// </summary>
        public int MaxConcurrentAiRequests { get; set; } = 1;

        /// <summary>
        /// How many of the highest ranked processes may be sent to the AI per scan.
        /// Keeps latency and the optimiser's own memory footprint low.
        /// </summary>
        public int MaxAiProcessAnalyses { get; set; } = 10;

        /// <summary>
        /// AI request timeout in seconds
        /// </summary>
        public int AiRequestTimeout { get; set; } = 30;

        #endregion

        #region Safety Settings

        /// <summary>
        /// Whether to create system restore points before optimization
        /// </summary>
        public bool CreateRestorePoints { get; set; } = true;

        /// <summary>
        /// How long the executor politely waits for an application to close itself (WM_CLOSE) before
        /// it falls back to a forced termination. Milliseconds, clamped to 500..15000.
        ///
        /// This exists so that closing a program never destroys unsaved work if the program is
        /// willing to shut down cleanly.
        /// </summary>
        public int CloseGracePeriodMs { get; set; } = 3000;

        /// <summary>
        /// How long the verifier waits after execution before it re-measures the system, in seconds.
        ///
        /// Measuring immediately produces false "improvements": closed applications release their
        /// working set over several seconds, and Windows needs a moment to retire the page tables.
        /// Clamped to 5..30 by <c>VerificationService</c>, so the default sits in the middle of the
        /// range that the specification asks for.
        /// </summary>
        public int VerificationSettleSeconds { get; set; } = 8;

        /// <summary>
        /// Whether to enable safety layer
        /// </summary>
        public bool SafetyLayerEnabled { get; set; } = true;

        /// <summary>
        /// Maximum allowed risk level for automatic actions
        /// </summary>
        public RiskLevel MaxAutoRiskLevel { get; set; } = RiskLevel.Low;

        /// <summary>
        /// Whether to require user confirmation for medium risk actions
        /// </summary>
        public bool RequireConfirmationForMediumRisk { get; set; } = true;

        /// <summary>
        /// Whether to allow high risk actions at all
        /// </summary>
        public bool AllowHighRiskActions { get; set; } = false;

        /// <summary>
        /// Whether to allow critical risk actions at all
        /// </summary>
        public bool AllowCriticalRiskActions { get; set; } = false;

        /// <summary>
        /// Whether to backup before optimization
        /// </summary>
        public bool BackupBeforeOptimization { get; set; } = true;

        /// <summary>
        /// Number of backup versions to keep
        /// </summary>
        public int BackupVersionsToKeep { get; set; } = 5;

        #endregion

        #region Logging Settings

        /// <summary>
        /// Whether logging is enabled
        /// </summary>
        public bool LoggingEnabled { get; set; } = true;

        /// <summary>
        /// Log level (Verbose, Info, Warning, Error)
        /// </summary>
        public string LogLevel { get; set; } = "Info";

        /// <summary>
        /// Log file path
        /// </summary>
        public string LogFilePath { get; set; } = "Logs";

        /// <summary>
        /// Maximum log file size in MB
        /// </summary>
        public int MaxLogFileSizeMB { get; set; } = 10;

        /// <summary>
        /// Number of log files to keep
        /// </summary>
        public int MaxLogFiles { get; set; } = 5;

        /// <summary>
        /// Whether to log to console
        /// </summary>
        public bool LogToConsole { get; set; } = false;

        #endregion

        #region Whitelist/Blacklist Settings

        /// <summary>
        /// List of processes to never optimize (blacklist)
        /// </summary>
        public List<string> BlacklistedProcesses { get; set; } = new List<string>
        {
            "System",
            "Registry",
            "smss",
            "csrss",
            "wininit",
            "services",
            "lsass",
            "winlogon",
            "dwm",
            "explorer",
            "svchost",
            "MsMpEng",  // Windows Defender
            "NisSrv",   // Windows Defender Network Inspection
            "SearchIndexer",
            "WindowsSearch",
            "ShellExperienceHost",
            "StartMenuExperienceHost",
            "RuntimeBroker",
            "ApplicationFrameHost",
            "SystemSettings",
            "SecurityHealthService",
            "SecurityHealthSystray"
        };

        /// <summary>
        /// List of processes to always allow (whitelist)
        /// </summary>
        [System.Text.Json.Serialization.JsonIgnore]
        public List<string> WhitelistedProcesses { get; set; } = new List<string>();

        /// <summary>
        /// The name this setting carries in <c>config.json</c>: the processes the optimiser must never
        /// touch ("Never touch" in the UI).
        ///
        /// The specification names this key <c>ExcludedProcesses</c>, so that is the property that is
        /// serialised; <see cref="WhitelistedProcesses"/> and this property are the same list, exposed
        /// under the name the rest of the code already uses. Both are kept so that a configuration file
        /// written by an earlier build, and a file written by this one, describe the same setting.
        /// </summary>
        [System.Text.Json.Serialization.JsonPropertyName("excludedProcesses")]
        public List<string> ExcludedProcesses
        {
            get => WhitelistedProcesses;
            set => WhitelistedProcesses = value ?? new List<string>();
        }

        /// <summary>
        /// True when the user has marked the given process as never-touch.
        /// </summary>
        public bool IsExcluded(string? processNameOrPath)
        {
            if (string.IsNullOrWhiteSpace(processNameOrPath))
                return false;

            return WhitelistedProcesses.Any(entry =>
                string.Equals(entry, processNameOrPath, StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>
        /// List of services to never optimize
        /// </summary>
        public List<string> BlacklistedServices { get; set; } = new List<string>
        {
            "WinDefend",
            "wscsvc",
            "MpsSvc",
            "BFE",
            "RpcSs",
            "DcomLaunch",
            "RpcEptMapper",
            "PlugPlay",
            "Power",
            "Schedule",
            "Themes",
            "UserManager",
            "Winmgmt",
            "AudioSrv",
            "AudioEndpointBuilder",
            "SysMain",
            "Superfetch"
        };

        /// <summary>
        /// List of startup items to never disable
        /// </summary>
        public List<string> BlacklistedStartupItems { get; set; } = new List<string>
        {
            "Windows Defender",
            "SecurityHealth",
            "OneDrive"
        };

        #endregion

        #region Game Mode Settings

        /// <summary>
        /// Whether Game Mode is enabled
        /// </summary>
        public bool GameModeEnabled { get; set; } = true;

        /// <summary>
        /// Whether to automatically detect games
        /// </summary>
        public bool AutoDetectGames { get; set; } = true;

        /// <summary>
        /// List of known game executables
        /// </summary>
        public List<string> KnownGameExecutables { get; set; } = new List<string>
        {
            "game",
            "launch",
            "client",
            "steam",
            "epicgames",
            "origin",
            "uplay",
            "battle.net",
            "riotclient",
            "valorant",
            "fortnite",
            "apex",
            "callofduty",
            "cod",
            "gta",
            "gta5",
            "gtav",
            "minecraft",
            "javaw",  // For Minecraft Java
            "bedrock",
            "wow",
            "worldofwarcraft",
            "overwatch",
            "diablo",
            "starcraft",
            "hearthstone",
            "heroes",
            "dota",
            "dota2",
            "csgo",
            "cs2",
            "pubg",
            "battlegrounds",
            "destiny",
            "destiny2",
            "division",
            "thedivision",
            "assassin",
            "ac",
            "far cry",
            "farcry",
            "watch dogs",
            "watchdogs",
            "rainbow",
            "r6",
            "siege",
            "forza",
            "halo",
            "gears",
            "gearsofwar",
            "fallout",
            "skyrim",
            "elder scrolls",
            "elderscrolls",
            "bethesda",
            "rockstar",
            "rstar",
            "ea",
            "electronic arts",
            "activision",
            "blizzard",
            "ubisoft",
            "take2",
            "2k",
            "square enix",
            "capcom",
            "bandai",
            "namco",
            "konami",
            "sega"
        };

        /// <summary>
        /// List of processes to close in Game Mode
        /// </summary>
        public List<string> GameModeCloseList { get; set; } = new List<string>
        {
            "Discord",
            "Spotify",
            "Steam",
            "EpicGamesLauncher",
            "GalaxyClient",
            "UbisoftGameLauncher",
            "Battle.net",
            "Origin",
            "Uplay",
            "GOG Galaxy",
            "Telegram",
            "WhatsApp",
            "Skype",
            "Slack",
            "Microsoft Teams",
            "Zoom",
            "Chrome",
            "Firefox",
            "Edge",
            "Opera",
            "Brave",
            "Vivaldi",
            "OneDrive",
            "Dropbox",
            "GoogleDrive",
            "Nextcloud",
            "OwnCloud",
            "Adobe Creative Cloud",
            "AdobeCC",
            "CCLibrary",
            "NVIDIA GeForce Experience",
            "NVIDIA Share",
            "AMD Software",
            "RadeonSoftware",
            "Intel Graphics Command Center",
            "IGCC",
            "MSI Afterburner",
            "RivaTuner",
            "HWMonitor",
            "CPU-Z",
            "GPU-Z",
            "Speccy",
            "HWiNFO",
            "OpenHardwareMonitor"
        };

        /// <summary>
        /// Whether to boost game priority in Game Mode
        /// </summary>
        public bool GameModeBoostPriority { get; set; } = true;

        /// <summary>
        /// Whether to set game affinity in Game Mode
        /// </summary>
        public bool GameModeSetAffinity { get; set; } = false;

        /// <summary>
        /// Whether to disable Windows Defender scans in Game Mode
        /// </summary>
        public bool GameModeDisableDefenderScans { get; set; } = false;

        #endregion

        #region Game &amp; App Optimizer (PHASE 62)

        /// <summary>
        /// Whether the Game &amp; App Optimizer section is shown and its profiles are loaded.
        /// Turning it off never removes profiles, and never changes anything the section already applied:
        /// an open session is still restored.
        /// </summary>
        public bool GameAppOptimizerEnabled { get; set; } = true;

        /// <summary>
        /// Whether a profile may apply itself the moment a user launches the application.
        ///
        /// Default false, as the specification requires: automatic optimisation must be off by default.
        /// This is the master switch; an individual profile must also opt in before anything happens.
        /// </summary>
        public bool GameAppAutoOptimizeOnLaunch { get; set; } = false;

        /// <summary>
        /// Whether to watch for profiled applications starting and stopping while the optimiser runs.
        /// Watching is passive - it observes, and only acts when a profile is allowed to act.
        /// </summary>
        public bool GameAppWatchForLaunches { get; set; } = true;

        /// <summary>
        /// Whether the power mode and graphics preference may be changed for a profile at all.
        /// Two switches, because they are two different machine settings; both default to allowed
        /// because a profile must still opt in per application before either is touched.
        /// </summary>
        public bool GameAppAllowPowerModeChanges { get; set; } = true;

        /// <summary>See <see cref="GameAppAllowPowerModeChanges"/>.</summary>
        public bool GameAppAllowGraphicsPreferenceChanges { get; set; } = true;

        /// <summary>
        /// How many benchmark records to keep per profile. The oldest are discarded first.
        /// </summary>
        public int GameAppMaxBenchmarksPerProfile { get; set; } = 50;

        /// <summary>
        /// How many session summaries to keep per profile.
        /// </summary>
        public int GameAppMaxSessionsPerProfile { get; set; } = 50;

        /// <summary>
        /// How long the optimiser waits after applying changes before it takes the "after" measurement.
        /// Clamped to 5-30 seconds: measuring sooner produces a number that is wrong in the flattering
        /// direction.
        /// </summary>
        public int GameAppBenchmarkSettleSeconds { get; set; } = 10;

        /// <summary>
        /// Whether an application the user added may be launched from the Game &amp; App Optimizer page.
        /// The launch is always a direct process creation with the recorded path - never a shell command.
        /// </summary>
        public bool GameAppAllowLaunchingApplications { get; set; } = true;

        #endregion

        #region Persistence

        /// <summary>
        /// Serialiser settings used for both reading and writing the configuration file.
        /// </summary>
        private static readonly JsonSerializerOptions SerializerOptions = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            ReadCommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,

            // BUG FIXED HERE - the configuration file could never be read.
            //
            // Every enum in this configuration is written as a name: "maxAutoRiskLevel": "Low",
            // "logLevel": "Info", "defaultOptimizationMode": "Manual". System.Text.Json rejects a
            // string where it expects an enum unless a string-enum converter is registered, and none
            // was. The shipped config.json therefore threw JsonException the moment it was loaded,
            // which the loader turned into "quarantine the file and use defaults".
            //
            // The consequences were not subtle: any user who edited config.json - to exclude a process,
            // to lower the RAM target, to enable a game mode - had the file renamed to
            // config.json.invalid and every one of their settings silently discarded. The application
            // then appeared to work, using defaults, so nothing looked wrong.
            //
            // allowIntegerValues keeps files written by an earlier build readable, where the enums may
            // have been serialised as numbers.
            Converters = { new JsonStringEnumConverter(allowIntegerValues: true) }
        };

        /// <summary>
        /// Upper bound on an accepted configuration file, in bytes. A larger file is treated as corrupt
        /// rather than parsed, so a malformed or hostile file cannot exhaust memory.
        /// </summary>
        private const int MaxConfigFileBytes = 1024 * 1024;

        /// <summary>
        /// Path of the recovery copy written alongside the configuration file.
        /// </summary>
        public static string BackupPathFor(string path) => path + ".bak";

        /// <summary>
        /// Outcomes of a load, reported through <see cref="LastLoadOutcome"/> so that a caller - and the
        /// user - can tell whether their settings were actually applied.
        /// </summary>
        public enum LoadOutcome
        {
            /// <summary>The file was read and its values were used.</summary>
            Loaded,

            /// <summary>No file existed; defaults were written.</summary>
            CreatedWithDefaults,

            /// <summary>The file was unusable, so the last known-good backup was used.</summary>
            RecoveredFromBackup,

            /// <summary>The file was unusable and there was no usable backup; defaults were used.</summary>
            FellBackToDefaults
        }

        /// <summary>
        /// What happened during the most recent <see cref="Load"/> call on this machine.
        ///
        /// This exists because silently substituting defaults is indistinguishable, from the outside,
        /// from a successful load - which is precisely how the defect above stayed invisible.
        /// </summary>
        public static LoadOutcome LastLoadOutcome { get; private set; } = LoadOutcome.Loaded;

        /// <summary>
        /// Settings that were outside their documented range and were clamped during the last load.
        /// Empty when nothing was adjusted.
        /// </summary>
        public static IReadOnlyList<string> LastLoadAdjustments { get; private set; } =
            Array.Empty<string>();

        /// <summary>
        /// Load the configuration from disk, with recovery.
        ///
        /// Order of attempts:
        ///   1. the file itself;
        ///   2. the <c>.bak</c> copy, when the file is unusable;
        ///   3. built-in defaults, rewritten to disk.
        ///
        /// A file that cannot be parsed at all is moved to <c>.invalid</c> so the user can inspect what
        /// went wrong - it is never deleted. In every branch the returned configuration is normalised:
        /// out-of-range values are clamped into the range the application can honour, and each clamp is
        /// recorded so the caller can tell the user what was adjusted instead of quietly changing their
        /// intent.
        /// </summary>
        public static AppConfig Load(string? path = null)
        {
            path ??= AppConstants.ConfigFilePath;

            LastLoadOutcome = LoadOutcome.Loaded;
            LastLoadAdjustments = Array.Empty<string>();

            // 1. The file itself.
            if (TryReadFile(path, out var fromFile, out var fileFailure))
            {
                LastLoadOutcome = LoadOutcome.Loaded;
                return fromFile!;
            }

            var hadFile = File.Exists(path);

            // 2. The backup, when the primary file existed but was unusable.
            if (hadFile)
            {
                var backupPath = BackupPathFor(path);

                if (TryReadFile(backupPath, out var fromBackup, out _))
                {
                    Quarantine(path, fileFailure);

                    LastLoadOutcome = LoadOutcome.RecoveredFromBackup;

                    // Preserve what was recovered as the new primary file so the next start is clean.
                    fromBackup!.Save(path);

                    return fromBackup;
                }
            }

            // 3. Defaults.
            if (hadFile)
                Quarantine(path, fileFailure);

            var defaults = new AppConfig();
            defaults.Save(path);

            LastLoadOutcome = hadFile
                ? LoadOutcome.FellBackToDefaults
                : LoadOutcome.CreatedWithDefaults;

            return defaults;
        }

        /// <summary>
        /// Deserialise a configuration file, isolating a single unusable entry instead of losing the
        /// whole file with it.
        ///
        /// THE PROBLEM THIS SOLVES:
        /// strict deserialisation is all-or-nothing. One typo - writing "Balanced" for the optimisation
        /// mode when Balanced is a power mode, or a stray comma, or a number where a name belongs -
        /// throws, and the loader's only remaining option is to discard every setting the user chose.
        /// That is a disproportionate response to a typo, and it looks to the user like the application
        /// ignored them.
        ///
        /// THE APPROACH:
        /// System.Text.Json reports the JSON path of the value that failed. The offending property is
        /// removed from the document and the parse is retried, up to a bounded number of times. Each
        /// removal is reported back so the caller can tell the user exactly which line was ignored and
        /// why. Anything that still cannot be parsed after that is genuinely unreadable and is handled
        /// by the caller's normal recovery path.
        ///
        /// The bound matters: without it, a pathological file could drive an unbounded loop.
        /// </summary>
        private static AppConfig? DeserializeTolerantly(string json, out List<string> droppedProperties)
        {
            const int maxDroppedProperties = 32;

            droppedProperties = new List<string>();

            // Fast path: the file is well-formed.
            try
            {
                return JsonSerializer.Deserialize<AppConfig>(json, SerializerOptions);
            }
            catch (JsonException)
            {
                // Fall through to the tolerant path.
            }

            System.Text.Json.Nodes.JsonNode? document;

            try
            {
                // Parse with the same leniency the strict path uses, so a trailing comma is still
                // tolerated even after a different property failed.
                using var parsed = JsonDocument.Parse(json, new JsonDocumentOptions
                {
                    AllowTrailingCommas = true,
                    CommentHandling = JsonCommentHandling.Skip
                });

                document = System.Text.Json.Nodes.JsonNode.Parse(parsed.RootElement.GetRawText());
            }
            catch (JsonException)
            {
                // The file is not JSON at all - no partial recovery is possible.
                return null;
            }

            if (document is not System.Text.Json.Nodes.JsonObject root || root.Count == 0)
                return null;

            for (var attempt = 0; attempt < maxDroppedProperties; attempt++)
            {
                try
                {
                    var candidate = root.ToJsonString();

                    return JsonSerializer.Deserialize<AppConfig>(candidate, SerializerOptions);
                }
                catch (JsonException failure)
                {
                    var removed = TryRemoveFailingProperty(root, failure.Path);

                    // A null result means the path could not be resolved to one top-level property, so
                    // there is nothing safe left to try.
                    if (removed == null)
                        return null;

                    droppedProperties.Add(removed);
                }
            }

            return null;
        }

        /// <summary>
        /// Remove the top-level property identified by a System.Text.Json error path.
        /// Returns a description of what was removed, or null when the path cannot be resolved to a
        /// single top-level property (in which case the caller gives up rather than guessing).
        /// </summary>
        private static string? TryRemoveFailingProperty(
            System.Text.Json.Nodes.JsonObject root,
            string? path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return null;

            // Paths look like "$.defaultOptimizationMode" or "$.excludedProcesses[3]".
            var trimmed = path.TrimStart('$');

            if (trimmed.StartsWith(".", StringComparison.Ordinal))
                trimmed = trimmed[1..];

            var bracket = trimmed.IndexOf('[');
            if (bracket >= 0)
                trimmed = trimmed[..bracket];

            if (trimmed.Length == 0)
                return null;

            if (!root.ContainsKey(trimmed))
                return null;

            var originalValue = root[trimmed]?.ToJsonString() ?? "null";
            root.Remove(trimmed);

            if (originalValue.Length > 120)
                originalValue = originalValue[..120] + "...";

            return $"ignored '{trimmed}' (value {originalValue} could not be read)";
        }

        /// <summary>
        /// Read and normalise one configuration file.
        /// Returns false with a human-readable reason rather than throwing.
        /// </summary>
        private static bool TryReadFile(string path, out AppConfig? config, out string failureReason)
        {
            config = null;
            failureReason = string.Empty;

            try
            {
                if (!File.Exists(path))
                {
                    failureReason = "The file does not exist.";
                    return false;
                }

                var length = new FileInfo(path).Length;
                if (length > MaxConfigFileBytes)
                {
                    failureReason =
                        $"The file is {length} bytes, which exceeds the {MaxConfigFileBytes} byte limit.";
                    return false;
                }

                var json = File.ReadAllText(path);
                var loaded = DeserializeTolerantly(json, out var droppedProperties);

                if (loaded == null)
                {
                    failureReason = "The file parsed but produced no configuration object.";
                    return false;
                }

                config = loaded.NormalizeToSupportedRanges();

                if (droppedProperties.Count > 0)
                {
                    // Surface every dropped property to the caller. A setting that was ignored because
                    // it could not be understood must never disappear without a trace.
                    LastLoadAdjustments = LastLoadAdjustments
                        .Concat(droppedProperties)
                        .ToList();
                }

                return true;
            }
            catch (JsonException exception)
            {
                failureReason = $"The file is not valid JSON: {exception.Message}";
                return false;
            }
            catch (NotSupportedException exception)
            {
                // Thrown for a value of the wrong shape, e.g. an object where a string was expected.
                failureReason = $"The file contains a value of an unsupported shape: {exception.Message}";
                return false;
            }
            catch (Exception exception)
            {
                failureReason = $"The file could not be read: {exception.Message}";
                return false;
            }
        }

        /// <summary>
        /// Move an unusable file aside so it can be inspected. Never deletes configuration data.
        /// </summary>
        private static void Quarantine(string path, string reason)
        {
            try
            {
                if (!File.Exists(path))
                    return;

                var quarantine = path + ".invalid";

                if (File.Exists(quarantine))
                    File.Delete(quarantine);

                File.Move(path, quarantine);

                // Leave a breadcrumb that says what went wrong, next to the file that went wrong.
                try
                {
                    File.WriteAllText(
                        quarantine + ".reason.txt",
                        $"This configuration file could not be used and was moved aside on " +
                        $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}.{Environment.NewLine}" +
                        $"Reason: {reason}{Environment.NewLine}" +
                        $"The application continued with the last known-good configuration, or with " +
                        $"defaults. Correct this file and rename it back to restore your settings." +
                        Environment.NewLine);
                }
                catch
                {
                    // The breadcrumb is helpful, not essential.
                }
            }
            catch
            {
                // Unable to move the file (locked or read-only). The caller still proceeds safely.
            }
        }

        /// <summary>
        /// Clamp every setting that has a documented range into that range.
        ///
        /// WHY CLAMP RATHER THAN REFUSE:
        /// refusing to load a file because one number is out of range would discard every other setting
        /// the user chose. Clamping keeps their intent whereever it is expressible and records exactly
        /// what was adjusted, so the change is visible rather than silent.
        /// </summary>
        public AppConfig NormalizeToSupportedRanges()
        {
            var adjustments = new List<string>();

            void Clamp(string name, Action<int> apply, int value, int min, int max)
            {
                if (value < min || value > max)
                {
                    var clamped = Math.Max(min, Math.Min(max, value));
                    apply(clamped);
                    adjustments.Add($"{name}: {value} -> {clamped} (allowed {min}..{max})");
                }
            }

            void ClampDouble(string name, Action<double> apply, double value, double min, double max)
            {
                if (double.IsNaN(value) || value < min || value > max)
                {
                    var clamped = double.IsNaN(value) ? min : Math.Max(min, Math.Min(max, value));
                    apply(clamped);
                    adjustments.Add($"{name}: {value} -> {clamped} (allowed {min}..{max})");
                }
            }

            // Target RAM: below 10 % is not a memory target, it is a promise that cannot be kept, and
            // above 90 % is not an optimisation.
            Clamp(nameof(TargetRamUsage), v => TargetRamUsage = v, TargetRamUsage, 10, 90);

            Clamp(nameof(AutoOptimizeInterval), v => AutoOptimizeInterval = v, AutoOptimizeInterval, 5, 1440);
            Clamp(nameof(IdleThreshold), v => IdleThreshold = v, IdleThreshold, 10, 600);
            Clamp(nameof(MinRamUsageToOptimize), v => MinRamUsageToOptimize = v, MinRamUsageToOptimize, 0, 100);
            Clamp(nameof(MinCpuUsageToOptimize), v => MinCpuUsageToOptimize = v, MinCpuUsageToOptimize, 0, 100);

            ClampDouble(nameof(AiConfidenceThreshold), v => AiConfidenceThreshold = (float)v, AiConfidenceThreshold, 0.0, 1.0);

            Clamp(nameof(MaxLogFileSizeMB), v => MaxLogFileSizeMB = v, MaxLogFileSizeMB, 1, 100);
            Clamp(nameof(MaxLogFiles), v => MaxLogFiles = v, MaxLogFiles, 1, 50);
            Clamp(nameof(BackupVersionsToKeep), v => BackupVersionsToKeep = v, BackupVersionsToKeep, 1, 20);

            // The observation window the specification requires is 5-15 s; the service clamps to 5-30.
            Clamp(nameof(VerificationSettleSeconds), v => VerificationSettleSeconds = v, VerificationSettleSeconds, 5, 30);
            Clamp(nameof(CloseGracePeriodMs), v => CloseGracePeriodMs = v, CloseGracePeriodMs, 500, 15000);

            // At least one request must be possible; more than a few would fight the local model.
            Clamp(nameof(MaxConcurrentAiRequests), v => MaxConcurrentAiRequests = v, MaxConcurrentAiRequests, 1, 4);
            Clamp(nameof(MaxAiProcessAnalyses), v => MaxAiProcessAnalyses = v, MaxAiProcessAnalyses, 0, 100);
            Clamp(nameof(AiRequestTimeout), v => AiRequestTimeout = v, AiRequestTimeout, 5, 300);

            // Secondary scan latency must not be negative or absurd.
            Clamp(nameof(ScanCacheSeconds), v => ScanCacheSeconds = v, ScanCacheSeconds, 0, 3600);

            // Game & App Optimizer (PHASE 62). The settle window follows the same reasoning as the
            // verification settle window: measuring sooner than 5 s produces a number that is wrong in
            // the flattering direction.
            Clamp(nameof(GameAppBenchmarkSettleSeconds), v => GameAppBenchmarkSettleSeconds = v,
                GameAppBenchmarkSettleSeconds, 5, 30);

            Clamp(nameof(GameAppMaxBenchmarksPerProfile), v => GameAppMaxBenchmarksPerProfile = v,
                GameAppMaxBenchmarksPerProfile, 1, 500);

            Clamp(nameof(GameAppMaxSessionsPerProfile), v => GameAppMaxSessionsPerProfile = v,
                GameAppMaxSessionsPerProfile, 1, 500);

            // The AI endpoint must be somewhere this application is willing to send system data.
            var endpointDecision = Core.AI.AiEndpointPolicy.Evaluate(OllamaServerUrl, AllowRemoteAiServer);

            if (!Core.AI.AiEndpointPolicy.IsPermitted(OllamaServerUrl, AllowRemoteAiServer))
            {
                adjustments.Add(
                    $"ollamaServerUrl: '{OllamaServerUrl}' was refused and reset to loopback " +
                    $"({Core.AI.AiEndpointPolicy.Describe(endpointDecision)})");

                OllamaServerUrl = "http://localhost:11434";
            }

            // Null collections produce null-reference faults deep inside the pipeline; treat them as
            // "the user listed nothing".
            ExcludedProcesses ??= new List<string>();
            BlacklistedProcesses ??= new List<string>();
            BlacklistedServices ??= new List<string>();
            BlacklistedStartupItems ??= new List<string>();
            KnownGameExecutables ??= new List<string>();
            GameModeCloseList ??= new List<string>();

            LastLoadAdjustments = adjustments;

            return this;
        }

        /// <summary>
        /// Persist the configuration to disk, keeping a recoverable copy.
        ///
        /// The write order is deliberate:
        ///   1. the file that is currently there - if it parses - is copied to <c>.bak</c>;
        ///   2. the new contents are written to a temporary file;
        ///   3. the temporary file replaces the real one.
        ///
        /// Writing through a temporary file means an interrupted save leaves the original file intact
        /// rather than a half-written one. Keeping a <c>.bak</c> means a file that is corrupted later -
        /// by a text editor, by a bad hand edit, by a disk problem - can still be recovered, which the
        /// previous implementation could not do because it wrote straight over the file and kept no copy.
        ///
        /// On the very first save there is nothing to copy, so the written file is also used as the
        /// initial backup. Without that, a first-run user would have an unbacked-up configuration and
        /// no recovery path at all.
        /// </summary>
        public bool Save(string? path = null)
        {
            path ??= AppConstants.ConfigFilePath;

            try
            {
                var directory = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
                    Directory.CreateDirectory(directory);

                var json = JsonSerializer.Serialize(this, SerializerOptions);
                var backupPath = BackupPathFor(path);

                PreserveRecoverableCopy(path, backupPath, json);

                // Write through a temporary file so an interrupted write cannot truncate the live file.
                var temporaryPath = path + ".tmp";

                try
                {
                    File.WriteAllText(temporaryPath, json);
                    File.Move(temporaryPath, path, overwrite: true);
                }
                catch
                {
                    // Clean up the temporary file if the swap failed, then report the failure.
                    try { if (File.Exists(temporaryPath)) File.Delete(temporaryPath); } catch { }
                    throw;
                }

                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Maintain the recovery copy, without ever replacing a good backup with a broken file.
        /// </summary>
        private static void PreserveRecoverableCopy(string path, string backupPath, string newContents)
        {
            // Nothing on disk yet: this is the initial save, so the new contents become the baseline.
            if (!File.Exists(path))
            {
                try
                {
                    File.WriteAllText(backupPath, newContents);
                }
                catch
                {
                    // A missing backup is not a reason to fail the save itself.
                }

                return;
            }

            var currentFileIsUsable = TryReadFile(path, out _, out _);

            if (!currentFileIsUsable)
            {
                // The live file is already broken. Overwriting the backup with it would destroy the only
                // good copy, so leave the existing backup exactly as it is.
                return;
            }

            try
            {
                File.Copy(path, backupPath, overwrite: true);
            }
            catch
            {
                // Keep going: the primary write is what matters.
            }
        }

        #endregion

        #region Methods

        /// <summary>
        /// Create a default configuration
        /// </summary>
        public static AppConfig CreateDefault()
        {
            return new AppConfig();
        }

        /// <summary>
        /// Validate the configuration
        /// </summary>
        public bool Validate(out List<string> errors)
        {
            errors = new List<string>();
            
            // Validate TargetRamUsage
            if (TargetRamUsage < 10 || TargetRamUsage > 90)
            {
                errors.Add("Target RAM usage must be between 10% and 90%");
            }
            
            // Validate AutoOptimizeInterval
            if (AutoOptimizeInterval < 5 || AutoOptimizeInterval > 1440)
            {
                errors.Add("Auto-optimize interval must be between 5 and 1440 minutes");
            }
            
            // Validate IdleThreshold
            if (IdleThreshold < 10 || IdleThreshold > 600)
            {
                errors.Add("Idle threshold must be between 10 and 600 seconds");
            }
            
            // Validate AiConfidenceThreshold
            if (AiConfidenceThreshold < 0 || AiConfidenceThreshold > 1)
            {
                errors.Add("AI confidence threshold must be between 0 and 1");
            }
            
            // Validate MaxLogFileSizeMB
            if (MaxLogFileSizeMB < 1 || MaxLogFileSizeMB > 100)
            {
                errors.Add("Maximum log file size must be between 1 and 100 MB");
            }
            
            // Validate MaxLogFiles
            if (MaxLogFiles < 1 || MaxLogFiles > 50)
            {
                errors.Add("Maximum number of log files must be between 1 and 50");
            }
            
            // Validate BackupVersionsToKeep
            if (BackupVersionsToKeep < 1 || BackupVersionsToKeep > 20)
            {
                errors.Add("Backup versions to keep must be between 1 and 20");
            }

            // Game & App Optimizer (PHASE 62)
            if (GameAppBenchmarkSettleSeconds < 5 || GameAppBenchmarkSettleSeconds > 30)
            {
                errors.Add("Game & App Optimizer benchmark settle time must be between 5 and 30 seconds");
            }

            if (GameAppMaxBenchmarksPerProfile < 1 || GameAppMaxBenchmarksPerProfile > 500)
            {
                errors.Add("Game & App Optimizer benchmark history must keep between 1 and 500 records");
            }

            if (GameAppMaxSessionsPerProfile < 1 || GameAppMaxSessionsPerProfile > 500)
            {
                errors.Add("Game & App Optimizer session history must keep between 1 and 500 records");
            }

            return errors.Count == 0;
        }

        /// <summary>
        /// Clone the configuration
        /// </summary>
        public AppConfig Clone()
        {
            var clone = new AppConfig
            {
                // General Settings
                Version = Version,
                CheckForUpdates = CheckForUpdates,
                RunAtStartup = RunAtStartup,
                MinimizeToTray = MinimizeToTray,
                ShowNotifications = ShowNotifications,
                PlaySounds = PlaySounds,
                Language = Language,

                // UI Settings
                DarkMode = DarkMode,
                UseAnimations = UseAnimations,
                UseFluentDesign = UseFluentDesign,
                WindowTransparency = WindowTransparency,
                DefaultView = DefaultView,
                ShowAdvancedOptions = ShowAdvancedOptions,

                // Optimization Settings
                DefaultOptimizationMode = DefaultOptimizationMode,
                TargetRamUsage = TargetRamUsage,
                AutoOptimizeEnabled = AutoOptimizeEnabled,
                AutoOptimizeInterval = AutoOptimizeInterval,
                AutoOptimizeOnIdle = AutoOptimizeOnIdle,
                IdleThreshold = IdleThreshold,
                MinRamUsageToOptimize = MinRamUsageToOptimize,
                MinCpuUsageToOptimize = MinCpuUsageToOptimize,
                OptimizeOnBattery = OptimizeOnBattery,
                AggressiveOnBattery = AggressiveOnBattery,
                ScanSkipCpuSampling = ScanSkipCpuSampling,
                PreferredPowerModeOnAc = PreferredPowerModeOnAc,
                PreferredPowerModeOnBattery = PreferredPowerModeOnBattery,
                ManagePowerSettings = ManagePowerSettings,
                ScanCacheSeconds = ScanCacheSeconds,

                // AI Settings
                AiEnabled = AiEnabled,
                AiModel = AiModel,
                AiProvider = AiProvider,
                OllamaServerUrl = OllamaServerUrl,
                AllowRemoteAiServer = AllowRemoteAiServer,
                AiConfidenceThreshold = AiConfidenceThreshold,
                RequireAiConfirmation = RequireAiConfirmation,
                MaxConcurrentAiRequests = MaxConcurrentAiRequests,
                MaxAiProcessAnalyses = MaxAiProcessAnalyses,
                AiRequestTimeout = AiRequestTimeout,

                // Safety Settings
                CreateRestorePoints = CreateRestorePoints,
                CloseGracePeriodMs = CloseGracePeriodMs,
                VerificationSettleSeconds = VerificationSettleSeconds,
                SafetyLayerEnabled = SafetyLayerEnabled,
                MaxAutoRiskLevel = MaxAutoRiskLevel,
                RequireConfirmationForMediumRisk = RequireConfirmationForMediumRisk,
                AllowHighRiskActions = AllowHighRiskActions,
                AllowCriticalRiskActions = AllowCriticalRiskActions,
                BackupBeforeOptimization = BackupBeforeOptimization,
                BackupVersionsToKeep = BackupVersionsToKeep,

                // Logging Settings
                LoggingEnabled = LoggingEnabled,
                LogLevel = LogLevel,
                LogFilePath = LogFilePath,
                MaxLogFileSizeMB = MaxLogFileSizeMB,
                MaxLogFiles = MaxLogFiles,
                LogToConsole = LogToConsole,

                // Whitelist/Blacklist Settings
                BlacklistedProcesses = new List<string>(BlacklistedProcesses),
                ExcludedProcesses = new List<string>(WhitelistedProcesses),
                BlacklistedServices = new List<string>(BlacklistedServices),
                BlacklistedStartupItems = new List<string>(BlacklistedStartupItems),

                // Game Mode Settings
                GameModeEnabled = GameModeEnabled,
                AutoDetectGames = AutoDetectGames,
                KnownGameExecutables = new List<string>(KnownGameExecutables),
                GameModeCloseList = new List<string>(GameModeCloseList),
                GameModeBoostPriority = GameModeBoostPriority,
                GameModeSetAffinity = GameModeSetAffinity,
                GameModeDisableDefenderScans = GameModeDisableDefenderScans,

                // Game & App Optimizer (PHASE 62)
                GameAppOptimizerEnabled = GameAppOptimizerEnabled,
                GameAppAutoOptimizeOnLaunch = GameAppAutoOptimizeOnLaunch,
                GameAppWatchForLaunches = GameAppWatchForLaunches,
                GameAppAllowPowerModeChanges = GameAppAllowPowerModeChanges,
                GameAppAllowGraphicsPreferenceChanges = GameAppAllowGraphicsPreferenceChanges,
                GameAppMaxBenchmarksPerProfile = GameAppMaxBenchmarksPerProfile,
                GameAppMaxSessionsPerProfile = GameAppMaxSessionsPerProfile,
                GameAppBenchmarkSettleSeconds = GameAppBenchmarkSettleSeconds,
                GameAppAllowLaunchingApplications = GameAppAllowLaunchingApplications
            };

            return clone;
        }

        #endregion
    }
}

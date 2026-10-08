using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Text.Json.Serialization;

namespace AISystemOptimizer.Core.GameApp.Models
{
    #region Settings enums

    /// <summary>
    /// The process priority a profile may ask for.
    ///
    /// The range is deliberately closed: <c>RealTime</c> is not representable, because a real-time
    /// process can starve the input and audio threads and make the machine unusable. The value is
    /// clamped to this range on load as well, so a hand-edited profile file cannot widen it.
    /// </summary>
    public enum ProcessPriorityPreference
    {
        [Description("Leave as it is")]
        LeaveUnchanged,

        [Description("Below normal")]
        BelowNormal,

        [Description("Normal")]
        Normal,

        [Description("Above normal")]
        AboveNormal,

        [Description("High")]
        High
    }

    /// <summary>Windows power mode a profile may request while the application runs.</summary>
    public enum PowerPreference
    {
        [Description("Leave as it is")]
        LeaveUnchanged,

        [Description("Balanced")]
        Balanced,

        [Description("Best performance")]
        HighPerformance,

        [Description("Power saving")]
        PowerSaver
    }

    /// <summary>Windows graphics preference for the application (Settings → Display → Graphics).</summary>
    public enum GraphicsPreference
    {
        [Description("Let Windows decide")]
        LetWindowsDecide,

        [Description("Power saving")]
        PowerSaving,

        [Description("High performance")]
        HighPerformance
    }

    /// <summary>
    /// How far a profile may go in cleaning an application's temporary files.
    ///
    /// There is no "delete everything" member. Only locations the application itself declares as
    /// temporary are in scope, and the deletion itself is a separate, confirmed step.
    /// </summary>
    public enum DiskCleanupScope
    {
        [Description("Do not touch any files")]
        None,

        /// <summary>Report locations and their sizes; delete nothing without an explicit confirmation.</summary>
        [Description("Identify temporary files only")]
        IdentifyOnly
    }

    /// <summary>What to do about one background process.</summary>
    public enum BackgroundProcessDecision
    {
        [Description("Allowed by this profile's rules")]
        AllowOptimization,

        [Description("Never optimise")]
        NeverOptimize,

        [Description("Ask every time")]
        AskEveryTime
    }

    /// <summary>What happens when the user launches the application while the optimiser is running.</summary>
    public enum ProfileStartupBehavior
    {
        [Description("Do nothing")]
        Nothing,

        [Description("Ask before applying")]
        AskOnLaunch,

        [Description("Apply this profile automatically")]
        ApplyOnLaunch
    }

    #endregion

    #region Profile sections

    /// <summary>CPU-related limits for one application. Priority only - never affinity, never clocks.</summary>
    public sealed class CpuProfileSettings
    {
        /// <summary>Whether this section may change anything at all for this application.</summary>
        public bool Enabled { get; set; } = true;

        public ProcessPriorityPreference Priority { get; set; } = ProcessPriorityPreference.LeaveUnchanged;

        /// <summary>
        /// Read-only in the model on purpose. Cores are never parked or un-parked by this feature: on a
        /// machine doing anything else, forcing affinity makes things worse, and the specification
        /// forbids it. The value is exposed so the interface can *show* affinity.
        /// </summary>
        [JsonIgnore]
        public bool AffinityIsNeverModified => true;
    }

    /// <summary>RAM-related limits for one application.</summary>
    public sealed class RamProfileSettings
    {
        /// <summary>Whether this section may change anything at all for this application.</summary>
        public bool Enabled { get; set; } = true;

        /// <summary>Whether background processes may be closed at all under this profile.</summary>
        public bool CloseBackgroundProcesses { get; set; } = true;

        /// <summary>Upper limit on how many background processes one session may close. Conservative by design.</summary>
        public int MaxBackgroundProcessesPerSession { get; set; } = 5;

        /// <summary>A process using less than this is not worth touching.</summary>
        public int MinimumWorkingSetMegabytes { get; set; } = 50;
    }

    /// <summary>GPU-related settings for one application.</summary>
    public sealed class GpuProfileSettings
    {
        /// <summary>Whether this section may change anything at all for this application.</summary>
        public bool Enabled { get; set; } = true;

        public GraphicsPreference GraphicsPreference { get; set; } = GraphicsPreference.LetWindowsDecide;

        /// <summary>
        /// Whether GPU-heavy background applications may be proposed for closing. Proposals only -
        /// every one still passes through the safety validator and the user's confirmation.
        /// </summary>
        public bool CloseGpuHeavyBackgroundApplications { get; set; } = true;
    }

    /// <summary>Disk-related settings for one application.</summary>
    public sealed class DiskProfileSettings
    {
        /// <summary>Whether this section may change anything at all for this application.</summary>
        public bool Enabled { get; set; } = true;

        public DiskCleanupScope CleanupScope { get; set; } = DiskCleanupScope.None;

        /// <summary>
        /// Whether the session reports the application's disk activity while it runs. This is a reading,
        /// not a change: the optimiser never defragments, never re-reads an SSD and never runs a disk
        /// command on its own.
        /// </summary>
        public bool ReportRuntimeActivity { get; set; } = true;

        /// <summary>True by default and not negotiable in the UI: nothing is deleted without a warning.</summary>
        public bool WarnBeforeDeleting { get; set; } = true;

        /// <summary>
        /// True by default: application data and save files are never in scope, whatever the scope
        /// setting says. Present so a hand-edited profile cannot remove the guarantee.
        /// </summary>
        [JsonIgnore]
        public bool SaveFilesAreNeverInScope => true;
    }

    /// <summary>
    /// Network settings for one application.
    ///
    /// There is exactly one honest thing to record here: whether the application's own network activity
    /// should be measured and shown. Nothing in this section can change the network: no adapter setting,
    /// no DNS, no router, no network stack, and no promise about latency. The guarantee is expressed as a
    /// read-only property so that a hand-edited profile file cannot remove it.
    /// </summary>
    public sealed class NetworkProfileSettings
    {
        /// <summary>Whether the application's network activity is shown in the session report.</summary>
        public bool ReportActivity { get; set; } = true;

        /// <summary>
        /// Read-only: the optimiser never changes DNS, adapters, the routing table or the network stack,
        /// and never claims a latency improvement it did not measure.
        /// </summary>
        [JsonIgnore]
        public bool NetworkSettingsAreNeverChanged => true;
    }

    /// <summary>Power-related settings for one application.</summary>
    public sealed class PowerProfileSettings
    {
        /// <summary>Whether this section may change anything at all for this application.</summary>
        public bool Enabled { get; set; } = true;

        public PowerPreference ModeWhileRunning { get; set; } = PowerPreference.LeaveUnchanged;

        /// <summary>Restore the previous power scheme when the application exits.</summary>
        public bool RestoreAfterExit { get; set; } = true;
    }

    /// <summary>
    /// How this application behaves in Game Mode.
    /// </summary>
    public sealed class ProfileBehaviorSettings
    {
        public ProfileStartupBehavior OnLaunch { get; set; } = ProfileStartupBehavior.Nothing;

        /// <summary>
        /// Off unless the user turns it on. The specification requires automatic optimisation to be off
        /// by default, and an application profile is exactly the thing a user would not expect to act on
        /// its own the first time.
        /// </summary>
        public bool AutoOptimize { get; set; }

        /// <summary>Watch for the application starting and stopping while the optimiser runs.</summary>
        public bool WatchForLaunch { get; set; }

        public bool RestoreAfterExit { get; set; } = true;
    }

    /// <summary>
    /// One rule about one background process, in the words the user chose.
    /// </summary>
    public sealed class BackgroundProcessRule
    {
        /// <summary>Process name without the extension, or the executable path when <see cref="MatchByPath"/>.</summary>
        public string Target { get; set; } = string.Empty;

        public bool MatchByPath { get; set; }

        public BackgroundProcessDecision Decision { get; set; } = BackgroundProcessDecision.AskEveryTime;

        public DateTime AddedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>Why the user chose this, so the session report can quote it.</summary>
        public string Reason { get; set; } = string.Empty;

        /// <summary>
        /// Which rule wins for a process named <paramref name="processName"/> at <paramref name="path"/>.
        ///
        /// Ordering rule: <c>NeverOptimize</c> beats everything. That means one list can only ever make
        /// the feature *more* careful - a rule added later can never re-enable something an earlier rule
        /// protects, and neither can re-enable something the hard system protections cover.
        /// </summary>
        public static BackgroundProcessDecision Resolve(
            IEnumerable<BackgroundProcessRule> rules,
            string processName,
            string path)
        {
            var relevant = (rules ?? Enumerable.Empty<BackgroundProcessRule>())
                .Where(r => r != null && Matches(r, processName, path))
                .ToList();

            if (relevant.Any(r => r.Decision == BackgroundProcessDecision.NeverOptimize))
                return BackgroundProcessDecision.NeverOptimize;

            if (relevant.Any(r => r.Decision == BackgroundProcessDecision.AllowOptimization))
                return BackgroundProcessDecision.AllowOptimization;

            return BackgroundProcessDecision.AskEveryTime;
        }

        /// <summary>True when one rule matches a process.</summary>
        public static bool Matches(BackgroundProcessRule rule, string processName, string path)
        {
            if (rule == null || string.IsNullOrWhiteSpace(rule.Target))
                return false;

            var target = rule.Target.Trim().Trim('"');

            if (rule.MatchByPath)
            {
                if (string.IsNullOrWhiteSpace(path))
                    return false;

                return Normalise(path).Equals(Normalise(target), StringComparison.OrdinalIgnoreCase);
            }

            var name = System.IO.Path.GetFileNameWithoutExtension(processName ?? string.Empty);
            var targetName = System.IO.Path.GetFileNameWithoutExtension(target);

            return name.Equals(targetName, StringComparison.OrdinalIgnoreCase);
        }

        private static string Normalise(string value) =>
            value.Trim().Trim('"').Replace('/', '\\').TrimEnd('\\');
    }

    #endregion

    #region History records

    /// <summary>
    /// One measurement of an application, taken before or after an optimisation.
    ///
    /// Every field is either a real reading or null. A null is displayed as N/A, never as zero and never
    /// as an estimate.
    /// </summary>
    public sealed class BenchmarkSample
    {
        public float? RamPercent { get; set; }
        public long? RamMegabytes { get; set; }
        public float? CpuPercent { get; set; }
        public float? GpuPercent { get; set; }
        public long? GpuMemoryBytes { get; set; }
        public float? DiskActivityPercent { get; set; }
        public float? NetworkMegabitsPerSecond { get; set; }
        public int? ApplicationProcessCount { get; set; }
        public long? ApplicationWorkingSetBytes { get; set; }
        public long? ApplicationPrivateBytes { get; set; }

        public DateTime CapturedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>
        /// Frames per second, when and only when a reliable source exists. Windows exposes no such source
        /// to a normal process, so this stays null and the report says so.
        /// </summary>
        public double? Fps { get; set; }

        /// <summary>Where <see cref="Fps"/> came from, or why it is absent.</summary>
        public string FpsSource { get; set; } = FpsUnavailableReason;

        public const string FpsUnavailableReason = "N/A - FPS source unavailable.";

        /// <summary>How long the application took to reach a responsive state, when it was measured.</summary>
        public double? LaunchTimeMilliseconds { get; set; }
    }

    /// <summary>
    /// A before/after pair for one profile, with the arithmetic done once so the interface cannot
    /// disagree with the record.
    /// </summary>
    public sealed class BenchmarkRecord
    {
        public Guid Id { get; set; } = Guid.NewGuid();

        public string Label { get; set; } = string.Empty;

        public DateTime RecordedAtUtc { get; set; } = DateTime.UtcNow;

        public BenchmarkSample? Before { get; set; }
        public BenchmarkSample? After { get; set; }

        /// <summary>How long the optimiser waited before taking the "after" sample.</summary>
        public int SettleSeconds { get; set; }

        /// <summary>Actions that were applied between the two samples.</summary>
        public List<string> AppliedActions { get; set; } = new List<string>();

        /// <summary>Actions that were proposed and refused, with the reason.</summary>
        public List<string> RefusedActions { get; set; } = new List<string>();

        /// <summary>
        /// RAM change in percentage points. Positive means the application used *more* afterwards.
        /// Deliberately points, not percent: the specification is explicit that 50% → 48% is
        /// "2 percentage points", not "4 percent better".
        /// </summary>
        public float? RamDeltaPoints => Delta(Before?.RamPercent, After?.RamPercent);

        public float? CpuDeltaPoints => Delta(Before?.CpuPercent, After?.CpuPercent);

        public float? GpuDeltaPoints => Delta(Before?.GpuPercent, After?.GpuPercent);

        public float? DiskDeltaPoints => Delta(Before?.DiskActivityPercent, After?.DiskActivityPercent);

        private static float? Delta(float? before, float? after) =>
            before.HasValue && after.HasValue ? after.Value - before.Value : null;

        /// <summary>True when nothing measurable changed, so the report can say so instead of implying success.</summary>
        public bool NoMeasurableChange =>
            RamDeltaPoints is null or < 0.5f and > -0.5f &&
            CpuDeltaPoints is null or < 0.5f and > -0.5f;

        /// <summary>The sentence shown next to a delta, or the reason there is none.</summary>
        public static string DescribeDelta(string name, float? points)
        {
            if (!points.HasValue)
                return $"{name}: N/A - no comparable readings.";

            var sign = points.Value > 0 ? "+" : string.Empty;

            return $"{name}: {sign}{points.Value:F1} percentage points";
        }
    }

    /// <summary>One line of a profile's optimisation history.</summary>
    public sealed class ProfileSessionSummary
    {
        public Guid SessionId { get; set; } = Guid.NewGuid();

        public DateTime StartedAtUtc { get; set; } = DateTime.UtcNow;

        public DateTime? CompletedAtUtc { get; set; }

        public string Trigger { get; set; } = "Manual";

        public int AppliedCount { get; set; }

        public int RefusedCount { get; set; }

        public int RestoredCount { get; set; }

        public bool WasRestored { get; set; }

        /// <summary>True when the session was still open when the application last started.</summary>
        public bool WasInterrupted { get; set; }

        public string Summary { get; set; } = string.Empty;
    }

    #endregion

    #region The profile

    /// <summary>
    /// Everything the application knows about one executable the user added.
    ///
    /// The profile is the only thing that is created when an application is added: adding never changes
    /// the system, never starts the program and never touches the registry. Optimisation happens later,
    /// and only on a user request or on an explicitly enabled auto-optimise.
    /// </summary>
    public sealed class GameAppProfile
    {
        /// <summary>Schema version of the profile file, so an older build can refuse a newer file.</summary>
        public const int CurrentSchemaVersion = 1;

        public int SchemaVersion { get; set; } = CurrentSchemaVersion;

        /// <summary>Stable identifier of this profile. Assignment is random and the file is named after it.</summary>
        public Guid ApplicationId { get; set; } = Guid.NewGuid();

        /// <summary>What the user called it, defaulting to the product name or the file name.</summary>
        public string DisplayName { get; set; } = string.Empty;

        /// <summary>The user's description of what this application is. Never inferred as "Game".</summary>
        public ApplicationKind Kind { get; set; } = ApplicationKind.Unknown;

        public GameAppProfileMode ProfileMode { get; set; } = GameAppProfileMode.Balanced;

        /// <summary>
        /// The identity the profile was built for. Compared against the file before any action.
        /// </summary>
        public ExecutableIdentity Identity { get; set; } = new ExecutableIdentity();

        /// <summary>
        /// Optional launcher that starts the real target (Steam, Epic, a batch wrapper). Explicit user
        /// configuration - never guessed from a list of known launchers.
        /// </summary>
        public string LauncherPath { get; set; } = string.Empty;

        /// <summary>
        /// Arguments for the launcher, one per entry, in the order they are passed.
        ///
        /// They are stored as a list rather than a string on purpose. A single string would have to be
        /// split, and every splitter that has ever been written decides - slightly differently - what a
        /// quote means. A list cannot be mis-split: each entry is exactly one argument, handed to
        /// <c>ProcessStartInfo.ArgumentList</c>, so there is no shell, no quoting, and no way for one
        /// argument to become two, or to become a command.
        /// </summary>
        public List<string> LauncherArgumentList { get; set; } = new List<string>();

        /// <summary>
        /// The executable the launcher will start, when it is not this profile's own executable. This is
        /// what the session watches for: a launcher usually stays alive and spawns the real target, and
        /// matching on the launcher would measure the wrong process.
        /// </summary>
        public string LauncherTargetPath { get; set; } = string.Empty;

        /// <summary>
        /// True when this profile is configured for a launcher: an explicit launcher path and an explicit
        /// target. Never inferred from a list of "known" launchers, because guessing which program is a
        /// launcher is exactly how the wrong process ends up being watched.
        /// </summary>
        [System.Text.Json.Serialization.JsonIgnore]
        public bool UsesLauncher =>
            !string.IsNullOrWhiteSpace(LauncherPath) && !string.IsNullOrWhiteSpace(LauncherTargetPath);

        /// <summary>True when the profile is active. A suspended profile is never applied.</summary>
        public bool Enabled { get; set; } = true;

        #region Settings

        public CpuProfileSettings Cpu { get; set; } = new CpuProfileSettings();
        public RamProfileSettings Ram { get; set; } = new RamProfileSettings();
        public GpuProfileSettings Gpu { get; set; } = new GpuProfileSettings();
        public DiskProfileSettings Disk { get; set; } = new DiskProfileSettings();
        public PowerProfileSettings Power { get; set; } = new PowerProfileSettings();
        public NetworkProfileSettings Network { get; set; } = new NetworkProfileSettings();
        public ProfileBehaviorSettings Behavior { get; set; } = new ProfileBehaviorSettings();

        /// <summary>Per-application background-process rules. More restrictive rules win.</summary>
        public List<BackgroundProcessRule> BackgroundRules { get; set; } = new List<BackgroundProcessRule>();

        #endregion

        #region History

        public List<BenchmarkRecord> Benchmarks { get; set; } = new List<BenchmarkRecord>();

        public List<ProfileSessionSummary> Sessions { get; set; } = new List<ProfileSessionSummary>();

        #endregion

        #region Timestamps and state

        public DateTime CreatedAtUtc { get; set; } = DateTime.UtcNow;

        public DateTime UpdatedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>Last time the executable was checked against the profile.</summary>
        public DateTime? LastVerifiedAtUtc { get; set; }

        /// <summary>Last health result, for display. Recomputed on load; never trusted from the file.</summary>
        public ApplicationHealthState LastKnownHealth { get; set; } = ApplicationHealthState.NotChecked;

        #endregion

        #region Derived

        [JsonIgnore]
        public string ExecutablePath => Identity?.ExecutablePath ?? string.Empty;

        [JsonIgnore]
        public string FileName => Identity?.FileName ?? string.Empty;

        [JsonIgnore]
        public bool HasBenchmarks => Benchmarks != null && Benchmarks.Count > 0;

        [JsonIgnore]
        public BenchmarkRecord? LatestBenchmark =>
            Benchmarks == null || Benchmarks.Count == 0
                ? null
                : Benchmarks.OrderByDescending(b => b.RecordedAtUtc).First();

        /// <summary>
        /// The name to show. Falls back through product name, file name, then the identifier, so a
        /// profile is never blank in the interface.
        /// </summary>
        public string ResolveDisplayName()
        {
            if (!string.IsNullOrWhiteSpace(DisplayName)) return DisplayName.Trim();
            if (!string.IsNullOrWhiteSpace(Identity?.ProductName)) return Identity!.ProductName.Trim();
            if (!string.IsNullOrWhiteSpace(Identity?.FileName)) return Identity!.FileName;
            return ApplicationId.ToString();
        }

        #endregion

        #region Limits

        /// <summary>
        /// Keep the history lists inside sane bounds. Called by the store on every load and save so a
        /// profile cannot grow without limit over years of use.
        /// </summary>
        public void TrimHistory(int maxBenchmarks, int maxSessions)
        {
            if (Benchmarks != null && maxBenchmarks > 0 && Benchmarks.Count > maxBenchmarks)
            {
                Benchmarks = Benchmarks
                    .OrderByDescending(b => b.RecordedAtUtc)
                    .Take(maxBenchmarks)
                    .OrderBy(b => b.RecordedAtUtc)
                    .ToList();
            }

            if (Sessions != null && maxSessions > 0 && Sessions.Count > maxSessions)
            {
                Sessions = Sessions
                    .OrderByDescending(s => s.StartedAtUtc)
                    .Take(maxSessions)
                    .OrderBy(s => s.StartedAtUtc)
                    .ToList();
            }
        }

        /// <summary>
        /// Clamp every value into its supported range and report each adjustment.
        ///
        /// A profile file is user-editable (and the user was invited to edit it), so it is untrusted
        /// input. Out-of-range values are corrected rather than obeyed, and the correction is reported
        /// in the same style the configuration loader uses.
        /// </summary>
        /// <summary>
        /// Check the launcher arguments and drop anything that is not a plain argument.
        ///
        /// An argument is a value that will be passed to a program. It must not contain a control
        /// character or a line break (either can turn one argument into two at some later layer), and it
        /// is length-capped. Nothing here interprets, expands or rewrites an argument: a value that is
        /// rejected is removed and reported, never repaired into something else.
        /// </summary>
        public List<string> NormalizeLauncherArguments()
        {
            var rejected = new List<string>();
            var kept = new List<string>();

            foreach (var argument in LauncherArgumentList ?? new List<string>())
            {
                if (argument == null)
                    continue;

                var value = argument;

                if (value.Length > 512 || value.IndexOfAny(new[] { '\r', '\n', '\0' }) >= 0 ||
                    value.Any(c => c < ' '))
                {
                    rejected.Add(value.Length > 60 ? value.Substring(0, 60) + "…" : value);
                    continue;
                }

                kept.Add(value);
            }

            if (rejected.Count > 0)
                LauncherArgumentList = kept;

            return rejected;
        }

        public List<string> NormalizeToSupportedRanges()
        {
            var adjustments = new List<string>();

            if (SchemaVersion <= 0 || SchemaVersion > CurrentSchemaVersion)
            {
                adjustments.Add($"schemaVersion {SchemaVersion} is not supported; using {CurrentSchemaVersion}");
                SchemaVersion = CurrentSchemaVersion;
            }

            if (BackgroundRules == null)
            {
                BackgroundRules = new List<BackgroundProcessRule>();
                adjustments.Add("backgroundRules was missing; an empty list was used");
            }

            if (Benchmarks == null)
            {
                Benchmarks = new List<BenchmarkRecord>();
                adjustments.Add("benchmarks was missing; an empty list was used");
            }

            if (Sessions == null)
            {
                Sessions = new List<ProfileSessionSummary>();
                adjustments.Add("sessions was missing; an empty list was used");
            }

            Cpu ??= new CpuProfileSettings();
            Ram ??= new RamProfileSettings();
            Gpu ??= new GpuProfileSettings();
            Disk ??= new DiskProfileSettings();
            Power ??= new PowerProfileSettings();
            Behavior ??= new ProfileBehaviorSettings();

            if (!Enum.IsDefined(typeof(ProcessPriorityPreference), Cpu.Priority))
            {
                adjustments.Add($"cpu.priority {Cpu.Priority} is not a supported value; leaving the priority unchanged");
                Cpu.Priority = ProcessPriorityPreference.LeaveUnchanged;
            }

            if (!Enum.IsDefined(typeof(PowerPreference), Power.ModeWhileRunning))
            {
                adjustments.Add($"power.modeWhileRunning {Power.ModeWhileRunning} is not a supported value; leaving the power mode unchanged");
                Power.ModeWhileRunning = PowerPreference.LeaveUnchanged;
            }

            if (!Enum.IsDefined(typeof(GraphicsPreference), Gpu.GraphicsPreference))
            {
                adjustments.Add($"gpu.graphicsPreference {Gpu.GraphicsPreference} is not a supported value; using 'Let Windows decide'");
                Gpu.GraphicsPreference = GraphicsPreference.LetWindowsDecide;
            }

            if (!Enum.IsDefined(typeof(DiskCleanupScope), Disk.CleanupScope))
            {
                adjustments.Add($"disk.cleanupScope {Disk.CleanupScope} is not a supported value; touching no files");
                Disk.CleanupScope = DiskCleanupScope.None;
            }

            if (!Enum.IsDefined(typeof(GameAppProfileMode), ProfileMode))
            {
                adjustments.Add($"profileMode {ProfileMode} is not a supported value; using Balanced");
                ProfileMode = GameAppProfileMode.Balanced;
            }

            if (!Enum.IsDefined(typeof(ApplicationKind), Kind))
            {
                adjustments.Add($"kind {Kind} is not a supported value; using Unknown");
                Kind = ApplicationKind.Unknown;
            }

            var before = Ram.MaxBackgroundProcessesPerSession;
            Ram.MaxBackgroundProcessesPerSession = Math.Clamp(Ram.MaxBackgroundProcessesPerSession, 0, 20);
            if (before != Ram.MaxBackgroundProcessesPerSession)
                adjustments.Add($"ram.maxBackgroundProcessesPerSession {before} was clamped to {Ram.MaxBackgroundProcessesPerSession}");

            before = Ram.MinimumWorkingSetMegabytes;
            Ram.MinimumWorkingSetMegabytes = Math.Clamp(Ram.MinimumWorkingSetMegabytes, 10, 4096);
            if (before != Ram.MinimumWorkingSetMegabytes)
                adjustments.Add($"ram.minimumWorkingSetMegabytes {before} was clamped to {Ram.MinimumWorkingSetMegabytes}");

            // A profile file could set this to false by hand; the field exists only so the guarantee is
            // visible in the file, and it is restored here rather than honoured.
            if (!Disk.WarnBeforeDeleting)
            {
                Disk.WarnBeforeDeleting = true;
                adjustments.Add("disk.warnBeforeDeleting cannot be disabled; it was restored to true");
            }

            // Same for the never-delete-save-files guarantee: it is not a setting, it is a rule.
            if (Disk.CleanupScope != DiskCleanupScope.None && Disk.CleanupScope != DiskCleanupScope.IdentifyOnly)
            {
                Disk.CleanupScope = DiskCleanupScope.None;
                adjustments.Add("disk.cleanupScope is limited to reporting only; touching no files");
            }

            // Effective settings for Custom mode: nothing may be switched on by a file that claims
            // "Custom" without the user having chosen anything.
            if (ProfileMode == GameAppProfileMode.Custom)
            {
                if (Cpu.Priority == ProcessPriorityPreference.LeaveUnchanged &&
                    Power.ModeWhileRunning == PowerPreference.LeaveUnchanged &&
                    Gpu.GraphicsPreference == GraphicsPreference.LetWindowsDecide &&
                    !Ram.CloseBackgroundProcesses &&
                    !Gpu.CloseGpuHeavyBackgroundApplications)
                {
                    adjustments.Add("profileMode is Custom but no custom action is selected; the profile will change nothing");
                }
            }

            if (string.IsNullOrWhiteSpace(DisplayName))
            {
                var resolved = ResolveDisplayName();
                if (!string.IsNullOrWhiteSpace(resolved))
                {
                    DisplayName = resolved;
                    adjustments.Add("displayName was empty and was filled in from the executable metadata");
                }
            }

            return adjustments;
        }

        #endregion

        /// <summary>A deep copy, used when a caller must not mutate the stored instance.</summary>
        public GameAppProfile Clone()
        {
            var json = System.Text.Json.JsonSerializer.Serialize(this, GameAppProfileJson.Options);
            return System.Text.Json.JsonSerializer.Deserialize<GameAppProfile>(json, GameAppProfileJson.Options)
                   ?? new GameAppProfile();
        }
    }

    /// <summary>
    /// The serializer settings for profile files, kept in one place so the store, the clone and the
    /// tests cannot drift apart.
    /// </summary>
    public static class GameAppProfileJson
    {
        public static readonly System.Text.Json.JsonSerializerOptions Options = new System.Text.Json.JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            ReadCommentHandling = System.Text.Json.JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
            Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter(allowIntegerValues: true) },
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.Never
        };
    }

    #endregion
}

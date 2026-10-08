using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AISystemOptimizer.Core.GameApp.Models
{
    /// <summary>One change that was made, with everything needed to reverse it.</summary>
    public sealed class SessionChangeRecord
    {
        public Guid Id { get; set; } = Guid.NewGuid();

        public Guid ApplicationId { get; set; }

        /// <summary>The kind of change: "Priority", "PowerScheme", "GraphicsPreference", "ClosedProcess".</summary>
        public string Kind { get; set; } = string.Empty;

        /// <summary>What the setting was before. Empty when there was no value before.</summary>
        public string OriginalValue { get; set; } = string.Empty;

        public string NewValue { get; set; } = string.Empty;

        public DateTime ChangedAtUtc { get; set; } = DateTime.UtcNow;

        public string Reason { get; set; } = string.Empty;

        /// <summary>True when reversing this means removing the value rather than setting one back.</summary>
        public bool OriginalValueWasAbsent { get; set; }

        /// <summary>Process id, for the changes that are about a process.</summary>
        public int TargetProcessId { get; set; }

        /// <summary>
        /// Creation time of the target process when the change was made. A process must be re-identified
        /// with this before anything is done to it again - the pid alone is not the process.
        /// </summary>
        public DateTime TargetCreationTimeUtc { get; set; }

        public string TargetPath { get; set; } = string.Empty;

        public string TargetName { get; set; } = string.Empty;

        /// <summary>
        /// True when the change can be reversed at all. Closing a process cannot: the session records
        /// that so it is never presented as restored.
        /// </summary>
        public bool IsReversible { get; set; } = true;

        /// <summary>Set when a restore attempt failed, with the exact reason. Never cleared silently.</summary>
        public string RestoreFailureReason { get; set; } = string.Empty;

        public bool WasRestored { get; set; }

        /// <summary>Even a non-reversible change describes what it did, so the user can act themselves.</summary>
        public string Describe() =>
            $"{Kind}: '{OriginalValue}' -> '{NewValue}'" +
            (string.IsNullOrEmpty(TargetName) ? string.Empty : $" ({TargetName})") +
            (IsReversible ? string.Empty : " - cannot be undone automatically");
    }

    /// <summary>
    /// One optimisation session: what was applied for one application, what it recorded, and whether it
    /// was put back.
    ///
    /// This is the record the specification requires before anything is changed:
    /// SessionId, ApplicationId, StartTime, the original power plan, the original priority, the original
    /// graphics preference, which processes were closed, which services were stopped, and any other
    /// reversible change. It is written to disk *before* the first change is made, so a crash in the first
    /// second is still recoverable.
    /// </summary>
    public sealed class GameAppSession
    {
        public const int CurrentSchemaVersion = 1;

        public int SchemaVersion { get; set; } = CurrentSchemaVersion;

        public Guid SessionId { get; set; } = Guid.NewGuid();

        public Guid ApplicationId { get; set; }

        public string ApplicationName { get; set; } = string.Empty;

        public string ExecutablePath { get; set; } = string.Empty;

        /// <summary>SHA-256 of the executable when the session started, so a replace is detectable.</summary>
        public string ExecutableHash { get; set; } = string.Empty;

        public DateTime StartTimeUtc { get; set; } = DateTime.UtcNow;

        public DateTime? EndTimeUtc { get; set; }

        public bool IsOpen { get; set; } = true;

        /// <summary>What started the session: "Manual", "Launch", "Auto", "Benchmark".</summary>
        public string Trigger { get; set; } = "Manual";

        /// <summary>The power scheme that was active before anything was changed. Empty when untouched.</summary>
        public string OriginalPowerPlan { get; set; } = string.Empty;

        /// <summary>Priority of the application's process before anything was changed, as text.</summary>
        public string OriginalPriority { get; set; } = string.Empty;

        public GraphicsPreference? OriginalGraphicsPreference { get; set; }

        /// <summary>Everything that was changed, each with its own rollback information.</summary>
        public List<SessionChangeRecord> Changes { get; set; } = new List<SessionChangeRecord>();

        /// <summary>Processes that were closed, recorded so the user can start them again.</summary>
        public List<string> ClosedProcesses { get; set; } = new List<string>();

        /// <summary>Services that were stopped. Empty in normal use: services are not stopped by this feature.</summary>
        public List<string> StoppedServices { get; set; } = new List<string>();

        /// <summary>Anything the planner wanted to do and refused, with the reason, for the history.</summary>
        public List<string> RefusedActions { get; set; } = new List<string>();

        /// <summary>True when the session was left open - the optimiser exited or crashed while it ran.</summary>
        public bool WasInterrupted { get; set; }

        /// <summary>True only when every reversible change was verified back in place.</summary>
        public bool WasRestored { get; set; }

        /// <summary>Exact failures from the restore, in the order they happened. Never summarised away.</summary>
        public List<string> RestoreFailures { get; set; } = new List<string>();

        public List<string> RestoreNotes { get; set; } = new List<string>();

        [JsonIgnore]
        public IEnumerable<SessionChangeRecord> ReversibleChanges => Changes.Where(c => c.IsReversible);

        [JsonIgnore]
        public IEnumerable<SessionChangeRecord> UnreversibleChanges => Changes.Where(c => !c.IsReversible);

        /// <summary>
        /// The sentence the specification requires for a session that did not finish.
        /// </summary>
        public string InterruptedSummary => "An optimization session was interrupted.";

        /// <summary>
        /// What happened, in a form the interface and the log can use without embellishment.
        /// </summary>
        public string Describe()
        {
            if (IsOpen)
            {
                return $"{ApplicationName}: session open since {StartTimeUtc.ToLocalTime():HH:mm:ss}, " +
                       $"{Changes.Count} change(s) made.";
            }

            if (!WasRestored && RestoreFailures.Count > 0)
            {
                return $"{ApplicationName}: session ended with {RestoreFailures.Count} restore failure(s). " +
                       "The exact failures are listed; nothing is claimed to have been restored.";
            }

            if (WasRestored && UnreversibleChanges.Any())
            {
                return $"{ApplicationName}: every reversible change was restored. " +
                       $"{UnreversibleChanges.Count()} change(s) could not be undone " +
                       "(a closed application stays closed) and are listed.";
            }

            return WasRestored
                ? $"{ApplicationName}: session ended, everything that was changed was restored."
                : $"{ApplicationName}: session ended. Restore status: not verified.";
        }

        public static JsonSerializerOptions JsonOptions { get; } = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            ReadCommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
            Converters = { new JsonStringEnumConverter() }
        };
    }
}

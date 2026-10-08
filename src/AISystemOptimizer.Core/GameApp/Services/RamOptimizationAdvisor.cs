using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// The memory figures shown in the RAM section, each with the definition the operating system uses.
    /// Keeping the definitions next to the numbers is deliberate: "used", "available" and "cached" are
    /// three different things, and a page that blurs them produces advice that makes a machine slower.
    /// </summary>
    public sealed class GameAppMemoryBreakdown
    {
        public long TotalBytes { get; init; }

        public long UsedBytes { get; init; }

        /// <summary>
        /// Memory the system can hand out, which already includes the reclaimable standby list. This is
        /// what Task Manager labels "Available", and it is why "free" memory is a small number on a healthy
        /// machine: Windows is using the rest as cache.
        /// </summary>
        public long AvailableBytes { get; init; }

        public long CachedBytes { get; init; }

        /// <summary>Null when the machine cannot report it - never a zero standing in for "unknown".</summary>
        public long? StandbyBytes { get; init; }

        public long CommittedBytes { get; init; }

        public long CommitLimitBytes { get; init; }

        public float UsedPercent => TotalBytes > 0 ? (float)((double)UsedBytes / TotalBytes * 100.0) : 0f;

        public float AvailablePercent => TotalBytes > 0 ? (float)((double)AvailableBytes / TotalBytes * 100.0) : 0f;

        public float CachedPercent => TotalBytes > 0 ? (float)((double)CachedBytes / TotalBytes * 100.0) : 0f;

        /// <summary>True when the machine is at a size where Windows itself takes a noticeable share.</summary>
        public bool IsSmallMachine => TotalBytes > 0 && TotalBytes <= 8L * 1024 * 1024 * 1024;

        public static string Format(long bytes) => bytes <= 0
            ? "N/A"
            : bytes >= 1024L * 1024 * 1024
                ? $"{bytes / (1024.0 * 1024 * 1024):F1} GB"
                : $"{bytes / (1024.0 * 1024):F0} MB";

        /// <summary>
        /// The three figures, labelled precisely enough that they cannot be confused with each other.
        /// </summary>
        public List<string> Describe()
        {
            var lines = new List<string>
            {
                $"Total: {Format(TotalBytes)}",
                $"In use: {Format(UsedBytes)} ({UsedPercent:F0}%)",
                $"Available: {Format(AvailableBytes)} ({AvailablePercent:F0}%)",
                $"Cached: {Format(CachedBytes)} ({CachedPercent:F0}%)"
            };

            lines.Add(StandbyBytes.HasValue
                ? $"Standby (reclaimable, already counted in Available): {Format(StandbyBytes.Value)}"
                : "Standby: N/A - this machine does not report the standby list.");

            if (CommitLimitBytes > 0)
            {
                lines.Add($"Committed: {Format(CommittedBytes)} of {Format(CommitLimitBytes)} " +
                          $"({(double)CommittedBytes / CommitLimitBytes * 100.0:F0}%)");
            }
            else
            {
                lines.Add("Committed: N/A - the commit limit could not be read.");
            }

            lines.Add(
                "Note: Available already includes the reclaimable standby list, so \"Available\" and " +
                "\"Cached\" describe memory Windows is holding ready to reuse, not memory that is lost.");

            return lines;
        }
    }

    /// <summary>
    /// What the optimiser may and may not say about memory.
    ///
    /// The rules this class exists to enforce:
    ///
    ///   * No fixed percentage is ever promised. A target may be shown, but it is a target for the user to
    ///     read, not a commitment, and the advice says so.
    ///   * A target that cannot be reached without unsafe actions produces exactly
    ///     "Safe optimization limit reached." - never a claim that it was reached by other means.
    ///   * Nothing here empties working sets, calls the garbage collector, clears caches or touches the
    ///     standby list. Those are not optimisations; they move work around and take it back seconds later.
    ///     The only mechanism offered is closing a *background application the user approves*, through the
    ///     existing safety pipeline.
    ///   * Windows' own share is accounted for, especially on an 8 GB machine, where the operating system
    ///     and its services legitimately hold most of a gigabyte before any user program starts.
    /// </summary>
    public static class RamOptimizationAdvisor
    {
        /// <summary>The sentence required when the safe limit has been reached.</summary>
        public const string SafeLimitReached = "Safe optimization limit reached.";

        /// <summary>What Windows itself typically holds on a machine of this size, from the measurement.</summary>
        public static long EstimateWindowsOverheadBytes(GameAppMemoryBreakdown memory)
        {
            // The figure is derived from the machine: the sum of the processes that cannot be touched,
            // which is what the caller measures, plus the pool and driver memory Windows reports. This
            // method exists mainly to keep the floor explicit: on an 8 GB machine at least 1.5 GB is
            // Windows, and the advice must not present that as waste.
            var floor = memory.IsSmallMachine ? 1536L * 1024 * 1024 : 2048L * 1024 * 1024;

            return Math.Min(floor, Math.Max(0, memory.UsedBytes - memory.TotalBytes / 8));
        }

        /// <summary>
        /// The answer to "can we reach this target?". It never asserts that a percentage was reached: it
        /// reports what closing the permitted background applications would free, and whether that is
        /// enough.
        /// </summary>
        public static RamOptimizationAdvice Evaluate(
            GameAppMemoryBreakdown memory,
            IEnumerable<BackgroundProcessAssessment> assessments,
            int? targetPercent,
            bool closeBackgroundProcessesAllowed)
        {
            if (memory == null)
                throw new ArgumentNullException(nameof(memory));

            // When the profile says nothing may be closed, no candidate is a candidate: keeping them in
            // the list would let the interface show a saving that this profile will never deliver.
            var permitted = (assessments ?? Enumerable.Empty<BackgroundProcessAssessment>())
                .Where(a => a.MayBeClosed)
                .ToList();

            var candidates = closeBackgroundProcessesAllowed
                ? permitted
                : new List<BackgroundProcessAssessment>();

            // A process's working set is not RAM that becomes free: only the pages that are actually
            // resident and private to it are released, and Windows keeps some as file cache. Counting the
            // whole working set would overstate the result by roughly half, so half is reported and the
            // reason for halving is stated in the text.
            var optimisticBytes = candidates.Sum(a => a.WorkingSet);
            var realisticBytes = (long)(optimisticBytes * 0.5);

            var advice = new RamOptimizationAdvice
            {
                Memory = memory,
                CandidateCount = candidates.Count,
                ReclaimableBytesIfAllClosed = realisticBytes,
                OptimisticBytesIfAllClosed = optimisticBytes,
                TargetPercent = targetPercent
            };

            advice.BlockedByProfile = !closeBackgroundProcessesAllowed;

            if (candidates.Count == 0)
            {
                advice.LimitReached = targetPercent.HasValue && memory.UsedPercent > targetPercent.Value;

                advice.Summary = !closeBackgroundProcessesAllowed
                    ? "This profile is set not to close background applications, so there is nothing this " +
                      "section can do. " + (advice.LimitReached ? SafeLimitReached : string.Empty)
                    : "No background application that this application is permitted to close is holding " +
                      "enough memory to be worth closing. " +
                      (advice.LimitReached ? SafeLimitReached : string.Empty);

                advice.Statements.Add(advice.Summary);
                return advice;
            }

            var projectedUsed = Math.Max(0, memory.UsedBytes - realisticBytes);
            var projectedPercent = memory.TotalBytes > 0
                ? (float)((double)projectedUsed / memory.TotalBytes * 100.0)
                : 0f;

            advice.ProjectedUsedBytes = projectedUsed;
            advice.ProjectedUsedPercent = projectedPercent;

            var reached = targetPercent.HasValue && projectedPercent <= targetPercent.Value;

            advice.LimitReached = targetPercent.HasValue && !reached;

            advice.Summary = targetPercent.HasValue
                ? reached
                    ? $"Closing the {candidates.Count} background application(s) you approved would bring " +
                      $"memory in use from {memory.UsedPercent:F0}% to about {projectedPercent:F0}%, which " +
                      $"meets your {targetPercent}% target. This is an estimate from the current working " +
                      "sets, not a guarantee."
                    : $"Closing the {candidates.Count} background application(s) you approved would bring " +
                      $"memory in use to about {projectedPercent:F0}%, which does not reach your " +
                      $"{targetPercent}% target. Reaching it would need changes this application will not " +
                      $"make. {SafeLimitReached}"
                : $"Closing the {candidates.Count} background application(s) you approved would free about " +
                  $"{GameAppMemoryBreakdown.Format(realisticBytes)}.";

            advice.Statements.Add(advice.Summary);

            if (!reached && targetPercent.HasValue)
            {
                advice.Statements.Add(
                    "What would reach the target - emptying every process's working set, clearing the " +
                    "standby list or disabling services Windows needs - is not offered: it either does " +
                    "nothing measurable or it makes the machine slower and less stable. " +
                    "Safe optimization limit reached.");
            }

            if (memory.IsSmallMachine)
            {
                advice.Statements.Add(
                    $"This machine has {GameAppMemoryBreakdown.Format(memory.TotalBytes)} of memory, of which " +
                    $"about {GameAppMemoryBreakdown.Format(EstimateWindowsOverheadBytes(memory))} is held by " +
                    "Windows itself and the programs that must keep running. A target below that is not " +
                    "achievable by closing background applications.");
            }

            advice.Statements.Add(
                "Memory that Windows is using as cache is not wasted memory: it is what makes the machine " +
                "feel fast, and it is released automatically when a program asks for it.");

            return advice;
        }
    }

    /// <summary>The result of evaluating a memory target.</summary>
    public sealed class RamOptimizationAdvice
    {
        public GameAppMemoryBreakdown Memory { get; set; } = new GameAppMemoryBreakdown();

        public int CandidateCount { get; set; }

        /// <summary>What closing the permitted applications would free, halved as described above.</summary>
        public long ReclaimableBytesIfAllClosed { get; set; }

        /// <summary>The raw sum of working sets, kept so the interface can explain the difference.</summary>
        public long OptimisticBytesIfAllClosed { get; set; }

        public int? TargetPercent { get; set; }

        public long ProjectedUsedBytes { get; set; }

        public float ProjectedUsedPercent { get; set; }

        /// <summary>True when the target cannot be met within the safety model.</summary>
        public bool LimitReached { get; set; }

        /// <summary>
        /// True when the profile itself forbids closing background applications, so the zero reclaimable
        /// figure is a setting rather than a measurement.
        /// </summary>
        public bool BlockedByProfile { get; set; }

        public string Summary { get; set; } = string.Empty;

        public List<string> Statements { get; } = new List<string>();

        public string DescribeReclaimable() =>
            ReclaimableBytesIfAllClosed > 0
                ? $"{GameAppMemoryBreakdown.Format(ReclaimableBytesIfAllClosed)} " +
                  $"(estimated from {GameAppMemoryBreakdown.Format(OptimisticBytesIfAllClosed)} of working set; " +
                  "only the resident, private part is actually released)"
                : "nothing";
    }
}

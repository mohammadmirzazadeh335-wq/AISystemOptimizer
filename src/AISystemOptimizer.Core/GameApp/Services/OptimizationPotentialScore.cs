using System;
using System.Collections.Generic;
using System.Linq;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One contribution to the score, with the measurement that produced it.
    /// </summary>
    public sealed class ScoreComponent
    {
        /// <summary>What was measured, for example "RAM pressure".</summary>
        public string Name { get; init; } = string.Empty;

        /// <summary>The points this component contributes. Always in [-10, +40].</summary>
        public int Points { get; init; }

        /// <summary>The most this component can contribute at all. Never zero.</summary>
        public int MaximumPoints { get; init; }

        /// <summary>The reading that produced the points, in the units it was measured in.</summary>
        public string Measurement { get; init; } = string.Empty;

        /// <summary>Why this matters at all. One sentence, no jargon.</summary>
        public string Explanation { get; init; } = string.Empty;

        public string Score => $"+{Points}";
    }

    /// <summary>
    /// The "Optimization Potential" score.
    ///
    /// The specification is explicit that this number must be transparent and itemised rather than
    /// arbitrary, so the score is nothing more than the sum of six components, each of which carries the
    /// reading that produced it and a sentence saying why. A user can add the numbers up themselves and
    /// disagree with any of them.
    ///
    /// The shape of the scale:
    ///   * RAM pressure            0-30
    ///   * CPU background load     0-20
    ///   * GPU background load     0-10
    ///   * Power mode              0-12
    ///   * Disk pressure           0-10
    ///   * Application size        0-8
    /// Maximum 90, displayed out of 100, because a score of 100 would claim there is nothing left to
    /// gain, which no measurement here can support.
    ///
    /// A component can also be negative - closing nothing because there is nothing to close is not a
    /// defect, but presenting it as an opportunity would be dishonest, so a machine already at rest
    /// scores low rather than being rounded up.
    /// </summary>
    public static class OptimizationPotentialScore
    {
        public const int MaximumScore = 90;

        /// <summary>
        /// RAM pressure: the closer the machine is to being unable to serve a working set without paging,
        /// the more there is to gain. Measured from the same figures the dashboard shows.
        /// </summary>
        public static ScoreComponent RamPressure(float ramPercentAvailable, long totalMemoryBytes, int reclaimableMegabytes)
        {
            // A machine below 55% "in use" is not under pressure: Windows is using memory as a cache,
            // which is what it is for. Above 85%, paging is likely and the score climbs quickly.
            var points = ramPercentAvailable switch
            {
                < 55f => 0,
                < 65f => 8,
                < 75f => 15,
                < 85f => 22,
                _ => 30
            };

            // What can actually be freed matters more than a percentage: on an 8 GB machine, 8 points of
            // "pressure" may be 600 MB, and on a 64 GB machine it may be 5 GB.
            var reclaimableFraction = totalMemoryBytes > 0
                ? (double)reclaimableMegabytes * 1024 * 1024 / totalMemoryBytes
                : 0;

            if (reclaimableFraction < 0.01 && points > 8)
            {
                // Less than one percent of RAM is realistically reclaimable, so most of the theoretical
                // win is not there. Deliberately reported rather than papered over.
                points = Math.Max(0, points - 10);
            }

            return new ScoreComponent
            {
                Name = "RAM pressure",
                Points = points,
                MaximumPoints = 30,
                Measurement = $"{ramPercentAvailable:F0}% in use, about {reclaimableMegabytes} MB reclaimable",
                Explanation = points == 0
                    ? "Memory is not under pressure, so there is nothing to gain here."
                    : "The machine is using enough memory that an application can be pushed into paging; " +
                      "closing background work that the user approves frees some of it."
            };
        }

        /// <summary>
        /// CPU background load: what the other processes are consuming, from the same measurement the
        /// process list uses. Counted only for processes the safety layer considers optimisable, so the
        /// score cannot be inflated by work that is never touched.
        /// </summary>
        public static ScoreComponent CpuBackgroundLoad(float backgroundCpuPercent, int candidates)
        {
            var points = backgroundCpuPercent switch
            {
                < 5f => 0,
                < 10f => 6,
                < 20f => 12,
                < 35f => 17,
                _ => 20
            };

            if (candidates == 0 && points > 0)
            {
                // There is load, but nothing the optimiser is permitted to touch. Reporting the points
                // would promise an improvement the feature will not deliver.
                points = 0;
            }

            return new ScoreComponent
            {
                Name = "CPU background load",
                Points = points,
                MaximumPoints = 20,
                Measurement = $"{backgroundCpuPercent:F1}% of total CPU in background processes, {candidates} optimisable",
                Explanation = points == 0
                    ? "Background processes are not using a noticeable amount of processor time."
                    : "Background work is competing with the application for processor time; the profile " +
                      "can raise the application's priority and close approved background applications."
            };
        }

        /// <summary>
        /// GPU background load. Reported only when a real reading exists: with no GPU counter the
        /// component contributes nothing and says so.
        /// </summary>
        public static ScoreComponent GpuBackgroundLoad(float? gpuPercent, bool mayCloseGpuHeavyProcesses)
        {
            if (!gpuPercent.HasValue)
            {
                return new ScoreComponent
                {
                    Name = "GPU background load",
                    Points = 0,
                    MaximumPoints = 10,
                    Measurement = "N/A - no GPU utilisation counter available",
                    Explanation = "The graphics processor's utilisation could not be read on this machine, " +
                                  "so this component contributes nothing rather than a guess."
                };
            }

            var value = gpuPercent.Value;

            var points = value switch
            {
                < 5f => 0,
                < 15f => 4,
                < 30f => 7,
                _ => 10
            };

            if (!mayCloseGpuHeavyProcesses && points > 0)
                points = 0;

            return new ScoreComponent
            {
                Name = "GPU background load",
                Points = points,
                MaximumPoints = 10,
                Measurement = $"{value:F1}% of GPU utilisation in other processes",
                Explanation = points == 0
                    ? "Nothing else is using the graphics processor in a way that competes with the application."
                    : "Other programs are using the graphics processor; closing the ones you approve, or " +
                      "setting a graphics preference for this application, reduces that contention."
            };
        }

        /// <summary>
        /// Power mode: a machine in a power-saving or balanced mode is holding processors back in a way
        /// that a reversible change can address. Nothing is changed while on battery unless the user asks.
        /// </summary>
        public static ScoreComponent PowerMode(string? activeSchemeName, bool onAcPower, bool profileChangesPower)
        {
            if (!profileChangesPower)
            {
                return new ScoreComponent
                {
                    Name = "Power mode",
                    Points = 0,
                    MaximumPoints = 12,
                    Measurement = activeSchemeName is null ? "Power scheme unknown" : activeSchemeName,
                    Explanation = "This profile does not change the power mode, so nothing is scored here."
                };
            }

            if (activeSchemeName is null)
            {
                return new ScoreComponent
                {
                    Name = "Power mode",
                    Points = 0,
                    MaximumPoints = 12,
                    Measurement = "The active power scheme could not be read",
                    Explanation = "Without being able to read the current power mode the optimiser will not " +
                                  "change it, and does not claim a gain."
                };
            }

            var isHighPerformance =
                activeSchemeName.Contains("High performance", StringComparison.OrdinalIgnoreCase) ||
                activeSchemeName.Contains("Ultimate", StringComparison.OrdinalIgnoreCase);

            var points = isHighPerformance ? 0 : onAcPower ? 12 : 6;

            return new ScoreComponent
            {
                Name = "Power mode",
                Points = points,
                MaximumPoints = 12,
                Measurement = $"{activeSchemeName}" + (onAcPower ? " (on AC power)" : " (on battery)"),
                Explanation = isHighPerformance
                    ? "The machine is already in a performance power mode."
                    : "The current power mode allows the processor to slow down under light load. " +
                      "Switching while the application runs - and restoring the original afterwards - is " +
                      (onAcPower ? "the intended use of this component." : "offered only after asking, because the machine is on battery.")
            };
        }

        /// <summary>
        /// Disk pressure: how busy the storage is. A reading, not a suggestion to defragment anything -
        /// the optimiser never does that, and never would on an SSD.
        /// </summary>
        public static ScoreComponent DiskPressure(float? diskPercent)
        {
            if (!diskPercent.HasValue)
            {
                return new ScoreComponent
                {
                    Name = "Disk pressure",
                    Points = 0,
                    MaximumPoints = 10,
                    Measurement = "N/A - no disk activity counter available",
                    Explanation = "Storage activity could not be read, so this component contributes nothing."
                };
            }

            var value = diskPercent.Value;

            var points = value switch
            {
                < 10f => 0,
                < 30f => 4,
                < 60f => 8,
                _ => 10
            };

            return new ScoreComponent
            {
                Name = "Disk pressure",
                Points = points,
                MaximumPoints = 10,
                Measurement = $"{value:F1}% active time",
                Explanation = points == 0
                    ? "Storage is not busy, so there is no contention to remove."
                    : "Storage is busy while the application runs, which shows up as stutter while game " +
                      "assets stream in. The profile reports this; it does not defragment, re-read an SSD " +
                      "or delete anything."
            };
        }

        /// <summary>
        /// Application size: how much memory the application itself is holding. A large working set does
        /// not by itself mean anything is wrong, so this contributes the least of all components.
        /// </summary>
        public static ScoreComponent ApplicationFootprint(long workingSetBytes)
        {
            var megabytes = workingSetBytes / (1024.0 * 1024.0);

            var points = megabytes switch
            {
                < 500 => 0,
                < 1500 => 3,
                < 3000 => 5,
                _ => 8
            };

            return new ScoreComponent
            {
                Name = "Application footprint",
                Points = points,
                MaximumPoints = 8,
                Measurement = $"{megabytes:F0} MB in use by the application",
                Explanation = points == 0
                    ? "The application's own memory use is unremarkable."
                    : "A large working set leaves less room for everything else, which is why keeping " +
                      "unrelated background work out of the way helps more on this machine."
            };
        }

        /// <summary>
        /// The score itself: a number out of 100 plus every component that produced it.
        /// </summary>
        public static OptimizationPotentialResult Calculate(
            float ramPercent,
            long totalMemoryBytes,
            int reclaimableMegabytes,
            float backgroundCpuPercent,
            int optimisableCandidates,
            float? gpuPercent,
            bool mayCloseGpuHeavyProcesses,
            string? activePowerScheme,
            bool onAcPower,
            bool profileChangesPower,
            float? diskPercent,
            long applicationWorkingSetBytes)
        {
            var components = new List<ScoreComponent>
            {
                RamPressure(ramPercent, totalMemoryBytes, reclaimableMegabytes),
                CpuBackgroundLoad(backgroundCpuPercent, optimisableCandidates),
                GpuBackgroundLoad(gpuPercent, mayCloseGpuHeavyProcesses),
                PowerMode(activePowerScheme, onAcPower, profileChangesPower),
                DiskPressure(diskPercent),
                ApplicationFootprint(applicationWorkingSetBytes)
            };

            return new OptimizationPotentialResult(components);
        }
    }

    /// <summary>
    /// The score, the components behind it, and the sentence that says what it means.
    /// </summary>
    public sealed class OptimizationPotentialResult
    {
        public OptimizationPotentialResult(IEnumerable<ScoreComponent> components)
        {
            Components = (components ?? Enumerable.Empty<ScoreComponent>()).ToList();

            var total = Components.Sum(c => c.Points);

            if (total < 0) total = 0;
            if (total > 100) total = 100;

            Score = total;
        }

        public List<ScoreComponent> Components { get; }

        /// <summary>0-100, and never presented as a prediction of a percentage improvement.</summary>
        public int Score { get; }

        public int MaximumPossible => Components.Sum(c => c.MaximumPoints);

        /// <summary>True when there is genuinely nothing to do - said plainly instead of inventing work.</summary>
        public bool NoSignificantOptimizationPossible => Score <= 10;

        /// <summary>
        /// The itemised breakdown, exactly as the interface shows it. Every line names the measurement it
        /// came from and every line is a number the user can add up.
        /// </summary>
        public List<string> Breakdown =>
            Components.Select(c => $"{c.Name} {c.Score}: {c.Measurement}").ToList();

        /// <summary>One sentence with no claim beyond what was measured.</summary>
        public string Summary
        {
            get
            {
                if (NoSignificantOptimizationPossible)
                {
                    return $"Optimization potential {Score}/100. No significant optimization was possible: " +
                           "the measurements above show nothing worth changing.";
                }

                var largest = Components.OrderByDescending(c => c.Points).FirstOrDefault();

                return $"Optimization potential {Score}/100, mainly from {largest?.Name.ToLowerInvariant() ?? "no single component"} " +
                       $"(+{largest?.Points ?? 0}). This score describes how much room there is to make things " +
                       "consistently better; it is not a prediction of a percentage improvement, and it does " +
                       "not promise frames per second.";
            }
        }

        public override string ToString() => $"{Score}/100 - {Summary}";
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Turns raw measurements into the scores and recommendations shown in the UI.
    ///
    /// Every score is derived from a measured value - nothing here is decorative.
    /// The formulas are documented so the user can audit why a score is what it is.
    /// </summary>
    public static class SystemScoring
    {
        #region Performance scores

        /// <summary>
        /// Fill <see cref="SystemInfo.PerformanceScores"/> and <see cref="SystemInfo.SystemHealthScore"/>.
        /// </summary>
        public static void CalculatePerformanceScores(SystemInfo info)
        {
            if (info == null) return;

            info.PerformanceScores.Clear();

            // RAM: 100 when ~0% used, 0 when 100% used. Weighted so that >70% starts to hurt.
            var ramUsage = info.RamUsagePercentage;
            var ramScore = ramUsage <= 50 ? 100 - (ramUsage * 0.4) : 80 - ((ramUsage - 50) * 1.6);
            info.PerformanceScores["RAM"] = Clamp((int)Math.Round(ramScore));

            // CPU: idle systems should score near 100.
            var cpuUsage = info.CpuUsage;
            var cpuScore = cpuUsage <= 20 ? 100 - (cpuUsage * 0.5) : 90 - ((cpuUsage - 20) * 1.125);
            info.PerformanceScores["CPU"] = Clamp((int)Math.Round(cpuScore));

            // GPU: only meaningful when we could actually measure it.
            if (info.Gpus.Count > 0 && info.Gpus.Any(g => g.Usage > 0))
            {
                var gpuUsage = info.TotalGpuUsage;
                info.PerformanceScores["GPU"] = Clamp((int)Math.Round(100 - (gpuUsage * 0.8)));
            }

            // Disk: worst case of (free space pressure, busy time).
            var diskScore = 100;

            var systemDisk = info.SystemDisk;
            if (systemDisk != null)
            {
                // Losing the last 15% of a system drive is what really hurts Windows.
                var usedPercent = systemDisk.UsagePercentage;
                if (usedPercent > 85)
                    diskScore -= (int)Math.Round((usedPercent - 85) * 3);
                else if (usedPercent > 75)
                    diskScore -= (int)Math.Round((usedPercent - 75) * 1);
            }

            var diskActivity = info.TotalDiskActivity;
            if (diskActivity > 60)
                diskScore -= (int)Math.Round((diskActivity - 60) * 0.75);

            info.PerformanceScores["Disk"] = Clamp(diskScore);

            // Startup: penalise non-Windows, user-facing startup entries (5 points each).
            var userStartup = info.StartupItems.Count(s => s.IsEnabled && !s.IsWindowsItem);
            info.PerformanceScores["Startup"] = Clamp(100 - (userStartup * 5));

            // Background apps: penalise idle background processes that hold RAM.
            var backgroundCount = info.BackgroundProcessCount;
            info.PerformanceScores["Background Apps"] = Clamp(100 - (backgroundCount * 2));

            // Overall = average of the scores we were able to measure.
            info.SystemHealthScore = info.PerformanceScores.Count == 0
                ? 0
                : Clamp((int)Math.Round(info.PerformanceScores.Values.Average()));
        }

        private static int Clamp(int value, int min = 0, int max = 100)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }

        #endregion

        #region Optimization info

        /// <summary>
        /// Decide whether optimization is worth proposing and how much RAM is realistically recoverable.
        /// </summary>
        public static void CalculateOptimizationInfo(SystemInfo info, AppConfig? config = null)
        {
            if (info == null) return;

            // Recovery estimate: only count processes we would actually be allowed to close.
            var optimizable = GetOptimizableProcesses(info);

            info.EstimatedRamRecovery = optimizable.Sum(p => p.WorkingSet);
            info.EstimatedCpuImprovement = optimizable.Sum(p => p.CpuUsage);

            // "Needs optimization" is deliberately conservative.
            var ramTarget = config?.MinRamUsageToOptimize ?? AppConstants.DefaultMinRamUsageToOptimize;
            var cpuTarget = config?.MinCpuUsageToOptimize ?? AppConstants.DefaultMinCpuUsageToOptimize;

            info.NeedsOptimization =
                info.RamUsagePercentage >= ramTarget ||
                info.CpuUsage >= cpuTarget ||
                optimizable.Count >= 3;

            GenerateRecommendations(info, config);
        }

        /// <summary>
        /// Processes that are both safe and worthwhile to close:
        /// not critical, not a service, not in use, no visible window.
        /// </summary>
        public static List<ProcessInfo> GetOptimizableProcesses(SystemInfo info)
        {
            if (info == null) return new List<ProcessInfo>();

            return info.Processes
                .Where(p => !p.IsBlacklisted)
                .Where(p => !p.IsUserWhitelisted)
                .Where(p => !p.IsActive)
                .Where(p => !p.HasVisibleWindow)
                .Where(p => !p.IsService)
                .Where(p => !p.IsWindowsProcess)
                .Where(p => !p.IsDriver)
                .Where(p => p.RiskLevel == RiskLevel.Low || p.RiskLevel == RiskLevel.Medium)
                .Where(p => p.Category == ProcessCategory.BackgroundApplication ||
                            p.Category == ProcessCategory.UserApplication ||
                            p.Category == ProcessCategory.Launcher ||
                            p.Category == ProcessCategory.Updater ||
                            p.Category == ProcessCategory.CloudSync ||
                            p.Category == ProcessCategory.Telemetry)
                // Ignore noise: anything below 10 MB is not worth the risk of touching it.
                .Where(p => p.WorkingSet >= 10 * 1024 * 1024)
                .OrderByDescending(p => p.WorkingSet)
                .ToList();
        }

        /// <summary>
        /// Build the human readable recommendation list for the dashboard / AI page.
        /// </summary>
        public static void GenerateRecommendations(SystemInfo info, AppConfig? config = null)
        {
            if (info == null) return;

            info.Recommendations.Clear();

            var ramTarget = config?.TargetRamUsage ?? AppConstants.DefaultTargetRamUsage;
            var optimizable = GetOptimizableProcesses(info);

            // 1. RAM pressure
            if (info.RamUsagePercentage >= ramTarget)
            {
                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = "Memory pressure detected",
                    Description =
                        $"System is using {info.RamUsagePercentage:F1}% of physical memory " +
                        $"({info.UsedPhysicalMemoryGB:F2} GB of {info.TotalPhysicalMemoryGB:F2} GB). " +
                        $"Closing {optimizable.Count} inactive background process(es) could recover about " +
                        $"{optimizable.Sum(p => p.WorkingSet) / (1024.0 * 1024 * 1024):F2} GB.",
                    Category = "RAM",
                    ResourceType = ResourceType.RAM,
                    EstimatedImprovement = $"-{optimizable.Sum(p => p.WorkingSet) / (1024.0 * 1024 * 1024):F2} GB",
                    RiskLevel = RiskLevel.Low,
                    Priority = 10,
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = "background_processes"
                });
            }
            else
            {
                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = "Memory usage is healthy",
                    Description =
                        $"Memory usage ({info.RamUsagePercentage:F1}%) is already at or below your target of {ramTarget}%. " +
                        "Windows may keep RAM in the standby cache on purpose - that memory is still available to applications.",
                    Category = "RAM",
                    ResourceType = ResourceType.RAM,
                    EstimatedImprovement = "None required",
                    RiskLevel = RiskLevel.Low,
                    Priority = 1,
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = "none"
                });
            }

            // 2. CPU
            if (info.CpuUsage >= 20)
            {
                var topCpu = info.Processes
                    .Where(p => !CriticalProcesses.IsCritical(p.Name))
                    .OrderByDescending(p => p.CpuUsage)
                    .Take(3)
                    .Select(p => $"{p.DisplayName} ({p.CpuUsage:F0}%)")
                    .ToList();

                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = "CPU load is elevated",
                    Description = topCpu.Count > 0
                        ? $"Current CPU usage is {info.CpuUsage:F1}%. Largest contributors: {string.Join(", ", topCpu)}."
                        : $"Current CPU usage is {info.CpuUsage:F1}%.",
                    Category = "CPU",
                    ResourceType = ResourceType.CPU,
                    EstimatedImprovement = $"-{Math.Min(info.CpuUsage * 0.5f, 25):F0}% (best case)",
                    RiskLevel = RiskLevel.Medium,
                    Priority = 8,
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = "cpu_intensive_processes"
                });
            }

            // 3. Startup items
            var heavyStartup = info.StartupItems
                .Where(s => s.IsEnabled && !s.IsWindowsItem && !s.IsBlacklisted)
                .OrderByDescending(s => s.EstimatedRamUsage)
                .Take(5)
                .ToList();

            if (heavyStartup.Count > 0)
            {
                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = $"{heavyStartup.Count} optional startup program(s)",
                    Description =
                        "These start with Windows and hold memory even when unused: " +
                        string.Join(", ", heavyStartup.Select(s => s.Name)) + ". " +
                        "Disabling them speeds up sign-in and reduces idle memory usage.",
                    Category = "Startup",
                    ResourceType = ResourceType.RAM,
                    EstimatedImprovement = heavyStartup.Sum(s => s.EstimatedRamUsage) > 0
                        ? $"up to {heavyStartup.Sum(s => s.EstimatedRamUsage) / (1024.0 * 1024 * 1024):F2} GB later"
                        : "Faster sign-in",
                    RiskLevel = RiskLevel.Low,
                    Priority = 7,
                    ActionType = OptimizationActionType.DisableStartup,
                    Target = "startup_items"
                });
            }

            // 4. Background applications
            if (optimizable.Count > 0)
            {
                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = $"{optimizable.Count} inactive background application(s)",
                    Description =
                        string.Join(", ", optimizable.Take(5).Select(p => $"{p.DisplayName} ({p.FormattedWorkingSet})")) +
                        (optimizable.Count > 5 ? ", ..." : string.Empty),
                    Category = "Background Process",
                    ResourceType = ResourceType.RAM,
                    EstimatedImprovement = $"-{optimizable.Sum(p => p.WorkingSet) / (1024.0 * 1024 * 1024):F2} GB",
                    RiskLevel = RiskLevel.Low,
                    Priority = 9,
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = "background_applications"
                });
            }

            // 5. Storage
            if (info.SystemDisk != null && info.SystemDisk.UsagePercentage >= 85)
            {
                info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
                {
                    Title = "System drive is getting full",
                    Description =
                        $"The system drive is {info.SystemDisk.UsagePercentage:F1}% full " +
                        $"({info.SystemDisk.FormattedFreeSpace} free). " +
                        "Low free space slows down Windows and can prevent updates from installing.",
                    Category = "Disk",
                    ResourceType = ResourceType.Disk,
                    EstimatedImprovement = "Improved responsiveness",
                    RiskLevel = RiskLevel.Low,
                    Priority = 6,
                    ActionType = OptimizationActionType.ClearCache,
                    Target = "disk_space"
                });
            }

            // 6. Security is a hard "do not touch" - state it explicitly in the UI.
            info.Recommendations.Add(new SystemInfo.OptimizationRecommendation
            {
                Title = "Windows security is left untouched",
                Description =
                    "Windows Defender, the firewall and UAC are never disabled by this application, " +
                    "even when doing so would save memory. Security comes before a lower RAM number.",
                Category = "Security",
                ResourceType = ResourceType.RAM,
                EstimatedImprovement = "N/A - by design",
                RiskLevel = RiskLevel.Critical,
                Priority = 0,
                ActionType = OptimizationActionType.CloseProcess,
                Target = "security"
            });

            info.Recommendations = info.Recommendations
                .OrderByDescending(r => r.Priority)
                .ToList();
        }

        #endregion

        #region Honest summary helpers

        /// <summary>
        /// Build a one-line summary of how much of the RAM target is actually achievable safely.
        /// Used for the "Safe optimization limit reached" message the user explicitly asked for.
        /// </summary>
        public static string DescribeAchievableTarget(SystemInfo info, int targetPercent)
        {
            if (info == null || info.TotalPhysicalMemory <= 0)
                return string.Empty;

            var optimizable = GetOptimizableProcesses(info);
            var recoverable = optimizable.Sum(p => p.WorkingSet);

            var projectedUsedBytes = Math.Max(0, (long)info.UsedPhysicalMemory - recoverable);
            var projectedPercent = projectedUsedBytes / (double)info.TotalPhysicalMemory * 100;

            if (projectedPercent <= targetPercent)
            {
                return $"Closing the {optimizable.Count} safe candidates should bring memory usage to " +
                       $"about {projectedPercent:F1}%, meeting your {targetPercent}% target.";
            }

            return $"Even after closing every safely closable application ({optimizable.Count} candidates, " +
                   $"~{recoverable / (1024.0 * 1024 * 1024):F2} GB), memory usage would be about {projectedPercent:F1}%. " +
                   $"Reaching {targetPercent}% is not possible without disabling Windows services, security features " +
                   "or drivers, which this application will not do. Safe optimization limit reached.";
        }

        /// <summary>
        /// Percentage of the user's RAM target that the safe optimizations can deliver.
        /// </summary>
        public static int CalculateTargetProgress(SystemInfo info, int targetPercent)
        {
            if (info == null || info.TotalPhysicalMemory <= 0) return 0;

            var current = info.RamUsagePercentage;
            if (current <= targetPercent) return 100;

            var optimizable = GetOptimizableProcesses(info);
            var recoverable = optimizable.Sum(p => p.WorkingSet);
            var projected = Math.Max(0, (long)info.UsedPhysicalMemory - recoverable) /
                            (double)info.TotalPhysicalMemory * 100;

            var needed = current - targetPercent;
            var achieved = current - projected;

            if (needed <= 0) return 100;

            return Clamp((int)Math.Round(achieved / needed * 100));
        }

        #endregion
    }
}

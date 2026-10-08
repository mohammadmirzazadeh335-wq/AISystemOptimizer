using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the rules engine: process classification, risk assignment and the
    /// "never touch" guarantees. These are the tests that protect system stability.
    /// </summary>
    public class RulesEngineTests
    {
        #region Critical process protection

        [Theory]
        [InlineData("System")]
        [InlineData("Registry")]
        [InlineData("smss.exe")]
        [InlineData("csrss.exe")]
        [InlineData("wininit.exe")]
        [InlineData("services.exe")]
        [InlineData("lsass.exe")]
        [InlineData("winlogon.exe")]
        [InlineData("dwm.exe")]
        [InlineData("explorer.exe")]
        [InlineData("svchost.exe")]
        public void CoreWindowsProcesses_AreClassifiedAsCritical(string processName)
        {
            Assert.True(CriticalProcesses.IsCritical(processName),
                $"{processName} must be treated as critical - closing it can destabilise Windows.");

            var category = CriticalProcesses.GetProcessCategory(processName, @"C:\Windows\System32\", false);
            Assert.Equal(ProcessCategory.Critical, category);

            var risk = CriticalProcesses.GetProcessRiskLevel(processName, category);
            Assert.Equal(RiskLevel.Critical, risk);
        }

        [Theory]
        [InlineData("MsMpEng.exe")]   // Windows Defender engine
        [InlineData("NisSrv.exe")]    // Defender network inspection
        [InlineData("SecurityHealthService.exe")]
        [InlineData("avp.exe")]       // third-party AV sample
        [InlineData("ekrn.exe")]      // ESET
        public void SecurityProcesses_AreNeverClassifiedAsClosable(string processName)
        {
            Assert.True(CriticalProcesses.IsSecurityProcess(processName),
                $"{processName} belongs to the security stack and must be protected.");

            var category = CriticalProcesses.GetProcessCategory(processName, @"C:\Program Files\AV\", false);

            Assert.True(category == ProcessCategory.Security || category == ProcessCategory.Critical,
                $"{processName} should be Security or Critical, but was {category}.");

            var risk = CriticalProcesses.GetProcessRiskLevel(processName, category);
            Assert.True(risk == RiskLevel.Critical || risk == RiskLevel.High,
                $"{processName} risk should never be Low or Medium, but was {risk}.");
        }

        [Theory]
        [InlineData("RadeonSoftware.exe")]
        [InlineData("atiesrxx.exe")]
        [InlineData("NvContainer.exe")]
        [InlineData("igfxEM.exe")]
        [InlineData("RtkAudUService64.exe")]
        [InlineData("SynTPEnh.exe")]
        public void DriverHelpers_AreNeverClassifiedAsClosable(string processName)
        {
            Assert.True(CriticalProcesses.IsDriverProcess(processName),
                $"{processName} is a hardware driver helper and must be protected.");

            var risk = CriticalProcesses.GetProcessRiskLevel(processName, ProcessCategory.Driver);
            Assert.True(risk == RiskLevel.High || risk == RiskLevel.Critical);
        }

        #endregion

        #region User application classification

        [Theory]
        [InlineData("chrome.exe", @"C:\Program Files\Google\Chrome\Application\chrome.exe")]
        [InlineData("Discord.exe", @"C:\Users\me\AppData\Local\Discord\app\Discord.exe")]
        [InlineData("Spotify.exe", @"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe")]
        [InlineData("Telegram.exe", @"C:\Users\me\AppData\Roaming\Telegram Desktop\Telegram.exe")]
        public void OrdinaryUserApplications_AreLowRisk(string processName, string path)
        {
            var category = CriticalProcesses.GetProcessCategory(processName, path, false);
            var risk = CriticalProcesses.GetProcessRiskLevel(processName, category);

            Assert.False(CriticalProcesses.IsCritical(processName));
            Assert.Equal(RiskLevel.Low, risk);
        }

        [Theory]
        [InlineData("OneDrive.exe", ProcessCategory.CloudSync)]
        [InlineData("Dropbox.exe", ProcessCategory.CloudSync)]
        [InlineData("Steam.exe", ProcessCategory.Launcher)]
        [InlineData("EpicGamesLauncher.exe", ProcessCategory.Launcher)]
        [InlineData("GoogleUpdate.exe", ProcessCategory.Updater)]
        [InlineData("DiagTrack", ProcessCategory.Telemetry)]
        public void SpecialCategories_AreDetected(string processName, ProcessCategory expected)
        {
            var category = CriticalProcesses.GetProcessCategory(processName, string.Empty, false);
            Assert.Equal(expected, category);
        }

        #endregion

        #region Never-touch guarantees

        [Fact]
        public void CriticalProcesses_AreNeverOfferedForOptimisation()
        {
            // Every entry in the critical bucket must be excluded by the candidate filter,
            // which is what the planner and the safety validator both rely on.
            foreach (var name in CriticalProcesses.SystemCritical)
            {
                Assert.True(CriticalProcesses.IsCritical(name));
            }

            Assert.Contains("lsass.exe", CriticalProcesses.SystemCritical);
            Assert.Contains("csrss.exe", CriticalProcesses.SystemCritical);
            Assert.Contains("smss.exe", CriticalProcesses.SystemCritical);
        }

        [Fact]
        public void ProtectedLists_AreNotEmpty()
        {
            Assert.NotEmpty(CriticalProcesses.SystemCritical);
            Assert.NotEmpty(CriticalProcesses.SystemProcesses);
            Assert.NotEmpty(CriticalProcesses.SecurityProcesses);
            Assert.NotEmpty(CriticalProcesses.DriverProcesses);
        }

        [Fact]
        public void DefenderAndFirewall_AreInTheDefaultBlacklists()
        {
            var config = AppConfig.CreateDefault();

            Assert.Contains("MsMpEng", config.BlacklistedProcesses);
            Assert.Contains("WinDefend", config.BlacklistedServices);
            Assert.Contains("MpsSvc", config.BlacklistedServices);   // Windows Firewall
            Assert.Contains("wscsvc", config.BlacklistedServices);   // Security Center
        }

        #endregion
    }

    /// <summary>
    /// Tests for the scoring rules: the numbers shown to the user must follow from measurements.
    /// </summary>
    public class ScoringTests
    {
        private static SystemInfo CreateSystemInfo(
            double ramPercent = 40,
            float cpuPercent = 5,
            int backgroundProcesses = 0,
            double diskUsagePercent = 50)
        {
            const long totalRam = 8L * 1024 * 1024 * 1024;

            var info = new SystemInfo
            {
                TotalPhysicalMemory = totalRam,
                AvailablePhysicalMemory = (long)(totalRam * (1 - ramPercent / 100.0)),
                CpuUsage = cpuPercent,
                BackgroundProcessCount = backgroundProcesses
            };

            info.Disks.Add(new SystemInfo.DiskInfo
            {
                DriveLetter = "C:\\",
                TotalSize = 500L * 1024 * 1024 * 1024,
                FreeSpace = (long)(500L * 1024 * 1024 * 1024 * (1 - diskUsagePercent / 100.0)),
                IsSystemDisk = true,
                Type = "NVMe SSD"
            });

            return info;
        }

        [Fact]
        public void RamUsagePercentage_IsDerivedFromMeasuredBytes()
        {
            var info = CreateSystemInfo(ramPercent: 37.5);

            Assert.Equal(37.5, info.RamUsagePercentage, 1);
            Assert.Equal(3.0, info.UsedPhysicalMemoryGB, 1);
        }

        [Fact]
        public void LowerMemoryUsage_ProducesHigherRamScore()
        {
            var lowUsage = CreateSystemInfo(ramPercent: 25);
            var highUsage = CreateSystemInfo(ramPercent: 90);

            SystemScoring.CalculatePerformanceScores(lowUsage);
            SystemScoring.CalculatePerformanceScores(highUsage);

            Assert.True(lowUsage.PerformanceScores["RAM"] > highUsage.PerformanceScores["RAM"],
                "Less memory in use must score higher.");
        }

        [Fact]
        public void Scores_AreAlwaysWithinBounds()
        {
            foreach (var ram in new[] { 0.0, 10, 35, 50, 75, 90, 99.9 })
            {
                var info = CreateSystemInfo(ramPercent: ram, cpuPercent: 100, backgroundProcesses: 200);
                SystemScoring.CalculatePerformanceScores(info);

                foreach (var score in info.PerformanceScores.Values)
                {
                    Assert.InRange(score, 0, 100);
                }

                Assert.InRange(info.SystemHealthScore, 0, 100);
            }
        }

        [Fact]
        public void TargetProgress_IsHundredPercent_WhenAlreadyBelowTarget()
        {
            var info = CreateSystemInfo(ramPercent: 20);
            var progress = SystemScoring.CalculateTargetProgress(info, targetPercent: 35);

            Assert.Equal(100, progress);
        }

        [Fact]
        public void DescribeAchievableTarget_SaysSoHonestly_WhenTargetIsUnreachable()
        {
            // A system at 60% with 4 GB in use and nothing safely closable cannot reach 35%.
            const long totalRam = 8L * 1024 * 1024 * 1024;

            var info = new SystemInfo
            {
                TotalPhysicalMemory = totalRam,
                AvailablePhysicalMemory = (long)(totalRam * 0.4)
            };

            // A protected, large process: must NOT be counted as recoverable.
            info.Processes.Add(new ProcessInfo
            {
                Id = 4,
                Name = "System",
                WorkingSet = 3L * 1024 * 1024 * 1024,
                IsWindowsProcess = true,
                Category = ProcessCategory.Critical,
                RiskLevel = RiskLevel.Critical
            });

            var message = SystemScoring.DescribeAchievableTarget(info, targetPercent: 35);

            Assert.Contains("not possible", message, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("Safe optimization limit reached", message, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void OptimizableProcesses_ExcludeCriticalAndActiveProcesses()
        {
            var info = new SystemInfo();

            info.Processes.Add(new ProcessInfo
            {
                Id = 1,
                Name = "lsass.exe",
                WorkingSet = 50L * 1024 * 1024,
                IsWindowsProcess = true,
                Category = ProcessCategory.Critical,
                RiskLevel = RiskLevel.Critical
            });

            info.Processes.Add(new ProcessInfo
            {
                Id = 2,
                Name = "chrome.exe",
                WorkingSet = 900L * 1024 * 1024,
                Category = ProcessCategory.UserApplication,
                RiskLevel = RiskLevel.Low,
                HasVisibleWindow = true,     // the user is looking at it
                IsActive = true
            });

            info.Processes.Add(new ProcessInfo
            {
                Id = 3,
                Name = "spotify.exe",
                WorkingSet = 200L * 1024 * 1024,
                Category = ProcessCategory.BackgroundApplication,
                RiskLevel = RiskLevel.Low
            });

            var candidates = SystemScoring.GetOptimizableProcesses(info);

            Assert.Single(candidates);
            Assert.Equal("spotify.exe", candidates[0].Name);
        }
    }
}

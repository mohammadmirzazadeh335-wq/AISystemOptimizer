using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using AISystemOptimizer.Core.Models;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the logic that decides what a profile would do and what the optimiser is allowed to say
    /// about it: the mode presets, the background-process categories, the potential score and the memory
    /// advice.
    ///
    /// These are the rules the specification is most specific about, so they are tested as rules: no mode
    /// may leave the safety model, no familiar name may earn a process the right to be closed, no score
    /// may be unexplainable, and no memory target may be promised.
    /// </summary>
    public class GameAppPlanningTests
    {
        private static ProcessInfo Process(
            string name,
            int id = 100,
            long workingSetMb = 400,
            ProcessCategory category = ProcessCategory.BackgroundApplication,
            RiskLevel risk = RiskLevel.Low,
            bool active = false,
            bool visible = false,
            bool service = false,
            bool security = false,
            DateTime? created = null)
        {
            return new ProcessInfo
            {
                Id = id,
                Name = name,
                Path = $@"C:\Program Files\{name}\{name}.exe",
                Category = category,
                RiskLevel = risk,
                WorkingSet = workingSetMb * 1024 * 1024,
                IsActive = active,
                HasVisibleWindow = visible,
                IsService = service,
                IsSecurity = security,
                CreationTimeUtc = created ?? DateTime.UtcNow
            };
        }

        #region Mode presets

        [Theory]
        [InlineData(GameAppProfileMode.Safe)]
        [InlineData(GameAppProfileMode.Balanced)]
        [InlineData(GameAppProfileMode.Performance)]
        [InlineData(GameAppProfileMode.Custom)]
        public void NoModeEverLeavesTheSafetyModel(GameAppProfileMode mode)
        {
            var profile = new GameAppProfile();

            ProfileModePresets.Apply(profile, mode);

            // The guarantees that no mode may touch.
            Assert.True(profile.Cpu.AffinityIsNeverModified);
            Assert.True(profile.Disk.WarnBeforeDeleting);
            Assert.True(profile.Disk.SaveFilesAreNeverInScope);
            Assert.True(profile.Network.NetworkSettingsAreNeverChanged);

            // No mode closes more than the per-session limit allows.
            Assert.InRange(profile.Ram.MaxBackgroundProcessesPerSession, 0, 20);

            // No mode selects an "unsafe" mode, because none exists.
            Assert.NotEqual("Unsafe", profile.ProfileMode.ToString());
        }

        [Fact]
        public void SafeModeChangesNothingAboutTheSystem()
        {
            var profile = new GameAppProfile();

            ProfileModePresets.Apply(profile, GameAppProfileMode.Safe);

            Assert.Equal(ProcessPriorityPreference.LeaveUnchanged, profile.Cpu.Priority);
            Assert.False(profile.Ram.CloseBackgroundProcesses);
            Assert.Equal(0, profile.Ram.MaxBackgroundProcessesPerSession);
            Assert.Equal(PowerPreference.LeaveUnchanged, profile.Power.ModeWhileRunning);
            Assert.Equal(GraphicsPreference.LetWindowsDecide, profile.Gpu.GraphicsPreference);
            Assert.Equal(DiskCleanupScope.None, profile.Disk.CleanupScope);
            Assert.False(profile.Network.ReportActivity);
        }

        [Fact]
        public void BalancedIsTheDefaultAndStaysConservative()
        {
            var profile = new GameAppProfile();

            Assert.Equal(GameAppProfileMode.Balanced, profile.ProfileMode);
            Assert.False(profile.Behavior.AutoOptimize);

            ProfileModePresets.Apply(profile, GameAppProfileMode.Balanced);

            Assert.Equal(ProcessPriorityPreference.AboveNormal, profile.Cpu.Priority);
            Assert.Equal(2, profile.Ram.MaxBackgroundProcessesPerSession);
            Assert.Equal(PowerPreference.HighPerformance, profile.Power.ModeWhileRunning);
            Assert.True(profile.Power.RestoreAfterExit);
        }

        [Fact]
        public void PerformanceIsTheMostThatIsAllowedAndNoMore()
        {
            var profile = new GameAppProfile();

            ProfileModePresets.Apply(profile, GameAppProfileMode.Performance);

            // High, never Realtime: Realtime priority can starve input and audio.
            Assert.Equal(ProcessPriorityPreference.High, profile.Cpu.Priority);
            Assert.DoesNotContain(
                Enum.GetNames<ProcessPriorityPreference>(),
                name => name.Contains("Realtime", StringComparison.OrdinalIgnoreCase));

            Assert.Equal(5, profile.Ram.MaxBackgroundProcessesPerSession);

            // Restoring is not optional in any mode.
            Assert.True(profile.Power.RestoreAfterExit);

            // Disk work is still limited to identifying what could be cleaned.
            Assert.Equal(DiskCleanupScope.IdentifyOnly, profile.Disk.CleanupScope);
        }

        [Fact]
        public void CustomModeChangesNothingAtAll()
        {
            var profile = new GameAppProfile();

            profile.Cpu.Priority = ProcessPriorityPreference.High;
            profile.Ram.MaxBackgroundProcessesPerSession = 3;
            profile.Gpu.GraphicsPreference = GraphicsPreference.PowerSaving;

            ProfileModePresets.Apply(profile, GameAppProfileMode.Custom);

            Assert.Equal(ProcessPriorityPreference.High, profile.Cpu.Priority);
            Assert.Equal(3, profile.Ram.MaxBackgroundProcessesPerSession);
            Assert.Equal(GraphicsPreference.PowerSaving, profile.Gpu.GraphicsPreference);
            Assert.Equal(GameAppProfileMode.Custom, profile.ProfileMode);
        }

        [Fact]
        public void EveryModeExplainsItself()
        {
            foreach (var mode in Enum.GetValues<GameAppProfileMode>())
            {
                var explanation = ProfileModePresets.Explain(mode);

                Assert.NotEmpty(explanation);
                Assert.All(explanation, e =>
                {
                    Assert.False(string.IsNullOrWhiteSpace(e.Setting));
                    Assert.False(string.IsNullOrWhiteSpace(e.Value));
                    Assert.False(string.IsNullOrWhiteSpace(e.Why));
                });

                Assert.False(string.IsNullOrWhiteSpace(ProfileModePresets.Describe(mode)));
            }
        }

        #endregion

        #region Background process categories

        [Theory]
        [InlineData("explorer.exe")]
        [InlineData("lsass.exe")]
        [InlineData("dwm.exe")]
        [InlineData("audiodg.exe")]
        [InlineData("MsMpEng.exe")]
        [InlineData("SecurityHealthService.exe")]
        [InlineData("OneDrive.exe")]
        public void ProtectedProcesses_AreNeverCandidatesWhateverTheirSize(string name)
        {
            // Large, low-risk and windowless: every property that would otherwise make it a candidate.
            var process = Process(name, workingSetMb: 900, category: ProcessCategory.BackgroundApplication);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.False(assessment.MayBeClosed);
            Assert.False(string.IsNullOrWhiteSpace(assessment.Reason));
        }

        [Fact]
        public void AProcessWithAnOpenWindow_IsNeverClosed()
        {
            var process = Process("SomeEditor.exe", category: ProcessCategory.UserApplication, visible: true);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.Contains("unsaved work", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AProcessInUse_IsNeverClosed()
        {
            var process = Process("SomeApp.exe", active: true);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.Contains("in use", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void SecuritySoftware_IsNeverClosedEvenWhenItIsNotOnTheNameList()
        {
            var process = Process("AcmeShield.exe", security: true, category: ProcessCategory.Security);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.Contains("Security", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void ServicesAreSentToTheServicesPageRatherThanClosedHere()
        {
            var process = Process("SomeService.exe", service: true, category: ProcessCategory.System);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.Contains("Services page", assessment.Reason, StringComparison.Ordinal);
        }

        [Fact]
        public void TheNeverOptimizeList_IsHonouredForAnOtherwisePerfectCandidate()
        {
            var process = Process("Suspicious.exe", workingSetMb: 800);

            var entries = new List<NeverOptimizeEntry>
            {
                new() { Kind = NeverOptimizeKind.ProcessName, Value = "Suspicious.exe", Reason = "I use it" }
            };

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile(), entries);

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
            Assert.Contains("never-optimise list", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AProfileRuleSayingNeverOptimize_BeatsAnythingElse()
        {
            var profile = new GameAppProfile();

            profile.BackgroundRules.Add(new BackgroundProcessRule
            {
                Target = "Helper",
                Decision = BackgroundProcessDecision.NeverOptimize
            });

            var assessment = BackgroundProcessCategorizer.Assess(Process("Helper.exe", workingSetMb: 900), profile);

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
        }

        [Fact]
        public void AProfileRuleSayingAllow_MakesAProcessUsuallySafeButNotAutomaticallyClosed()
        {
            var profile = new GameAppProfile();

            profile.BackgroundRules.Add(new BackgroundProcessRule
            {
                Target = "Helper.exe",
                Decision = BackgroundProcessDecision.AllowOptimization
            });

            var assessment = BackgroundProcessCategorizer.Assess(Process("Helper.exe", workingSetMb: 900), profile);

            Assert.Equal(BackgroundProcessCategory.UsuallySafe, assessment.Category);
            Assert.True(assessment.MayBeClosed);
        }

        [Fact]
        public void ATinyProcess_IsNotWorthClosingAndIsReportedAsSuch()
        {
            var process = Process("Tiny.exe", workingSetMb: 4);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.NotEqual(BackgroundProcessCategory.SafeToClose, assessment.Category);
            Assert.Contains("almost nothing", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AProfileThatForbidsClosing_IsRespected()
        {
            var profile = new GameAppProfile();
            profile.Ram.CloseBackgroundProcesses = false;

            var assessment = BackgroundProcessCategorizer.Assess(Process("Big.exe", workingSetMb: 1200), profile);

            Assert.False(assessment.MayBeClosed);
        }

        [Fact]
        public void AnUnrecognisedProgramIsConfirmedWithTheUserRatherThanGuessed()
        {
            // Medium risk, no window, not active: a real candidate, but not one the optimiser claims to
            // understand.
            var process = Process("MysteryTool.exe", workingSetMb: 700, risk: RiskLevel.Medium,
                category: ProcessCategory.Unknown);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.UserConfirmationRequired, assessment.Category);
            Assert.Contains("not certain", assessment.Reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AFamiliarNameIsNotEnoughOnItsOwn()
        {
            // This helper's name is on the known list, but it has a window, which means it may have work
            // in progress. It must not be waved through on the strength of its name.
            var process = Process("Widgets.exe", workingSetMb: 900, visible: true);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.Equal(BackgroundProcessCategory.NeverClose, assessment.Category);
        }

        [Fact]
        public void CandidatesAreLimitedByTheProfileAndOrderedByWhatTheyWouldFree()
        {
            var profile = new GameAppProfile();
            profile.Ram.MaxBackgroundProcessesPerSession = 2;

            var assessments = new List<BackgroundProcessAssessment>
            {
                new() { ProcessId = 1, ProcessName = "small", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 100 },
                new() { ProcessId = 2, ProcessName = "big", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 900 },
                new() { ProcessId = 3, ProcessName = "medium", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 500 },
                new() { ProcessId = 4, ProcessName = "protected", Category = BackgroundProcessCategory.NeverClose, WorkingSet = 4000 }
            };

            var selected = BackgroundProcessCategorizer.SelectCandidates(assessments, profile);

            Assert.Equal(2, selected.Count);
            Assert.Equal("big", selected[0].ProcessName);
            Assert.Equal("medium", selected[1].ProcessName);

            // Nothing outside the permission set can ever be selected, however large.
            Assert.DoesNotContain(selected, a => a.ProcessName == "protected");
        }

        [Fact]
        public void AProfileThatMayCloseNothing_SelectsNothing()
        {
            var profile = new GameAppProfile();
            profile.Ram.MaxBackgroundProcessesPerSession = 0;

            var assessments = new List<BackgroundProcessAssessment>
            {
                new() { ProcessId = 1, ProcessName = "x", Category = BackgroundProcessCategory.SafeToClose, WorkingSet = 900 }
            };

            Assert.Empty(BackgroundProcessCategorizer.SelectCandidates(assessments, profile));
        }

        [Fact]
        public void AProcessThatCannotBeTerminated_IsNotACandidate()
        {
            // The scanner marks a high-risk process as not terminable; the categoriser must not override it.
            var process = Process("Blocked.exe", risk: RiskLevel.High, workingSetMb: 800);

            var assessment = BackgroundProcessCategorizer.Assess(process, new GameAppProfile());

            Assert.False(assessment.MayBeClosed);
        }

        [Fact]
        public void TheSummaryCountsEveryCategoryWithoutInventingSavings()
        {
            var assessments = new List<BackgroundProcessAssessment>
            {
                new() { ProcessName = "a", Category = BackgroundProcessCategory.NeverClose, WorkingSet = 500L * 1024 * 1024 },
                new() { ProcessName = "b", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 600L * 1024 * 1024 }
            };

            var summary = BackgroundProcessCategorizer.Summarise(assessments);

            Assert.Contains("2 process(es) examined", summary, StringComparison.Ordinal);
            Assert.Contains("600 MB", summary, StringComparison.Ordinal);
            Assert.Contains("never closed", summary, StringComparison.Ordinal);
        }

        #endregion

        #region Optimization potential score

        [Fact]
        public void TheScoreIsTheSumOfItsParts()
        {
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 78f,
                totalMemoryBytes: 16L * 1024 * 1024 * 1024,
                reclaimableMegabytes: 1200,
                backgroundCpuPercent: 14f,
                optimisableCandidates: 3,
                gpuPercent: 22f,
                mayCloseGpuHeavyProcesses: true,
                activePowerScheme: "Balanced",
                onAcPower: true,
                profileChangesPower: true,
                diskPercent: 35f,
                applicationWorkingSetBytes: 2000L * 1024 * 1024);

            Assert.Equal(result.Components.Sum(c => c.Points), result.Score);

            // Every component explains itself with a measurement the user can check.
            Assert.All(result.Components, c =>
            {
                Assert.False(string.IsNullOrWhiteSpace(c.Name));
                Assert.False(string.IsNullOrWhiteSpace(c.Measurement));
                Assert.False(string.IsNullOrWhiteSpace(c.Explanation));
                Assert.True(c.MaximumPoints > 0);
                Assert.InRange(c.Points, 0, c.MaximumPoints);
            });
        }

        [Fact]
        public void AMachineAtRestScoresLowAndSaysSo()
        {
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 40f,
                totalMemoryBytes: 32L * 1024 * 1024 * 1024,
                reclaimableMegabytes: 50,
                backgroundCpuPercent: 2f,
                optimisableCandidates: 9,
                gpuPercent: 1f,
                mayCloseGpuHeavyProcesses: true,
                activePowerScheme: "High performance",
                onAcPower: true,
                profileChangesPower: true,
                diskPercent: 2f,
                applicationWorkingSetBytes: 300L * 1024 * 1024);

            Assert.True(result.NoSignificantOptimizationPossible);
            Assert.Contains("No significant optimization was possible", result.Summary, StringComparison.Ordinal);
            Assert.Equal(0, result.Score);
        }

        [Fact]
        public void MissingReadingsContributeNothingAndAreLabelledNA()
        {
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 80f,
                totalMemoryBytes: 16L * 1024 * 1024 * 1024,
                reclaimableMegabytes: 2000,
                backgroundCpuPercent: 30f,
                optimisableCandidates: 4,
                gpuPercent: null,
                mayCloseGpuHeavyProcesses: true,
                activePowerScheme: null,
                onAcPower: true,
                profileChangesPower: true,
                diskPercent: null,
                applicationWorkingSetBytes: 3000L * 1024 * 1024);

            var gpu = result.Components.Single(c => c.Name == "GPU background load");
            var disk = result.Components.Single(c => c.Name == "Disk pressure");
            var power = result.Components.Single(c => c.Name == "Power mode");

            Assert.Equal(0, gpu.Points);
            Assert.Contains("N/A", gpu.Measurement, StringComparison.Ordinal);
            Assert.Equal(0, disk.Points);
            Assert.Contains("N/A", disk.Measurement, StringComparison.Ordinal);

            // The power mode could not be read, so it is not changed and not scored.
            Assert.Equal(0, power.Points);
            Assert.Contains("could not be read", power.Measurement, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void TheScoreNeverClaimsWorkItWillNotDo()
        {
            // There is load, but nothing the optimiser may touch.
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 50f,
                totalMemoryBytes: 16L * 1024 * 1024 * 1024,
                reclaimableMegabytes: 0,
                backgroundCpuPercent: 25f,
                optimisableCandidates: 0,
                gpuPercent: null,
                mayCloseGpuHeavyProcesses: false,
                activePowerScheme: "Balanced",
                onAcPower: true,
                profileChangesPower: false,
                diskPercent: null,
                applicationWorkingSetBytes: 100L * 1024 * 1024);

            var cpu = result.Components.Single(c => c.Name == "CPU background load");

            Assert.Equal(0, cpu.Points);
            Assert.Equal(0, result.Score);
        }

        [Fact]
        public void TheBreakdownIsItemisedExactlyAsTheSpecificationShows()
        {
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 80f, totalMemoryBytes: 16L * 1024 * 1024 * 1024, reclaimableMegabytes: 1500,
                backgroundCpuPercent: 18f, optimisableCandidates: 2,
                gpuPercent: 10f, mayCloseGpuHeavyProcesses: true,
                activePowerScheme: "Balanced", onAcPower: true, profileChangesPower: true,
                diskPercent: 20f, applicationWorkingSetBytes: 1200L * 1024 * 1024);

            var breakdown = result.Breakdown;

            Assert.Equal(6, breakdown.Count);
            Assert.Contains(breakdown, line => line.StartsWith("RAM pressure +", StringComparison.Ordinal));
            Assert.Contains(breakdown, line => line.StartsWith("CPU background load +", StringComparison.Ordinal));
            Assert.Contains(breakdown, line => line.StartsWith("GPU background load +", StringComparison.Ordinal));
            Assert.Contains(breakdown, line => line.StartsWith("Power mode +", StringComparison.Ordinal));
            Assert.Contains(breakdown, line => line.StartsWith("Disk pressure +", StringComparison.Ordinal));

            // The summary explicitly refuses to be read as an FPS prediction.
            Assert.Contains("not a prediction", result.Summary, StringComparison.Ordinal);
            Assert.DoesNotContain("FPS will", result.Summary, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AScoreIsBoundedAndNeverPromisesPerfection()
        {
            var result = OptimizationPotentialScore.Calculate(
                ramPercent: 99f, totalMemoryBytes: 4L * 1024 * 1024 * 1024, reclaimableMegabytes: 3000,
                backgroundCpuPercent: 90f, optimisableCandidates: 40,
                gpuPercent: 95f, mayCloseGpuHeavyProcesses: true,
                activePowerScheme: "Power saver", onAcPower: true, profileChangesPower: true,
                diskPercent: 99f, applicationWorkingSetBytes: 8L * 1024 * 1024 * 1024);

            Assert.Equal(OptimizationPotentialScore.MaximumScore, result.Score);
            Assert.True(result.Score < 100);
        }

        #endregion

        #region RAM advice

        private static GameAppMemoryBreakdown Memory(long totalGb, long usedGb, long cachedGb, long? standbyGb = null)
        {
            const long gb = 1024L * 1024 * 1024;

            return new GameAppMemoryBreakdown
            {
                TotalBytes = totalGb * gb,
                UsedBytes = usedGb * gb,
                AvailableBytes = (totalGb - usedGb) * gb,
                CachedBytes = cachedGb * gb,
                StandbyBytes = standbyGb.HasValue ? standbyGb.Value * gb : null,
                CommittedBytes = usedGb * gb + gb,
                CommitLimitBytes = totalGb * 2 * gb
            };
        }

        [Fact]
        public void UsedAvailableAndCachedAreKeptApart()
        {
            var memory = Memory(totalGb: 16, usedGb: 10, cachedGb: 5, standbyGb: 3);

            var lines = memory.Describe();

            Assert.Contains(lines, l => l.StartsWith("In use:", StringComparison.Ordinal));
            Assert.Contains(lines, l => l.StartsWith("Available:", StringComparison.Ordinal));
            Assert.Contains(lines, l => l.StartsWith("Cached:", StringComparison.Ordinal));
            Assert.Contains(lines, l => l.StartsWith("Standby", StringComparison.Ordinal));

            // The explanation that stops "cached" being read as "wasted".
            Assert.Contains(lines, l => l.Contains("not memory that is lost", StringComparison.Ordinal));

            Assert.Equal(62.5f, memory.UsedPercent, 1);
        }

        [Fact]
        public void AStandbyFigureThatCannotBeReadIsNA()
        {
            var memory = Memory(totalGb: 16, usedGb: 8, cachedGb: 4);

            Assert.Null(memory.StandbyBytes);
            Assert.Contains(memory.Describe(), l => l.Contains("Standby: N/A", StringComparison.Ordinal));
        }

        [Fact]
        public void AnUnreachableTarget_ProducesTheRequiredSentence()
        {
            var memory = Memory(totalGb: 16, usedGb: 12, cachedGb: 3);

            var candidates = new List<BackgroundProcessAssessment>
            {
                new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 400 * 1024 * 1024 }
            };

            var advice = RamOptimizationAdvisor.Evaluate(memory, candidates, targetPercent: 35, closeBackgroundProcessesAllowed: true);

            Assert.True(advice.LimitReached);
            Assert.Contains(RamOptimizationAdvisor.SafeLimitReached, advice.Summary, StringComparison.Ordinal);
            Assert.Contains(advice.Statements, s => s.Contains("Safe optimization limit reached.", StringComparison.Ordinal));

            // And it says what it refuses to do, instead of doing it.
            Assert.Contains(advice.Statements, s => s.Contains("standby list", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AReachableTarget_IsReportedAsAnEstimateNotAPromise()
        {
            var memory = Memory(totalGb: 16, usedGb: 9, cachedGb: 4);

            var candidates = new List<BackgroundProcessAssessment>
            {
                new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 3L * 1024 * 1024 * 1024 }
            };

            var advice = RamOptimizationAdvisor.Evaluate(memory, candidates, targetPercent: 50, closeBackgroundProcessesAllowed: true);

            Assert.False(advice.LimitReached);
            Assert.Contains("about", advice.Summary, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("not a guarantee", advice.Summary, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void TheReclaimableEstimateIsHalvedAndTheReasonIsStated()
        {
            var memory = Memory(totalGb: 16, usedGb: 6, cachedGb: 5);

            var candidates = new List<BackgroundProcessAssessment>
            {
                new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 1000 * 1024 * 1024 }
            };

            var advice = RamOptimizationAdvisor.Evaluate(memory, candidates, targetPercent: null, closeBackgroundProcessesAllowed: true);

            Assert.Equal(500 * 1024 * 1024, advice.ReclaimableBytesIfAllClosed);
            Assert.Equal(1000L * 1024 * 1024, advice.OptimisticBytesIfAllClosed);
            Assert.Contains("resident", advice.DescribeReclaimable(), StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AProfileThatForbidsClosing_SaysSoInsteadOfQuietlyDoingNothing()
        {
            var memory = Memory(totalGb: 16, usedGb: 12, cachedGb: 2);

            var candidates = new List<BackgroundProcessAssessment>
            {
                new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 900 * 1024 * 1024 }
            };

            var advice = RamOptimizationAdvisor.Evaluate(memory, candidates, 35, closeBackgroundProcessesAllowed: false);

            Assert.Contains("set not to close", advice.Summary, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(0, advice.ReclaimableBytesIfAllClosed);
        }

        [Fact]
        public void TheWindowsShareIsAcknowledgedOnASmallMachine()
        {
            var memory = Memory(totalGb: 8, usedGb: 6, cachedGb: 1);

            var advice = RamOptimizationAdvisor.Evaluate(
                memory,
                new List<BackgroundProcessAssessment>
                {
                    new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 200 * 1024 * 1024 }
                },
                targetPercent: 35,
                closeBackgroundProcessesAllowed: true);

            Assert.True(memory.IsSmallMachine);
            Assert.True(RamOptimizationAdvisor.EstimateWindowsOverheadBytes(memory) >= 1536L * 1024 * 1024);
            Assert.Contains(advice.Statements, s => s.Contains("Windows itself", StringComparison.Ordinal));
        }

        [Fact]
        public void CacheIsNeverDescribedAsWastedMemory()
        {
            var memory = Memory(totalGb: 16, usedGb: 9, cachedGb: 6);

            var advice = RamOptimizationAdvisor.Evaluate(
                memory,
                new List<BackgroundProcessAssessment>
                {
                    new() { ProcessName = "a", Category = BackgroundProcessCategory.UsuallySafe, WorkingSet = 500 * 1024 * 1024 }
                },
                targetPercent: null,
                closeBackgroundProcessesAllowed: true);

            Assert.Contains(advice.Statements, s =>
                s.Contains("cache", StringComparison.OrdinalIgnoreCase) &&
                s.Contains("not wasted", StringComparison.OrdinalIgnoreCase));
        }

        #endregion
    }
}

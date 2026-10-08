using System;
using System.Collections.Generic;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the safety layer. These encode the promises made to the user:
    /// no destructive act can pass, even if it arrives from the AI or the planner.
    /// </summary>
    public class SafetyLayerTests
    {
        private static AppConfig TestConfig()
        {
            var config = AppConfig.CreateDefault();
            config.SafetyLayerEnabled = true;
            config.AllowHighRiskActions = false;
            config.AllowCriticalRiskActions = false;
            config.MaxAutoRiskLevel = RiskLevel.Low;
            return config;
        }

        private static SystemInfo EmptySystem() => new SystemInfo
        {
            TotalPhysicalMemory = 8L * 1024 * 1024 * 1024,
            AvailablePhysicalMemory = 5L * 1024 * 1024 * 1024
        };

        [Theory]
        [InlineData("System")]
        [InlineData("lsass.exe")]
        [InlineData("csrss.exe")]
        [InlineData("dwm.exe")]
        public void ClosingACriticalProcess_IsRejected(string processName)
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = processName,
                RiskLevel = RiskLevel.Low, // even if someone *claims* it is low risk
                CanUndo = false
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()),
                $"Closing {processName} must be rejected by the safety layer.");
        }

        [Fact]
        public void AnAiSuggestionToKillSvchost_IsRejected()
        {
            // The specification's explicit example: the AI says "kill svchost.exe".
            var validator = new SafetyValidator(config: TestConfig());

            var aiAction = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "svchost.exe",
                RiskLevel = RiskLevel.Low,
                AiRecommended = true,
                AiConfidence = 0.99f,
                Reason = "The AI believes this frees 300 MB"
            };

            Assert.False(validator.ValidateAction(aiAction, EmptySystem()),
                "AI recommendations must go through the same validation as any other action.");
        }

        [Theory]
        [InlineData("WinDefend")]
        [InlineData("MpsSvc")]
        [InlineData("wscsvc")]
        [InlineData("BFE")]
        public void DisablingSecurityServices_IsRejected(string serviceName)
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.DisableService,
                Target = serviceName,
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()),
                $"Disabling {serviceName} would weaken the system and must be rejected.");
        }

        [Fact]
        public void CriticalRiskActions_AreRejectedByDefault()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "some_app.exe",
                RiskLevel = RiskLevel.Critical
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()));
        }

        [Fact]
        public void HighRiskActions_AreRejectedWhenNotExplicitlyAllowed()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "vendor_helper.exe",
                RiskLevel = RiskLevel.High
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()));
        }

        [Fact]
        public void ClosingAProcessThatIsInUse_IsRejected()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var system = EmptySystem();
            system.Processes.Add(new ProcessInfo
            {
                Id = 4242,
                Name = "chrome.exe",
                WorkingSet = 800L * 1024 * 1024,
                Category = ProcessCategory.UserApplication,
                RiskLevel = RiskLevel.Low,
                HasVisibleWindow = true,
                IsActive = true
            });

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "chrome.exe",
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(action, system),
                "A process with a visible window must never be closed automatically.");
        }

        [Fact]
        public void ClosingAnIdleBackgroundProcess_IsAllowed()
        {
            // WHY THIS TEST CHANGED
            // --------------------
            // The test used to build an action with only a name and expect it to be approved. That
            // expectation encoded a real defect: an action carrying no process identity cannot be
            // proven, at execution time, to refer to the same process the planner looked at. Windows
            // recycles process ids, so such an action may terminate an unrelated program.
            //
            // The safety layer now requires a pid plus the kernel creation timestamp, which is exactly
            // what OptimizationPlanner.AnchorProcessIdentities records. The original intent of the
            // test - "an idle, low-risk background application is a legitimate optimisation" - is
            // unchanged and is asserted here with a realistic, fully anchored action.
            var validator = new SafetyValidator(config: TestConfig());

            var creationTime = new DateTime(2026, 1, 1, 12, 0, 0, DateTimeKind.Utc);

            var system = EmptySystem();
            system.Processes.Add(new ProcessInfo
            {
                Id = 5150,
                Name = "spotify.exe",
                WorkingSet = 200L * 1024 * 1024,
                Category = ProcessCategory.BackgroundApplication,
                RiskLevel = RiskLevel.Low,
                HasVisibleWindow = false,
                IsActive = false,
                CreationTimeUtc = creationTime
            });

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "spotify.exe",
                TargetPid = 5150,
                TargetProcessName = "spotify",
                TargetCreationTimeUtc = creationTime,
                RiskLevel = RiskLevel.Low,
                CanUndo = false
            };

            Assert.True(validator.ValidateAction(action, system),
                "An idle background application with a verified identity is a legitimate optimisation.");
        }

        [Fact]
        public void ClosingAProcessWithoutARecordedIdentity_IsRejected()
        {
            // Fail closed: an action that cannot prove which process it points at is never approved,
            // even when the target itself looks perfectly harmless.
            var validator = new SafetyValidator(config: TestConfig());

            var system = EmptySystem();
            system.Processes.Add(new ProcessInfo
            {
                Id = 5150,
                Name = "spotify.exe",
                Category = ProcessCategory.BackgroundApplication,
                RiskLevel = RiskLevel.Low,
                HasVisibleWindow = false,
                IsActive = false
            });

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "spotify.exe",
                RiskLevel = RiskLevel.Low,
                CanUndo = false
            };

            Assert.False(validator.ValidateAction(action, system),
                "A process action without a pid and creation time cannot be verified and must be rejected.");
        }

        // ---------------------------------------------------------------------------------------
        // PID-reuse (TOCTOU) discriminator.
        //
        // These tests target WindowsApiHelper.IsSameProcessIdentity, which is intentionally a pure
        // function with no Win32 dependency. Testing the pure comparison is what makes the PID-reuse
        // claim verifiable; the surrounding method that reads the live timestamp can only be
        // exercised on Windows, and that limitation is recorded in the report rather than papered over.
        // ---------------------------------------------------------------------------------------

        [Fact]
        public void SameProcessIdentity_ExactTimestamp_Matches()
        {
            var moment = new DateTime(2026, 1, 1, 9, 0, 0, DateTimeKind.Utc);

            Assert.True(WindowsApiHelper.IsSameProcessIdentity(moment, moment),
                "A process scanned and executed against in the same instant is the same process.");
        }

        [Fact]
        public void SameProcessIdentity_SubSecondDrift_StillMatches()
        {
            // Serialising a timestamp through the history file can round it slightly; that must not
            // turn a legitimate action into a false rejection.
            var planned = new DateTime(2026, 1, 1, 9, 0, 0, DateTimeKind.Utc);

            Assert.True(WindowsApiHelper.IsSameProcessIdentity(planned, planned.AddMilliseconds(400)),
                "Rounding below the tolerance must still be accepted.");
        }

        [Theory]
        // A recycled pid is always a *newer* process, i.e. a later creation time.
        [InlineData(2)]
        [InlineData(60)]
        [InlineData(600)]
        [InlineData(86400)]
        public void SameProcessIdentity_RecycledPid_IsRejected(int offsetSeconds)
        {
            // The specification's TOCTOU scenario, verbatim:
            //   1. a process is scanned and gets pid 1234;
            //   2. it exits, and Windows hands pid 1234 to a different program;
            //   3. the optimiser must not kill that new program.
            var planned = new DateTime(2026, 1, 1, 9, 0, 0, DateTimeKind.Utc);
            var reused = planned.AddSeconds(offsetSeconds);

            Assert.False(WindowsApiHelper.IsSameProcessIdentity(planned, reused),
                $"A process created {offsetSeconds}s later under the same pid is a different process.");
        }

        [Fact]
        public void SameProcessIdentity_UnrecordedTimestamp_IsRejected()
        {
            // DateTime.MinValue means "no identity was captured". That is not a match - treating
            // "unknown" as "verified" is precisely the failure this guard exists to prevent.
            var actual = new DateTime(2026, 1, 1, 9, 0, 0, DateTimeKind.Utc);

            Assert.False(WindowsApiHelper.IsSameProcessIdentity(DateTime.MinValue, actual),
                "An unrecorded creation time must never be accepted as a match.");

            Assert.False(WindowsApiHelper.IsSameProcessIdentity(actual, DateTime.MinValue),
                "An unreadable live creation time must never be accepted as a match.");
        }

        [Fact]
        public void ActionWithoutRecordedIdentity_HasNoIdentityFlag()
        {
            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "notepad.exe",
                TargetPid = 1234
                // TargetCreationTimeUtc deliberately left unset.
            };

            Assert.False(action.HasProcessIdentity,
                "A pid alone is not an identity - the creation time must be present.");
        }

        [Fact]
        public void CaptureProcessIdentity_RecordsPidTimestampAndName()
        {
            var creationTime = new DateTime(2026, 3, 4, 5, 6, 7, DateTimeKind.Utc);

            var process = new ProcessInfo
            {
                Id = 4242,
                Name = "Discord.exe",
                Path = @"C:\Users\user\AppData\Local\Discord\Discord.exe",
                CreationTimeUtc = creationTime
            };

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = process.Name
            };

            action.CaptureProcessIdentity(process);

            Assert.Equal(4242, action.TargetPid);
            Assert.Equal(creationTime, action.TargetCreationTimeUtc);
            Assert.Equal("Discord", action.TargetProcessName);
            Assert.True(action.HasProcessIdentity);
        }

        [Fact]
        public void TerminateProcessSafely_RefusesWithoutAnIdentity()
        {
            // The guard that closes the check-to-use race: without the creation timestamp the method
            // cannot prove the pid still refers to the process that was inspected, so it refuses.
            var closed = Core.Utilities.ProcessHelper.TerminateProcessSafely(
                processId: 4,
                expectedCreationTimeUtc: DateTime.MinValue,
                out var reason);

            Assert.False(closed);
            Assert.Contains("identity", reason, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void TerminateProcessesByName_IsRefusedOutright()
        {
            // Closing every process with a given name cannot distinguish two instances of the same
            // executable, one of which may be the window the user is working in.
#pragma warning disable CS0618 // the obsolete attribute is the point of the test
            var closed = Core.Utilities.ProcessHelper.TerminateProcessesByName(
                "chrome.exe",
                out var errors);
#pragma warning restore CS0618

            Assert.Equal(0, closed);
            Assert.NotEmpty(errors);
        }

        [Theory]
        [InlineData("svchost", "svchost")]
        [InlineData("svchost.exe", "svchost")]
        [InlineData(@"C:\Windows\System32\svchost.exe", "svchost")]
        [InlineData("\"C:\\Program Files\\App\\App.exe\"", "App")]
        [InlineData("Discord.EXE", "Discord")]
        [InlineData("", "")]
        public void NormalizeProcessName_ProducesComparableNames(string input, string expected)
        {
            Assert.Equal(expected, WindowsApiHelper.NormalizeProcessName(input));
        }

        [Fact]
        public void UserConfirmation_IsRequiredForIrreversibleActions()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var irreversible = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "discord.exe",
                RiskLevel = RiskLevel.Low,
                CanUndo = false
            };

            Assert.True(validator.RequiresUserConfirmation(irreversible, EmptySystem()));
        }

        [Fact]
        public void UserConfirmation_IsRequiredForAiSuggestions()
        {
            var config = TestConfig();
            config.RequireAiConfirmation = true;

            var validator = new SafetyValidator(config: config);

            var aiAction = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "some_app.exe",
                RiskLevel = RiskLevel.Low,
                CanUndo = true,
                AiRecommended = true
            };

            Assert.True(validator.RequiresUserConfirmation(aiAction, EmptySystem()));
        }

        [Fact]
        public void PlanWithCriticalAction_IsRejectedEntirely()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var plan = new OptimizationPlan();
            plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "spotify.exe",
                RiskLevel = RiskLevel.Low
            });
            plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "lsass.exe",
                RiskLevel = RiskLevel.Critical
            });

            Assert.False(validator.ValidatePlan(plan, EmptySystem()),
                "A single unsafe action must invalidate the whole plan.");
        }

        [Fact]
        public void SafetyLayer_CanBeDisabled_ButDefaultsToEnabled()
        {
            Assert.True(AppConfig.CreateDefault().SafetyLayerEnabled);

            var config = TestConfig();
            config.SafetyLayerEnabled = false;

            var validator = new SafetyValidator(config: config);

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "lsass.exe",
                RiskLevel = RiskLevel.Low
            };

            // With the safety layer switched off the validator declines everything rather than
            // silently becoming permissive - failing closed is the safe behaviour.
            Assert.False(validator.ValidateAction(action, EmptySystem()));
        }
    }

    /// <summary>
    /// Tests for the configuration contract: defaults, validation and round-tripping.
    /// </summary>
    public class ConfigurationTests
    {
        [Fact]
        public void DefaultConfiguration_MatchesTheDocumentedDefaults()
        {
            var config = AppConfig.CreateDefault();

            Assert.Equal(35, config.TargetRamUsage);
            Assert.True(config.DarkMode);
            Assert.True(config.SafetyLayerEnabled);
            Assert.Equal(RiskLevel.Low, config.MaxAutoRiskLevel);
            Assert.False(config.AllowHighRiskActions);
            Assert.False(config.AllowCriticalRiskActions);
            Assert.True(config.GameModeEnabled);
        }

        [Fact]
        public void Validation_RejectsOutOfRangeValues()
        {
            var config = AppConfig.CreateDefault();
            config.TargetRamUsage = 5;               // below the safe minimum
            config.AutoOptimizeInterval = 1;         // too aggressive
            config.AiConfidenceThreshold = 2f;       // outside 0..1

            Assert.False(config.Validate(out var errors));
            Assert.NotEmpty(errors);
        }

        [Fact]
        public void Validation_AcceptsTheDefaults()
        {
            Assert.True(AppConfig.CreateDefault().Validate(out var errors));
            Assert.Empty(errors);
        }

        [Fact]
        public void Clone_IsIndependentFromTheOriginal()
        {
            var config = AppConfig.CreateDefault();
            var clone = config.Clone();

            clone.WhitelistedProcesses.Add("custom.exe");
            clone.TargetRamUsage = 42;

            Assert.DoesNotContain("custom.exe", config.WhitelistedProcesses);
            Assert.Equal(35, config.TargetRamUsage);
        }

        [Fact]
        public void OptimizationPlan_ComputesRiskFromItsActions()
        {
            var plan = new OptimizationPlan();

            plan.Actions.Add(new OptimizationAction { RiskLevel = RiskLevel.Low });
            Assert.Equal(RiskLevel.Low, plan.OverallRiskLevel);

            plan.Actions.Add(new OptimizationAction { RiskLevel = RiskLevel.Medium });
            Assert.Equal(RiskLevel.Medium, plan.OverallRiskLevel);

            plan.Actions.Clear();
            plan.Actions.Add(new OptimizationAction { RiskLevel = RiskLevel.High });
            Assert.Equal(RiskLevel.High, plan.OverallRiskLevel);
        }

        [Fact]
        public void OptimizationPlan_EstimatesOnlyProcessAndServiceRecovery()
        {
            var plan = new OptimizationPlan();

            plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                ResourceType = ResourceType.RAM,
                EstimatedResourceRecovery = 512L * 1024 * 1024
            });

            plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.AdjustPowerSettings,
                ResourceType = ResourceType.CPU,
                EstimatedResourceRecovery = 999L * 1024 * 1024   // must be ignored for RAM
            });

            Assert.Equal(512L * 1024 * 1024, plan.EstimatedRamRecovery);
        }
    }
}

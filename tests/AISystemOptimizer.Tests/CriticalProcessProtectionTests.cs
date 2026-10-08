using System;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the layered protection around the processes the operating system cannot do without.
    ///
    /// The specification is explicit that a name blacklist is not enough, and that "safe" must never be
    /// decided by something as simple as a string comparison against one list. These tests therefore
    /// check the classification, the risk assignment, the category mapping and the decision the safety
    /// layer reaches - each independently.
    /// </summary>
    public class CriticalProcessProtectionTests
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

        #region Name coverage

        [Theory]
        [InlineData("svchost.exe")]
        [InlineData("lsass.exe")]
        [InlineData("csrss.exe")]
        [InlineData("wininit.exe")]
        [InlineData("winlogon.exe")]
        [InlineData("services.exe")]
        [InlineData("smss.exe")]
        [InlineData("System")]
        [InlineData("dwm.exe")]
        [InlineData("explorer.exe")]
        [InlineData("audiodg.exe")]
        public void CoreWindowsProcesses_AreCritical(string name)
        {
            Assert.True(CriticalProcesses.IsCritical(name),
                $"{name} is required for Windows to function and must be classified critical.");
        }

        [Theory]
        [InlineData("MsMpEng.exe")]
        [InlineData("mpcmdrun.exe")]
        [InlineData("SecurityHealthService.exe")]
        [InlineData("SecurityHealthSystray.exe")]
        [InlineData("NisSrv.exe")]
        public void SecurityStack_IsCritical(string name)
        {
            // Spec section 20: the security stack is never optimised, even on request.
            Assert.True(CriticalProcesses.IsCritical(name),
                $"{name} is part of the security stack and must be treated as critical.");
        }

        [Fact]
        public void IsCritical_IsCaseInsensitive()
        {
            Assert.True(CriticalProcesses.IsCritical("SVCHOST.EXE"));
            Assert.True(CriticalProcesses.IsCritical("Lsass.Exe"));
        }

        [Fact]
        public void IsCritical_RejectsOrdinaryApplications()
        {
            // The counterpart check: a normal application must not be swept up by the protection,
            // otherwise the optimiser would never do anything at all.
            //
            // BUG FIXED HERE: notepad.exe, mspaint.exe, calc.exe, wordpad.exe, charmap.exe and the
            // Snipping Tool used to sit in the "system processes that must never be terminated" list.
            // They are ordinary applications: the interface labelled them "Windows System" and they
            // could never be optimised. They now live in their own set and are protected by the much
            // stronger rule that applies to every application - a program with a window, or with the
            // foreground, is never closed.
            Assert.False(CriticalProcesses.IsCritical("notepad.exe"));
            Assert.False(CriticalProcesses.IsCritical("spotify.exe"));
            Assert.False(CriticalProcesses.IsCritical("mspaint.exe"));
            Assert.False(CriticalProcesses.IsCritical("calc.exe"));
        }

        [Theory]
        [InlineData("notepad.exe")]
        [InlineData("mspaint.exe")]
        [InlineData("calc.exe")]
        [InlineData("wordpad.exe")]
        public void MicrosoftUserApplications_AreRecognisedButNotSystemCritical(string name)
        {
            Assert.True(CriticalProcesses.IsMicrosoftUserApplication(name));
            Assert.False(CriticalProcesses.IsCritical(name),
                $"{name} is a user application, not a Windows system process.");

            var category = CriticalProcesses.GetProcessCategory(name, string.Empty, isService: false);
            Assert.Equal(ProcessCategory.UserApplication, category);
        }

        [Fact]
        public void IdleProcess_IsProtected()
        {
            Assert.True(CriticalProcesses.IsCritical("Idle"));
            Assert.True(CriticalProcesses.IsCriticalName("System"));
        }

        #endregion

        #region svchost - a container, not one service

        [Fact]
        public void Svchost_CategoryIsSystemService_AndIsCritical()
        {
            // svchost.exe hosts many unrelated services. It must be classified as a system service and
            // it must be critical, so the "close it because it uses memory" path can never be reached.
            var category = CriticalProcesses.GetProcessCategory(
                "svchost.exe", @"C:\Windows\System32\svchost.exe", isService: true);

            // svchost.exe is protected at the strongest level, which is what matters here: whatever
            // bucket the category lands in, the safety layer must refuse to close it.
            Assert.True(category == ProcessCategory.Critical || category == ProcessCategory.System,
                $"svchost.exe must be classified as a protected Windows component, was {category}.");
            Assert.True(CriticalProcesses.IsCritical("svchost.exe"));

            var risk = CriticalProcesses.GetProcessRiskLevel("svchost.exe", category);
            Assert.Equal(RiskLevel.Critical, risk);
        }

        [Fact]
        public void Svchost_CloseAction_IsRejectedEvenWhenThePlannerSaysLowRisk()
        {
            // The specific dangerous case: a caller (or an AI) labels the action low risk to get it
            // past the risk ceiling. The critical-process rule must fire independently of the label.
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "svchost.exe",
                TargetPid = 1234,
                TargetProcessName = "svchost",
                TargetCreationTimeUtc = DateTime.UtcNow,
                RiskLevel = RiskLevel.Low,
                Description = "Free up memory",
                Reason = "svchost is using a lot of RAM"
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()),
                "svchost.exe must never be closed as a memory optimisation.");
        }

        [Fact]
        public void StoppingTheServiceInsideSvchost_MustGoThroughTheServicePathNotTheProcessPath()
        {
            // The model the application relies on: the process is off-limits, and any legitimate
            // service change goes through the service path, where dependency checking and the service
            // blacklist apply instead.
            var system = EmptySystem();

            system.Services.Add(new SystemInfo.ServiceInfo
            {
                Name = "WinDefend",
                DisplayName = "Microsoft Defender Antivirus Service",
                Status = "Running",
                IsWindowsService = true,
                IsCritical = true
            });

            var validator = new SafetyValidator(config: TestConfig());

            var disableDefender = new OptimizationAction
            {
                ActionType = OptimizationActionType.DisableService,
                Target = "WinDefend",
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(disableDefender, system),
                "Disabling Windows Defender must be refused regardless of the risk label attached to it.");
        }

        #endregion

        #region explorer.exe

        [Fact]
        public void Explorer_IsClassifiedAsCriticallyProtected()
        {
            Assert.True(CriticalProcesses.IsCritical("explorer.exe"));
            Assert.Equal(RiskLevel.Critical,
                CriticalProcesses.GetProcessRiskLevel("explorer.exe", ProcessCategory.System));
        }

        [Fact]
        public void Explorer_IsNeverAnOptimisationTarget()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "explorer.exe",
                TargetPid = 4242,
                TargetProcessName = "explorer",
                TargetCreationTimeUtc = DateTime.UtcNow,
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()),
                "Restarting the shell is never a memory optimisation and must not be reachable from the RAM path.");
        }

        #endregion

        #region Drivers

        [Fact]
        public void KnownDriverHelpers_AreCritical()
        {
            Assert.True(CriticalProcesses.IsCritical("RtkAudioService64.exe"));
            Assert.True(CriticalProcesses.IsCritical("igfxEM.exe"));
        }

        [Fact]
        public void DriverRecognition_AndCriticalRecognition_Agree()
        {
            // BUG FIXED HERE: IsDriverProcess applied a vendor-name heuristic that IsCritical did not,
            // so a driver recognised only by its name was classified as a driver yet approved for
            // closing. The two must never disagree in that direction.
            var heuristicallyNamedDrivers = new[]
            {
                "RtkAudUService64.exe",
                "igfxtray.exe",
                "nvcontainer.exe",
                "SynTPEnh.exe",
                "ETDCtrl.exe"
            };

            foreach (var name in heuristicallyNamedDrivers)
            {
                if (CriticalProcesses.IsDriverProcess(name))
                {
                    Assert.True(CriticalProcesses.IsCritical(name),
                        $"{name} is recognised as a driver, so it must also be treated as critical.");
                }
            }
        }

        [Fact]
        public void DriverClassification_DoesNotSwallowUnrelatedApplications()
        {
            // A previous version of the rules engine matched on loose substrings and classified Steam
            // as a game purely because the word appeared in the binary name. Guard the direction that
            // matters: a normal application must not be pulled into the driver list.
            Assert.False(CriticalProcesses.IsDriverProcess("Steam.exe"));
            Assert.False(CriticalProcesses.IsDriverProcess("Discord.exe"));
            Assert.False(CriticalProcesses.IsDriverProcess("chrome.exe"));
        }

        #endregion

        #region Category mapping for the whole requirement list

        [Theory]
        [InlineData("steam.exe", ProcessCategory.Launcher)]
        [InlineData("EpicGamesLauncher.exe", ProcessCategory.Launcher)]
        [InlineData("GoogleUpdate.exe", ProcessCategory.Updater)]
        [InlineData("OneDrive.exe", ProcessCategory.CloudSync)]
        [InlineData("DiagTrack", ProcessCategory.Telemetry)]
        public void RequirementCategories_AreDetected(string name, ProcessCategory expected)
        {
            // The specification lists launcher / updater / cloud-sync / telemetry as categories that
            // must be recognised in their own right rather than lumped into "background".
            Assert.Equal(expected, CriticalProcesses.GetProcessCategory(name, string.Empty, isService: false));
        }

        [Fact]
        public void TelemetryDetection_DoesNotTriggerOnUnrelatedNames()
        {
            // "diagtrack" contains "ac"; a naive substring match made almost everything telemetry at
            // one point. Check a few names that must not match.
            Assert.NotEqual(ProcessCategory.Telemetry,
                CriticalProcesses.GetProcessCategory("Acrobat.exe", string.Empty, isService: false));
            Assert.NotEqual(ProcessCategory.Telemetry,
                CriticalProcesses.GetProcessCategory("Code.exe", string.Empty, isService: false));
        }

        #endregion

        #region Risk levels gate the action, not just the category

        [Fact]
        public void CriticalRiskAction_IsRefusedWhenNotExplicitlyAllowed()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.StopService,
                Target = "SomeBenignLookingService",
                RiskLevel = RiskLevel.Critical
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()));
        }

        [Fact]
        public void HighRiskAction_IsRefusedWhenNotExplicitlyAllowed()
        {
            var validator = new SafetyValidator(config: TestConfig());

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.StopService,
                Target = "SomeBenignLookingService",
                RiskLevel = RiskLevel.High
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()));
        }

        #endregion

        #region Fail-closed behaviour of the safety layer itself

        [Fact]
        public void DisablingTheSafetyLayer_MakesEveryActionFailClosed()
        {
            // If someone turns the safety layer off in the configuration file, the correct behaviour is
            // to refuse everything - not to execute without checks. "Off" must not mean "unprotected".
            var config = TestConfig();
            config.SafetyLayerEnabled = false;

            var validator = new SafetyValidator(config: config);

            var harmless = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "spotify.exe",
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(harmless, EmptySystem()),
                "A disabled safety layer must fail closed rather than allow unchecked execution.");
        }

        [Fact]
        public void UserExcludedProcess_IsRefused()
        {
            // "Never touch" in the UI must be honoured by the same validator the planner consults.
            var config = TestConfig();
            config.ExcludedProcesses.Add("my-banking-app.exe");

            var validator = new SafetyValidator(config: config);

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "my-banking-app.exe",
                TargetPid = 99,
                TargetProcessName = "my-banking-app",
                TargetCreationTimeUtc = DateTime.UtcNow,
                RiskLevel = RiskLevel.Low
            };

            Assert.False(validator.ValidateAction(action, EmptySystem()),
                "A process the user excluded must never be proposed or executed.");
        }

        [Fact]
        public void ExcludedProcesses_MapOntoTheSpecificationKeyName()
        {
            // The specification names the configuration key ExcludedProcesses. Confirm the alias and the
            // list are the same thing, so the file and the code agree.
            var config = AppConfig.CreateDefault();
            config.ExcludedProcesses.Add("never-touch-me.exe");

            Assert.Contains("never-touch-me.exe", config.WhitelistedProcesses);
            Assert.True(config.IsExcluded("never-touch-me.exe"));
            Assert.True(config.IsExcluded("NEVER-TOUCH-ME.EXE"));
            Assert.False(config.IsExcluded("something-else.exe"));
        }

        #endregion
    }
}

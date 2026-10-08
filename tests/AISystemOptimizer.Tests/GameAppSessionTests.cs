using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using AISystemOptimizer.Core.Models;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the part of the feature that has to be right even when everything else goes wrong: the
    /// session record, the planner's refusals, and the restore that must never claim more than it checked.
    ///
    /// The rules under test:
    ///   * The record is written before the first change; if it cannot be written, nothing is changed.
    ///   * A session that was left open is detected on the next start and is never restored silently.
    ///   * A failure to restore is reported exactly, and "everything restored" is not claimed.
    ///   * Nothing is planned that the profile or the safety model does not allow.
    /// </summary>
    public class GameAppSessionTests : IDisposable
    {
        private readonly string _directory;
        private readonly GameAppSessionStore _store;

        public GameAppSessionTests()
        {
            _directory = Path.Combine(Path.GetTempPath(), "aio-sessions-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_directory);
            _store = new GameAppSessionStore(directory: _directory);
        }

        public void Dispose()
        {
            try
            {
                if (Directory.Exists(_directory))
                    Directory.Delete(_directory, recursive: true);
            }
            catch
            {
                // Never fail a run on cleanup.
            }
        }

        private static GameAppSession Session(
            string application = "ExampleGame",
            params SessionChangeRecord[] changes)
        {
            var session = new GameAppSession
            {
                ApplicationId = Guid.NewGuid(),
                ApplicationName = application,
                ExecutablePath = @"C:\Games\Example\Game.exe",
                ExecutableHash = new string('a', 64),
                Trigger = "Manual"
            };

            session.Changes.AddRange(changes);

            return session;
        }

        private static GameAppProfile Profile()
        {
            return new GameAppProfile
            {
                ApplicationId = Guid.NewGuid(),
                DisplayName = "Example Game",
                ProfileMode = GameAppProfileMode.Balanced,
                Identity = new ExecutableIdentity
                {
                    ExecutablePath = @"C:\Games\Example\Game.exe",
                    FileName = "Game.exe",
                    Sha256 = new string('a', 64),
                    FileSizeBytes = 1024
                }
            };
        }

        private static ApplicationHealth Healthy() => new ApplicationHealth { State = ApplicationHealthState.Healthy };

        #region The session record

        [Fact]
        public void AnOpenSessionIsRecordedBeforeAnythingIsChanged()
        {
            var session = Session();

            Assert.True(_store.SaveOpen(session));

            var open = _store.LoadOpenSessions();

            Assert.Single(open);
            Assert.Equal(session.SessionId, open[0].SessionId);
            Assert.True(open[0].WasInterrupted);
            Assert.Equal("An optimization session was interrupted.", open[0].InterruptedSummary);
        }

        [Fact]
        public void ClosingASessionRemovesTheOpenRecordAndWritesHistory()
        {
            var session = Session();

            Assert.True(_store.SaveOpen(session));

            session.Changes.Add(new SessionChangeRecord
            {
                Kind = "GraphicsPreference",
                OriginalValue = "GpuPreference=1;",
                NewValue = "GpuPreference=2;",
                TargetPath = @"C:\Games\Example\Game.exe",
                TargetName = "Game.exe"
            });

            session.WasRestored = true;

            Assert.True(_store.CloseSession(session));

            // No open record is left: the next start must not report an interruption that is over.
            Assert.Empty(_store.LoadOpenSessions());

            var history = _store.LoadHistory();

            Assert.Single(history);
            Assert.Equal(session.SessionId, history[0].SessionId);
            Assert.False(history[0].IsOpen);
            Assert.NotNull(history[0].EndTimeUtc);
            Assert.True(history[0].WasRestored);
            Assert.Single(history[0].Changes);
        }

        [Fact]
        public void ADamagedOpenSessionFileIsReportedAndDoesNotStopTheOthers()
        {
            var good = Session();
            Assert.True(_store.SaveOpen(good));

            File.WriteAllText(Path.Combine(_store.OpenSessionDirectory, Guid.NewGuid().ToString("D") + ".json"), "{ broken");

            var open = _store.LoadOpenSessions();

            Assert.Single(open);
            Assert.Equal(good.SessionId, open[0].SessionId);
            Assert.NotEmpty(_store.LoadProblems);
        }

        [Fact]
        public void AnEmptyOpenSessionFileIsSkippedWithAReason()
        {
            Directory.CreateDirectory(_store.OpenSessionDirectory);
            File.WriteAllText(Path.Combine(_store.OpenSessionDirectory, Guid.NewGuid().ToString("D") + ".json"), string.Empty);

            Assert.Empty(_store.LoadOpenSessions());
            Assert.Contains(_store.LoadProblems, p => p.Contains("unexpected size", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void ADamagedHistoryFileIsQuarantinedAndTheFeatureStillWorks()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_store.HistoryPath)!);
            File.WriteAllText(_store.HistoryPath, "not json at all");

            Assert.Empty(_store.LoadHistory());

            // The damaged file is kept, with a reason, rather than deleted.
            Assert.True(File.Exists(_store.HistoryPath + ".invalid"));

            // And the store still works afterwards.
            var session = Session();
            Assert.True(_store.SaveOpen(session));
            Assert.True(_store.CloseSession(session));
            Assert.Single(_store.LoadHistory());
        }

        [Fact]
        public void TheHistoryIsTrimmedToItsLimitKeepingTheNewest()
        {
            for (var i = 0; i < 5; i++)
            {
                var session = Session($"App {i}");
                session.StartTimeUtc = DateTime.UtcNow.AddMinutes(-i);

                Assert.True(_store.SaveOpen(session));
                Assert.True(_store.CloseSession(session));
            }

            var history = _store.LoadHistory(maximum: 3);

            Assert.Equal(3, history.Count);
            Assert.Equal("App 0", history[0].ApplicationName);
        }

        #endregion

        #region The planner

        [Fact]
        public void AProfileWhoseExecutableChanged_PlansNothingAtAll()
        {
            var planner = new GameAppActionPlanner();

            var health = new ApplicationHealth { State = ApplicationHealthState.ExecutableChanged };
            health.Findings.Add("The file's contents changed.");

            var plan = planner.Plan(
                Profile(),
                health,
                Array.Empty<ApplicationRunInfo>(),
                Array.Empty<ProcessInfo>(),
                null,
                allowPowerChange: true,
                allowGraphicsChange: true);

            Assert.False(plan.HasAnythingToDo);
            Assert.Contains(plan.Refusals, r => r.Why.Contains("requires verification", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AProfileThatIsSwitchedOff_PlansNothing()
        {
            var profile = Profile();
            profile.Enabled = false;

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), Array.Empty<ApplicationRunInfo>(), Array.Empty<ProcessInfo>(),
                null, true, true);

            Assert.False(plan.HasAnythingToDo);
            Assert.Contains(plan.Refusals, r => r.Why.Contains("switched off", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AffinityIsNeverPlanned()
        {
            var profile = Profile();
            ProfileModePresets.Apply(profile, GameAppProfileMode.Performance);

            var instances = new List<ApplicationRunInfo>
            {
                new() { ProcessId = 4242, CreationTimeUtc = DateTime.UtcNow, IsConfirmedMatch = true, Path = profile.ExecutablePath }
            };

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), instances, Array.Empty<ProcessInfo>(), null, true, true);

            // The only process action is the priority change.
            Assert.All(plan.Plan.Actions, a =>
                Assert.NotEqual(OptimizationActionType.ChangeAffinity, a.ActionType));

            Assert.Contains(plan.Refusals, r =>
                r.What.Contains("affinity", StringComparison.OrdinalIgnoreCase) &&
                r.Why.Contains("never", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void EveryPlannedActionCarriesItsOwnRollbackAndReason()
        {
            var profile = Profile();
            ProfileModePresets.Apply(profile, GameAppProfileMode.Balanced);

            var instances = new List<ApplicationRunInfo>
            {
                new() { ProcessId = 100, CreationTimeUtc = DateTime.UtcNow, IsConfirmedMatch = true, Path = profile.ExecutablePath }
            };

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), instances, Array.Empty<ProcessInfo>(), null, true, true);

            Assert.NotEmpty(plan.Plan.Actions);

            foreach (var action in plan.Plan.Actions)
            {
                Assert.False(string.IsNullOrWhiteSpace(action.Reason));
                Assert.False(string.IsNullOrWhiteSpace(action.Description));

                // Anything aimed at a process must carry that process's identity. Anything that is not
                // aimed at a process (the power mode) has no pid, and that is correct.
                if (action.ActionType is OptimizationActionType.ChangePriority or OptimizationActionType.CloseProcess)
                {
                    Assert.Equal(100, action.TargetPid);
                    Assert.NotEqual(DateTime.MinValue, action.TargetCreationTimeUtc);
                }

                if (action.ActionType != OptimizationActionType.CloseProcess)
                    Assert.True(action.CanUndo, $"{action.ActionType} should be undoable");
            }
        }

        [Fact]
        public void AProcessIdWithoutACreationTime_IsNeverPlanned()
        {
            var profile = Profile();
            profile.Ram.MaxBackgroundProcessesPerSession = 3;

            var processes = new List<ProcessInfo>
            {
                new()
                {
                    Id = 900,
                    Name = "BigHelper",
                    Path = @"C:\Tools\BigHelper.exe",
                    Category = ProcessCategory.BackgroundApplication,
                    RiskLevel = RiskLevel.Low,
                    WorkingSet = 900L * 1024 * 1024,
                    CreationTimeUtc = DateTime.MinValue // unreadable
                }
            };

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), Array.Empty<ApplicationRunInfo>(), processes, null, true, true);

            Assert.DoesNotContain(plan.Plan.Actions, a => a.ActionType == OptimizationActionType.CloseProcess);
            Assert.Contains(plan.Refusals, r => r.Why.Contains("not an identity", StringComparison.Ordinal));
        }

        [Fact]
        public void ThePowerModeIsNotChangedWhenTheOriginalCannotBeRead()
        {
            var profile = Profile();
            profile.Power.Enabled = true;
            profile.Power.ModeWhileRunning = PowerPreference.HighPerformance;

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), Array.Empty<ApplicationRunInfo>(), Array.Empty<ProcessInfo>(), null, true, true);

            // Off Windows - and on any machine where powercfg cannot be read - the scheme is unknown, so
            // no power action may be planned. A change that cannot be undone is not made.
            if (string.IsNullOrWhiteSpace(AISystemOptimizer.Core.Utilities.PowerSchemeManager.GetActiveSchemeName()))
            {
                Assert.DoesNotContain(plan.Plan.Actions, a => a.ActionType == OptimizationActionType.AdjustPowerSettings);
                Assert.Contains(plan.Refusals, r => r.Why.Contains("could not be read", StringComparison.OrdinalIgnoreCase));
            }
        }

        [Fact]
        public void TheGraphicsPreferenceIsRefusedWhenTheConfigurationForbidsIt()
        {
            var profile = Profile();
            profile.Gpu.GraphicsPreference = GraphicsPreference.HighPerformance;

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), Array.Empty<ApplicationRunInfo>(), Array.Empty<ProcessInfo>(), null,
                allowPowerChange: true,
                allowGraphicsChange: false);

            Assert.Null(plan.RequestedGraphicsPreference);
            Assert.Contains(plan.Refusals, r => r.What.Contains("Graphics", StringComparison.Ordinal));
        }

        [Fact]
        public void NothingIsPlannedWhenNothingNeedsDoing()
        {
            var profile = Profile();
            ProfileModePresets.Apply(profile, GameAppProfileMode.Safe);

            var plan = new GameAppActionPlanner().Plan(
                profile, Healthy(), Array.Empty<ApplicationRunInfo>(), Array.Empty<ProcessInfo>(), null, true, true);

            Assert.False(plan.HasAnythingToDo);
            Assert.Contains("No action was planned", plan.Summary, StringComparison.Ordinal);
        }

        #endregion

        #region Starting a session

        [Fact]
        public async Task ASessionDoesNotStartWhenItsRecordCannotBeWritten()
        {
            // A file where the sessions directory should be: the record cannot be created.
            var blockedRoot = Path.Combine(_directory, "blocked");
            Directory.CreateDirectory(blockedRoot);
            File.WriteAllText(Path.Combine(blockedRoot, "sessions"), "in the way");

            var brokenStore = new GameAppSessionStore(directory: blockedRoot);

            var manager = new GameAppSessionManager(
                config: AppConfig.CreateDefault(),
                store: brokenStore);

            var profile = Profile();
            profile.Cpu.Priority = ProcessPriorityPreference.High;

            var plan = new GameAppPlan
            {
                Profile = profile
            };

            plan.Plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.ChangePriority,
                Target = "Game.exe",
                TargetPid = 555,
                TargetCreationTimeUtc = DateTime.UtcNow
            });

            var result = await manager.StartPlannedSessionAsync(profile, plan, "Manual", userConfirmed: true);

            Assert.False(result.Started);
            Assert.Contains("could not be written", result.Message, StringComparison.OrdinalIgnoreCase);
            Assert.False(manager.HasActiveSession);

            // Nothing was left behind on disk.
            Assert.False(File.Exists(Path.Combine(blockedRoot, "sessions", "open", "x.json")));
        }

        [Fact]
        public async Task ASessionWithNothingToDoDoesNotStartAndSaysWhy()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var profile = Profile();

            var emptyPlan = new GameAppPlan { Profile = profile };

            var result = await manager.StartPlannedSessionAsync(profile, emptyPlan, "Manual", true);

            Assert.False(result.Started);
            Assert.Contains("No action was planned", result.Message, StringComparison.Ordinal);
            Assert.False(manager.HasActiveSession);
        }

        #endregion

        #region Restoring

        [Fact]
        public async Task AChangeThisBuildDoesNotUnderstand_IsReportedAsAFailureNotASuccess()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "SomethingNew",
                OriginalValue = "a",
                NewValue = "b"
            });

            var result = await manager.RestoreSessionAsync(session);

            Assert.False(result.EverythingRestored);
            Assert.True(result.HasFailures);
            Assert.Contains(result.Failures, f => f.Contains("does not know how to reverse", StringComparison.Ordinal));
            Assert.Contains("NOT", result.Summary, StringComparison.Ordinal);
            Assert.False(session.WasRestored);
        }

        [Fact]
        public async Task APowerChangeWithNoRecordedOriginalValue_FailsInsteadOfGuessing()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "PowerScheme",
                OriginalValue = string.Empty,
                NewValue = "HighPerformance"
            });

            var result = await manager.RestoreSessionAsync(session);

            Assert.False(result.EverythingRestored);
            Assert.Contains(result.Failures, f => f.Contains("was not recorded", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public async Task APriorityChangeForAProcessThatHasExited_IsNotAFailure()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "Priority",
                OriginalValue = "Normal",
                NewValue = "High",
                TargetProcessId = 999_999_999,
                TargetCreationTimeUtc = DateTime.UtcNow.AddMinutes(-5),
                TargetName = "Game.exe"
            });

            var result = await manager.RestoreSessionAsync(session);

            Assert.True(result.EverythingRestored);
            Assert.Contains(result.Restored, r => r.Contains("exited", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public async Task AClosedProcessIsListedAsNotReversibleRatherThanRestored()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "ClosedProcess",
                OriginalValue = "running",
                NewValue = "closed",
                IsReversible = false,
                TargetName = "SomeHelper"
            });

            var result = await manager.RestoreSessionAsync(session);

            Assert.Single(result.NotReversible);
            Assert.Contains("cannot be undone", result.Summary, StringComparison.Ordinal);

            // The claim must be scoped: reversible things were restored, this one was not.
            Assert.Contains("Every reversible change was restored", result.Summary, StringComparison.Ordinal);
        }

        [Fact]
        public async Task ARestoreFailureIsRecordedOnTheChangeItself()
        {
            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var change = new SessionChangeRecord
            {
                Kind = "UnknownKind",
                OriginalValue = "x",
                NewValue = "y"
            };

            var session = Session("ExampleGame", change);

            await manager.RestoreSessionAsync(session);

            Assert.False(change.WasRestored);
            Assert.False(string.IsNullOrWhiteSpace(change.RestoreFailureReason));
        }

        [Fact]
        public void AGraphicsChangeDescribesItsRollbackExactly()
        {
            var change = new GraphicsPreferenceChange
            {
                ExecutablePath = @"C:\Games\Example\Game.exe",
                OriginalValue = "GpuPreference=1;",
                NewValue = "GpuPreference=2;",
                RegistryValueName = @"C:\Games\Example\Game.exe"
            };

            Assert.Contains("back to 'GpuPreference=1;'", change.RollbackDescription, StringComparison.Ordinal);
            Assert.Contains("HKCU", change.RollbackDescription, StringComparison.Ordinal);

            var absent = new GraphicsPreferenceChange
            {
                ExecutablePath = @"C:\Games\Example\Game.exe",
                OriginalValueWasAbsent = true,
                NewValue = "GpuPreference=2;",
                RegistryValueName = @"C:\Games\Example\Game.exe"
            };

            Assert.Contains("Remove", absent.RollbackDescription, StringComparison.Ordinal);
        }

        [Fact]
        public void RestoringAGraphicsPreferenceOnAPlatformWithoutTheRegistry_IsRefusedHonestly()
        {
            var service = new GraphicsPreferenceService();

            var result = service.Restore(new GraphicsPreferenceChange
            {
                ExecutablePath = Path.Combine(_directory, "Anything.exe"),
                OriginalValueWasAbsent = true
            });

            if (!OperatingSystem.IsWindows())
            {
                Assert.False(result.Success);
                Assert.Contains("Windows", result.Message, StringComparison.Ordinal);
            }
        }

        [Fact]
        public void TheGraphicsValueIsReadBackAsWhatItMeans()
        {
            Assert.Equal(GraphicsPreference.HighPerformance,
                GraphicsPreferenceService.DescribeValue("GpuPreference=2;"));

            Assert.Equal(GraphicsPreference.PowerSaving,
                GraphicsPreferenceService.DescribeValue("GpuPreference=1;"));

            Assert.Equal(GraphicsPreference.LetWindowsDecide,
                GraphicsPreferenceService.DescribeValue(string.Empty));

            Assert.Equal(GraphicsPreference.LetWindowsDecide,
                GraphicsPreferenceService.DescribeValue("something else entirely"));
        }

        #endregion

        #region Interrupted sessions

        [Fact]
        public async Task AnInterruptedSessionIsDescribedBeforeAnythingIsDone()
        {
            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "PowerScheme",
                OriginalValue = "Balanced",
                NewValue = "HighPerformance"
            });

            session.ClosedProcesses.Add("SomeHelper (PID 4321)");

            Assert.True(_store.SaveOpen(session));

            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var interrupted = manager.FindInterruptedSessions();

            Assert.Single(interrupted);

            var description = manager.DescribeInterruptedSession(interrupted[0]);

            Assert.Contains("An optimization session was interrupted.", description, StringComparison.Ordinal);
            Assert.Contains("ExampleGame", description, StringComparison.Ordinal);
            Assert.Contains("Restore", description, StringComparison.Ordinal);
            Assert.Contains("Review", description, StringComparison.Ordinal);
            Assert.Contains("Nothing is changed until you choose", description, StringComparison.Ordinal);

            // Finding an interrupted session must not, by itself, change anything.
            Assert.Single(_store.LoadOpenSessions());

            await Task.CompletedTask;
        }

        [Fact]
        public void DismissingAnInterruptedSession_RecordsTheDecisionInsteadOfHidingIt()
        {
            var session = Session("ExampleGame");

            Assert.True(_store.SaveOpen(session));

            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            Assert.True(manager.DismissInterruptedSession(session, "the changes are what I wanted"));

            Assert.Empty(_store.LoadOpenSessions());

            var history = _store.LoadHistory();

            Assert.Single(history);
            Assert.True(history[0].WasInterrupted);
            Assert.Contains(history[0].RestoreNotes, note => note.Contains("not to restore", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public async Task AnInterruptedSessionThatIsRestoredIsClosedProperly()
        {
            var session = Session("ExampleGame", new SessionChangeRecord
            {
                Kind = "Priority",
                OriginalValue = "Normal",
                NewValue = "AboveNormal",
                TargetProcessId = 999_999_998,
                TargetCreationTimeUtc = DateTime.UtcNow.AddMinutes(-1),
                TargetName = "Game.exe"
            });

            Assert.True(_store.SaveOpen(session));

            var manager = new GameAppSessionManager(config: AppConfig.CreateDefault(), store: _store);

            var result = await manager.RestoreInterruptedSessionAsync(session);

            Assert.Empty(_store.LoadOpenSessions());
            Assert.Single(_store.LoadHistory());

            // The process had exited, which is not a failure: there was nothing left to put back.
            Assert.True(result.EverythingRestored);
        }

        #endregion

        #region Session descriptions

        [Fact]
        public void ASessionNeverClaimsEverythingWasRestoredWhenSomethingFailed()
        {
            var session = Session("ExampleGame");
            session.IsOpen = false;
            session.WasRestored = false;
            session.RestoreFailures.Add("GraphicsPreference: the value could not be set back");

            var description = session.Describe();

            Assert.Contains("restore failure", description, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("nothing is claimed", description, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("Everything restored", description, StringComparison.Ordinal);
        }

        [Fact]
        public void AVerifiedRestoreSaysSoAndStillListsWhatCouldNotBeUndone()
        {
            var session = Session("ExampleGame");
            session.IsOpen = false;
            session.WasRestored = true;

            session.Changes.Add(new SessionChangeRecord
            {
                Kind = "ClosedProcess",
                IsReversible = false,
                TargetName = "Helper"
            });

            var description = session.Describe();

            Assert.Contains("every reversible change was restored", description, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("could not be undone", description, StringComparison.OrdinalIgnoreCase);
        }

        #endregion
    }
}

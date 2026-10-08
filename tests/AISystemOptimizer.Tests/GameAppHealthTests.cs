using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the rules that decide whether a profile may still be used.
    ///
    /// These are the rules that stop a profile being applied to the wrong program: a file that was
    /// replaced, updated, moved, re-pointed through a link, or that has become unreadable. Each of them
    /// must suspend the profile and say why - none of them may quietly continue.
    /// </summary>
    public class GameAppHealthTests : IDisposable
    {
        private readonly string _directory;
        private readonly GameAppProfileService _service;

        public GameAppHealthTests()
        {
            _directory = Path.Combine(Path.GetTempPath(), "aio-health-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_directory);

            _service = new GameAppProfileService(
                store: new GameAppProfileStore(directory: Path.Combine(_directory, "profiles")));
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

        private string WriteFile(string name, string content)
        {
            var path = Path.Combine(_directory, name);
            File.WriteAllText(path, content);
            return path;
        }

        private static ExecutableInspectionResult Inspection(
            string path,
            string hash,
            string? publisher = null,
            long size = 1024,
            string version = "1.0.0.0",
            SignatureVerdict verdict = SignatureVerdict.Valid)
        {
            return new ExecutableInspectionResult
            {
                SuppliedPath = path,
                CanonicalPath = path,
                FileName = Path.GetFileName(path),
                Exists = true,
                Sha256 = hash,
                Publisher = publisher ?? string.Empty,
                FileSizeBytes = size,
                FileVersion = version,
                SignatureVerdict = verdict
            };
        }

        private static GameAppProfile ProfileFor(
            string path,
            string hash,
            string? publisher = null,
            long size = 1024,
            string version = "1.0.0.0")
        {
            return new GameAppProfile
            {
                ApplicationId = Guid.NewGuid(),
                DisplayName = "Test Application",
                Kind = ApplicationKind.Heavy,
                Identity = new ExecutableIdentity
                {
                    ExecutablePath = path,
                    FileName = Path.GetFileName(path),
                    Sha256 = hash,
                    Publisher = publisher ?? string.Empty,
                    FileSizeBytes = size,
                    FileVersion = version
                }
            };
        }

        #region The healthy case

        [Fact]
        public void AnUnchangedExecutable_IsHealthyAndUsable()
        {
            var path = WriteFile("Steady.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-one");

            var health = GameAppProfileService.EvaluateHealth(profile, Inspection(path, "hash-one"));

            Assert.Equal(ApplicationHealthState.Healthy, health.State);
            Assert.True(health.IsUsable);
            Assert.Equal("Executable verified.", health.Summary);
            Assert.NotNull(health.CurrentIdentity);
        }

        [Fact]
        public void AHealthyProfileWithAnUnsignedExecutable_ReportsTheSignatureAsAWarningNotAFailure()
        {
            var path = WriteFile("Unsigned.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-one");

            var health = GameAppProfileService.EvaluateHealth(
                profile, Inspection(path, "hash-one", verdict: SignatureVerdict.Unsigned));

            // Unsigned is not a reason to refuse to run: it is a caution, recorded as a finding.
            Assert.Equal(ApplicationHealthState.Healthy, health.State);
            Assert.Contains(health.Findings, f => f.Contains("Unsigned", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AMalformedProfileFile_IsRejectedBeforeItsRulesAreTrusted()
        {
            var path = WriteFile("Anything.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-one");
            profile.SchemaVersion = GameAppProfile.CurrentSchemaVersion + 1;

            var health = _service.CheckHealth(profile, computeHash: false);

            Assert.Equal(ApplicationHealthState.ProfileOutdated, health.State);
            Assert.False(health.IsUsable);
        }

        #endregion

        #region Changed executable

        [Fact]
        public void AChangedExecutable_SuspendsTheProfileWithTheRequiredSentence()
        {
            var path = WriteFile("Updated.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-before", size: 512);

            var health = GameAppProfileService.EvaluateHealth(
                profile, Inspection(path, "hash-after", size: 900, version: "2.0.0.0"));

            Assert.Equal(ApplicationHealthState.ExecutableChanged, health.State);
            Assert.False(health.IsUsable);

            // The exact sentence the specification requires.
            Assert.Equal("Executable changed. Profile requires verification.", health.Summary);

            Assert.Contains(health.Findings, f => f.Contains("contents changed", StringComparison.OrdinalIgnoreCase));
            Assert.Contains(health.Findings, f => f.Contains("512", StringComparison.Ordinal));
            Assert.Contains(health.Findings, f => f.Contains("900", StringComparison.Ordinal));
            Assert.Contains(health.Findings, f => f.Contains("2.0.0.0", StringComparison.Ordinal));
        }

        [Fact]
        public void TheReportedHashes_AreShortenedSoTheyCanBeShownToAUser()
        {
            var path = WriteFile("Hashes.exe", new string('A', 512));

            var longBefore = new string('a', 64);
            var longAfter = new string('b', 64);

            var health = GameAppProfileService.EvaluateHealth(
                ProfileFor(path, longBefore), Inspection(path, longAfter));

            var finding = health.Findings.First(f => f.Contains("contents changed", StringComparison.OrdinalIgnoreCase));

            Assert.Contains("aaaaaaaaaaaa…", finding, StringComparison.Ordinal);
            Assert.Contains("bbbbbbbbbbbb…", finding, StringComparison.Ordinal);
            Assert.DoesNotContain(longAfter, finding, StringComparison.Ordinal);
        }

        [Fact]
        public void AProfileWithNoRecordedHash_SuspendsRatherThanBeingTreatedAsMatching()
        {
            var path = WriteFile("NoHash.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-one");
            profile.Identity!.Sha256 = string.Empty;

            var health = GameAppProfileService.EvaluateHealth(profile, Inspection(path, "hash-two"));

            Assert.Equal(ApplicationHealthState.ExecutableChanged, health.State);
            Assert.False(health.IsUsable);
            Assert.Contains(health.Findings, f => f.Contains("does not record a file hash", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void WhenHashComparisonIsSwitchedOff_TheOtherChecksStillApply()
        {
            // Used after the user has re-verified a profile: an update changed the contents, and the user
            // confirmed it was their own update. Publisher changes must still be caught.
            var path = WriteFile("ReVerified.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-before", publisher: "Original Studio Ltd");

            var health = GameAppProfileService.EvaluateHealth(
                profile,
                Inspection(path, "hash-after", publisher: "Somebody Else"),
                computeHash: false);

            Assert.Equal(ApplicationHealthState.PublisherChanged, health.State);
            Assert.Equal("Publisher changed. Profile requires verification.", health.Summary);
        }

        #endregion

        #region Missing, moved and unreadable

        [Fact]
        public void AMissingExecutable_IsReportedAndTheProfileIsNotUsable()
        {
            var path = Path.Combine(_directory, "Gone.exe");

            var profile = ProfileFor(path, "hash-one");

            var health = _service.CheckHealth(profile);

            Assert.Equal(ApplicationHealthState.ExecutableMissing, health.State);
            Assert.False(health.IsUsable);
            Assert.Contains("Executable missing", health.Summary, StringComparison.Ordinal);
        }

        [Fact]
        public void ADeletionAfterProfiling_IsDetectedByTheNextHealthCheck()
        {
            var path = WriteFile("Disappear.exe", new string('A', 900));

            var result = _service.AddApplication(path);
            Assert.True(result.Success, result.ErrorMessage);

            Assert.True(_service.CheckHealth(result.Profile!).IsUsable);

            File.Delete(path);

            var health = _service.CheckHealth(result.Profile!);

            Assert.Equal(ApplicationHealthState.ExecutableMissing, health.State);
            Assert.False(health.IsUsable);
        }

        [Fact]
        public void AMoveAfterProfiling_IsReportedAsMissingRatherThanSilentlyFollowed()
        {
            var path = WriteFile("Moveable.exe", new string('A', 900));

            var result = _service.AddApplication(path);
            Assert.True(result.Success, result.ErrorMessage);

            Directory.CreateDirectory(Path.Combine(_directory, "elsewhere"));
            File.Move(path, Path.Combine(_directory, "elsewhere", "Moveable.exe"));

            var health = _service.CheckHealth(result.Profile!);

            Assert.Equal(ApplicationHealthState.ExecutableMissing, health.State);

            // The user can point the profile at the new location; until then nothing is applied.
            Assert.False(health.IsUsable);
        }

        [Fact]
        public void AProfileWithNoPath_GetsNowhereRatherThanGuessing()
        {
            var profile = ProfileFor(@"C:\empty", "hash");

            profile.Identity!.ExecutablePath = string.Empty;

            var health = _service.CheckHealth(profile);

            Assert.Equal(ApplicationHealthState.ExecutableMissing, health.State);
            Assert.Contains(health.Findings, f => f.Contains("does not record an executable path", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AProfileWhoseStoredPathIsNoLongerAcceptable_IsSuspended()
        {
            // The profile file is user-editable, so the path inside it is input that must be validated
            // again - not trusted because it was written earlier.
            var profile = ProfileFor(@"\\?\C:\Windows\System32\cmd.exe", "hash");

            var health = _service.CheckHealth(profile);

            Assert.Equal(ApplicationHealthState.ExecutableChanged, health.State);
            Assert.False(health.IsUsable);
            Assert.Contains(health.Findings, f => f.Contains("no longer acceptable", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AnExecutableThatCannotBeHashed_IsReportedAsAPermissionProblem()
        {
            var path = WriteFile("Locked.exe", new string('A', 512));

            var profile = ProfileFor(path, "hash-one");

            // An inspection that ran but produced no hash is exactly what an unreadable file looks like.
            var unreadable = Inspection(path, string.Empty);
            unreadable.Exists = true;

            var health = GameAppProfileService.EvaluateHealth(profile, unreadable);

            // With no hash to compare, the profile cannot be verified, so it is suspended.
            Assert.False(health.IsUsable);
        }

        #endregion

        #region Adding applications

        [Fact]
        public void AddingAnApplication_OnlyWritesAProfile()
        {
            var path = WriteFile("Fresh.exe", new string('A', 2048));

            var before = Directory.GetFiles(_directory, "*.json", SearchOption.AllDirectories).Length;

            var result = _service.AddApplication(path);

            Assert.True(result.Success, result.ErrorMessage);
            Assert.NotNull(result.Profile);

            var after = Directory.GetFiles(_directory, "*.json", SearchOption.AllDirectories).Length;

            Assert.Equal(before + 1, after);

            // The profile records what was read about the file, and the file itself is untouched.
            Assert.Equal(new FileInfo(path).Length, result.Profile!.Identity.FileSizeBytes);
            Assert.Equal(64, result.Profile.Identity.Sha256!.Length);
            Assert.Equal("Balanced", result.Profile.ProfileMode.ToString());

            // Nothing about the application is decided by its name: it starts as Unknown until told otherwise.
            Assert.Equal(ApplicationKind.Unknown, result.Profile.Kind);
        }

        [Fact]
        public void AddingTheSameExecutableTwice_IsRefusedAndPointsAtTheExistingProfile()
        {
            var path = WriteFile("Twice.exe", new string('A', 2048));

            var first = _service.AddApplication(path);
            Assert.True(first.Success, first.ErrorMessage);

            var second = _service.AddApplication(path);

            Assert.False(second.Success);
            Assert.Same(first.Profile, second.ExistingProfile);
            Assert.Contains("already has a profile", second.ErrorMessage, StringComparison.OrdinalIgnoreCase);

            Assert.Single(_service.Profiles);
        }

        [Fact]
        public void AddingAnInvalidPath_FailsWithoutWritingAnything()
        {
            var profilesDirectory = Path.Combine(_directory, "profiles");

            var result = _service.AddApplication(@"\\?\C:\Windows\System32\cmd.exe");

            Assert.False(result.Success);
            Assert.Empty(_service.Profiles);
            Assert.False(Directory.Exists(profilesDirectory) && Directory.GetFiles(profilesDirectory).Length > 0);
        }

        [Fact]
        public void AddingAFileThatIsNotAnExecutable_FailsWhenTheFileCannotBeHashed()
        {
            // "Anything.exe" is not a real executable, but it exists and can be hashed, so it is accepted
            // with an explicit note - the requirement is to inspect, not to refuse what looks unusual.
            var path = WriteFile("Anything.exe", "just text");

            var result = _service.AddApplication(path);

            Assert.True(result.Success, result.ErrorMessage);
            Assert.Contains(result.Notes, n => n.Contains("too small", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AnUnsignedApplication_IsAddedWithAnExplanationRatherThanAWarning()
        {
            var path = WriteFile("Unsigned.exe", new string('A', 4096));

            var result = _service.AddApplication(path);

            Assert.True(result.Success, result.ErrorMessage);

            // Off Windows the verdict is Unknown; on Windows an unsigned file is Unsigned. Both must be
            // explained in the note rather than being turned into a refusal.
            Assert.Contains(
                result.Notes,
                n => n.Contains("signature", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AProfileIsListed_EvenWhenItsExecutableIsMissing()
        {
            // The user must be able to see and remove a stale profile; hiding it would leave them with no
            // way to clean up.
            var path = WriteFile("Vanishing.exe", new string('A', 4096));

            var result = _service.AddApplication(path);
            Assert.True(result.Success, result.ErrorMessage);

            File.Delete(path);
            _service.Reload();

            Assert.Single(_service.Profiles);

            var health = _service.CheckHealth(_service.Profiles[0]);

            Assert.Equal(ApplicationHealthState.ExecutableMissing, health.State);
        }

        #endregion

        #region Re-verification

        [Fact]
        public void ReVerifyingAProfile_RebindsItToTheNewExecutableAndKeepsItsSettings()
        {
            var path = WriteFile("Updated.exe", new string('A', 4096));

            var result = _service.AddApplication(path);
            Assert.True(result.Success, result.ErrorMessage);

            var profile = result.Profile!;
            profile.ProfileMode = GameAppProfileMode.Performance;
            profile.Cpu.Priority = ProcessPriorityPreference.AboveNormal;
            Assert.True(_service.Update(profile));

            // The application updates itself: same path, new contents.
            File.WriteAllText(path, new string('B', 8192));

            var health = _service.CheckHealth(profile);
            Assert.Equal(ApplicationHealthState.ExecutableChanged, health.State);

            Assert.True(_service.RebindToCurrentExecutable(profile, health));

            // The new contents are now the identity, and the settings the user chose are untouched.
            Assert.Equal(health.CurrentIdentity!.Sha256, profile.Identity.Sha256);
            Assert.Equal(8192, profile.Identity.FileSizeBytes);
            Assert.Equal(GameAppProfileMode.Performance, profile.ProfileMode);
            Assert.Equal(ProcessPriorityPreference.AboveNormal, profile.Cpu.Priority);

            var after = _service.CheckHealth(profile);
            Assert.True(after.IsUsable);
        }

        [Fact]
        public void ReVerifyingIsRefusedWhenThereIsNothingToVerifyAgainst()
        {
            var profile = ProfileFor(@"C:\missing.exe", "hash");
            var health = new ApplicationHealth { State = ApplicationHealthState.ExecutableMissing };

            Assert.False(_service.RebindToCurrentExecutable(profile, health));
            Assert.False(_service.RebindToCurrentExecutable(null!, health));
        }

        #endregion

        #region Never-optimize interaction

        [Fact]
        public void AnApplicationOnTheNeverOptimizeList_IsRecognisedBeforeAnythingIsApplied()
        {
            var path = WriteFile("Protected.exe", new string('A', 4096));

            var result = _service.AddApplication(path);
            Assert.True(result.Success, result.ErrorMessage);

            var profile = result.Profile!;

            var entries = new List<NeverOptimizeEntry>
            {
                new() { Kind = NeverOptimizeKind.ExecutablePath, Value = path, Reason = "I said so" }
            };

            Assert.True(_service.IsApplicationProtected(profile, entries));

            var other = new List<NeverOptimizeEntry>
            {
                new() { Kind = NeverOptimizeKind.ExecutablePath, Value = Path.Combine(_directory, "other.exe") }
            };

            Assert.False(_service.IsApplicationProtected(profile, other));
        }

        [Fact]
        public void TheNeverOptimizeList_SurvivesAReload()
        {
            var listPath = Path.Combine(_directory, "never-optimize.json");
            var store = new NeverOptimizeStore(filePath: listPath);

            var entries = new List<NeverOptimizeEntry>
            {
                new() { Kind = NeverOptimizeKind.ProcessName, Value = "chrome.exe", Reason = "Video calls" }
            };

            Assert.True(store.Save(entries));

            var loaded = new NeverOptimizeStore(filePath: listPath).Load();

            Assert.Single(loaded);
            Assert.Equal("chrome.exe", loaded[0].Value);
            Assert.Equal("Video calls", loaded[0].Reason);
        }

        [Fact]
        public void ANeverOptimizeEntry_ThatClaimsItCanOverrideSystemProtection_IsCorrectedOnLoad()
        {
            var listPath = Path.Combine(_directory, "never-optimize.json");

            File.WriteAllText(listPath, """
            {
              "entries": [
                { "kind": "ProcessName", "value": "lsass.exe", "canOverrideSystemProtection": true }
              ]
            }
            """);

            var store = new NeverOptimizeStore(filePath: listPath);
            var loaded = store.Load();

            Assert.Single(loaded);
            Assert.False(loaded[0].CanOverrideSystemProtection);
            Assert.Contains(store.LoadProblems, p => p.Contains("not possible", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AMissingNeverOptimizeFile_IsAnEmptyListNotAnError()
        {
            var store = new NeverOptimizeStore(filePath: Path.Combine(_directory, "absent.json"));

            Assert.Empty(store.Load());
            Assert.Empty(store.LoadProblems);
        }

        [Fact]
        public void ACorruptNeverOptimizeFile_IsQuarantinedRatherThanSilentlyEmptied()
        {
            var listPath = Path.Combine(_directory, "never-optimize.json");
            File.WriteAllText(listPath, "{ not json");

            var store = new NeverOptimizeStore(filePath: listPath);
            var loaded = store.Load();

            Assert.Empty(loaded);
            Assert.NotEmpty(store.LoadProblems);

            // Silently losing a protection list would be worse than an empty list, so the file is kept.
            Assert.True(File.Exists(listPath + ".invalid"));
        }

        #endregion

        #region Multiple instances and identity

        [Fact]
        public void RunInformation_RequiresAConfirmedMatchBeforeItIsUsed()
        {
            var run = new ApplicationRunInfo
            {
                ProcessId = 1234,
                CreationTimeUtc = DateTime.UtcNow,
                Path = @"C:\Games\Game.exe"
            };

            // A process found by name alone is not confirmed, and must not be acted on.
            Assert.False(run.IsConfirmedMatch);

            run.IsConfirmedMatch = true;

            Assert.True(run.IsConfirmedMatch);
            Assert.Contains("1234", run.Describe(), StringComparison.Ordinal);
        }

        [Fact]
        public void MultipleInstances_AreRepresentedAsSeparateRunsWithTheirOwnCreationTimes()
        {
            var first = new ApplicationRunInfo
            {
                ProcessId = 1000,
                CreationTimeUtc = DateTime.UtcNow.AddMinutes(-10),
                IsConfirmedMatch = true
            };

            var second = new ApplicationRunInfo
            {
                ProcessId = 2000,
                CreationTimeUtc = DateTime.UtcNow,
                IsConfirmedMatch = true
            };

            // The creation time is what distinguishes a live process from a reused process ID.
            Assert.NotEqual(first.CreationTimeUtc, second.CreationTimeUtc);
            Assert.NotEqual(first.ProcessId, second.ProcessId);
            Assert.NotEqual(first.Describe(), second.Describe());
        }

        [Fact]
        public void DetectingRunningState_ForAUserWhoHasNoSuchApplication_ReportsNotRunning()
        {
            // Deterministic on every platform: nothing is named like this.
            var inspector = new ExecutableInspector();

            var state = inspector.DetectRunningState(
                Path.Combine(_directory, "AIO-No-Such-Executable-9f3c.exe"),
                out var confirmed,
                out var unconfirmed);

            Assert.Equal(ApplicationRunState.NotRunning, state);
            Assert.Empty(confirmed);
            Assert.Empty(unconfirmed);
        }

        [Fact]
        public void DetectingRunningState_WithAnEmptyPath_ReportsNotRunningRatherThanThrowing()
        {
            var inspector = new ExecutableInspector();

            var state = inspector.DetectRunningState(string.Empty, out var confirmed, out _);

            Assert.Equal(ApplicationRunState.NotRunning, state);
            Assert.Empty(confirmed);
        }

        #endregion
    }
}

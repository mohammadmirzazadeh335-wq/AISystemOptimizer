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
    /// Tests for the Game &amp; App Optimizer's profile model, storage and identity rules.
    ///
    /// Everything here is pure file and object logic, so it runs anywhere. The parts that need Windows -
    /// reading a real PE header, verifying a real signature, finding a running process - are covered by
    /// the compiled smoke harness on the target machine, not by pretending here.
    /// </summary>
    public class GameAppProfileTests : IDisposable
    {
        private readonly string _directory;
        private readonly GameAppProfileStore _store;

        public GameAppProfileTests()
        {
            _directory = Path.Combine(Path.GetTempPath(), "aio-profiles-" + Guid.NewGuid().ToString("N"));
            _store = new GameAppProfileStore(directory: _directory);
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
                // A leftover temp directory must never fail a test run.
            }
        }

        private static GameAppProfile MakeProfile(string path = @"C:\Games\ExampleGame\Game.exe", string hash = "abc123")
        {
            return new GameAppProfile
            {
                ApplicationId = Guid.NewGuid(),
                DisplayName = "ExampleGame",
                Kind = ApplicationKind.Game,
                ProfileMode = GameAppProfileMode.Balanced,
                Identity = new ExecutableIdentity
                {
                    ExecutablePath = path,
                    FileName = Path.GetFileName(path),
                    Sha256 = hash,
                    Publisher = "Example Studio",
                    ProductName = "Example Game",
                    FileVersion = "1.0.0.0",
                    FileSizeBytes = 12345678
                }
            };
        }

        #region Identity

        [Fact]
        public void AProfileIdentity_IsNotJustAFileName()
        {
            // Two different programs can share a file name. The identity must carry more than the name,
            // or a profile would follow the wrong executable.
            var identity = new ExecutableIdentity();

            Assert.False(identity.IsUsable);

            identity.ExecutablePath = @"C:\Games\A\Game.exe";

            // A path without a hash is still not an identity: the file at that path can be replaced.
            Assert.False(identity.IsUsable);

            identity.Sha256 = "deadbeef";

            Assert.True(identity.IsUsable);
        }

        [Fact]
        public void TwoProfilesWithTheSameFileName_AreDifferentProfiles()
        {
            var first = MakeProfile(@"C:\Games\One\Game.exe", "hash-one");
            var second = MakeProfile(@"C:\Games\Two\Game.exe", "hash-two");

            Assert.NotEqual(first.ApplicationId, second.ApplicationId);
            Assert.NotEqual(first.Identity.Sha256, second.Identity.Sha256);
        }

        [Fact]
        public void FindByExecutable_MatchesThePathFirstAndThenTheHash()
        {
            var profile = MakeProfile(@"C:\Games\One\Game.exe", "hash-one");
            var profiles = new List<GameAppProfile> { profile };

            // Exact path, including a different separator and mixed case.
            Assert.Same(profile, _store.FindByExecutable(profiles, @"c:/games/one/game.exe"));

            // Same contents at a new location (the user moved the installation).
            Assert.Same(profile, _store.FindByExecutable(profiles, @"D:\Elsewhere\Game.exe", "HASH-ONE"));

            // A different program with the same name and different contents is not this profile.
            Assert.Null(_store.FindByExecutable(profiles, @"D:\Elsewhere\Game.exe", "hash-two"));
        }

        [Fact]
        public void IsDuplicate_RefusesTheSameExecutableTwice()
        {
            var profile = MakeProfile(@"C:\Games\One\Game.exe", "hash-one");
            var profiles = new List<GameAppProfile> { profile };

            Assert.True(_store.IsDuplicate(profiles, @"C:\Games\One\Game.exe"));
            Assert.False(_store.IsDuplicate(profiles, @"C:\Games\Two\Other.exe", "other-hash"));
        }

        #endregion

        #region Persistence

        [Fact]
        public void AProfile_RoundTripsThroughStorage()
        {
            var profile = MakeProfile();
            profile.Cpu.Priority = ProcessPriorityPreference.AboveNormal;
            profile.Power.ModeWhileRunning = PowerPreference.HighPerformance;
            profile.Gpu.GraphicsPreference = GraphicsPreference.HighPerformance;
            profile.Behavior.AutoOptimize = true;

            profile.BackgroundRules.Add(new BackgroundProcessRule
            {
                Target = "chrome",
                Decision = BackgroundProcessDecision.AllowOptimization,
                Reason = "The user closed it by hand before"
            });

            Assert.True(_store.Save(profile));

            var reloaded = _store.LoadAll();

            Assert.Single(reloaded);

            var loaded = reloaded[0];

            Assert.Equal(profile.ApplicationId, loaded.ApplicationId);
            Assert.Equal(profile.Identity.Sha256, loaded.Identity.Sha256);
            Assert.Equal(ProcessPriorityPreference.AboveNormal, loaded.Cpu.Priority);
            Assert.Equal(PowerPreference.HighPerformance, loaded.Power.ModeWhileRunning);
            Assert.Equal(GraphicsPreference.HighPerformance, loaded.Gpu.GraphicsPreference);
            Assert.True(loaded.Behavior.AutoOptimize);
            Assert.Single(loaded.BackgroundRules);
            Assert.Equal("chrome", loaded.BackgroundRules[0].Target);
            Assert.Equal(BackgroundProcessDecision.AllowOptimization, loaded.BackgroundRules[0].Decision);
        }

        [Fact]
        public void EnumValues_ArePersistedAsReadableNames()
        {
            // A profile file a human may inspect must not depend on enum ordinals, which change silently
            // when a member is inserted.
            var profile = MakeProfile();
            profile.ProfileMode = GameAppProfileMode.Performance;

            Assert.True(_store.Save(profile));

            var json = File.ReadAllText(_store.FilePathFor(profile));

            Assert.Contains("\"Performance\"", json, StringComparison.Ordinal);
            Assert.Contains("\"profileMode\"", json, StringComparison.Ordinal);

            // And a name written by hand is understood.
            var text = json.Replace("\"Performance\"", "\"Safe\"");
            File.WriteAllText(_store.FilePathFor(profile), text);

            var reloaded = _store.LoadAll();
            Assert.Equal(GameAppProfileMode.Safe, reloaded[0].ProfileMode);
        }

        [Fact]
        public void TheProfileFileName_IsNotDerivedFromTheExecutable()
        {
            // A profile must survive the executable being renamed or moved, so the health check can report
            // the change instead of the profile disappearing.
            var profile = MakeProfile(@"C:\Games\ExampleGame\Game.exe");

            Assert.Equal($"{profile.ApplicationId:D}.json", Path.GetFileName(_store.FilePathFor(profile)));
            Assert.DoesNotContain("Game", Path.GetFileName(_store.FilePathFor(profile)));
        }

        [Fact]
        public void AProfileWithoutAnIdentifier_IsRefused()
        {
            var profile = MakeProfile();
            profile.ApplicationId = Guid.Empty;

            Assert.False(_store.Save(profile));
        }

        [Fact]
        public void RemovingAProfile_RemovesItsFilesAndNothingElse()
        {
            var profile = MakeProfile();
            profile.TrimHistory(50, 50);

            Assert.True(_store.Save(profile));

            // Save once more so a backup exists as well.
            Assert.True(_store.Save(profile));

            var path = _store.FilePathFor(profile);
            Assert.True(File.Exists(path));

            Assert.True(_store.Delete(profile));
            Assert.False(File.Exists(path));
            Assert.False(File.Exists(path + ".bak"));
        }

        [Fact]
        public void AddingAProfile_TouchesNothingOutsideItsOwnDirectory()
        {
            // This is the "no global side effects" requirement, asserted as far as it can be off Windows:
            // the store writes inside its own directory and nowhere else.
            var before = Directory.Exists(_directory) ? Directory.GetFiles(_directory).Length : 0;

            var profile = MakeProfile();
            Assert.True(_store.Save(profile));

            var files = Directory.GetFiles(_directory);

            Assert.Equal(before + 1, files.Length);
            Assert.All(files, f => Assert.StartsWith(_directory, Path.GetFullPath(f), StringComparison.Ordinal));
        }

        #endregion

        #region Corrupt and hostile files

        [Fact]
        public void ACorruptProfileFile_IsQuarantinedAndTheOthersStillLoad()
        {
            var good = MakeProfile();
            Assert.True(_store.Save(good));

            var bad = Path.Combine(_directory, Guid.NewGuid().ToString("D") + ".json");
            File.WriteAllText(bad, "{ this is not json ###");

            var loaded = _store.LoadAll();

            Assert.Single(loaded);
            Assert.Equal(good.ApplicationId, loaded[0].ApplicationId);

            // The damaged file is kept, with a reason, rather than deleted.
            Assert.False(File.Exists(bad));
            Assert.True(File.Exists(bad + ".invalid"));
            Assert.True(File.Exists(bad + ".invalid.reason.txt"));

            Assert.Equal(ProfileLoadOutcome.LoadedWithProblems, _store.LastOutcome);
            Assert.NotEmpty(_store.LoadProblems);
        }

        [Fact]
        public void ACorruptFile_IsRecoveredFromTheBackupWhenOneExists()
        {
            var profile = MakeProfile();
            profile.DisplayName = "BeforeDamage";

            Assert.True(_store.Save(profile));
            Assert.True(_store.Save(profile)); // creates the .bak

            var path = _store.FilePathFor(profile);
            File.WriteAllText(path, "not json at all");

            var loaded = _store.LoadAll();

            Assert.Single(loaded);
            Assert.Equal(profile.ApplicationId, loaded[0].ApplicationId);
            Assert.Equal("BeforeDamage", loaded[0].DisplayName);
            Assert.True(File.Exists(path + ".invalid"));
        }

        [Fact]
        public void AProfileWithoutAnIdentifierOnDisk_IsRejected()
        {
            var path = Path.Combine(_directory, "no-id.json");

            Directory.CreateDirectory(_directory);
            File.WriteAllText(path, "{ \"displayName\": \"Nameless\", \"applicationId\": \"00000000-0000-0000-0000-000000000000\" }");

            var loaded = _store.LoadAll();

            Assert.Empty(loaded);
            Assert.Equal(ProfileLoadOutcome.LoadedWithProblems, _store.LastOutcome);
        }

        [Fact]
        public void AnOversizedProfileFile_IsRefusedRatherThanRead()
        {
            Directory.CreateDirectory(_directory);

            var path = Path.Combine(_directory, Guid.NewGuid().ToString("D") + ".json");
            File.WriteAllText(path, new string('x', 600 * 1024));

            var loaded = _store.LoadAll();

            Assert.Empty(loaded);
            Assert.Contains(_store.LoadProblems, p => p.Contains("above the", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AnEmptyProfileDirectory_IsNotAnError()
        {
            Assert.Empty(_store.LoadAll());
            Assert.Equal(ProfileLoadOutcome.Empty, _store.LastOutcome);
            Assert.Empty(_store.LoadProblems);
        }

        #endregion

        #region Ranges and guarantees

        [Fact]
        public void OutOfRangeValues_AreClampedAndReported()
        {
            var profile = MakeProfile();

            profile.Ram.MaxBackgroundProcessesPerSession = 5000;
            profile.Ram.MinimumWorkingSetMegabytes = 0;
            profile.SchemaVersion = 99;

            var adjustments = profile.NormalizeToSupportedRanges();

            Assert.Equal(20, profile.Ram.MaxBackgroundProcessesPerSession);
            Assert.Equal(10, profile.Ram.MinimumWorkingSetMegabytes);
            Assert.Equal(GameAppProfile.CurrentSchemaVersion, profile.SchemaVersion);
            Assert.Equal(3, adjustments.Count);
        }

        [Fact]
        public void WarnBeforeDeleting_CannotBeTurnedOffByEditingTheFile()
        {
            var profile = MakeProfile();
            profile.Disk.WarnBeforeDeleting = false;

            var adjustments = profile.NormalizeToSupportedRanges();

            Assert.True(profile.Disk.WarnBeforeDeleting);
            Assert.Contains(adjustments, a => a.Contains("warnBeforeDeleting", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void TheDiskScope_CannotBeWidenedByEditingTheFile()
        {
            var profile = MakeProfile();
            profile.Disk.CleanupScope = (DiskCleanupScope)99;

            var adjustments = profile.NormalizeToSupportedRanges();

            Assert.Equal(DiskCleanupScope.None, profile.Disk.CleanupScope);
            Assert.NotEmpty(adjustments);
        }

        [Fact]
        public void AffinityAndSaveFileGuarantees_AreNotSettable()
        {
            // These are guarantees, not settings, and they have no setter to reach.
            var cpu = new CpuProfileSettings();
            var disk = new DiskProfileSettings();

            Assert.True(cpu.AffinityIsNeverModified);
            Assert.True(disk.SaveFilesAreNeverInScope);

            Assert.Null(typeof(CpuProfileSettings).GetProperty("AffinityIsNeverModified")!.SetMethod);
            Assert.Null(typeof(DiskProfileSettings).GetProperty("SaveFilesAreNeverInScope")!.SetMethod);
        }

        [Fact]
        public void AProfileWithNoDisplayName_GetsOneFromItsMetadata()
        {
            var profile = MakeProfile();
            profile.DisplayName = string.Empty;

            profile.NormalizeToSupportedRanges();

            Assert.Equal("Example Game", profile.DisplayName);
        }

        [Fact]
        public void HistoryIsTrimmedToItsLimit()
        {
            var profile = MakeProfile();

            for (var i = 0; i < 80; i++)
            {
                profile.Benchmarks.Add(new BenchmarkRecord
                {
                    Label = $"run {i}",
                    RecordedAtUtc = DateTime.UtcNow.AddMinutes(-i)
                });
            }

            for (var i = 0; i < 80; i++)
            {
                profile.Sessions.Add(new ProfileSessionSummary { StartedAtUtc = DateTime.UtcNow.AddMinutes(-i) });
            }

            profile.TrimHistory(maxBenchmarks: 10, maxSessions: 5);

            Assert.Equal(10, profile.Benchmarks.Count);
            Assert.Equal(5, profile.Sessions.Count);

            // The newest are kept, not the oldest.
            Assert.Equal("run 0", profile.Benchmarks.Last().Label);
        }

        [Fact]
        public void CloningAProfile_ProducesAnIndependentCopy()
        {
            var profile = MakeProfile();
            profile.BackgroundRules.Add(new BackgroundProcessRule { Target = "chrome" });

            var clone = profile.Clone();

            clone.DisplayName = "Changed";
            clone.BackgroundRules.Clear();

            Assert.Equal("ExampleGame", profile.DisplayName);
            Assert.Single(profile.BackgroundRules);
        }

        #endregion

        #region Never-optimize matching

        [Fact]
        public void NeverOptimizeEntries_MatchTheWayTheySayTheyDo()
        {
            var byName = new NeverOptimizeEntry { Kind = NeverOptimizeKind.ProcessName, Value = "chrome" };
            var byPath = new NeverOptimizeEntry { Kind = NeverOptimizeKind.ExecutablePath, Value = @"C:\Apps\Discord.exe" };
            var byPublisher = new NeverOptimizeEntry { Kind = NeverOptimizeKind.Publisher, Value = "Acme Corp" };
            var byHash = new NeverOptimizeEntry { Kind = NeverOptimizeKind.FileHash, Value = "ABC123" };

            Assert.True(byName.Matches("chrome.exe", @"C:\x\chrome.exe", null, null));
            Assert.True(byName.Matches("CHROME", null, null, null));
            Assert.False(byName.Matches("chromium.exe", null, null, null));

            Assert.True(byPath.Matches(null, @"c:\apps\discord.exe", null, null));
            Assert.False(byPath.Matches(null, @"c:\other\discord.exe", null, null));

            Assert.True(byPublisher.Matches(null, null, "Acme Corp Ltd", null));
            Assert.False(byPublisher.Matches(null, null, "Other Ltd", null));

            Assert.True(byHash.Matches(null, null, null, "abc123"));
            Assert.False(byHash.Matches(null, null, null, "def456"));
        }

        [Fact]
        public void AnEmptyNeverOptimizeEntry_MatchesNothing()
        {
            var entry = new NeverOptimizeEntry { Kind = NeverOptimizeKind.ProcessName, Value = "   " };

            Assert.False(entry.Matches("anything.exe", @"C:\anything.exe", "anyone", "anyhash"));
        }

        #endregion

        #region Background process rules

        [Fact]
        public void ABackgroundRule_CanOnlyMakeThingsMoreCareful()
        {
            // The ordering rule that makes the whole model safe: NeverOptimize wins, whatever else exists.
            var rules = new List<BackgroundProcessRule>
            {
                new() { Target = "chrome", Decision = BackgroundProcessDecision.AllowOptimization },
                new() { Target = "chrome.exe", Decision = BackgroundProcessDecision.NeverOptimize }
            };

            Assert.Equal(
                BackgroundProcessDecision.NeverOptimize,
                BackgroundProcessRule.Resolve(rules, "chrome", @"C:\Program Files\Google\Chrome\Application\chrome.exe"));

            // The reverse order must not change that.
            rules.Reverse();

            Assert.Equal(
                BackgroundProcessDecision.NeverOptimize,
                BackgroundProcessRule.Resolve(rules, "chrome", null));
        }

        [Fact]
        public void AProcessWithNoRule_DefaultsToAskingTheUser()
        {
            Assert.Equal(
                BackgroundProcessDecision.AskEveryTime,
                BackgroundProcessRule.Resolve(new List<BackgroundProcessRule>(), "anything", null));

            Assert.Equal(
                BackgroundProcessDecision.AskEveryTime,
                BackgroundProcessRule.Resolve(null, "anything", null));
        }

        [Fact]
        public void APathRule_DoesNotMatchADifferentProgramWithTheSameName()
        {
            var rule = new BackgroundProcessRule
            {
                Target = @"C:\Tools\helper.exe",
                MatchByPath = true,
                Decision = BackgroundProcessDecision.AllowOptimization
            };

            Assert.True(BackgroundProcessRule.Matches(rule, "helper", @"C:\Tools\helper.exe"));
            Assert.False(BackgroundProcessRule.Matches(rule, "helper", @"C:\Elsewhere\helper.exe"));
        }

        [Fact]
        public void ANameRule_IgnoresTheExtensionAndTheCase()
        {
            var rule = new BackgroundProcessRule { Target = "OneDrive.exe" };

            Assert.True(BackgroundProcessRule.Matches(rule, "onedrive", null));
            Assert.True(BackgroundProcessRule.Matches(rule, "OneDrive", null));
            Assert.False(BackgroundProcessRule.Matches(rule, "OneDriveSetup", null));
        }

        #endregion

        #region Benchmark arithmetic

        [Fact]
        public void ADelta_IsMeasuredInPercentagePoints()
        {
            var record = new BenchmarkRecord
            {
                Before = new BenchmarkSample { RamPercent = 61f, CpuPercent = 28f },
                After = new BenchmarkSample { RamPercent = 47f, CpuPercent = 15f }
            };

            Assert.Equal(-14f, record.RamDeltaPoints);
            Assert.Equal(-13f, record.CpuDeltaPoints);

            var sentence = BenchmarkRecord.DescribeDelta("RAM", record.RamDeltaPoints);

            // The wording the specification demands: points, never "percent better".
            Assert.Contains("percentage points", sentence, StringComparison.Ordinal);
            Assert.DoesNotContain("% better", sentence, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void ADeltaWithNoComparableReading_IsReportedAsUnavailable()
        {
            var record = new BenchmarkRecord
            {
                Before = new BenchmarkSample { RamPercent = 55f },
                After = new BenchmarkSample() // no reading taken
            };

            Assert.Null(record.RamDeltaPoints);
            Assert.Contains("N/A", BenchmarkRecord.DescribeDelta("RAM", record.RamDeltaPoints), StringComparison.Ordinal);
        }

        [Fact]
        public void Fps_IsAlwaysUnavailableUntilARealSourceExists()
        {
            var sample = new BenchmarkSample();

            Assert.Null(sample.Fps);
            Assert.Equal(BenchmarkSample.FpsUnavailableReason, sample.FpsSource);
            Assert.Contains("N/A", sample.FpsSource, StringComparison.Ordinal);
        }

        [Fact]
        public void NoMeasurableChange_IsDetectable()
        {
            var record = new BenchmarkRecord
            {
                Before = new BenchmarkSample { RamPercent = 50f, CpuPercent = 10f },
                After = new BenchmarkSample { RamPercent = 50.2f, CpuPercent = 9.8f }
            };

            Assert.True(record.NoMeasurableChange);
        }

        [Fact]
        public void ARealChange_IsNotReportedAsNoChange()
        {
            var record = new BenchmarkRecord
            {
                Before = new BenchmarkSample { RamPercent = 50f, CpuPercent = 10f },
                After = new BenchmarkSample { RamPercent = 44f, CpuPercent = 10f }
            };

            Assert.False(record.NoMeasurableChange);
        }

        #endregion

        #region Launcher configuration

        [Fact]
        public void NoLauncherIsAssumedWhenNoneIsConfigured()
        {
            // The optimiser must never guess which program is a launcher: it uses what the user set.
            var profile = MakeProfile();

            Assert.False(profile.UsesLauncher);
            Assert.Empty(profile.LauncherArgumentList);
        }

        [Fact]
        public void ALauncherNeedsBothItsOwnPathAndAnExplicitTarget()
        {
            var profile = MakeProfile();

            profile.LauncherPath = @"C:\Program Files\SomeLauncher\launcher.exe";

            // A launcher without a target is not a usable configuration: there would be nothing to watch.
            Assert.False(profile.UsesLauncher);

            profile.LauncherTargetPath = @"C:\Games\ExampleGame\Game.exe";

            Assert.True(profile.UsesLauncher);
        }

        [Fact]
        public void EachArgumentIsExactlyOneEntrySoNothingHasToBeSplit()
        {
            var profile = MakeProfile();

            profile.LauncherArgumentList.Add("-applaunch");
            profile.LauncherArgumentList.Add("440");
            profile.LauncherArgumentList.Add(@"C:\Games\Example Game\Game.exe");

            var reloaded = RoundTrip(profile);

            // Three arguments stay three arguments, including the one containing a space: nothing was
            // split, joined or quoted on the way through storage.
            Assert.Equal(3, reloaded.LauncherArgumentList.Count);
            Assert.Equal("440", reloaded.LauncherArgumentList[1]);
            Assert.Equal(@"C:\Games\Example Game\Game.exe", reloaded.LauncherArgumentList[2]);
        }

        [Theory]
        [InlineData("two\narguments")]
        [InlineData("one\rargument")]
        [InlineData("bell\u0007")]
        public void AnArgumentThatCouldBecomeTwoArgumentsIsRemovedRatherThanRepaired(string argument)
        {
            var profile = MakeProfile();

            profile.LauncherArgumentList.Add("safe");
            profile.LauncherArgumentList.Add(argument);

            var rejected = profile.NormalizeLauncherArguments();

            Assert.Single(rejected);
            Assert.Single(profile.LauncherArgumentList);
            Assert.Equal("safe", profile.LauncherArgumentList[0]);
        }

        [Fact]
        public void AnOverlongArgumentIsRemoved()
        {
            var profile = MakeProfile();

            profile.LauncherArgumentList.Add(new string('a', 900));

            Assert.Single(profile.NormalizeLauncherArguments());
            Assert.Empty(profile.LauncherArgumentList);
        }

        [Fact]
        public void ArgumentsAreNeverInterpretedExpandedOrShellQuoted()
        {
            var profile = MakeProfile();

            // Anything that would be meaningful to a shell is just characters in an argument here.
            profile.LauncherArgumentList.Add("&& del /f /q C:\\*");
            profile.LauncherArgumentList.Add("$(Get-Process).Kill()");
            profile.LauncherArgumentList.Add("%TEMP%");

            Assert.Empty(profile.NormalizeLauncherArguments());
            Assert.Equal(3, profile.LauncherArgumentList.Count);

            var reloaded = RoundTrip(profile);

            Assert.Equal("$(Get-Process).Kill()", reloaded.LauncherArgumentList[1]);
            Assert.Equal("%TEMP%", reloaded.LauncherArgumentList[2]);
        }

        private static GameAppProfile RoundTrip(GameAppProfile profile)
        {
            var json = System.Text.Json.JsonSerializer.Serialize(profile, GameAppProfileJson.Options);

            return System.Text.Json.JsonSerializer.Deserialize<GameAppProfile>(json, GameAppProfileJson.Options)!;
        }

        #endregion

        #region Interaction with the rest of the application

        [Fact]
        public void AProfileCarriesNoExecutableContent_OnlyPathsAndHashes()
        {
            // Guard against a future change that starts storing the executable itself (or worse, a
            // command line built from it) in the profile file.
            var profile = MakeProfile();
            profile.LauncherArgumentList.Add("--windowed");

            Assert.True(_store.Save(profile));

            var json = File.ReadAllText(_store.FilePathFor(profile));

            Assert.Contains(profile.Identity.Sha256!, json, StringComparison.Ordinal);
            Assert.DoesNotContain("powershell", json, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("cmd.exe", json, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("UseShellExecute", json, StringComparison.Ordinal);
        }

        #endregion
    }
}

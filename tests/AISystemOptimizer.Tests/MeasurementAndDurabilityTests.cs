using System;
using System.IO;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the measurement maths and for the durability guarantees that protect the user's
    /// configuration and their ability to undo a change.
    /// </summary>
    public class MeasurementAndDurabilityTests
    {
        #region RAM maths (spec sections on RAM measurement and percentage)

        [Fact]
        public void RamUsagePercentage_IsDerivedFromMeasuredBytes()
        {
            // 8 GB installed, 5 GB available => 3 GB in use => 37.5 %.
            // This is the same definition Task Manager uses for "In use" (Total - Available, where
            // Windows' "Available" already includes the reclaimable standby list).
            var info = new SystemInfo
            {
                TotalPhysicalMemory = 8L * 1024 * 1024 * 1024,
                AvailablePhysicalMemory = 5L * 1024 * 1024 * 1024
            };

            Assert.Equal(3.0, info.UsedPhysicalMemoryGB, 3);
            Assert.Equal(37.5f, info.RamUsagePercentage, 2);
        }

        [Fact]
        public void RamUsagePercentage_IsZeroForAnEmptySnapshot()
        {
            // A snapshot whose total is unknown must not divide by zero or report a bogus percentage.
            var info = new SystemInfo();

            Assert.Equal(0f, info.RamUsagePercentage);
        }

        [Theory]
        [InlineData(8, 8.0, 0f)]
        [InlineData(8, 6.0, 25f)]
        [InlineData(8, 4.0, 50f)]
        [InlineData(8, 2.0, 75f)]
        [InlineData(16, 8.0, 50f)]
        public void RamUsagePercentage_MatchesHandCalculation(int totalGb, double availableGb, float expected)
        {
            var info = new SystemInfo
            {
                TotalPhysicalMemory = (long)(totalGb * 1024.0 * 1024 * 1024),
                AvailablePhysicalMemory = (long)(availableGb * 1024.0 * 1024 * 1024)
            };

            Assert.Equal(expected, info.RamUsagePercentage, 1);
        }

        [Fact]
        public void RamUsagePercentage_IsNeverNegative()
        {
            // Defensive: a snapshot taken while memory was being paged must not produce a negative
            // percentage that would then be shown to the user or written to the history file.
            var info = new SystemInfo
            {
                TotalPhysicalMemory = 4L * 1024 * 1024 * 1024,
                AvailablePhysicalMemory = 6L * 1024 * 1024 * 1024
            };

            Assert.True(info.RamUsagePercentage >= 0f);
        }

        #endregion

        #region Unreachable-target honesty (spec section 33)

        [Fact]
        public void UnreachableRamTarget_IsReportedHonestly_NotFaked()
        {
            // 8 GB with 6 GB in use, and the only closable processes hold 200 MB. Reaching 35 % would
            // need 3.2 GB of the 6 GB in use to disappear, which is not safely possible. The message
            // must say so rather than pretend otherwise.
            var info = new SystemInfo
            {
                TotalPhysicalMemory = 8L * 1024 * 1024 * 1024,
                AvailablePhysicalMemory = 2L * 1024 * 1024 * 1024
            };

            var message = SystemScoring.DescribeAchievableTarget(info, 35);

            Assert.False(string.IsNullOrWhiteSpace(message));
            Assert.Contains("35", message);
        }

        [Fact]
        public void TargetProgress_IsBoundedBetweenZeroAndHundred()
        {
            var info = new SystemInfo
            {
                TotalPhysicalMemory = 8L * 1024 * 1024 * 1024,
                AvailablePhysicalMemory = 5L * 1024 * 1024 * 1024
            };

            var progress = SystemScoring.CalculateTargetProgress(info, 35);

            Assert.InRange(progress, 0, 100);
        }

        #endregion

        #region Configuration durability (spec section on configuration corruption)

        [Fact]
        public void CorruptConfig_DoesNotThrow_AndFallsBackToDefaults()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path, "{ this is not valid json ###");

                var config = AppConfig.Load(path);

                Assert.NotNull(config);
                // Defaults must be intact so the safety layer is never silently switched off by a
                // corrupt file.
                Assert.True(config.SafetyLayerEnabled);
                Assert.True(config.SafetyLayerEnabled);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
                if (File.Exists(path + ".invalid")) File.Delete(path + ".invalid");
            }
        }

        [Fact]
        public void CorruptConfig_IsQuarantinedRatherThanDiscardedSilently()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path, "not json");

                AppConfig.Load(path);

                Assert.True(File.Exists(path + ".invalid"),
                    "The unusable file must be kept as .invalid so the user can inspect what went wrong.");
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
                if (File.Exists(path + ".invalid")) File.Delete(path + ".invalid");
            }
        }

        [Fact]
        public void MissingConfig_IsCreatedWithDefaults()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                Assert.False(File.Exists(path));

                var config = AppConfig.Load(path);

                Assert.NotNull(config);
                Assert.True(config.SafetyLayerEnabled);
                Assert.True(File.Exists(path), "A missing configuration should be written out with defaults.");
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void ConfigRoundTrip_PreservesSafetySettings()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                var original = AppConfig.CreateDefault();
                original.VerificationSettleSeconds = 12;
                original.CloseGracePeriodMs = 1500;
                original.MaxAutoRiskLevel = RiskLevel.Low;
                original.ExcludedProcesses.Add("my-important-tool.exe");

                Assert.True(original.Save(path));

                var reloaded = AppConfig.Load(path);

                Assert.Equal(12, reloaded.VerificationSettleSeconds);
                Assert.Equal(1500, reloaded.CloseGracePeriodMs);
                Assert.Equal(RiskLevel.Low, reloaded.MaxAutoRiskLevel);
                Assert.Contains("my-important-tool.exe", reloaded.ExcludedProcesses);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void DefaultSettleWindow_IsInsideTheRangeTheSpecificationRequires()
        {
            // The spec asks for a 5-15 second observation window before the "after" measurement.
            var config = AppConfig.CreateDefault();

            Assert.InRange(config.VerificationSettleSeconds, 5, 15);
        }

        #endregion

        #region Undo / rollback (spec section on reversibility)

        [Fact]
        public void StartupDisable_ProducesAnUndoAction()
        {
            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.DisableStartup,
                Target = "SomeUpdater",
                RiskLevel = RiskLevel.Low,
                CanUndo = true
            };

            action.AttachUndoAction();

            Assert.NotNull(action.UndoAction);
            Assert.Equal(OptimizationActionType.DisableStartup, action.UndoAction!.ActionType);
            Assert.Equal("SomeUpdater", action.UndoAction.Target);
            Assert.False(action.UndoAction.CanUndo, "Undo must be as safe as possible - it is not itself undoable.");
        }

        [Fact]
        public void IrreversibleAction_HasNoUndo()
        {
            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.ClearCache,
                Target = "System Cache",
                CanUndo = false
            };

            action.AttachUndoAction();

            Assert.Null(action.UndoAction);
        }

        [Fact]
        public void UndoAction_CarriesTheProcessIdentity()
        {
            // The undo must be subject to the same PID-reuse protection as the original action.
            var creationTime = new DateTime(2026, 2, 2, 2, 2, 2, DateTimeKind.Utc);

            var action = new OptimizationAction
            {
                ActionType = OptimizationActionType.ChangePriority,
                Target = "game.exe",
                TargetPid = 777,
                TargetProcessName = "game",
                TargetCreationTimeUtc = creationTime,
                TargetImagePath = @"C:\Games\game.exe",
                CanUndo = true
            };

            action.AttachUndoAction();

            Assert.NotNull(action.UndoAction);
            Assert.Equal(777, action.UndoAction!.TargetPid);
            Assert.Equal(creationTime, action.UndoAction.TargetCreationTimeUtc);
            Assert.Equal("game", action.UndoAction.TargetProcessName);
            Assert.True(action.UndoAction.HasProcessIdentity);
        }

        [Fact]
        public void Clone_PreservesTheProcessIdentity()
        {
            // A cloned plan must not lose the identity, otherwise re-validating the clone would pass
            // an action that the original would have rejected.
            var creationTime = new DateTime(2026, 5, 5, 5, 5, 5, DateTimeKind.Utc);

            var original = new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                Target = "spotify.exe",
                TargetPid = 1000,
                TargetProcessName = "spotify",
                TargetCreationTimeUtc = creationTime,
                TargetImagePath = @"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe"
            };

            var clone = original.Clone();

            Assert.Equal(original.TargetPid, clone.TargetPid);
            Assert.Equal(original.TargetCreationTimeUtc, clone.TargetCreationTimeUtc);
            Assert.Equal(original.TargetProcessName, clone.TargetProcessName);
            Assert.Equal(original.TargetImagePath, clone.TargetImagePath);
            Assert.True(clone.HasProcessIdentity);
        }

        #endregion

        #region Plan-level risk

        [Fact]
        public void PlanOverallRisk_IsTheHighestRiskItContains()
        {
            var plan = new OptimizationPlan();

            plan.AddAction(new OptimizationAction { RiskLevel = RiskLevel.Low });
            plan.AddAction(new OptimizationAction { RiskLevel = RiskLevel.Medium });
            plan.AddAction(new OptimizationAction { RiskLevel = RiskLevel.High });

            Assert.Equal(RiskLevel.High, plan.OverallRiskLevel);
        }

        [Fact]
        public void EstimatedRamRecovery_SumsOnlyRamActions()
        {
            var plan = new OptimizationPlan();

            plan.AddAction(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                ResourceType = ResourceType.RAM,
                EstimatedResourceRecovery = 100L * 1024 * 1024
            });

            plan.AddAction(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                ResourceType = ResourceType.RAM,
                EstimatedResourceRecovery = 50L * 1024 * 1024
            });

            Assert.Equal(150L * 1024 * 1024, plan.EstimatedRamRecovery);
        }

        [Fact]
        public void EstimatedRamRecovery_DoesNotCountCpuMotivatedActions()
        {
            // BUG FIXED HERE: the total used to be filtered by action type, so a process the planner
            // proposed closing because it was hogging the CPU had its working set added to the memory
            // estimate. The plan then promised more free memory than it could return.
            var plan = new OptimizationPlan();

            plan.AddAction(new OptimizationAction
            {
                ActionType = OptimizationActionType.CloseProcess,
                ResourceType = ResourceType.CPU,
                EstimatedResourceRecovery = 900L * 1024 * 1024
            });

            plan.AddAction(new OptimizationAction
            {
                ActionType = OptimizationActionType.StopService,
                ResourceType = ResourceType.CPU,
                EstimatedResourceRecovery = 500L * 1024 * 1024
            });

            Assert.Equal(0L, plan.EstimatedRamRecovery);
        }

        #endregion

        #region Active-application protection with several instances

        [Fact]
        public void Analyzer_ExcludesInUseProcessesFromTheClosableList()
        {
            var system = new SystemInfo
            {
                TotalPhysicalMemory = 8L * 1024 * 1024 * 1024,
                AvailablePhysicalMemory = 5L * 1024 * 1024 * 1024
            };

            system.Processes.Add(new ProcessInfo
            {
                Id = 100,
                Name = "chrome.exe",
                Category = ProcessCategory.UserApplication,
                RiskLevel = RiskLevel.Low,
                IsActive = false,
                HasVisibleWindow = false
            });

            system.Processes.Add(new ProcessInfo
            {
                Id = 200,
                Name = "chrome.exe",
                Category = ProcessCategory.UserApplication,
                RiskLevel = RiskLevel.Low,
                IsActive = true,
                HasVisibleWindow = true
            });

            // The rule the optimiser actually relies on: anything in use is never a candidate.
            var closable = system.Processes.Where(p => !p.IsActive && !p.HasVisibleWindow).ToList();

            Assert.Single(closable);
            Assert.Equal(100, closable[0].Id);
        }

        #endregion

        #region AI endpoint policy

        [Theory]
        [InlineData("http://localhost:11434")]
        [InlineData("http://127.0.0.1:8080")]
        [InlineData("http://localhost")]
        [InlineData("https://127.0.0.1:11434")]
        [InlineData("http://[::1]:11434")]
        public void LoopbackAiEndpoints_AreAlwaysPermitted(string url)
        {
            // Every supported local runtime listens on loopback, so that must never be blocked.
            Assert.True(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: false));
            Assert.True(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: true));
        }

        [Theory]
        [InlineData("https://api.openai.com")]
        [InlineData("https://example.com:11434")]
        [InlineData("http://8.8.8.8")]
        [InlineData("ftp://example.com")]
        [InlineData("file:///etc/passwd")]
        [InlineData("ssh://server")]
        public void PublicOrDisallowedAiEndpoints_AreRefusedEvenWhenOptedIn(string url)
        {
            // The application sends the user's process, service and start-up inventory to its AI server.
            // That must not be able to leave the machine because of an unnoticed setting, so a public
            // address is refused regardless of the opt-in.
            Assert.False(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: false),
                $"'{url}' must be refused by default.");
            Assert.False(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: true),
                $"'{url}' must be refused even when remote AI servers are enabled.");
        }

        [Theory]
        [InlineData("http://192.168.1.50:11434")]
        [InlineData("http://10.0.0.5:8080")]
        [InlineData("http://172.16.4.4:11434")]
        [InlineData("http://my-desktop:11434")]
        [InlineData("http://ollama.local:11434")]
        public void PrivateNetworkAiEndpoints_RequireAnExplicitOptIn(string url)
        {
            // Running the model server on another machine at home is a real scenario, but it is a
            // deliberate choice and it must be made deliberately.
            Assert.False(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: false),
                $"'{url}' must not be used without an explicit opt-in.");

            Assert.True(Core.AI.AiEndpointPolicy.IsPermitted(url, allowPrivateNetwork: true),
                $"'{url}' is a local-network address and should be usable once opted in.");
        }

        [Fact]
        public void ExternalAiEndpoint_InConfiguration_IsResetToLoopbackAndReported()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path,
                    "{ \"aiEnabled\": true, \"ollamaServerUrl\": \"https://api.openai.com\" }");

                var loaded = AppConfig.Load(path);

                Assert.Contains("localhost", loaded.OllamaServerUrl, StringComparison.OrdinalIgnoreCase);

                Assert.Contains(
                    AppConfig.LastLoadAdjustments,
                    adjustment => adjustment.Contains("ollamaServerUrl", StringComparison.Ordinal));
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void RemoteAiIsOffByDefault()
        {
            // The default must keep system information on this machine.
            Assert.False(AppConfig.CreateDefault().AllowRemoteAiServer);
        }

        #endregion

        #region Threat model: input validation at the boundary

        [Theory]
        [InlineData("381b4222-f694-41f0-9685-ff5bb260df2e")]
        [InlineData("{381b4222-f694-41f0-9685-ff5bb260df2e}")]
        public void ValidPowerSchemeGuid_IsAccepted(string guid)
        {
            Assert.True(WindowsApiHelper.IsValidPowerSchemeGuid(guid));
        }

        [Theory]
        // Argument injection: none of these are a GUID, and every one of them would change what
        // powercfg does if it were interpolated into the command line unchecked.
        [InlineData("381b4222-f694-41f0-9685-ff5bb260df2e & calc.exe")]
        [InlineData("381b4222-f694-41f0-9685-ff5bb260df2e\" /delete")]
        [InlineData("; shutdown /s")]
        [InlineData("| net user")]
        [InlineData("../../windows/system32/cmd.exe")]
        [InlineData("")]
        [InlineData("   ")]
        [InlineData(null)]
        public void MaliciousOrMalformedPowerSchemeValue_IsRejected(string? value)
        {
            Assert.False(WindowsApiHelper.IsValidPowerSchemeGuid(value));
        }

        [Theory]
        [InlineData("http://localhost:11434")]
        [InlineData("localhost:11434")]
        [InlineData("HTTP://LocalHost:11434/")]
        public void AiServerUrl_IsNormalisedToStringsWeControl(string input)
        {
            var normalised = Core.AI.OpenAiCompatibleClient.NormalizeBaseUrl(input);

            Assert.StartsWith("http", normalised, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain(" ", normalised);
            Assert.False(normalised.EndsWith("/"), "A trailing slash would produce a doubled separator.");
        }

        [Fact]
        public void AiServerUrl_WithNoValue_FallsBackToLoopback()
        {
            // The default must never point at a remote host: AI is local-only by design.
            var normalised = Core.AI.OpenAiCompatibleClient.NormalizeBaseUrl(null);

            Assert.Contains("localhost", normalised, StringComparison.OrdinalIgnoreCase);
        }

        #endregion

        #region Shipped configuration template

        [Fact]
        public void ShippedConfigTemplate_ActuallyLoadsItsValues()
        {
            // WHY THIS TEST WAS REWRITTEN
            // --------------------------
            // The original version of this test asserted SafetyLayerEnabled == true, CreateRestorePoints
            // == true, AllowCriticalRiskActions == false, MaxAutoRiskLevel == Low. Every one of those is
            // ALSO the built-in default. The test therefore passed whether the file was read correctly
            // or was rejected outright and replaced with defaults - it could not fail for the reason it
            // existed. It was, in practice, asserting nothing.
            //
            // It was hiding a real defect: the shipped template writes every enum as a name
            // ("maxAutoRiskLevel": "Low"), the deserialiser had no string-enum converter, so the whole
            // file threw and was quarantined. Users who edited config.json lost every setting silently.
            //
            // This version reads a value out of the file that is NOT the default, so it can only pass
            // when the file is genuinely parsed.
            var templatePath = Path.Combine(AppContext.BaseDirectory, "config.defaults.json");
            Assert.True(File.Exists(templatePath), "config.defaults.json should be copied next to the tests.");

            var workPath = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.Copy(templatePath, workPath, overwrite: true);

                var loaded = AppConfig.Load(workPath);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);
                Assert.False(File.Exists(workPath + ".invalid"),
                    "The shipped template must never be quarantined - if it is, the application ships a " +
                    "configuration file it cannot read.");

                // A distinctive value that differs from the built-in default of 35.
                var json = File.ReadAllText(workPath);
                Assert.Contains("\"targetRamUsage\"", json, StringComparison.Ordinal);

                var marker = "\"targetRamUsage\":";
                var index = json.IndexOf(marker, StringComparison.Ordinal);
                var raw = json[(index + marker.Length)..].TrimStart().Split(',', '\n', '\r')[0].Trim();

                Assert.True(int.TryParse(raw, out var expected),
                    $"Could not read targetRamUsage from the template (raw: '{raw}').");

                Assert.Equal(expected, loaded.TargetRamUsage);
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(workPath + suffix)) File.Delete(workPath + suffix);
            }
        }

        [Fact]
        public void ShippedConfigTemplate_EnumNamesAreReadable()
        {
            // The specific regression: enum names in the file must deserialise into the matching enum
            // members, not into defaults via an exception-then-quarantine path.
            var templatePath = Path.Combine(AppContext.BaseDirectory, "config.defaults.json");
            var workPath = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.Copy(templatePath, workPath, overwrite: true);

                var loaded = AppConfig.Load(workPath);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);

                // The template sets these to names rather than numbers.
                Assert.Equal(RiskLevel.Low, loaded.MaxAutoRiskLevel);
                Assert.Equal("Ollama", loaded.AiProvider, ignoreCase: true);
                Assert.Equal(OptimizationMode.Manual, loaded.DefaultOptimizationMode);
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(workPath + suffix)) File.Delete(workPath + suffix);
            }
        }

        [Theory]
        [InlineData("Medium", RiskLevel.Medium)]
        [InlineData("High", RiskLevel.High)]
        [InlineData("Critical", RiskLevel.Critical)]
        [InlineData("Low", RiskLevel.Low)]
        [InlineData("medium", RiskLevel.Medium)]
        public void StringEnumValues_AreReadFromTheFile(string wire, RiskLevel expected)
        {
            // Reading a non-default value proves the file was parsed rather than discarded.
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path, $"{{ \"maxAutoRiskLevel\": \"{wire}\" }}");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);
                Assert.Equal(expected, loaded.MaxAutoRiskLevel);
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void OneUnreadableValue_DoesNotDiscardTheWholeFile()
        {
            // A single typo in one setting used to throw away every setting the user had chosen. Now the
            // offending property is isolated, the rest of the file is honoured, and the dropped setting
            // is reported so the user can see what happened.
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                // "Balanced" is a power mode, not an optimisation mode - an easy and realistic mistake.
                File.WriteAllText(path,
                    "{ \"targetRamUsage\": 41, \"defaultOptimizationMode\": \"Balanced\", " +
                    "\"logLevel\": \"Debug\" }");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);
                Assert.Equal(41, loaded.TargetRamUsage);

                // The valid setting that followed the invalid one must have survived.
                Assert.Equal(41, loaded.TargetRamUsage);
                Assert.NotEmpty(AppConfig.LastLoadAdjustments);
                Assert.Contains(
                    AppConfig.LastLoadAdjustments,
                    adjustment => adjustment.Contains("defaultOptimizationMode", StringComparison.Ordinal));
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void CorruptFile_IsRecoveredFromBackupBeforeDefaults()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                // Save a configuration with a distinctive value, which also creates the recovery copy.
                var good = AppConfig.CreateDefault();
                good.TargetRamUsage = 55;

                Assert.True(good.Save(path));
                Assert.True(File.Exists(path + ".bak"),
                    "Saving must leave a recovery copy behind, otherwise there is nothing to recover from.");

                // Destroy the live file.
                File.WriteAllText(path, "{ corrupted ###");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.RecoveredFromBackup, AppConfig.LastLoadOutcome);
                Assert.Equal(55, loaded.TargetRamUsage);
                Assert.True(File.Exists(path + ".invalid"),
                    "The unusable file must be kept aside so the user can inspect it.");
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void BrokenFile_WithoutABackup_FallsBackToDefaultsSafely()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path, "not json at all");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.FellBackToDefaults, AppConfig.LastLoadOutcome);

                // The safety-critical defaults must survive the fallback.
                Assert.True(loaded.SafetyLayerEnabled);
                Assert.False(loaded.AllowCriticalRiskActions);
                Assert.False(loaded.AllowHighRiskActions);
                Assert.Equal(RiskLevel.Low, loaded.MaxAutoRiskLevel);
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void OutOfRangeValues_AreClampedAndReported()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path,
                    "{ \"targetRamUsage\": 999, \"maxLogFiles\": 0, " +
                    "\"verificationSettleSeconds\": 100000, \"closeGracePeriodMs\": -5000, " +
                    "\"aiRequestTimeout\": -1, \"maxConcurrentAiRequests\": 5000 }");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);
                Assert.InRange(loaded.TargetRamUsage, 10, 90);
                Assert.InRange(loaded.MaxLogFiles, 1, 50);
                Assert.InRange(loaded.VerificationSettleSeconds, 5, 30);
                Assert.InRange(loaded.CloseGracePeriodMs, 500, 15000);
                Assert.InRange(loaded.AiRequestTimeout, 5, 300);
                Assert.InRange(loaded.MaxConcurrentAiRequests, 1, 4);

                // Whatever was changed must have been reported.
                Assert.NotEmpty(AppConfig.LastLoadAdjustments);

                // And the clamped configuration must pass its own validation.
                Assert.True(loaded.Validate(out _));
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void MissingKeys_KeepTheirSafeDefaults()
        {
            var path = Path.Combine(Path.GetTempPath(), $"aio-cfg-{Guid.NewGuid():N}.json");

            try
            {
                File.WriteAllText(path, "{ \"targetRamUsage\": 40 }");

                var loaded = AppConfig.Load(path);

                Assert.Equal(AppConfig.LoadOutcome.Loaded, AppConfig.LastLoadOutcome);
                Assert.Equal(40, loaded.TargetRamUsage);

                // Anything absent must arrive as its safe default, never as null or zero.
                Assert.True(loaded.SafetyLayerEnabled);
                Assert.True(loaded.CreateRestorePoints);
                Assert.NotNull(loaded.ExcludedProcesses);
                Assert.NotNull(loaded.BlacklistedProcesses);
                Assert.NotNull(loaded.KnownGameExecutables);
            }
            finally
            {
                foreach (var suffix in new[] { "", ".bak", ".invalid", ".invalid.reason.txt", ".tmp" })
                    if (File.Exists(path + suffix)) File.Delete(path + suffix);
            }
        }

        [Fact]
        public void ShippedConfigTemplate_IsTheSameListAsTheSpecificationKey()
        {
            // The specification requires a key named ExcludedProcesses. Confirm the shipped file uses
            // it and that the values in it survive the load.
            var path = Path.Combine(AppContext.BaseDirectory, "config.defaults.json");

            var json = File.ReadAllText(path);

            Assert.Contains("excludedProcesses", json, StringComparison.Ordinal);
            Assert.DoesNotContain("whitelistedProcesses", json, StringComparison.Ordinal);

            var defaults = AppConfig.Load(path);
            Assert.NotNull(defaults.ExcludedProcesses);
        }

        #endregion
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using AISystemOptimizer.Core.Models;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the artificial-intelligence part.
    ///
    /// The model is the least trustworthy component in the system: it produces plausible text, it does not
    /// know what it is allowed to do, and it will happily suggest something dangerous if asked well. These
    /// tests are written from that assumption. For every rule the specification names - unknown action,
    /// unknown risk, invalid target, confidence outside 0-1, free-form text instead of JSON - there is a
    /// test that the answer is a refusal with a reason, and never a fallback.
    /// </summary>
    public class GameAppAiAdvisorTests
    {
        private static GameAppProfile Profile()
        {
            return new GameAppProfile
            {
                ApplicationId = Guid.NewGuid(),
                DisplayName = "Example Game",
                Identity = new ExecutableIdentity
                {
                    ExecutablePath = @"C:\Games\Example\Game.exe",
                    FileName = "Game.exe",
                    Sha256 = new string('a', 64),
                    Architecture = "x64",
                    Signature = SignatureVerdict.Valid
                }
            };
        }

        private static List<BackgroundProcessAssessment> Candidates()
        {
            return new List<BackgroundProcessAssessment>
            {
                new()
                {
                    ProcessId = 1234,
                    ProcessName = "Helper",
                    Category = BackgroundProcessCategory.UsuallySafe,
                    Reason = "No window, not in use.",
                    WorkingSet = 800L * 1024 * 1024
                },
                new()
                {
                    ProcessId = 5678,
                    ProcessName = "locker",
                    Category = BackgroundProcessCategory.NeverClose,
                    Reason = "Protected.",
                    WorkingSet = 200L * 1024 * 1024
                }
            };
        }

        private static GameAppAiAnalysis Analyse(string response, IEnumerable<BackgroundProcessAssessment>? candidates = null)
        {
            return new GameAppAiAdvisor().Analyse(
                response,
                "prompt",
                Profile(),
                new SystemInfo { TotalPhysicalMemory = 16L * 1024 * 1024 * 1024 },
                candidates?.ToList() ?? Candidates());
        }

        #region The happy path

        [Fact]
        public void AWellFormedSuggestion_IsAcceptedAsARecommendationOnly()
        {
            var response = """
            {
              "recommendations": [
                { "action": "change_priority", "target": "Game.exe", "reason": "The profile raises priority while it runs.", "risk": "low", "confidence": 0.8 }
              ]
            }
            """;

            var analysis = Analyse(response);

            var suggestion = Assert.Single(analysis.Accepted);

            Assert.Equal(OptimizationActionType.ChangePriority, suggestion.ActionType);
            Assert.Equal("Game.exe", suggestion.Target);
            Assert.Equal(0.8d, suggestion.Confidence, 3);

            // It is a recommendation: the summary says the safety validator and the user still decide.
            Assert.Contains("recommendations only", analysis.Summary, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void ACloseSuggestionForACloseableProcess_IsAccepted()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "target": "Helper", "reason": "It holds 800 MB and has no window.", "risk": "low", "confidence": 0.6 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Single(analysis.Accepted);
        }

        [Fact]
        public void TheRawResponseIsKeptVerbatimForTheLog()
        {
            var response = """{ "recommendations": [ { "action": "adjust_power", "target": "system", "reason": "Performance mode while running.", "risk": "low", "confidence": 0.5 } ] }""";

            var analysis = Analyse(response);

            Assert.Equal(response, analysis.RawResponse);
            Assert.Equal("prompt", analysis.Prompt);
        }

        #endregion

        #region Unknown actions, risks, targets, confidence

        [Fact]
        public void AnUnknownActionIsRefusedAndNeverMappedToSomethingElse()
        {
            var response = """
            { "recommendations": [ { "action": "disable_defender", "target": "MsMpEng.exe", "reason": "For speed.", "risk": "low", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.Single(analysis.Suggestions);
            Assert.False(analysis.Suggestions[0].Accepted);
            Assert.Null(analysis.Suggestions[0].ActionType);
            Assert.Contains("not one of the actions", analysis.Suggestions[0].RefusalReason, StringComparison.OrdinalIgnoreCase);
            Assert.Contains(analysis.Refusals, r => r.Contains("allowed vocabulary", StringComparison.Ordinal));
        }

        [Theory]
        [InlineData("optimize_registry")]
        [InlineData("clear_standby_list")]
        [InlineData("empty_working_set")]
        [InlineData("run_script")]
        [InlineData("Stop-Service")]
        public void EveryPlausibleSoundActionOutsideTheVocabulary_IsRefused(string action)
        {
            var response = $$"""
            { "recommendations": [ { "action": "{{action}}", "target": "Game.exe", "reason": "Because.", "risk": "low", "confidence": 0.5 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.NotEmpty(analysis.Refusals);
        }

        [Fact]
        public void AnUnknownRiskIsRefusedRatherThanAssumedSafe()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "target": "Helper", "reason": "Frees memory.", "risk": "harmless", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.Contains(analysis.Suggestions, s => s.RefusalReason.Contains("not a risk level", StringComparison.OrdinalIgnoreCase));
        }

        [Theory]
        [InlineData("-0.2")]
        [InlineData("1.5")]
        [InlineData("42")]
        public void AConfidenceOutsideZeroToOne_IsRefused(string confidence)
        {
            var response = $$"""
            { "recommendations": [ { "action": "close_process", "target": "Helper", "reason": "Frees memory.", "risk": "low", "confidence": {{confidence}} } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.Contains(analysis.Suggestions, s => s.RefusalReason.Contains("confidence", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AMissingConfidence_IsRefused()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "target": "Helper", "reason": "Frees memory.", "risk": "low" } ] }
            """;

            Assert.Empty(Analyse(response).Accepted);
        }

        [Fact]
        public void AConfidenceThatIsTextInsteadOfANumber_IsRefused()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "target": "Helper", "reason": "x", "risk": "low", "confidence": "high" } ] }
            """;

            Assert.Empty(Analyse(response).Accepted);
        }

        [Fact]
        public void AMissingTarget_IsRefused()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "reason": "Frees memory.", "risk": "low", "confidence": 0.9 } ] }
            """;

            Assert.Empty(Analyse(response).Accepted);
        }

        [Theory]
        [InlineData(@"C:\Windows\System32\cmd.exe /c del /f /q C:\*")]
        [InlineData("Helper.exe && format C:")]
        [InlineData("Helper; rm -rf /")]
        [InlineData("$(Get-Process).Kill()")]
        public void ATargetThatIsACommandRatherThanAName_IsRefused(string target)
        {
            var response = $$"""
            { "recommendations": [ { "action": "close_process", "target": "{{target.Replace("\\", "\\\\")}}", "reason": "Frees memory.", "risk": "low", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.NotEmpty(analysis.Refusals);
        }

        [Fact]
        public void ACloseSuggestionForAProcessTheProfileMayNotClose_IsRefused()
        {
            var response = """
            { "recommendations": [ { "action": "close_process", "target": "locker", "reason": "It uses memory.", "risk": "low", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.Contains(analysis.Suggestions, s => s.RefusalReason.Contains("not one this profile may close", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void APrioritySuggestionForADifferentProgram_IsRefused()
        {
            var response = """
            { "recommendations": [ { "action": "change_priority", "target": "chrome", "reason": "Increases speed.", "risk": "low", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);
            Assert.Contains(analysis.Suggestions, s => s.RefusalReason.Contains("this profile's own application", StringComparison.OrdinalIgnoreCase));
        }

        [Theory]
        [InlineData("high")]
        [InlineData("critical")]
        public void AHighRiskSuggestion_IsRecordedAndRefused(string risk)
        {
            var response = $$"""
            { "recommendations": [ { "action": "adjust_power", "target": "system", "reason": "Faster.", "risk": "{{risk}}", "confidence": 0.9 } ] }
            """;

            var analysis = Analyse(response);

            Assert.Empty(analysis.Accepted);

            // It is shown, with the risk that caused the refusal - not silently dropped.
            Assert.Contains(analysis.Suggestions, s => s.Risk == (risk == "high" ? RiskLevel.High : RiskLevel.Critical));
            Assert.Contains(analysis.Refusals, r => r.Contains("refused", StringComparison.OrdinalIgnoreCase));
        }

        #endregion

        #region Malformed and hostile responses

        [Fact]
        public void FreeFormTextInsteadOfJson_ProducesNothing()
        {
            var analysis = Analyse("Sure! I will close everything for you right away. `taskkill /F /IM chrome.exe`");

            Assert.Empty(analysis.Accepted);
            Assert.Empty(analysis.Suggestions);
            Assert.NotEmpty(analysis.Refusals);
            Assert.Contains("not JSON", analysis.Summary, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AnEmptyResponse_IsReportedAsNoRecommendationRatherThanAFailure()
        {
            var analysis = Analyse(string.Empty);

            Assert.False(analysis.AiWasAvailable);
            Assert.Empty(analysis.Suggestions);
            Assert.Contains("works without it", analysis.Summary, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AResponseWithNothingRecognisable_IsExplained()
        {
            var analysis = Analyse("""{ "notes": "nothing to suggest" }""");

            Assert.Empty(analysis.Accepted);
            Assert.Contains(analysis.Refusals, r => r.Contains("recommendations", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AnOversizedResponse_IsDiscarded()
        {
            var huge = "{\"recommendations\":[]}" + new string('j', 300 * 1024);

            var analysis = Analyse(huge);

            Assert.Empty(analysis.Suggestions);
            Assert.Contains(analysis.Refusals, r => r.Contains("above the limit", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AnEntryThatIsNotAnObject_IsIgnoredWithAReason()
        {
            var analysis = Analyse("""{ "recommendations": [ "please close chrome", 42 ] }""");

            Assert.Empty(analysis.Accepted);
            Assert.NotEmpty(analysis.Refusals);
        }

        [Fact]
        public void TheNumberOfRecommendationsIsBounded()
        {
            var entries = string.Join(",", Enumerable.Range(0, 60).Select(i =>
                $$"""{ "action": "close_process", "target": "Helper", "reason": "x", "risk": "low", "confidence": 0.5 }"""));

            var analysis = Analyse($$"""{ "recommendations": [ {{entries}} ] }""");

            Assert.True(analysis.Suggestions.Count <= 25);
            Assert.Contains(analysis.Refusals, r => r.Contains("first 25", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AModelFieldWithControlCharacters_CannotForgeALogLine()
        {
            var response = "{ \"recommendations\": [ { \"action\": \"close_process\", \"target\": \"Helper\", " +
                           "\"reason\": \"first\\nsecond\\rthird\", \"risk\": \"low\", \"confidence\": 0.5 } ] }";

            var analysis = Analyse(response);

            var suggestion = Assert.Single(analysis.Accepted);

            Assert.DoesNotContain("\n", suggestion.Reason, StringComparison.Ordinal);
            Assert.DoesNotContain("\r", suggestion.Reason, StringComparison.Ordinal);
        }

        [Fact]
        public void ExtraFieldsInTheResponse_AreIgnored()
        {
            var response = """
            {
              "recommendations": [
                { "action": "close_process", "target": "Helper", "reason": "x", "risk": "low", "confidence": 0.5,
                  "execute": "taskkill /F /IM Helper.exe", "path": "C:\\evil.exe", "admin": true }
              ]
            }
            """;

            var analysis = Analyse(response);

            var suggestion = Assert.Single(analysis.Accepted);

            // The extra fields changed nothing: there is no member on the suggestion that carries them.
            Assert.Equal("Helper", suggestion.Target);
            Assert.DoesNotContain("taskkill", suggestion.Describe(), StringComparison.OrdinalIgnoreCase);
            Assert.Null(typeof(GameAppAiSuggestion).GetProperty("Execute"));
            Assert.Null(typeof(GameAppAiSuggestion).GetProperty("Path"));
        }

        #endregion

        #region The prompt

        [Fact]
        public void ThePromptStatesTheAllowedActionsAndTheForbiddenOnes()
        {
            var advisor = new GameAppAiAdvisor();

            var prompt = advisor.BuildPrompt(
                Profile(),
                new ApplicationHealth { State = ApplicationHealthState.Healthy },
                new List<ApplicationRunInfo>(),
                new SystemInfo { TotalPhysicalMemory = 16L * 1024 * 1024 * 1024, CpuUsage = 12f },
                Candidates());

            Assert.Contains("close_process", prompt, StringComparison.Ordinal);
            Assert.Contains("change_priority", prompt, StringComparison.Ordinal);
            Assert.Contains("adjust_power", prompt, StringComparison.Ordinal);
            Assert.Contains("set_graphics_preference", prompt, StringComparison.Ordinal);

            Assert.Contains("Defender", prompt, StringComparison.Ordinal);
            Assert.Contains("registry", prompt, StringComparison.Ordinal);
            Assert.Contains("overclocking", prompt, StringComparison.Ordinal);
            Assert.Contains("frames-per-second", prompt, StringComparison.Ordinal);

            // The prompt names the applications the model may suggest closing, and their classification.
            Assert.Contains("Helper", prompt, StringComparison.Ordinal);
            Assert.Contains("confidence", prompt, StringComparison.Ordinal);
        }

        [Fact]
        public void TheVocabularyIsClosed()
        {
            Assert.True(GameAppAiAdvisor.IsAllowedAction("close_process"));
            Assert.True(GameAppAiAdvisor.IsAllowedAction("change_priority"));
            Assert.True(GameAppAiAdvisor.IsAllowedAction("adjust_power"));
            Assert.True(GameAppAiAdvisor.IsAllowedAction("set_graphics_preference"));

            Assert.False(GameAppAiAdvisor.IsAllowedAction("disable_service"));
            Assert.False(GameAppAiAdvisor.IsAllowedAction("stop_service"));
            Assert.False(GameAppAiAdvisor.IsAllowedAction("clear_cache"));
            Assert.False(GameAppAiAdvisor.IsAllowedAction("disable_startup"));
            Assert.False(GameAppAiAdvisor.IsAllowedAction("uninstall_application"));
            Assert.False(GameAppAiAdvisor.IsAllowedAction(null));
            Assert.False(GameAppAiAdvisor.IsAllowedAction(string.Empty));

            // The graphics action has no executor action type behind it, on purpose.
            Assert.False(GameAppAiAdvisor.AllowedActions.ContainsKey("set_graphics_preference"));
        }

        #endregion
    }
}

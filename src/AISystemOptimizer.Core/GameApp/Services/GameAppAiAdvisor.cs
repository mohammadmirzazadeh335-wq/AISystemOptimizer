using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AISystemOptimizer.Core.AI;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One thing the local model suggested, after it has been checked.
    ///
    /// A suggestion is a sentence for a human, plus - when it survives validation - a reference to one of
    /// the actions the optimiser already knows how to plan. It is never executable on its own: it has no
    /// command, no path to run and no way to reach the executor except by being turned into an
    /// <see cref="OptimizationAction"/> by <see cref="GameAppActionPlanner"/> and then validated by the
    /// existing safety layer.
    /// </summary>
    public sealed class GameAppAiSuggestion
    {
        /// <summary>The wire action name exactly as the model returned it.</summary>
        public string RawAction { get; init; } = string.Empty;

        /// <summary>The action type it maps to, or null when it was refused.</summary>
        public OptimizationActionType? ActionType { get; init; }

        public string Target { get; init; } = string.Empty;

        public string Reason { get; init; } = string.Empty;

        public RiskLevel Risk { get; init; } = RiskLevel.Critical;

        public double Confidence { get; init; }

        /// <summary>True when this suggestion survived every check.</summary>
        public bool Accepted { get; init; }

        /// <summary>Why it was refused, when it was. Never empty for a refused suggestion.</summary>
        public string RefusalReason { get; init; } = string.Empty;

        public string Describe() => Accepted
            ? $"[{Risk}] {ActionType} on '{Target}' ({Confidence:P0}): {Reason}"
            : $"REFUSED '{RawAction}' on '{Target}': {RefusalReason}";
    }

    /// <summary>
    /// The result of asking the model, with everything it said kept - including what was thrown away.
    /// </summary>
    public sealed class GameAppAiAnalysis
    {
        public bool AiWasAvailable { get; init; }

        public string Summary { get; init; } = string.Empty;

        public List<GameAppAiSuggestion> Suggestions { get; init; } = new List<GameAppAiSuggestion>();

        public List<string> Refusals { get; init; } = new List<string>();

        /// <summary>The prompt that was sent, so the user can see exactly what the model was told.</summary>
        public string Prompt { get; init; } = string.Empty;

        /// <summary>The raw response, kept verbatim for the log. Model output is data, never instructions.</summary>
        public string RawResponse { get; init; } = string.Empty;

        public IEnumerable<GameAppAiSuggestion> Accepted => Suggestions.Where(s => s.Accepted);
    }

    /// <summary>
    /// The artificial-intelligence part of the Game &amp; App Optimizer.
    ///
    /// The rules, in the order they are enforced:
    ///   1. The model is given a snapshot and asked for JSON. It is never given a way to run anything.
    ///   2. Its answer goes through the <b>existing</b> <see cref="AiRecommendationParser"/>, which has the
    ///      strict action allow-list and refuses unknown risks rather than defaulting them.
    ///   3. On top of that, this class checks the parts the specification names: confidence must be inside
    ///      0-1, the target must exist in the snapshot the model was given, and the action must be one this
    ///      feature is willing to offer at all.
    ///   4. Anything that fails is kept as a refusal with its reason, so the user sees what the model
    ///      suggested and why it was not taken.
    ///   5. Nothing here executes. The suggestions are turned into actions by the planner, and only if the
    ///      user confirms them.
    ///
    /// There is deliberately no fallback that turns an unknown action into a known one. A model that
    /// returns "" has produced nothing.
    /// </summary>
    public sealed class GameAppAiAdvisor
    {
        /// <summary>
        /// The vocabulary the model may use. It is this feature's own list: the actions the Game &amp; App
        /// Optimizer is prepared to plan, and nothing else.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, OptimizationActionType> AllowedActions =
            new Dictionary<string, OptimizationActionType>(StringComparer.OrdinalIgnoreCase)
            {
                ["close_process"] = OptimizationActionType.CloseProcess,
                ["change_priority"] = OptimizationActionType.ChangePriority,
                ["adjust_power"] = OptimizationActionType.AdjustPowerSettings
            };

        /// <summary>
        /// The one action that has no executor action type behind it. It is applied by
        /// <see cref="GraphicsPreferenceService"/> - one per-user registry value, with its original value
        /// recorded and restored - and it is kept out of <see cref="AllowedActions"/> on purpose, so that
        /// nothing can accidentally map it onto an action that does something else.
        /// </summary>
        public const string GraphicsPreferenceAction = "set_graphics_preference";

        private readonly ILogger _logger;

        public GameAppAiAdvisor(ILogger? logger = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
        }

        /// <summary>
        /// Whether an action name is in the vocabulary at all.
        /// </summary>
        public static bool IsAllowedAction(string? action) =>
            !string.IsNullOrWhiteSpace(action) &&
            (action!.Trim().Equals(GraphicsPreferenceAction, StringComparison.OrdinalIgnoreCase) ||
             AllowedActions.ContainsKey(action.Trim()));

        /// <summary>
        /// Build the prompt. Everything in it is measured data; the model's answer is treated as text.
        /// </summary>
        public string BuildPrompt(
            GameAppProfile profile,
            ApplicationHealth health,
            IReadOnlyList<ApplicationRunInfo> runningInstances,
            SystemInfo systemInfo,
            IReadOnlyList<BackgroundProcessAssessment> backgroundProcesses)
        {
            if (profile == null) throw new ArgumentNullException(nameof(profile));

            var lines = new List<string>
            {
                "You are advising a Windows performance tool. Answer with JSON only.",
                string.Empty,
                "APPLICATION",
                $"- name: {profile.ResolveDisplayName()}",
                $"- executable: {profile.FileName}",
                $"- architecture: {profile.Identity?.Architecture ?? "Unknown"}",
                $"- publisher: {(string.IsNullOrWhiteSpace(profile.Identity?.Publisher) ? "not recorded" : profile.Identity!.Publisher)}",
                $"- signature: {profile.Identity?.Signature ?? SignatureVerdict.Unknown}",
                $"- location: {profile.ExecutablePath}",
                $"- running: {(runningInstances != null && runningInstances.Count > 0 ? $"{runningInstances.Count} instance(s)" : "not running")}",
                $"- profile mode: {profile.ProfileMode}",
                string.Empty,
                "SYSTEM",
                $"- RAM in use: {systemInfo.RamUsagePercentage:F0}% of {systemInfo.TotalPhysicalMemory / (1024.0 * 1024 * 1024):F1} GB",
                $"- available RAM: {systemInfo.AvailablePhysicalMemory / (1024.0 * 1024 * 1024):F1} GB",
                $"- CPU load: {systemInfo.CpuUsage:F0}%",
                $"- GPU: {(systemInfo.Gpus != null && systemInfo.Gpus.Count > 0 ? systemInfo.Gpus[0].Name : "not reported")}",
                $"- GPU utilisation: {(systemInfo.Gpus != null && systemInfo.Gpus.Count > 0 && systemInfo.Gpus[0].Usage > 0 ? $"{systemInfo.Gpus[0].Usage:F0}%" : "not available")}",
                $"- Windows: {systemInfo.OsVersion}",
                $"- power mode: {Utilities.PowerSchemeManager.GetActiveSchemeName() ?? "not available"}",
                string.Empty,
                "BACKGROUND PROCESSES (already classified; you may only suggest closing ones marked as closeable)",
                string.Empty
            };

            foreach (var assessment in (backgroundProcesses ?? Array.Empty<BackgroundProcessAssessment>()).Take(25))
            {
                lines.Add($"- {assessment.ProcessName} (PID {assessment.ProcessId}): {assessment.Category}, " +
                          $"{assessment.WorkingSet / (1024 * 1024)} MB - {assessment.Reason}");
            }

            lines.Add(string.Empty);
            lines.Add("Allowed actions (use these exact names; anything else is discarded):");
            lines.Add("- close_process: close a background process listed as closeable above.");
            lines.Add("- change_priority: raise this application's priority. Only AboveNormal or High.");
            lines.Add("- adjust_power: use a performance power mode while the application runs. Restored afterwards.");
            lines.Add("- set_graphics_preference: HighPerformance or PowerSaving for this application.");
            lines.Add(string.Empty);
            lines.Add("Forbidden, and never to be suggested: disabling or stopping Windows services, disabling " +
                      "Defender or the firewall, clearing caches, emptying working sets, clearing the standby " +
                      "list, defragmenting, editing the registry, overclocking, changing BIOS settings, " +
                      "installing drivers, promising a frames-per-second improvement, or any command line.");
            lines.Add(string.Empty);
            lines.Add("Answer with exactly this shape:");
            lines.Add("{\"recommendations\":[{\"action\":\"change_priority\",\"target\":\"Game.exe\"," +
                      "\"reason\":\"why, in one sentence\",\"risk\":\"low\",\"confidence\":0.7}]}");
            lines.Add("confidence must be a number between 0 and 1. risk must be low, medium, high or critical.");

            return string.Join(Environment.NewLine, lines);
        }

        /// <summary>
        /// Validate a model response and turn it into suggestions.
        ///
        /// This is a pure function of (response text, snapshot the model was shown). It parses the schema
        /// the specification defines - <c>recommendations[]</c> with <c>action</c>, <c>target</c>,
        /// <c>reason</c>, <c>risk</c> and <c>confidence</c> - and refuses anything that does not fit:
        /// unknown action, unknown risk, missing or implausible target, confidence outside 0-1, or a
        /// response that is too large. The shared <see cref="AiRecommendationParser"/> helpers are used for
        /// the field sanitising, the plausibility test and the risk mapping, so there is one set of rules.
        ///
        /// Free-form text is never executed and never turned into an action by interpretation: a string
        /// that is not one of the allowed action names produces a refusal, not a fallback.
        /// </summary>
        public GameAppAiAnalysis Analyse(
            string? response,
            string? prompt,
            GameAppProfile profile,
            SystemInfo? systemInfo,
            IReadOnlyList<BackgroundProcessAssessment>? backgroundProcesses)
        {
            var refusals = new List<string>();
            var suggestions = new List<GameAppAiSuggestion>();

            if (string.IsNullOrWhiteSpace(response))
            {
                return new GameAppAiAnalysis
                {
                    AiWasAvailable = false,
                    Summary = "The model returned nothing. No recommendation was produced, and nothing was done. " +
                              "The optimiser works without it: the deterministic rules are what decide.",
                    Prompt = prompt ?? string.Empty,
                    RawResponse = string.Empty
                };
            }

            if (response.Length > AiRecommendationParser.MaxAiResponseCharacters)
            {
                return new GameAppAiAnalysis
                {
                    AiWasAvailable = true,
                    Summary = "The model's answer was too large to consider, so it was discarded. Nothing was done.",
                    Prompt = prompt ?? string.Empty,
                    RawResponse = string.Empty,
                    Refusals = { $"The response was {response.Length} characters, above the limit." }
                };
            }

            JsonDocument document;

            try
            {
                document = JsonDocument.Parse(response);
            }
            catch (JsonException exception)
            {
                return new GameAppAiAnalysis
                {
                    AiWasAvailable = true,
                    Summary = "The model's answer was not JSON, so nothing in it was used.",
                    Prompt = prompt ?? string.Empty,
                    RawResponse = response,
                    Refusals = { $"The response could not be parsed: {exception.Message}" }
                };
            }

            using (document)
            {
                if (document.RootElement.ValueKind != JsonValueKind.Object ||
                    !document.RootElement.TryGetProperty("recommendations", out var recommendations) ||
                    recommendations.ValueKind != JsonValueKind.Array)
                {
                    return new GameAppAiAnalysis
                    {
                        AiWasAvailable = true,
                        Summary = "The model's answer did not follow the requested shape, so nothing in it was used.",
                        Prompt = prompt ?? string.Empty,
                        RawResponse = response,
                        Refusals = { "The response had no \"recommendations\" array." }
                    };
                }

                const int maxRecommendations = 25;

                var closeableNames = new HashSet<string>(
                    (backgroundProcesses ?? Array.Empty<BackgroundProcessAssessment>())
                        .Where(a => a.MayBeClosed)
                        .Select(a => a.ProcessName),
                    StringComparer.OrdinalIgnoreCase);

                var index = 0;

                foreach (var element in recommendations.EnumerateArray())
                {
                    if (index++ >= maxRecommendations)
                    {
                        refusals.Add($"Only the first {maxRecommendations} recommendations were considered.");
                        break;
                    }

                    EvaluateRecommendation(element, profile, closeableNames, suggestions, refusals);
                }
            }

            var accepted = suggestions.Count(s => s.Accepted);

            _logger.Info("GameAppAiAdvisor",
                $"AI analysis for '{profile.ResolveDisplayName()}': {accepted} suggestion(s) accepted, " +
                $"{suggestions.Count - accepted} refused, {refusals.Count} reason(s) recorded.");

            return new GameAppAiAnalysis
            {
                AiWasAvailable = true,
                Suggestions = suggestions,
                Refusals = refusals,
                Prompt = prompt ?? string.Empty,
                RawResponse = response,
                Summary = accepted == 0
                    ? "The model suggested nothing this feature is willing to do. Nothing was changed."
                    : $"{accepted} suggestion(s) survived validation. They are recommendations only: they " +
                      "still go through the safety validator and your confirmation before anything happens."
            };
        }

        private static void EvaluateRecommendation(
            JsonElement element,
            GameAppProfile profile,
            HashSet<string> closeableNames,
            List<GameAppAiSuggestion> suggestions,
            List<string> refusals)
        {
            if (element.ValueKind != JsonValueKind.Object)
            {
                refusals.Add("An entry in recommendations was not an object, so it was ignored.");
                return;
            }

            var action = GetString(element, "action");
            var target = AiRecommendationParser.SanitizeField(GetString(element, "target"), 256);
            var reason = AiRecommendationParser.SanitizeField(GetString(element, "reason"), 512);
            var risk = GetString(element, "risk");

            GameAppAiSuggestion Refused(string why) => new GameAppAiSuggestion
            {
                RawAction = action,
                Target = target,
                Reason = reason,
                Risk = RiskLevel.Critical,
                Confidence = 0,
                Accepted = false,
                RefusalReason = why
            };

            // 1. The action must be in this feature's vocabulary.
            if (string.IsNullOrWhiteSpace(action))
            {
                suggestions.Add(Refused("No action was named."));
                refusals.Add("An entry named no action, so it was refused.");
                return;
            }

            if (!IsAllowedAction(action))
            {
                suggestions.Add(Refused($"'{action}' is not one of the actions this feature offers."));
                refusals.Add($"'{action}' was refused: it is not in the allowed vocabulary.");
                return;
            }

            // 2. The risk must map through the shared mapping. An unknown risk is refused, never defaulted.
            if (!AiRecommendationParser.TryMapRiskLevel(risk, out var riskLevel))
            {
                suggestions.Add(Refused(
                    $"'{risk}' is not a risk level this application understands, so the suggestion was refused " +
                    "rather than assumed to be safe."));
                refusals.Add($"'{action}' was refused: '{risk}' is not a known risk level.");
                return;
            }

            // 3. Confidence must be a number inside 0-1. Anything else is refused.
            if (!element.TryGetProperty("confidence", out var confidenceElement) ||
                confidenceElement.ValueKind != JsonValueKind.Number ||
                !confidenceElement.TryGetDouble(out var confidence) ||
                confidence < 0d || confidence > 1d)
            {
                suggestions.Add(Refused(
                    "The confidence was missing or outside the range 0 to 1, so the suggestion was refused."));
                refusals.Add($"'{action}' on '{target}' was refused: confidence missing or out of range.");
                return;
            }

            // 4. The target must be there and must be plausible as a name rather than a path or a command.
            if (string.IsNullOrWhiteSpace(target) || !AiRecommendationParser.IsPlausibleTargetName(target))
            {
                suggestions.Add(Refused("The target was missing or was not a plausible process or application name."));
                refusals.Add($"'{action}' was refused: implausible or missing target '{target}'.");
                return;
            }

            // 5. Per-action rules. These are the same limits the planner enforces; the model cannot widen
            //    them, and there is no branch that turns an unknown action into a known one.
            if (action.Equals("close_process", StringComparison.OrdinalIgnoreCase) &&
                !closeableNames.Contains(ExecutablePathValidator.NormaliseExecutableName(target)))
            {
                suggestions.Add(Refused(
                    "That process is not one this profile may close. The model cannot add one to the list."));
                refusals.Add($"close_process on '{target}' was refused: not a permitted candidate.");
                return;
            }

            if (action.Equals("change_priority", StringComparison.OrdinalIgnoreCase) &&
                !target.Equals(profile.FileName, StringComparison.OrdinalIgnoreCase) &&
                !target.Equals(ExecutablePathValidator.NormaliseExecutableName(profile.FileName), StringComparison.OrdinalIgnoreCase))
            {
                suggestions.Add(Refused("Priority changes are only offered for this profile's own application."));
                refusals.Add($"change_priority on '{target}' was refused: not this profile's application.");
                return;
            }

            // 6. Risk ceiling. A high or critical suggestion is recorded and refused: the planner would
            //    refuse it as well, and showing it as "accepted" would be misleading.
            if (riskLevel is RiskLevel.High or RiskLevel.Critical)
            {
                suggestions.Add(new GameAppAiSuggestion
                {
                    RawAction = action,
                    Target = target,
                    Reason = reason,
                    Risk = riskLevel,
                    Confidence = confidence,
                    Accepted = false,
                    RefusalReason =
                        $"The model rated this {riskLevel}; this feature only ever offers low and medium risk changes."
                });

                refusals.Add($"'{action}' on '{target}' was refused: rated {riskLevel}.");
                return;
            }

            var actionType = AllowedActions.TryGetValue(action, out var mapped)
                ? mapped
                : (OptimizationActionType?)null;

            suggestions.Add(new GameAppAiSuggestion
            {
                RawAction = action,
                ActionType = actionType,
                Target = target,
                Reason = reason,
                Risk = riskLevel,
                Confidence = confidence,
                Accepted = true
            });
        }

        private static string GetString(JsonElement element, string name) =>
            element.ValueKind == JsonValueKind.Object &&
            element.TryGetProperty(name, out var property) &&
            property.ValueKind == JsonValueKind.String
                ? property.GetString() ?? string.Empty
                : string.Empty;
    }
}

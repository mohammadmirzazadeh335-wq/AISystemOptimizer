using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.AI
{
    /// <summary>
    /// Strict, testable parser for the recommendations a local language model returns.
    ///
    /// The model is treated as an untrusted source of DATA, never as a source of instructions.
    /// Everything it emits passes through an allow-list and a range check before it can become an
    /// <see cref="SystemInfo.OptimizationRecommendation"/>, and an <see cref="SystemInfo.OptimizationRecommendation"/>
    /// is still only a proposal - the safety layer decides whether it may run.
    ///
    /// The rules enforced here are:
    ///   * the response is bounded in size before it is parsed;
    ///   * the action type must be one of a fixed set - an unknown type is dropped, never coerced
    ///     onto a destructive default;
    ///   * the risk level must be one of a fixed set - an unknown level is dropped, so a model cannot
    ///     label a dangerous action as low risk by inventing a new string;
    ///   * the target must look like an object name and must exist in the snapshot the model was shown;
    ///   * numeric fields are clamped into a sane range;
    ///   * free text is stripped of control characters and length-capped before it is logged or shown.
    /// </summary>
    public sealed class AiRecommendationParser
    {
        /// <summary>
        /// Optional logger. The parser works without one so it can be exercised in tests.
        /// </summary>
        public ILogger? Logger { get; set; }

        /// <summary>
        /// Parse optimization recommendations from AI response
        /// </summary>
        public List<SystemInfo.OptimizationRecommendation> Parse(
            string? response,
            SystemInfo? systemInfo)
        {
            var recommendations = new List<SystemInfo.OptimizationRecommendation>();

            // Hard ceiling on how much the model may hand back. An unbounded list is both a
            // denial-of-service vector for the executor and a way to flood the review UI.
            const int maxRecommendations = 25;

            // Hard ceiling on a single string field. A model that returns a multi-megabyte "reason"
            // would otherwise be able to exhaust memory here.
            const int maxFieldLength = 512;

            try
            {
                if (response == null)
                    return recommendations;

                var trimmed = response.Trim();

                // Bounded input: an oversized response is discarded rather than parsed.
                if (trimmed.Length > MaxAiResponseCharacters)
                {
                    Logger?.Warning("AiRecommendationParser",
                        $"Discarding an oversized AI response ({trimmed.Length} characters).");
                    return recommendations;
                }

                if (!trimmed.StartsWith("{") || !trimmed.EndsWith("}"))
                    return recommendations;

                var json = JsonDocument.Parse(trimmed);
                var root = json.RootElement;

                if (!root.TryGetProperty("recommendations", out var recommendationsProperty) ||
                    recommendationsProperty.ValueKind != JsonValueKind.Array)
                {
                    return recommendations;
                }

                foreach (var recommendation in recommendationsProperty.EnumerateArray())
                {
                    if (recommendations.Count >= maxRecommendations)
                    {
                        Logger?.Warning("AiRecommendationParser",
                            $"The AI returned more than {maxRecommendations} recommendations; " +
                            "the remainder were ignored.");
                        break;
                    }

                    if (recommendation.ValueKind != JsonValueKind.Object)
                        continue;

                    // ---- FIELD 1: action type -------------------------------------------------
                    // THE CRITICAL RULE: an unknown or missing action type is REJECTED, never coerced.
                    // The previous implementation mapped every unrecognised value onto
                    // OptimizationActionType.CloseProcess, i.e. a model that emitted garbage - or an
                    // attacker who injected text into a process description - could steer the system
                    // towards the single most destructive action available. Unknown now means "drop".
                    if (!recommendation.TryGetProperty("type", out var typeProperty) ||
                        typeProperty.ValueKind != JsonValueKind.String)
                    {
                        Logger?.Warning("AiRecommendationParser",
                            "Ignoring an AI recommendation with no 'type' field.");
                        continue;
                    }

                    var typeName = typeProperty.GetString()?.Trim().ToLowerInvariant();
                    if (!TryMapActionType(typeName, out var actionType))
                    {
                        Logger?.Warning("AiRecommendationParser",
                            $"Ignoring an AI recommendation with an unknown action type: '{typeName}'");
                        continue;
                    }

                    // ---- FIELD 2: target ------------------------------------------------------
                    // The target is validated against the live system. An AI-named target that does
                    // not exist as a running process (or a known service) is dropped instead of being
                    // forwarded to the planner, so the model cannot invent privileged targets.
                    if (!recommendation.TryGetProperty("target", out var targetProperty) ||
                        targetProperty.ValueKind != JsonValueKind.String)
                    {
                        Logger?.Warning("AiRecommendationParser",
                            "Ignoring an AI recommendation with no 'target' field.");
                        continue;
                    }

                    var target = SanitizeField(targetProperty.GetString(), maxFieldLength);
                    if (target.Length == 0 || !IsPlausibleTargetName(target))
                    {
                        Logger?.Warning("AiRecommendationParser",
                            $"Ignoring an AI recommendation with an unusable target: '{target}'");
                        continue;
                    }

                    if (!TargetExistsInSystemSnapshot(actionType, target, systemInfo))
                    {
                        Logger?.Warning("AiRecommendationParser",
                            $"Ignoring an AI recommendation for a target that is not present on this " +
                            $"system: '{target}'");
                        continue;
                    }

                    var rec = new SystemInfo.OptimizationRecommendation
                    {
                        ActionType = actionType,
                        Target = target
                    };

                    // ---- FIELD 3: free text is data, never a command ---------------------------
                    if (recommendation.TryGetProperty("reason", out var reasonProperty) &&
                        reasonProperty.ValueKind == JsonValueKind.String)
                    {
                        rec.Description = SanitizeField(reasonProperty.GetString(), maxFieldLength);
                    }

                    // ---- FIELD 4: numeric fields are range-checked -----------------------------
                    if (recommendation.TryGetProperty("estimated_ram_recovery_mb", out var ramProperty) &&
                        ramProperty.ValueKind == JsonValueKind.Number &&
                        ramProperty.TryGetInt64(out var ramMb))
                    {
                        var bounded = Math.Clamp(ramMb, 0, 1024L * 1024L); // at most 1 TB
                        rec.EstimatedImprovement = $"{bounded} MB RAM";
                    }

                    if (recommendation.TryGetProperty("estimated_cpu_improvement_percent", out var cpuProperty) &&
                        cpuProperty.ValueKind == JsonValueKind.Number &&
                        cpuProperty.TryGetDouble(out var cpuPercent))
                    {
                        var bounded = Math.Clamp(cpuPercent, 0d, 100d);
                        rec.EstimatedImprovement = $"{bounded:F0}% CPU";
                    }

                    if (recommendation.TryGetProperty("risk_level", out var riskProperty) &&
                        riskProperty.ValueKind == JsonValueKind.String)
                    {
                        if (!TryMapRiskLevel(riskProperty.GetString(), out var riskLevel))
                        {
                            Logger?.Warning("AiRecommendationParser",
                                $"Ignoring an AI recommendation with an unknown risk level: " +
                                $"'{riskProperty.GetString()}'");
                            continue;
                        }

                        rec.RiskLevel = riskLevel;
                    }

                    if (recommendation.TryGetProperty("priority", out var priorityProperty) &&
                        priorityProperty.ValueKind == JsonValueKind.Number &&
                        priorityProperty.TryGetInt32(out var priority))
                    {
                        rec.Priority = Math.Clamp(priority, 1, 10);
                    }

                    rec.IsAiGenerated = true;
                    recommendations.Add(rec);
                }
            }
            catch (JsonException ex)
            {
                Logger?.Warning("AiRecommendationParser",
                    $"The AI response was not valid JSON and was ignored: {ex.Message}");
            }
            catch (Exception ex)
            {
                Logger?.Error("AiRecommendationParser", "Failed to parse optimization recommendations", null, ex);
            }

            return recommendations;
        }

        /// <summary>
        /// Maximum accepted AI response size, in characters. Anything larger is discarded unparsed.
        /// </summary>
        public const int MaxAiResponseCharacters = 256 * 1024;

        /// <summary>
        /// Map a wire action name onto a supported action type.
        /// The set is a strict allow-list: there is no default branch that produces an action, so a
        /// value that is not named here can never become executable.
        /// </summary>
        public static bool TryMapActionType(string? wireName, out OptimizationActionType actionType)
        {
            switch (wireName)
            {
                case "close_process":
                    actionType = OptimizationActionType.CloseProcess;
                    return true;

                case "disable_startup":
                    actionType = OptimizationActionType.DisableStartup;
                    return true;

                case "stop_service":
                    actionType = OptimizationActionType.StopService;
                    return true;

                case "disable_service":
                    actionType = OptimizationActionType.DisableService;
                    return true;

                case "change_priority":
                    actionType = OptimizationActionType.ChangePriority;
                    return true;

                case "clear_cache":
                    actionType = OptimizationActionType.ClearCache;
                    return true;

                default:
                    actionType = OptimizationActionType.CloseProcess;
                    return false;
            }
        }

        /// <summary>
        /// Map a wire risk level onto <see cref="RiskLevel"/>. Unknown values are refused rather than
        /// defaulted, so a model cannot down-label a dangerous action as low risk.
        /// </summary>
        public static bool TryMapRiskLevel(string? wireName, out RiskLevel riskLevel)
        {
            switch (wireName?.Trim().ToLowerInvariant())
            {
                case "low":
                    riskLevel = RiskLevel.Low;
                    return true;

                case "medium":
                    riskLevel = RiskLevel.Medium;
                    return true;

                case "high":
                    riskLevel = RiskLevel.High;
                    return true;

                case "critical":
                    riskLevel = RiskLevel.Critical;
                    return true;

                default:
                    riskLevel = RiskLevel.Critical;
                    return false;
            }
        }

        /// <summary>
        /// Trim, strip control characters and cap the length of a model-supplied string.
        ///
        /// Model output is DATA. It is shown to the user and stored in the log; it is never
        /// interpreted. Control characters are removed because they can be used to forge log lines.
        /// </summary>
        public static string SanitizeField(string? value, int maxLength)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            var builder = new StringBuilder(Math.Min(value!.Length, maxLength));

            foreach (var character in value)
            {
                if (builder.Length >= maxLength)
                    break;

                // Drop C0/C1 control characters, including CR and LF, so that model output cannot
                // inject new lines into the structured log or terminal output.
                if (char.IsControl(character))
                    continue;

                builder.Append(character);
            }

            return builder.ToString().Trim();
        }

        /// <summary>
        /// A target name must look like a process, executable or service name - not a path, a URL or
        /// a command line. This blocks path traversal and shell metacharacters at the boundary.
        /// </summary>
        public static bool IsPlausibleTargetName(string target)
        {
            if (string.IsNullOrWhiteSpace(target) || target.Length > 260)
                return false;

            foreach (var character in target)
            {
                if (!char.IsLetterOrDigit(character) &&
                    character != '.' && character != '_' && character != '-' &&
                    character != ' ' && character != '(' && character != ')' &&
                    character != '+' && character != '#')
                {
                    return false;
                }
            }

            // Reject command interpreters outright. Closing a shell a user is working in is never an
            // optimisation, and a model asking to do so is a signal that its output should not be
            // trusted for this request.
            var normalised = WindowsApiHelper.NormalizeProcessName(target);

            return !normalised.Equals("cmd", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("powershell", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("pwsh", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("wscript", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("cscript", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("mshta", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("rundll32", StringComparison.OrdinalIgnoreCase) &&
                   !normalised.Equals("conhost", StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// True when the named target actually exists in the snapshot the model was shown.
        /// The model is reasoning about a snapshot, so a target it names that is not in that snapshot
        /// is either a hallucination or an injection attempt - both are dropped.
        /// </summary>
        public static bool TargetExistsInSystemSnapshot(
            OptimizationActionType actionType,
            string target,
            SystemInfo systemInfo)
        {
            if (systemInfo == null)
                return false;

            var wanted = WindowsApiHelper.NormalizeProcessName(target);

            switch (actionType)
            {
                case OptimizationActionType.CloseProcess:
                case OptimizationActionType.ChangePriority:
                case OptimizationActionType.ChangeAffinity:
                    return systemInfo.Processes.Any(p =>
                        string.Equals(
                            WindowsApiHelper.NormalizeProcessName(p.Name),
                            wanted,
                            StringComparison.OrdinalIgnoreCase));

                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    return systemInfo.Services.Any(s =>
                        string.Equals(s.Name, target, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(s.DisplayName, target, StringComparison.OrdinalIgnoreCase));

                case OptimizationActionType.DisableStartup:
                    return systemInfo.StartupItems.Any(s =>
                        string.Equals(s.Name, target, StringComparison.OrdinalIgnoreCase));

                // Cache clearing and power-plan changes do not name a target object.
                default:
                    return true;
            }
        }
    }
}

using System;
using System.Collections.Generic;
using System.Linq;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Represents an optimization plan with actions to be executed
    /// </summary>
    public class OptimizationPlan
    {
        #region Properties

        /// <summary>
        /// Unique identifier for the plan
        /// </summary>
        public Guid Id { get; set; } = Guid.NewGuid();

        /// <summary>
        /// Plan name
        /// </summary>
        public string Name { get; set; } = "System Optimization Plan";

        /// <summary>
        /// Plan description
        /// </summary>
        public string Description { get; set; } = string.Empty;

        /// <summary>
        /// Optimization mode used
        /// </summary>
        public OptimizationMode Mode { get; set; } = OptimizationMode.Manual;

        /// <summary>
        /// When the plan was created
        /// </summary>
        public DateTime CreatedAt { get; set; } = DateTime.Now;

        /// <summary>
        /// When the plan was executed (if executed)
        /// </summary>
        public DateTime? ExecutedAt { get; set; }

        /// <summary>
        /// System information before optimization
        /// </summary>
        public SystemInfo BeforeSystemInfo { get; set; } = new SystemInfo();

        /// <summary>
        /// System information after optimization (if executed)
        /// </summary>
        public SystemInfo? AfterSystemInfo { get; set; }

        /// <summary>
        /// List of actions to be executed
        /// </summary>
        public List<OptimizationAction> Actions { get; set; } = new List<OptimizationAction>();

        /// <summary>
        /// List of actions that were skipped
        /// </summary>
        public List<OptimizationAction> SkippedActions { get; set; } = new List<OptimizationAction>();

        /// <summary>
        /// List of actions that failed
        /// </summary>
        public List<OptimizationAction> FailedActions { get; set; } = new List<OptimizationAction>();

        /// <summary>
        /// Overall risk level of the plan
        /// </summary>
        public RiskLevel OverallRiskLevel
        {
            get
            {
                if (Actions.Count == 0) return RiskLevel.Low;
                
                var highestRisk = Actions.Max(a => a.RiskLevel);
                return highestRisk;
            }
        }

        /// <summary>
        /// Estimated RAM recovery in bytes.
        ///
        /// The total is taken over actions whose <see cref="OptimizationAction.ResourceType"/> is
        /// <see cref="ResourceType.RAM"/> - that field is what the planner sets to say which resource an
        /// action is meant to recover, and <see cref="OptimizationAction.EstimatedResourceRecovery"/> is
        /// documented as the bytes that action frees.
        ///
        /// WHY THIS IS NOT FILTERED BY ACTION TYPE:
        /// an earlier version summed every CloseProcess and StopService, regardless of which resource
        /// the action was created for. The planner creates close-process actions with a CPU resource
        /// type when the motivation is CPU contention, so those bytes were being counted as expected
        /// memory recovery. The number shown to the user was therefore larger than what the plan could
        /// actually deliver, which is exactly the kind of inflated claim this application must not make.
        /// </summary>
        public long EstimatedRamRecovery
        {
            get
            {
                return Actions
                    .Where(a => a.ResourceType == ResourceType.RAM)
                    .Sum(a => a.EstimatedResourceRecovery);
            }
        }

        /// <summary>
        /// Estimated CPU improvement percentage
        /// </summary>
        public float EstimatedCpuImprovement
        {
            get
            {
                var cpuActions = Actions
                    .Where(a => a.ResourceType == ResourceType.CPU);
                
                return cpuActions.Sum(a => a.EstimatedImprovementPercentage);
            }
        }

        /// <summary>
        /// Total number of actions
        /// </summary>
        public int TotalActionCount => Actions.Count;

        /// <summary>
        /// Number of successful actions
        /// </summary>
        public int SuccessfulActionCount => Actions.Count(a => a.Status == ActionStatus.Success);

        /// <summary>
        /// Number of failed actions
        /// </summary>
        public int FailedActionCount => FailedActions.Count;

        /// <summary>
        /// Number of skipped actions
        /// </summary>
        public int SkippedActionCount => SkippedActions.Count;

        /// <summary>
        /// Whether the plan has been executed
        /// </summary>
        public bool IsExecuted => ExecutedAt.HasValue;

        /// <summary>
        /// Whether the plan was successful
        /// </summary>
        public bool IsSuccessful => IsExecuted && FailedActionCount == 0;

        /// <summary>
        /// Whether the plan can be undone
        /// </summary>
        public bool CanUndo => Actions.Any(a => a.CanUndo);

        /// <summary>
        /// Whether AI was used in generating this plan
        /// </summary>
        public bool AiUsed { get; set; }

        /// <summary>
        /// AI-generated summary
        /// </summary>
        public string AiSummary { get; set; } = string.Empty;

        /// <summary>
        /// User who created the plan
        /// </summary>
        public string CreatedBy { get; set; } = Environment.UserName;

        /// <summary>
        /// Whether the plan was created automatically
        /// </summary>
        public bool IsAutomatic { get; set; }

        #endregion

        #region Helper Properties

        /// <summary>
        /// Formatted estimated RAM recovery
        /// </summary>
        public string FormattedEstimatedRamRecovery
        {
            get
            {
                var mb = EstimatedRamRecovery / (1024.0 * 1024.0);
                var gb = mb / 1024.0;
                
                if (gb >= 1)
                    return $"{gb:F2} GB";
                else if (mb >= 1)
                    return $"{mb:F2} MB";
                else
                    return $"{EstimatedRamRecovery / 1024.0:F2} KB";
            }
        }

        /// <summary>
        /// Formatted creation time
        /// </summary>
        public string FormattedCreatedAt => CreatedAt.ToString("yyyy-MM-dd HH:mm:ss");

        /// <summary>
        /// Formatted execution time
        /// </summary>
        public string FormattedExecutedAt => ExecutedAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? "Not executed";

        /// <summary>
        /// Success rate percentage
        /// </summary>
        public float SuccessRate
        {
            get
            {
                if (TotalActionCount == 0) return 0;
                return (float)((double)SuccessfulActionCount / TotalActionCount * 100);
            }
        }

        #endregion

        #region Methods

        /// <summary>
        /// Add an action to the plan
        /// </summary>
        public void AddAction(OptimizationAction action)
        {
            if (action != null)
            {
                Actions.Add(action);
            }
        }

        /// <summary>
        /// Add multiple actions to the plan
        /// </summary>
        public void AddActions(IEnumerable<OptimizationAction> actions)
        {
            if (actions != null)
            {
                Actions.AddRange(actions);
            }
        }

        /// <summary>
        /// Remove an action from the plan
        /// </summary>
        public bool RemoveAction(OptimizationAction action)
        {
            return Actions.Remove(action);
        }

        /// <summary>
        /// Remove action by index
        /// </summary>
        public bool RemoveAction(int index)
        {
            if (index >= 0 && index < Actions.Count)
            {
                Actions.RemoveAt(index);
                return true;
            }
            return false;
        }

        /// <summary>
        /// Clear all actions
        /// </summary>
        public void ClearActions()
        {
            Actions.Clear();
            SkippedActions.Clear();
            FailedActions.Clear();
        }

        /// <summary>
        /// Get actions by risk level
        /// </summary>
        public List<OptimizationAction> GetActionsByRiskLevel(RiskLevel riskLevel)
        {
            return Actions.FindAll(a => a.RiskLevel == riskLevel);
        }

        /// <summary>
        /// Get actions by resource type
        /// </summary>
        public List<OptimizationAction> GetActionsByResourceType(ResourceType resourceType)
        {
            return Actions.FindAll(a => a.ResourceType == resourceType);
        }

        /// <summary>
        /// Get actions by action type
        /// </summary>
        public List<OptimizationAction> GetActionsByActionType(OptimizationActionType actionType)
        {
            return Actions.FindAll(a => a.ActionType == actionType);
        }

        /// <summary>
        /// Get high-risk actions
        /// </summary>
        public List<OptimizationAction> GetHighRiskActions()
        {
            return Actions.FindAll(a => a.RiskLevel == RiskLevel.High || a.RiskLevel == RiskLevel.Critical);
        }

        /// <summary>
        /// Get safe actions
        /// </summary>
        public List<OptimizationAction> GetSafeActions()
        {
            return Actions.FindAll(a => a.RiskLevel == RiskLevel.Low);
        }

        /// <summary>
        /// Sort actions by priority (highest first)
        /// </summary>
        public void SortByPriority()
        {
            Actions.Sort((a, b) => b.Priority.CompareTo(a.Priority));
        }

        /// <summary>
        /// Sort actions by estimated resource recovery (highest first)
        /// </summary>
        public void SortByResourceRecovery()
        {
            Actions.Sort((a, b) => b.EstimatedResourceRecovery.CompareTo(a.EstimatedResourceRecovery));
        }

        /// <summary>
        /// Sort actions by risk level (safest first)
        /// </summary>
        public void SortByRiskLevel()
        {
            Actions.Sort((a, b) => a.RiskLevel.CompareTo(b.RiskLevel));
        }

        /// <summary>
        /// Generate a summary of the plan
        /// </summary>
        public string GenerateSummary()
        {
            var summary = new System.Text.StringBuilder();
            
            summary.AppendLine($"Optimization Plan: {Name}");
            summary.AppendLine($"Created: {FormattedCreatedAt}");
            summary.AppendLine($"Mode: {Mode}");
            summary.AppendLine($"AI Used: {(AiUsed ? "Yes" : "No")}");
            summary.AppendLine();
            
            summary.AppendLine("=== Summary ===");
            summary.AppendLine($"Total Actions: {TotalActionCount}");
            summary.AppendLine($"Estimated RAM Recovery: {FormattedEstimatedRamRecovery}");
            summary.AppendLine($"Estimated CPU Improvement: {EstimatedCpuImprovement:F1}%");
            summary.AppendLine($"Overall Risk Level: {OverallRiskLevel}");
            summary.AppendLine();
            
            summary.AppendLine("=== Actions ===");
            foreach (var action in Actions)
            {
                summary.AppendLine($"  - {action.ActionType}: {action.Target} (Risk: {action.RiskLevel}, Recovery: {action.FormattedEstimatedRecovery})");
            }
            
            if (SkippedActions.Count > 0)
            {
                summary.AppendLine();
                summary.AppendLine("=== Skipped Actions ===");
                foreach (var action in SkippedActions)
                {
                    summary.AppendLine($"  - {action.ActionType}: {action.Target} (Reason: {action.SkipReason})");
                }
            }
            
            if (FailedActions.Count > 0)
            {
                summary.AppendLine();
                summary.AppendLine("=== Failed Actions ===");
                foreach (var action in FailedActions)
                {
                    summary.AppendLine($"  - {action.ActionType}: {action.Target} (Error: {action.ErrorMessage})");
                }
            }
            
            if (!string.IsNullOrEmpty(AiSummary))
            {
                summary.AppendLine();
                summary.AppendLine("=== AI Summary ===");
                summary.AppendLine(AiSummary);
            }
            
            return summary.ToString();
        }

        /// <summary>
        /// Create a copy of the plan
        /// </summary>
        public OptimizationPlan Clone()
        {
            var clone = new OptimizationPlan
            {
                Id = Id,
                Name = Name,
                Description = Description,
                Mode = Mode,
                CreatedAt = CreatedAt,
                ExecutedAt = ExecutedAt,
                BeforeSystemInfo = BeforeSystemInfo,
                AfterSystemInfo = AfterSystemInfo,
                AiUsed = AiUsed,
                AiSummary = AiSummary,
                CreatedBy = CreatedBy,
                IsAutomatic = IsAutomatic
            };
            
            clone.Actions.AddRange(Actions.Select(a => a.Clone()));
            clone.SkippedActions.AddRange(SkippedActions.Select(a => a.Clone()));
            clone.FailedActions.AddRange(FailedActions.Select(a => a.Clone()));
            
            return clone;
        }

        #endregion
    }
}

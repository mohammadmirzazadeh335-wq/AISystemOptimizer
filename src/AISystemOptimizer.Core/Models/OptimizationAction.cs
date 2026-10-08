using System;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Represents a single optimization action.
    /// Immutable in spirit: every action carries its own risk level, undo information
    /// and the evidence that justified it, so that the Safety Layer can audit it.
    /// </summary>
    public class OptimizationAction : IEquatable<OptimizationAction>, IComparable<OptimizationAction>
    {
        #region Properties

        /// <summary>
        /// Unique identifier for the action
        /// </summary>
        public Guid Id { get; set; } = Guid.NewGuid();

        /// <summary>
        /// Action type
        /// </summary>
        public OptimizationActionType ActionType { get; set; } = OptimizationActionType.CloseProcess;

        /// <summary>
        /// Target process, service, or component name
        /// </summary>
        public string Target { get; set; } = string.Empty;

        /// <summary>
        /// Target process ID (if applicable)
        /// </summary>
        public int TargetPid { get; set; }

        /// <summary>
        /// Creation timestamp (UTC) of the process observed when this action was planned.
        ///
        /// This is the anti-TOCTOU / anti-PID-reuse guard. Windows recycles process ids, so a pid
        /// alone is <b>not</b> an identity: between planning and execution the original process may
        /// have exited and the same pid may have been reassigned to an unrelated process. The
        /// executor re-reads the live creation time and refuses the action when it differs.
        ///
        /// <see cref="DateTime.MinValue"/> means "no identity was captured" - execution code must
        /// then refuse process-terminating actions rather than assume the pid is still valid.
        /// </summary>
        public DateTime TargetCreationTimeUtc { get; set; } = DateTime.MinValue;

        /// <summary>
        /// Executable image path observed when this action was planned, used to corroborate identity.
        /// Empty when the path could not be read (protected process); never treated as a match.
        /// </summary>
        public string TargetImagePath { get; set; } = string.Empty;

        /// <summary>
        /// Normalised process name observed when this action was planned (no directory, no .exe).
        /// </summary>
        public string TargetProcessName { get; set; } = string.Empty;

        /// <summary>
        /// True when a process identity (pid + creation time) was captured for this action.
        /// </summary>
        public bool HasProcessIdentity =>
            TargetPid > 0 && TargetCreationTimeUtc != DateTime.MinValue;

        /// <summary>
        /// Capture the identity of a live process onto this action. Called by the planner the moment
        /// it decides to propose a process action, never later.
        /// </summary>
        public void CaptureProcessIdentity(ProcessInfo process)
        {
            if (process == null)
                return;

            TargetPid = process.Id;
            TargetImagePath = process.Path ?? string.Empty;
            TargetProcessName = WindowsApiHelper.NormalizeProcessName(process.Name);
            TargetCreationTimeUtc = process.CreationTimeUtc;
        }

        /// <summary>
        /// Target path (if applicable)
        /// </summary>
        public string TargetPath { get; set; } = string.Empty;

        /// <summary>
        /// Resource type affected
        /// </summary>
        public ResourceType ResourceType { get; set; } = ResourceType.RAM;

        /// <summary>
        /// Risk level of the action
        /// </summary>
        public RiskLevel RiskLevel { get; set; } = RiskLevel.Medium;

        /// <summary>
        /// Action description (what will happen)
        /// </summary>
        public string Description { get; set; } = string.Empty;

        /// <summary>
        /// Reason for the action (why it is proposed)
        /// </summary>
        public string Reason { get; set; } = string.Empty;

        /// <summary>
        /// Estimated resource recovery in bytes (used for RAM-type actions)
        /// </summary>
        public long EstimatedResourceRecovery { get; set; }

        /// <summary>
        /// Estimated improvement percentage (used for CPU-type actions)
        /// </summary>
        public float EstimatedImprovementPercentage { get; set; }

        /// <summary>
        /// Priority (1-10, higher is more important)
        /// </summary>
        public int Priority { get; set; } = 5;

        /// <summary>
        /// Whether the action has been executed
        /// </summary>
        public bool IsExecuted { get; set; }

        /// <summary>
        /// Action status
        /// </summary>
        public ActionStatus Status { get; set; } = ActionStatus.Pending;

        /// <summary>
        /// When the action was executed
        /// </summary>
        public DateTime? ExecutedAt { get; set; }

        /// <summary>
        /// Error message if the action failed
        /// </summary>
        public string ErrorMessage { get; set; } = string.Empty;

        /// <summary>
        /// Whether the action can be undone
        /// </summary>
        public bool CanUndo { get; set; }

        /// <summary>
        /// Undo action (if applicable)
        /// </summary>
        public OptimizationAction? UndoAction { get; set; }

        /// <summary>
        /// Whether the action was confirmed by the user
        /// </summary>
        public bool UserConfirmed { get; set; }

        /// <summary>
        /// Whether the action was AI-recommended
        /// </summary>
        public bool AiRecommended { get; set; }

        /// <summary>
        /// AI confidence score (0-1)
        /// </summary>
        public float AiConfidence { get; set; }

        /// <summary>
        /// Skip reason (if skipped)
        /// </summary>
        public string SkipReason { get; set; } = string.Empty;

        /// <summary>
        /// Whether the action requires administrator privileges
        /// </summary>
        public bool RequiresAdmin { get; set; }

        /// <summary>
        /// Process information (if applicable)
        /// </summary>
        public ProcessInfo? ProcessInfo { get; set; }

        /// <summary>
        /// Service information (if applicable)
        /// </summary>
        public SystemInfo.ServiceInfo? ServiceInfo { get; set; }

        /// <summary>
        /// Startup item information (if applicable)
        /// </summary>
        public SystemInfo.StartupItem? StartupItem { get; set; }

        #endregion

        #region Helper Properties

        /// <summary>
        /// Formatted estimated recovery
        /// </summary>
        public string FormattedEstimatedRecovery
        {
            get
            {
                if (ResourceType == ResourceType.RAM)
                {
                    var mb = EstimatedResourceRecovery / (1024.0 * 1024.0);
                    var gb = mb / 1024.0;

                    if (gb >= 1)
                        return $"{gb:F2} GB";
                    else if (mb >= 1)
                        return $"{mb:F2} MB";
                    else
                        return $"{EstimatedResourceRecovery / 1024.0:F2} KB";
                }
                else if (ResourceType == ResourceType.CPU)
                {
                    return $"{EstimatedImprovementPercentage:F1}% CPU";
                }
                else
                {
                    return $"{EstimatedResourceRecovery}";
                }
            }
        }

        /// <summary>
        /// Formatted execution time
        /// </summary>
        public string FormattedExecutedAt => ExecutedAt?.ToString("HH:mm:ss") ?? "Not executed";

        /// <summary>
        /// Whether this action is safe enough to run without user confirmation
        /// </summary>
        public bool IsAutoSafe => RiskLevel == RiskLevel.Low && CanUndo;

        #endregion

        #region Methods

        /// <summary>
        /// Mark the action as executed successfully.
        /// NOTE: This does not perform the operation - SafeExecutor does that.
        /// </summary>
        public void MarkAsExecuted()
        {
            IsExecuted = true;
            ExecutedAt = DateTime.Now;
            Status = ActionStatus.Success;
        }

        /// <summary>
        /// Mark the action as failed
        /// </summary>
        public void MarkAsFailed(string errorMessage)
        {
            IsExecuted = true;
            ExecutedAt = DateTime.Now;
            Status = ActionStatus.Failed;
            ErrorMessage = errorMessage;
        }

        /// <summary>
        /// Mark the action as skipped
        /// </summary>
        public void MarkAsSkipped(string reason)
        {
            Status = ActionStatus.Skipped;
            SkipReason = reason;
        }

        /// <summary>
        /// Mark the action as rejected by the safety layer
        /// </summary>
        public void MarkAsRejected(string reason)
        {
            Status = ActionStatus.Rejected;
            SkipReason = reason;
        }

        /// <summary>
        /// Create the inverse action that undoes this one (when technically possible).
        /// </summary>
        public OptimizationAction? CreateUndoAction()
        {
            // Actions that cannot be reverted do not get an undo action.
            if (!CanUndo)
                return null;

            var undo = new OptimizationAction
            {
                ActionType = GetInverseActionType(ActionType),
                Target = Target,
                TargetPid = TargetPid,
                TargetPath = TargetPath,
                TargetCreationTimeUtc = TargetCreationTimeUtc,
                TargetImagePath = TargetImagePath,
                TargetProcessName = TargetProcessName,
                ResourceType = ResourceType,
                RiskLevel = RiskLevel.Low, // restoring is deliberately as safe as possible
                Description = $"Undo: {Description}",
                Reason = $"Restore previous state for '{Target}'",
                Priority = Priority,
                CanUndo = false,
                AiRecommended = false,
                RequiresAdmin = RequiresAdmin,
                ProcessInfo = ProcessInfo,
                ServiceInfo = ServiceInfo,
                StartupItem = StartupItem
            };

            return undo;
        }

        /// <summary>
        /// Build the undo action and attach it to this action.
        /// </summary>
        public void AttachUndoAction()
        {
            UndoAction = CreateUndoAction();
        }

        /// <summary>
        /// Map an action type to the action type that reverses it.
        /// </summary>
        private static OptimizationActionType GetInverseActionType(OptimizationActionType actionType)
        {
            switch (actionType)
            {
                // Closing a process cannot be undone by an API call. We flag it as
                // non-undoable, but if an undo is ever requested we re-launch it.
                case OptimizationActionType.CloseProcess:
                    return OptimizationActionType.CloseProcess;

                case OptimizationActionType.DisableStartup:
                    return OptimizationActionType.DisableStartup; // re-enable -> handled by executor flag

                case OptimizationActionType.StopService:
                    return OptimizationActionType.StopService;    // restart

                case OptimizationActionType.DisableService:
                    return OptimizationActionType.DisableService; // re-enable

                case OptimizationActionType.ClearCache:
                    return OptimizationActionType.ClearCache;     // not reversible

                case OptimizationActionType.ChangePriority:
                    return OptimizationActionType.ChangePriority; // restore previous priority

                case OptimizationActionType.ChangeAffinity:
                    return OptimizationActionType.ChangeAffinity; // restore previous affinity

                case OptimizationActionType.UninstallApplication:
                    return OptimizationActionType.UninstallApplication; // not reversible

                case OptimizationActionType.AdjustPowerSettings:
                    return OptimizationActionType.AdjustPowerSettings;   // restore previous plan

                default:
                    return OptimizationActionType.CloseProcess;
            }
        }

        /// <summary>
        /// Create a deep copy of the action
        /// </summary>
        public OptimizationAction Clone()
        {
            var clone = new OptimizationAction
            {
                Id = Id,
                ActionType = ActionType,
                Target = Target,
                TargetPid = TargetPid,
                TargetPath = TargetPath,
                TargetCreationTimeUtc = TargetCreationTimeUtc,
                TargetImagePath = TargetImagePath,
                TargetProcessName = TargetProcessName,
                ResourceType = ResourceType,
                RiskLevel = RiskLevel,
                Description = Description,
                Reason = Reason,
                EstimatedResourceRecovery = EstimatedResourceRecovery,
                EstimatedImprovementPercentage = EstimatedImprovementPercentage,
                Priority = Priority,
                IsExecuted = IsExecuted,
                Status = Status,
                ExecutedAt = ExecutedAt,
                ErrorMessage = ErrorMessage,
                CanUndo = CanUndo,
                UserConfirmed = UserConfirmed,
                AiRecommended = AiRecommended,
                AiConfidence = AiConfidence,
                SkipReason = SkipReason,
                RequiresAdmin = RequiresAdmin,
                ProcessInfo = ProcessInfo,
                ServiceInfo = ServiceInfo,
                StartupItem = StartupItem
            };

            if (UndoAction != null)
                clone.UndoAction = UndoAction.Clone();

            return clone;
        }

        #endregion

        #region IEquatable Implementation

        public bool Equals(OptimizationAction? other)
        {
            if (other is null) return false;
            return Id == other.Id;
        }

        public override bool Equals(object? obj)
        {
            return Equals(obj as OptimizationAction);
        }

        public override int GetHashCode()
        {
            return Id.GetHashCode();
        }

        #endregion

        #region IComparable Implementation

        public int CompareTo(OptimizationAction? other)
        {
            if (other is null) return 1;
            return Priority.CompareTo(other.Priority);
        }

        #endregion

        #region Overrides

        public override string ToString()
        {
            return $"{ActionType}: {Target} (Risk: {RiskLevel}, Priority: {Priority}, Status: {Status})";
        }

        #endregion
    }
}

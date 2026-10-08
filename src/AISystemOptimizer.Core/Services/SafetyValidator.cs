using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for validating the safety of optimization actions
    /// This is the final layer of protection before any action is executed
    /// </summary>
    public class SafetyValidator : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly ProcessAnalyzer _processAnalyzer;
        private readonly List<OptimizationAction> _rejectedActions = new List<OptimizationAction>();

        // Why an action was refused, keyed by the action's own id. A refusal that cannot be explained
        // to the user is not a useful refusal - and a validation report that only says "false" cannot
        // be audited.
        private readonly Dictionary<Guid, string> _rejectionReasons = new Dictionary<Guid, string>();

        private readonly object _lock = new object();

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new safety validator
        /// </summary>
        public SafetyValidator(
            ILogger logger = null,
            AppConfig config = null,
            ProcessAnalyzer processAnalyzer = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _processAnalyzer = processAnalyzer ?? new ProcessAnalyzer(logger, config);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Validate an optimization action
        /// </summary>
        public bool ValidateAction(OptimizationAction action, SystemInfo systemInfo = null)
        {
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? new SystemScanner(_logger, _config).Scan();
                
                _logger.Info("SafetyValidator", 
                    $"Validating action: {action.ActionType} on {action.Target}");
                
                // Check if the action is explicitly rejected
                if (IsActionRejected(action))
                {
                    _logger.Warning("SafetyValidator", 
                        $"Action rejected (previously rejected): {action.ActionType} on {action.Target}");
                    return false;
                }
                
                // Run through all validation checks
                var validationResult = PerformValidation(action, systemInfo);
                
                if (!validationResult.IsValid)
                {
                    _logger.Warning("SafetyValidator", 
                        $"Action rejected: {action.ActionType} on {action.Target}. Reason: {validationResult.RejectionReason}");
                    
                    // Add to rejected actions list
                    lock (_lock)
                    {
                        _rejectedActions.Add(action);
                        _rejectionReasons[action.Id] = validationResult.RejectionReason;

                        // Bounded: a long session must not accumulate reasons forever.
                        if (_rejectionReasons.Count > 500)
                        {
                            foreach (var stale in _rejectionReasons.Keys.Take(100).ToList())
                                _rejectionReasons.Remove(stale);
                        }
                    }
                    
                    return false;
                }
                
                _logger.Info("SafetyValidator", 
                    $"Action validated: {action.ActionType} on {action.Target}");

                lock (_lock)
                {
                    // The same action object may have been corrected and re-validated.
                    _rejectionReasons.Remove(action.Id);
                }

                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("SafetyValidator", 
                    $"Validation failed for action: {action.ActionType} on {action.Target}", 
                    null, ex);
                return false;
            }
        }

        /// <summary>
        /// Validate multiple optimization actions
        /// </summary>
        public Dictionary<OptimizationAction, bool> ValidateActions(
            List<OptimizationAction> actions,
            SystemInfo systemInfo = null)
        {
            var results = new Dictionary<OptimizationAction, bool>();
            
            foreach (var action in actions)
            {
                results[action] = ValidateAction(action, systemInfo);
            }
            
            return results;
        }

        /// <summary>
        /// Validate an optimization plan
        /// </summary>
        public bool ValidatePlan(OptimizationPlan plan, SystemInfo systemInfo = null)
        {
            if (plan == null || plan.Actions.Count == 0)
                return true; // Empty plan is safe
            
            // Validate each action in the plan
            var validationResults = ValidateActions(plan.Actions, systemInfo);
            
            // If any action is rejected, the plan is rejected
            if (validationResults.Values.Any(result => !result))
                return false;
            
            // Additional plan-level validation
            return ValidatePlanLevel(plan, systemInfo);
        }

        /// <summary>
        /// Why an action was refused, or null when it was not refused. The reason names the rule that
        /// stopped it, so the interface and the validation report can say what happened instead of
        /// showing a bare failure.
        /// </summary>
        public string? GetRejectionReason(OptimizationAction action)
        {
            if (action == null)
                return null;

            lock (_lock)
            {
                return _rejectionReasons.TryGetValue(action.Id, out var reason) ? reason : null;
            }
        }

        /// <summary>
        /// Check if an action is explicitly rejected
        /// </summary>
        public bool IsActionRejected(OptimizationAction action)
        {
            lock (_lock)
            {
                return _rejectedActions.Any(a => 
                    a.ActionType == action.ActionType &&
                    a.Target == action.Target);
            }
        }

        /// <summary>
        /// Clear the list of rejected actions
        /// </summary>
        public void ClearRejectedActions()
        {
            lock (_lock)
            {
                _rejectedActions.Clear();
                _rejectionReasons.Clear();
            }
        }

        /// <summary>
        /// Get the list of rejected actions
        /// </summary>
        public List<OptimizationAction> GetRejectedActions()
        {
            lock (_lock)
            {
                return new List<OptimizationAction>(_rejectedActions);
            }
        }

        /// <summary>
        /// Remove an action from the rejected list
        /// </summary>
        public bool RemoveRejectedAction(OptimizationAction action)
        {
            lock (_lock)
            {
                return _rejectedActions.Remove(action);
            }
        }

        /// <summary>
        /// Check if the safety layer is enabled
        /// </summary>
        public bool IsSafetyLayerEnabled => _config.SafetyLayerEnabled;

        /// <summary>
        /// Decide whether this action needs an explicit confirmation from the user
        /// before the executor may run it.
        ///
        /// Rule: if the action is not trivially safe AND reversible, ask.
        /// </summary>
        public bool RequiresUserConfirmation(OptimizationAction action, SystemInfo? systemInfo = null)
        {
            if (action == null) return true;

            // Anything above the auto risk ceiling always needs a human.
            if (action.RiskLevel > _config.MaxAutoRiskLevel) return true;

            // Medium risk needs confirmation unless the user opted out.
            if (action.RiskLevel == RiskLevel.Medium && _config.RequireConfirmationForMediumRisk) return true;

            // Irreversible actions need confirmation even at low risk.
            if (!action.CanUndo) return true;

            // Elevation-bound actions need confirmation when we are not elevated.
            if (action.RequiresAdmin && !WindowsApiHelper.IsAdministrator()) return true;

            // Anything the AI suggested needs a human unless explicitly disabled.
            if (action.AiRecommended && _config.RequireAiConfirmation) return true;

            return false;
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Perform validation on an action
        /// </summary>
        private ValidationResult PerformValidation(OptimizationAction action, SystemInfo systemInfo)
        {
            var result = new ValidationResult { Action = action, IsValid = true };
            
            // Check 1: Safety layer must be enabled
            if (!IsSafetyLayerEnabled)
            {
                result.IsValid = false;
                result.RejectionReason = "Safety layer is disabled";
                return result;
            }
            
            // Check 2: Cannot perform actions that are above the maximum allowed risk level
            if (action.RiskLevel > _config.MaxAutoRiskLevel)
            {
                result.IsValid = false;
                result.RejectionReason = $"Action risk level ({action.RiskLevel}) exceeds maximum allowed ({_config.MaxAutoRiskLevel})";
                return result;
            }
            
            // Check 3: Cannot perform high risk actions if not allowed
            if (action.RiskLevel == RiskLevel.High && !_config.AllowHighRiskActions)
            {
                result.IsValid = false;
                result.RejectionReason = "High risk actions are not allowed";
                return result;
            }
            
            // Check 4: Cannot perform critical risk actions if not allowed
            if (action.RiskLevel == RiskLevel.Critical && !_config.AllowCriticalRiskActions)
            {
                result.IsValid = false;
                result.RejectionReason = "Critical risk actions are not allowed";
                return result;
            }
            
            // Check 5: Cannot perform actions on critical processes.
            //
            // The path recorded with the action is passed in so that the layered checks (driver store,
            // Windows directory) can run as well as the name lists. Checking the name alone left
            // processes that are only recognisable from their path - a driver loaded from Program Files,
            // for instance - outside the protection.
            if (action.ActionType == OptimizationActionType.CloseProcess &&
                CriticalProcesses.IsCritical(
                    action.Target,
                    FirstNonEmpty(action.TargetImagePath, action.TargetPath)))
            {
                result.IsValid = false;
                result.RejectionReason = $"Cannot perform action on critical process '{action.Target}'";
                return result;
            }
            
            // Check 6: Cannot perform actions on blacklisted processes
            if (action.ActionType == OptimizationActionType.CloseProcess &&
                _config.BlacklistedProcesses.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
            {
                result.IsValid = false;
                result.RejectionReason = "Process is blacklisted";
                return result;
            }
            
            // Check 7: Cannot perform actions on blacklisted services
            if ((action.ActionType == OptimizationActionType.StopService ||
                 action.ActionType == OptimizationActionType.DisableService) &&
                _config.BlacklistedServices.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
            {
                result.IsValid = false;
                result.RejectionReason = "Service is blacklisted";
                return result;
            }
            
            // Check 8: Cannot perform actions on blacklisted startup items
            if (action.ActionType == OptimizationActionType.DisableStartup &&
                _config.BlacklistedStartupItems.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
            {
                result.IsValid = false;
                result.RejectionReason = "Startup item is blacklisted";
                return result;
            }
            
            // Check 9: Cannot disable Windows Defender
            if ((action.ActionType == OptimizationActionType.StopService ||
                 action.ActionType == OptimizationActionType.DisableService) &&
                action.Target.Equals("WinDefend", StringComparison.OrdinalIgnoreCase))
            {
                result.IsValid = false;
                result.RejectionReason = "Cannot disable Windows Defender";
                return result;
            }
            
            // Check 10: Cannot disable Windows Firewall
            if ((action.ActionType == OptimizationActionType.StopService ||
                 action.ActionType == OptimizationActionType.DisableService) &&
                action.Target.Equals("MpsSvc", StringComparison.OrdinalIgnoreCase))
            {
                result.IsValid = false;
                result.RejectionReason = "Cannot disable Windows Firewall";
                return result;
            }
            
            // Check 11: Cannot disable UAC-related services
            if ((action.ActionType == OptimizationActionType.StopService ||
                 action.ActionType == OptimizationActionType.DisableService) &&
                (action.Target.Equals("UserAccountControl", StringComparison.OrdinalIgnoreCase) ||
                 action.Target.Equals("UAC", StringComparison.OrdinalIgnoreCase)))
            {
                result.IsValid = false;
                result.RejectionReason = "Cannot disable UAC-related services";
                return result;
            }
            
            // Check 12: Cannot perform actions that require admin if not running as admin
            if (action.RequiresAdmin && !WindowsApiHelper.IsAdministrator())
            {
                result.IsValid = false;
                result.RejectionReason = "Action requires administrator privileges";
                return result;
            }
            
            // Check 13: Cannot close a process that is in use, and the identity of the process that
            //           is about to be closed must still be the one that was planned.
            //
            // NOTE ON THE PREVIOUS IMPLEMENTATION: this check used to resolve the target with
            //   systemInfo.Processes.FirstOrDefault(p => p.Name.Equals(action.Target, ...))
            // which is wrong whenever a single executable runs more than once - Chrome, Discord,
            // Steam and svchost all do. FirstOrDefault() then validates instance #1 while the action
            // targets instance #4, so a protected instance could be waved through. The target is now
            // resolved by pid, and every instance of the target executable is treated as protected
            // if any one of them is in use.
            if (action.ActionType == OptimizationActionType.CloseProcess)
            {
                var targetInstances = ResolveTargetProcesses(action, systemInfo);

                if (targetInstances.Count == 0)
                {
                    result.IsValid = false;
                    result.RejectionReason =
                        "The target process is no longer running, so the action was dropped.";
                    return result;
                }

                foreach (var instance in targetInstances)
                {
                    if (instance.IsActive || instance.HasVisibleWindow)
                    {
                        result.IsValid = false;
                        result.RejectionReason =
                            $"'{instance.Name}' (PID {instance.Id}) is in use " +
                            $"{(instance.IsActive ? "(foreground/responding)" : "(has an open window)")} " +
                            "and will not be closed automatically.";
                        return result;
                    }
                }

                // Identity guard: the recorded creation time must still describe the process that
                // owns this pid, otherwise the pid was recycled and this is a different process.
                var identity = ValidateProcessIdentity(action, targetInstances[0]);
                if (!identity.IsValid)
                {
                    result.IsValid = false;
                    result.RejectionReason = identity.RejectionReason;
                    return result;
                }
            }
            else if (action.ActionType != OptimizationActionType.ClearCache &&
                     action.ActionType != OptimizationActionType.AdjustPowerSettings &&
                     action.TargetPid > 0)
            {
                // Any other pid-scoped action is held to the same identity rule.
                var identity = ValidateProcessIdentity(action, null);
                if (!identity.IsValid)
                {
                    result.IsValid = false;
                    result.RejectionReason = identity.RejectionReason;
                    return result;
                }
            }
            
            // Check 15: Cannot disable Windows system services
            if ((action.ActionType == OptimizationActionType.StopService ||
                 action.ActionType == OptimizationActionType.DisableService))
            {
                var service = systemInfo.Services.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (service != null && service.IsWindowsService && service.IsCritical)
                {
                    result.IsValid = false;
                    result.RejectionReason = "Cannot disable critical Windows service";
                    return result;
                }
            }
            
            // Check 16: Cannot perform too many actions at once
            // This is a plan-level check, so we don't implement it here
            
            // Check 17: Validate based on system state
            if (!ValidateSystemState(action, systemInfo))
            {
                result.IsValid = false;
                result.RejectionReason = "System state does not allow this action";
                return result;
            }
            
            // Check 18: Validate based on user configuration
            if (!ValidateUserConfiguration(action))
            {
                result.IsValid = false;
                result.RejectionReason = "User configuration does not allow this action";
                return result;
            }
            
            return result;
        }

        /// <summary>
        /// The first argument that is not null, empty or whitespace.
        /// </summary>
        private static string FirstNonEmpty(params string?[] candidates)
        {
            foreach (var candidate in candidates)
            {
                if (!string.IsNullOrWhiteSpace(candidate))
                    return candidate!;
            }

            return string.Empty;
        }

        /// <summary>
        /// Resolve the live instances an action is aimed at.
        ///
        /// The pid decides when it is known. The name is only a fallback for actions that were
        /// produced before an identity was captured, and in that case <b>all</b> matching instances
        /// are returned so that a single in-use instance protects every sibling.
        /// </summary>
        private static List<ProcessInfo> ResolveTargetProcesses(
            OptimizationAction action,
            SystemInfo systemInfo)
        {
            var matches = new List<ProcessInfo>();

            if (systemInfo?.Processes == null)
                return matches;

            if (action.TargetPid > 0)
            {
                foreach (var process in systemInfo.Processes)
                {
                    if (process.Id == action.TargetPid)
                        matches.Add(process);
                }

                if (matches.Count > 0)
                    return matches;
            }

            var name = WindowsApiHelper.NormalizeProcessName(
                string.IsNullOrWhiteSpace(action.TargetProcessName)
                    ? action.Target
                    : action.TargetProcessName);

            if (name.Length == 0)
                return matches;

            foreach (var process in systemInfo.Processes)
            {
                if (string.Equals(
                        WindowsApiHelper.NormalizeProcessName(process.Name),
                        name,
                        StringComparison.OrdinalIgnoreCase))
                {
                    matches.Add(process);
                }
                else if (!string.IsNullOrEmpty(action.TargetPath) &&
                         string.Equals(process.Path, action.TargetPath, StringComparison.OrdinalIgnoreCase))
                {
                    matches.Add(process);
                }
            }

            return matches;
        }

        /// <summary>
        /// Confirm that the process the action was planned against is still the same process.
        ///
        /// Three independent checks are layered, cheapest and most portable first:
        ///
        ///   1. The action must carry an identity at all. An action with only a name or only a pid
        ///      cannot be proven and is rejected - "unknown" is never treated as "verified".
        ///   2. The identity recorded at plan time must agree with the snapshot the action is being
        ///      validated against. This is pure date arithmetic with no Win32 dependency, so it is the
        ///      guarantee that always holds and that the unit tests exercise directly.
        ///   3. The live process behind the pid must still report the same creation timestamp, read
        ///      with GetProcessTimes. This closes the remaining window between the snapshot and the
        ///      moment of validation. It is best-effort: when the live timestamp cannot be read the
        ///      check is skipped rather than guessed, and the executor performs the identical check
        ///      again immediately before it acts.
        ///
        /// A missing image path is not treated as a match and not treated as tampering: an unreadable
        /// path simply cannot corroborate the identity, so the creation time carries the check.
        /// </summary>
        private ActionIdentityResult ValidateProcessIdentity(
            OptimizationAction action,
            ProcessInfo? snapshotProcess)
        {
            var result = new ActionIdentityResult { IsValid = true };

            // ---- Check 1: an identity must exist ------------------------------------------------
            // A process-scoped action without a captured identity cannot be proven safe at execution
            // time, because the scan that produced it may be minutes old. Fail closed.
            if (!action.HasProcessIdentity)
            {
                result.IsValid = false;
                result.RejectionReason =
                    $"No process identity (pid + creation time) was recorded for '{action.Target}', " +
                    "so it cannot be proven that the process is still the same one. Action rejected.";
                return result;
            }

            // ---- Check 2: the plan must agree with the snapshot it is validated against ---------
            if (snapshotProcess != null &&
                !WindowsApiHelper.IsSameProcessIdentity(
                    action.TargetCreationTimeUtc,
                    snapshotProcess.CreationTimeUtc))
            {
                result.IsValid = false;
                result.RejectionReason =
                    $"The process behind pid {action.TargetPid} is not the one that was planned " +
                    $"(planned start {action.TargetCreationTimeUtc:O}, current start " +
                    $"{snapshotProcess.CreationTimeUtc:O}). The pid was reassigned, so the action " +
                    "was rejected.";
                _logger?.Warning("SafetyValidator", result.RejectionReason);
                return result;
            }

            // ---- Check 3: the recorded image path must agree with the snapshot ------------------
            if (!string.IsNullOrWhiteSpace(action.TargetImagePath) &&
                snapshotProcess != null &&
                !string.IsNullOrWhiteSpace(snapshotProcess.Path) &&
                !PathsEqual(action.TargetImagePath, snapshotProcess.Path))
            {
                result.IsValid = false;
                result.RejectionReason =
                    $"The action records a different executable than the process behind pid " +
                    $"{action.TargetPid} (planned '{action.TargetImagePath}', current " +
                    $"'{snapshotProcess.Path}'). Action rejected.";
                return result;
            }

            // NOTE ON SCOPE - why there is no live Win32 call in this method.
            // This validator is a pure decision function over (action, snapshot). Keeping it free of
            // live system calls has three consequences, all deliberate:
            //   * the policy is deterministic and unit-testable without a Windows host;
            //   * the same action validated twice against the same snapshot always yields the same
            //     verdict, so a plan cannot be approved by a race;
            //   * the transient facts that really must be re-read - is the process still alive, has
            //     it become the foreground window, has it opened a window - are re-read exactly once,
            //     in SafeExecutor, at the instant before the process is touched (see
            //     SafeExecutor.ExecuteCloseProcessAsync). Checking them here as well would only widen
            //     the TOCTOU window by making the gap between check and use longer.
            return result;
        }

        /// <summary>
        /// Compare two executable paths, tolerating the differences that do not change the file:
        /// trailing whitespace, surrounding quotes and a mixed path separator.
        /// </summary>
        private static bool PathsEqual(string left, string right)
        {
            static string Canonicalise(string value) =>
                value.Trim().Trim('"').Replace('/', '\\').TrimEnd('\\');

            return string.Equals(
                Canonicalise(left),
                Canonicalise(right),
                StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Outcome of an identity verification.
        /// </summary>
        private sealed class ActionIdentityResult
        {
            public bool IsValid { get; set; } = true;
            public string RejectionReason { get; set; } = string.Empty;
        }

        /// <summary>
        /// Validate based on system state
        /// </summary>
        private bool ValidateSystemState(OptimizationAction action, SystemInfo systemInfo)        {
            // Don't perform aggressive optimizations when on battery if not configured
            if (systemInfo.IsOnBattery && !_config.AggressiveOnBattery)
            {
                // Allow only low-risk actions when on battery
                if (action.RiskLevel > RiskLevel.Low)
                    return false;
            }
            
            // Don't perform certain actions when system is under high load
            if (systemInfo.CpuUsage > 90)
            {
                // Don't close processes when CPU is already high
                if (action.ActionType == OptimizationActionType.CloseProcess)
                    return false;
            }
            
            // Don't perform disk-intensive actions when disk is busy
            if (systemInfo.TotalDiskActivity > 80)
            {
                if (action.ActionType == OptimizationActionType.ClearCache)
                    return false;
            }
            
            return true;
        }

        /// <summary>
        /// Validate based on user configuration
        /// </summary>
        private bool ValidateUserConfiguration(OptimizationAction action)
        {
            // Check if the action is in the user's whitelist
            if (_config.WhitelistedProcesses.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
                return false;
            
            return true;
        }

        /// <summary>
        /// Validate at the plan level
        /// </summary>
        private bool ValidatePlanLevel(OptimizationPlan plan, SystemInfo systemInfo)
        {
            // Check 1: Cannot have too many high-risk actions in a single plan
            var highRiskCount = plan.Actions.Count(a => a.RiskLevel == RiskLevel.High);
            if (highRiskCount > 5) // Arbitrary limit
            {
                _logger.Warning("SafetyValidator", 
                    $"Plan rejected: Too many high-risk actions ({highRiskCount})");
                return false;
            }
            
            // Check 2: Cannot have any critical-risk actions in a single plan
            var criticalRiskCount = plan.Actions.Count(a => a.RiskLevel == RiskLevel.Critical);
            if (criticalRiskCount > 0)
            {
                _logger.Warning("SafetyValidator", 
                    $"Plan rejected: Contains critical-risk actions ({criticalRiskCount})");
                return false;
            }
            
            // Check 3: Cannot disable too many services in a single plan
            var serviceActions = plan.Actions.Count(a => 
                a.ActionType == OptimizationActionType.StopService ||
                a.ActionType == OptimizationActionType.DisableService);
            if (serviceActions > 3) // Arbitrary limit
            {
                _logger.Warning("SafetyValidator", 
                    $"Plan rejected: Too many service actions ({serviceActions})");
                return false;
            }
            
            // Check 4: Cannot close too many processes in a single plan
            var closeActions = plan.Actions.Count(a => a.ActionType == OptimizationActionType.CloseProcess);
            if (closeActions > 20) // Arbitrary limit
            {
                _logger.Warning("SafetyValidator", 
                    $"Plan rejected: Too many process close actions ({closeActions})");
                return false;
            }
            
            // Check 5: Cannot perform actions that would leave the system in an unstable state
            if (WouldLeaveSystemUnstable(plan, systemInfo))
            {
                _logger.Warning("SafetyValidator", "Plan rejected: Would leave system in unstable state");
                return false;
            }
            
            return true;
        }

        /// <summary>
        /// Check if a plan would leave the system in an unstable state
        /// </summary>
        private bool WouldLeaveSystemUnstable(OptimizationPlan plan, SystemInfo systemInfo)
        {
            // Check if we're disabling too many critical services
            var criticalServices = systemInfo.Services
                .Where(s => s.IsCritical)
                .Select(s => s.Name)
                .ToList();
            
            var servicesToDisable = plan.Actions
                .Where(a => a.ActionType == OptimizationActionType.StopService ||
                           a.ActionType == OptimizationActionType.DisableService)
                .Select(a => a.Target)
                .ToList();
            
            var criticalServicesToDisable = criticalServices.Intersect(servicesToDisable, StringComparer.OrdinalIgnoreCase);
            
            if (criticalServicesToDisable.Count() > 2)
                return true;
            
            // Check if we're closing too many system processes
            var systemProcesses = systemInfo.Processes
                .Where(p => p.IsWindowsProcess || p.IsDriver)
                .Select(p => p.Name)
                .ToList();
            
            var processesToClose = plan.Actions
                .Where(a => a.ActionType == OptimizationActionType.CloseProcess)
                .Select(a => a.Target)
                .ToList();
            
            var systemProcessesToClose = systemProcesses.Intersect(processesToClose, StringComparer.OrdinalIgnoreCase);
            
            if (systemProcessesToClose.Count() > 3)
                return true;
            
            return false;
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the validator
        /// </summary>
        public void Dispose()
        {
            try
            {
                _processAnalyzer?.Dispose();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Validation result
    /// </summary>
    public class ValidationResult
    {
        /// <summary>
        /// The action being validated
        /// </summary>
        public OptimizationAction Action { get; set; } = new OptimizationAction();
        
        /// <summary>
        /// Whether the action is valid
        /// </summary>
        public bool IsValid { get; set; } = true;
        
        /// <summary>
        /// Reason for rejection if not valid
        /// </summary>
        public string RejectionReason { get; set; } = string.Empty;
    }
}

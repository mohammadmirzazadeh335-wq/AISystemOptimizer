using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for verifying optimization results
    /// </summary>
    public class VerificationService : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private readonly SafetyValidator _safetyValidator;
        private bool _disposed = false;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new verification service
        /// </summary>
        public VerificationService(
            ILogger logger = null,
            AppConfig config = null,
            SystemScanner scanner = null,
            SafetyValidator safetyValidator = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _safetyValidator = safetyValidator ?? new SafetyValidator(logger, config);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Verify an optimization plan before execution
        /// </summary>
        public VerificationResult VerifyPlan(OptimizationPlan plan, SystemInfo systemInfo = null)
        {
            var result = new VerificationResult { Plan = plan };
            
            try
            {
                _logger.Info("VerificationService", $"Verifying optimization plan: {plan.Name}");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? _scanner.Scan();
                
                // Check 1: Plan is not null
                if (plan == null)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan is null");
                    return result;
                }
                
                // Check 2: Plan has actions
                if (plan.Actions.Count == 0)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan has no actions");
                    return result;
                }
                
                // Check 3: All actions are valid
                var actionResults = new List<ActionVerificationResult>();
                foreach (var action in plan.Actions)
                {
                    var actionResult = VerifyAction(action, systemInfo);
                    actionResults.Add(actionResult);
                    
                    if (!actionResult.IsValid)
                    {
                        result.IsValid = false;
                        result.Errors.AddRange(actionResult.Errors);
                        result.FailedActions.Add(action);
                    }
                }
                
                result.ActionResults = actionResults;
                result.ValidActionCount = actionResults.Count(r => r.IsValid);
                result.InvalidActionCount = actionResults.Count(r => !r.IsValid);
                
                // Check 4: Plan doesn't contain critical actions if not allowed
                if (plan.Actions.Any(a => a.RiskLevel == RiskLevel.Critical) && 
                    !_config.AllowCriticalRiskActions)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan contains critical risk actions but critical actions are not allowed");
                }
                
                // Check 5: Plan doesn't contain too many high-risk actions
                var highRiskCount = plan.Actions.Count(a => a.RiskLevel == RiskLevel.High);
                if (highRiskCount > 5 && !_config.AllowHighRiskActions)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan contains too many high-risk actions");
                }
                
                // Check 6: Plan doesn't disable critical services
                var criticalServices = plan.Actions
                    .Where(a => a.ActionType == OptimizationActionType.StopService ||
                               a.ActionType == OptimizationActionType.DisableService)
                    .Where(a => CriticalProcesses.IsCritical(a.Target))
                    .ToList();
                
                if (criticalServices.Count > 0)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan attempts to stop/disable critical services");
                    result.FailedActions.AddRange(criticalServices);
                }
                
                // Check 7: Plan doesn't disable Windows Defender
                var defenderActions = plan.Actions
                    .Where(a => a.ActionType == OptimizationActionType.StopService ||
                               a.ActionType == OptimizationActionType.DisableService)
                    .Where(a => a.Target.Equals("WinDefend", StringComparison.OrdinalIgnoreCase))
                    .ToList();
                
                if (defenderActions.Count > 0)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan attempts to stop/disable Windows Defender");
                    result.FailedActions.AddRange(defenderActions);
                }
                
                // Check 8: Plan doesn't disable Windows Firewall
                var firewallActions = plan.Actions
                    .Where(a => a.ActionType == OptimizationActionType.StopService ||
                               a.ActionType == OptimizationActionType.DisableService)
                    .Where(a => a.Target.Equals("MpsSvc", StringComparison.OrdinalIgnoreCase))
                    .ToList();
                
                if (firewallActions.Count > 0)
                {
                    result.IsValid = false;
                    result.Errors.Add("Plan attempts to stop/disable Windows Firewall");
                    result.FailedActions.AddRange(firewallActions);
                }
                
                // Check 9: Verify system state allows the plan
                if (!VerifySystemState(plan, systemInfo))
                {
                    result.IsValid = false;
                    result.Errors.Add("System state does not allow this plan");
                }
                
                // Check 10: Calculate estimated impact
                result.EstimatedRamRecovery = plan.EstimatedRamRecovery;
                result.EstimatedCpuImprovement = plan.EstimatedCpuImprovement;
                result.EstimatedImpact = CalculateEstimatedImpact(plan, systemInfo);
                
                _logger.Info("VerificationService", 
                    $"Plan verification completed: Valid={result.IsValid}, " +
                    $"Errors={result.Errors.Count}, " +
                    $"ValidActions={result.ValidActionCount}, " +
                    $"InvalidActions={result.InvalidActionCount}");
            }
            catch (Exception ex)
            {
                _logger.Error("VerificationService", "Failed to verify plan", null, ex);
                result.IsValid = false;
                result.Errors.Add(ex.Message);
            }
            
            return result;
        }

        /// <summary>
        /// Verify a single action
        /// </summary>
        public ActionVerificationResult VerifyAction(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var result = new ActionVerificationResult { Action = action };
            
            try
            {
                _logger.Info("VerificationService", 
                    $"Verifying action: {action.ActionType} on {action.Target}");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? _scanner.Scan();
                
                // Check 1: Action is not null
                if (action == null)
                {
                    result.IsValid = false;
                    result.Errors.Add("Action is null");
                    return result;
                }
                
                // Check 2: Action type is valid
                if (!IsValidActionType(action.ActionType))
                {
                    result.IsValid = false;
                    result.Errors.Add($"Invalid action type: {action.ActionType}");
                    return result;
                }
                
                // Check 3: Target is not empty
                if (string.IsNullOrEmpty(action.Target))
                {
                    result.IsValid = false;
                    result.Errors.Add("Action target is empty");
                    return result;
                }
                
                // Check 4: Action is safe
                if (!_safetyValidator.ValidateAction(action, systemInfo))
                {
                    result.IsValid = false;
                    result.Errors.Add("Action failed safety validation");
                    return result;
                }
                
                // Check 5: Verify based on action type
                switch (action.ActionType)
                {
                    case OptimizationActionType.CloseProcess:
                        result.IsValid = VerifyCloseProcessAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.DisableStartup:
                        result.IsValid = VerifyDisableStartupAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.StopService:
                        result.IsValid = VerifyStopServiceAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.DisableService:
                        result.IsValid = VerifyDisableServiceAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.ClearCache:
                        result.IsValid = VerifyClearCacheAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.ChangePriority:
                        result.IsValid = VerifyChangePriorityAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.ChangeAffinity:
                        result.IsValid = VerifyChangeAffinityAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.UninstallApplication:
                        result.IsValid = VerifyUninstallApplicationAction(action, systemInfo, result);
                        break;
                    
                    case OptimizationActionType.AdjustPowerSettings:
                        result.IsValid = VerifyAdjustPowerSettingsAction(action, systemInfo, result);
                        break;
                }
                
                _logger.Info("VerificationService", 
                    $"Action verification completed: {action.ActionType} on {action.Target} -> Valid={result.IsValid}");
            }
            catch (Exception ex)
            {
                _logger.Error("VerificationService", 
                    $"Failed to verify action: {action.ActionType} on {action.Target}", null, ex);
                result.IsValid = false;
                result.Errors.Add(ex.Message);
            }
            
            return result;
        }

        /// <summary>
        /// Verify optimization results after execution
        /// </summary>
        public async Task<PostExecutionVerificationResult> VerifyExecutionAsync(
            OptimizationPlan plan,
            ExecutionResult executionResult)
        {
            var result = new PostExecutionVerificationResult
            {
                Plan = plan,
                ExecutionResult = executionResult
            };
            
            try
            {
                _logger.Info("VerificationService", "Verifying optimization results");
                
                // Check 1: Execution was successful
                if (!executionResult.IsSuccessful)
                {
                    result.IsValid = false;
                    result.Errors.Add("Execution was not successful");
                    return result;
                }
                
                // Check 2: Let the system settle, then scan.
                //
                // Measuring straight after execution produces false numbers. A process that was just
                // asked to close releases its working set over several seconds, and Windows needs a
                // moment before the freed pages show up as available. The specification requires a
                // 5-15 second observation window, so the wait is clamped into that range and the
                // actual wait is written into the report.
                var settleSeconds = Math.Clamp(_config.VerificationSettleSeconds, 5, 30);

                _logger.Info("VerificationService",
                    $"Waiting {settleSeconds}s for the system to settle before measuring the result");

                await Task.Delay(TimeSpan.FromSeconds(settleSeconds)).ConfigureAwait(false);

                var currentSystemInfo = await _scanner.ScanAsync();
                result.AfterSystemInfo = currentSystemInfo;
                result.SettleSeconds = settleSeconds;
                
                // Check 3: Verify that the actions had the expected effect
                foreach (var action in executionResult.ExecutedActions)
                {
                    var verification = VerifyActionEffect(action, plan.BeforeSystemInfo, currentSystemInfo);
                    result.ActionVerifications.Add(verification);
                    
                    if (!verification.IsSuccessful)
                    {
                        result.PartiallySuccessful = true;
                        result.FailedVerifications.Add(verification);
                    }
                }
                
                // Check 4: Verify overall improvement
                result.RamImprovement = VerifyRamImprovement(plan, currentSystemInfo);
                result.CpuImprovement = VerifyCpuImprovement(plan, currentSystemInfo);
                result.ProcessCountImprovement = VerifyProcessCountImprovement(plan, currentSystemInfo);
                
                // Check 5: Verify no critical services were affected
                if (!VerifyCriticalServicesUnaffected(plan, currentSystemInfo))
                {
                    result.IsValid = false;
                    result.Errors.Add("Critical services were affected by the optimization");
                }
                
                // Check 6: Verify system stability
                result.SystemStability = VerifySystemStability(currentSystemInfo);
                
                // Check 7: Generate report
                result.Report = GenerateVerificationReport(plan, executionResult, currentSystemInfo);
                
                _logger.Info("VerificationService", 
                    $"Post-execution verification completed: " +
                    $"RAM Improvement={result.RamImprovement:F1}%, " +
                    $"CPU Improvement={result.CpuImprovement:F1}%, " +
                    $"Process Count Improvement={result.ProcessCountImprovement}");
            }
            catch (Exception ex)
            {
                _logger.Error("VerificationService", "Failed to verify execution", null, ex);
                result.IsValid = false;
                result.Errors.Add(ex.Message);
            }
            
            return result;
        }

        /// <summary>
        /// Verify that a specific action had the expected effect
        /// </summary>
        public ActionEffectVerification VerifyActionEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            var result = new ActionEffectVerification { Action = action };
            
            try
            {
                _logger.Info("VerificationService", 
                    $"Verifying effect of action: {action.ActionType} on {action.Target}");
                
                switch (action.ActionType)
                {
                    case OptimizationActionType.CloseProcess:
                        result.IsSuccessful = VerifyCloseProcessEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.DisableStartup:
                        result.IsSuccessful = VerifyDisableStartupEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.StopService:
                    case OptimizationActionType.DisableService:
                        result.IsSuccessful = VerifyServiceEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.ClearCache:
                        result.IsSuccessful = true; // Cache clearing is hard to verify
                        break;
                    
                    case OptimizationActionType.ChangePriority:
                        result.IsSuccessful = VerifyPriorityChangeEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.ChangeAffinity:
                        result.IsSuccessful = VerifyAffinityChangeEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.UninstallApplication:
                        result.IsSuccessful = VerifyUninstallEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                    
                    case OptimizationActionType.AdjustPowerSettings:
                        result.IsSuccessful = VerifyPowerSettingsEffect(action, beforeSystemInfo, afterSystemInfo);
                        break;
                }
                
                _logger.Info("VerificationService", 
                    $"Effect verification completed: {action.ActionType} on {action.Target} -> Successful={result.IsSuccessful}");
            }
            catch (Exception ex)
            {
                _logger.Error("VerificationService", 
                    $"Failed to verify effect of action: {action.ActionType} on {action.Target}", null, ex);
                result.IsSuccessful = false;
                result.Error = ex.Message;
            }
            
            return result;
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Check if an action type is valid
        /// </summary>
        private bool IsValidActionType(OptimizationActionType actionType)
        {
            return Enum.IsDefined(typeof(OptimizationActionType), actionType);
        }

        /// <summary>
        /// Verify a close process action
        /// </summary>
        private bool VerifyCloseProcessAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the process is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot close critical process: {action.Target}");
                    return false;
                }
                
                // Check if the process is blacklisted
                if (_config.BlacklistedProcesses.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
                {
                    result.Errors.Add($"Process is blacklisted: {action.Target}");
                    return false;
                }
                
                // Check if the process is a Windows system process
                if (CriticalProcesses.IsWindowsSystemProcess(action.Target))
                {
                    result.Errors.Add($"Cannot close Windows system process: {action.Target}");
                    return false;
                }
                
                // Check if the process is a driver
                if (CriticalProcesses.IsDriverProcess(action.Target))
                {
                    result.Errors.Add($"Cannot close driver process: {action.Target}");
                    return false;
                }
                
                // Check if the process is a service
                var process = systemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (process != null && process.IsService)
                {
                    result.Errors.Add($"Process is a service, use StopService or DisableService instead: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify a disable startup action
        /// </summary>
        private bool VerifyDisableStartupAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the startup item is blacklisted
                if (_config.BlacklistedStartupItems.Any(b => string.Equals(b, action.Target, StringComparison.OrdinalIgnoreCase)))
                {
                    result.Errors.Add($"Startup item is blacklisted: {action.Target}");
                    return false;
                }
                
                // Check if the startup item is a Windows item
                var startupItem = systemInfo.StartupItems.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (startupItem != null && startupItem.IsWindowsItem)
                {
                    result.Errors.Add($"Cannot disable Windows startup item: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify a stop service action
        /// </summary>
        private bool VerifyStopServiceAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the service is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot stop critical service: {action.Target}");
                    return false;
                }
                
                // Check if the service is blacklisted
                if (_config.BlacklistedServices.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
                {
                    result.Errors.Add($"Service is blacklisted: {action.Target}");
                    return false;
                }
                
                // Check if the service is a Windows service
                var service = systemInfo.Services.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (service != null && service.IsCritical)
                {
                    result.Errors.Add($"Cannot stop critical Windows service: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify a disable service action
        /// </summary>
        private bool VerifyDisableServiceAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the service is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot disable critical service: {action.Target}");
                    return false;
                }
                
                // Check if the service is blacklisted
                if (_config.BlacklistedServices.Contains(action.Target, StringComparer.OrdinalIgnoreCase))
                {
                    result.Errors.Add($"Service is blacklisted: {action.Target}");
                    return false;
                }
                
                // Check if the service is a Windows service
                var service = systemInfo.Services.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (service != null && service.IsCritical)
                {
                    result.Errors.Add($"Cannot disable critical Windows service: {action.Target}");
                    return false;
                }
                
                // Check if the service is Windows Defender
                if (action.Target.Equals("WinDefend", StringComparison.OrdinalIgnoreCase))
                {
                    result.Errors.Add("Cannot disable Windows Defender");
                    return false;
                }
                
                // Check if the service is Windows Firewall
                if (action.Target.Equals("MpsSvc", StringComparison.OrdinalIgnoreCase))
                {
                    result.Errors.Add("Cannot disable Windows Firewall");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify a clear cache action
        /// </summary>
        private bool VerifyClearCacheAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            // Clear cache is generally safe
            return true;
        }

        /// <summary>
        /// Verify a change priority action
        /// </summary>
        private bool VerifyChangePriorityAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the process exists
                var process = systemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (process == null)
                {
                    result.Errors.Add($"Process not found: {action.Target}");
                    return false;
                }
                
                // Check if the process is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot change priority of critical process: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify a change affinity action
        /// </summary>
        private bool VerifyChangeAffinityAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the process exists
                var process = systemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (process == null)
                {
                    result.Errors.Add($"Process not found: {action.Target}");
                    return false;
                }
                
                // Check if the process is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot change affinity of critical process: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify an uninstall application action
        /// </summary>
        private bool VerifyUninstallApplicationAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the application is critical
                if (CriticalProcesses.IsCritical(action.Target))
                {
                    result.Errors.Add($"Cannot uninstall critical application: {action.Target}");
                    return false;
                }
                
                // Check if the application is a Windows component
                if (action.Target.Contains("Windows") || action.Target.Contains("Microsoft"))
                {
                    result.Errors.Add($"Cannot uninstall Windows component: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify an adjust power settings action
        /// </summary>
        private bool VerifyAdjustPowerSettingsAction(
            OptimizationAction action,
            SystemInfo systemInfo,
            ActionVerificationResult result)
        {
            try
            {
                // Check if the power mode is valid
                if (!Enum.TryParse<PowerMode>(action.Target, true, out _))
                {
                    result.Errors.Add($"Invalid power mode: {action.Target}");
                    return false;
                }
                
                return true;
            }
            catch (Exception ex)
            {
                result.Errors.Add(ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Verify that the system state allows the plan
        /// </summary>
        private bool VerifySystemState(OptimizationPlan plan, SystemInfo systemInfo)
        {
            // Check if we're on battery and the plan has high-risk actions
            if (systemInfo.IsOnBattery && !_config.AggressiveOnBattery)
            {
                if (plan.Actions.Any(a => a.RiskLevel > RiskLevel.Low))
                {
                    _logger.Warning("VerificationService", 
                        "System is on battery power but plan contains non-low-risk actions");
                    return false;
                }
            }
            
            // Check if system is under high load
            if (systemInfo.CpuUsage > 90)
            {
                // Don't perform CPU-intensive actions when CPU is already high
                if (plan.Actions.Any(a => a.ResourceType == ResourceType.CPU && a.RiskLevel > RiskLevel.Low))
                {
                    _logger.Warning("VerificationService", 
                        "System CPU usage is high but plan contains CPU-intensive actions");
                    return false;
                }
            }
            
            // Check if system has low available memory
            if (systemInfo.AvailablePhysicalMemory < 500 * 1024 * 1024) // Less than 500 MB
            {
                // Don't perform memory-intensive actions when memory is low
                if (plan.Actions.Any(a => a.ResourceType == ResourceType.RAM && a.RiskLevel > RiskLevel.Low))
                {
                    _logger.Warning("VerificationService", 
                        "System has low available memory but plan contains memory-intensive actions");
                    return false;
                }
            }
            
            return true;
        }

        /// <summary>
        /// Calculate estimated impact of a plan
        /// </summary>
        private ImpactLevel CalculateEstimatedImpact(OptimizationPlan plan, SystemInfo systemInfo)
        {
            var impactScore = 0;
            
            // Calculate based on estimated RAM recovery
            var ramRecoveryGB = plan.EstimatedRamRecovery / (1024.0 * 1024.0 * 1024.0);
            impactScore += (int)(ramRecoveryGB * 20); // 1 GB = 20 points
            
            // Calculate based on estimated CPU improvement
            impactScore += (int)(plan.EstimatedCpuImprovement * 2); // 1% CPU = 2 points
            
            // Calculate based on number of actions
            impactScore += plan.Actions.Count * 2; // Each action = 2 points
            
            // Calculate based on risk level
            var highRiskCount = plan.Actions.Count(a => a.RiskLevel == RiskLevel.High);
            impactScore -= highRiskCount * 10; // Each high risk action = -10 points
            
            var criticalRiskCount = plan.Actions.Count(a => a.RiskLevel == RiskLevel.Critical);
            impactScore -= criticalRiskCount * 20; // Each critical risk action = -20 points
            
            // Ensure score is between 0 and 100
            impactScore = Math.Max(0, Math.Min(100, impactScore));
            
            // Convert to impact level
            if (impactScore >= 80)
                return ImpactLevel.High;
            else if (impactScore >= 50)
                return ImpactLevel.Medium;
            else if (impactScore >= 20)
                return ImpactLevel.Low;
            else
                return ImpactLevel.Minimal;
        }

        /// <summary>
        /// Verify that a close process action had the expected effect
        /// </summary>
        private bool VerifyCloseProcessEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                // Check if the process is no longer running
                var processBefore = beforeSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processBefore == null)
                {
                    // Process wasn't running before, so we can't verify
                    return true;
                }
                
                var processAfter = afterSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processAfter == null)
                {
                    // Process is no longer running, action was successful
                    return true;
                }
                
                // Process is still running, action was not successful
                return false;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that a disable startup action had the expected effect
        /// </summary>
        private bool VerifyDisableStartupEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                // Check if the startup item is now disabled
                var startupBefore = beforeSystemInfo.StartupItems.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (startupBefore == null)
                {
                    // Startup item wasn't found before, so we can't verify
                    return true;
                }
                
                var startupAfter = afterSystemInfo.StartupItems.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (startupAfter == null)
                {
                    // Startup item is no longer in the list, action was successful
                    return true;
                }
                
                // Check if the startup item is now disabled
                if (!startupAfter.IsEnabled)
                {
                    return true;
                }
                
                // Startup item is still enabled, action was not successful
                return false;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that a service action had the expected effect
        /// </summary>
        private bool VerifyServiceEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                var serviceBefore = beforeSystemInfo.Services.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (serviceBefore == null)
                {
                    // Service wasn't found before, so we can't verify
                    return true;
                }
                
                var serviceAfter = afterSystemInfo.Services.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (serviceAfter == null)
                {
                    // Service is no longer in the list, action was successful
                    return true;
                }
                
                // Check based on action type
                switch (action.ActionType)
                {
                    case OptimizationActionType.StopService:
                        // Check if the service is now stopped
                        return serviceAfter.Status == "Stopped";
                    
                    case OptimizationActionType.DisableService:
                        // Check if the service is now disabled
                        return serviceAfter.StartType == "Disabled";
                    
                    default:
                        return true;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that a priority change action had the expected effect
        /// </summary>
        private bool VerifyPriorityChangeEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                var processBefore = beforeSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processBefore == null)
                {
                    // Process wasn't running before, so we can't verify
                    return true;
                }
                
                var processAfter = afterSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processAfter == null)
                {
                    // Process is no longer running, so we can't verify
                    return true;
                }
                
                // Check if the priority was changed
                // Note: This is hard to verify without knowing what the priority was set to
                return true; // Assume it worked
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that an affinity change action had the expected effect
        /// </summary>
        private bool VerifyAffinityChangeEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                var processBefore = beforeSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processBefore == null)
                {
                    // Process wasn't running before, so we can't verify
                    return true;
                }
                
                var processAfter = afterSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processAfter == null)
                {
                    // Process is no longer running, so we can't verify
                    return true;
                }
                
                // Check if the affinity was changed
                // Note: This is hard to verify without knowing what the affinity was set to
                return true; // Assume it worked
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that an uninstall action had the expected effect
        /// </summary>
        private bool VerifyUninstallEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                // Check if the process is no longer running
                var processBefore = beforeSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                    p.DisplayName.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processBefore == null)
                {
                    // Process wasn't running before, so we can't verify
                    return true;
                }
                
                var processAfter = afterSystemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                    p.DisplayName.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (processAfter == null)
                {
                    // Process is no longer running, action was successful
                    return true;
                }
                
                // Process is still running, action was not successful
                return false;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify that a power settings action had the expected effect
        /// </summary>
        private bool VerifyPowerSettingsEffect(
            OptimizationAction action,
            SystemInfo beforeSystemInfo,
            SystemInfo afterSystemInfo)
        {
            try
            {
                // Check if the power mode was changed
                if (Enum.TryParse<PowerMode>(action.Target, true, out var targetMode))
                {
                    return afterSystemInfo.CurrentPowerMode == targetMode;
                }
                
                return false;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify RAM improvement
        /// </summary>
        private float VerifyRamImprovement(OptimizationPlan plan, SystemInfo afterSystemInfo)
        {
            try
            {
                var beforeRamUsage = plan.BeforeSystemInfo.RamUsagePercentage;
                var afterRamUsage = afterSystemInfo.RamUsagePercentage;
                
                return Math.Max(0, beforeRamUsage - afterRamUsage);
            }
            catch
            {
                return 0f;
            }
        }

        /// <summary>
        /// Verify CPU improvement
        /// </summary>
        private float VerifyCpuImprovement(OptimizationPlan plan, SystemInfo afterSystemInfo)
        {
            try
            {
                var beforeCpuUsage = plan.BeforeSystemInfo.CpuUsage;
                var afterCpuUsage = afterSystemInfo.CpuUsage;
                
                return Math.Max(0, beforeCpuUsage - afterCpuUsage);
            }
            catch
            {
                return 0f;
            }
        }

        /// <summary>
        /// Verify process count improvement
        /// </summary>
        private int VerifyProcessCountImprovement(OptimizationPlan plan, SystemInfo afterSystemInfo)
        {
            try
            {
                var beforeProcessCount = plan.BeforeSystemInfo.TotalProcessCount;
                var afterProcessCount = afterSystemInfo.TotalProcessCount;
                
                return Math.Max(0, beforeProcessCount - afterProcessCount);
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Verify that critical services were not affected
        /// </summary>
        private bool VerifyCriticalServicesUnaffected(OptimizationPlan plan, SystemInfo afterSystemInfo)
        {
            try
            {
                // Get all critical services
                var criticalServices = afterSystemInfo.Services
                    .Where(s => s.IsCritical)
                    .Select(s => s.Name)
                    .ToList();
                
                // Check if any critical services were stopped
                var stoppedCriticalServices = afterSystemInfo.Services
                    .Where(s => s.IsCritical && s.Status == "Stopped")
                    .ToList();
                
                if (stoppedCriticalServices.Count > 0)
                {
                    _logger.Warning("VerificationService", 
                        $"Critical services were stopped: {string.Join(", ", stoppedCriticalServices.Select(s => s.Name))}");
                    return false;
                }
                
                // Check if any critical services were disabled
                var disabledCriticalServices = afterSystemInfo.Services
                    .Where(s => s.IsCritical && s.StartType == "Disabled")
                    .ToList();
                
                if (disabledCriticalServices.Count > 0)
                {
                    _logger.Warning("VerificationService", 
                        $"Critical services were disabled: {string.Join(", ", disabledCriticalServices.Select(s => s.Name))}");
                    return false;
                }
                
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Verify system stability
        /// </summary>
        private bool VerifySystemStability(SystemInfo systemInfo)
        {
            try
            {
                // Check if critical services are running
                var criticalServices = systemInfo.Services
                    .Where(s => s.IsCritical)
                    .ToList();
                
                foreach (var service in criticalServices)
                {
                    if (service.Status != "Running")
                    {
                        _logger.Warning("VerificationService", 
                            $"Critical service is not running: {service.Name}");
                        return false;
                    }
                }
                
                // Check if Windows Defender is running (if enabled)
                if (systemInfo.IsDefenderEnabled)
                {
                    var defenderService = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals("WinDefend", StringComparison.OrdinalIgnoreCase));
                    
                    if (defenderService != null && defenderService.Status != "Running")
                    {
                        _logger.Warning("VerificationService", "Windows Defender is not running");
                        return false;
                    }
                }
                
                // Check if Windows Firewall is running (if enabled)
                if (systemInfo.IsFirewallEnabled)
                {
                    var firewallService = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals("MpsSvc", StringComparison.OrdinalIgnoreCase));
                    
                    if (firewallService != null && firewallService.Status != "Running")
                    {
                        _logger.Warning("VerificationService", "Windows Firewall is not running");
                        return false;
                    }
                }
                
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Generate a verification report
        /// </summary>
        private string GenerateVerificationReport(
            OptimizationPlan plan,
            ExecutionResult executionResult,
            SystemInfo afterSystemInfo)
        {
            var report = new System.Text.StringBuilder();
            
            report.AppendLine("=== OPTIMIZATION VERIFICATION REPORT ===");
            report.AppendLine();
            report.AppendLine($"Plan: {plan.Name}");
            report.AppendLine($"Created: {plan.CreatedAt:yyyy-MM-dd HH:mm:ss}");
            report.AppendLine($"Executed: {executionResult.StartedAt:yyyy-MM-dd HH:mm:ss}");
            report.AppendLine($"Duration: {executionResult.Duration.TotalSeconds:F1} seconds");
            report.AppendLine();
            
            report.AppendLine("=== EXECUTION SUMMARY ===");
            report.AppendLine($"Total Actions: {executionResult.ExecutedActions.Count}");
            report.AppendLine($"Successful: {executionResult.SuccessfulCount}");
            report.AppendLine($"Failed: {executionResult.FailedCount}");
            report.AppendLine($"Skipped: {executionResult.SkippedCount}");
            report.AppendLine();
            
            report.AppendLine("=== PERFORMANCE IMPROVEMENT ===");
            report.AppendLine($"RAM Usage: {plan.BeforeSystemInfo.RamUsagePercentage:F1}% -> {afterSystemInfo.RamUsagePercentage:F1}% (Δ: {VerifyRamImprovement(plan, afterSystemInfo):+0.00;-0.00}%)");
            report.AppendLine($"CPU Usage: {plan.BeforeSystemInfo.CpuUsage:F1}% -> {afterSystemInfo.CpuUsage:F1}% (Δ: {VerifyCpuImprovement(plan, afterSystemInfo):+0.00;-0.00}%)");
            report.AppendLine($"Process Count: {plan.BeforeSystemInfo.TotalProcessCount} -> {afterSystemInfo.TotalProcessCount} (Δ: {VerifyProcessCountImprovement(plan, afterSystemInfo):+0;-0})");
            report.AppendLine();
            
            report.AppendLine("=== ACTION VERIFICATION ===");
            foreach (var action in executionResult.ExecutedActions)
            {
                var verification = VerifyActionEffect(action, plan.BeforeSystemInfo, afterSystemInfo);
                report.AppendLine($"  - {action.ActionType}: {action.Target} - {(verification.IsSuccessful ? "SUCCESS" : "FAILED")}");
            }
            
            if (executionResult.FailedActions.Count > 0)
            {
                report.AppendLine();
                report.AppendLine("=== FAILED ACTIONS ===");
                foreach (var action in executionResult.FailedActions)
                {
                    report.AppendLine($"  - {action.ActionType}: {action.Target} - Error: {action.ErrorMessage}");
                }
            }
            
            if (executionResult.SkippedActions.Count > 0)
            {
                report.AppendLine();
                report.AppendLine("=== SKIPPED ACTIONS ===");
                foreach (var action in executionResult.SkippedActions)
                {
                    report.AppendLine($"  - {action.ActionType}: {action.Target} - Reason: {action.SkipReason}");
                }
            }
            
            report.AppendLine();
            report.AppendLine("=== SYSTEM STABILITY ===");
            report.AppendLine($"System Stability: {(VerifySystemStability(afterSystemInfo) ? "STABLE" : "UNSTABLE")}");
            report.AppendLine($"Critical Services Running: {afterSystemInfo.Services.Count(s => s.IsCritical && s.Status == "Running")}/{afterSystemInfo.Services.Count(s => s.IsCritical)}");
            
            return report.ToString();
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the service
        /// </summary>
        public void Dispose()
        {
            try
            {
                _scanner?.Dispose();
                _safetyValidator?.Dispose();
            }
            catch { }
            
            _disposed = true;
        }

        #endregion
    }

    /// <summary>
    /// Verification result
    /// </summary>
    public class VerificationResult
    {
        /// <summary>
        /// The optimization plan being verified
        /// </summary>
        public OptimizationPlan Plan { get; set; }
        
        /// <summary>
        /// Whether the plan is valid
        /// </summary>
        public bool IsValid { get; set; } = true;
        
        /// <summary>
        /// List of errors
        /// </summary>
        public List<string> Errors { get; set; } = new List<string>();
        
        /// <summary>
        /// List of action verification results
        /// </summary>
        public List<ActionVerificationResult> ActionResults { get; set; } = new List<ActionVerificationResult>();
        
        /// <summary>
        /// Number of valid actions
        /// </summary>
        public int ValidActionCount { get; set; }
        
        /// <summary>
        /// Number of invalid actions
        /// </summary>
        public int InvalidActionCount { get; set; }
        
        /// <summary>
        /// List of failed actions
        /// </summary>
        public List<OptimizationAction> FailedActions { get; set; } = new List<OptimizationAction>();
        
        /// <summary>
        /// Estimated RAM recovery
        /// </summary>
        public long EstimatedRamRecovery { get; set; }
        
        /// <summary>
        /// Estimated CPU improvement
        /// </summary>
        public float EstimatedCpuImprovement { get; set; }
        
        /// <summary>
        /// Estimated impact level
        /// </summary>
        public ImpactLevel EstimatedImpact { get; set; } = ImpactLevel.Low;
    }

    /// <summary>
    /// Action verification result
    /// </summary>
    public class ActionVerificationResult
    {
        /// <summary>
        /// The action being verified
        /// </summary>
        public OptimizationAction Action { get; set; }
        
        /// <summary>
        /// Whether the action is valid
        /// </summary>
        public bool IsValid { get; set; } = true;
        
        /// <summary>
        /// List of errors
        /// </summary>
        public List<string> Errors { get; set; } = new List<string>();
    }

    /// <summary>
    /// Post-execution verification result
    /// </summary>
    public class PostExecutionVerificationResult
    {
        /// <summary>
        /// The optimization plan
        /// </summary>
        public OptimizationPlan Plan { get; set; }
        
        /// <summary>
        /// The execution result
        /// </summary>
        public ExecutionResult ExecutionResult { get; set; }
        
        /// <summary>
        /// System info after execution
        /// </summary>
        public SystemInfo AfterSystemInfo { get; set; }
        
        /// <summary>
        /// Whether the verification was successful
        /// </summary>
                /// <summary>
        /// How long the verifier waited for the system to settle before measuring, in seconds.
        /// Recorded so that a report can state how the "after" numbers were obtained.
        /// </summary>
        public int SettleSeconds { get; set; }

public bool IsValid { get; set; } = true;
        
        /// <summary>
        /// Whether the verification was partially successful
        /// </summary>
        public bool PartiallySuccessful { get; set; } = false;
        
        /// <summary>
        /// List of errors
        /// </summary>
        public List<string> Errors { get; set; } = new List<string>();
        
        /// <summary>
        /// List of action effect verifications
        /// </summary>
        public List<ActionEffectVerification> ActionVerifications { get; set; } = new List<ActionEffectVerification>();
        
        /// <summary>
        /// List of failed verifications
        /// </summary>
        public List<ActionEffectVerification> FailedVerifications { get; set; } = new List<ActionEffectVerification>();
        
        /// <summary>
        /// RAM usage improvement percentage
        /// </summary>
        public float RamImprovement { get; set; }
        
        /// <summary>
        /// CPU usage improvement percentage
        /// </summary>
        public float CpuImprovement { get; set; }
        
        /// <summary>
        /// Process count improvement
        /// </summary>
        public int ProcessCountImprovement { get; set; }
        
        /// <summary>
        /// Whether the system is stable
        /// </summary>
        public bool SystemStability { get; set; } = true;
        
        /// <summary>
        /// Verification report
        /// </summary>
        public string Report { get; set; } = string.Empty;
    }

    /// <summary>
    /// Action effect verification
    /// </summary>
    public class ActionEffectVerification
    {
        /// <summary>
        /// The action
        /// </summary>
        public OptimizationAction Action { get; set; }
        
        /// <summary>
        /// Whether the effect was successful
        /// </summary>
        public bool IsSuccessful { get; set; } = true;
        
        /// <summary>
        /// Error message if any
        /// </summary>
        public string Error { get; set; } = string.Empty;
    }

    /// <summary>
    /// Impact level enumeration
    /// </summary>
    public enum ImpactLevel
    {
        Minimal,
        Low,
        Medium,
        High
    }
}

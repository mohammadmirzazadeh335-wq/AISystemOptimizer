using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for analyzing the risk of optimization actions
    /// </summary>
    public class RiskAnalyzer : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly ProcessAnalyzer _processAnalyzer;
        private readonly SafetyValidator _safetyValidator;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new risk analyzer
        /// </summary>
        public RiskAnalyzer(
            ILogger logger = null,
            AppConfig config = null,
            ProcessAnalyzer processAnalyzer = null,
            SafetyValidator safetyValidator = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _processAnalyzer = processAnalyzer ?? new ProcessAnalyzer(logger, config);
            _safetyValidator = safetyValidator ?? new SafetyValidator(logger, config);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Analyze the risk of an optimization action
        /// </summary>
        public RiskAnalysisResult AnalyzeActionRisk(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var result = new RiskAnalysisResult { Action = action };
            
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? new SystemScanner(_logger, _config).Scan();
                
                _logger.Info("RiskAnalyzer", 
                    $"Analyzing risk for action: {action.ActionType} on {action.Target}");
                
                // Set the action's risk level based on analysis
                action.RiskLevel = DetermineActionRiskLevel(action, systemInfo);
                result.DeterminedRiskLevel = action.RiskLevel;
                
                // Check if the action is safe
                result.IsSafe = IsActionSafe(action, systemInfo);
                
                // Get safety recommendations
                result.Recommendations = GetSafetyRecommendations(action, systemInfo);
                
                // Check if the action requires user confirmation
                result.RequiresConfirmation = RequiresConfirmation(action, systemInfo);
                
                // Check if the action can be performed automatically
                result.CanAutoPerform = CanAutoPerform(action, systemInfo);
                
                // Get potential side effects
                result.PotentialSideEffects = GetPotentialSideEffects(action, systemInfo);
                
                // Get recovery options
                result.RecoveryOptions = GetRecoveryOptions(action, systemInfo);
                
                _logger.Info("RiskAnalyzer", 
                    $"Risk analysis completed for action: {action.ActionType} on {action.Target}. " +
                    $"Risk: {result.DeterminedRiskLevel}, Safe: {result.IsSafe}");
            }
            catch (Exception ex)
            {
                _logger.Error("RiskAnalyzer", 
                    $"Failed to analyze risk for action: {action.ActionType} on {action.Target}", 
                    null, ex);
                result.Error = ex.Message;
            }
            
            return result;
        }

        /// <summary>
        /// Analyze the risk of multiple actions
        /// </summary>
        public List<RiskAnalysisResult> AnalyzeActionsRisk(
            List<OptimizationAction> actions,
            SystemInfo systemInfo = null)
        {
            var results = new List<RiskAnalysisResult>();
            
            foreach (var action in actions)
            {
                try
                {
                    var result = AnalyzeActionRisk(action, systemInfo);
                    results.Add(result);
                }
                catch (Exception ex)
                {
                    _logger.Error("RiskAnalyzer", 
                        $"Failed to analyze risk for action: {action.ActionType} on {action.Target}", 
                        null, ex);
                }
            }
            
            return results;
        }

        /// <summary>
        /// Determine the overall risk level of an optimization plan
        /// </summary>
        public RiskLevel DeterminePlanRiskLevel(OptimizationPlan plan, SystemInfo systemInfo = null)
        {
            if (plan == null || plan.Actions.Count == 0)
                return RiskLevel.Low;
            
            // The overall risk level is the highest risk level of all actions
            var highestRisk = plan.Actions.Max(a => a.RiskLevel);
            
            // If there are critical actions, the plan is critical
            if (highestRisk == RiskLevel.Critical)
                return RiskLevel.Critical;
            
            // If there are high risk actions, the plan is high
            if (highestRisk == RiskLevel.High)
                return RiskLevel.High;
            
            // If there are medium risk actions, the plan is medium
            if (highestRisk == RiskLevel.Medium)
                return RiskLevel.Medium;
            
            // Otherwise, the plan is low risk
            return RiskLevel.Low;
        }

        /// <summary>
        /// Check if an action is safe to perform
        /// </summary>
        public bool IsActionSafe(OptimizationAction action, SystemInfo systemInfo = null)
        {
            // Use the safety validator
            return _safetyValidator.ValidateAction(action, systemInfo);
        }

        /// <summary>
        /// Check if an action requires user confirmation
        /// </summary>
        public bool RequiresConfirmation(OptimizationAction action, SystemInfo systemInfo = null)
        {
            // Always require confirmation for high and critical risk actions
            if (action.RiskLevel == RiskLevel.High || action.RiskLevel == RiskLevel.Critical)
                return true;
            
            // Require confirmation for medium risk actions if configured
            if (action.RiskLevel == RiskLevel.Medium && _config.RequireConfirmationForMediumRisk)
                return true;
            
            // Require confirmation for actions that require admin if not running as admin
            if (action.RequiresAdmin && !WindowsApiHelper.IsAdministrator())
                return true;
            
            // Require confirmation for actions that can't be undone
            if (!action.CanUndo)
                return true;
            
            return false;
        }

        /// <summary>
        /// Check if an action can be performed automatically
        /// </summary>
        public bool CanAutoPerform(OptimizationAction action, SystemInfo systemInfo = null)
        {
            // Cannot auto-perform if it requires confirmation
            if (RequiresConfirmation(action, systemInfo))
                return false;
            
            // Cannot auto-perform if it's not safe
            if (!IsActionSafe(action, systemInfo))
                return false;
            
            // Cannot auto-perform if it requires admin and we're not running as admin
            if (action.RequiresAdmin && !WindowsApiHelper.IsAdministrator())
                return false;
            
            // Check the maximum allowed risk level for auto actions
            if (action.RiskLevel > _config.MaxAutoRiskLevel)
                return false;
            
            return true;
        }

        /// <summary>
        /// Determine the risk level of an action
        /// </summary>
        public RiskLevel DetermineActionRiskLevel(OptimizationAction action, SystemInfo systemInfo = null)
        {
            // Use the existing risk level if already set
            if (action.RiskLevel != RiskLevel.Low) // Default is Low
                return action.RiskLevel;
            
            // Determine based on action type
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    return DetermineProcessRiskLevel(action.Target, systemInfo);
                
                case OptimizationActionType.DisableStartup:
                    return DetermineStartupRiskLevel(action.Target, systemInfo);
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    return DetermineServiceRiskLevel(action.Target, systemInfo);
                
                case OptimizationActionType.ClearCache:
                    return RiskLevel.Low; // Clearing cache is generally safe
                
                case OptimizationActionType.ChangePriority:
                case OptimizationActionType.ChangeAffinity:
                    return RiskLevel.Medium; // Changing process settings can affect performance
                
                case OptimizationActionType.UninstallApplication:
                    return RiskLevel.High; // Uninstalling can break dependencies
                
                case OptimizationActionType.AdjustPowerSettings:
                    return RiskLevel.Low; // Adjusting power settings is generally safe
                
                default:
                    return RiskLevel.Medium;
            }
        }

        /// <summary>
        /// Determine the risk level of closing a process
        /// </summary>
        public RiskLevel DetermineProcessRiskLevel(string processName, SystemInfo systemInfo = null)
        {
            // Check if it's a critical process
            if (CriticalProcesses.IsCritical(processName))
                return RiskLevel.Critical;
            
            // Check if it's blacklisted
            if (_config.BlacklistedProcesses.Contains(processName, StringComparer.OrdinalIgnoreCase))
                return RiskLevel.Critical;
            
            // Check if it's a Windows system process
            if (CriticalProcesses.IsWindowsSystemProcess(processName))
                return RiskLevel.High;
            
            // Check if it's a driver
            if (CriticalProcesses.IsDriverProcess(processName))
                return RiskLevel.High;
            
            // Check if it's a security process
            if (CriticalProcesses.IsSecurityProcess(processName))
                return RiskLevel.High;
            
            // Check the process category
            var category = CriticalProcesses.GetProcessCategory(processName, string.Empty, false);
            return CriticalProcesses.GetProcessRiskLevel(processName, category);
        }

        /// <summary>
        /// Determine the risk level of disabling a startup item
        /// </summary>
        public RiskLevel DetermineStartupRiskLevel(string startupName, SystemInfo systemInfo = null)
        {
            // Check if it's a Windows startup item
            if (_config.BlacklistedStartupItems.Contains(startupName, StringComparer.OrdinalIgnoreCase))
                return RiskLevel.High;
            
            // Check if it's a security-related startup item
            if (startupName.Contains("defender", StringComparison.OrdinalIgnoreCase) ||
                startupName.Contains("security", StringComparison.OrdinalIgnoreCase) ||
                startupName.Contains("firewall", StringComparison.OrdinalIgnoreCase) ||
                startupName.Contains("antivirus", StringComparison.OrdinalIgnoreCase))
                return RiskLevel.High;
            
            // Check if it's a system startup item
            if (startupName.Contains("windows", StringComparison.OrdinalIgnoreCase) ||
                startupName.Contains("microsoft", StringComparison.OrdinalIgnoreCase))
                return RiskLevel.Medium;
            
            // Default to low risk for user startup items
            return RiskLevel.Low;
        }

        /// <summary>
        /// Determine the risk level of stopping/disabling a service
        /// </summary>
        public RiskLevel DetermineServiceRiskLevel(string serviceName, SystemInfo systemInfo = null)
        {
            // Check if it's a critical service
            if (_config.BlacklistedServices.Contains(serviceName, StringComparer.OrdinalIgnoreCase))
                return RiskLevel.Critical;
            
            // Check if it's a Windows service
            if (CriticalProcesses.IsWindowsSystemProcess(serviceName))
                return RiskLevel.High;
            
            // Check if it's a security service
            if (CriticalProcesses.IsSecurityProcess(serviceName))
                return RiskLevel.High;
            
            // Check if it's a driver service
            if (CriticalProcesses.IsDriverProcess(serviceName))
                return RiskLevel.High;
            
            // Default to medium risk for services
            return RiskLevel.Medium;
        }

        /// <summary>
        /// Get safety recommendations for an action
        /// </summary>
        public List<string> GetSafetyRecommendations(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var recommendations = new List<string>();
            
            // General recommendations
            if (action.RiskLevel == RiskLevel.Critical)
            {
                recommendations.Add("CRITICAL RISK: This action could cause system instability or data loss. NOT RECOMMENDED.");
            }
            else if (action.RiskLevel == RiskLevel.High)
            {
                recommendations.Add("HIGH RISK: This action could cause issues with certain applications or system features. Proceed with caution.");
            }
            else if (action.RiskLevel == RiskLevel.Medium)
            {
                recommendations.Add("MEDIUM RISK: This action is generally safe but may affect some applications. Review before proceeding.");
            }
            else
            {
                recommendations.Add("LOW RISK: This action is generally safe and unlikely to cause issues.");
            }
            
            // Specific recommendations based on action type
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    recommendations.Add("Consider saving any unsaved work before closing this process.");
                    recommendations.Add("The process may restart automatically if it's part of an application.");
                    break;
                
                case OptimizationActionType.DisableStartup:
                    recommendations.Add("Disabling startup items can improve boot time.");
                    recommendations.Add("You can re-enable the startup item later if needed.");
                    break;
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    recommendations.Add("Stopping or disabling services may affect system functionality.");
                    recommendations.Add("Some services may be required by other applications.");
                    break;
                
                case OptimizationActionType.ClearCache:
                    recommendations.Add("Clearing cache can free up disk space.");
                    recommendations.Add("Some applications may need to rebuild their cache after this operation.");
                    break;
                
                case OptimizationActionType.ChangePriority:
                    recommendations.Add("Changing process priority can affect system performance.");
                    recommendations.Add("Higher priority processes get more CPU time, which may starve other processes.");
                    break;
                
                case OptimizationActionType.ChangeAffinity:
                    recommendations.Add("Changing process affinity can affect multi-core performance.");
                    recommendations.Add("This can be useful for games or applications that don't use all CPU cores efficiently.");
                    break;
                
                case OptimizationActionType.UninstallApplication:
                    recommendations.Add("Uninstalling applications can free up disk space and remove background processes.");
                    recommendations.Add("Make sure you don't need this application before uninstalling.");
                    recommendations.Add("Some applications may leave behind files and registry entries.");
                    break;
                
                case OptimizationActionType.AdjustPowerSettings:
                    recommendations.Add("Adjusting power settings can affect system performance and power consumption.");
                    recommendations.Add("Higher performance modes use more power but provide better responsiveness.");
                    break;
            }
            
            // Recommendations based on system state
            if (systemInfo != null)
            {
                if (systemInfo.IsOnBattery)
                {
                    recommendations.Add("System is on battery power. Be extra cautious with actions that may affect power consumption.");
                }
                
                if (systemInfo.RamUsagePercentage > 90)
                {
                    recommendations.Add("System is under high memory pressure. Closing non-essential processes is recommended.");
                }
                
                if (systemInfo.CpuUsage > 80)
                {
                    recommendations.Add("System is under high CPU load. Be cautious with actions that may increase CPU usage.");
                }
            }
            
            return recommendations;
        }

        /// <summary>
        /// Get potential side effects of an action
        /// </summary>
        public List<string> GetPotentialSideEffects(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var sideEffects = new List<string>();
            
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    sideEffects.Add("The application may lose unsaved data.");
                    sideEffects.Add("The process may restart automatically.");
                    sideEffects.Add("Dependent processes may fail.");
                    sideEffects.Add("Application features may not work correctly until restarted.");
                    break;
                
                case OptimizationActionType.DisableStartup:
                    sideEffects.Add("The application will not start automatically when Windows starts.");
                    sideEffects.Add("You will need to manually start the application.");
                    sideEffects.Add("Some applications may not work correctly if they expect to start with Windows.");
                    break;
                
                case OptimizationActionType.StopService:
                    sideEffects.Add("The service will stop running until the next system restart or manual start.");
                    sideEffects.Add("Applications that depend on this service may not work correctly.");
                    sideEffects.Add("Some Windows features may be disabled.");
                    break;
                
                case OptimizationActionType.DisableService:
                    sideEffects.Add("The service will not start automatically.");
                    sideEffects.Add("Applications that depend on this service may not work correctly.");
                    sideEffects.Add("Some Windows features may be disabled.");
                    sideEffects.Add("The service will need to be manually enabled to start again.");
                    break;
                
                case OptimizationActionType.ClearCache:
                    sideEffects.Add("Some applications may start slower the next time they are launched.");
                    sideEffects.Add("Temporary files will be deleted.");
                    sideEffects.Add("Some application data may be lost (e.g., unsaved work, preferences).");
                    break;
                
                case OptimizationActionType.ChangePriority:
                    sideEffects.Add("The process may use more or less CPU time.");
                    sideEffects.Add("Other processes may be affected by the priority change.");
                    sideEffects.Add("System responsiveness may be affected.");
                    break;
                
                case OptimizationActionType.ChangeAffinity:
                    sideEffects.Add("The process will only run on specific CPU cores.");
                    sideEffects.Add("Performance may be improved or degraded depending on the application.");
                    sideEffects.Add("Other processes may be affected by the affinity change.");
                    break;
                
                case OptimizationActionType.UninstallApplication:
                    sideEffects.Add("The application will be completely removed from the system.");
                    sideEffects.Add("All application data and settings will be deleted.");
                    sideEffects.Add("Other applications that depend on this application may not work correctly.");
                    sideEffects.Add("You will need to reinstall the application to use it again.");
                    break;
                
                case OptimizationActionType.AdjustPowerSettings:
                    sideEffects.Add("System power consumption will change.");
                    sideEffects.Add("Battery life may be affected.");
                    sideEffects.Add("System performance may be affected.");
                    sideEffects.Add("Fan noise may change.");
                    break;
            }
            
            return sideEffects;
        }

        /// <summary>
        /// Get recovery options for an action
        /// </summary>
        public List<string> GetRecoveryOptions(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var recoveryOptions = new List<string>();
            
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    recoveryOptions.Add("Restart the application manually.");
                    recoveryOptions.Add("Restart the computer to restore all processes.");
                    recoveryOptions.Add("Check for application updates that may fix the issue.");
                    break;
                
                case OptimizationActionType.DisableStartup:
                    recoveryOptions.Add("Re-enable the startup item in Task Manager or msconfig.");
                    recoveryOptions.Add("Run the application manually.");
                    recoveryOptions.Add("Re-add the shortcut to the Startup folder.");
                    break;
                
                case OptimizationActionType.StopService:
                    recoveryOptions.Add("Restart the service manually using Services.msc or command line.");
                    recoveryOptions.Add("Restart the computer to restore the service.");
                    recoveryOptions.Add("Check the service dependencies and start them first.");
                    break;
                
                case OptimizationActionType.DisableService:
                    recoveryOptions.Add("Re-enable the service using Services.msc or command line.");
                    recoveryOptions.Add("Set the service startup type back to its original value.");
                    recoveryOptions.Add("Restart the computer to apply the changes.");
                    break;
                
                case OptimizationActionType.ClearCache:
                    recoveryOptions.Add("Restart the application to rebuild the cache.");
                    recoveryOptions.Add("Restore deleted files from backup if available.");
                    recoveryOptions.Add("Reinstall the application to restore default cache.");
                    break;
                
                case OptimizationActionType.ChangePriority:
                    recoveryOptions.Add("Reset the process priority to Normal.");
                    recoveryOptions.Add("Restart the process to reset its priority.");
                    break;
                
                case OptimizationActionType.ChangeAffinity:
                    recoveryOptions.Add("Reset the process affinity to use all CPU cores.");
                    recoveryOptions.Add("Restart the process to reset its affinity.");
                    break;
                
                case OptimizationActionType.UninstallApplication:
                    recoveryOptions.Add("Reinstall the application from the original installation source.");
                    recoveryOptions.Add("Restore from a system backup if available.");
                    recoveryOptions.Add("Use system restore to revert the uninstallation.");
                    break;
                
                case OptimizationActionType.AdjustPowerSettings:
                    recoveryOptions.Add("Reset the power settings to their original values.");
                    recoveryOptions.Add("Use the Windows power options control panel.");
                    recoveryOptions.Add("Restart the computer to apply the changes.");
                    break;
            }
            
            // General recovery options
            recoveryOptions.Add("Use System Restore to revert system changes.");
            recoveryOptions.Add("Check the Windows Event Log for errors.");
            recoveryOptions.Add("Run system diagnostics to check for issues.");
            
            return recoveryOptions;
        }

        /// <summary>
        /// Analyze the impact of an optimization action
        /// </summary>
        public ImpactAnalysisResult AnalyzeActionImpact(OptimizationAction action, SystemInfo systemInfo = null)
        {
            var result = new ImpactAnalysisResult { Action = action };
            
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? new SystemScanner(_logger, _config).Scan();
                
                // Calculate potential resource recovery
                result.PotentialRamRecovery = CalculatePotentialRamRecovery(action, systemInfo);
                result.PotentialCpuImprovement = CalculatePotentialCpuImprovement(action, systemInfo);
                
                // Calculate potential performance impact
                result.PotentialPerformanceImpact = CalculatePotentialPerformanceImpact(action, systemInfo);
                
                // Calculate potential stability impact
                result.PotentialStabilityImpact = CalculatePotentialStabilityImpact(action, systemInfo);
                
                // Determine if the impact is positive or negative
                result.IsPositiveImpact = result.PotentialPerformanceImpact > 0 ||
                                       result.PotentialStabilityImpact >= 0;
            }
            catch (Exception ex)
            {
                _logger.Error("RiskAnalyzer", 
                    $"Failed to analyze impact for action: {action.ActionType} on {action.Target}", 
                    null, ex);
                result.Error = ex.Message;
            }
            
            return result;
        }

        /// <summary>
        /// Calculate potential RAM recovery for an action
        /// </summary>
        private long CalculatePotentialRamRecovery(OptimizationAction action, SystemInfo systemInfo)
        {
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    var process = systemInfo.Processes.FirstOrDefault(p => 
                        p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                        p.Path.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (process != null)
                        return process.WorkingSet;
                    break;
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    var service = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (service != null && service.ProcessId > 0)
                    {
                        var hostingProcess = systemInfo.Processes.FirstOrDefault(p => p.Id == service.ProcessId);
                        if (hostingProcess != null)
                            return hostingProcess.WorkingSet;
                    }
                    break;
                
                case OptimizationActionType.ClearCache:
                    // Estimate cache size (this is a rough estimate)
                    return 100 * 1024 * 1024; // 100 MB
                
                case OptimizationActionType.DisableStartup:
                    var startup = systemInfo.StartupItems.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (startup != null)
                        return startup.EstimatedRamUsage;
                    break;
            }
            
            return 0;
        }

        /// <summary>
        /// Calculate potential CPU improvement for an action
        /// </summary>
        private float CalculatePotentialCpuImprovement(OptimizationAction action, SystemInfo systemInfo)
        {
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    var process = systemInfo.Processes.FirstOrDefault(p => 
                        p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                        p.Path.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (process != null)
                        return process.CpuUsage;
                    break;
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    var service = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (service != null && service.ProcessId > 0)
                    {
                        var hostingProcess = systemInfo.Processes.FirstOrDefault(p => p.Id == service.ProcessId);
                        if (hostingProcess != null)
                            return hostingProcess.CpuUsage;
                    }
                    break;
            }
            
            return 0f;
        }

        /// <summary>
        /// Calculate potential performance impact for an action
        /// </summary>
        private float CalculatePotentialPerformanceImpact(OptimizationAction action, SystemInfo systemInfo)
        {
            // Positive impact for closing processes and disabling startup
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    var process = systemInfo.Processes.FirstOrDefault(p => 
                        p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                        p.Path.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (process != null)
                    {
                        // Higher impact for processes using more resources
                        var ramImpact = process.WorkingSet / (1024.0 * 1024.0 * 1024.0); // GB
                        var cpuImpact = process.CpuUsage / 100f; // Percentage
                        return (float)(ramImpact * 0.5 + cpuImpact * 0.3);
                    }
                    break;
                
                case OptimizationActionType.DisableStartup:
                    var startup = systemInfo.StartupItems.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (startup != null)
                    {
                        // Impact based on startup item's estimated RAM usage
                        var ramImpact = startup.EstimatedRamUsage / (1024.0 * 1024.0 * 1024.0); // GB
                        return (float)(ramImpact * 0.8); // Higher impact for startup items
                    }
                    break;
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    var service = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (service != null)
                    {
                        // Lower impact for services (more caution needed)
                        return 0.1f;
                    }
                    break;
                
                case OptimizationActionType.ClearCache:
                    return 0.2f; // Moderate impact
                
                case OptimizationActionType.ChangePriority:
                    return 0.3f; // Moderate impact
                
                case OptimizationActionType.ChangeAffinity:
                    return 0.4f; // Higher impact
                
                case OptimizationActionType.AdjustPowerSettings:
                    return 0.5f; // Higher impact
            }
            
            return 0f;
        }

        /// <summary>
        /// Calculate potential stability impact for an action
        /// </summary>
        private float CalculatePotentialStabilityImpact(OptimizationAction action, SystemInfo systemInfo)
        {
            // Negative impact for actions that could cause instability
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    var process = systemInfo.Processes.FirstOrDefault(p => 
                        p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                        p.Path.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (process != null)
                    {
                        // Negative impact for critical processes
                        if (CriticalProcesses.IsCritical(process.Name))
                            return -1f; // Very negative
                        
                        // Negative impact for system processes
                        if (process.IsWindowsProcess || process.IsDriver)
                            return -0.8f;
                        
                        // Negative impact for services
                        if (process.IsService)
                            return -0.5f;
                        
                        // Positive impact for user processes
                        if (process.Category == ProcessCategory.UserApplication ||
                            process.Category == ProcessCategory.BackgroundApplication)
                            return 0.2f;
                    }
                    break;
                
                case OptimizationActionType.DisableStartup:
                    var startup = systemInfo.StartupItems.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (startup != null)
                    {
                        // Negative impact for Windows startup items
                        if (startup.IsWindowsItem)
                            return -0.5f;
                        
                        // Positive impact for user startup items
                        return 0.3f;
                    }
                    break;
                
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                    var service = systemInfo.Services.FirstOrDefault(s => 
                        s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                    if (service != null)
                    {
                        // Negative impact for critical services
                        if (service.IsCritical)
                            return -1f;
                        
                        // Negative impact for Windows services
                        if (service.IsWindowsService)
                            return -0.8f;
                        
                        // Negative impact for all services
                        return -0.5f;
                    }
                    break;
                
                case OptimizationActionType.ClearCache:
                    return -0.1f; // Slightly negative (could cause issues with some apps)
                
                case OptimizationActionType.ChangePriority:
                    return -0.2f; // Slightly negative (could affect performance)
                
                case OptimizationActionType.ChangeAffinity:
                    return -0.3f; // Moderately negative (could affect performance)
                
                case OptimizationActionType.AdjustPowerSettings:
                    return -0.1f; // Slightly negative (could affect power consumption)
            }
            
            return 0f;
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the analyzer
        /// </summary>
        public void Dispose()
        {
            try
            {
                _processAnalyzer?.Dispose();
                _safetyValidator?.Dispose();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Risk analysis result
    /// </summary>
    public class RiskAnalysisResult
    {
        /// <summary>
        /// The action being analyzed
        /// </summary>
        public OptimizationAction Action { get; set; } = new OptimizationAction();
        
        /// <summary>
        /// The determined risk level
        /// </summary>
        public RiskLevel DeterminedRiskLevel { get; set; } = RiskLevel.Medium;
        
        /// <summary>
        /// Whether the action is safe to perform
        /// </summary>
        public bool IsSafe { get; set; } = false;
        
        /// <summary>
        /// List of safety recommendations
        /// </summary>
        public List<string> Recommendations { get; set; } = new List<string>();
        
        /// <summary>
        /// Whether the action requires user confirmation
        /// </summary>
        public bool RequiresConfirmation { get; set; } = true;
        
        /// <summary>
        /// Whether the action can be performed automatically
        /// </summary>
        public bool CanAutoPerform { get; set; } = false;
        
        /// <summary>
        /// List of potential side effects
        /// </summary>
        public List<string> PotentialSideEffects { get; set; } = new List<string>();
        
        /// <summary>
        /// List of recovery options
        /// </summary>
        public List<string> RecoveryOptions { get; set; } = new List<string>();
        
        /// <summary>
        /// Error message if analysis failed
        /// </summary>
        public string Error { get; set; } = string.Empty;
    }

    /// <summary>
    /// Impact analysis result
    /// </summary>
    public class ImpactAnalysisResult
    {
        /// <summary>
        /// The action being analyzed
        /// </summary>
        public OptimizationAction Action { get; set; } = new OptimizationAction();
        
        /// <summary>
        /// Potential RAM recovery in bytes
        /// </summary>
        public long PotentialRamRecovery { get; set; }
        
        /// <summary>
        /// Potential CPU improvement percentage
        /// </summary>
        public float PotentialCpuImprovement { get; set; }
        
        /// <summary>
        /// Potential performance impact (positive or negative)
        /// </summary>
        public float PotentialPerformanceImpact { get; set; }
        
        /// <summary>
        /// Potential stability impact (positive or negative)
        /// </summary>
        public float PotentialStabilityImpact { get; set; }
        
        /// <summary>
        /// Whether the impact is positive
        /// </summary>
        public bool IsPositiveImpact { get; set; }
        
        /// <summary>
        /// Error message if analysis failed
        /// </summary>
        public string Error { get; set; } = string.Empty;
    }
}

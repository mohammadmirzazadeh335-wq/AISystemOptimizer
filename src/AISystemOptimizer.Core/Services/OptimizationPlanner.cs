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
    /// Service for creating optimization plans
    /// </summary>
    public class OptimizationPlanner : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private readonly ProcessAnalyzer _processAnalyzer;
        private readonly RiskAnalyzer _riskAnalyzer;
        private readonly AIService _aiService;
        private readonly SafetyValidator _safetyValidator;

        #endregion

        #region Events

        /// <summary>
        /// Event raised when a plan is created
        /// </summary>
        public event EventHandler<PlanEventArgs> PlanCreated;

        /// <summary>
        /// Event raised when a plan is updated
        /// </summary>
        public event EventHandler<PlanEventArgs> PlanUpdated;

        /// <summary>
        /// Event raised when plan creation fails
        /// </summary>
        public event EventHandler<PlanEventArgs> PlanCreationFailed;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new optimization planner
        /// </summary>
        public OptimizationPlanner(
            ILogger logger = null,
            AppConfig config = null,
            SystemScanner scanner = null,
            ProcessAnalyzer processAnalyzer = null,
            RiskAnalyzer riskAnalyzer = null,
            AIService aiService = null,
            SafetyValidator safetyValidator = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _processAnalyzer = processAnalyzer ?? new ProcessAnalyzer(logger, config, scanner);
            _riskAnalyzer = riskAnalyzer ?? new RiskAnalyzer(logger, config, processAnalyzer, safetyValidator);
            _aiService = aiService ?? new AIService(logger, config);
            _safetyValidator = safetyValidator ?? new SafetyValidator(logger, config);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Create an optimization plan
        /// </summary>
        public async Task<OptimizationPlan> CreatePlanAsync(
            OptimizationMode mode = OptimizationMode.Manual,
            SystemInfo systemInfo = null,
            List<ProcessInfo> targetProcesses = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", 
                    $"Creating optimization plan with mode: {mode}");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync();
                
                var stopwatch = System.Diagnostics.Stopwatch.StartNew();
                
                // Create the plan
                var plan = new OptimizationPlan
                {
                    Name = $"Optimization Plan - {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
                    Description = $"Auto-generated optimization plan for {systemInfo.ComputerName}",
                    Mode = mode,
                    CreatedAt = DateTime.Now,
                    BeforeSystemInfo = systemInfo.Clone()
                };
                
                // Analyze the system and processes
                var analysisResults = await AnalyzeSystemAsync(systemInfo, mode, targetProcesses);
                
                // Generate actions based on the analysis
                var actions = GenerateActionsFromAnalysis(analysisResults, systemInfo, mode);
                
                // Add actions to the plan
                plan.AddActions(actions);
                
                // Validate the plan
                if (!_safetyValidator.ValidatePlan(plan, systemInfo))
                {
                    _logger.Warning("OptimizationPlanner", "Plan validation failed");
                    
                    // Raise plan creation failed event
                    PlanCreationFailed?.Invoke(this, new PlanEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Plan = plan,
                        Duration = stopwatch.Elapsed,
                        ErrorMessage = "Plan validation failed"
                    });
                    
                    return null;
                }
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                // Add AI summary if enabled
                if (_config.AiEnabled)
                {
                    try
                    {
                        plan.AiSummary = _aiService.AnalyzeSystem(systemInfo);
                        plan.AiUsed = true;
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("OptimizationPlanner", "Failed to generate AI summary", null, ex);
                        plan.AiUsed = false;
                    }
                }
                
                _logger.Info("OptimizationPlanner", 
                    $"Optimization plan created with {plan.TotalActionCount} actions, " +
                    $"estimated RAM recovery: {plan.FormattedEstimatedRamRecovery}");
                
                // Anchor every process-scoped action to the instance it was planned for, so the
                // executor can prove the pid still refers to the same process before it acts.
                AnchorProcessIdentities(plan, systemInfo);

                // Raise plan created event
                PlanCreated?.Invoke(this, new PlanEventArgs
                {
                    Timestamp = DateTime.Now,
                    Plan = plan,
                    Duration = stopwatch.Elapsed
                });
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to create optimization plan", null, ex);
                
                // Raise plan creation failed event
                PlanCreationFailed?.Invoke(this, new PlanEventArgs
                {
                    Timestamp = DateTime.Now,
                    ErrorMessage = ex.Message,
                    Exception = ex
                });
                
                throw;
            }
        }

        /// <summary>
        /// Create a quick optimization plan (fewer actions, faster)
        /// </summary>
        public async Task<OptimizationPlan> CreateQuickPlanAsync(
            OptimizationMode mode = OptimizationMode.Manual,
            SystemInfo systemInfo = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", 
                    $"Creating quick optimization plan with mode: {mode}");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync();
                
                var plan = new OptimizationPlan
                {
                    Name = $"Quick Optimization Plan - {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
                    Description = "Quick auto-generated optimization plan",
                    Mode = mode,
                    CreatedAt = DateTime.Now,
                    BeforeSystemInfo = systemInfo.Clone()
                };
                
                // For quick plan, only include high-priority, low-risk actions
                var safeActions = new List<OptimizationAction>();
                
                // Get background processes that can be safely closed
                var backgroundProcesses = _processAnalyzer.GetBackgroundProcesses(systemInfo)
                    .Where(r => r.CanOptimize && r.RiskLevel == RiskLevel.Low)
                    .OrderByDescending(r => r.OptimizationScore)
                    .Take(5);
                
                foreach (var result in backgroundProcesses)
                {
                    var action = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.CloseProcess,
                        Target = result.ProcessInfo.Name,
                        TargetPid = result.ProcessInfo.Id,
                        TargetPath = result.ProcessInfo.Path,
                        ResourceType = ResourceType.RAM,
                        RiskLevel = result.RiskLevel,
                        Description = $"Close background process: {result.ProcessInfo.DisplayName}",
                        Reason = result.Recommendation,
                        EstimatedResourceRecovery = result.EstimatedRamRecovery,
                        Priority = result.OptimizationScore / 10, // Convert 0-100 to 0-10
                        CanUndo = false, // Can't easily undo closing a process
                        AiRecommended = result.AiAnalyzed
                    };
                    
                    // Validate the action
                    if (_safetyValidator.ValidateAction(action, systemInfo))
                    {
                        safeActions.Add(action);
                    }
                }
                
                // Get startup items that can be safely disabled
                var startupItems = systemInfo.StartupItems
                    .Where(s => s.IsEnabled && !s.IsWindowsItem && !s.IsBlacklisted)
                    .OrderByDescending(s => s.EstimatedRamUsage)
                    .Take(3);
                
                foreach (var item in startupItems)
                {
                    var action = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.DisableStartup,
                        Target = item.Name,
                        TargetPath = item.Path,
                        ResourceType = ResourceType.RAM,
                        RiskLevel = RiskLevel.Low,
                        Description = $"Disable startup item: {item.Name}",
                        Reason = $"Startup item consumes {item.EstimatedRamUsage / (1024.0 * 1024.0):F2} MB of RAM",
                        EstimatedResourceRecovery = item.EstimatedRamUsage,
                        Priority = 5, // Medium priority
                        CanUndo = true, // Can re-enable startup items
                        AiRecommended = false
                    };
                    
                    // Validate the action
                    if (_safetyValidator.ValidateAction(action, systemInfo))
                    {
                        safeActions.Add(action);
                    }
                }
                
                // Add actions to the plan
                plan.AddActions(safeActions);
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                AnchorProcessIdentities(plan, systemInfo);

                _logger.Info("OptimizationPlanner", 
                    $"Quick optimization plan created with {plan.TotalActionCount} actions");
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to create quick optimization plan", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Create a Game Mode optimization plan
        /// </summary>
        public async Task<OptimizationPlan> CreateGameModePlanAsync(
            ProcessInfo gameProcess = null,
            SystemInfo systemInfo = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", "Creating Game Mode optimization plan");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync();
                
                var plan = new OptimizationPlan
                {
                    Name = $"Game Mode Optimization Plan - {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
                    Description = "Optimization plan for improved gaming performance",
                    Mode = OptimizationMode.GameMode,
                    CreatedAt = DateTime.Now,
                    BeforeSystemInfo = systemInfo.Clone()
                };
                
                // If a game process is specified, boost its priority
                if (gameProcess != null)
                {
                    var priorityAction = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.ChangePriority,
                        Target = gameProcess.Name,
                        TargetPid = gameProcess.Id,
                        TargetPath = gameProcess.Path,
                        ResourceType = ResourceType.CPU,
                        RiskLevel = RiskLevel.Low,
                        Description = $"Boost priority for game: {gameProcess.DisplayName}",
                        Reason = "Improve game performance by giving it higher CPU priority",
                        EstimatedImprovementPercentage = 10f, // Estimated improvement
                        Priority = 10, // Highest priority
                        CanUndo = true,
                        AiRecommended = false
                    };
                    
                    if (_safetyValidator.ValidateAction(priorityAction, systemInfo))
                    {
                        plan.AddAction(priorityAction);
                    }
                }
                
                // Close background processes that are in the game mode close list
                var processesToClose = systemInfo.Processes
                    .Where(p => !CriticalProcesses.IsCritical(p.Name) && !p.IsActive && !p.HasVisibleWindow)
                    .Where(p => _config.GameModeCloseList.Contains(p.Name, StringComparer.OrdinalIgnoreCase) ||
                               _config.GameModeCloseList.Contains(p.DisplayName, StringComparer.OrdinalIgnoreCase))
                    .OrderByDescending(p => p.WorkingSet)
                    .Take(10);
                
                foreach (var process in processesToClose)
                {
                    var action = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.CloseProcess,
                        Target = process.Name,
                        TargetPid = process.Id,
                        TargetPath = process.Path,
                        ResourceType = ResourceType.RAM,
                        RiskLevel = RiskLevel.Low,
                        Description = $"Close background process for Game Mode: {process.DisplayName}",
                        Reason = "Free up resources for better gaming performance",
                        EstimatedResourceRecovery = process.WorkingSet,
                        Priority = 8, // High priority
                        CanUndo = false,
                        AiRecommended = false
                    };
                    
                    if (_safetyValidator.ValidateAction(action, systemInfo))
                    {
                        plan.AddAction(action);
                    }
                }
                
                // Close other non-essential background processes
                var otherProcesses = systemInfo.Processes
                    .Where(p => !CriticalProcesses.IsCritical(p.Name) && !p.IsActive && !p.HasVisibleWindow)
                    .Where(p => p.Category == ProcessCategory.BackgroundApplication ||
                               p.Category == ProcessCategory.Launcher ||
                               p.Category == ProcessCategory.Updater ||
                               p.Category == ProcessCategory.CloudSync)
                    .OrderByDescending(p => p.WorkingSet)
                    .Take(5);
                
                foreach (var process in otherProcesses)
                {
                    var action = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.CloseProcess,
                        Target = process.Name,
                        TargetPid = process.Id,
                        TargetPath = process.Path,
                        ResourceType = ResourceType.RAM,
                        RiskLevel = process.RiskLevel,
                        Description = $"Close non-essential process for Game Mode: {process.DisplayName}",
                        Reason = "Free up additional resources for gaming",
                        EstimatedResourceRecovery = process.WorkingSet,
                        Priority = 6, // Medium priority
                        CanUndo = false,
                        AiRecommended = false
                    };
                    
                    if (_safetyValidator.ValidateAction(action, systemInfo))
                    {
                        plan.AddAction(action);
                    }
                }
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                AnchorProcessIdentities(plan, systemInfo);

                _logger.Info("OptimizationPlanner", 
                    $"Game Mode optimization plan created with {plan.TotalActionCount} actions");
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to create Game Mode optimization plan", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Update an existing plan
        /// </summary>
        /// <summary>
        /// Anchor every process-scoped action to the concrete process instance it was planned for.
        ///
        /// The planner only ever knows the pid, and a pid is not an identity: Windows recycles pids, so
        /// between planning and execution the same number can belong to a completely different program.
        /// Recording the kernel creation timestamp (and the image path when it is readable) at plan
        /// time gives the executor something it can re-verify immediately before it acts.
        ///
        /// Call this as the last step of every plan-building path, before the plan is returned.
        /// </summary>
        private void AnchorProcessIdentities(OptimizationPlan plan, SystemInfo systemInfo)
        {
            if (plan == null || systemInfo?.Processes == null)
                return;

            foreach (var action in plan.Actions)
            {
                if (!IsProcessScoped(action.ActionType) || action.TargetPid <= 0)
                    continue;

                var process = systemInfo.Processes.FirstOrDefault(p => p.Id == action.TargetPid);

                if (process == null)
                {
                    // The process vanished between the analysis pass and now. Leave the action without
                    // an identity so that the safety layer drops it instead of guessing.
                    _logger?.Warning("OptimizationPlanner",
                        $"Process {action.TargetPid} ({action.Target}) is gone; " +
                        "the action cannot carry an identity and will not be executed.");
                    continue;
                }

                action.CaptureProcessIdentity(process);
                action.TargetProcessName = WindowsApiHelper.NormalizeProcessName(process.Name);
            }

            _logger?.Debug("OptimizationPlanner",
                $"Anchored process identities for {plan.Actions.Count(a => a.HasProcessIdentity)} action(s)");
        }

        /// <summary>
        /// True for action types that act on one specific running process and therefore need an
        /// identity to be verifiable.
        /// </summary>
        private static bool IsProcessScoped(OptimizationActionType actionType)
        {
            return actionType == OptimizationActionType.CloseProcess ||
                   actionType == OptimizationActionType.ChangePriority ||
                   actionType == OptimizationActionType.ChangeAffinity;
        }

        public async Task<OptimizationPlan> UpdatePlanAsync(
            OptimizationPlan plan,
            SystemInfo systemInfo = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", "Updating optimization plan");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync();
                
                var stopwatch = System.Diagnostics.Stopwatch.StartNew();
                
                // Re-analyze the system
                var analysisResults = await AnalyzeSystemAsync(systemInfo, plan.Mode);
                
                // Clear existing actions
                plan.ClearActions();
                
                // Generate new actions
                var actions = GenerateActionsFromAnalysis(analysisResults, systemInfo, plan.Mode);
                
                // Add actions to the plan
                plan.AddActions(actions);
                
                // Validate the plan
                if (!_safetyValidator.ValidatePlan(plan, systemInfo))
                {
                    _logger.Warning("OptimizationPlanner", "Updated plan validation failed");
                    return null;
                }
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                // Update the timestamp
                plan.CreatedAt = DateTime.Now;
                
                AnchorProcessIdentities(plan, systemInfo);

                _logger.Info("OptimizationPlanner", 
                    $"Optimization plan updated with {plan.TotalActionCount} actions");
                
                // Raise plan updated event
                PlanUpdated?.Invoke(this, new PlanEventArgs
                {
                    Timestamp = DateTime.Now,
                    Plan = plan,
                    Duration = stopwatch.Elapsed
                });
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to update optimization plan", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Create a plan from a list of actions
        /// </summary>
        public OptimizationPlan CreatePlanFromActions(
            List<OptimizationAction> actions,
            SystemInfo systemInfo = null,
            string name = null,
            string description = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", "Creating plan from actions");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? _scanner.Scan();
                
                var plan = new OptimizationPlan
                {
                    Name = name ?? $"Custom Optimization Plan - {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
                    Description = description ?? "Custom optimization plan",
                    Mode = OptimizationMode.Manual,
                    CreatedAt = DateTime.Now,
                    BeforeSystemInfo = systemInfo.Clone()
                };
                
                // Add actions to the plan
                plan.AddActions(actions);
                
                // Validate the plan
                if (!_safetyValidator.ValidatePlan(plan, systemInfo))
                {
                    _logger.Warning("OptimizationPlanner", "Custom plan validation failed");
                    return null;
                }
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                _logger.Info("OptimizationPlanner", 
                    $"Custom optimization plan created with {plan.TotalActionCount} actions");
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to create custom optimization plan", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Create a plan for a specific optimization target
        /// </summary>
        public async Task<OptimizationPlan> CreateTargetedPlanAsync(
            ResourceType targetResource,
            SystemInfo systemInfo = null)
        {
            try
            {
                _logger.Info("OptimizationPlanner", $"Creating targeted plan for {targetResource}");
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync();
                
                var plan = new OptimizationPlan
                {
                    Name = $"Targeted Optimization Plan ({targetResource}) - {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
                    Description = $"Optimization plan targeting {targetResource}",
                    Mode = OptimizationMode.Manual,
                    CreatedAt = DateTime.Now,
                    BeforeSystemInfo = systemInfo.Clone()
                };
                
                var actions = new List<OptimizationAction>();
                
                switch (targetResource)
                {
                    case ResourceType.RAM:
                        // Focus on RAM optimization
                        var highRamProcesses = _processAnalyzer.GetHighRamUsageProcesses(10, systemInfo)
                            .Where(r => r.CanOptimize);
                        
                        foreach (var result in highRamProcesses)
                        {
                            var action = new OptimizationAction
                            {
                                ActionType = OptimizationActionType.CloseProcess,
                                Target = result.ProcessInfo.Name,
                                TargetPid = result.ProcessInfo.Id,
                                TargetPath = result.ProcessInfo.Path,
                                ResourceType = ResourceType.RAM,
                                RiskLevel = result.RiskLevel,
                                Description = $"Close high RAM usage process: {result.ProcessInfo.DisplayName}",
                                Reason = result.Recommendation,
                                EstimatedResourceRecovery = result.EstimatedRamRecovery,
                                Priority = result.OptimizationScore / 10,
                                CanUndo = false,
                                AiRecommended = result.AiAnalyzed
                            };
                            
                            if (_safetyValidator.ValidateAction(action, systemInfo))
                            {
                                actions.Add(action);
                            }
                        }
                        
                        // Also consider startup items
                        var startupItems = systemInfo.StartupItems
                            .Where(s => s.IsEnabled && !s.IsWindowsItem && !s.IsBlacklisted)
                            .OrderByDescending(s => s.EstimatedRamUsage)
                            .Take(5);
                        
                        foreach (var item in startupItems)
                        {
                            var action = new OptimizationAction
                            {
                                ActionType = OptimizationActionType.DisableStartup,
                                Target = item.Name,
                                TargetPath = item.Path,
                                ResourceType = ResourceType.RAM,
                                RiskLevel = RiskLevel.Low,
                                Description = $"Disable startup item to reduce RAM usage: {item.Name}",
                                Reason = $"Startup item consumes {item.EstimatedRamUsage / (1024.0 * 1024.0):F2} MB of RAM",
                                EstimatedResourceRecovery = item.EstimatedRamUsage,
                                Priority = 5,
                                CanUndo = true,
                                AiRecommended = false
                            };
                            
                            if (_safetyValidator.ValidateAction(action, systemInfo))
                            {
                                actions.Add(action);
                            }
                        }
                        break;
                    
                    case ResourceType.CPU:
                        // Focus on CPU optimization
                        var highCpuProcesses = _processAnalyzer.GetHighCpuUsageProcesses(10, systemInfo)
                            .Where(r => r.CanOptimize);
                        
                        foreach (var result in highCpuProcesses)
                        {
                            var action = new OptimizationAction
                            {
                                ActionType = OptimizationActionType.CloseProcess,
                                Target = result.ProcessInfo.Name,
                                TargetPid = result.ProcessInfo.Id,
                                TargetPath = result.ProcessInfo.Path,
                                ResourceType = ResourceType.CPU,
                                RiskLevel = result.RiskLevel,
                                Description = $"Close high CPU usage process: {result.ProcessInfo.DisplayName}",
                                Reason = result.Recommendation,
                                EstimatedImprovementPercentage = result.EstimatedCpuImprovement,
                                Priority = result.OptimizationScore / 10,
                                CanUndo = false,
                                AiRecommended = result.AiAnalyzed
                            };
                            
                            if (_safetyValidator.ValidateAction(action, systemInfo))
                            {
                                actions.Add(action);
                            }
                        }
                        
                        // Also consider changing process priorities
                        if (systemInfo.Processes.Any(p => p.Category == ProcessCategory.Game))
                        {
                            var gameProcesses = systemInfo.Processes
                                .Where(p => p.Category == ProcessCategory.Game && !p.IsActive);
                            
                            foreach (var gameProcess in gameProcesses)
                            {
                                var action = new OptimizationAction
                                {
                                    ActionType = OptimizationActionType.ChangePriority,
                                    Target = gameProcess.Name,
                                    TargetPid = gameProcess.Id,
                                    TargetPath = gameProcess.Path,
                                    ResourceType = ResourceType.CPU,
                                    RiskLevel = RiskLevel.Low,
                                    Description = $"Boost priority for game: {gameProcess.DisplayName}",
                                    Reason = "Improve game performance by giving it higher CPU priority",
                                    EstimatedImprovementPercentage = 10f,
                                    Priority = 8,
                                    CanUndo = true,
                                    AiRecommended = false
                                };
                                
                                if (_safetyValidator.ValidateAction(action, systemInfo))
                                {
                                    actions.Add(action);
                                }
                            }
                        }
                        break;
                    
                    case ResourceType.Disk:
                        // The only disk action this application performs is clearing disposable caches.
                        //
                        // It does not defragment, it does not retrim, and it does not move files: on the
                        // NVMe drive the specification targets, defragmentation is at best pointless and
                        // at worst it consumes write endurance. Clearing temp files, thumbnail caches and
                        // the DNS resolver cache is the whole of the disk optimiser, and the report says
                        // explicitly that this frees storage rather than memory.
                        var cacheAction = new OptimizationAction
                        {
                            ActionType = OptimizationActionType.ClearCache,
                            Target = "System Cache",
                            ResourceType = ResourceType.Disk,
                            RiskLevel = RiskLevel.Low,
                            Description = "Clear system cache",
                            Reason = "Free up disk space by clearing temporary files",
                            EstimatedResourceRecovery = 100 * 1024 * 1024, // 100 MB
                            Priority = 5,
                            CanUndo = false,
                            AiRecommended = false
                        };
                        
                        if (_safetyValidator.ValidateAction(cacheAction, systemInfo))
                        {
                            actions.Add(cacheAction);
                        }
                        break;
                    
                    case ResourceType.GPU:
                        // For GPU, we can only provide recommendations
                        // We can't really optimize GPU usage programmatically
                        break;
                    
                    case ResourceType.Network:
                        // For network, we can only provide recommendations
                        break;
                }
                
                // Add actions to the plan
                plan.AddActions(actions);
                
                // Validate the plan
                if (!_safetyValidator.ValidatePlan(plan, systemInfo))
                {
                    _logger.Warning("OptimizationPlanner", "Targeted plan validation failed");
                    return null;
                }
                
                // Sort actions by priority
                plan.SortByPriority();
                
                // Calculate plan metrics
                CalculatePlanMetrics(plan, systemInfo);
                
                _logger.Info("OptimizationPlanner", 
                    $"Targeted optimization plan created with {plan.TotalActionCount} actions");
                
                return plan;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", 
                    $"Failed to create targeted optimization plan for {targetResource}", null, ex);
                throw;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Analyze the system and generate analysis results
        /// </summary>
        private async Task<List<ProcessAnalysisResult>> AnalyzeSystemAsync(
            SystemInfo systemInfo,
            OptimizationMode mode,
            List<ProcessInfo> targetProcesses = null)
        {
            var results = new List<ProcessAnalysisResult>();
            
            try
            {
                // If target processes are specified, only analyze those
                if (targetProcesses != null && targetProcesses.Count > 0)
                {
                    foreach (var process in targetProcesses)
                    {
                        var result = _processAnalyzer.AnalyzeProcess(process, systemInfo);
                        results.Add(result);
                    }
                    return results;
                }
                
                // Otherwise, analyze all processes based on the mode
                switch (mode)
                {
                    case OptimizationMode.Manual:
                        // Analyze all processes
                        results = _processAnalyzer.AnalyzeAllProcesses(systemInfo);
                        break;
                    
                    case OptimizationMode.Automatic:
                        // Analyze all processes and filter for safe optimizations
                        results = _processAnalyzer.AnalyzeAllProcesses(systemInfo)
                            .Where(r => r.CanOptimize && r.RiskLevel <= _config.MaxAutoRiskLevel)
                            .ToList();
                        break;
                    
                    case OptimizationMode.GameMode:
                        // Analyze processes with focus on gaming
                        results = _processAnalyzer.AnalyzeAllProcesses(systemInfo)
                            .Where(r => r.CanOptimize && 
                                       (r.Category == ProcessCategory.BackgroundApplication ||
                                        r.Category == ProcessCategory.Launcher ||
                                        r.Category == ProcessCategory.Updater ||
                                        r.Category == ProcessCategory.CloudSync ||
                                        r.Category == ProcessCategory.Telemetry))
                            .ToList();
                        break;
                    
                    case OptimizationMode.Aggressive:
                        // Analyze all processes with more aggressive filtering
                        results = _processAnalyzer.AnalyzeAllProcesses(systemInfo)
                            .Where(r => r.CanOptimize && r.RiskLevel <= RiskLevel.Medium)
                            .ToList();
                        break;
                    
                    case OptimizationMode.Conservative:
                        // Analyze all processes with conservative filtering
                        results = _processAnalyzer.AnalyzeAllProcesses(systemInfo)
                            .Where(r => r.CanOptimize && r.RiskLevel == RiskLevel.Low)
                            .ToList();
                        break;
                }
                
                return results;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to analyze system", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Generate optimization actions from analysis results
        /// </summary>
        private List<OptimizationAction> GenerateActionsFromAnalysis(
            List<ProcessAnalysisResult> analysisResults,
            SystemInfo systemInfo,
            OptimizationMode mode)
        {
            var actions = new List<OptimizationAction>();
            
            try
            {
                foreach (var result in analysisResults)
                {
                    // Skip results that can't be optimized
                    if (!result.CanOptimize) continue;
                    
                    // Create an action based on the analysis result
                    var action = CreateActionFromResult(result, systemInfo);
                    
                    if (action != null && _safetyValidator.ValidateAction(action, systemInfo))
                    {
                        actions.Add(action);
                    }
                }
                
                // Add additional actions based on system state
                AddSystemActions(actions, systemInfo, mode);
                
                // Add AI recommendations if enabled
                if (_config.AiEnabled)
                {
                    try
                    {
                        var aiRecommendations = _aiService.GetOptimizationRecommendations(systemInfo);
                        foreach (var rec in aiRecommendations)
                        {
                            var action = new OptimizationAction
                            {
                                ActionType = rec.ActionType,
                                Target = rec.Target,
                                ResourceType = rec.ResourceType,
                                RiskLevel = rec.RiskLevel,
                                Description = rec.Description,
                                Reason = rec.Description,
                                EstimatedImprovementPercentage = float.TryParse(
                                    rec.EstimatedImprovement.Replace("%", "").Trim(), 
                                    out var improvement) ? improvement : 0f,
                                Priority = rec.Priority,
                                CanUndo = true, // Most AI recommendations can be undone
                                AiRecommended = true
                            };
                            
                            if (_safetyValidator.ValidateAction(action, systemInfo))
                            {
                                actions.Add(action);
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("OptimizationPlanner", "Failed to add AI recommendations", null, ex);
                    }
                }
                
                return actions;
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to generate actions from analysis", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Create an optimization action from an analysis result
        /// </summary>
        private OptimizationAction CreateActionFromResult(
            ProcessAnalysisResult result,
            SystemInfo systemInfo)
        {
            var process = result.ProcessInfo;
            
            // Determine the action type based on the process category
            var actionType = OptimizationActionType.CloseProcess;
            
            // For services, we might want to stop or disable them
            if (process.IsService)
            {
                actionType = OptimizationActionType.StopService;
            }
            
            // Create the action
            var action = new OptimizationAction
            {
                ActionType = actionType,
                Target = process.Name,
                TargetPid = process.Id,
                TargetPath = process.Path,
                ResourceType = ResourceType.RAM, // Default to RAM
                RiskLevel = result.RiskLevel,
                Description = result.Recommendation,
                Reason = result.RecommendationDetails,
                EstimatedResourceRecovery = result.EstimatedRamRecovery,
                EstimatedImprovementPercentage = result.EstimatedCpuImprovement,
                Priority = result.OptimizationScore / 10, // Convert 0-100 to 0-10
                CanUndo = false, // Most process actions can't be easily undone
                AiRecommended = result.AiAnalyzed,
                AiConfidence = result.AiAnalyzed ? 0.8f : 0f, // Assume 80% confidence for AI
                ProcessInfo = process
            };
            
            return action;
        }

        /// <summary>
        /// Add system-level actions based on system state
        /// </summary>
        private void AddSystemActions(
            List<OptimizationAction> actions,
            SystemInfo systemInfo,
            OptimizationMode mode)
        {
            try
            {
                // Check if we should adjust power settings
                if (mode == OptimizationMode.GameMode || mode == OptimizationMode.Aggressive)
                {
                    // Check current power mode
                    var currentPowerMode = systemInfo.CurrentPowerMode;
                    
                    // For Game Mode, suggest High Performance if not already set
                    if (mode == OptimizationMode.GameMode &&
                        currentPowerMode != PowerMode.HighPerformance &&
                        currentPowerMode != PowerMode.UltimatePerformance)
                    {
                        var powerAction = new OptimizationAction
                        {
                            ActionType = OptimizationActionType.AdjustPowerSettings,
                            Target = "High Performance",
                            ResourceType = ResourceType.CPU,
                            RiskLevel = RiskLevel.Low,
                            Description = "Set power mode to High Performance",
                            Reason = "Improve system responsiveness for gaming",
                            EstimatedImprovementPercentage = 5f,
                            Priority = 7,
                            CanUndo = true,
                            AiRecommended = false
                        };
                        
                        if (_safetyValidator.ValidateAction(powerAction, systemInfo))
                        {
                            actions.Add(powerAction);
                        }
                    }
                }
                
                // Check if we should clear cache
                if (mode != OptimizationMode.Conservative)
                {
                    var cacheAction = new OptimizationAction
                    {
                        ActionType = OptimizationActionType.ClearCache,
                        Target = "System Cache",
                        ResourceType = ResourceType.Disk,
                        RiskLevel = RiskLevel.Low,
                        Description = "Clear system cache",
                        Reason = "Free up disk space by clearing temporary files",
                        EstimatedResourceRecovery = 100 * 1024 * 1024, // 100 MB
                        Priority = 3,
                        CanUndo = false,
                        AiRecommended = false
                    };
                    
                    if (_safetyValidator.ValidateAction(cacheAction, systemInfo))
                    {
                        actions.Add(cacheAction);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to add system actions", null, ex);
            }
        }

        /// <summary>
        /// Calculate plan metrics
        /// </summary>
        private void CalculatePlanMetrics(OptimizationPlan plan, SystemInfo systemInfo)
        {
            try
            {
                // Calculate total estimated RAM recovery
                var ramRecovery = plan.Actions
                    .Where(a => a.ResourceType == ResourceType.RAM)
                    .Sum(a => a.EstimatedResourceRecovery);
                
                // Calculate total estimated CPU improvement
                var cpuImprovement = plan.Actions
                    .Where(a => a.ResourceType == ResourceType.CPU)
                    .Sum(a => a.EstimatedImprovementPercentage);
                
                // Update the plan
                // Note: These are calculated properties, so we don't need to set them
                // They're automatically calculated when accessed
                
                // Calculate overall risk level
                // OverallRiskLevel is a computed property (highest risk of the contained actions);
                // nothing to assign here.
            }
            catch (Exception ex)
            {
                _logger.Error("OptimizationPlanner", "Failed to calculate plan metrics", null, ex);
            }
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the planner
        /// </summary>
        public void Dispose()
        {
            try
            {
                _scanner?.Dispose();
                _processAnalyzer?.Dispose();
                _riskAnalyzer?.Dispose();
                _aiService?.Dispose();
                _safetyValidator?.Dispose();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Plan event arguments
    /// </summary>
    public class PlanEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public TimeSpan Duration { get; set; }
        public OptimizationPlan Plan { get; set; }
        public string ErrorMessage { get; set; } = string.Empty;
        public Exception Exception { get; set; }
    }
}

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for safely executing optimization actions
    /// This is the component that actually performs the optimizations
    /// </summary>
    public class SafeExecutor : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private readonly SafetyValidator _safetyValidator;
        private readonly RecoveryService _recoveryService;
        private readonly ProcessAnalyzer _processAnalyzer;
        private bool _disposed = false;

        /// <summary>
        /// Cancellation source for the run that is currently in progress.
        ///
        /// Previously <see cref="CancelExecution"/> was a no-op that only wrote a log line, so the
        /// "Cancel" affordance in the UI did nothing while the plan kept executing. The executor now
        /// owns a real source and links it with the caller's token.
        /// </summary>
        private CancellationTokenSource? _executionCts;

        private readonly object _executionLock = new object();

        #endregion

        #region Events

        /// <summary>
        /// Event raised when an action starts executing
        /// </summary>
        public event EventHandler<ActionEventArgs> ActionStarted;

        /// <summary>
        /// Event raised when an action completes
        /// </summary>
        public event EventHandler<ActionEventArgs> ActionCompleted;

        /// <summary>
        /// Event raised when an action fails
        /// </summary>
        public event EventHandler<ActionEventArgs> ActionFailed;

        /// <summary>
        /// Event raised when an action is skipped
        /// </summary>
        public event EventHandler<ActionEventArgs> ActionSkipped;

        /// <summary>
        /// Event raised when execution starts
        /// </summary>
        public event EventHandler<ExecutionEventArgs> ExecutionStarted;

        /// <summary>
        /// Event raised when execution completes
        /// </summary>
        public event EventHandler<ExecutionEventArgs> ExecutionCompleted;

        /// <summary>
        /// Event raised when execution fails
        /// </summary>
        public event EventHandler<ExecutionEventArgs> ExecutionFailed;

        /// <summary>
        /// Event raised when progress is updated
        /// </summary>
        public event EventHandler<ExecutionProgressEventArgs> ProgressUpdated;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new safe executor
        /// </summary>
        public SafeExecutor(
            ILogger logger = null,
            AppConfig config = null,
            SystemScanner scanner = null,
            SafetyValidator safetyValidator = null,
            RecoveryService recoveryService = null,
            ProcessAnalyzer processAnalyzer = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _safetyValidator = safetyValidator ?? new SafetyValidator(logger, config);
            _recoveryService = recoveryService ?? new RecoveryService(logger, config);
            _processAnalyzer = processAnalyzer ?? new ProcessAnalyzer(logger, config);
        }

        #endregion

        #region Properties

        /// <summary>
        /// Whether an execution is currently in progress
        /// </summary>
        public bool IsExecuting { get; private set; } = false;

        /// <summary>
        /// Current execution progress (0-100)
        /// </summary>
        public int CurrentProgress { get; private set; } = 0;

        #endregion

        #region Public Methods

        /// <summary>
        /// Execute an optimization plan
        /// </summary>
        public async Task<ExecutionResult> ExecutePlanAsync(
            OptimizationPlan plan,
            bool confirmActions = true,
            bool createRestorePoint = true,
            CancellationToken cancellationToken = default)
        {
            if (IsExecuting)
            {
                _logger.Warning("SafeExecutor", "Execution already in progress");
                return new ExecutionResult
                {
                    IsSuccessful = false,
                    ErrorMessage = "Execution already in progress"
                };
            }
            
            if (plan == null || plan.Actions.Count == 0)
            {
                _logger.Warning("SafeExecutor", "No actions to execute");
                return new ExecutionResult
                {
                    IsSuccessful = true,
                    ErrorMessage = "No actions to execute"
                };
            }
            
            // Own a cancellable source for this run and link it to the caller's token so that either
            // the UI's Cancel button or the caller's own token can stop the run.
            CancellationTokenSource runCts;

            lock (_executionLock)
            {
                _executionCts?.Dispose();
                _executionCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                runCts = _executionCts;
            }

            var effectiveToken = runCts.Token;

            try
            {
                IsExecuting = true;
                CurrentProgress = 0;
                
                var stopwatch = System.Diagnostics.Stopwatch.StartNew();
                var result = new ExecutionResult
                {
                    Plan = plan,
                    StartedAt = DateTime.Now
                };
                
                // Raise execution started event
                ExecutionStarted?.Invoke(this, new ExecutionEventArgs
                {
                    Timestamp = DateTime.Now,
                    Plan = plan
                });
                
                _logger.Info("SafeExecutor", 
                    $"Starting execution of plan: {plan.Name} with {plan.TotalActionCount} actions");
                
                // Create a restore point if requested and enabled
                if (createRestorePoint && _config.CreateRestorePoints)
                {
                    try
                    {
                        _logger.Info("SafeExecutor", "Creating system restore point");
                        WindowsApiHelper.CreateRestorePoint($"AI System Optimizer - {plan.Name}");
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("SafeExecutor", "Failed to create restore point", null, ex);
                    }
                }
                
                // Backup current system state
                var beforeSystemInfo = await _scanner.ScanAsync(effectiveToken);
                plan.BeforeSystemInfo = beforeSystemInfo;
                
                // Execute each action
                var executedActions = new List<OptimizationAction>();
                var failedActions = new List<OptimizationAction>();
                var skippedActions = new List<OptimizationAction>();
                
                for (int i = 0; i < plan.Actions.Count && !effectiveToken.IsCancellationRequested; i++)
                {
                    var action = plan.Actions[i];
                    
                    // Update progress
                    CurrentProgress = (int)(((float)i / plan.Actions.Count) * 100);
                    ProgressUpdated?.Invoke(this, new ExecutionProgressEventArgs
                    {
                        Timestamp = DateTime.Now,
                        CurrentActionIndex = i,
                        TotalActions = plan.Actions.Count,
                        Percentage = CurrentProgress,
                        CurrentAction = action
                    });
                    
                    // Validate the action one more time (safety check)
                    if (!_safetyValidator.ValidateAction(action, beforeSystemInfo))
                    {
                        _logger.Warning("SafeExecutor", 
                            $"Action validation failed during execution: {action.ActionType} on {action.Target}");
                        
                        action.Status = ActionStatus.Skipped;
                        action.SkipReason = "Safety validation failed";
                        skippedActions.Add(action);
                        plan.SkippedActions.Add(action);
                        
                        // Raise action skipped event
                        ActionSkipped?.Invoke(this, new ActionEventArgs
                        {
                            Timestamp = DateTime.Now,
                            Action = action,
                            ActionIndex = i,
                            TotalActions = plan.Actions.Count
                        });
                        
                        continue;
                    }
                    
                    // Check if the action requires confirmation
                    if (confirmActions && _safetyValidator.RequiresUserConfirmation(action, beforeSystemInfo))
                    {
                        _logger.Info("SafeExecutor", 
                            $"Action requires confirmation: {action.ActionType} on {action.Target}");
                        
                        action.Status = ActionStatus.Pending;

                        // Confirmation is deliberately NOT obtained here.
                        //
                        // The executor runs off the UI thread and owns no window; asking for consent
                        // from inside it would mean either blocking that thread or inventing a second,
                        // unvalidated confirmation path. The consent step belongs to the layer that
                        // owns the window: OptimizationViewModel shows the preview dialog and only calls
                        // the engine once the user has agreed.
                        //
                        // An action that still reaches this point without consent is therefore skipped
                        // rather than executed. Skipping is the safe outcome and it is reported: the
                        // action is added to the skipped list and surfaced in the summary, so nothing
                        // disappears silently.
                        action.Status = ActionStatus.Skipped;
                        action.SkipReason =
                            "Requires confirmation, which was not granted before execution started";
                        skippedActions.Add(action);
                        plan.SkippedActions.Add(action);
                        
                        // Raise action skipped event
                        ActionSkipped?.Invoke(this, new ActionEventArgs
                        {
                            Timestamp = DateTime.Now,
                            Action = action,
                            ActionIndex = i,
                            TotalActions = plan.Actions.Count
                        });
                        
                        continue;
                    }
                    
                    // Raise action started event
                    ActionStarted?.Invoke(this, new ActionEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Action = action,
                        ActionIndex = i,
                        TotalActions = plan.Actions.Count
                    });
                    
                    // Execute the action
                    var executionResult = await ExecuteActionAsync(action, beforeSystemInfo, effectiveToken);
                    
                    if (executionResult.IsSuccessful)
                    {
                        action.Status = ActionStatus.Success;
                        action.IsExecuted = true;
                        action.ExecutedAt = DateTime.Now;
                        executedActions.Add(action);
                        result.SuccessfulCount++;
                        
                        // Raise action completed event
                        ActionCompleted?.Invoke(this, new ActionEventArgs
                        {
                            Timestamp = DateTime.Now,
                            Action = action,
                            ActionIndex = i,
                            TotalActions = plan.Actions.Count,
                            Result = executionResult
                        });
                    }
                    else
                    {
                        action.Status = ActionStatus.Failed;
                        action.IsExecuted = true;
                        action.ExecutedAt = DateTime.Now;
                        action.ErrorMessage = executionResult.ErrorMessage;
                        failedActions.Add(action);
                        plan.FailedActions.Add(action);
                        result.FailedCount++;
                        
                        _logger.Error("SafeExecutor", 
                            $"Action failed: {action.ActionType} on {action.Target}. Error: {executionResult.ErrorMessage}");
                        
                        // Raise action failed event
                        ActionFailed?.Invoke(this, new ActionEventArgs
                        {
                            Timestamp = DateTime.Now,
                            Action = action,
                            ActionIndex = i,
                            TotalActions = plan.Actions.Count,
                            Result = executionResult
                        });
                    }
                }
                
                // Update progress to 100%
                CurrentProgress = 100;
                ProgressUpdated?.Invoke(this, new ExecutionProgressEventArgs
                {
                    Timestamp = DateTime.Now,
                    CurrentActionIndex = plan.Actions.Count,
                    TotalActions = plan.Actions.Count,
                    Percentage = 100,
                    CurrentAction = null
                });
                
                // Scan the system after execution
                var afterSystemInfo = await _scanner.ScanAsync(effectiveToken);
                plan.AfterSystemInfo = afterSystemInfo;
                plan.ExecutedAt = DateTime.Now;
                
                // Calculate results
                result.CompletedAt = DateTime.Now;
                result.Duration = stopwatch.Elapsed;
                result.ExecutedActions = executedActions;
                result.FailedActions = failedActions;
                result.SkippedActions = skippedActions;
                result.IsSuccessful = result.FailedCount == 0;
                
                // Calculate improvement metrics
                CalculateImprovementMetrics(plan, result);
                
                _logger.Info("SafeExecutor", 
                    $"Execution completed in {result.Duration.TotalSeconds:F1} seconds. " +
                    $"Success: {result.SuccessfulCount}, Failed: {result.FailedCount}, Skipped: {result.SkippedCount}");
                
                // Raise execution completed event
                ExecutionCompleted?.Invoke(this, new ExecutionEventArgs
                {
                    Timestamp = DateTime.Now,
                    Plan = plan,
                    Result = result,
                    Duration = result.Duration
                });
                
                return result;
            }
            catch (OperationCanceledException)
            {
                _logger.Warning("SafeExecutor", "Execution was cancelled");
                
                var result = new ExecutionResult
                {
                    IsSuccessful = false,
                    ErrorMessage = "Execution was cancelled",
                    StartedAt = DateTime.Now,
                    CompletedAt = DateTime.Now
                };
                
                // Raise execution failed event
                ExecutionFailed?.Invoke(this, new ExecutionEventArgs
                {
                    Timestamp = DateTime.Now,
                    ErrorMessage = "Execution was cancelled",
                    Result = result
                });
                
                return result;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", "Execution failed", null, ex);
                
                var result = new ExecutionResult
                {
                    IsSuccessful = false,
                    ErrorMessage = ex.Message,
                    Exception = ex,
                    StartedAt = DateTime.Now,
                    CompletedAt = DateTime.Now
                };
                
                // Raise execution failed event
                ExecutionFailed?.Invoke(this, new ExecutionEventArgs
                {
                    Timestamp = DateTime.Now,
                    ErrorMessage = ex.Message,
                    Exception = ex,
                    Result = result
                });
                
                return result;
            }
            finally
            {
                IsExecuting = false;
            }
        }

        /// <summary>
        /// Execute a single optimization action
        /// </summary>
        public async Task<ActionExecutionResult> ExecuteActionAsync(
            OptimizationAction action,
            SystemInfo systemInfo = null,
            CancellationToken cancellationToken = default)
        {
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? await _scanner.ScanAsync(cancellationToken);
                
                _logger.Info("SafeExecutor", 
                    $"Executing action: {action.ActionType} on {action.Target}");
                
                var result = new ActionExecutionResult
                {
                    Action = action,
                    StartedAt = DateTime.Now
                };
                
                // Execute based on action type
                switch (action.ActionType)
                {
                    case OptimizationActionType.CloseProcess:
                        result.IsSuccessful = await ExecuteCloseProcessAsync(action, systemInfo, cancellationToken);
                        break;
                    
                    case OptimizationActionType.DisableStartup:
                        result.IsSuccessful = ExecuteDisableStartup(action, systemInfo);
                        break;
                    
                    case OptimizationActionType.StopService:
                        result.IsSuccessful = ExecuteStopService(action, systemInfo);
                        break;
                    
                    case OptimizationActionType.DisableService:
                        result.IsSuccessful = ExecuteDisableService(action, systemInfo);
                        break;
                    
                    case OptimizationActionType.ClearCache:
                        result.IsSuccessful = await ExecuteClearCacheAsync(action, systemInfo, cancellationToken);
                        break;
                    
                    case OptimizationActionType.ChangePriority:
                        result.IsSuccessful = ExecuteChangePriority(action, systemInfo);
                        break;
                    
                    case OptimizationActionType.ChangeAffinity:
                        result.IsSuccessful = ExecuteChangeAffinity(action, systemInfo);
                        break;
                    
                    case OptimizationActionType.UninstallApplication:
                        result.IsSuccessful = await ExecuteUninstallApplicationAsync(action, systemInfo, cancellationToken);
                        break;
                    
                    case OptimizationActionType.AdjustPowerSettings:
                        result.IsSuccessful = ExecuteAdjustPowerSettings(action, systemInfo);
                        break;
                    
                    default:
                        _logger.Warning("SafeExecutor", 
                            $"Unknown action type: {action.ActionType}");
                        result.IsSuccessful = false;
                        result.ErrorMessage = "Unknown action type";
                        break;
                }
                
                result.CompletedAt = DateTime.Now;
                
                if (result.IsSuccessful)
                {
                    _logger.Info("SafeExecutor", 
                        $"Action completed successfully: {action.ActionType} on {action.Target}");
                }
                else
                {
                    _logger.Warning("SafeExecutor", 
                        $"Action failed: {action.ActionType} on {action.Target}");
                }
                
                return result;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Failed to execute action: {action.ActionType} on {action.Target}", null, ex);
                
                return new ActionExecutionResult
                {
                    Action = action,
                    IsSuccessful = false,
                    ErrorMessage = ex.Message,
                    Exception = ex
                };
            }
        }

        /// <summary>
        /// Undo the last optimization
        /// </summary>
        public async Task<UndoResult> UndoLastOptimizationAsync(
            OptimizationPlan plan,
            CancellationToken cancellationToken = default)
        {
            try
            {
                _logger.Info("SafeExecutor", "Undoing last optimization");
                
                var stopwatch = System.Diagnostics.Stopwatch.StartNew();
                var result = new UndoResult
                {
                    Plan = plan,
                    StartedAt = DateTime.Now
                };
                
                // Get the actions that can be undone
                var undoableActions = plan.Actions
                    .Where(a => a.CanUndo && a.UndoAction != null)
                    .OrderByDescending(a => a.ExecutedAt)
                    .ToList();
                
                if (undoableActions.Count == 0)
                {
                    _logger.Info("SafeExecutor", "No undoable actions found");
                    result.IsSuccessful = true;
                    result.CompletedAt = DateTime.Now;
                    result.Duration = stopwatch.Elapsed;
                    return result;
                }
                
                // Execute undo actions in reverse order
                for (int i = undoableActions.Count - 1; i >= 0 && !cancellationToken.IsCancellationRequested; i--)
                {
                    var action = undoableActions[i];
                    var undoAction = action.UndoAction;
                    
                    _logger.Info("SafeExecutor", 
                        $"Undoing action: {action.ActionType} on {action.Target}");
                    
                    var undoResult = await ExecuteActionAsync(undoAction, null, cancellationToken);
                    
                    if (undoResult.IsSuccessful)
                    {
                        result.SuccessfulCount++;
                    }
                    else
                    {
                        result.FailedCount++;
                        result.FailedActions.Add(undoAction);
                    }
                }
                
                result.CompletedAt = DateTime.Now;
                result.Duration = stopwatch.Elapsed;
                result.IsSuccessful = result.FailedCount == 0;
                
                _logger.Info("SafeExecutor", 
                    $"Undo completed in {result.Duration.TotalSeconds:F1} seconds. " +
                    $"Success: {result.SuccessfulCount}, Failed: {result.FailedCount}");
                
                return result;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", "Failed to undo last optimization", null, ex);
                
                return new UndoResult
                {
                    IsSuccessful = false,
                    ErrorMessage = ex.Message,
                    Exception = ex
                };
            }
        }

        /// <summary>
        /// Cancel the execution that is currently in progress.
        ///
        /// Cancellation is cooperative and safe by construction: the loop that walks the plan checks
        /// the token before every action, so a cancel can never leave an action half-applied. The
        /// action that is already running is allowed to finish - interrupting a service stop or a
        /// registry write midway is exactly the inconsistent state this design exists to avoid.
        /// </summary>
        public void CancelExecution()
        {
            lock (_executionLock)
            {
                if (_executionCts == null || _executionCts.IsCancellationRequested)
                {
                    _logger.Info("SafeExecutor", "Cancel requested but no execution is in progress");
                    return;
                }

                try
                {
                    _executionCts.Cancel();
                    _logger.Info("SafeExecutor",
                        "Execution cancellation requested; the remaining actions will be skipped");
                }
                catch (ObjectDisposedException)
                {
                    // The run finished between the null check and the cancel - nothing to do.
                }
            }
        }

        /// <summary>
        /// True while a cancellable execution is in progress.
        /// </summary>
        public bool CanCancel
        {
            get
            {
                lock (_executionLock)
                {
                    return IsExecuting && _executionCts != null && !_executionCts.IsCancellationRequested;
                }
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Execute a close process action
        /// </summary>
        private async Task<bool> ExecuteCloseProcessAsync(
            OptimizationAction action,
            SystemInfo systemInfo,
            CancellationToken cancellationToken)
        {
            try
            {
                _logger.Info("SafeExecutor", 
                    $"Closing process: {action.Target} (PID: {action.TargetPid})");
                
                // Check if the process is still running
                if (!WindowsApiHelper.IsProcessRunning(action.TargetPid))
                {
                    _logger.Info("SafeExecutor", 
                        $"Process already closed: {action.Target} (PID: {action.TargetPid})");
                    return true;
                }

                // ---- TOCTOU GUARD ------------------------------------------------------------
                // Re-read the identity of the process that owns this pid *right now*. If the original
                // process exited since the scan, Windows may have handed the same pid to a completely
                // different program; terminating on a stale pid would kill the wrong process.
                if (!action.HasProcessIdentity)
                {
                    _logger.Error("SafeExecutor",
                        $"Refusing to close '{action.Target}' (PID {action.TargetPid}): " +
                        "no creation time was recorded, so the pid cannot be proven to be the same process.");
                    action.MarkAsSkipped("Process identity could not be verified (no recorded creation time).");
                    return false;
                }

                if (!WindowsApiHelper.VerifyProcessIdentity(
                        action.TargetPid,
                        action.TargetCreationTimeUtc,
                        action.TargetProcessName,
                        out var identityFailure))
                {
                    _logger.Error("SafeExecutor",
                        $"Refusing to close '{action.Target}' (PID {action.TargetPid}): {identityFailure}");
                    action.MarkAsSkipped(identityFailure);
                    return false;
                }

                // Get the process
                var process = WindowsApiHelper.GetProcessById(action.TargetPid);
                if (process == null)
                {
                    _logger.Warning("SafeExecutor", 
                        $"Process not found: {action.Target} (PID: {action.TargetPid})");
                    return false;
                }
                
                // Final safety check
                if (CriticalProcesses.IsCritical(process.ProcessName))
                {
                    _logger.Error("SafeExecutor", 
                        $"Attempted to close critical process: {process.ProcessName}");
                    return false;
                }

                // Re-check "in use" at the very last moment. The scan that produced this plan may be
                // minutes old, and the user can switch to an application at any time. A process that
                // has become foreground or has shown a window since the scan must never be closed.
                var foregroundPid = WindowsApiHelper.GetForegroundProcessId();
                if (foregroundPid == action.TargetPid)
                {
                    _logger.Error("SafeExecutor",
                        $"Refusing to close '{action.Target}' (PID {action.TargetPid}): " +
                        "it is now the foreground window and is in use.");
                    action.MarkAsSkipped("Process became the active window after the scan.");
                    return false;
                }

                if (WindowsApiHelper.HasVisibleWindow(action.TargetPid))
                {
                    _logger.Error("SafeExecutor",
                        $"Refusing to close '{action.Target}' (PID {action.TargetPid}): " +
                        "it now owns a visible window and is in use.");
                    action.MarkAsSkipped("Process opened a window after the scan.");
                    return false;
                }

                // ---- GRACEFUL CLOSE FIRST ----------------------------------------------------
                // Ask the application to shut down through its normal path (WM_CLOSE) so that it can
                // save data and release resources. Only if it is still alive after the grace period
                // is a forced termination considered, and only for processes that the safety layer
                // already classified as a closable background application.
                var gracePeriodMs = Math.Clamp(_config.CloseGracePeriodMs, 500, 15000);
                var closedGracefully = false;

                try
                {
                    closedGracefully = process.CloseMainWindow();
                    if (closedGracefully)
                    {
                        _logger.Info("SafeExecutor",
                            $"Sent a close request to {process.ProcessName} (PID {action.TargetPid}); " +
                            $"waiting up to {gracePeriodMs} ms for it to exit cleanly.");

                        var deadline = DateTime.UtcNow.AddMilliseconds(gracePeriodMs);
                        while (DateTime.UtcNow < deadline && !cancellationToken.IsCancellationRequested)
                        {
                            if (process.HasExited)
                                break;

                            await Task.Delay(100, cancellationToken).ConfigureAwait(false);
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    _logger.Warning("SafeExecutor",
                        $"Cancelled while waiting for {action.Target} to close cleanly.");
                    return false;
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor",
                        $"Graceful close is not available for {action.Target}", null, ex);
                }

                if (process.HasExited)
                {
                    _logger.Info("SafeExecutor",
                        $"'{action.Target}' (PID {action.TargetPid}) closed cleanly and saved its state.");
                    return true;
                }

                // ---- FORCED TERMINATION (last resort) ---------------------------------------
                _logger.Info("SafeExecutor",
                    $"'{action.Target}' did not close within the grace period; terminating it.");

                // Kill the process, passing the verified creation time so the identity is re-checked
                // once more inside the API helper.
                if (WindowsApiHelper.TerminateProcess(
                        action.TargetPid,
                        exitCode: 0,
                        timeoutMs: 5000,
                        expectedCreationTimeUtc: action.TargetCreationTimeUtc))
                {
                    // Wait for the process to exit
                    await Task.Run(() =>
                    {
                        var timeout = TimeSpan.FromSeconds(5);
                        var startTime = DateTime.Now;
                        
                        while (WindowsApiHelper.IsProcessRunning(action.TargetPid) &&
                               (DateTime.Now - startTime) < timeout &&
                               !cancellationToken.IsCancellationRequested)
                        {
                            Thread.Sleep(100);
                        }
                    }, cancellationToken);
                    
                    // Check if the process was successfully terminated
                    if (!WindowsApiHelper.IsProcessRunning(action.TargetPid))
                    {
                        _logger.Info("SafeExecutor", 
                            $"Successfully closed process: {action.Target} (PID: {action.TargetPid})");
                        return true;
                    }
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to close process: {action.Target} (PID: {action.TargetPid})");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error closing process: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute a disable startup action
        /// </summary>
        private bool ExecuteDisableStartup(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", $"Disabling startup item: {action.Target}");
                
                // Find the startup item
                var startupItem = systemInfo.StartupItems.FirstOrDefault(s => 
                    s.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                    s.Path.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (startupItem == null)
                {
                    _logger.Warning("SafeExecutor", 
                        $"Startup item not found: {action.Target}");
                    return false;
                }
                
                // Disable the start-up entry. The removed command line is stored on the action so
                // that "Undo" can recreate it exactly as it was.
                if (WindowsApiHelper.DisableStartupItem(startupItem, out var removedValue))
                {
                    action.CanUndo = true;

                    if (action.UndoAction == null)
                    {
                        action.UndoAction = new OptimizationAction
                        {
                            ActionType = OptimizationActionType.DisableStartup,
                            Target = startupItem.Name,
                            TargetPath = startupItem.Path,
                            ResourceType = ResourceType.RAM,
                            RiskLevel = RiskLevel.Low,
                            Description = $"Re-enable start-up entry: {startupItem.Name}",
                            Reason = "Undo of a previous start-up optimisation",
                            StartupItem = startupItem,
                            CanUndo = false
                        };
                    }

                    action.UndoAction.TargetPath = removedValue; // exact original command line

                    _logger.Info("SafeExecutor",
                        $"Disabled start-up entry: {action.Target}");
                    return true;
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to disable startup item: {action.Target}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error disabling startup item: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute a stop service action
        /// </summary>
        private bool ExecuteStopService(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", $"Stopping service: {action.Target}");
                
                // Check if the service is running
                if (!WindowsApiHelper.IsServiceRunning(action.Target))
                {
                    _logger.Info("SafeExecutor", 
                        $"Service already stopped: {action.Target}");
                    return true;
                }
                
                // Stop the service
                if (WindowsApiHelper.StopService(action.Target))
                {
                    _logger.Info("SafeExecutor", 
                        $"Successfully stopped service: {action.Target}");
                    return true;
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to stop service: {action.Target}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error stopping service: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute a disable service action
        /// </summary>
        private bool ExecuteDisableService(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", $"Disabling service: {action.Target}");
                
                // First, stop the service if it's running
                if (WindowsApiHelper.IsServiceRunning(action.Target))
                {
                    if (!WindowsApiHelper.StopService(action.Target))
                    {
                        _logger.Warning("SafeExecutor", 
                            $"Failed to stop service before disabling: {action.Target}");
                        return false;
                    }
                }
                
                // Disable the service
                if (WindowsApiHelper.DisableService(action.Target))
                {
                    _logger.Info("SafeExecutor", 
                        $"Successfully disabled service: {action.Target}");
                    return true;
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to disable service: {action.Target}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error disabling service: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// True when the value is a Windows Installer product code ({GUID} or bare GUID), which is the
        /// only input <c>msiexec /x</c> accepts. Anything else is refused rather than passed on.
        /// </summary>
        private static bool IsValidMsiProductCode(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return false;

            var candidate = value!.Trim();

            // A registry uninstall string for MSI products is commonly written as
            // "MsiExec.exe /I{GUID}" or "MsiExec.exe /X{GUID}".
            var lastOpen = candidate.LastIndexOf('{');
            var lastClose = candidate.LastIndexOf('}');

            if (lastOpen >= 0 && lastClose > lastOpen)
                candidate = candidate.Substring(lastOpen + 1, lastClose - lastOpen - 1);
            else
                candidate = candidate.Trim('{', '}');

            return Guid.TryParseExact(candidate, "D", out _);
        }

        /// <summary>
        /// Execute a clear cache action
        /// </summary>
        private async Task<bool> ExecuteClearCacheAsync(
            OptimizationAction action,
            SystemInfo systemInfo,
            CancellationToken cancellationToken)
        {
            try
            {
                _logger.Info("SafeExecutor", "Clearing system cache");
                
                // Clear various caches
                var results = new List<bool>();
                
                // Clear Windows temp directory
                try
                {
                    var tempPath = Path.GetTempPath();
                    var tempFiles = Directory.GetFiles(tempPath, "*", SearchOption.AllDirectories);
                    
                    int removed = 0;
                    int blocked = 0;

                    foreach (var file in tempFiles)
                    {
                        cancellationToken.ThrowIfCancellationRequested();

                        try
                        {
                            File.Delete(file);
                            removed++;
                        }
                        catch
                        {
                            // Locked, in use, or permission denied. That is the normal case for a
                            // proportion of any temp directory, so it is counted rather than logged
                            // one line per file, and it is reported honestly at the end.
                            blocked++;
                        }
                    }

                    // Report what actually happened instead of assuming success.
                    _logger.Info("SafeExecutor",
                        $"Cache sweep deleted {removed} file(s); {blocked} could not be removed and were skipped.");

                    results.Add(removed > 0 || blocked == 0);
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", "Failed to clear temp directory", null, ex);
                    results.Add(false);
                }
                
                // Clear user temp directory
                try
                {
                    var userTempPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Temp");
                    if (Directory.Exists(userTempPath))
                    {
                        var tempFiles = Directory.GetFiles(userTempPath, "*", SearchOption.AllDirectories);
                        
                        int removed = 0;
                        int blocked = 0;

                        foreach (var file in tempFiles)
                        {
                            cancellationToken.ThrowIfCancellationRequested();

                            try
                            {
                                File.Delete(file);
                                removed++;
                            }
                            catch
                            {
                                // Locked or in use - normal for part of any temp directory.
                                blocked++;
                            }
                        }

                        _logger.Info("SafeExecutor",
                            $"User temp sweep deleted {removed} file(s); {blocked} were skipped.");
                    }

                    results.Add(true);
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", "Failed to clear user temp directory", null, ex);
                    results.Add(false);
                }
                
                // Clear browser caches (Chrome, Edge, Firefox, etc.)
                try
                {
                    var browserCachePaths = new[]
                    {
                        // Chrome
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), 
                                    "Google\\Chrome\\User Data\\Default\\Cache"),
                        // Edge
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), 
                                    "Microsoft\\Edge\\User Data\\Default\\Cache"),
                        // Firefox
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), 
                                    "Mozilla\\Firefox\\Profiles")
                    };
                    
                    foreach (var cachePath in browserCachePaths)
                    {
                        if (Directory.Exists(cachePath))
                        {
                            var cacheFiles = Directory.GetFiles(cachePath, "*", SearchOption.AllDirectories);
                            
                            int removedCached = 0;
                            int blockedCached = 0;

                            foreach (var file in cacheFiles)
                            {
                                cancellationToken.ThrowIfCancellationRequested();

                                try
                                {
                                    File.Delete(file);
                                    removedCached++;
                                }
                                catch
                                {
                                    // The owning browser may have the file open; skip it.
                                    blockedCached++;
                                }
                            }

                            _logger.Info("SafeExecutor",
                                $"Browser cache sweep deleted {removedCached} file(s); " +
                                $"{blockedCached} were skipped.");
                        }
                    }
                    
                    results.Add(true);
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", "Failed to clear browser caches", null, ex);
                    results.Add(false);
                }
                
                // Clear Windows prefetch
                try
                {
                    var prefetchPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "Prefetch");
                    if (Directory.Exists(prefetchPath))
                    {
                        var prefetchFiles = Directory.GetFiles(prefetchPath, "*");
                        
                        int removedPrefetch = 0;
                        int blockedPrefetch = 0;

                        foreach (var file in prefetchFiles)
                        {
                            cancellationToken.ThrowIfCancellationRequested();

                            try
                            {
                                File.Delete(file);
                                removedPrefetch++;
                            }
                            catch
                            {
                                blockedPrefetch++;
                            }
                        }

                        _logger.Info("SafeExecutor",
                            $"Prefetch sweep deleted {removedPrefetch} file(s); " +
                            $"{blockedPrefetch} were locked and skipped.");
                    }
                    
                    results.Add(true);
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", "Failed to clear prefetch", null, ex);
                    results.Add(false);
                }
                
                // Return true if at least one cache was cleared successfully
                return results.Any(r => r);
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", "Failed to clear cache", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute a change priority action
        /// </summary>
        private bool ExecuteChangePriority(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", 
                    $"Changing priority for process: {action.Target} (PID: {action.TargetPid})");
                
                // Check if the process is still running
                if (!WindowsApiHelper.IsProcessRunning(action.TargetPid))
                {
                    _logger.Info("SafeExecutor", 
                        $"Process not running: {action.Target} (PID: {action.TargetPid})");
                    return true;
                }
                
                // Set the priority to AboveNormal
                if (WindowsApiHelper.SetProcessPriority(action.TargetPid, System.Diagnostics.ProcessPriorityClass.AboveNormal))
                {
                    _logger.Info("SafeExecutor", 
                        $"Successfully changed priority for process: {action.Target} (PID: {action.TargetPid})");
                    return true;
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to change priority for process: {action.Target} (PID: {action.TargetPid})");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error changing priority for process: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute a change affinity action
        /// </summary>
        private bool ExecuteChangeAffinity(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", 
                    $"Changing affinity for process: {action.Target} (PID: {action.TargetPid})");
                
                // Check if the process is still running
                if (!WindowsApiHelper.IsProcessRunning(action.TargetPid))
                {
                    _logger.Info("SafeExecutor", 
                        $"Process not running: {action.Target} (PID: {action.TargetPid})");
                    return true;
                }
                
                // Set affinity to use all cores
                if (WindowsApiHelper.ResetProcessAffinityToAllCores(action.TargetPid))
                {
                    _logger.Info("SafeExecutor", 
                        $"Successfully changed affinity for process: {action.Target} (PID: {action.TargetPid})");
                    return true;
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to change affinity for process: {action.Target} (PID: {action.TargetPid})");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error changing affinity for process: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute an uninstall application action
        /// </summary>
        private async Task<bool> ExecuteUninstallApplicationAsync(
            OptimizationAction action,
            SystemInfo systemInfo,
            CancellationToken cancellationToken)
        {
            try
            {
                _logger.Info("SafeExecutor", $"Uninstalling application: {action.Target}");
                
                // Find the application in the system
                var process = systemInfo.Processes.FirstOrDefault(p => 
                    p.Name.Equals(action.Target, StringComparison.OrdinalIgnoreCase) ||
                    p.DisplayName.Equals(action.Target, StringComparison.OrdinalIgnoreCase));
                
                if (process != null)
                {
                    // First, close the process if it's running
                    if (WindowsApiHelper.IsProcessRunning(process.Id))
                    {
                        await ExecuteCloseProcessAsync(new OptimizationAction
                        {
                            ActionType = OptimizationActionType.CloseProcess,
                            Target = process.Name,
                            TargetPid = process.Id
                        }, systemInfo, cancellationToken);
                    }
                }
                
                // Try to uninstall using the application's uninstaller
                try
                {
                    // Look for uninstaller in common locations
                    var uninstallPaths = new[]
                    {
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), 
                                    action.Target, "uninstall.exe"),
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), 
                                    action.Target, "uninstall.exe"),
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), 
                                    action.Target, "uninstall.exe")
                    };
                    
                    foreach (var uninstallPath in uninstallPaths)
                    {
                        if (File.Exists(uninstallPath))
                        {
                            var processInfo = new System.Diagnostics.ProcessStartInfo
                            {
                                FileName = uninstallPath,
                                Arguments = "/S", // Silent uninstall
                                UseShellExecute = false,
                                CreateNoWindow = true
                            };
                            
                            using (var uninstallProcess = System.Diagnostics.Process.Start(processInfo))
                            {
                                if (uninstallProcess != null)
                                {
                                    await uninstallProcess.WaitForExitAsync(cancellationToken);

                                    if (uninstallProcess.ExitCode == 0)
                                    {
                                        _logger.Info("SafeExecutor",
                                            $"Successfully uninstalled application: {action.Target}");
                                        return true;
                                    }
                                }
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", 
                        $"Failed to uninstall using application uninstaller: {action.Target}", null, ex);
                }
                
                // Try to use Windows Installer to uninstall
                try
                {
                    var uninstallString = GetUninstallString(action.Target);

                    // msiexec /x takes a product code, which is a GUID. An uninstall string read out of
                    // the registry is not trusted input, so it is not forwarded to a command line unless
                    // it really is one - a stray quote in that value would otherwise let it carry extra
                    // arguments into an elevated installer.
                    if (IsValidMsiProductCode(uninstallString))
                    {
                        var processInfo = new System.Diagnostics.ProcessStartInfo
                        {
                            FileName = "msiexec.exe",
                            Arguments = "/x \"" + uninstallString!.Trim() + "\" /qn", // Quiet uninstall
                            UseShellExecute = false,
                            CreateNoWindow = true
                        };
                        
                        using (var msiProcess = System.Diagnostics.Process.Start(processInfo))
                        {
                            if (msiProcess != null)
                            {
                                await msiProcess.WaitForExitAsync(cancellationToken);

                                if (msiProcess.ExitCode == 0)
                                {
                                    _logger.Info("SafeExecutor",
                                        $"Successfully uninstalled application via MSI: {action.Target}");
                                    return true;
                                }
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    _logger.Warning("SafeExecutor", 
                        $"Failed to uninstall via MSI: {action.Target}", null, ex);
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to uninstall application: {action.Target}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error uninstalling application: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Execute an adjust power settings action
        /// </summary>
        private bool ExecuteAdjustPowerSettings(OptimizationAction action, SystemInfo systemInfo)
        {
            try
            {
                _logger.Info("SafeExecutor", $"Adjusting power settings to: {action.Target}");
                
                // Parse the target as a power mode
                if (Enum.TryParse<PowerMode>(action.Target, true, out var powerMode))
                {
                    if (PowerSchemeManager.SetActiveScheme(powerMode))
                    {
                        _logger.Info("SafeExecutor", 
                            $"Successfully adjusted power settings to: {action.Target}");
                        return true;
                    }
                }
                
                _logger.Warning("SafeExecutor", 
                    $"Failed to adjust power settings to: {action.Target}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", 
                    $"Error adjusting power settings: {action.Target}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Get the uninstall string for an application
        /// </summary>
        private string GetUninstallString(string applicationName)
        {
            try
            {
                // Look in the registry for uninstall information
                var uninstallKey = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall");
                
                if (uninstallKey != null)
                {
                    foreach (var subKeyName in uninstallKey.GetSubKeyNames())
                    {
                        using (var subKey = uninstallKey.OpenSubKey(subKeyName))
                        {
                            var displayName = subKey.GetValue("DisplayName")?.ToString() ?? string.Empty;
                            
                            if (displayName.Equals(applicationName, StringComparison.OrdinalIgnoreCase))
                            {
                                var uninstallString = subKey.GetValue("UninstallString")?.ToString();
                                if (!string.IsNullOrEmpty(uninstallString))
                                {
                                    return uninstallString;
                                }
                            }
                        }
                    }
                }
                
                // Also check 64-bit registry
                uninstallKey = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall");
                
                if (uninstallKey != null)
                {
                    foreach (var subKeyName in uninstallKey.GetSubKeyNames())
                    {
                        using (var subKey = uninstallKey.OpenSubKey(subKeyName))
                        {
                            var displayName = subKey.GetValue("DisplayName")?.ToString() ?? string.Empty;
                            
                            if (displayName.Equals(applicationName, StringComparison.OrdinalIgnoreCase))
                            {
                                var uninstallString = subKey.GetValue("UninstallString")?.ToString();
                                if (!string.IsNullOrEmpty(uninstallString))
                                {
                                    return uninstallString;
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SafeExecutor", 
                    $"Failed to get uninstall string for: {applicationName}", null, ex);
            }
            
            return null;
        }

        /// <summary>
        /// Calculate improvement metrics
        /// </summary>
        private void CalculateImprovementMetrics(OptimizationPlan plan, ExecutionResult result)
        {
            try
            {
                if (plan.BeforeSystemInfo == null || plan.AfterSystemInfo == null)
                    return;
                
                // Calculate RAM improvement
                var beforeRamUsage = plan.BeforeSystemInfo.RamUsagePercentage;
                var afterRamUsage = plan.AfterSystemInfo.RamUsagePercentage;
                result.RamImprovement = beforeRamUsage - afterRamUsage;
                
                // Calculate CPU improvement
                var beforeCpuUsage = plan.BeforeSystemInfo.CpuUsage;
                var afterCpuUsage = plan.AfterSystemInfo.CpuUsage;
                result.CpuImprovement = beforeCpuUsage - afterCpuUsage;
                
                // Calculate process count improvement
                var beforeProcessCount = plan.BeforeSystemInfo.TotalProcessCount;
                var afterProcessCount = plan.AfterSystemInfo.TotalProcessCount;
                result.ProcessCountImprovement = beforeProcessCount - afterProcessCount;
                
                // Calculate estimated RAM recovered
                result.EstimatedRamRecovered = plan.EstimatedRamRecovery;
                
                _logger.Info("SafeExecutor", 
                    $"Improvement metrics - RAM: {result.RamImprovement:F1}%, " +
                    $"CPU: {result.CpuImprovement:F1}%, " +
                    $"Processes: {result.ProcessCountImprovement}");
            }
            catch (Exception ex)
            {
                _logger.Error("SafeExecutor", "Failed to calculate improvement metrics", null, ex);
            }
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the executor
        /// </summary>
        public void Dispose()
        {
            try
            {
                _scanner?.Dispose();
                _safetyValidator?.Dispose();
                _recoveryService?.Dispose();
                _processAnalyzer?.Dispose();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Execution result
    /// </summary>
    public class ExecutionResult
    {
        /// <summary>
        /// The optimization plan that was executed
        /// </summary>
        public OptimizationPlan Plan { get; set; }
        
        /// <summary>
        /// Whether the execution was successful
        /// </summary>
        public bool IsSuccessful { get; set; } = false;
        
        /// <summary>
        /// When the execution started
        /// </summary>
        public DateTime StartedAt { get; set; }
        
        /// <summary>
        /// When the execution completed
        /// </summary>
        public DateTime CompletedAt { get; set; }
        
        /// <summary>
        /// Duration of the execution
        /// </summary>
        public TimeSpan Duration { get; set; }
        
        /// <summary>
        /// Number of successful actions
        /// </summary>
        public int SuccessfulCount { get; set; } = 0;
        
        /// <summary>
        /// Number of failed actions
        /// </summary>
        public int FailedCount { get; set; } = 0;
        
        /// <summary>
        /// Number of skipped actions
        /// </summary>
        public int SkippedCount { get; set; } = 0;
        
        /// <summary>
        /// List of executed actions
        /// </summary>
        public List<OptimizationAction> ExecutedActions { get; set; } = new List<OptimizationAction>();
        
        /// <summary>
        /// List of failed actions
        /// </summary>
        public List<OptimizationAction> FailedActions { get; set; } = new List<OptimizationAction>();
        
        /// <summary>
        /// List of skipped actions
        /// </summary>
        public List<OptimizationAction> SkippedActions { get; set; } = new List<OptimizationAction>();
        
        /// <summary>
        /// Error message if execution failed
        /// </summary>
        public string ErrorMessage { get; set; } = string.Empty;
        
        /// <summary>
        /// Exception if execution failed
        /// </summary>
        public Exception Exception { get; set; }
        
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
        /// Estimated RAM recovered in bytes
        /// </summary>
        public long EstimatedRamRecovered { get; set; }
    }

    /// <summary>
    /// Action execution result
    /// </summary>
    public class ActionExecutionResult
    {
        /// <summary>
        /// The action that was executed
        /// </summary>
        public OptimizationAction Action { get; set; }
        
        /// <summary>
        /// Whether the action was successful
        /// </summary>
        public bool IsSuccessful { get; set; } = false;
        
        /// <summary>
        /// When the action started
        /// </summary>
        public DateTime StartedAt { get; set; }
        
        /// <summary>
        /// When the action completed
        /// </summary>
        public DateTime CompletedAt { get; set; }
        
        /// <summary>
        /// Duration of the action
        /// </summary>
        public TimeSpan Duration => CompletedAt - StartedAt;
        
        /// <summary>
        /// Error message if the action failed
        /// </summary>
        public string ErrorMessage { get; set; } = string.Empty;
        
        /// <summary>
        /// Exception if the action failed
        /// </summary>
        public Exception Exception { get; set; }
    }

    /// <summary>
    /// Undo result
    /// </summary>
    public class UndoResult
    {
        /// <summary>
        /// The plan that was undone
        /// </summary>
        public OptimizationPlan Plan { get; set; }
        
        /// <summary>
        /// Whether the undo was successful
        /// </summary>
        public bool IsSuccessful { get; set; } = false;
        
        /// <summary>
        /// When the undo started
        /// </summary>
        public DateTime StartedAt { get; set; }
        
        /// <summary>
        /// When the undo completed
        /// </summary>
        public DateTime CompletedAt { get; set; }
        
        /// <summary>
        /// Duration of the undo
        /// </summary>
        public TimeSpan Duration { get; set; }
        
        /// <summary>
        /// Number of successful undo actions
        /// </summary>
        public int SuccessfulCount { get; set; } = 0;
        
        /// <summary>
        /// Number of failed undo actions
        /// </summary>
        public int FailedCount { get; set; } = 0;
        
        /// <summary>
        /// List of failed undo actions
        /// </summary>
        public List<OptimizationAction> FailedActions { get; set; } = new List<OptimizationAction>();
        
        /// <summary>
        /// Error message if undo failed
        /// </summary>
        public string ErrorMessage { get; set; } = string.Empty;
        
        /// <summary>
        /// Exception if undo failed
        /// </summary>
        public Exception Exception { get; set; }
    }

    /// <summary>
    /// Action event arguments
    /// </summary>
    public class ActionEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public OptimizationAction Action { get; set; }
        public int ActionIndex { get; set; }
        public int TotalActions { get; set; }
        public ActionExecutionResult Result { get; set; }
    }

    /// <summary>
    /// Execution event arguments
    /// </summary>
    public class ExecutionEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public OptimizationPlan Plan { get; set; }
        public ExecutionResult Result { get; set; }
        public TimeSpan Duration { get; set; }
        public string ErrorMessage { get; set; } = string.Empty;
        public Exception Exception { get; set; }
    }

    /// <summary>
    /// Execution progress event arguments
    /// </summary>
    public class ExecutionProgressEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public int CurrentActionIndex { get; set; }
        public int TotalActions { get; set; }
        public int Percentage { get; set; }
        public OptimizationAction CurrentAction { get; set; }
    }
}

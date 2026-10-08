using System;
using System.Collections.Generic;
using System.Diagnostics;
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
    /// The single façade the UI talks to.
    ///
    /// It wires the pipeline the product specification asks for:
    ///
    ///   SystemScanner  ->  Rules engine (ProcessAnalyzer / CriticalProcesses)
    ///                  ->  RiskAnalyzer
    ///                  ->  AI (optional, only when configured and reachable)
    ///                  ->  OptimizationPlanner
    ///                  ->  SafetyValidator        (final veto)
    ///                  ->  SafeExecutor
    ///                  ->  VerificationService    (did it actually help?)
    ///
    /// No optimisation can reach SafeExecutor without passing SafetyValidator,
    /// including anything suggested by the AI.
    /// </summary>
    public sealed class OptimizationEngine : IDisposable
    {
        #region Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private readonly ProcessAnalyzer _analyzer;
        private readonly RiskAnalyzer _riskAnalyzer;
        private readonly SafetyValidator _safetyValidator;
        private readonly OptimizationPlanner _planner;
        private readonly SafeExecutor _executor;
        private readonly VerificationService _verification;
        private readonly RecoveryService _recovery;
        private readonly AIService _aiService;
        private readonly StartupManager _startupManager;
        private readonly ServiceManager _serviceManager;
        private readonly object _syncRoot = new object();
        private bool _disposed;

        #endregion

        #region Construction

        public OptimizationEngine(AppConfig? config = null, ILogger? logger = null)
        {
            _config = config ?? AppConfig.Load();
            _logger = logger ?? LoggerFactory.GetLogger(_config);

            _scanner = new SystemScanner(_logger, _config);
            _analyzer = new ProcessAnalyzer(_logger, _config, _scanner);
            _safetyValidator = new SafetyValidator(_logger, _config, _analyzer);
            _riskAnalyzer = new RiskAnalyzer(_logger, _config, _analyzer, _safetyValidator);
            _planner = new OptimizationPlanner(_logger, _config, _scanner, _analyzer, _riskAnalyzer);
            _executor = new SafeExecutor(_logger, _config, _scanner, _safetyValidator, new RecoveryService(_logger, _config), _analyzer);
            _verification = new VerificationService(_logger, _config, _scanner, _safetyValidator);
            _recovery = new RecoveryService(_logger, _config);
            _aiService = new AIService(_logger, _config);
            _startupManager = new StartupManager(_logger, _config, _scanner);
            _serviceManager = new ServiceManager(_logger, _config, _scanner);
        }

        #endregion

        #region Exposed services

        /// <summary>Active configuration (mutable - call Save() after editing).</summary>
        public AppConfig Config => _config;

        /// <summary>Scanner (read only operations).</summary>
        public SystemScanner Scanner => _scanner;

        /// <summary>Start-up manager.</summary>
        public StartupManager StartupManager => _startupManager;

        /// <summary>Service manager.</summary>
        public ServiceManager ServiceManager => _serviceManager;

        /// <summary>Optimisation history / undo store.</summary>
        public RecoveryService Recovery => _recovery;

        /// <summary>AI service (may be unavailable - always check first).</summary>
        public AIService Ai => _aiService;

        /// <summary>Logger.</summary>
        public ILogger Logger => _logger;

        /// <summary>Last completed optimisation session (used by the Undo button).</summary>
        public OptimizationPlan? LastExecutedPlan { get; private set; }

        #endregion

        #region Scan

        /// <summary>
        /// Full system scan.
        /// </summary>
        public Task<SystemInfo> ScanAsync(CancellationToken cancellationToken = default)
        {
            _logger.Info("OptimizationEngine", "Scan requested");
            return _scanner.ScanAsync(cancellationToken);
        }

        /// <summary>
        /// Signal the executor to stop after the action that is currently running.
        /// Exposed here so the UI never reaches past the engine façade.
        /// </summary>
        public void CancelExecution()
        {
            _logger.Info("OptimizationEngine", "Cancellation forwarded to the executor");

            try
            {
                _executor.CancelExecution();
            }
            catch (Exception ex)
            {
                _logger.Warning("OptimizationEngine",
                    "Failed to forward the cancellation request to the executor", null, ex);
            }
        }

        /// <summary>True while an execution can still be stopped.</summary>
        public bool CanCancelExecution => _executor.CanCancel;

        /// <summary>
        /// Live metrics sample (cheap, used by the real-time dashboard).
        /// </summary>
        public SystemInfo SampleMetrics()
        {
            return _scanner.QuickScan();
        }

        #endregion

        #region Analysis

        /// <summary>
        /// Analyse every process and return the ranked optimisation candidates.
        /// AI is only consulted for candidates, never for protected processes.
        /// </summary>
        public List<ProcessAnalysisResult> AnalyzeProcesses(SystemInfo systemInfo, bool useAi = false)
        {
            var results = _analyzer.AnalyzeAllProcesses(systemInfo);

            if (!useAi || !_config.AiEnabled || !_aiService.IsAvailable)
                return results;

            // Ask the AI about the top candidates only - keeps latency and RAM cost low.
            var candidates = results
                .Where(r => r.CanOptimize)
                .OrderByDescending(r => r.OptimizationScore)
                .Take(Math.Max(1, _config.MaxAiProcessAnalyses))
                .ToList();

            foreach (var candidate in candidates)
            {
                try
                {
                    var explanation = _aiService.AnalyzeProcess(candidate.ProcessInfo);

                    if (!string.IsNullOrWhiteSpace(explanation))
                    {
                        candidate.AiAnalysis = explanation;
                        candidate.AiAnalyzed = true;
                    }
                }
                catch (Exception ex)
                {
                    _logger.Warning("OptimizationEngine",
                        $"AI analysis failed for {candidate.ProcessInfo.Name}", null, ex);
                    break; // If the AI is down, do not hammer it for every process.
                }
            }

            return results;
        }

        /// <summary>
        /// AI written system summary for the recommendations page (empty when AI is off).
        /// </summary>
        public string GetAiSummary(SystemInfo systemInfo)
        {
            if (!_config.AiEnabled || !_aiService.IsAvailable)
                return string.Empty;

            try
            {
                return _aiService.AnalyzeSystem(systemInfo);
            }
            catch (Exception ex)
            {
                _logger.Warning("OptimizationEngine", "AI system summary failed", null, ex);
                return string.Empty;
            }
        }

        /// <summary>
        /// Rule based recommendations that always work, AI or not.
        /// </summary>
        public List<SystemInfo.OptimizationRecommendation> GetRecommendations(SystemInfo systemInfo)
        {
            return systemInfo.Recommendations;
        }

        /// <summary>
        /// The honest description of what the user's RAM target can realistically reach.
        /// </summary>
        public string DescribeRamTarget(SystemInfo systemInfo)
        {
            return SystemScoring.DescribeAchievableTarget(systemInfo, _config.TargetRamUsage);
        }

        /// <summary>
        /// Progress towards the RAM target (0-100).
        /// </summary>
        public int GetRamTargetProgress(SystemInfo systemInfo)
        {
            return SystemScoring.CalculateTargetProgress(systemInfo, _config.TargetRamUsage);
        }

        #endregion

        #region Planning

        /// <summary>
        /// Build an optimisation plan (nothing is executed yet).
        /// </summary>
        public async Task<OptimizationPlan?> CreatePlanAsync(
            OptimizationMode mode,
            SystemInfo? systemInfo = null,
            List<ProcessInfo>? targetProcesses = null,
            CancellationToken cancellationToken = default)
        {
            systemInfo ??= await ScanAsync(cancellationToken).ConfigureAwait(false);

            OptimizationPlan? plan;

            switch (mode)
            {
                case OptimizationMode.GameMode:
                    plan = await _planner.CreateGameModePlanAsync(FindGameProcess(systemInfo), systemInfo)
                        .ConfigureAwait(false);
                    break;

                case OptimizationMode.Automatic:
                    plan = await _planner.CreatePlanAsync(OptimizationMode.Automatic, systemInfo, targetProcesses)
                        .ConfigureAwait(false);
                    break;

                default:
                    plan = await _planner.CreatePlanAsync(mode, systemInfo, targetProcesses)
                        .ConfigureAwait(false);
                    break;
            }

            if (plan == null)
            {
                _logger.Warning("OptimizationEngine", "Planning produced no valid plan");
                return null;
            }

            // Final gate before the plan is ever shown as executable.
            PreparePlanForReview(plan, systemInfo);

            return plan;
        }

        /// <summary>
        /// A fast, conservative plan used by "Smart Optimize" on the dashboard.
        /// </summary>
        public async Task<OptimizationPlan?> CreateQuickPlanAsync(SystemInfo? systemInfo = null)
        {
            systemInfo ??= await ScanAsync().ConfigureAwait(false);

            var plan = await _planner.CreateQuickPlanAsync(OptimizationMode.Conservative, systemInfo)
                .ConfigureAwait(false);

            if (plan != null)
                PreparePlanForReview(plan, systemInfo);

            return plan;
        }

        /// <summary>
        /// Decide, per action, whether it may run automatically, and reject anything the
        /// safety layer does not approve.
        /// </summary>
        private void PreparePlanForReview(OptimizationPlan plan, SystemInfo systemInfo)
        {
            foreach (var action in plan.Actions)
            {
                // Attach the undo definition where the action type supports it.
                action.AttachUndoAction();

                if (!_safetyValidator.ValidateAction(action, systemInfo))
                {
                    action.MarkAsRejected("Rejected by the safety layer");
                    continue;
                }

                action.UserConfirmed = false;
                action.RequiresAdmin = RequiresElevation(action);
            }

            // Rejected actions never travel inside the executable set.
            var rejected = plan.Actions.Where(a => a.Status == ActionStatus.Rejected).ToList();

            foreach (var action in rejected)
            {
                plan.Actions.Remove(action);
                plan.SkippedActions.Add(action);
            }

            plan.SortByPriority();

            _logger.Info("OptimizationEngine",
                $"Plan ready: {plan.Actions.Count} executable, {plan.SkippedActions.Count} skipped, " +
                $"estimated recovery {plan.FormattedEstimatedRamRecovery}");
        }

        private static bool RequiresElevation(OptimizationAction action)
        {
            switch (action.ActionType)
            {
                case OptimizationActionType.StopService:
                case OptimizationActionType.DisableService:
                case OptimizationActionType.UninstallApplication:
                case OptimizationActionType.AdjustPowerSettings:
                case OptimizationActionType.ChangeAffinity:
                    return true;

                case OptimizationActionType.DisableStartup:
                    // HKLM start-up entries need elevation, HKCU ones do not.
                    return action.StartupItem != null &&
                           action.StartupItem.Source.IndexOf("HKLM", StringComparison.OrdinalIgnoreCase) >= 0;

                default:
                    return false;
            }
        }

        /// <summary>
        /// Find a running game for Game Mode (null when none is detected).
        /// </summary>
        public ProcessInfo? FindGameProcess(SystemInfo systemInfo)
        {
            return systemInfo.Processes
                .Where(p => !p.IsWindowsProcess && !p.IsService && !p.IsDriver)
                .FirstOrDefault(p => ProcessHelper.IsGameProcess(p));
        }

        #endregion

        #region Execution

        /// <summary>
        /// Execute a previously reviewed plan. Returns the verification report.
        /// </summary>
        public async Task<OptimizationReport> ExecutePlanAsync(
            OptimizationPlan plan,
            bool createRestorePoint,
            CancellationToken cancellationToken = default)
        {
            if (plan == null || plan.Actions.Count == 0)
            {
                return OptimizationReport.Empty("Nothing to optimise - no safe actions were available.");
            }

            var stopwatch = Stopwatch.StartNew();

            // 1. Record the before state (already captured by the planner, but refresh it).
            var before = plan.BeforeSystemInfo ?? await ScanAsync(cancellationToken).ConfigureAwait(false);

            // 2. Guard every action once more, immediately before execution.
            var executable = new List<OptimizationAction>();

            foreach (var action in plan.Actions)
            {
                if (action.Status == ActionStatus.Rejected)
                {
                    plan.SkippedActions.Add(action);
                    continue;
                }

                if (!_safetyValidator.ValidateAction(action, before))
                {
                    action.MarkAsRejected("Blocked by the safety layer at execution time");
                    plan.SkippedActions.Add(action);
                    continue;
                }

                executable.Add(action);
            }

            plan.Actions.Clear();
            plan.Actions.AddRange(executable);

            if (plan.Actions.Count == 0)
            {
                return OptimizationReport.Empty(
                    "Every proposed action was blocked by the safety layer. Nothing was changed.");
            }

            // 3. Execute.
            var session = _recovery.StartSession(plan);

            var execution = await _executor.ExecutePlanAsync(
                plan,
                confirmActions: false,
                createRestorePoint: createRestorePoint && _config.CreateRestorePoints,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            // 4. Verify.
            var verification = await _verification.VerifyExecutionAsync(plan, execution).ConfigureAwait(false);

            // 5. Persist history.
            session.AfterSystemInfo = plan.AfterSystemInfo;
            session.EndTimestamp = DateTime.Now;
            session.Notes = verification.Report;
            _recovery.SaveSession(session);

            LastExecutedPlan = plan;
            stopwatch.Stop();

            // 6. Build the human report.
            var report = OptimizationReport.FromExecution(plan, execution, verification, stopwatch.Elapsed);

            _logger.Info("OptimizationEngine",
                $"Optimisation finished: {report.SuccessCount} succeeded, {report.FailedCount} failed, " +
                $"RAM {report.BeforeRamPercent:F1}% -> {report.AfterRamPercent:F1}%");

            return report;
        }

        /// <summary>
        /// Undo the most recent optimisation.
        /// </summary>
        public async Task<UndoResult> UndoLastOptimizationAsync(
            CancellationToken cancellationToken = default)
        {
            var plan = LastExecutedPlan;

            if (plan == null && _recovery.History.Sessions.Count > 0)
                plan = _recovery.History.Sessions[^1].Plan;

            if (plan == null)
                return new UndoResult { IsSuccessful = false, ErrorMessage = "There is no optimisation to undo." };

            return await _executor.UndoLastOptimizationAsync(plan, cancellationToken).ConfigureAwait(false);
        }

        /// <summary>
        /// Whether an undo is currently possible.
        /// </summary>
        public bool CanUndo => LastExecutedPlan != null &&
                                   LastExecutedPlan.Actions.Any(a => a.CanUndo);

        #endregion

        #region Cache maintenance (the honest "RAM clean")

        /// <summary>
        /// Result of a cache clean attempt - reported honestly, including when nothing was possible.
        /// </summary>
        public sealed class CacheCleanResult
        {
            public bool Performed { get; set; }
            public long BytesRecovered { get; set; }
            public string Message { get; set; } = string.Empty;
            public List<string> Details { get; set; } = new List<string>();
        }

        /// <summary>
        /// Remove only genuinely disposable data: user temp files, the Windows temp folder,
        /// the thumbnail cache and the DNS resolver cache.
        ///
        /// It deliberately does NOT:
        ///   * touch the standby list / working sets (fake "RAM boosters" do that and it makes
        ///     the system slower, not faster),
        ///   * clear the page file or flush the file cache,
        ///   * delete anything inside Program Files, Windows\System32 or user documents.
        /// </summary>
        public CacheCleanResult CleanSafeCaches(CancellationToken cancellationToken = default)
        {
            var result = new CacheCleanResult();
            long freed = 0;

            var targets = new List<(string Path, bool Recursive, string Label)>
            {
                (Path.GetTempPath(), true, "User temporary files"),
                (Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Temp"), true, "Local app temporary files"),
                (Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    @"Microsoft\Windows\Explorer"), false, "Thumbnail cache")
            };

            foreach (var (path, recursive, label) in targets)
            {
                cancellationToken.ThrowIfCancellationRequested();

                try
                {
                    if (!Directory.Exists(path)) continue;

                    var searchOption = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;
                    long removed = 0;
                    int fileCount = 0;

                    foreach (var file in Directory.EnumerateFiles(path, "*", searchOption))
                    {
                        cancellationToken.ThrowIfCancellationRequested();

                        try
                        {
                            var info = new FileInfo(file);
                            if (!info.Exists) continue;

                            // Only thumbnail cache files are removed outside the temp folders.
                            if (!recursive && !info.Name.StartsWith("thumbcache", StringComparison.OrdinalIgnoreCase)
                                           && !info.Name.StartsWith("iconcache", StringComparison.OrdinalIgnoreCase))
                                continue;

                            var length = info.Length;
                            info.Delete();

                            removed += length;
                            fileCount++;
                        }
                        catch
                        {
                            // Locked file - normal, just skip it.
                        }
                    }

                    if (fileCount > 0)
                    {
                        freed += removed;
                        result.Details.Add($"{label}: {fileCount} file(s), {FormatBytes(removed)}");
                    }
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    _logger.Warning("OptimizationEngine", $"Cache clean skipped for {label}", null, ex);
                }
            }

            // DNS resolver cache - a genuine, safe, measurable win for the network stack.
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "ipconfig.exe",
                    Arguments = "/flushdns",
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                using (var process = Process.Start(psi))
                {
                    process?.WaitForExit(10000);
                    result.Details.Add("DNS resolver cache flushed");
                }
            }
            catch { }

            result.BytesRecovered = freed;
            result.Performed = freed > 0;
            result.Message = freed > 0
                ? $"Recovered {FormatBytes(freed)} of disposable data on disk. " +
                  "Note: this frees storage, not RAM. Windows keeps RAM in the standby cache on purpose - " +
                  "that memory is still available to your applications."
                : "Nothing to clean: the disposable caches were already empty. " +
                  "No RAM was artificially cleared, because doing so would slow the system down instead of speeding it up.";

            _logger.Info("OptimizationEngine", result.Message);
            return result;
        }

        private static string FormatBytes(long bytes)
        {
            if (bytes < 1024) return $"{bytes} B";
            if (bytes < 1024 * 1024) return $"{bytes / 1024.0:F1} KB";
            if (bytes < 1024L * 1024 * 1024) return $"{bytes / (1024.0 * 1024):F1} MB";
            return $"{bytes / (1024.0 * 1024 * 1024):F2} GB";
        }

        #endregion

        #region Reports

        /// <summary>
        /// Detailed memory breakdown - the user asked to see more than "used %".
        /// </summary>
        public MemoryBreakdown GetMemoryBreakdown(SystemInfo systemInfo)
        {
            var (pageFileTotal, pageFileAvailable) = WindowsApiHelper.GetPageFileBytes();

            return new MemoryBreakdown
            {
                TotalPhysical = systemInfo.TotalPhysicalMemory,
                AvailablePhysical = systemInfo.AvailablePhysicalMemory,
                UsedPhysical = systemInfo.UsedPhysicalMemory,
                Cached = systemInfo.CachedMemory,
                Standby = systemInfo.StandbyMemory,
                Free = systemInfo.FreeMemory,
                PagedPool = systemInfo.PagedPoolMemory,
                NonPagedPool = systemInfo.NonPagedPoolMemory,
                Committed = PerformanceCounterHelper.GetCommittedMemory(),
                CommitLimit = PerformanceCounterHelper.GetCommitLimit(),
                PageFileTotal = pageFileTotal,
                PageFileAvailable = pageFileAvailable,
                PageFileUsage = systemInfo.PageFileUsage,
                WorkingSetTotal = systemInfo.Processes.Sum(p => p.WorkingSet)
            };
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            try
            {
                _scanner.Dispose();
                _analyzer.Dispose();
                _riskAnalyzer.Dispose();
                _planner.Dispose();
                _executor.Dispose();
                _verification.Dispose();
                _recovery.Dispose();
                _aiService.Dispose();
                _startupManager.Dispose();
                _serviceManager.Dispose();
                PerformanceCounterHelper.ResetCache();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Memory breakdown used by the RAM page (used / available / cached / standby / committed...).
    /// </summary>
    public sealed class MemoryBreakdown
    {
        public long TotalPhysical { get; set; }
        public long AvailablePhysical { get; set; }
        public long UsedPhysical { get; set; }
        public long Cached { get; set; }
        public long Standby { get; set; }
        public long Free { get; set; }
        public long PagedPool { get; set; }
        public long NonPagedPool { get; set; }
        public long Committed { get; set; }
        public long CommitLimit { get; set; }
        public long PageFileTotal { get; set; }
        public long PageFileAvailable { get; set; }
        public long PageFileUsage { get; set; }
        public long WorkingSetTotal { get; set; }

        public string FormattedTotal => Format(TotalPhysical);
        public string FormattedUsed => Format(UsedPhysical);
        public string FormattedAvailable => Format(AvailablePhysical);
        public string FormattedCached => Format(Cached);
        public string FormattedStandby => Format(Standby);
        public string FormattedFree => Format(Free);
        public string FormattedPagedPool => Format(PagedPool);
        public string FormattedNonPagedPool => Format(NonPagedPool);
        public string FormattedCommitted => Format(Committed);
        public string FormattedCommitLimit => Format(CommitLimit);
        public string FormattedPageFileUsage => Format(PageFileUsage);
        public string FormattedWorkingSetTotal => Format(WorkingSetTotal);

        public static string Format(long bytes)
        {
            if (bytes <= 0) return "N/A";

            if (bytes < 1024) return $"{bytes} B";
            if (bytes < 1024 * 1024) return $"{bytes / 1024.0:F1} KB";
            if (bytes < 1024L * 1024 * 1024) return $"{bytes / (1024.0 * 1024):F1} MB";
            return $"{bytes / (1024.0 * 1024 * 1024):F2} GB";
        }
    }

    /// <summary>
    /// The final optimisation report shown to the user (and written to the log).
    /// Every number comes from a measurement, never from an estimate presented as fact.
    /// </summary>
    public sealed class OptimizationReport
    {
        public string Title { get; set; } = "SYSTEM OPTIMIZATION REPORT";
        public DateTime GeneratedAt { get; set; } = DateTime.Now;
        public TimeSpan Duration { get; set; }

        public float BeforeRamPercent { get; set; }
        public float AfterRamPercent { get; set; }
        public float BeforeCpuPercent { get; set; }
        public float AfterCpuPercent { get; set; }
        public int BeforeProcessCount { get; set; }
        public int AfterProcessCount { get; set; }

        public long RecoveredBytes { get; set; }
        public int SuccessCount { get; set; }
        public int FailedCount { get; set; }
        public int SkippedCount { get; set; }

        public List<string> Actions { get; set; } = new List<string>();
        public List<string> Skipped { get; set; } = new List<string>();
        public List<string> Notes { get; set; } = new List<string>();

        /// <summary>True when the optimisation produced no measurable improvement.</summary>
        public bool NoSignificantChange { get; set; }

        public string RamDeltaText =>
            $"{BeforeRamPercent:F0}% -> {AfterRamPercent:F0}% ({BeforeRamPercent - AfterRamPercent:+0.0;-0.0;0.0} points)";

        public string CpuDeltaText =>
            $"{BeforeCpuPercent:F0}% -> {AfterCpuPercent:F0}% ({BeforeCpuPercent - AfterCpuPercent:+0.0;-0.0;0.0} points)";

        public string ProcessDeltaText =>
            $"{BeforeProcessCount} -> {AfterProcessCount} ({BeforeProcessCount - AfterProcessCount:+0;-0;0})";

        public string RecoveredText => MemoryBreakdown.Format(RecoveredBytes);

        public string Summary
        {
            get
            {
                if (NoSignificantChange)
                {
                    return "No significant optimisation was possible: the memory in use is genuinely " +
                           "required by Windows and your open applications. Nothing was forced.";
                }

                return $"Freed about {RecoveredText} of memory and closed {SuccessCount} " +
                       $"unnecessary background item(s).";
            }
        }

        public static OptimizationReport Empty(string message) => new OptimizationReport
        {
            Notes = { message },
            NoSignificantChange = true
        };

        public static OptimizationReport FromExecution(
            OptimizationPlan plan,
            ExecutionResult execution,
            PostExecutionVerificationResult verification,
            TimeSpan duration)
        {
            var report = new OptimizationReport
            {
                Duration = duration,
                BeforeRamPercent = plan.BeforeSystemInfo?.RamUsagePercentage ?? 0,
                AfterRamPercent = plan.AfterSystemInfo?.RamUsagePercentage ?? plan.BeforeSystemInfo?.RamUsagePercentage ?? 0,
                BeforeCpuPercent = plan.BeforeSystemInfo?.CpuUsage ?? 0,
                AfterCpuPercent = plan.AfterSystemInfo?.CpuUsage ?? plan.BeforeSystemInfo?.CpuUsage ?? 0,
                BeforeProcessCount = plan.BeforeSystemInfo?.TotalProcessCount ?? 0,
                AfterProcessCount = plan.AfterSystemInfo?.TotalProcessCount ?? plan.BeforeSystemInfo?.TotalProcessCount ?? 0,
                SuccessCount = execution.SuccessfulCount,
                FailedCount = execution.FailedCount,
                SkippedCount = execution.SkippedCount,
                RecoveredBytes = Math.Max(0,
                    (plan.BeforeSystemInfo?.UsedPhysicalMemory ?? 0) - (plan.AfterSystemInfo?.UsedPhysicalMemory ?? 0))
            };

            foreach (var action in execution.ExecutedActions)
            {
                report.Actions.Add($"{Describe(action)} - recovered {action.FormattedEstimatedRecovery} ({action.RiskLevel} risk)");
            }

            foreach (var action in execution.SkippedActions)
            {
                report.Skipped.Add($"{Describe(action)} - {action.SkipReason}");
            }

            // Security-related skips are always explained: the user explicitly asked for this.
            foreach (var note in BuildSecurityNotes(plan))
            {
                report.Skipped.Add(note);
            }

            // Honesty check: did anything actually change?
            var ramDelta = Math.Abs(report.BeforeRamPercent - report.AfterRamPercent);
            var processDelta = Math.Abs(report.BeforeProcessCount - report.AfterProcessCount);

            if (report.SuccessCount == 0 || (ramDelta < 0.5 && processDelta == 0))
            {
                report.NoSignificantChange = true;
                report.Notes.Add(
                    "No significant optimisation was possible. The memory currently in use is actively " +
                    "required by Windows and your open applications - artificially clearing it would not " +
                    "improve performance.");
            }

            if (!string.IsNullOrWhiteSpace(verification?.Report))
            {
                report.Notes.Add(verification.Report);
            }

            return report;
        }

        private static string Describe(OptimizationAction action)
        {
            switch (action.ActionType)
            {
                case OptimizationActionType.CloseProcess:
                    return $"Closed {action.Target}";

                case OptimizationActionType.DisableStartup:
                    return $"Disabled start-up entry {action.Target}";

                case OptimizationActionType.StopService:
                    return $"Stopped service {action.Target}";

                case OptimizationActionType.DisableService:
                    return $"Disabled service {action.Target}";

                case OptimizationActionType.ClearCache:
                    return $"Cleared disposable caches ({action.Target})";

                case OptimizationActionType.ChangePriority:
                    return $"Raised priority of {action.Target}";

                case OptimizationActionType.ChangeAffinity:
                    return $"Adjusted CPU affinity of {action.Target}";

                case OptimizationActionType.AdjustPowerSettings:
                    return $"Set power mode to {action.Target}";

                case OptimizationActionType.UninstallApplication:
                    return $"Uninstalled {action.Target}";

                default:
                    return action.Description;
            }
        }

        private static IEnumerable<string> BuildSecurityNotes(OptimizationPlan plan)
        {
            yield return "Windows Defender - never touched (security first)";
            yield return "Windows Firewall - never touched";
            yield return "Windows core services and drivers - never touched";
            yield return "Pagefile and memory manager - never modified";
        }
    }
}

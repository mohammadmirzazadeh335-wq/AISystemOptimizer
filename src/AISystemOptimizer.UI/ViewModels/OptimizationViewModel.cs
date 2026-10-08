using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Optimisation page: memory breakdown, plan preview (what will be closed / disabled,
    /// expected recovery, aggregated risk) and the execution + report flow.
    /// </summary>
    public sealed class OptimizationViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;

        private SystemInfo _systemInfo = new SystemInfo();
        private MemoryBreakdown _memory = new MemoryBreakdown();
        private OptimizationPlan? _plan;
        private ObservableCollection<OptimizationAction> _actions = new();
        private ObservableCollection<OptimizationAction> _skippedActions = new();
        private string _reportText = string.Empty;
        private string _planSummary = "No plan has been prepared yet. Use Smart Optimize on the dashboard.";
        private string _ramTargetMessage = string.Empty;
        private int _ramTargetProgress;
        private bool _createRestorePoint = true;
        private bool _isGameModePlan;

        /// <summary>
        /// Cancels the scan / plan / execution that is currently running.
        /// Replaced for every operation so that a finished run never cancels the next one.
        /// </summary>
        private CancellationTokenSource? _operationCts;

        #endregion

        #region Construction

        public OptimizationViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            CreatePlanCommand = new AsyncRelayCommand(CreatePlanAsync, () => !IsBusy, engine.Logger);
            OptimizeCommand = new AsyncRelayCommand(ExecutePlanAsync, () => CanExecutePlan, engine.Logger);
            CancelPlanCommand = new RelayCommand(ClearPlan);
            CancelExecutionCommand = new RelayCommand(CancelExecution, () => CanCancelExecution);
            RefreshSystemInfoCommand = new AsyncRelayCommand(RefreshSystemInfoAsync, () => !IsBusy, engine.Logger);
            UndoCommand = new AsyncRelayCommand(UndoAsync, () => _engine.CanUndo, engine.Logger);
            OpenReportCommand = new RelayCommand(OpenReport);
            CopyReportCommand = new RelayCommand(CopyReport);
        }

        #endregion

        #region State

        /// <summary>Snapshot the page is describing.</summary>
        public SystemInfo SystemInfo
        {
            get => _systemInfo;
            private set
            {
                if (SetProperty(ref _systemInfo, value))
                    RaiseSystemInfoDependentProperties();
            }
        }

        /// <summary>Detailed memory breakdown (used / cached / standby / committed...).</summary>
        public MemoryBreakdown Memory
        {
            get => _memory;
            private set => SetProperty(ref _memory, value);
        }

        /// <summary>The plan currently under review (null when none).</summary>
        public OptimizationPlan? Plan
        {
            get => _plan;
            private set
            {
                if (SetProperty(ref _plan, value))
                {
                    OnPropertyChanged(nameof(HasPlan));
                    OnPropertyChanged(nameof(CanExecutePlan));
                    OnPropertyChanged(nameof(PlanTitle));
                    OnPropertyChanged(nameof(PlanRiskLevel));
                    OnPropertyChanged(nameof(PlanRiskText));
                    OnPropertyChanged(nameof(PlanEstimatedRam));
                    OnPropertyChanged(nameof(PlanCpuEstimate));
                    OnPropertyChanged(nameof(PlanActionCountText));
                    OnPropertyChanged(nameof(IsRestorePointRecommended));
                }
            }
        }

        /// <summary>Actions the plan will run.</summary>
        public ObservableCollection<OptimizationAction> Actions
        {
            get => _actions;
            private set => SetProperty(ref _actions, value);
        }

        /// <summary>Actions that were skipped (in use, protected, rejected).</summary>
        public ObservableCollection<OptimizationAction> SkippedActions
        {
            get => _skippedActions;
            private set => SetProperty(ref _skippedActions, value);
        }

        /// <summary>Human readable final report.</summary>
        public string ReportText
        {
            get => _reportText;
            private set
            {
                if (SetProperty(ref _reportText, value))
                    OnPropertyChanged(nameof(HasReport));
            }
        }

        public bool HasReport => !string.IsNullOrEmpty(ReportText);

        public bool HasPlan => Plan != null && Plan.Actions.Count > 0;

        public bool CanExecutePlan => HasPlan && !IsBusy;

        /// <summary>One-line summary shown above the action list.</summary>
        public string PlanSummary
        {
            get => _planSummary;
            private set => SetProperty(ref _planSummary, value);
        }

        public string PlanTitle => Plan?.Name ?? "No plan prepared";

        public RiskLevel PlanRiskLevel => Plan?.OverallRiskLevel ?? RiskLevel.Low;

        public string PlanRiskText => Plan == null
            ? "-"
            : Plan.OverallRiskLevel switch
            {
                RiskLevel.Low => "\u25CF LOW - safe, reversible where possible",
                RiskLevel.Medium => "\u25CF MEDIUM - review before running",
                RiskLevel.High => "\u25CF HIGH - not offered for automatic execution",
                _ => "\u25CF CRITICAL - blocked by the safety layer"
            };

        public string PlanEstimatedRam => Plan == null ? "-" : "-" + Plan.FormattedEstimatedRamRecovery;

        public string PlanCpuEstimate => Plan == null ? "-" : $"~{Plan.EstimatedCpuImprovement:F1}% CPU";

        public string PlanActionCountText =>
            Plan == null ? "0 actions" : $"{Plan.TotalActionCount} action(s), {Plan.SkippedActionCount} skipped";

        /// <summary>Restore points are recommended for any plan that changes system configuration.</summary>
        public bool IsRestorePointRecommended =>
            Plan != null && Plan.Actions.Any(a => a.ActionType != OptimizationActionType.CloseProcess);

        /// <summary>Whether a restore point will be attempted before executing.</summary>
        public bool CreateRestorePoint
        {
            get => _createRestorePoint;
            set => SetProperty(ref _createRestorePoint, value);
        }

        /// <summary>True when the reviewed plan came from Game Mode.</summary>
        public bool IsGameModePlan
        {
            get => _isGameModePlan;
            private set => SetProperty(ref _isGameModePlan, value);
        }

        /// <summary>Honest statement about the user's RAM target.</summary>
        public string RamTargetMessage
        {
            get => _ramTargetMessage;
            private set => SetProperty(ref _ramTargetMessage, value);
        }

        /// <summary>How much of the RAM target the safe optimisations can deliver (0-100).</summary>
        public int RamTargetProgress
        {
            get => _ramTargetProgress;
            private set => SetProperty(ref _ramTargetProgress, value);
        }

        #endregion

        #region Memory presentation

        public string RamUsageText =>
            $"{SystemInfo.RamUsagePercentage:F1}% used \u2022 {Memory.FormattedUsed} of {Memory.FormattedTotal}";

        public string RamDetailText =>
            $"Available {Memory.FormattedAvailable} \u2022 Cached {Memory.FormattedCached} \u2022 " +
            $"Standby {Memory.FormattedStandby} \u2022 Committed {Memory.FormattedCommitted} of {Memory.FormattedCommitLimit}";

        public string RamExplanation =>
            "Cached and standby memory is not wasted memory. Windows uses otherwise idle RAM to cache " +
            "files and ready-to-run code; it is handed back instantly when an application needs it. " +
            "Forcing it to be cleared makes the machine slower, which is why this application never does it. " +
            "Only the working sets of programs you are not using can be recovered for real.";

        public string PageFileText =>
            $"Pagefile usage {Memory.FormattedPageFileUsage}. The pagefile is never disabled or resized by this app.";

        public string ProcessMemoryText =>
            $"Working sets of all processes: {Memory.FormattedWorkingSetTotal}";

        private void RaiseSystemInfoDependentProperties()
        {
            OnPropertyChanged(nameof(RamUsageText));
            OnPropertyChanged(nameof(RamDetailText));
            OnPropertyChanged(nameof(PageFileText));
            OnPropertyChanged(nameof(ProcessMemoryText));
            OnPropertyChanged(nameof(HealthScore));
            OnPropertyChanged(nameof(HealthScoreText));
            OnPropertyChanged(nameof(ScoreRows));
        }

        public int HealthScore => SystemInfo.SystemHealthScore;

        public string HealthScoreText => $"{SystemInfo.SystemHealthScore}/100";

        /// <summary>Score rows for the score card.</summary>
        public IEnumerable<ScoreRow> ScoreRows =>
            SystemInfo.PerformanceScores
                .Select(kv => new ScoreRow { Name = kv.Key, Score = kv.Value })
                .OrderByDescending(r => r.Score);

        #endregion

        #region Commands

        public AsyncRelayCommand CreatePlanCommand { get; }
        public AsyncRelayCommand OptimizeCommand { get; }
        public RelayCommand CancelPlanCommand { get; }

        /// <summary>Stops the optimization run that is in progress, after the current action.</summary>
        public RelayCommand CancelExecutionCommand { get; }
        public AsyncRelayCommand RefreshSystemInfoCommand { get; }
        public AsyncRelayCommand UndoCommand { get; }
        public RelayCommand OpenReportCommand { get; }
        public RelayCommand CopyReportCommand { get; }

        #endregion

        #region Data

        /// <summary>Apply a scan result.</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            SystemInfo = info;
            Memory = _engine.GetMemoryBreakdown(info);
            RamTargetProgress = _engine.GetRamTargetProgress(info);
            RamTargetMessage = _engine.DescribeRamTarget(info);
        }

        /// <summary>Load a plan for review (called by the shell after Smart Optimize / Game Mode).</summary>
        public void LoadPlan(OptimizationPlan plan)
        {
            Plan = plan;
            IsGameModePlan = plan.Mode == OptimizationMode.GameMode;

            Actions = new ObservableCollection<OptimizationAction>(plan.Actions);
            SkippedActions = new ObservableCollection<OptimizationAction>(plan.SkippedActions);

            ReportText = string.Empty;

            var sb = new StringBuilder();
            sb.Append($"{plan.Actions.Count} action(s) ready, {plan.SkippedActions.Count} skipped. ");

            if (plan.EstimatedRamRecovery > 0)
                sb.Append($"Estimated recovery {plan.FormattedEstimatedRamRecovery}. ");
            else
                sb.Append("No measurable memory recovery is expected from these actions. ");

            sb.Append(plan.OverallRiskLevel == RiskLevel.Low
                ? "Every action is low risk."
                : $"Highest risk in this plan: {plan.OverallRiskLevel}.");

            PlanSummary = sb.ToString().TrimEnd();
        }

        /// <summary>Refresh the system information card.</summary>
        public async Task RefreshSystemInfoAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Refreshing system information...", async () =>
            {
                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);
            });

            EndOperation();
        }

        #endregion

        #region Plan lifecycle

        private async Task CreatePlanAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Analysing and building an optimisation plan...", async () =>
            {
                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);

                var plan = await _engine.CreatePlanAsync(
                    OptimizationMode.Manual,
                    info,
                    cancellationToken: token).ConfigureAwait(true);

                if (plan == null || plan.Actions.Count == 0)
                {
                    PlanSummary =
                        "No safe optimisation was found. Everything using meaningful memory is either in " +
                        "use, protected, or required by Windows.";
                    ClearPlanCollections();
                    return;
                }

                LoadPlan(plan);
            });
        }

        /// <summary>
        /// Execute the reviewed plan. This is the only place the UI triggers real changes,
        /// and it always runs through SafetyValidator inside the engine.
        /// </summary>
        private async Task ExecutePlanAsync()
        {
            var plan = Plan;
            if (plan == null || plan.Actions.Count == 0) return;

            var confirm = MessageBox.Show(
                BuildConfirmationText(plan),
                "Confirm optimisation",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes) return;

            var token = BeginOperation();

            await RunGuardedAsync("Applying safe optimisations...", async () =>
            {
                var report = await _engine.ExecutePlanAsync(plan, CreateRestorePoint, token).ConfigureAwait(true);

                ReportText = BuildReportText(report);
                PlanSummary = report.Summary;

                // Refresh both the page and the dashboard through a normal scan.
                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);

                Plan = null;
                ClearPlanCollections();

                UndoCommand.RaiseCanExecuteChanged();
            });

            EndOperation();
        }

        private static string BuildConfirmationText(OptimizationPlan plan)
        {
            var sb = new StringBuilder();

            sb.AppendLine("OPTIMISATION PREVIEW");
            sb.AppendLine();

            var closes = plan.Actions.Where(a => a.ActionType == OptimizationActionType.CloseProcess).ToList();
            var disables = plan.Actions.Where(a => a.ActionType == OptimizationActionType.DisableStartup).ToList();
            var services = plan.Actions.Where(a =>
                a.ActionType == OptimizationActionType.StopService ||
                a.ActionType == OptimizationActionType.DisableService).ToList();
            var others = plan.Actions.Except(closes).Except(disables).Except(services).ToList();

            if (closes.Count > 0)
            {
                sb.AppendLine("Will close:");
                foreach (var action in closes)
                    sb.AppendLine($"  \u2022 {action.Target} ({action.FormattedEstimatedRecovery})");
                sb.AppendLine();
            }

            if (disables.Count > 0)
            {
                sb.AppendLine("Will disable at start-up:");
                foreach (var action in disables)
                    sb.AppendLine($"  \u2022 {action.Target}");
                sb.AppendLine();
            }

            if (services.Count > 0)
            {
                sb.AppendLine("Will stop/disable services:");
                foreach (var action in services)
                    sb.AppendLine($"  \u2022 {action.Target}");
                sb.AppendLine();
            }

            if (others.Count > 0)
            {
                sb.AppendLine("Other actions:");
                foreach (var action in others)
                    sb.AppendLine($"  \u2022 {action.Description}");
                sb.AppendLine();
            }

            sb.AppendLine($"Estimated memory recovery: {plan.FormattedEstimatedRamRecovery}");
            sb.AppendLine($"Overall risk: {plan.OverallRiskLevel}");
            sb.AppendLine();
            sb.AppendLine("Protected items (Windows core, drivers, Defender, firewall, pagefile) are never touched.");
            sb.AppendLine();
            sb.Append("Run these actions now?");

            return sb.ToString();
        }

        private string BuildReportText(OptimizationReport report)
        {
            var sb = new StringBuilder();

            sb.AppendLine(report.Title);
            sb.AppendLine(new string('=', report.Title.Length));
            sb.AppendLine($"Generated: {report.GeneratedAt:yyyy-MM-dd HH:mm:ss}   Duration: {report.Duration.TotalSeconds:F1}s");
            sb.AppendLine();

            sb.AppendLine("BEFORE -> AFTER");
            sb.AppendLine($"  RAM:       {report.RamDeltaText}");
            sb.AppendLine($"  CPU:       {report.CpuDeltaText}");
            sb.AppendLine($"  Processes: {report.ProcessDeltaText}");
            sb.AppendLine($"  Recovered: {report.RecoveredText}");
            sb.AppendLine();

            if (report.Actions.Count > 0)
            {
                sb.AppendLine("ACTIONS");
                foreach (var action in report.Actions)
                    sb.AppendLine("  \u2713 " + action);
                sb.AppendLine();
            }

            if (report.Skipped.Count > 0)
            {
                sb.AppendLine("SKIPPED (and why)");
                foreach (var skipped in report.Skipped)
                    sb.AppendLine("  \u26A0 " + skipped);
                sb.AppendLine();
            }

            sb.AppendLine("SUMMARY");
            sb.AppendLine("  " + report.Summary);

            if (report.NoSignificantChange)
            {
                sb.AppendLine();
                sb.AppendLine("  Honest note: the numbers above show no meaningful improvement. Rather than pretend");
                sb.AppendLine("  otherwise, the optimiser reports it. Memory that is genuinely in use cannot be");
                sb.AppendLine("  'freed' without harming performance or stability.");
            }

            if (report.Notes.Count > 0)
            {
                sb.AppendLine();
                sb.AppendLine("VERIFICATION");
                foreach (var note in report.Notes)
                    sb.AppendLine("  " + note);
            }

            return sb.ToString();
        }

        private void ClearPlan()
        {
            Plan = null;
            ClearPlanCollections();
            PlanSummary = "Plan cancelled. Nothing was changed.";
        }

        #endregion

        #region Cancellation

        /// <summary>
        /// Start a cancellable operation and return its token.
        ///
        /// A fresh source is created per operation so that cancelling one run can never affect the
        /// next one, and the previous source is disposed so that registrations do not accumulate.
        /// </summary>
        private CancellationToken BeginOperation()
        {
            EndOperation();

            _operationCts = new CancellationTokenSource();

            OnPropertyChanged(nameof(CanCancelExecution));
            CancelExecutionCommand.RaiseCanExecuteChanged();

            return _operationCts.Token;
        }

        /// <summary>Release the current operation's cancellation source.</summary>
        private void EndOperation()
        {
            var previous = _operationCts;
            _operationCts = null;

            if (previous != null)
            {
                try
                {
                    previous.Dispose();
                }
                catch (ObjectDisposedException)
                {
                    // Already released - nothing to do.
                }
            }

            OnPropertyChanged(nameof(CanCancelExecution));
            CancelExecutionCommand.RaiseCanExecuteChanged();
        }

        /// <summary>
        /// True while something is running that the user is allowed to stop.
        /// </summary>
        public bool CanCancelExecution => IsBusy && _operationCts != null && !_operationCts.IsCancellationRequested;

        /// <summary>
        /// Stop the running operation.
        ///
        /// Two mechanisms are used together because they cover different phases:
        /// the token stops the scan/plan work and the executor's own loop, while
        /// <see cref="OptimizationEngine.CancelExecution"/> additionally signals the executor so that
        /// an action already in flight is not replaced by a forced kill.
        /// </summary>
        private void CancelExecution()
        {
            var cts = _operationCts;

            if (cts == null || cts.IsCancellationRequested)
                return;

            Logger.Info("OptimizationViewModel",
                "User requested cancellation of the running optimisation.");

            _engine.CancelExecution();

            try
            {
                cts.Cancel();
            }
            catch (ObjectDisposedException)
            {
                // The operation completed in the meantime.
            }

            BusyMessage = "Cancelling - the current step will finish, then nothing further runs...";
            OnPropertyChanged(nameof(CanCancelExecution));
            CancelExecutionCommand.RaiseCanExecuteChanged();
        }

        private void ClearPlanCollections()
        {
            Actions = new ObservableCollection<OptimizationAction>();
            SkippedActions = new ObservableCollection<OptimizationAction>();
        }

        private async Task UndoAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Undoing the last optimisation...", async () =>
            {
                var result = await _engine.UndoLastOptimizationAsync(token).ConfigureAwait(true);

                ReportText = result.IsSuccessful
                    ? $"Undo complete.\n\nRestored {result.SuccessfulCount} action(s).\n" +
                      "Start-up entries were re-enabled and services restarted where applicable. " +
                      "Applications that were closed must be started again manually."
                    : $"Undo finished with problems.\n\n{result.ErrorMessage}\n" +
                      "Check the log for details. No destructive operation was attempted.";

                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);

                UndoCommand.RaiseCanExecuteChanged();
            });
        }

        #endregion

        #region Report output

        private void OpenReport()
        {
            try
            {
                var folder = Core.Constants.AppConstants.ReportsDirectoryPath;
                System.IO.Directory.CreateDirectory(folder);

                var file = System.IO.Path.Combine(folder, $"report_{DateTime.Now:yyyyMMdd_HHmmss}.txt");
                System.IO.File.WriteAllText(file, ReportText);

                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = file,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not write the report: {ex.Message}";
            }
        }

        private void CopyReport()
        {
            try
            {
                if (!string.IsNullOrEmpty(ReportText))
                    Clipboard.SetText(ReportText);
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not copy the report: {ex.Message}";
            }
        }

        #endregion
    }

    /// <summary>A single row of the score card.</summary>
    public sealed class ScoreRow
    {
        public string Name { get; set; } = string.Empty;
        public int Score { get; set; }
        public string ScoreText => $"{Score}";
    }
}

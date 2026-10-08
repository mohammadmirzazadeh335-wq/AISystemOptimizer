using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// History page: every optimisation carried out, with before/after measurements,
    /// plus the report generator and the restore-point helper.
    /// </summary>
    public sealed class HistoryViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private ObservableCollection<OptimizationSession> _sessions = new();
        private OptimizationSession? _selectedSession;
        private string _reportText = string.Empty;
        private string _summaryText = string.Empty;

        #endregion

        #region Construction

        public HistoryViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            RefreshCommand = new RelayCommand(Refresh);
            CreateRestorePointCommand = new AsyncRelayCommand(CreateRestorePointAsync, () => !IsBusy);
            ExportReportCommand = new RelayCommand(ExportReport);
            ClearHistoryCommand = new AsyncRelayCommand(ClearHistoryAsync, () => !IsBusy);
            UndoSelectedCommand = new AsyncRelayCommand(UndoLastAsync, () => _engine.CanUndo);
            OpenBackupsCommand = new RelayCommand(OpenBackups);

            Refresh();
        }

        #endregion

        #region State

        /// <summary>All recorded sessions, newest first.</summary>
        public ObservableCollection<OptimizationSession> Sessions
        {
            get => _sessions;
            private set => SetProperty(ref _sessions, value);
        }

        /// <summary>Selected session.</summary>
        public OptimizationSession? SelectedSession
        {
            get => _selectedSession;
            set
            {
                if (SetProperty(ref _selectedSession, value))
                {
                    OnPropertyChanged(nameof(HasSelection));
                    OnPropertyChanged(nameof(SelectedSummary));
                }
            }
        }

        public bool HasSelection => SelectedSession != null;

        /// <summary>Session details.</summary>
        public string SelectedSummary
        {
            get
            {
                var session = SelectedSession;
                if (session == null) return "Select an entry to see what changed.";

                var sb = new StringBuilder();

                sb.AppendLine($"Session {session.Timestamp:yyyy-MM-dd HH:mm:ss}");
                sb.AppendLine($"Mode: {session.Plan?.Mode.ToString() ?? "unknown"}");
                sb.AppendLine();
                sb.AppendLine($"RAM:       {session.BeforeRamUsage:F1}% -> {session.AfterRamUsage:F1}%");
                sb.AppendLine($"CPU:       {session.BeforeCpuUsage:F1}% -> {session.AfterCpuUsage:F1}%");
                sb.AppendLine($"Processes: {session.BeforeProcessCount} -> {session.AfterProcessCount}");
                sb.AppendLine();

                if (session.Plan != null)
                {
                    sb.AppendLine($"Actions: {session.Plan.TotalActionCount} " +
                                  $"({session.Plan.SuccessfulActionCount} succeeded, " +
                                  $"{session.Plan.FailedActionCount} failed, " +
                                  $"{session.Plan.SkippedActionCount} skipped)");
                    sb.AppendLine();

                    foreach (var action in session.Plan.Actions)
                    {
                        sb.AppendLine($"  \u2022 {action.ActionType}: {action.Target} ({action.Status})");
                    }
                }

                return sb.ToString().TrimEnd();
            }
        }

        /// <summary>Aggregate statistics.</summary>
        public string SummaryText
        {
            get => _summaryText;
            private set => SetProperty(ref _summaryText, value);
        }

        /// <summary>Generated report.</summary>
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

        /// <summary>True when Windows allows us to create restore points.</summary>
        public bool IsElevated => WindowsApiHelper.IsAdministrator();

        public string RestorePointNote => IsElevated
            ? "A restore point will also be created automatically before any plan that changes system settings."
            : "Creating restore points requires administrator rights. Run the application as administrator " +
              "if you want automatic restore points.";

        #endregion

        #region Commands

        public RelayCommand RefreshCommand { get; }
        public AsyncRelayCommand CreateRestorePointCommand { get; }
        public RelayCommand ExportReportCommand { get; }
        public AsyncRelayCommand ClearHistoryCommand { get; }
        public AsyncRelayCommand UndoSelectedCommand { get; }
        public RelayCommand OpenBackupsCommand { get; }

        #endregion

        #region Data

        /// <summary>Reload the history from disk.</summary>
        public void Refresh()
        {
            try
            {
                _engine.Recovery.LoadHistory();

                var history = _engine.Recovery.History;

                Sessions = new ObservableCollection<OptimizationSession>(
                    history.GetRecentSessions(100).OrderByDescending(s => s.Timestamp));

                SummaryText = history.TotalOptimizationCount == 0
                    ? "No optimisation has been run yet."
                    : $"{history.TotalOptimizationCount} optimisation session(s) \u2022 " +
                      $"average success rate {history.AverageSuccessRate:F0}% \u2022 " +
                      $"total measured recovery {MemoryBreakdown.Format(history.TotalRamRecovered)} \u2022 " +
                      $"last run {(history.LastOptimizationDate?.ToString("yyyy-MM-dd HH:mm") ?? "never")}";

                ReportText = history.TotalOptimizationCount > 0 ? history.GenerateReport() : string.Empty;
            }
            catch (Exception ex)
            {
                Logger.Warning("HistoryViewModel", "Could not load the optimisation history", null, ex);
                ErrorMessage = "Could not load the optimisation history.";
            }
        }

        #endregion

        #region Actions

        private async Task CreateRestorePointAsync()
        {
            await RunGuardedAsync("Asking Windows for a restore point...", async () =>
            {
                var created = await Task.Run(() =>
                    _engine.Recovery.CreateRestorePoint("AI System Optimizer - manual restore point"))
                    .ConfigureAwait(true);

                if (created)
                {
                    MessageBox.Show(
                        "A Windows System Restore point was created.",
                        "Restore point",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                }
                else
                {
                    MessageBox.Show(
                        "Windows did not allow a restore point to be created.\n\n" +
                        "Common reasons:\n" +
                        "  \u2022 System Protection is turned off for the system drive.\n" +
                        "  \u2022 The application is not running as administrator.\n" +
                        "  \u2022 A restore point was created in the last 24 hours (Windows rate-limits these).\n\n" +
                        "You can enable System Protection in Control Panel > System > System Protection.",
                        "Restore point not created",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                }
            });
        }

        private async Task UndoLastAsync()
        {
            await RunGuardedAsync("Undoing the last optimisation...", async () =>
            {
                var result = await _engine.UndoLastOptimizationAsync().ConfigureAwait(true);

                MessageBox.Show(
                    result.IsSuccessful
                        ? $"Undo complete. {result.SuccessfulCount} action(s) reverted."
                        : $"Undo finished with problems.\n\n{result.ErrorMessage}",
                    "Undo last optimisation",
                    MessageBoxButton.OK,
                    result.IsSuccessful ? MessageBoxImage.Information : MessageBoxImage.Warning);

                Refresh();
            });
        }

        private void ExportReport()
        {
            try
            {
                var folder = Core.Constants.AppConstants.ReportsDirectoryPath;
                System.IO.Directory.CreateDirectory(folder);

                var file = System.IO.Path.Combine(folder, $"history_{DateTime.Now:yyyyMMdd_HHmmss}.txt");
                System.IO.File.WriteAllText(file, ReportText);

                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = file,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not export the report: {ex.Message}";
            }
        }

        private async Task ClearHistoryAsync()
        {
            var confirm = MessageBox.Show(
                "Delete the optimisation history?\n\n" +
                "This only removes the local log of what this application did. System restore points " +
                "created by Windows are not affected.",
                "Clear history",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync("Clearing history...", async () =>
            {
                await Task.Run(() => _engine.Recovery.ClearHistory()).ConfigureAwait(true);
                Refresh();
            });
        }

        private void OpenBackups()
        {
            try
            {
                var folder = Core.Constants.AppConstants.BackupDirectoryPath;

                if (!System.IO.Directory.Exists(folder))
                    System.IO.Directory.CreateDirectory(folder);

                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = folder,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not open the backup folder: {ex.Message}";
            }
        }

        #endregion
    }
}

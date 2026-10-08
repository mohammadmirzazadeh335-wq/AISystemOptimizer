using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Processes page: full process table, filtering, and the details pane
    /// (path, publisher, signature, parent, criticality, risk, AI explanation).
    /// </summary>
    public sealed class ProcessesViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private ObservableCollection<ProcessInfo> _processes = new();
        private ObservableCollection<ProcessInfo> _filteredProcesses = new();
        private ProcessInfo? _selectedProcess;
        private string _searchText = string.Empty;
        private string _categoryFilter = "All";
        private string _sortColumn = "RAM";
        private bool _showOnlyOptimizable;
        private string _aiExplanation = string.Empty;
        private string _classificationNote = string.Empty;

        #endregion

        #region Construction

        public ProcessesViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
            CloseProcessCommand = new AsyncRelayCommand(CloseSelectedAsync, CanCloseSelected);
            WhitelistCommand = new AsyncRelayCommand(WhitelistSelectedAsync, () => SelectedProcess != null);
            BlacklistCommand = new AsyncRelayCommand(BlacklistSelectedAsync, () => SelectedProcess != null);
            ExplainCommand = new AsyncRelayCommand(ExplainSelectedAsync, CanExplainSelected);
            ClearFiltersCommand = new RelayCommand(ClearFilters);
            IgnoreWhitelistCommand = new RelayCommand(() => { });
        }

        #endregion

        #region Collections and filters

        /// <summary>Every process from the last scan.</summary>
        public ObservableCollection<ProcessInfo> Processes
        {
            get => _processes;
            private set => SetProperty(ref _processes, value);
        }

        /// <summary>Processes after search/filter/sort are applied (what the grid binds to).</summary>
        public ObservableCollection<ProcessInfo> FilteredProcesses
        {
            get => _filteredProcesses;
            private set => SetProperty(ref _filteredProcesses, value);
        }

        /// <summary>Search text (name, path or publisher).</summary>
        public string SearchText
        {
            get => _searchText;
            set
            {
                if (SetProperty(ref _searchText, value))
                    ApplyFilters();
            }
        }

        /// <summary>Category filter: All, Application, Background, Critical, System, Driver, Security.</summary>
        public string CategoryFilter
        {
            get => _categoryFilter;
            set
            {
                if (SetProperty(ref _categoryFilter, value))
                    ApplyFilters();
            }
        }

        /// <summary>Sort column: RAM, CPU, Name, Category, Risk.</summary>
        public string SortColumn
        {
            get => _sortColumn;
            set
            {
                if (SetProperty(ref _sortColumn, value))
                    ApplyFilters();
            }
        }

        /// <summary>When true, only safe optimisation candidates are listed.</summary>
        public bool ShowOnlyOptimizable
        {
            get => _showOnlyOptimizable;
            set
            {
                if (SetProperty(ref _showOnlyOptimizable, value))
                    ApplyFilters();
            }
        }

        /// <summary>Available category filters for the combo box.</summary>
        public List<string> CategoryFilters { get; } = new()
        {
            "All", "Application", "Background", "Launcher", "Updater", "Cloud Sync",
            "Telemetry", "Game", "System", "Driver", "Security", "Critical"
        };

        /// <summary>Available sort columns.</summary>
        public List<string> SortColumns { get; } = new() { "RAM", "CPU", "Name", "Category", "Risk" };

        #endregion

        #region Selection and details

        /// <summary>Selected row - drives the details pane.</summary>
        public ProcessInfo? SelectedProcess
        {
            get => _selectedProcess;
            set
            {
                if (SetProperty(ref _selectedProcess, value))
                {
                    OnPropertyChanged(nameof(HasSelection));
                    OnPropertyChanged(nameof(SelectedProcessSummary));
                    OnPropertyChanged(nameof(CanCloseSelectedProcess));
                    OnPropertyChanged(nameof(CloseButtonTooltip));
                    AiExplanation = string.Empty;
                    ClassificationNote = BuildClassificationNote(value);
                    CloseProcessCommand.RaiseCanExecuteChanged();
                }
            }
        }

        public bool HasSelection => SelectedProcess != null;

        /// <summary>One-line summary of what the selected process is.</summary>
        public string SelectedProcessSummary
        {
            get
            {
                var process = SelectedProcess;
                if (process == null) return "Select a process to see its details.";

                return $"{process.DisplayName} \u2022 PID {process.Id} \u2022 {process.FormattedWorkingSet} RAM \u2022 " +
                       $"{process.FormattedCpuUsage} CPU \u2022 {process.Category} \u2022 risk {process.RiskLevel}";
            }
        }

        /// <summary>
        /// Plain language explanation of why we are (or are not) allowed to touch this process.
        /// </summary>
        public string ClassificationNote
        {
            get => _classificationNote;
            private set => SetProperty(ref _classificationNote, value);
        }

        /// <summary>AI explanation of the process (empty until requested).</summary>
        public string AiExplanation
        {
            get => _aiExplanation;
            private set => SetProperty(ref _aiExplanation, value);
        }

        /// <summary>Whether the AI is configured and reachable.</summary>
        public bool IsAiAvailable => _engine.Config.AiEnabled && _engine.Ai.IsAvailable;

        public int ProcessCount => FilteredProcesses.Count;

        public string CountText =>
            $"{FilteredProcesses.Count} of {Processes.Count} processes shown";

        /// <summary>Total memory held by the listed processes.</summary>
        public string ListedMemoryText =>
            $"Listed memory: {MemoryBreakdown.Format(FilteredProcesses.Sum(p => p.WorkingSet))}";

        #endregion

        #region Commands

        public AsyncRelayCommand RefreshCommand { get; }
        public AsyncRelayCommand CloseProcessCommand { get; }
        public AsyncRelayCommand WhitelistCommand { get; }
        public AsyncRelayCommand BlacklistCommand { get; }
        public AsyncRelayCommand ExplainCommand { get; }
        public RelayCommand ClearFiltersCommand { get; }
        public RelayCommand IgnoreWhitelistCommand { get; }

        /// <summary>Explains why <see cref="CloseProcessCommand"/> is enabled or not.</summary>
        public string CloseButtonTooltip
        {
            get
            {
                var process = SelectedProcess;

                if (process == null)
                    return "Select a process first.";

                if (CriticalProcesses.IsCritical(process.Name))
                    return "Protected: this is a critical Windows component and will never be closed by this app.";

                if (process.HasVisibleWindow || process.IsActive)
                    return "This application is in use. The optimiser never closes programs you are using.";

                if (process.IsService)
                    return "This process hosts a Windows service - use the Services page instead.";

                if (process.RiskLevel == RiskLevel.High || process.RiskLevel == RiskLevel.Critical)
                    return $"Risk level {process.RiskLevel}: not offered for closing.";

                return $"Close {process.DisplayName} and recover {process.FormattedWorkingSet}.";
            }
        }

        public bool CanCloseSelectedProcess =>
            SelectedProcess != null && processCanBeClosed(SelectedProcess);

        private static bool processCanBeClosed(ProcessInfo process)
        {
            if (process == null) return false;
            if (process.IsUserWhitelisted) return false;
            if (CriticalProcesses.IsCritical(process.Name)) return false;
            if (process.IsService) return false;
            if (process.HasVisibleWindow || process.IsActive) return false;
            if (process.RiskLevel == RiskLevel.High || process.RiskLevel == RiskLevel.Critical) return false;

            return true;
        }

        private bool CanCloseSelected() => CanCloseSelectedProcess;

        private bool CanExplainSelected() => SelectedProcess != null && IsAiAvailable;

        #endregion

        #region Data handling

        /// <summary>Apply a scan result (called by the shell).</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            Processes = new ObservableCollection<ProcessInfo>(info.Processes);
            ApplyFilters();
        }

        /// <summary>Re-read the process list.</summary>
        public async Task RefreshAsync()
        {
            await RunGuardedAsync("Refreshing the process list...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);
                ApplySystemInfo(info);
            });
        }

        /// <summary>Apply search, filter and sort.</summary>
        public void ApplyFilters()
        {
            IEnumerable<ProcessInfo> query = Processes;

            if (!string.IsNullOrWhiteSpace(SearchText))
            {
                var term = SearchText.Trim();
                query = query.Where(p =>
                    p.Name.Contains(term, StringComparison.OrdinalIgnoreCase) ||
                    p.DisplayName.Contains(term, StringComparison.OrdinalIgnoreCase) ||
                    p.Path.Contains(term, StringComparison.OrdinalIgnoreCase) ||
                    p.Publisher.Contains(term, StringComparison.OrdinalIgnoreCase));
            }

            if (!string.IsNullOrEmpty(CategoryFilter) && CategoryFilter != "All")
            {
                var wanted = CategoryFilter switch
                {
                    "Application" => ProcessCategory.UserApplication,
                    "Background" => ProcessCategory.BackgroundApplication,
                    "Launcher" => ProcessCategory.Launcher,
                    "Updater" => ProcessCategory.Updater,
                    "Cloud Sync" => ProcessCategory.CloudSync,
                    "Telemetry" => ProcessCategory.Telemetry,
                    "Game" => ProcessCategory.Game,
                    "System" => ProcessCategory.System,
                    "Driver" => ProcessCategory.Driver,
                    "Security" => ProcessCategory.Security,
                    "Critical" => ProcessCategory.Critical,
                    _ => ProcessCategory.Unknown
                };

                query = query.Where(p => p.Category == wanted);
            }

            if (ShowOnlyOptimizable)
            {
                query = query.Where(p => !CriticalProcesses.IsCritical(p.Name))
                             .Where(p => !p.IsActive && !p.HasVisibleWindow)
                             .Where(p => !p.IsService)
                             .Where(p => p.RiskLevel == RiskLevel.Low || p.RiskLevel == RiskLevel.Medium)
                             .Where(p => p.WorkingSet >= 10 * 1024 * 1024);
            }

            query = SortColumn switch
            {
                "CPU" => query.OrderByDescending(p => p.CpuUsage),
                "Name" => query.OrderBy(p => p.DisplayName, StringComparer.OrdinalIgnoreCase),
                "Category" => query.OrderBy(p => p.Category).ThenByDescending(p => p.WorkingSet),
                "Risk" => query.OrderByDescending(p => p.RiskLevel).ThenByDescending(p => p.WorkingSet),
                _ => query.OrderByDescending(p => p.WorkingSet)
            };

            FilteredProcesses = new ObservableCollection<ProcessInfo>(query);

            OnPropertyChanged(nameof(ProcessCount));
            OnPropertyChanged(nameof(CountText));
            OnPropertyChanged(nameof(ListedMemoryText));
        }

        private void ClearFilters()
        {
            SearchText = string.Empty;
            CategoryFilter = "All";
            SortColumn = "RAM";
            ShowOnlyOptimizable = false;
        }

        private static string BuildClassificationNote(ProcessInfo? process)
        {
            if (process == null) return string.Empty;

            if (CriticalProcesses.IsCritical(process.Name))
            {
                return "PROTECTED (critical): This is a core Windows component. Closing it can crash or " +
                       "destabilise the session, so this application will never touch it - not even in " +
                       "Automatic or Game mode.";
            }

            if (process.IsSecurity)
            {
                return "PROTECTED (security): This is part of your security stack. Reducing RAM by weakening " +
                       "your protection is never an acceptable trade, so it is excluded from every plan.";
            }

            if (process.IsService)
            {
                return "SERVICE: This process hosts a Windows service. Stop it from the Services page where the " +
                       "dependency and start-type information is available.";
            }

            if (process.IsDriver)
            {
                return "DRIVER: Hardware driver component. Drivers are never touched - a broken driver can make " +
                       "the machine unusable.";
            }

            if (process.HasVisibleWindow || process.IsActive)
            {
                return "IN USE: This application has a visible window, so the optimiser treats it as actively " +
                       "used and will never close it automatically, regardless of how much memory it holds.";
            }

            if (process.IsUserWhitelisted)
            {
                return "WHITELISTED: You added this process to the whitelist, so it is excluded from every " +
                       "optimisation.";
            }

            if (process.Category == ProcessCategory.BackgroundApplication)
            {
                return "GOOD CANDIDATE: Runs in the background with no visible window. Closing it is safe and " +
                       "recoverable - it can simply be started again.";
            }

            return $"SAFE TO REVIEW: Category {process.Category}, risk {process.RiskLevel}. " +
                   "Closing it is allowed after you confirm, and the action is written to the log.";
        }

        #endregion

        #region Actions

        /// <summary>
        /// Close the selected process. This goes through the same safety validator the
        /// automatic path uses - the manual button is not a bypass.
        /// </summary>
        private async Task CloseSelectedAsync()
        {
            var process = SelectedProcess;
            if (process == null) return;

            var confirm = MessageBox.Show(
                $"Close {process.DisplayName} (PID {process.Id})?\n\n" +
                $"Memory used: {process.FormattedWorkingSet}\n" +
                $"Risk level: {process.RiskLevel}\n\n" +
                "Any unsaved work in that application will be lost.",
                "Confirm close process",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync($"Closing {process.DisplayName}...", async () =>
            {
                var action = new OptimizationAction
                {
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = process.Name,
                    TargetPid = process.Id,
                    TargetPath = process.Path,
                    ResourceType = ResourceType.RAM,
                    RiskLevel = process.RiskLevel,
                    Description = $"User closed {process.DisplayName}",
                    Reason = "Manual action from the Processes page",
                    EstimatedResourceRecovery = process.WorkingSet,
                    CanUndo = false,
                    UserConfirmed = true,
                    ProcessInfo = process
                };

                var info = _engine.Scanner.LastScanResult;

                await Task.Run(() =>
                {
                    var executor = new SafeExecutor(_engine.Logger, _engine.Config);
                    var result = executor.ExecuteActionAsync(action, info).GetAwaiter().GetResult();

                    ErrorMessage = result.IsSuccessful ? string.Empty
                        : $"Could not close {process.DisplayName}: {result.ErrorMessage}";
                }).ConfigureAwait(true);

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task WhitelistSelectedAsync()
        {
            var process = SelectedProcess;
            if (process == null) return;

            if (!_engine.Config.WhitelistedProcesses.Contains(process.Name, StringComparer.OrdinalIgnoreCase))
            {
                _engine.Config.WhitelistedProcesses.Add(process.Name);
                _engine.Config.Save();
            }

            await Task.CompletedTask;

            ClassificationNote = $"'{process.Name}' added to the whitelist. It will never be closed automatically.";
        }

        private async Task BlacklistSelectedAsync()
        {
            var process = SelectedProcess;
            if (process == null) return;

            if (!_engine.Config.BlacklistedProcesses.Contains(process.Name, StringComparer.OrdinalIgnoreCase))
            {
                _engine.Config.BlacklistedProcesses.Add(process.Name);
                _engine.Config.Save();
            }

            await Task.CompletedTask;

            ClassificationNote = $"'{process.Name}' added to 'Never touch'. It is now excluded from every plan.";
        }

        private async Task ExplainSelectedAsync()
        {
            var process = SelectedProcess;
            if (process == null || !IsAiAvailable) return;

            await RunGuardedAsync($"Asking the local AI about {process.DisplayName}...", async () =>
            {
                var explanation = await Task.Run(() => _engine.Ai.ExplainProcess(process)).ConfigureAwait(true);

                AiExplanation = string.IsNullOrWhiteSpace(explanation)
                    ? "The AI model returned no answer. Rule-based analysis is still available above."
                    : explanation;
            });
        }

        #endregion
    }
}

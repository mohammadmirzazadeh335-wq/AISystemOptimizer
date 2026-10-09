using System;
using System.Threading;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Application shell view model: owns the engine, the navigation state, the live
    /// metric timer and the child page view models.
    /// </summary>
    public sealed class MainViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private readonly DispatcherTimer _liveTimer;
        private int _sampleInFlight;
        private readonly Stopwatch _uptime = Stopwatch.StartNew();

        private SystemInfo _systemInfo = new SystemInfo();
        private object? _currentView;
        private string _currentViewTitle = "Dashboard";
        private string _currentPageKey = "Dashboard";
        private bool _isGameModeActive;
        private string _statusMessage = "Ready.";
        private bool _hasUnsavedChanges;
        private bool _isLiveMonitoringEnabled = true;
        private DateTime _lastRefresh = DateTime.MinValue;

        #endregion

        #region Construction

        public MainViewModel()
        {
            _engine = new OptimizationEngine(AppConfig.Load(), LoggerFactory.GetLogger());

            Dashboard = new DashboardViewModel(_engine);
            Processes = new ProcessesViewModel(_engine);
            Optimization = new OptimizationViewModel(_engine);
            Startup = new StartupViewModel(_engine);
            Services = new ServicesViewModel(_engine);
            GameMode = new GameModeViewModel(_engine);
            GameAppOptimizer = new GameAppOptimizerViewModel(_engine);
            History = new HistoryViewModel(_engine);
            Settings = new SettingsViewModel(_engine);
            About = new AboutViewModel(_engine);

            foreach (var child in AllPages)
            {
                child.NavigationRequested += (_, key) => Navigate(key);
            }

            NavigateCommand = new RelayCommand<string>(Navigate);
            AnalyzeCommand = new AsyncRelayCommand(AnalyzeAsync);
            SmartOptimizeCommand = new AsyncRelayCommand(SmartOptimizeAsync, () => !IsBusy);
            ToggleGameModeCommand = new AsyncRelayCommand(ToggleGameModeAsync);
            UndoLastCommand = new AsyncRelayCommand(UndoAsync, () => _engine.CanUndo);
            RefreshCommand = new AsyncRelayCommand(RefreshAsync);
            OpenLogFolderCommand = new RelayCommand(OpenLogFolder);

            CurrentView = Dashboard;

            // Live monitoring: refreshes cheap metrics a few times per second.
            _liveTimer = new DispatcherTimer(DispatcherPriority.Background)
            {
                Interval = TimeSpan.FromSeconds(2)
            };
            _liveTimer.Tick += async (_, _) => await SampleMetricsAsync();

            _liveTimer.Start();

            // First full scan runs in the background so the window appears immediately.
            _ = AnalyzeAsync();
        }

        #endregion

        #region Child view models

        public DashboardViewModel Dashboard { get; }
        public ProcessesViewModel Processes { get; }
        public OptimizationViewModel Optimization { get; }
        public StartupViewModel Startup { get; }
        public ServicesViewModel Services { get; }
        public GameModeViewModel GameMode { get; }
        public GameAppOptimizerViewModel GameAppOptimizer { get; }
        public HistoryViewModel History { get; }
        public SettingsViewModel Settings { get; }
        public AboutViewModel About { get; }

        private IEnumerable<BaseViewModel> AllPages
        {
            get
            {
                yield return Dashboard;
                yield return Processes;
                yield return Optimization;
                yield return Startup;
                yield return Services;
                yield return GameMode;
                yield return GameAppOptimizer;
                yield return History;
                yield return Settings;
                yield return About;
            }
        }

        #endregion

        #region Commands

        public RelayCommand<string> NavigateCommand { get; }
        public AsyncRelayCommand AnalyzeCommand { get; }
        public AsyncRelayCommand SmartOptimizeCommand { get; }
        public AsyncRelayCommand ToggleGameModeCommand { get; }
        public AsyncRelayCommand UndoLastCommand { get; }
        public AsyncRelayCommand RefreshCommand { get; }
        public RelayCommand OpenLogFolderCommand { get; }

        #endregion

        #region Shell state

        /// <summary>Currently hosted page view model.</summary>
        public object? CurrentView
        {
            get => _currentView;
            private set => SetProperty(ref _currentView, value);
        }

        /// <summary>Title shown in the custom title bar.</summary>
        public string CurrentViewTitle
        {
            get => _currentViewTitle;
            private set => SetProperty(ref _currentViewTitle, value);
        }

        /// <summary>Key of the active page (used by the navigation radio buttons).</summary>
        public string CurrentPageKey
        {
            get => _currentPageKey;
            private set
            {
                if (SetProperty(ref _currentPageKey, value))
                    RaiseNavigationFlags();
            }
        }

        public bool IsDashboardView => CurrentPageKey == "Dashboard";
        public bool IsSystemInfoView => CurrentPageKey == "SystemInfo";
        public bool IsProcessesView => CurrentPageKey == "Processes";
        public bool IsOptimizationView => CurrentPageKey == "Optimization";
        public bool IsStartupView => CurrentPageKey == "Startup";
        public bool IsServicesView => CurrentPageKey == "Services";
        public bool IsGameModeView => CurrentPageKey == "GameMode";
        public bool IsGameAppOptimizerView => CurrentPageKey == "GameAppOptimizer";
        public bool IsHistoryView => CurrentPageKey == "History";
        public bool IsSettingsView => CurrentPageKey == "Settings";
        public bool IsAboutView => CurrentPageKey == "About";

        /// <summary>Latest full system snapshot.</summary>
        public SystemInfo SystemInfo
        {
            get => _systemInfo;
            private set => SetProperty(ref _systemInfo, value);
        }

        /// <summary>User name shown in the navigation pane.</summary>
        public string UserName => Environment.UserName;

        /// <summary>Short machine description shown under the user name.</summary>
        public string SystemSummary =>
            $"{Environment.MachineName} \u2022 {Environment.ProcessorCount} threads \u2022 " +
            $"{MemoryBreakdown.Format(SystemInfo.TotalPhysicalMemory)} RAM";

        /// <summary>True while Game Mode is applied.</summary>
        public bool IsGameModeActive
        {
            get => _isGameModeActive;
            private set
            {
                if (SetProperty(ref _isGameModeActive, value))
                    OnPropertyChanged(nameof(GameModeButtonText));
            }
        }

        public string GameModeButtonText => IsGameModeActive ? "Exit Game Mode" : "Enter Game Mode";

        /// <summary>Status bar text.</summary>
        public string StatusMessage
        {
            get => _statusMessage;
            set => SetProperty(ref _statusMessage, value);
        }

        /// <summary>True when a page has unsaved edits (drives the close confirmation).</summary>
        public bool HasUnsavedChanges
        {
            get => _hasUnsavedChanges;
            set => SetProperty(ref _hasUnsavedChanges, value);
        }

        /// <summary>Whether the 2-second live sampling timer is running.</summary>
        public bool IsLiveMonitoringEnabled
        {
            get => _isLiveMonitoringEnabled;
            set
            {
                if (SetProperty(ref _isLiveMonitoringEnabled, value))
                {
                    if (value) _liveTimer.Start();
                    else _liveTimer.Stop();
                }
            }
        }

        /// <summary>Uptime of the optimiser itself (spec: it must stay light, so we surface its own cost).</summary>
        public string OptimizerResourceUsage
        {
            get
            {
                try
                {
                    using (var process = Process.GetCurrentProcess())
                    {
                        return $"Optimizer: {process.WorkingSet64 / (1024.0 * 1024):F0} MB " +
                               $"\u2022 {_uptime.Elapsed:mm\\:ss} uptime";
                    }
                }
                catch
                {
                    return string.Empty;
                }
            }
        }

        /// <summary>Whether the application is running elevated (shown in the status bar).</summary>
        public bool IsElevated => WindowsApiHelper.IsAdministrator();

        public string ElevationText => IsElevated
            ? "Administrator"
            : "Standard user (some optimisations will ask for elevation)";

        #endregion

        #region Navigation

        /// <summary>Switch to a page by key.</summary>
        public void Navigate(string? pageKey)
        {
            if (string.IsNullOrWhiteSpace(pageKey)) return;

            var page = pageKey.Trim();

            switch (page)
            {
                case "Dashboard":
                    CurrentView = Dashboard;
                    CurrentViewTitle = "Dashboard";
                    break;

                case "Processes":
                    CurrentView = Processes;
                    CurrentViewTitle = "Processes";
                    _ = Processes.RefreshAsync();
                    break;

                case "Optimization":
                case "SystemInfo":
                    // "System Info" shares the optimisation page (memory breakdown lives there).
                    CurrentView = Optimization;
                    CurrentViewTitle = page == "SystemInfo" ? "System Information" : "Optimization";
                    _ = Optimization.RefreshSystemInfoAsync();
                    break;

                case "Startup":
                    CurrentView = Startup;
                    CurrentViewTitle = "Start-up Programs";
                    _ = Startup.RefreshAsync();
                    break;

                case "Services":
                    CurrentView = Services;
                    CurrentViewTitle = "Windows Services";
                    _ = Services.RefreshAsync();
                    break;

                case "GameMode":
                    CurrentView = GameMode;
                    CurrentViewTitle = "Game Mode";
                    break;

                case "GameAppOptimizer":
                    CurrentView = GameAppOptimizer;
                    CurrentViewTitle = "Game & App Optimizer";
                    _ = GameAppOptimizer.LoadAsync();
                    break;

                case "History":
                    CurrentView = History;
                    CurrentViewTitle = "Optimisation History";
                    History.Refresh();
                    break;

                case "Settings":
                    CurrentView = Settings;
                    CurrentViewTitle = "Settings";
                    Settings.Reload();
                    break;

                case "About":
                    CurrentView = About;
                    CurrentViewTitle = "About";
                    break;

                default:
                    Logger.Warning("MainViewModel", $"Unknown navigation target '{page}'");
                    return;
            }

            CurrentPageKey = page == "SystemInfo" ? "Optimization" : page;
            StatusMessage = $"Viewing {CurrentViewTitle}";
        }

        private void RaiseNavigationFlags()
        {
            OnPropertyChanged(nameof(IsDashboardView));
            OnPropertyChanged(nameof(IsSystemInfoView));
            OnPropertyChanged(nameof(IsProcessesView));
            OnPropertyChanged(nameof(IsOptimizationView));
            OnPropertyChanged(nameof(IsStartupView));
            OnPropertyChanged(nameof(IsServicesView));
            OnPropertyChanged(nameof(IsGameModeView));
            OnPropertyChanged(nameof(IsGameAppOptimizerView));
            OnPropertyChanged(nameof(IsHistoryView));
            OnPropertyChanged(nameof(IsSettingsView));
            OnPropertyChanged(nameof(IsAboutView));
        }

        #endregion

        #region Operations

        /// <summary>Full scan, then push results to every page.</summary>
        public async Task AnalyzeAsync()
        {
            await RunGuardedAsync("Analysing the system...", async () =>
            {
                StatusMessage = "Scanning processes, services, start-up items and hardware...";

                var info = await _engine.ScanAsync().ConfigureAwait(true);

                SystemInfo = info;
                _lastRefresh = DateTime.Now;

                PublishSystemInfo(info);

                StatusMessage = info.NeedsOptimization
                    ? $"Scan complete - {info.Processes.Count} processes, RAM {info.RamUsagePercentage:F1}%, " +
                      $"health score {info.SystemHealthScore}/100."
                    : $"Scan complete - the system is already well optimised (health score {info.SystemHealthScore}/100).";

                // The undo button becomes available/disappears based on engine state.
                UndoLastCommand.RaiseCanExecuteChanged();
                SmartOptimizeCommand.RaiseCanExecuteChanged();
            });
        }

        private void PublishSystemInfo(SystemInfo info)
        {
            Dashboard.ApplySystemInfo(info);
            Processes.ApplySystemInfo(info);
            Optimization.ApplySystemInfo(info);
            Startup.ApplySystemInfo(info);
            Services.ApplySystemInfo(info);
            GameMode.ApplySystemInfo(info);
            History.Refresh();
            OnPropertyChanged(nameof(SystemSummary));
        }

        /// <summary>Cheap metric refresh for the live dashboard.</summary>
        private async Task SampleMetricsAsync()
        {
            // The two-second tick must NEVER block the UI thread. v1.0.0 sampled the counters
            // synchronously here, so one stuck Windows reading froze the whole window. The sample
            // now runs on a worker thread, and a tick that finds the previous sample still in
            // flight is simply skipped.
            if (IsBusy) return;
            if (Interlocked.CompareExchange(ref _sampleInFlight, 1, 0) != 0) return;

            try
            {
                var sample = await Task.Run(() => _engine.SampleMetrics()).ConfigureAwait(true);

                // Only the live values are replaced; the full snapshot stays as-is.
                Dashboard.ApplyLiveSample(sample);
            }
            catch (Exception ex)
            {
                Logger.Warning("MainViewModel", "Live metric sampling failed", null, ex);
            }
            finally
            {
                Interlocked.Exchange(ref _sampleInFlight, 0);
            }
        }

        /// <summary>Refresh everything.</summary>
        private async Task RefreshAsync()
        {
            await AnalyzeAsync();
        }

        /// <summary>
        /// One-click "Smart Optimize": builds a conservative plan and asks the user to confirm it.
        /// Nothing is executed without the explicit confirmation step in the preview dialog.
        /// </summary>
        private async Task SmartOptimizeAsync()
        {
            await RunGuardedAsync("Building a safe optimisation plan...", async () =>
            {
                var plan = await _engine.CreateQuickPlanAsync(SystemInfo).ConfigureAwait(true);

                if (plan == null || plan.Actions.Count == 0)
                {
                    StatusMessage = "No safe optimisation was possible right now - nothing was changed.";
                    MessageBox.Show(
                        "Nothing to optimise.\n\n" +
                        "Every candidate was either protected (Windows components, drivers, security) " +
                        "or currently in use. This application will not close programs you are using " +
                        "and will not disable Windows features to make a number look better.",
                        "AI System Optimizer",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                    return;
                }

                // Hand the plan to the preview page and switch to it.
                Optimization.LoadPlan(plan);
                Navigate("Optimization");

                IsGameModeActive = plan.Mode == OptimizationMode.GameMode;
                UndoLastCommand.RaiseCanExecuteChanged();
            });
        }

        /// <summary>Toggle Game Mode: build and preview a game-session plan.</summary>
        private async Task ToggleGameModeAsync()
        {
            if (IsGameModeActive)
            {
                IsGameModeActive = false;
                StatusMessage = "Game Mode disabled. Closed applications can be restarted normally.";
                return;
            }

            await RunGuardedAsync("Detecting a running game...", async () =>
            {
                var plan = await _engine.CreatePlanAsync(OptimizationMode.GameMode, SystemInfo).ConfigureAwait(true);

                if (plan == null || plan.Actions.Count == 0)
                {
                    var game = _engine.FindGameProcess(SystemInfo);

                    MessageBox.Show(
                        game == null
                            ? "No running game was detected.\n\nStart your game first, then enable Game Mode so the " +
                              "optimiser can raise the game's priority and pause background applications."
                            : $"Game detected: {game.DisplayName}, but there is nothing safe to optimise - " +
                              "the machine is already in good shape for gaming.",
                        "AI System Optimizer - Game Mode",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                    return;
                }

                Optimization.LoadPlan(plan);
                Navigate("Optimization");
                StatusMessage = "Game Mode plan prepared - review it, then choose Optimize.";
            });
        }

        /// <summary>Undo the last optimisation.</summary>
        private async Task UndoAsync()
        {
            var confirm = MessageBox.Show(
                "Undo the last optimisation?\n\n" +
                "Start-up entries that were disabled will be restored and services that were stopped " +
                "will be started again. Applications that were closed must be reopened manually - " +
                "Windows does not allow an application to be restarted exactly as it was.",
                "Undo last optimisation",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes)
                return;

            await RunGuardedAsync("Undoing the last optimisation...", async () =>
            {
                var result = await _engine.UndoLastOptimizationAsync().ConfigureAwait(true);

                StatusMessage = result.IsSuccessful
                    ? $"Undo complete: {result.SuccessfulCount} action(s) reverted."
                    : $"Undo finished with {result.FailedCount} failure(s): {result.ErrorMessage}";

                await AnalyzeAsync();
                UndoLastCommand.RaiseCanExecuteChanged();
            });
        }

        private void OpenLogFolder()
        {
            try
            {
                var path = Constants_LogDirectory;

                if (!System.IO.Directory.Exists(path))
                    System.IO.Directory.CreateDirectory(path);

                Process.Start(new ProcessStartInfo
                {
                    FileName = path,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                StatusMessage = $"Could not open the log folder: {ex.Message}";
            }
        }

        private static string Constants_LogDirectory => Core.Constants.AppConstants.LogDirectoryPath;

        #endregion

        #region Disposal

        protected override void Dispose(bool disposing)
        {
            if (!disposing) return;

            try
            {
                _liveTimer.Stop();

                foreach (var page in AllPages.OfType<IDisposable>())
                {
                    page.Dispose();
                }

                _engine.Dispose();
            }
            catch { }
        }

        #endregion
    }
}

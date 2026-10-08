using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Game Mode page. Explains exactly what Game Mode does and does not do, detects a running
    /// game, and prepares the game-session plan.
    ///
    /// Guarantees surfaced in the UI:
    ///   * Windows Defender / firewall stay on.
    ///   * Drivers are never touched.
    ///   * Windows Update is never crippled.
    ///   * Start-up entries are not modified by Game Mode.
    ///   * The game's priority is raised only to AboveNormal.
    /// </summary>
    public sealed class GameModeViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private SystemInfo _systemInfo = new SystemInfo();
        private ProcessInfo? _detectedGame;
        private ObservableCollection<ProcessInfo> _gameCandidates = new();
        private ObservableCollection<ProcessInfo> _backgroundCandidates = new();
        private bool _boostGamePriority = true;
        private bool _closeLaunchers = true;
        private bool _pauseCloudSync = true;
        private string _statusText = "No game detected.";

        #endregion

        #region Construction

        public GameModeViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            DetectGameCommand = new AsyncRelayCommand(DetectGameAsync, () => !IsBusy);
            PreparePlanCommand = new AsyncRelayCommand(PreparePlanAsync, () => !IsBusy);
        }

        #endregion

        #region State

        /// <summary>Latest snapshot.</summary>
        public SystemInfo SystemInfo
        {
            get => _systemInfo;
            private set => SetProperty(ref _systemInfo, value);
        }

        /// <summary>The game we believe is running (null when none).</summary>
        public ProcessInfo? DetectedGame
        {
            get => _detectedGame;
            private set
            {
                if (SetProperty(ref _detectedGame, value))
                {
                    OnPropertyChanged(nameof(HasDetectedGame));
                    OnPropertyChanged(nameof(GameSummary));
                }
            }
        }

        public bool HasDetectedGame => DetectedGame != null;

        /// <summary>Summary of the detected game.</summary>
        public string GameSummary => DetectedGame == null
            ? "No game detected. Start the game first, then press Detect."
            : $"{DetectedGame.DisplayName} (PID {DetectedGame.Id}) \u2022 {DetectedGame.FormattedWorkingSet} RAM \u2022 " +
              $"priority {DetectedGame.PriorityClass}";

        /// <summary>Programs that would be paused for the game session.</summary>
        public ObservableCollection<ProcessInfo> BackgroundCandidates
        {
            get => _backgroundCandidates;
            private set => SetProperty(ref _backgroundCandidates, value);
        }

        /// <summary>Processes that look like games (for manual selection).</summary>
        public ObservableCollection<ProcessInfo> GameCandidates
        {
            get => _gameCandidates;
            private set => SetProperty(ref _gameCandidates, value);
        }

        /// <summary>Status line for the page.</summary>
        public string StatusText
        {
            get => _statusText;
            private set => SetProperty(ref _statusText, value);
        }

        /// <summary>Raise the game's priority (AboveNormal only).</summary>
        public bool BoostGamePriority
        {
            get => _boostGamePriority;
            set => SetProperty(ref _boostGamePriority, value);
        }

        /// <summary>Close launchers and stores during the session.</summary>
        public bool CloseLaunchers
        {
            get => _closeLaunchers;
            set => SetProperty(ref _closeLaunchers, value);
        }

        /// <summary>Pause cloud sync clients during the session.</summary>
        public bool PauseCloudSync
        {
            get => _pauseCloudSync;
            set => SetProperty(ref _pauseCloudSync, value);
        }

        /// <summary>Total memory the pause candidates hold.</summary>
        public string PotentialRecoveryText =>
            $"Pausing these would free about {MemoryBreakdown.Format(BackgroundCandidates.Sum(p => p.WorkingSet))} " +
            "(measured working sets).";

        /// <summary>Explicit statement of the Game Mode guarantees.</summary>
        public List<string> Guarantees { get; } = new()
        {
            "Windows Defender real-time protection stays ON.",
            "The Windows firewall stays ON.",
            "Hardware drivers and their helpers are never touched.",
            "Windows Update is never disabled or blocked.",
            "Start-up entries are not modified - this is a session-only change.",
            "The game priority is raised to AboveNormal at most (never High or RealTime).",
            "CPU affinity is only changed if you explicitly enable it, and Windows keeps managing the scheduler."
        };

        #endregion

        #region Commands

        public AsyncRelayCommand DetectGameCommand { get; }
        public AsyncRelayCommand PreparePlanCommand { get; }

        #endregion

        #region Data

        /// <summary>Apply a scan result.</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            SystemInfo = info;

            // A game guess is only offered for processes with a window (i.e. actually running in front).
            var candidates = info.Processes
                .Where(p => !p.IsWindowsProcess && !p.IsService && !p.IsDriver)
                .Where(p => ProcessHelper.IsGameProcess(p))
                .OrderByDescending(p => p.WorkingSet)
                .ToList();

            GameCandidates = new ObservableCollection<ProcessInfo>(candidates);

            DetectedGame = candidates.FirstOrDefault(p => p.HasVisibleWindow) ?? candidates.FirstOrDefault();

            BackgroundCandidates = new ObservableCollection<ProcessInfo>(
                info.Processes
                    .Where(p => !p.IsWindowsProcess && !p.IsDriver && !p.IsService)
                    .Where(p => !p.IsActive && !p.HasVisibleWindow)
                    .Where(p => p.WorkingSet >= 50 * 1024 * 1024)
                    .OrderByDescending(p => p.WorkingSet)
                    .Take(15));

            OnPropertyChanged(nameof(PotentialRecoveryText));

            StatusText = DetectedGame == null
                ? "No game detected yet."
                : $"Game detected: {DetectedGame.DisplayName}.";
        }

        #endregion

        #region Actions

        private async Task DetectGameAsync()
        {
            await RunGuardedAsync("Looking for a running game...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);
                ApplySystemInfo(info);

                StatusText = DetectedGame == null
                    ? "No game detected. Games installed outside the common folders may not be recognised - " +
                      "you can still run a normal optimisation while playing."
                    : $"Game detected: {DetectedGame.DisplayName}. Press 'Prepare Game Plan' to review " +
                      "the session optimisation.";
            });
        }

        private async Task PreparePlanAsync()
        {
            await RunGuardedAsync("Preparing the game session plan...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);
                ApplySystemInfo(info);

                var plan = await _engine.CreatePlanAsync(OptimizationMode.GameMode, info).ConfigureAwait(true);

                if (plan == null || plan.Actions.Count == 0)
                {
                    StatusText = "Nothing safe to change for this session - the system is already in good shape.";
                    return;
                }

                // Honour the user's toggles: drop the categories they disabled.
                var filtered = plan.Actions.Where(action =>
                {
                    if (action.ActionType == OptimizationActionType.ChangePriority && !BoostGamePriority)
                        return false;

                    if (action.ActionType == OptimizationActionType.CloseProcess)
                    {
                        var name = action.Target.ToLowerInvariant();

                        var isLauncher = name.Contains("steam") || name.Contains("epic") ||
                                         name.Contains("origin") || name.Contains("uplay") ||
                                         name.Contains("battle") || name.Contains("galaxy") ||
                                         name.Contains("gog") || name.Contains("riot");

                        var isCloudSync = name.Contains("onedrive") || name.Contains("dropbox") ||
                                          name.Contains("drive") || name.Contains("nextcloud");

                        if (isLauncher && !CloseLaunchers) return false;
                        if (isCloudSync && !PauseCloudSync) return false;
                    }

                    return true;
                }).ToList();

                plan.Actions.Clear();
                plan.Actions.AddRange(filtered);

                if (plan.Actions.Count == 0)
                {
                    StatusText = "With the current settings there is nothing to change. " +
                                 "Enable launcher or cloud-sync handling, or boost the game priority.";
                    return;
                }

                PlanPrepared?.Invoke(this, plan);
                StatusText = $"Game plan ready: {plan.Actions.Count} action(s), " +
                             $"{plan.FormattedEstimatedRamRecovery} recoverable.";
            });
        }

        /// <summary>Raised with a plan the shell should display on the optimisation page.</summary>
        public event EventHandler<OptimizationPlan>? PlanPrepared;

        #endregion
    }
}

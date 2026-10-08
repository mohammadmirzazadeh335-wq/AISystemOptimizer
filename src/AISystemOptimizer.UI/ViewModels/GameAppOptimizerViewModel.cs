using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;
using Microsoft.Win32;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// One application shown as a card.
    ///
    /// A card owns no behaviour of its own beyond what the user clicks: it reads the current state and
    /// asks the page to act. Everything that changes the machine happens in Core, through the existing
    /// safety pipeline.
    /// </summary>
    public sealed class GameAppCardViewModel : BaseViewModel
    {
        private readonly GameAppOptimizerViewModel _page;

        private ApplicationRunState _runState = ApplicationRunState.NotRunning;
        private List<ApplicationRunInfo> _instances = new List<ApplicationRunInfo>();
        private ApplicationHealth _health = new ApplicationHealth();
        private bool _isChecking;
        private string _statusDetail = string.Empty;
        private string _performanceSummary = "Not measured yet.";

        public GameAppCardViewModel(GameAppProfile profile, GameAppOptimizerViewModel page)
        {
            Profile = profile;
            _page = page;

            OptimizeCommand = new AsyncRelayCommand(() => _page.OptimizeAsync(this), () => !page.IsBusy);
            LaunchCommand = new RelayCommand(() => _page.Launch(this), () => CanLaunch);
            RemoveCommand = new AsyncRelayCommand(() => _page.RemoveAsync(this), () => !page.IsBusy);
            OpenProfileCommand = new RelayCommand(() => _page.OpenProfile(this));
        }

        public GameAppProfile Profile { get; }

        public Guid ApplicationId => Profile.ApplicationId;

        public string DisplayName => Profile.ResolveDisplayName();

        public string ExecutablePath => Profile.ExecutablePath;

        public string FileName => Profile.FileName;

        /// <summary>The mode the profile will apply, in words.</summary>
        public string ProfileModeText => Profile.ProfileMode.ToString();

        public string KindText => Profile.Kind == ApplicationKind.Unknown
            ? "Not specified"
            : Profile.Kind.ToString();

        public string PublisherText => string.IsNullOrWhiteSpace(Profile.Identity?.Publisher)
            ? "Publisher not recorded"
            : Profile.Identity!.Publisher;

        public string SignatureText => Profile.Identity?.Signature switch
        {
            SignatureVerdict.Valid => "Signature: valid",
            SignatureVerdict.Invalid => "Signature: does not verify",
            SignatureVerdict.Unsigned => "Signature: unsigned (not evidence of harm)",
            _ => "Signature: unknown"
        };

        public string ArchitectureText => string.IsNullOrWhiteSpace(Profile.Identity?.Architecture)
            ? "Architecture: unknown"
            : "Architecture: " + Profile.Identity!.Architecture;

        public string FileSizeText => Profile.Identity == null || Profile.Identity.FileSizeBytes <= 0
            ? "Size: N/A"
            : $"Size: {Profile.Identity.FileSizeBytes / (1024.0 * 1024.0):F1} MB";

        public string HashText => string.IsNullOrWhiteSpace(Profile.Identity?.Sha256)
            ? "SHA-256: not recorded"
            : "SHA-256: " + Profile.Identity!.Sha256!.Substring(0, Math.Min(16, Profile.Identity.Sha256!.Length)) + "…";

        /// <summary>The status line, which is what the specification asks the card to show live.</summary>
        public string StatusText => _runState switch
        {
            ApplicationRunState.Running when _instances.Count == 1 => $"● Running · PID {_instances[0].ProcessId}",
            ApplicationRunState.Running => $"● Running · {_instances.Count} instances · PID {string.Join(", ", _instances.Select(i => i.ProcessId))}",
            ApplicationRunState.Unconfirmed => "Running (identity not confirmed)",
            _ => "Not Running"
        };

        public string StatusDetail
        {
            get => _statusDetail;
            private set => SetProperty(ref _statusDetail, value);
        }

        public bool IsRunning => _runState == ApplicationRunState.Running;

        public bool CanLaunch => Profile.Behavior.OnLaunch != ProfileStartupBehavior.Nothing || true;

        /// <summary>Plain-language health, so a suspended profile is obvious on the card.</summary>
        public string HealthText => _health.Summary;

        public bool HealthIsProblem => _health.State is not (ApplicationHealthState.Healthy or ApplicationHealthState.NotChecked);

        public List<string> HealthFindings => _health.Findings;

        public string PerformanceSummary
        {
            get => _performanceSummary;
            private set => SetProperty(ref _performanceSummary, value);
        }

        public bool IsChecking
        {
            get => _isChecking;
            private set => SetProperty(ref _isChecking, value);
        }

        public AsyncRelayCommand OptimizeCommand { get; }
        public RelayCommand LaunchCommand { get; }
        public AsyncRelayCommand RemoveCommand { get; }
        public RelayCommand OpenProfileCommand { get; }

        /// <summary>
        /// Re-read everything this card shows. Called on a timer, so it must stay cheap: the running
        /// check compares paths from the process list, and the hash is only recomputed when asked.
        /// </summary>
        public void Refresh(ApplicationRunState state, List<ApplicationRunInfo> instances, ApplicationHealth health)
        {
            _runState = state;
            _instances = instances ?? new List<ApplicationRunInfo>();
            _health = health ?? new ApplicationHealth();

            StatusDetail = _instances.Count > 0
                ? string.Join("  ", _instances.Select(i => i.Describe()))
                : (health?.Findings.Count > 0 ? health!.Findings[0] : "No matching process is running.");

            OnPropertyChanged(nameof(StatusText));
            OnPropertyChanged(nameof(IsRunning));
            OnPropertyChanged(nameof(HealthText));
            OnPropertyChanged(nameof(HealthIsProblem));
            OnPropertyChanged(nameof(HealthFindings));
            OnPropertyChanged(nameof(PerformanceSummary));
        }

        public void DescribePerformance(string text) => PerformanceSummary = text;

        public IReadOnlyList<ApplicationRunInfo> Instances => _instances;

        public ApplicationHealth Health => _health;
    }

    /// <summary>
    /// The Game &amp; App Optimizer page.
    ///
    /// What it does: lists applications, inspects them, shows what an optimisation would do, applies it
    /// through the existing safety pipeline and puts it back afterwards.
    ///
    /// What it deliberately does not do, and never will:
    ///   * execute a selected file in order to inspect it;
    ///   * close a process by name without checking its identity, its windows and the protected lists;
    ///   * empty working sets, clear caches, touch the standby list, defragment anything, or promise a
    ///     memory percentage it cannot reach safely;
    ///   * claim a frames-per-second improvement, since no FPS source exists;
    ///   * apply anything automatically: automatic optimisation is off by default and opt-in per profile.
    /// </summary>
    public sealed class GameAppOptimizerViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private readonly GameAppProfileService _profiles;
        private readonly GameAppSessionManager _sessions;
        private readonly GameAppActionPlanner _planner;
        private readonly ExecutableInspector _inspector;
        private readonly NeverOptimizeStore _neverOptimizeStore;
        private readonly GameAppAiAdvisor _aiAdvisor;

        private readonly ObservableCollection<GameAppCardViewModel> _cards = new();
        private readonly List<NeverOptimizeEntry> _neverOptimize = new();

        private GameAppCardViewModel? _selectedCard;
        private OptimizationPotentialResult? _score;
        private GameAppMemoryBreakdown _memory = new GameAppMemoryBreakdown();
        private RamOptimizationAdvice? _ramAdvice;
        private SystemInfo _systemInfo = new SystemInfo();

        private string _area = "MyApps";
        private string _statusMessage = "Loading application profiles...";
        private string _actionLog = string.Empty;
        private bool _isRefreshing;
        private DateTime _lastRefreshUtc = DateTime.MinValue;
        private bool _aiAnalysisRunning;

        #endregion

        #region Construction

        public GameAppOptimizerViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            _profiles = new GameAppProfileService(engine.Logger);
            _planner = new GameAppActionPlanner(engine.Logger);
            _inspector = new ExecutableInspector(engine.Logger);
            _neverOptimizeStore = new NeverOptimizeStore(engine.Logger);
            _aiAdvisor = new GameAppAiAdvisor(engine.Logger);
            _sessions = new GameAppSessionManager(
                engine.Logger,
                engine.Config,
                profiles: _profiles);

            AddApplicationCommand = new AsyncRelayCommand(AddApplicationAsync, () => !IsBusy);
            RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
            OptimizeSelectedCommand = new AsyncRelayCommand(() => OptimizeAsync(SelectedCard), () => !IsBusy && SelectedCard != null);
            EndSessionCommand = new AsyncRelayCommand(EndSessionAsync, () => _sessions.HasActiveSession);
            RestoreInterruptedCommand = new AsyncRelayCommand(RestoreInterruptedAsync, () => InterruptedSessions.Count > 0);
            DismissInterruptedCommand = new RelayCommand(DismissInterrupted, () => InterruptedSessions.Count > 0);
            ShowAreaCommand = new RelayCommand<string>(area => Area = area ?? "MyApps");
            AnalyzeWithAiCommand = new AsyncRelayCommand(AnalyzeWithAiAsync, () => !IsBusy && SelectedCard != null);
            ShowInterruptedDetailsCommand = new RelayCommand(() =>
                MessageBox.Show(
                    InterruptedDescription,
                    "An optimization session was interrupted",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning));
        }

        #endregion

        #region State

        public ObservableCollection<GameAppCardViewModel> Cards => _cards;

        public ObservableCollection<GameAppSession> InterruptedSessions { get; } = new();

        public GameAppCardViewModel? SelectedCard
        {
            get => _selectedCard;
            set
            {
                if (SetProperty(ref _selectedCard, value))
                {
                    OnPropertyChanged(nameof(HasSelection));
                    RaiseCommands();
                }
            }
        }

        public bool HasSelection => SelectedCard != null;

        /// <summary>My Games &amp; Apps / Running / Profiles / Benchmarks / History.</summary>
        public string Area
        {
            get => _area;
            set
            {
                if (SetProperty(ref _area, value ?? "MyApps"))
                {
                    OnPropertyChanged(nameof(IsMyAppsArea));
                    OnPropertyChanged(nameof(IsRunningArea));
                    OnPropertyChanged(nameof(IsProfilesArea));
                    OnPropertyChanged(nameof(IsBenchmarksArea));
                    OnPropertyChanged(nameof(IsHistoryArea));
                }
            }
        }

        public bool IsMyAppsArea => Area == "MyApps";
        public bool IsRunningArea => Area == "Running";
        public bool IsProfilesArea => Area == "Profiles";
        public bool IsBenchmarksArea => Area == "Benchmarks";
        public bool IsHistoryArea => Area == "History";

        public string StatusMessage
        {
            get => _statusMessage;
            private set => SetProperty(ref _statusMessage, value);
        }

        /// <summary>A running account of what this page has done, in order. Never a summary that hides a refusal.</summary>
        public string ActionLog
        {
            get => _actionLog;
            private set => SetProperty(ref _actionLog, value);
        }

        public bool IsRefreshing
        {
            get => _isRefreshing;
            private set => SetProperty(ref _isRefreshing, value);
        }

        public bool HasApplications => _cards.Count > 0;

        public bool HasNoApplications => _cards.Count == 0;

        public bool HasInterruptedSession => InterruptedSessions.Count > 0;

        public string InterruptedDescription { get; private set; } = string.Empty;

        /// <summary>The optimisation potential score, with every component behind it.</summary>
        public string PotentialText => _score == null
            ? "Not measured yet."
            : $"{_score.Score}/100";

        public string PotentialSummary => _score?.Summary ?? "Open this page with a profile running to see what could be gained.";

        public List<string> PotentialBreakdown => _score?.Breakdown ?? new List<string>();

        /// <summary>The memory figures, with used / available / cached kept apart.</summary>
        public List<string> MemoryLines => _memory.Describe();

        public string RamTargetText => _ramAdvice?.Summary ?? "No target is set. A target is shown, never promised.";

        public List<string> RamStatements => _ramAdvice?.Statements ?? new List<string>();

        public string SessionText => _sessions.ActiveSession == null
            ? "No optimisation session is running."
            : _sessions.ActiveSession.Describe();

        public bool HasActiveSession => _sessions.HasActiveSession;

        public string SafeOptimizationLimitText => RamOptimizationAdvisor.SafeLimitReached;

        /// <summary>What the current profile would do, before it does it.</summary>
        public string PlanPreview { get; private set; } = "Select an application to see what a profile would do.";

        public RelayCommand<string> ShowAreaCommand { get; }
        public AsyncRelayCommand AddApplicationCommand { get; }
        public AsyncRelayCommand RefreshCommand { get; }
        public AsyncRelayCommand OptimizeSelectedCommand { get; }
        public AsyncRelayCommand EndSessionCommand { get; }
        public AsyncRelayCommand RestoreInterruptedCommand { get; }
        public RelayCommand DismissInterruptedCommand { get; }
        public RelayCommand ShowInterruptedDetailsCommand { get; }
        public AsyncRelayCommand AnalyzeWithAiCommand { get; }

        #endregion

        #region Loading

        /// <summary>
        /// Load profiles and check them against the executables on disk. Called when the page is opened
        /// and whenever the user asks.
        /// </summary>
        public async Task LoadAsync()
        {
            await RunGuardedAsync("Loading application profiles...", async () =>
            {
                _profiles.Reload();

                _cards.Clear();

                foreach (var profile in _profiles.Profiles)
                {
                    var card = new GameAppCardViewModel(profile, this);
                    _cards.Add(card);
                }

                OnPropertyChanged(nameof(HasApplications));
                OnPropertyChanged(nameof(HasNoApplications));

                foreach (var entry in _neverOptimizeStore.Load())
                    _neverOptimize.Add(entry);

                DetectInterruptedSessions();

                await RefreshAsync().ConfigureAwait(true);

                StatusMessage = _cards.Count == 0
                    ? "No applications yet. Use \"+ Add Game / App\" to choose an executable."
                    : $"{_cards.Count} application profile(s) loaded from {_profiles.StoreDirectory}.";
            }).ConfigureAwait(true);
        }

        /// <summary>
        /// Update each card: running state, identity check and the memory picture.
        /// </summary>
        public async Task RefreshAsync()
        {
            if (_isRefreshing)
                return;

            // The timer fires often; a full hash of every profile is expensive, so it is done on the
            // first pass and when the user asks explicitly.
            var fullCheck = DateTime.UtcNow - _lastRefreshUtc > TimeSpan.FromSeconds(30);

            IsRefreshing = true;

            try
            {
                var systemInfo = await _engine.ScanAsync().ConfigureAwait(true);

                _systemInfo = systemInfo;

                foreach (var card in _cards)
                {
                    var state = _inspector.DetectRunningState(
                        card.ExecutablePath, out var instances, out _);

                    var health = fullCheck
                        ? _profiles.CheckHealth(card.Profile)
                        : new ApplicationHealth { State = ApplicationHealthState.NotChecked };

                    card.Refresh(state, instances, health);

                    if (card.Profile.LastKnownHealth != health.State)
                        card.Profile.LastKnownHealth = health.State;
                }

                _lastRefreshUtc = DateTime.UtcNow;

                UpdateMemoryAndScore(systemInfo);

                RaiseCommands();
            }
            catch (Exception exception)
            {
                ErrorMessage = $"The application list could not be refreshed: {exception.Message}";
            }
            finally
            {
                IsRefreshing = false;
            }
        }

        private void UpdateMemoryAndScore(SystemInfo systemInfo)
        {
            _memory = new GameAppMemoryBreakdown
            {
                TotalBytes = systemInfo.TotalPhysicalMemory,
                UsedBytes = systemInfo.UsedPhysicalMemory,
                AvailableBytes = systemInfo.AvailablePhysicalMemory,
                CachedBytes = systemInfo.CachedMemory,
                StandbyBytes = systemInfo.StandbyMemory > 0 ? systemInfo.StandbyMemory : null,
                CommittedBytes = systemInfo.PageFileUsage,
                CommitLimitBytes = systemInfo.PageFileLimit
            };

            var assessments = BackgroundProcessCategorizer.AssessAll(
                systemInfo.Processes ?? new List<ProcessInfo>(),
                SelectedCard?.Profile,
                _neverOptimize);

            var profile = SelectedCard?.Profile;

            _ramAdvice = RamOptimizationAdvisor.Evaluate(
                _memory,
                assessments,
                targetPercent: null,
                closeBackgroundProcessesAllowed: profile?.Ram.CloseBackgroundProcesses ?? true);

            var candidates = BackgroundProcessCategorizer.SelectCandidates(assessments, profile ?? new GameAppProfile());

            var backgroundCpu = (systemInfo.Processes ?? new List<ProcessInfo>())
                .Where(p => p.RiskLevel is RiskLevel.Low or RiskLevel.Medium)
                .Sum(p => p.CpuUsage);

            var gpu = systemInfo.Gpus?.FirstOrDefault(g => g.IsPrimary) ?? systemInfo.Gpus?.FirstOrDefault();
            var gpuPercent = gpu != null && gpu.Usage > 0 ? gpu.Usage : (float?)null;
            var diskPercent = systemInfo.TotalDiskActivity > 0 ? systemInfo.TotalDiskActivity : (float?)null;

            _score = OptimizationPotentialScore.Calculate(
                ramPercent: systemInfo.RamUsagePercentage,
                totalMemoryBytes: systemInfo.TotalPhysicalMemory,
                reclaimableMegabytes: (int)(candidates.Sum(c => c.WorkingSet) / (1024 * 1024)),
                backgroundCpuPercent: backgroundCpu,
                optimisableCandidates: candidates.Count,
                gpuPercent: gpuPercent,
                mayCloseGpuHeavyProcesses: profile?.Gpu.CloseGpuHeavyBackgroundApplications ?? true,
                activePowerScheme: PowerSchemeManager.GetActiveSchemeName(),
                onAcPower: !systemInfo.IsOnBattery,
                profileChangesPower: profile?.Power.Enabled ?? true,
                diskPercent: diskPercent,
                applicationWorkingSetBytes: SelectedCard?.Instances.Sum(i => i.WorkingSet) ?? 0);

            OnPropertyChanged(nameof(PotentialText));
            OnPropertyChanged(nameof(PotentialSummary));
            OnPropertyChanged(nameof(PotentialBreakdown));
            OnPropertyChanged(nameof(MemoryLines));
            OnPropertyChanged(nameof(RamTargetText));
            OnPropertyChanged(nameof(RamStatements));
            OnPropertyChanged(nameof(SessionText));
            OnPropertyChanged(nameof(HasActiveSession));
        }

        private void DetectInterruptedSessions()
        {
            InterruptedSessions.Clear();

            foreach (var session in _sessions.FindInterruptedSessions())
                InterruptedSessions.Add(session);

            InterruptedDescription = InterruptedSessions.Count == 0
                ? string.Empty
                : _sessions.DescribeInterruptedSession(InterruptedSessions[0]);

            OnPropertyChanged(nameof(HasInterruptedSession));
            OnPropertyChanged(nameof(InterruptedDescription));
        }

        private void RaiseCommands()
        {
            OptimizeSelectedCommand.RaiseCanExecuteChanged();
            AnalyzeWithAiCommand.RaiseCanExecuteChanged();
            EndSessionCommand.RaiseCanExecuteChanged();
            RestoreInterruptedCommand.RaiseCanExecuteChanged();
            DismissInterruptedCommand.RaiseCanExecuteChanged();
            AddApplicationCommand.RaiseCanExecuteChanged();
            RefreshCommand.RaiseCanExecuteChanged();

            foreach (var card in _cards)
            {
                card.OptimizeCommand.RaiseCanExecuteChanged();
                card.RemoveCommand.RaiseCanExecuteChanged();
            }
        }

        #endregion

        #region Adding and removing

        /// <summary>
        /// Choose an executable with the Windows file picker and create a profile for it.
        ///
        /// The file is opened for reading and hashed; it is never started. Everything the user is shown
        /// comes from the file's own metadata.
        /// </summary>
        private async Task AddApplicationAsync()
        {
            var dialog = new OpenFileDialog
            {
                Title = "Select a game or application executable",
                Filter = "Applications (*.exe)|*.exe",
                CheckFileExists = true,
                CheckPathExists = true,
                Multiselect = false,
                DereferenceLinks = false
            };

            if (dialog.ShowDialog() != true)
                return;

            await RunGuardedAsync("Inspecting the selected file...", async () =>
            {
                var result = _profiles.AddApplication(dialog.FileName);

                if (!result.Success)
                {
                    var message = result.ErrorMessage;

                    if (result.ExistingProfile != null)
                    {
                        var existing = _cards.FirstOrDefault(c => c.ApplicationId == result.ExistingProfile.ApplicationId);

                        if (existing != null)
                            SelectedCard = existing;
                    }

                    Log($"Not added: {message}");
                    MessageBox.Show(message, "Game & App Optimizer", MessageBoxButton.OK, MessageBoxImage.Information);

                    return;
                }

                var card = new GameAppCardViewModel(result.Profile!, this);
                _cards.Add(card);
                SelectedCard = card;

                OnPropertyChanged(nameof(HasApplications));
                OnPropertyChanged(nameof(HasNoApplications));

                var lines = new List<string> { $"Added {card.DisplayName}." };
                lines.AddRange(result.Notes);

                Log(string.Join(Environment.NewLine, lines));

                StatusMessage = $"Added {card.DisplayName}. No system setting was changed by adding it.";

                await RefreshAsync().ConfigureAwait(true);
            }).ConfigureAwait(true);
        }

        /// <summary>
        /// Remove a profile. The executable itself is never touched, and the user is told so.
        /// </summary>
        public async Task RemoveAsync(GameAppCardViewModel? card)
        {
            if (card == null)
                return;

            var confirm = MessageBox.Show(
                $"Remove the profile for '{card.DisplayName}'?\r\n\r\n" +
                "This deletes the profile file and its history. The application itself is not touched, and " +
                "no system setting is changed.",
                "Remove profile",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes)
                return;

            await RunGuardedAsync("Removing the profile...", async () =>
            {
                var removed = _profiles.RemoveApplication(card.ApplicationId);

                if (removed)
                {
                    _cards.Remove(card);

                    if (SelectedCard == card)
                        SelectedCard = _cards.FirstOrDefault();

                    OnPropertyChanged(nameof(HasApplications));
                    OnPropertyChanged(nameof(HasNoApplications));

                    Log($"Removed the profile for {card.DisplayName}. The application was not touched.");
                }
                else
                {
                    Log($"The profile for {card.DisplayName} could not be removed.");
                }

                await Task.CompletedTask.ConfigureAwait(true);
            }).ConfigureAwait(true);
        }

        /// <summary>
        /// Show a card's profile in the interface (and, with the shift key held, open the file it is
        /// stored in). The file dialog is the shell's, not a command this application builds.
        /// </summary>
        public void OpenProfile(GameAppCardViewModel? card)
        {
            if (card == null)
                return;

            SelectedCard = card;
            Area = "Profiles";

            var lines = new List<string>
            {
                $"{card.DisplayName}",
                $"Executable: {card.ExecutablePath}",
                $"Mode: {card.ProfileModeText}",
                $"{card.PublisherText}",
                $"{card.SignatureText}",
                $"{card.ArchitectureText}",
                $"{card.FileSizeText}",
                $"{card.HashText}",
                $"Health: {card.HealthText}"
            };

            lines.AddRange(card.HealthFindings.Select(f => " - " + f));

            Log(string.Join(Environment.NewLine, lines));
        }

        #endregion

        #region Launching

        /// <summary>
        /// Start the application.
        ///
        /// The path comes from the profile's validated identity and is passed to ProcessStartInfo with
        /// UseShellExecute=false: no shell, no command string, no arguments the user did not store. If the
        /// executable no longer matches the profile, it is not started from here at all.
        /// </summary>
        public void Launch(GameAppCardViewModel? card)
        {
            if (card == null)
                return;

            if (!_engine.Config.GameAppAllowLaunchingApplications)
            {
                Log("Launching is switched off in this application's settings.");
                return;
            }

            var health = card.Health;

            if (health.State is not (ApplicationHealthState.Healthy or ApplicationHealthState.NotChecked))
            {
                Log($"{card.DisplayName} was not started: {health.Summary}");
                return;
            }

            var validation = ExecutablePathValidator.Validate(card.ExecutablePath);

            if (!validation.IsValid)
            {
                Log($"The stored path is no longer acceptable, so nothing was started: {validation.ErrorMessage}");
                return;
            }

            // Launcher support, when the profile explicitly configures one. The target is what the
            // session watches for, because a launcher usually stays alive while the real application
            // starts underneath it.
            var launcherPath = card.Profile.UsesLauncher ? card.Profile.LauncherPath : string.Empty;

            if (!string.IsNullOrWhiteSpace(launcherPath))
            {
                var launcher = ExecutablePathValidator.Validate(launcherPath);

                if (!launcher.IsValid)
                {
                    Log($"The configured launcher could not be used, so nothing was started: {launcher.ErrorMessage}");
                    return;
                }

                var rejected = card.Profile.NormalizeLauncherArguments();

                if (rejected.Count > 0)
                {
                    Log($"{rejected.Count} launcher argument(s) were rejected because they contained a line " +
                        "break or a control character, and were removed: " +
                        string.Join(" | ", rejected));
                }

                try
                {
                    var launcherStart = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = launcher.CanonicalPath,
                        WorkingDirectory = Path.GetDirectoryName(launcher.CanonicalPath) ?? string.Empty,
                        UseShellExecute = false
                    };

                    // One list entry is one argument. There is no shell, no quoting and no splitting, so
                    // an argument cannot become two arguments or a command.
                    foreach (var argument in card.Profile.LauncherArgumentList)
                        launcherStart.ArgumentList.Add(argument);

                    System.Diagnostics.Process.Start(launcherStart);

                    Log($"Started the launcher ({launcher.CanonicalPath}) for {card.DisplayName}. " +
                        $"{card.Profile.LauncherArgumentList.Count} argument(s) were passed.");

                    return;
                }
                catch (Exception exception)
                {
                    ErrorMessage = $"The launcher could not be started: {exception.Message}";
                    return;
                }
            }

            try
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = validation.CanonicalPath,
                    WorkingDirectory = Path.GetDirectoryName(validation.CanonicalPath) ?? string.Empty,
                    UseShellExecute = false
                };

                System.Diagnostics.Process.Start(startInfo);

                Log($"Started {card.DisplayName} ({validation.CanonicalPath}).");
            }
            catch (Exception exception)
            {
                ErrorMessage = $"The application could not be started: {exception.Message}";
            }
        }

        #endregion

        #region Optimising

        /// <summary>
        /// Plan and apply the profile for one application, after the user has seen what it will do.
        /// </summary>
        public async Task OptimizeAsync(GameAppCardViewModel? card)
        {
            if (card == null)
                return;

            await RunGuardedAsync("Preparing the optimisation plan...", async () =>
            {
                var systemInfo = await _engine.ScanAsync().ConfigureAwait(true);

                var health = _profiles.CheckHealth(card.Profile);

                card.Refresh(card.IsRunning ? ApplicationRunState.Running : ApplicationRunState.NotRunning,
                    card.Instances.ToList(), health);

                if (!health.IsUsable)
                {
                    // A suspended profile is not applied to whatever is at that path now.
                    Log($"{card.DisplayName}: {health.Summary}\r\n" + string.Join("\r\n", health.Findings));
                    MessageBox.Show(health.Summary, "Profile suspended", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                var state = _inspector.DetectRunningState(card.ExecutablePath, out var instances, out _);

                var plan = _planner.Plan(
                    card.Profile,
                    health,
                    instances,
                    systemInfo.Processes ?? new List<ProcessInfo>(),
                    _neverOptimize,
                    _engine.Config.GameAppAllowPowerModeChanges,
                    _engine.Config.GameAppAllowGraphicsPreferenceChanges);

                PlanPreview = plan.Summary;
                OnPropertyChanged(nameof(PlanPreview));

                if (!plan.HasAnythingToDo)
                {
                    Log(plan.Summary + Environment.NewLine +
                        string.Join(Environment.NewLine, plan.Refusals.Select(r => " - " + r.Describe())));

                    MessageBox.Show(
                        plan.Summary + Environment.NewLine + Environment.NewLine +
                        string.Join(Environment.NewLine, plan.Refusals.Select(r => " - " + r.Describe())),
                        "Nothing to do",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);

                    return;
                }

                // The user sees every change before it happens, in the same words the log will use.
                var preview = plan.Summary + Environment.NewLine + Environment.NewLine +
                              string.Join(Environment.NewLine,
                                  plan.Plan.Actions.Select(a => $" - {a.Description}: {a.Reason}")) +
                              (plan.Refusals.Count > 0
                                  ? Environment.NewLine + Environment.NewLine + "Considered and not done:" +
                                    Environment.NewLine +
                                    string.Join(Environment.NewLine, plan.Refusals.Select(r => " - " + r.Describe()))
                                  : string.Empty);

                var confirmed = MessageBox.Show(
                    preview + Environment.NewLine + Environment.NewLine +
                    "Everything reversible is restored when the application exits or when you press " +
                    "\"End session and restore\". Continue?",
                    $"Optimise {card.DisplayName}",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question) == MessageBoxResult.Yes;

                if (!confirmed)
                {
                    Log($"The plan for {card.DisplayName} was not applied: you chose not to continue.");
                    return;
                }

                var result = await _sessions.StartPlannedSessionAsync(
                    card.Profile, plan, "Manual", userConfirmed: true).ConfigureAwait(true);

                Log(result.Message + Environment.NewLine +
                    string.Join(Environment.NewLine, result.Notes.Select(n => " - " + n)) +
                    (result.Refusals.Count > 0
                        ? Environment.NewLine + "Not done:" + Environment.NewLine +
                          string.Join(Environment.NewLine, result.Refusals.Select(r => " - " + r))
                        : string.Empty));

                StatusMessage = result.Message;

                if (state == ApplicationRunState.NotRunning)
                {
                    Log($"{card.DisplayName} is not running. Changes that apply to a running process were " +
                        "not made; the profile's settings are ready for when it starts.");
                }

                OnPropertyChanged(nameof(SessionText));
                OnPropertyChanged(nameof(HasActiveSession));

                RaiseCommands();

                await Task.CompletedTask.ConfigureAwait(true);
            }).ConfigureAwait(true);
        }

        /// <summary>
        /// End the running session and put back everything that can be put back.
        /// </summary>
        public async Task EndSessionAsync()
        {
            await RunGuardedAsync("Restoring the machine to how it was...", async () =>
            {
                var result = await _sessions.EndSessionAsync().ConfigureAwait(true);

                Log(result.Summary);

                StatusMessage = result.HasFailures
                    ? "Restore finished with failures - see the details."
                    : "Session ended.";

                if (result.HasFailures)
                {
                    MessageBox.Show(result.Summary, "Restore finished with failures",
                        MessageBoxButton.OK, MessageBoxImage.Warning);
                }

                OnPropertyChanged(nameof(SessionText));
                OnPropertyChanged(nameof(HasActiveSession));

                RaiseCommands();

                await RefreshAsync().ConfigureAwait(true);
            }).ConfigureAwait(true);
        }

        /// <summary>
        /// Restore an interrupted session, at the user's request. This is never done automatically.
        /// </summary>
        private async Task RestoreInterruptedAsync()
        {
            if (InterruptedSessions.Count == 0)
                return;

            var session = InterruptedSessions[0];

            var confirm = MessageBox.Show(
                _sessions.DescribeInterruptedSession(session) + Environment.NewLine + Environment.NewLine +
                "Restore the reversible changes now?",
                "Restore interrupted session",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question) == MessageBoxResult.Yes;

            if (!confirm)
                return;

            await RunGuardedAsync("Restoring the interrupted session...", async () =>
            {
                var result = await _sessions.RestoreInterruptedSessionAsync(session).ConfigureAwait(true);

                Log(result.Summary);

                DetectInterruptedSessions();
                RaiseCommands();

                await RefreshAsync().ConfigureAwait(true);
            }).ConfigureAwait(true);
        }

        private void DismissInterrupted()
        {
            if (InterruptedSessions.Count == 0)
                return;

            var session = InterruptedSessions[0];

            var confirm = MessageBox.Show(
                "Leave the changes from this interrupted session in place?\r\n\r\n" +
                "The session is recorded in the history with your decision, so it is never as if it had " +
                "not happened. Nothing is changed either way.",
                "Keep the changes",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question) == MessageBoxResult.Yes;

            if (!confirm)
                return;

            _sessions.DismissInterruptedSession(session, "the user chose to keep the changes");

            Log("The interrupted session was dismissed; its changes were kept and the decision recorded.");

            DetectInterruptedSessions();
            RaiseCommands();
        }

        #endregion

        /// <summary>
        /// Ask the local model what it would suggest for the selected application.
        ///
        /// The answer is treated as text from an untrusted source: it is parsed against a strict schema,
        /// every suggestion is checked against the same vocabulary and limits the planner uses, and
        /// anything that does not fit is shown with the reason it was refused. Nothing is applied - a
        /// suggestion must still survive the planner, the safety validator and the user's confirmation.
        /// </summary>
        private async Task AnalyzeWithAiAsync()
        {
            var card = SelectedCard;

            if (card == null)
                return;

            if (_aiAnalysisRunning)
                return;

            _aiAnalysisRunning = true;

            try
            {
                await RunGuardedAsync("Asking the local model...", async () =>
                {
                    var systemInfo = _systemInfo.TotalPhysicalMemory > 0
                        ? _systemInfo
                        : await _engine.ScanAsync().ConfigureAwait(true);

                    var assessments = BackgroundProcessCategorizer.AssessAll(
                        systemInfo.Processes ?? new List<ProcessInfo>(),
                        card.Profile,
                        _neverOptimize);

                    var prompt = _aiAdvisor.BuildPrompt(
                        card.Profile,
                        card.Health,
                        card.Instances.ToList(),
                        systemInfo,
                        assessments);

                    var response = await _engine.Ai.AskAsync(prompt).ConfigureAwait(true);

                    var analysis = _aiAdvisor.Analyse(
                        response,
                        prompt,
                        card.Profile,
                        systemInfo,
                        assessments);

                    var lines = new List<string> { analysis.Summary };

                    if (analysis.Accepted.Any())
                    {
                        lines.Add("Suggestions that survived validation (recommendations only - nothing was applied):");

                        foreach (var suggestion in analysis.Accepted)
                            lines.Add(" - " + suggestion.Describe());
                    }

                    if (analysis.Refusals.Count > 0)
                    {
                        lines.Add("Refused, with the reason:");

                        foreach (var refusal in analysis.Refusals)
                            lines.Add(" - " + refusal);
                    }

                    if (!analysis.AiWasAvailable)
                    {
                        lines.Add("The model was not available. The optimiser works without it: the rules " +
                                  "above decide, not the model.");
                    }

                    var text = string.Join(Environment.NewLine, lines);

                    card.DescribePerformance(text);
                    Log(text);

                    StatusMessage = analysis.Summary;
                }).ConfigureAwait(true);
            }
            finally
            {
                _aiAnalysisRunning = false;
            }
        }

        private void Log(string text)
        {
            var stamp = DateTime.Now.ToString("HH:mm:ss");

            _actionLog = $"[{stamp}] {text}{Environment.NewLine}{Environment.NewLine}{_actionLog}";

            if (_actionLog.Length > 20000)
                _actionLog = _actionLog.Substring(0, 20000);

            OnPropertyChanged(nameof(ActionLog));

            Logger.Info("GameAppOptimizer", text.Replace(Environment.NewLine, " | "));
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _sessions.Dispose();
                _profiles.Dispose();
            }

            base.Dispose(disposing);
        }
    }
}

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
    /// Settings page. Everything is written to config.json through <see cref="AppConfig.Save"/>.
    /// </summary>
    public sealed class SettingsViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private AppConfig _config = AppConfig.CreateDefault();

        private bool _darkMode = true;
        private bool _useAnimations = true;
        private bool _showNotifications = true;
        private bool _minimizeToTray = true;

        private int _targetRamUsage = 35;
        private bool _autoOptimizeEnabled;
        private int _autoOptimizeInterval = 30;
        private bool _autoOptimizeOnIdle = true;
        private int _idleThreshold = 60;
        private bool _optimizeOnBattery = true;

        private bool _aiEnabled = true;
        private string _aiModel = "llama3.2:3b";
        private string _ollamaUrl = "http://localhost:11434";
        private float _aiConfidence = 0.7f;

        private bool _safetyLayerEnabled = true;
        private bool _createRestorePoints = true;
        private bool _requireConfirmationForMediumRisk = true;
        private bool _allowHighRiskActions;
        private bool _loggingEnabled = true;
        private string _logLevel = "Info";

        private bool _gameModeEnabled = true;
        private bool _autoDetectGames = true;
        private bool _gameModeBoostPriority = true;

        private string _aiStatus = "Not checked yet.";
        private string _newWhitelistEntry = string.Empty;

        #endregion

        #region Construction

        public SettingsViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            SaveCommand = new AsyncRelayCommand(SaveAsync, () => !IsBusy);
            ReloadCommand = new RelayCommand(Reload);
            ResetDefaultsCommand = new AsyncRelayCommand(ResetToDefaultsAsync, () => !IsBusy);
            TestAiCommand = new AsyncRelayCommand(TestAiAsync, () => !IsBusy);
            AddWhitelistCommand = new AsyncRelayCommand(AddWhitelistAsync);
            RemoveWhitelistCommand = new AsyncRelayCommand(RemoveWhitelistAsync);
            OpenConfigFolderCommand = new RelayCommand(OpenConfigFolder);

            Reload();
        }

        #endregion

        #region Commands

        public AsyncRelayCommand SaveCommand { get; }
        public RelayCommand ReloadCommand { get; }
        public AsyncRelayCommand ResetDefaultsCommand { get; }
        public AsyncRelayCommand TestAiCommand { get; }
        public AsyncRelayCommand AddWhitelistCommand { get; }
        public AsyncRelayCommand RemoveWhitelistCommand { get; }
        public RelayCommand OpenConfigFolderCommand { get; }

        #endregion

        #region Appearance

        public bool DarkMode
        {
            get => _darkMode;
            set => SetProperty(ref _darkMode, value);
        }

        public bool UseAnimations
        {
            get => _useAnimations;
            set => SetProperty(ref _useAnimations, value);
        }

        public bool ShowNotifications
        {
            get => _showNotifications;
            set => SetProperty(ref _showNotifications, value);
        }

        public bool MinimizeToTray
        {
            get => _minimizeToTray;
            set => SetProperty(ref _minimizeToTray, value);
        }

        #endregion

        #region Optimisation

        /// <summary>RAM target in percent. The UI explains when it is not safely reachable.</summary>
        public int TargetRamUsage
        {
            get => _targetRamUsage;
            set
            {
                if (SetProperty(ref _targetRamUsage, value))
                    OnPropertyChanged(nameof(TargetRamReachability));
            }
        }

        /// <summary>Honest assessment of the configured target against the current machine.</summary>
        public string TargetRamReachability =>
            _engine.Scanner.LastScanTime == DateTime.MinValue
                ? "Run a scan to see whether this target can be reached safely."
                : _engine.DescribeRamTarget(_engine.Scanner.LastScanResult);

        public bool AutoOptimizeEnabled
        {
            get => _autoOptimizeEnabled;
            set => SetProperty(ref _autoOptimizeEnabled, value);
        }

        public int AutoOptimizeInterval
        {
            get => _autoOptimizeInterval;
            set => SetProperty(ref _autoOptimizeInterval, value);
        }

        public bool AutoOptimizeOnIdle
        {
            get => _autoOptimizeOnIdle;
            set => SetProperty(ref _autoOptimizeOnIdle, value);
        }

        public int IdleThreshold
        {
            get => _idleThreshold;
            set => SetProperty(ref _idleThreshold, value);
        }

        public bool OptimizeOnBattery
        {
            get => _optimizeOnBattery;
            set => SetProperty(ref _optimizeOnBattery, value);
        }

        #endregion

        #region AI

        public bool AiEnabled
        {
            get => _aiEnabled;
            set
            {
                if (SetProperty(ref _aiEnabled, value))
                    OnPropertyChanged(nameof(AiConfigurationHint));
            }
        }

        public string AiModel
        {
            get => _aiModel;
            set => SetProperty(ref _aiModel, value);
        }

        public string OllamaUrl
        {
            get => _ollamaUrl;
            set => SetProperty(ref _ollamaUrl, value);
        }

        public float AiConfidence
        {
            get => _aiConfidence;
            set => SetProperty(ref _aiConfidence, value);
        }

        /// <summary>Status of the last AI check.</summary>
        public string AiStatus
        {
            get => _aiStatus;
            private set => SetProperty(ref _aiStatus, value);
        }

        /// <summary>Explains what happens when the AI is unavailable.</summary>
        public string AiConfigurationHint =>
            "The AI is entirely optional. When it is disabled or unreachable, the rule-based analyser " +
            "still provides full functionality - the application never requires an internet connection.";

        #endregion

        #region Safety and logging

        public bool SafetyLayerEnabled
        {
            get => _safetyLayerEnabled;
            set => SetProperty(ref _safetyLayerEnabled, value);
        }

        public bool CreateRestorePoints
        {
            get => _createRestorePoints;
            set => SetProperty(ref _createRestorePoints, value);
        }

        public bool RequireConfirmationForMediumRisk
        {
            get => _requireConfirmationForMediumRisk;
            set => SetProperty(ref _requireConfirmationForMediumRisk, value);
        }

        public bool AllowHighRiskActions
        {
            get => _allowHighRiskActions;
            set => SetProperty(ref _allowHighRiskActions, value);
        }

        public bool LoggingEnabled
        {
            get => _loggingEnabled;
            set => SetProperty(ref _loggingEnabled, value);
        }

        public string LogLevel
        {
            get => _logLevel;
            set => SetProperty(ref _logLevel, value);
        }

        /// <summary>Log levels for the combo box.</summary>
        public List<string> LogLevels { get; } = new() { "Verbose", "Debug", "Info", "Warning", "Error" };

        /// <summary>Where the log lives, shown to the user.</summary>
        public string LogPath => Core.Constants.AppConstants.LogDirectoryPath;

        /// <summary>Where config.json lives.</summary>
        public string ConfigPath => Core.Constants.AppConstants.ConfigFilePath;

        #endregion

        #region Game mode

        public bool GameModeEnabled
        {
            get => _gameModeEnabled;
            set => SetProperty(ref _gameModeEnabled, value);
        }

        public bool AutoDetectGames
        {
            get => _autoDetectGames;
            set => SetProperty(ref _autoDetectGames, value);
        }

        public bool GameModeBoostPriority
        {
            get => _gameModeBoostPriority;
            set => SetProperty(ref _gameModeBoostPriority, value);
        }

        #endregion

        #region Whitelist

        /// <summary>Process names the optimiser must never close automatically.</summary>
        public ObservableCollection<string> Whitelist { get; } =
            new ObservableCollection<string>();

        /// <summary>New whitelist entry being typed.</summary>
        public string NewWhitelistEntry
        {
            get => _newWhitelistEntry;
            set => SetProperty(ref _newWhitelistEntry, value);
        }

        /// <summary>Protected processes fixed by the application (never editable).</summary>
        public string ProtectedSummary =>
            "Windows core processes, drivers, security components and the pagefile are always protected. " +
            "That list is built into the application and cannot be edited.";

        #endregion

        #region Load / save

        /// <summary>Reload settings from the active configuration.</summary>
        public void Reload()
        {
            try
            {
                _config = _engine.Config;

                DarkMode = _config.DarkMode;
                UseAnimations = _config.UseAnimations;
                ShowNotifications = _config.ShowNotifications;
                MinimizeToTray = _config.MinimizeToTray;

                TargetRamUsage = _config.TargetRamUsage;
                AutoOptimizeEnabled = _config.AutoOptimizeEnabled;
                AutoOptimizeInterval = _config.AutoOptimizeInterval;
                AutoOptimizeOnIdle = _config.AutoOptimizeOnIdle;
                IdleThreshold = _config.IdleThreshold;
                OptimizeOnBattery = _config.OptimizeOnBattery;

                AiEnabled = _config.AiEnabled;
                AiModel = _config.AiModel;
                OllamaUrl = _config.OllamaServerUrl;
                AiConfidence = _config.AiConfidenceThreshold;

                SafetyLayerEnabled = _config.SafetyLayerEnabled;
                CreateRestorePoints = _config.CreateRestorePoints;
                RequireConfirmationForMediumRisk = _config.RequireConfirmationForMediumRisk;
                AllowHighRiskActions = _config.AllowHighRiskActions;
                LoggingEnabled = _config.LoggingEnabled;
                LogLevel = _config.LogLevel;

                GameModeEnabled = _config.GameModeEnabled;
                AutoDetectGames = _config.AutoDetectGames;
                GameModeBoostPriority = _config.GameModeBoostPriority;

                Whitelist.Clear();
                foreach (var entry in _config.WhitelistedProcesses)
                    Whitelist.Add(entry);

                OnPropertyChanged(nameof(TargetRamReachability));
                OnPropertyChanged(nameof(LogPath));
                OnPropertyChanged(nameof(ConfigPath));
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not load settings: {ex.Message}";
            }
        }

        /// <summary>Persist settings to config.json.</summary>
        private async Task SaveAsync()
        {
            await RunGuardedAsync("Saving settings...", async () =>
            {
                _config.DarkMode = DarkMode;
                _config.UseAnimations = UseAnimations;
                _config.ShowNotifications = ShowNotifications;
                _config.MinimizeToTray = MinimizeToTray;

                _config.TargetRamUsage = Math.Clamp(TargetRamUsage, 10, 90);
                _config.AutoOptimizeEnabled = AutoOptimizeEnabled;
                _config.AutoOptimizeInterval = Math.Clamp(AutoOptimizeInterval, 5, 1440);
                _config.AutoOptimizeOnIdle = AutoOptimizeOnIdle;
                _config.IdleThreshold = Math.Clamp(IdleThreshold, 10, 600);
                _config.OptimizeOnBattery = OptimizeOnBattery;

                _config.AiEnabled = AiEnabled;
                _config.AiModel = AiModel;
                _config.OllamaServerUrl = OllamaUrl;
                _config.AiConfidenceThreshold = Math.Clamp(AiConfidence, 0f, 1f);

                _config.SafetyLayerEnabled = SafetyLayerEnabled;
                _config.CreateRestorePoints = CreateRestorePoints;
                _config.RequireConfirmationForMediumRisk = RequireConfirmationForMediumRisk;
                _config.AllowHighRiskActions = AllowHighRiskActions;
                _config.LoggingEnabled = LoggingEnabled;
                _config.LogLevel = LogLevel;

                _config.GameModeEnabled = GameModeEnabled;
                _config.AutoDetectGames = AutoDetectGames;
                _config.GameModeBoostPriority = GameModeBoostPriority;

                _config.WhitelistedProcesses = Whitelist.ToList();

                if (!_config.Validate(out var errors))
                {
                    ErrorMessage = "Settings not saved: " + string.Join("; ", errors);
                    return;
                }

                var saved = await Task.Run(() => _config.Save()).ConfigureAwait(true);

                ErrorMessage = saved ? string.Empty : "Settings could not be written to disk.";
            });
        }

        private async Task ResetToDefaultsAsync()
        {
            var confirm = MessageBox.Show(
                "Reset every setting to its default value?\n\n" +
                "Your whitelist and blacklist entries will be removed as well.",
                "Reset settings",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync("Resetting settings...", async () =>
            {
                var defaults = AppConfig.CreateDefault();

                await Task.Run(() =>
                {
                    defaults.Save();

                    // Apply the defaults to the running engine as well.
                    var current = _engine.Config;

                    foreach (var property in typeof(AppConfig).GetProperties())
                    {
                        if (property.CanWrite)
                            property.SetValue(current, property.GetValue(defaults));
                    }
                }).ConfigureAwait(true);

                Reload();
            });
        }

        private async Task TestAiAsync()
        {
            await RunGuardedAsync("Contacting the local AI model...", async () =>
            {
                AiStatus = "Contacting " + OllamaUrl + " ...";

                var available = await Task.Run(() => _engine.Ai.IsAvailable).ConfigureAwait(true);

                AiStatus = available
                    ? $"Available. Model: {AiModel}. The AI adds explanations and second opinions; " +
                      "every suggestion it makes is still subject to the safety layer."
                    : "Not reachable. Rule-based analysis remains fully functional - the AI is optional.";
            });
        }

        #endregion

        #region Whitelist actions

        private async Task AddWhitelistAsync()
        {
            var entry = NewWhitelistEntry?.Trim();

            if (string.IsNullOrWhiteSpace(entry))
                return;

            if (!Whitelist.Contains(entry, StringComparer.OrdinalIgnoreCase))
                Whitelist.Add(entry);

            NewWhitelistEntry = string.Empty;

            await SaveAsync().ConfigureAwait(true);
        }

        private async Task RemoveWhitelistAsync()
        {
            // The parameter carries the entry to remove when invoked from the list.
            await SaveAsync().ConfigureAwait(true);
        }

        /// <summary>Remove a specific whitelist entry (bound from the list item).</summary>
        public async Task RemoveWhitelistEntryAsync(string entry)
        {
            if (string.IsNullOrWhiteSpace(entry)) return;

            var match = Whitelist.FirstOrDefault(w => string.Equals(w, entry, StringComparison.OrdinalIgnoreCase));

            if (match != null)
                Whitelist.Remove(match);

            await SaveAsync().ConfigureAwait(true);
        }

        private void OpenConfigFolder()
        {
            try
            {
                var folder = Core.Constants.AppConstants.AppDataPath;
                System.IO.Directory.CreateDirectory(folder);

                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = folder,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not open the configuration folder: {ex.Message}";
            }
        }

        #endregion
    }
}

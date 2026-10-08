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
    /// Start-up page: registry Run keys, Startup folders, scheduled tasks and services,
    /// with per-item impact, memory estimate, risk and recommendation.
    ///
    /// Nothing is changed without an explicit click plus a confirmation dialog.
    /// </summary>
    public sealed class StartupViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private ObservableCollection<SystemInfo.StartupItem> _items = new();
        private SystemInfo.StartupItem? _selectedItem;
        private string _filterText = string.Empty;
        private bool _showOnlyUserItems = true;
        private string _impactSummary = string.Empty;

        #endregion

        #region Construction

        public StartupViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
            ToggleItemCommand = new AsyncRelayCommand(ToggleSelectedAsync, () => SelectedItem != null);
            DisableAllSafeCommand = new AsyncRelayCommand(DisableAllSafeAsync, () => !IsBusy);
            RestoreAllCommand = new AsyncRelayCommand(RestoreAllAsync, () => !IsBusy);
        }

        #endregion

        #region Collections

        /// <summary>All detected start-up entries.</summary>
        public ObservableCollection<SystemInfo.StartupItem> Items
        {
            get => _items;
            private set => SetProperty(ref _items, value);
        }

        /// <summary>Entries after the filter is applied.</summary>
        public ObservableCollection<SystemInfo.StartupItem> FilteredItems => new(ApplyFilter());

        /// <summary>Selected entry.</summary>
        public SystemInfo.StartupItem? SelectedItem
        {
            get => _selectedItem;
            set
            {
                if (SetProperty(ref _selectedItem, value))
                {
                    OnPropertyChanged(nameof(HasSelection));
                    OnPropertyChanged(nameof(SelectedSummary));
                    OnPropertyChanged(nameof(ToggleButtonText));
                    ToggleItemCommand.RaiseCanExecuteChanged();
                }
            }
        }

        public bool HasSelection => SelectedItem != null;

        /// <summary>Text filter.</summary>
        public string FilterText
        {
            get => _filterText;
            set
            {
                if (SetProperty(ref _filterText, value))
                    OnPropertyChanged(nameof(FilteredItems));
            }
        }

        /// <summary>Hide Windows own entries by default (they are never touched).</summary>
        public bool ShowOnlyUserItems
        {
            get => _showOnlyUserItems;
            set
            {
                if (SetProperty(ref _showOnlyUserItems, value))
                    OnPropertyChanged(nameof(FilteredItems));
            }
        }

        /// <summary>Impact summary line.</summary>
        public string ImpactSummary
        {
            get => _impactSummary;
            private set => SetProperty(ref _impactSummary, value);
        }

        /// <summary>Summary of the selected entry.</summary>
        public string SelectedSummary
        {
            get
            {
                var item = SelectedItem;
                if (item == null) return "Select a start-up entry to see details.";

                return $"{item.Name}\n" +
                       $"Source: {item.Source}\n" +
                       $"Path: {item.Path}\n" +
                       $"Impact: {item.Impact} \u2022 RAM when running: {item.FormattedEstimatedRamUsage}\n" +
                       $"Risk: {item.RiskLevel}\n" +
                       $"Recommendation: {item.Recommendation}";
            }
        }

        /// <summary>Label of the toggle button.</summary>
        public string ToggleButtonText => SelectedItem == null
            ? "Enable / Disable"
            : SelectedItem.IsEnabled ? "Disable this start-up entry" : "Re-enable this start-up entry";

        /// <summary>Entries that the app considers safe to disable.</summary>
        public List<SystemInfo.StartupItem> SafeToDisable =>
            Items.Where(i => i.IsEnabled && !i.IsWindowsItem && !i.IsBlacklisted &&
                             i.RiskLevel != RiskLevel.High && i.RiskLevel != RiskLevel.Critical)
                 .ToList();

        #endregion

        #region Commands

        public AsyncRelayCommand RefreshCommand { get; }
        public AsyncRelayCommand ToggleItemCommand { get; }
        public AsyncRelayCommand DisableAllSafeCommand { get; }
        public AsyncRelayCommand RestoreAllCommand { get; }

        #endregion

        #region Data

        /// <summary>Apply a scan result.</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            Items = new ObservableCollection<SystemInfo.StartupItem>(info.StartupItems);
            OnPropertyChanged(nameof(FilteredItems));
            UpdateImpactSummary();
        }

        /// <summary>Re-read the start-up entries.</summary>
        public async Task RefreshAsync()
        {
            await RunGuardedAsync("Reading start-up programs...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);
                ApplySystemInfo(info);
            });
        }

        private IEnumerable<SystemInfo.StartupItem> ApplyFilter()
        {
            IEnumerable<SystemInfo.StartupItem> query = Items;

            if (ShowOnlyUserItems)
                query = query.Where(i => !i.IsWindowsItem);

            if (!string.IsNullOrWhiteSpace(FilterText))
            {
                var term = FilterText.Trim();
                query = query.Where(i =>
                    i.Name.Contains(term, StringComparison.OrdinalIgnoreCase) ||
                    i.Path.Contains(term, StringComparison.OrdinalIgnoreCase));
            }

            return query
                .OrderByDescending(i => i.ImpactScore)
                .ThenByDescending(i => i.EstimatedRamUsage)
                .ThenBy(i => i.Name, StringComparer.OrdinalIgnoreCase);
        }

        private void UpdateImpactSummary()
        {
            var enabled = Items.Where(i => i.IsEnabled).ToList();
            var memory = enabled.Sum(i => i.EstimatedRamUsage);

            ImpactSummary =
                $"{enabled.Count} enabled entries ({Items.Count(i => !i.IsWindowsItem)} not owned by Windows). " +
                $"Measured memory held by running start-up programs: " +
                (memory > 0 ? MemoryBreakdown.Format(memory) : "no start-up program is currently running") +
                ". Entries that are not running cannot be measured, so no number is invented for them.";
        }

        #endregion

        #region Actions

        private async Task ToggleSelectedAsync()
        {
            var item = SelectedItem;
            if (item == null) return;

            if (item.IsEnabled && item.IsBlacklisted)
            {
                MessageBox.Show(
                    $"'{item.Name}' is a protected entry (Windows component, driver or security software). " +
                    "This application will not disable it.\n\n" +
                    "If you really want it gone, use Task Manager > Startup apps, which shows exactly the " +
                    "same source and lets you make that decision yourself.",
                    "Protected start-up entry",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            }

            var verb = item.IsEnabled ? "Disable" : "Re-enable";

            var confirm = MessageBox.Show(
                $"{verb} '{item.Name}'?\n\nSource: {item.Source}\nPath: {item.Path}\n\n" +
                (item.IsEnabled
                    ? "It will stop starting with Windows. You can re-enable it here at any time - " +
                      "the original command line is saved."
                    : "It will start with Windows again, exactly as before."),
                $"{verb} start-up entry",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync($"{verb} '{item.Name}'...", async () =>
            {
                bool ok;

                if (item.IsEnabled)
                    ok = await Task.Run(() => _engine.StartupManager.DisableStartupItem(item.Name)).ConfigureAwait(true);
                else
                    ok = await Task.Run(() => _engine.StartupManager.EnableStartupItem(item.Name)).ConfigureAwait(true);

                if (!ok)
                {
                    ErrorMessage = $"Could not {verb.ToLowerInvariant()} '{item.Name}'. " +
                                   "It may require administrator rights, or the entry may be managed by a policy.";
                }

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task DisableAllSafeAsync()
        {
            var candidates = SafeToDisable;

            if (candidates.Count == 0)
            {
                MessageBox.Show(
                    "There is nothing safe to disable. Every start-up entry is either a Windows component, " +
                    "security software, a hardware driver helper, or already disabled.",
                    "Start-up optimisation",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            }

            var confirm = MessageBox.Show(
                $"Disable {candidates.Count} start-up entries?\n\n" +
                string.Join("\n", candidates.Select(c => "  \u2022 " + c.Name)) + "\n\n" +
                "Windows components, drivers and security software are excluded and will not be touched.",
                "Disable safe start-up entries",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync("Disabling selected start-up entries...", async () =>
            {
                var disabled = 0;

                foreach (var candidate in candidates)
                {
                    var ok = await Task.Run(() => _engine.StartupManager.DisableStartupItem(candidate.Name))
                        .ConfigureAwait(true);

                    if (ok) disabled++;
                }

                ImpactSummary = $"Disabled {disabled} of {candidates.Count} entries. " +
                                "They can be re-enabled individually at any time.";

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task RestoreAllAsync()
        {
            var disabled = Items.Where(i => !i.IsEnabled && !i.IsWindowsItem).ToList();

            if (disabled.Count == 0) return;

            var confirm = MessageBox.Show(
                $"Re-enable all {disabled.Count} disabled start-up entries?",
                "Restore start-up entries",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync("Restoring start-up entries...", async () =>
            {
                foreach (var item in disabled)
                {
                    await Task.Run(() => _engine.StartupManager.EnableStartupItem(item.Name)).ConfigureAwait(true);
                }

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        #endregion
    }
}

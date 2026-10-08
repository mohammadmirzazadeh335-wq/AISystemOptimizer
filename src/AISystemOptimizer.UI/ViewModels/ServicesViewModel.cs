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
    /// Services page. Deliberately conservative: critical Windows services and everything on the
    /// blacklist cannot be stopped or disabled from here, and every change is confirmed.
    /// </summary>
    public sealed class ServicesViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private ObservableCollection<SystemInfo.ServiceInfo> _services = new();
        private SystemInfo.ServiceInfo? _selectedService;
        private string _filterText = string.Empty;
        private bool _showOnlyRunning = true;
        private bool _showOnlyThirdParty;
        private string _summary = string.Empty;

        #endregion

        #region Construction

        public ServicesViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
            StopServiceCommand = new AsyncRelayCommand(StopSelectedAsync, CanStopSelected);
            StartServiceCommand = new AsyncRelayCommand(StartSelectedAsync, CanStartSelected);
            DisableServiceCommand = new AsyncRelayCommand(DisableSelectedAsync, CanDisableSelected);
            EnableServiceCommand = new AsyncRelayCommand(EnableSelectedAsync, CanEnableSelected);
        }

        #endregion

        #region Collections

        /// <summary>All services detected on the machine.</summary>
        public ObservableCollection<SystemInfo.ServiceInfo> Services
        {
            get => _services;
            private set => SetProperty(ref _services, value);
        }

        /// <summary>Services after filtering.</summary>
        public ObservableCollection<SystemInfo.ServiceInfo> FilteredServices => new(ApplyFilter());

        /// <summary>Selected service.</summary>
        public SystemInfo.ServiceInfo? SelectedService
        {
            get => _selectedService;
            set
            {
                if (SetProperty(ref _selectedService, value))
                {
                    OnPropertyChanged(nameof(HasSelection));
                    OnPropertyChanged(nameof(SelectedSummary));
                    OnPropertyChanged(nameof(ProtectionNote));
                    StopServiceCommand.RaiseCanExecuteChanged();
                    StartServiceCommand.RaiseCanExecuteChanged();
                    DisableServiceCommand.RaiseCanExecuteChanged();
                    EnableServiceCommand.RaiseCanExecuteChanged();
                }
            }
        }

        public bool HasSelection => SelectedService != null;

        /// <summary>Text filter (name or display name).</summary>
        public string FilterText
        {
            get => _filterText;
            set
            {
                if (SetProperty(ref _filterText, value))
                    OnPropertyChanged(nameof(FilteredServices));
            }
        }

        /// <summary>Only list running services.</summary>
        public bool ShowOnlyRunning
        {
            get => _showOnlyRunning;
            set
            {
                if (SetProperty(ref _showOnlyRunning, value))
                    OnPropertyChanged(nameof(FilteredServices));
            }
        }

        /// <summary>Only list services that are not part of Windows.</summary>
        public bool ShowOnlyThirdParty
        {
            get => _showOnlyThirdParty;
            set
            {
                if (SetProperty(ref _showOnlyThirdParty, value))
                    OnPropertyChanged(nameof(FilteredServices));
            }
        }

        /// <summary>Counters shown above the list.</summary>
        public string Summary
        {
            get => _summary;
            private set => SetProperty(ref _summary, value);
        }

        /// <summary>Details of the selected service.</summary>
        public string SelectedSummary
        {
            get
            {
                var service = SelectedService;
                if (service == null) return "Select a service to see its details.";

                return $"{service.DisplayName} ({service.Name})\n" +
                       $"Status: {service.Status}   Start type: {service.StartType}\n" +
                       $"Windows service: {(service.IsWindowsService ? "yes" : "no")}   " +
                       $"Critical: {(service.IsCritical ? "yes" : "no")}   Risk: {service.RiskLevel}";
            }
        }

        /// <summary>Explains why the buttons are disabled for the selected service.</summary>
        public string ProtectionNote
        {
            get
            {
                var service = SelectedService;
                if (service == null) return string.Empty;

                if (service.IsCritical)
                {
                    return "PROTECTED: This service is required by Windows or by your security stack. " +
                           "Stopping or disabling it is refused, because a lower memory figure is not worth " +
                           "a broken or unprotected system.";
                }

                if (service.IsWindowsService)
                {
                    return "WINDOWS SERVICE: Part of the operating system. It is never disabled automatically; " +
                           "you may stop it manually if you understand the consequences.";
                }

                return "THIRD PARTY: This service is not part of Windows. Stopping or disabling it is allowed " +
                       "after confirmation, and it can be re-enabled here.";
            }
        }

        #endregion

        #region Commands

        public AsyncRelayCommand RefreshCommand { get; }
        public AsyncRelayCommand StopServiceCommand { get; }
        public AsyncRelayCommand StartServiceCommand { get; }
        public AsyncRelayCommand DisableServiceCommand { get; }
        public AsyncRelayCommand EnableServiceCommand { get; }

        private bool CanStopSelected()
        {
            var service = SelectedService;
            if (service == null) return false;

            return service.CanStop && !service.IsCritical &&
                   !_engine.Config.BlacklistedServices.Any(b =>
                       string.Equals(b, service.Name, StringComparison.OrdinalIgnoreCase));
        }

        private bool CanStartSelected() => SelectedService?.Status == "Stopped";

        private bool CanDisableSelected()
        {
            var service = SelectedService;
            if (service == null) return false;

            return !service.IsCritical && !service.IsWindowsService && service.StartType != "Disabled" &&
                   !_engine.Config.BlacklistedServices.Any(b =>
                       string.Equals(b, service.Name, StringComparison.OrdinalIgnoreCase));
        }

        private bool CanEnableSelected() => SelectedService?.StartType == "Disabled";

        #endregion

        #region Data

        /// <summary>Apply a scan result.</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            Services = new ObservableCollection<SystemInfo.ServiceInfo>(info.Services);
            OnPropertyChanged(nameof(FilteredServices));

            var running = info.Services.Count(s => s.Status == "Running");
            var thirdParty = info.Services.Count(s => !s.IsWindowsService);

            Summary = $"{info.Services.Count} services \u2022 {running} running \u2022 {thirdParty} third party \u2022 " +
                      $"{info.Services.Count(s => s.IsCritical)} protected";
        }

        /// <summary>Re-read the service list.</summary>
        public async Task RefreshAsync()
        {
            await RunGuardedAsync("Reading services...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);
                ApplySystemInfo(info);
            });
        }

        private IEnumerable<SystemInfo.ServiceInfo> ApplyFilter()
        {
            IEnumerable<SystemInfo.ServiceInfo> query = Services;

            if (ShowOnlyRunning)
                query = query.Where(s => s.Status == "Running");

            if (ShowOnlyThirdParty)
                query = query.Where(s => !s.IsWindowsService);

            if (!string.IsNullOrWhiteSpace(FilterText))
            {
                var term = FilterText.Trim();
                query = query.Where(s =>
                    s.Name.Contains(term, StringComparison.OrdinalIgnoreCase) ||
                    s.DisplayName.Contains(term, StringComparison.OrdinalIgnoreCase));
            }

            return query
                .OrderByDescending(s => s.IsCritical)
                .ThenBy(s => s.DisplayName, StringComparer.OrdinalIgnoreCase);
        }

        #endregion

        #region Actions

        private async Task StopSelectedAsync()
        {
            var service = SelectedService;
            if (service == null) return;

            var confirm = MessageBox.Show(
                $"Stop service '{service.DisplayName}' ({service.Name})?\n\n" +
                "Stopping a service can break features that depend on it. It will restart at the next boot " +
                "unless you also disable it.",
                "Stop service",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync($"Stopping {service.Name}...", async () =>
            {
                var ok = await Task.Run(() => _engine.ServiceManager.StopService(service.Name)).ConfigureAwait(true);

                if (!ok)
                {
                    ErrorMessage = $"Windows refused to stop '{service.Name}'. " +
                                   "It may be protected, have a running dependent service, or require elevation.";
                }

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task StartSelectedAsync()
        {
            var service = SelectedService;
            if (service == null) return;

            await RunGuardedAsync($"Starting {service.Name}...", async () =>
            {
                var ok = await Task.Run(() => _engine.ServiceManager.StartService(service.Name)).ConfigureAwait(true);

                if (!ok)
                    ErrorMessage = $"Could not start '{service.Name}'. It may depend on another stopped service.";

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task DisableSelectedAsync()
        {
            var service = SelectedService;
            if (service == null) return;

            var confirm = MessageBox.Show(
                $"Disable service '{service.DisplayName}' ({service.Name})?\n\n" +
                "It will be stopped now and will not start with Windows. Features that depend on it will " +
                "stop working until you re-enable it here.\n\n" +
                "A System Restore point is recommended first.",
                "Disable service",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

            if (confirm != MessageBoxResult.Yes) return;

            await RunGuardedAsync($"Disabling {service.Name}...", async () =>
            {
                var ok = await Task.Run(() => _engine.ServiceManager.DisableService(service.Name)).ConfigureAwait(true);

                if (!ok)
                    ErrorMessage = $"Windows refused to disable '{service.Name}'. Administrator rights are " +
                                   "required for this operation.";

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        private async Task EnableSelectedAsync()
        {
            var service = SelectedService;
            if (service == null) return;

            await RunGuardedAsync($"Re-enabling {service.Name}...", async () =>
            {
                var ok = await Task.Run(() => _engine.ServiceManager.EnableService(service.Name)).ConfigureAwait(true);

                if (!ok)
                    ErrorMessage = $"Could not re-enable '{service.Name}'. Administrator rights are required.";

                await RefreshAsync().ConfigureAwait(true);
            });
        }

        #endregion
    }
}

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// About page: what the application is, what it deliberately does not do, and the
    /// list of guarantees the user can hold it to.
    /// </summary>
    public sealed class AboutViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;
        private string _diagnostics = string.Empty;

        #endregion

        #region Construction

        public AboutViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            OpenLogFolderCommand = new RelayCommand(OpenLogFolder);
            OpenWebsiteCommand = new RelayCommand(OpenWebsite);
            RunDiagnosticsCommand = new AsyncRelayCommand(RunDiagnosticsAsync, () => !IsBusy);
            CopyDiagnosticsCommand = new RelayCommand(CopyDiagnostics);

            BuildCapabilityList();
        }

        #endregion

        #region Identity

        public string AppName => AppConstants.AppName;

        public string AppVersion =>
            Assembly.GetEntryAssembly()?.GetName().Version?.ToString() ?? AppConstants.AppVersion;

        public string AppDescription =>
            "A real Windows 11 system optimiser: it measures, explains, asks for confirmation, " +
            "acts only where it is safe, verifies the result, and reports honestly when nothing " +
            "can be improved.";

        public string Publisher => AppConstants.AppPublisher;

        public string Framework =>
            $".NET {Environment.Version} on {Environment.OSVersion.VersionString}";

        public string Elevation => WindowsApiHelper.IsAdministrator()
            ? "Running elevated (Administrator)"
            : "Running as a standard user - some operations will be refused by Windows";

        #endregion

        #region Guarantees

        /// <summary>What the application will never do - held to in code, not just in text.</summary>
        public List<string> NeverDoes { get; } = new()
        {
            "Disable Windows Defender, the firewall or UAC",
            "Kill critical system processes (system, csrss, lsass, dwm, explorer, svchost, ...)",
            "Touch hardware drivers",
            "Disable Windows Update",
            "Disable or resize the pagefile",
            "Install, patch or delete system components",
            "Clear the standby list to make the RAM number look better",
            "Hide the real effect of an optimisation behind an animation",
            "Bypass UAC in any way",
            "Change the registry outside the documented Run keys for start-up items",
            "Claim a speed-up that was not measured"
        };

        /// <summary>What it does do, in plain language.</summary>
        public List<string> DoesDo { get; } = new()
        {
            "Scans processes, services, start-up items, memory, CPU, GPU and disk usage",
            "Separates user applications from background noise and from Windows internals",
            "Ranks every candidate by how much it costs and how risky it is to touch",
            "Closes inactive background applications you are not using",
            "Disables optional start-up entries (with the original value saved for undo)",
            "Stops and disables third-party services that you explicitly approve",
            "Raises a running game to AboveNormal priority in Game Mode",
            "Clears genuinely disposable caches (temp files, thumbnail cache, DNS cache)",
            "Measures before and after values and reports them side by side",
            "Keeps a log and an undo path for everything it changes"
        };

        /// <summary>Capabilities detected on this machine (drives the "N/A" honesty in the UI).</summary>
        public List<CapabilityRow> Capabilities { get; } = new();

        private void BuildCapabilityList()
        {
            var info = _engine.Scanner.LastScanTime == DateTime.MinValue
                ? new SystemInfo()
                : _engine.Scanner.LastScanResult;

            Capabilities.Clear();

            Capabilities.Add(new CapabilityRow
            {
                Name = "Memory counters",
                Available = info.TotalPhysicalMemory > 0,
                Note = info.TotalPhysicalMemory > 0
                    ? "GlobalMemoryStatusEx + performance counters"
                    : "Unavailable"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "CPU temperature sensor",
                Available = info.CpuTemperature.HasValue,
                Note = info.CpuTemperature.HasValue
                    ? $"{info.CpuTemperature:F0} \u00B0C"
                    : "Not exposed by this hardware/driver - the UI shows N/A rather than a guessed value"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "GPU temperature sensor",
                Available = false,
                Note = "Not available through WMI on this machine"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "Per-process GPU usage",
                Available = info.Gpus.Any(g => g.Usage > 0),
                Note = info.Gpus.Any(g => g.Usage > 0)
                    ? "GPU Engine counters available"
                    : "GPU Engine counters unavailable - system-wide GPU usage only"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "Disk SMART / temperature",
                Available = info.SystemDisk?.Temperature != null,
                Note = info.SystemDisk?.Temperature != null
                    ? "Storage driver exposes temperature"
                    : "Not exposed - no fabricated values are shown"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "System Restore",
                Available = WindowsApiHelper.IsAdministrator(),
                Note = WindowsApiHelper.IsAdministrator()
                    ? "Restore points can be created"
                    : "Requires administrator rights"
            });

            Capabilities.Add(new CapabilityRow
            {
                Name = "Local AI (Ollama)",
                Available = _engine.Config.AiEnabled && _engine.Ai.IsAvailable,
                Note = _engine.Config.AiEnabled
                    ? _engine.Ai.IsAvailable
                        ? $"Model {_engine.Config.AiModel} reachable at {_engine.Config.OllamaServerUrl}"
                        : "Not reachable - rule-based analysis is used instead"
                    : "Disabled in settings"
            });
        }

        #endregion

        #region Diagnostics

        /// <summary>Diagnostics text (useful when reporting a problem).</summary>
        public string Diagnostics
        {
            get => _diagnostics;
            private set
            {
                if (SetProperty(ref _diagnostics, value))
                    OnPropertyChanged(nameof(HasDiagnostics));
            }
        }

        public bool HasDiagnostics => !string.IsNullOrEmpty(Diagnostics);

        #endregion

        #region Commands

        public RelayCommand OpenLogFolderCommand { get; }
        public RelayCommand OpenWebsiteCommand { get; }
        public AsyncRelayCommand RunDiagnosticsCommand { get; }
        public RelayCommand CopyDiagnosticsCommand { get; }

        #endregion

        #region Actions

        private async Task RunDiagnosticsAsync()
        {
            await RunGuardedAsync("Collecting diagnostics...", async () =>
            {
                var info = await _engine.ScanAsync().ConfigureAwait(true);

                BuildCapabilityList();

                var sb = new System.Text.StringBuilder();

                sb.AppendLine("AI System Optimizer - diagnostics");
                sb.AppendLine($"Version:        {AppVersion}");
                sb.AppendLine($"Runtime:        {Framework}");
                sb.AppendLine($"Elevated:       {WindowsApiHelper.IsAdministrator()}");
                sb.AppendLine($"Machine:        {Environment.MachineName}");
                sb.AppendLine($"OS:             {info.OsName} build {info.OsBuild} ({info.OsArchitecture})");
                sb.AppendLine($"CPU:            {info.CpuName} ({info.CpuPhysicalCoreCount} cores / " +
                              $"{info.CpuLogicalProcessorCount} threads)");
                sb.AppendLine($"RAM:            {info.FormattedRamUsage}");
                sb.AppendLine($"GPU:            {info.PrimaryGpu?.Name ?? "unknown"}");
                sb.AppendLine($"System disk:    {info.SystemDisk?.Type ?? "unknown"} " +
                              $"({info.SystemDisk?.UsagePercentage:F0}% used)");
                sb.AppendLine();
                sb.AppendLine("Counter availability:");
                sb.AppendLine($"  memory:       {info.TotalPhysicalMemory > 0}");
                sb.AppendLine($"  cpu temp:     {info.CpuTemperature.HasValue}");
                sb.AppendLine($"  gpu engine:   {info.Gpus.Any(g => g.Usage > 0)}");
                sb.AppendLine($"  disk temp:    {info.SystemDisk?.Temperature != null}");
                sb.AppendLine($"  ollama:       {_engine.Config.AiEnabled && _engine.Ai.IsAvailable}");
                sb.AppendLine();
                sb.AppendLine("Last performance counter error:");
                sb.AppendLine($"  {PerformanceCounterHelper.LastError ?? "(none)"}");

                Diagnostics = sb.ToString();
            });
        }

        private void CopyDiagnostics()
        {
            try
            {
                if (!string.IsNullOrEmpty(Diagnostics))
                    System.Windows.Clipboard.SetText(Diagnostics);
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not copy diagnostics: {ex.Message}";
            }
        }

        private void OpenLogFolder()
        {
            try
            {
                var path = AppConstants.LogDirectoryPath;
                System.IO.Directory.CreateDirectory(path);

                Process.Start(new ProcessStartInfo
                {
                    FileName = path,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not open the log folder: {ex.Message}";
            }
        }

        private void OpenWebsite()
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = AppConstants.AppWebsite,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                ErrorMessage = $"Could not open the website: {ex.Message}";
            }
        }

        #endregion
    }

    /// <summary>A capability row on the About page.</summary>
    public sealed class CapabilityRow
    {
        public string Name { get; set; } = string.Empty;
        public bool Available { get; set; }
        public string Note { get; set; } = string.Empty;

        public string StatusText => Available ? "Available" : "N/A";
    }
}

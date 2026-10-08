using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Dashboard: live metrics, health score, memory breakdown and the quick actions
    /// (Analyze / Smart Optimize / Smart RAM clean / Undo).
    /// </summary>
    public sealed class DashboardViewModel : BaseViewModel
    {
        #region Fields

        private readonly OptimizationEngine _engine;

        // Rolling buffers for the real-time charts (60 samples ~ 2 minutes at 2 s interval).
        private const int MaxSamples = 60;

        private SystemInfo _systemInfo = new SystemInfo();
        private MemoryBreakdown _memory = new MemoryBreakdown();

        private double _ramPercent;
        private double _cpuPercent;
        private double _gpuPercent;
        private double _diskPercent;
        private double _networkMbps;
        private int _healthScore;
        private int _ramTargetProgress;
        private string _ramTargetMessage = string.Empty;
        private string _cleanResultMessage = string.Empty;
        private ObservableCollection<SystemInfo.OptimizationRecommendation> _recommendations = new();
        private ObservableCollection<ProcessInfo> _topProcesses = new();

        #endregion

        #region Construction

        public DashboardViewModel(OptimizationEngine engine) : base(engine.Logger)
        {
            _engine = engine;

            RamSamples = new ObservableCollection<double>();
            CpuSamples = new ObservableCollection<double>();
            GpuSamples = new ObservableCollection<double>();
            DiskSamples = new ObservableCollection<double>();

            StartAnalysisCommand = new AsyncRelayCommand(AnalyzeAsync, () => !IsBusy, engine.Logger);
            SmartOptimizeCommand = new AsyncRelayCommand(SmartOptimizeAsync, () => !IsBusy, engine.Logger);
            SmartRamCleanCommand = new AsyncRelayCommand(SmartRamCleanAsync, () => !IsBusy, engine.Logger);
            CancelCommand = new RelayCommand(CancelRunningWork, () => CanCancel);
            ShowProcessesCommand = new RelayCommand(() => RequestNavigation("Processes"));
            ShowOptimizationCommand = new RelayCommand(() => RequestNavigation("Optimization"));
            ShowReportsCommand = new RelayCommand(() => RequestNavigation("History"));
        }

        #endregion

        /// <summary>Latest full snapshot shown on this page.</summary>
        public SystemInfo SystemInfo
        {
            get => _systemInfo;
            private set
            {
                if (SetProperty(ref _systemInfo, value))
                    NotifyScoreProperties();
            }
        }

        #region Collections

        /// <summary>Live RAM samples (percent).</summary>
        public ObservableCollection<double> RamSamples { get; }

        /// <summary>Live CPU samples (percent).</summary>
        public ObservableCollection<double> CpuSamples { get; }

        /// <summary>Live GPU samples (percent).</summary>
        public ObservableCollection<double> GpuSamples { get; }

        /// <summary>Live disk activity samples (percent).</summary>
        public ObservableCollection<double> DiskSamples { get; }

        /// <summary>Rule based recommendations (always available, AI or not).</summary>
        public ObservableCollection<SystemInfo.OptimizationRecommendation> Recommendations
        {
            get => _recommendations;
            private set => SetProperty(ref _recommendations, value);
        }

        /// <summary>Biggest memory consumers, for the "top processes" card.</summary>
        public ObservableCollection<ProcessInfo> TopProcesses
        {
            get => _topProcesses;
            private set => SetProperty(ref _topProcesses, value);
        }

        #endregion

        #region Commands

        public AsyncRelayCommand StartAnalysisCommand { get; }

        /// <summary>Stops the work the dashboard is currently doing.</summary>
        public RelayCommand CancelCommand { get; }
        public AsyncRelayCommand SmartOptimizeCommand { get; }
        public AsyncRelayCommand SmartRamCleanCommand { get; }
        public RelayCommand ShowProcessesCommand { get; }
        public RelayCommand ShowOptimizationCommand { get; }
        public RelayCommand ShowReportsCommand { get; }

        #endregion

        #region Live metrics

        public double RamPercent
        {
            get => _ramPercent;
            private set
            {
                if (SetProperty(ref _ramPercent, value))
                {
                    OnPropertyChanged(nameof(RamPercentText));
                    OnPropertyChanged(nameof(RamUsedText));
                    OnPropertyChanged(nameof(IsRamTargetMet));
                }
            }
        }

        public double CpuPercent
        {
            get => _cpuPercent;
            private set
            {
                if (SetProperty(ref _cpuPercent, value))
                    OnPropertyChanged(nameof(CpuPercentText));
            }
        }

        public double GpuPercent
        {
            get => _gpuPercent;
            private set
            {
                if (SetProperty(ref _gpuPercent, value))
                    OnPropertyChanged(nameof(GpuPercentText));
            }
        }

        public double DiskPercent
        {
            get => _diskPercent;
            private set
            {
                if (SetProperty(ref _diskPercent, value))
                    OnPropertyChanged(nameof(DiskPercentText));
            }
        }

        public double NetworkMbps
        {
            get => _networkMbps;
            private set
            {
                if (SetProperty(ref _networkMbps, value))
                    OnPropertyChanged(nameof(NetworkText));
            }
        }

        public string RamPercentText => $"{RamPercent:F0}%";
        public string CpuPercentText => $"{CpuPercent:F0}%";
        public string GpuPercentText => GpuPercent > 0 ? $"{GpuPercent:F0}%" : "N/A";
        public string DiskPercentText => $"{DiskPercent:F0}%";

        public string RamUsedText =>
            $"{MemoryBreakdown.Format(Memory.UsedPhysical)} / {MemoryBreakdown.Format(Memory.TotalPhysical)}";

        public string NetworkText =>
            $"{(NetworkMbps >= 1 ? $"{NetworkMbps:F1} MB/s" : $"{NetworkMbps * 1000:F0} KB/s")}";

        /// <summary>Health score 0-100 produced by the scoring rules.</summary>
        public int HealthScore
        {
            get => _healthScore;
            private set
            {
                if (SetProperty(ref _healthScore, value))
                    OnPropertyChanged(nameof(HealthScoreText));
            }
        }

        public string HealthScoreText => $"{HealthScore}/100";

        /// <summary>How far the safe optimisations get towards the user's RAM target (0-100).</summary>
        public int RamTargetProgress
        {
            get => _ramTargetProgress;
            private set => SetProperty(ref _ramTargetProgress, value);
        }

        /// <summary>Honest statement about whether the RAM target is reachable.</summary>
        public string RamTargetMessage
        {
            get => _ramTargetMessage;
            private set => SetProperty(ref _ramTargetMessage, value);
        }

        /// <summary>True when the configured RAM target is currently met.</summary>
        public bool IsRamTargetMet => RamPercent <= _engine.Config.TargetRamUsage;

        /// <summary>Result text of the last SMART RAM CLEAN run.</summary>
        public string CleanResultMessage
        {
            get => _cleanResultMessage;
            private set
            {
                if (SetProperty(ref _cleanResultMessage, value))
                    OnPropertyChanged(nameof(HasCleanResult));
            }
        }

        public bool HasCleanResult => !string.IsNullOrEmpty(CleanResultMessage);

        /// <summary>Detailed memory breakdown shown in the RAM card.</summary>
        public MemoryBreakdown Memory
        {
            get => _memory;
            private set
            {
                if (SetProperty(ref _memory, value))
                {
                    OnPropertyChanged(nameof(RamUsedText));
                    OnPropertyChanged(nameof(MemoryFootnote));
                }
            }
        }

        /// <summary>
        /// The explanation the specification asks for: cached/standby memory is not a problem.
        /// </summary>
        public string MemoryFootnote =>
            "Windows deliberately keeps RAM in the standby cache to speed things up. " +
            "That memory is still available to applications, so a high 'used' figure is not automatically bad.";

        /// <summary>Score for the current RAM usage (0-100, higher is better).</summary>
        public int RamScore => GetScore("RAM");

        public int CpuScore => GetScore("CPU");

        public int DiskScore => GetScore("Disk");

        public int StartupScore => GetScore("Startup");

        public int BackgroundScore => GetScore("Background Apps");

        private int GetScore(string key)
        {
            return SystemInfo.PerformanceScores.TryGetValue(key, out var score) ? score : 0;
        }

        /// <summary>Hardware summary line for the header card.</summary>
        public string HardwareSummary
        {
            get
            {
                var gpu = SystemInfo.PrimaryGpu?.Name ?? "Unknown GPU";
                var disk = SystemInfo.SystemDisk?.Type ?? "Unknown disk";

                return $"{SystemInfo.CpuName} \u2022 {gpu} \u2022 {disk}";
            }
        }

        /// <summary>Security status line (always states that security is untouched).</summary>
        public string SecuritySummary
        {
            get
            {
                var defender = SystemInfo.IsRealTimeProtectionEnabled ? "Defender active" : "Defender status unknown";
                var firewall = SystemInfo.IsFirewallEnabled ? "Firewall on" : "Firewall off";
                var uac = SystemInfo.IsUacEnabled ? "UAC on" : "UAC off";

                return $"{defender} \u2022 {firewall} \u2022 {uac} (never modified by this app)";
            }
        }

        /// <summary>Summary of how many items are safe to optimise right now.</summary>
        public string OptimizationSummary
        {
            get
            {
                var optimizable = SystemScoring.GetOptimizableProcesses(SystemInfo);

                if (optimizable.Count == 0)
                    return "Nothing safe to close right now.";

                var totalMb = optimizable.Sum(p => p.WorkingSet) / (1024.0 * 1024.0);

                return $"{optimizable.Count} inactive application(s) can be closed safely " +
                       $"\u2014 about {totalMb:F0} MB.";
            }
        }

        #endregion

        #region Snapshot handling

        /// <summary>Apply a full scan result.</summary>
        public void ApplySystemInfo(SystemInfo info)
        {
            SystemInfo = info;
            Memory = _engine.GetMemoryBreakdown(info);

            RamPercent = info.RamUsagePercentage;
            CpuPercent = info.CpuUsage;
            GpuPercent = info.TotalGpuUsage;
            DiskPercent = info.TotalDiskActivity;
            NetworkMbps = (info.NetworkDownloadSpeed + info.NetworkUploadSpeed) / (1024.0 * 1024.0);

            HealthScore = info.SystemHealthScore;
            RamTargetProgress = _engine.GetRamTargetProgress(info);
            RamTargetMessage = _engine.DescribeRamTarget(info);

            Recommendations = new ObservableCollection<SystemInfo.OptimizationRecommendation>(info.Recommendations);

            TopProcesses = new ObservableCollection<ProcessInfo>(
                info.Processes
                    .Where(p => !p.IsWindowsProcess && !p.IsDriver)
                    .OrderByDescending(p => p.WorkingSet)
                    .Take(8));

            SeedSamples(RamSamples, RamPercent);
            SeedSamples(CpuSamples, CpuPercent);
            SeedSamples(GpuSamples, GpuPercent);
            SeedSamples(DiskSamples, DiskPercent);

            NotifyScoreProperties();
        }

        /// <summary>Apply a cheap live sample (dashboard only).</summary>
        public void ApplyLiveSample(SystemInfo sample)
        {
            if (sample.TotalPhysicalMemory <= 0)
                return;

            RamPercent = sample.RamUsagePercentage;
            CpuPercent = sample.CpuUsage;
            DiskPercent = sample.TotalDiskActivity;
            NetworkMbps = (sample.NetworkDownloadSpeed + sample.NetworkUploadSpeed) / (1024.0 * 1024.0);

            // GPU counters are comparatively expensive: only refresh them on full scans.
            AppendSample(RamSamples, RamPercent);
            AppendSample(CpuSamples, CpuPercent);
            AppendSample(DiskSamples, DiskPercent);

            Memory = new MemoryBreakdown
            {
                TotalPhysical = sample.TotalPhysicalMemory,
                AvailablePhysical = sample.AvailablePhysicalMemory,
                UsedPhysical = sample.UsedPhysicalMemory,
                Cached = sample.CachedMemory,
                Standby = sample.StandbyMemory,
                Free = sample.FreeMemory,
                PagedPool = sample.PagedPoolMemory,
                NonPagedPool = sample.NonPagedPoolMemory,
                Committed = Memory.Committed,
                CommitLimit = Memory.CommitLimit,
                PageFileTotal = Memory.PageFileTotal,
                PageFileAvailable = Memory.PageFileAvailable,
                WorkingSetTotal = Memory.WorkingSetTotal
            };
        }

        private static void SeedSamples(ObservableCollection<double> buffer, double value)
        {
            buffer.Clear();

            for (int i = 0; i < MaxSamples; i++)
            {
                buffer.Add(value);
            }
        }

        private static void AppendSample(ObservableCollection<double> buffer, double value)
        {
            buffer.Add(value);

            while (buffer.Count > MaxSamples)
            {
                buffer.RemoveAt(0);
            }
        }

        private void NotifyScoreProperties()
        {
            OnPropertyChanged(nameof(RamScore));
            OnPropertyChanged(nameof(CpuScore));
            OnPropertyChanged(nameof(DiskScore));
            OnPropertyChanged(nameof(StartupScore));
            OnPropertyChanged(nameof(BackgroundScore));
            OnPropertyChanged(nameof(HardwareSummary));
            OnPropertyChanged(nameof(SecuritySummary));
            OnPropertyChanged(nameof(OptimizationSummary));
            OnPropertyChanged(nameof(IsRamTargetMet));
        }

        #endregion

        #region Cancellation

        /// <summary>Cancellation source for whatever the dashboard is currently doing.</summary>
        private CancellationTokenSource? _operationCts;

        /// <summary>True while the dashboard has work the user is allowed to stop.</summary>
        public bool CanCancel => IsBusy && _operationCts != null && !_operationCts.IsCancellationRequested;

        /// <summary>Stop the running analysis or plan build.</summary>
        private void CancelRunningWork()
        {
            var cts = _operationCts;

            if (cts == null || cts.IsCancellationRequested)
                return;

            Logger.Info("DashboardViewModel", "User requested cancellation of the running dashboard work.");

            _engine.CancelExecution();

            try
            {
                cts.Cancel();
            }
            catch (ObjectDisposedException)
            {
                // The operation already finished.
            }

            BusyMessage = "Cancelling...";
            OnPropertyChanged(nameof(CanCancel));
            CancelCommand.RaiseCanExecuteChanged();
        }

        /// <summary>Start a cancellable operation and return its token.</summary>
        private CancellationToken BeginOperation()
        {
            EndOperation();
            _operationCts = new CancellationTokenSource();
            OnPropertyChanged(nameof(CanCancel));
            CancelCommand.RaiseCanExecuteChanged();
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
                }
            }

            OnPropertyChanged(nameof(CanCancel));
            CancelCommand.RaiseCanExecuteChanged();
        }

        #endregion

        #region Actions

        private async Task AnalyzeAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Analysing the system...", async () =>
            {
                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);
                ErrorMessage = string.Empty;
            });

            EndOperation();
        }

        private async Task SmartOptimizeAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Preparing a safe optimisation...", async () =>
            {
                var plan = await _engine.CreateQuickPlanAsync(SystemInfo).ConfigureAwait(true);

                if (plan == null || plan.Actions.Count == 0)
                {
                    CleanResultMessage =
                        "No safe actions were available. Everything that uses meaningful memory is either " +
                        "in use, protected, or genuinely required by Windows.";
                    return;
                }

                // Publishing the plan makes the Optimisation page show its preview.
                PlanPrepared?.Invoke(this, plan);
                RequestNavigation("Optimization");
            });

            EndOperation();
        }

        private async Task SmartRamCleanAsync()
        {
            var token = BeginOperation();

            await RunGuardedAsync("Cleaning disposable caches...", async () =>
            {
                var result = await Task.Run(() => _engine.CleanSafeCaches()).ConfigureAwait(true);

                var builder = new StringBuilder();
                builder.AppendLine(result.Message);

                foreach (var detail in result.Details)
                {
                    builder.AppendLine("\u2022 " + detail);
                }

                CleanResultMessage = builder.ToString().TrimEnd();

                // Refresh the metrics so the user sees the true effect (usually small, sometimes none).
                var info = await _engine.ScanAsync(token).ConfigureAwait(true);
                ApplySystemInfo(info);
            });

            EndOperation();
        }

        /// <summary>Raised when this page produced a plan the shell should display.</summary>
        public event EventHandler<OptimizationPlan>? PlanPrepared;

        #endregion
    }
}

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Reads the state of the machine. Read-only: this class never modifies anything.
    ///
    /// Pipeline position:
    ///   SystemScanner -> Rules Engine -> Risk Analyzer -> (AI) -> Planner -> SafetyValidator -> SafeExecutor
    /// </summary>
    public class SystemScanner : IDisposable
    {
        #region Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SemaphoreSlim _scanGate = new SemaphoreSlim(1, 1);
        private SystemInfo _lastScanResult = new SystemInfo();
        private CancellationTokenSource? _cancellation;
        private bool _disposed;

        #endregion

        #region Events

        /// <summary>Raised when a scan starts.</summary>
        public event EventHandler<ScanEventArgs>? ScanStarted;

        /// <summary>Raised when a scan completes successfully.</summary>
        public event EventHandler<ScanEventArgs>? ScanCompleted;

        /// <summary>Raised when a scan fails or is cancelled.</summary>
        public event EventHandler<ScanEventArgs>? ScanFailed;

        /// <summary>Raised while a scan makes progress (0-100).</summary>
        public event EventHandler<ScanProgressEventArgs>? ScanProgress;

        #endregion

        #region Construction

        public SystemScanner(ILogger? logger = null, AppConfig? config = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
        }

        #endregion

        #region Properties

        /// <summary>Result of the most recent scan.</summary>
        public SystemInfo LastScanResult => _lastScanResult;

        /// <summary>When the most recent scan finished.</summary>
        public DateTime LastScanTime { get; private set; } = DateTime.MinValue;

        /// <summary>True while a scan is in flight.</summary>
        public bool IsScanning { get; private set; }

        /// <summary>Time elapsed since the last completed scan.</summary>
        public TimeSpan TimeSinceLastScan => LastScanTime == DateTime.MinValue
            ? TimeSpan.MaxValue
            : DateTime.Now - LastScanTime;

        #endregion

        #region Public API

        /// <summary>
        /// Perform a full scan asynchronously.
        /// </summary>
        public Task<SystemInfo> ScanAsync(CancellationToken cancellationToken = default)
        {
            return Task.Run(() => ScanCore(cancellationToken), cancellationToken);
        }

        /// <summary>
        /// Perform a full scan synchronously.
        /// </summary>
        public SystemInfo Scan(CancellationToken cancellationToken = default)
        {
            return ScanCore(cancellationToken);
        }

        /// <summary>
        /// Light-weight scan (OS + CPU + memory) used by the tray/dashboard refresh.
        /// </summary>
        public SystemInfo QuickScan()
        {
            var info = new SystemInfo { CollectedAt = DateTime.Now };

            CollectOsInfo(info);
            CollectMemoryInfo(info);
            info.CpuUsage = PerformanceCounterHelper.GetCpuUsage();
            info.CpuCoreCount = PerformanceCounterHelper.GetPhysicalCoreCount();
            info.CpuPhysicalCoreCount = info.CpuCoreCount;
            info.CpuLogicalProcessorCount = Environment.ProcessorCount;
            info.TotalProcessCount = WindowsApiHelper.GetAllProcesses().Length;
            info.CurrentPowerMode = GetPowerMode();
            info.IsOnBattery = WindowsApiHelper.IsOnBattery();

            SystemScoring.CalculatePerformanceScores(info);

            return info;
        }

        /// <summary>
        /// Refresh a single component of the last snapshot.
        /// </summary>
        public SystemInfo RescanComponent(ScanComponent component, CancellationToken cancellationToken = default)
        {
            var result = _lastScanResult.Clone();

            switch (component)
            {
                case ScanComponent.Processes:
                    result.Processes = CollectProcesses(cancellationToken);
                    result.TotalProcessCount = result.Processes.Count;
                    break;

                case ScanComponent.Memory:
                    CollectMemoryInfo(result);
                    break;

                case ScanComponent.Cpu:
                    result.CpuUsage = PerformanceCounterHelper.GetCpuUsage();
                    result.CpuCoreUsage = PerformanceCounterHelper.GetCpuUsagePerCore();
                    result.CpuTemperature = PerformanceCounterHelper.GetCpuTemperature();
                    var (current, max) = PerformanceCounterHelper.GetCpuClockMhz();
                    result.CpuBaseClock = current;
                    result.CpuMaxClock = max;
                    break;

                case ScanComponent.Disks:
                    result.Disks = CollectDisks();
                    break;

                case ScanComponent.Gpus:
                    result.Gpus = CollectGpus();
                    result.TotalGpuUsage = result.Gpus.Count > 0
                        ? (float)result.Gpus.Average(g => g.Usage)
                        : 0f;
                    break;

                case ScanComponent.Services:
                    result.Services = CollectServices();
                    break;

                case ScanComponent.Startup:
                    result.StartupItems = CollectStartupItems();
                    break;

                case ScanComponent.Network:
                    result.NetworkAdapters = CollectNetworkAdapters();
                    break;

                case ScanComponent.Security:
                    CollectSecurityInfo(result);
                    break;

                case ScanComponent.All:
                    return ScanCore(cancellationToken);
            }

            result.CollectedAt = DateTime.Now;
            _lastScanResult = result;
            LastScanTime = DateTime.Now;

            return result;
        }

        /// <summary>
        /// Cancel an in-flight scan.
        /// </summary>
        public void CancelScan()
        {
            try
            {
                _cancellation?.Cancel();
            }
            catch { }
        }

        /// <summary>
        /// Is the user currently idle (used by auto-optimize)?
        /// </summary>
        public bool IsUserIdle(int? thresholdSeconds = null)
        {
            var threshold = thresholdSeconds ?? _config.IdleThreshold;
            return WindowsApiHelper.IsSystemIdle(threshold);
        }

        /// <summary>
        /// Average CPU usage over a window - far more meaningful than a single sample.
        /// </summary>
        public float MeasureAverageCpuUsage(int sampleCount = 3, int intervalMs = 500)
        {
            if (sampleCount <= 0) return 0f;

            float total = 0;
            var taken = 0;

            for (int i = 0; i < sampleCount; i++)
            {
                total += PerformanceCounterHelper.GetCpuUsage();
                taken++;

                if (i < sampleCount - 1)
                    Thread.Sleep(intervalMs);
            }

            return taken == 0 ? 0f : total / taken;
        }

        #endregion

        #region Scan pipeline

        private SystemInfo ScanCore(CancellationToken cancellationToken)
        {
            _scanGate.Wait(cancellationToken);

            try
            {
                if (IsScanning)
                {
                    _logger.Warning("SystemScanner", "A scan is already running - returning the previous snapshot");
                    return _lastScanResult;
                }

                IsScanning = true;
                _cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

                var startedAt = DateTime.Now;
                var stopwatch = Stopwatch.StartNew();

                ScanStarted?.Invoke(this, new ScanEventArgs { Timestamp = startedAt });

                try
                {
                    var result = new SystemInfo();

                    ReportProgress(5, "Reading operating system information...");
                    CollectOsInfo(result);
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(15, "Reading CPU information...");
                    if (!_config.ScanSkipCpuSampling)
                    {
                        result.CpuUsage = PerformanceCounterHelper.GetCpuUsage();
                        result.CpuCoreUsage = PerformanceCounterHelper.GetCpuUsagePerCore();
                    }
                    else
                    {
                        result.CpuUsage = PerformanceCounterHelper.GetCpuUsage();
                        result.CpuCoreUsage = Array.Empty<float>();
                    }

                    result.CpuCoreCount = PerformanceCounterHelper.GetPhysicalCoreCount();
                    result.CpuPhysicalCoreCount = result.CpuCoreCount;
                    result.CpuLogicalProcessorCount = Environment.ProcessorCount;
                    result.CpuTemperature = PerformanceCounterHelper.GetCpuTemperature();

                    var (currentClock, maxClock) = PerformanceCounterHelper.GetCpuClockMhz();
                    result.CpuBaseClock = currentClock;
                    result.CpuMaxClock = maxClock;
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(28, "Reading memory information...");
                    CollectMemoryInfo(result);

                    ReportProgress(38, "Reading GPU information...");
                    result.Gpus = CollectGpus();
                    result.TotalGpuUsage = result.Gpus.Count > 0 ? (float)result.Gpus.Average(g => g.Usage) : 0f;
                    result.TotalGpuMemoryUsage = result.Gpus.Sum(g => g.UsedMemory);
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(48, "Reading disk information...");
                    result.Disks = CollectDisks();
                    result.TotalDiskReadSpeed = PerformanceCounterHelper.GetDiskReadBytesPerSecond();
                    result.TotalDiskWriteSpeed = PerformanceCounterHelper.GetDiskWriteBytesPerSecond();
                    result.TotalDiskActivity = PerformanceCounterHelper.GetDiskActivity();
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(60, "Enumerating processes...");
                    result.Processes = CollectProcesses(cancellationToken);
                    result.TotalProcessCount = result.Processes.Count;
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(75, "Enumerating services...");
                    result.Services = CollectServices();
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(85, "Reading start-up programs...");
                    result.StartupItems = CollectStartupItems();
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(92, "Reading network...");
                    result.NetworkAdapters = CollectNetworkAdapters();
                    result.NetworkDownloadSpeed = PerformanceCounterHelper.GetNetworkDownloadSpeed();
                    result.NetworkUploadSpeed = PerformanceCounterHelper.GetNetworkUploadSpeed();
                    cancellationToken.ThrowIfCancellationRequested();

                    ReportProgress(96, "Reading security status...");
                    CollectSecurityInfo(result);
                    CollectPowerInfo(result);

                    ReportProgress(98, "Calculating scores...");
                    CalculateCounts(result);
                    SystemScoring.CalculatePerformanceScores(result);
                    SystemScoring.CalculateOptimizationInfo(result, _config);

                    result.CollectedAt = DateTime.Now;

                    ReportProgress(100, "Scan complete");

                    _lastScanResult = result;
                    LastScanTime = DateTime.Now;

                    _logger.Info("SystemScanner",
                        $"Scan finished in {stopwatch.ElapsedMilliseconds} ms - " +
                        $"{result.TotalProcessCount} processes, RAM {result.RamUsagePercentage:F1}%, CPU {result.CpuUsage:F1}%");

                    ScanCompleted?.Invoke(this, new ScanEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Duration = stopwatch.Elapsed,
                        SystemInfo = result
                    });

                    return result;
                }
                catch (OperationCanceledException)
                {
                    _logger.Warning("SystemScanner", "Scan cancelled");

                    ScanFailed?.Invoke(this, new ScanEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Duration = stopwatch.Elapsed,
                        ErrorMessage = "Scan was cancelled"
                    });

                    throw;
                }
                catch (Exception ex)
                {
                    _logger.Error("SystemScanner", "Scan failed", null, ex);

                    ScanFailed?.Invoke(this, new ScanEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Duration = stopwatch.Elapsed,
                        ErrorMessage = ex.Message,
                        Exception = ex
                    });

                    throw;
                }
            }
            finally
            {
                IsScanning = false;
                _scanGate.Release();

                try
                {
                    _cancellation?.Dispose();
                }
                catch { }

                _cancellation = null;
            }
        }

        private void ReportProgress(int percentage, string message)
        {
            try
            {
                ScanProgress?.Invoke(this, new ScanProgressEventArgs
                {
                    Timestamp = DateTime.Now,
                    Percentage = percentage,
                    Message = message
                });
            }
            catch { }
        }

        #endregion

        #region Collectors

        private void CollectOsInfo(SystemInfo info)
        {
            try
            {
                info.OsName = "Windows";
                info.OsVersion = Environment.OSVersion.Version.ToString();
                info.OsBuild = Environment.OSVersion.Version.Build.ToString();
                info.OsArchitecture = Environment.Is64BitOperatingSystem ? "x64" : "x86";

                var version = Environment.OSVersion.Version;
                info.IsWindows11 = version.Major >= 10 && version.Build >= 22000;
                info.IsWindows10 = version.Major >= 10 && version.Build >= 10240 && version.Build < 22000;

                info.ComputerName = Environment.MachineName;
                info.UserName = Environment.UserName;
                info.IsAdministrator = WindowsApiHelper.IsAdministrator();
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read OS information", null, ex);
            }
        }

        private void CollectMemoryInfo(SystemInfo info)
        {
            try
            {
                info.TotalPhysicalMemory = PerformanceCounterHelper.GetTotalPhysicalMemory();
                info.AvailablePhysicalMemory = PerformanceCounterHelper.GetAvailablePhysicalMemory();
                info.CachedMemory = PerformanceCounterHelper.GetCachedMemory();
                info.StandbyMemory = PerformanceCounterHelper.GetStandbyMemory();
                info.FreeMemory = PerformanceCounterHelper.GetFreeMemory();
                info.PagedPoolMemory = PerformanceCounterHelper.GetPagedPoolMemory();
                info.NonPagedPoolMemory = PerformanceCounterHelper.GetNonPagedPoolMemory();
                info.PageFileUsage = PerformanceCounterHelper.GetPageFileUsage();
                info.PageFileLimit = PerformanceCounterHelper.GetPageFileLimit();
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read memory information", null, ex);
            }
        }

        private List<SystemInfo.GpuInfo> CollectGpus()
        {
            var result = new List<SystemInfo.GpuInfo>();

            try
            {
                var gpus = PerformanceCounterHelper.GetGpuInformation();

                foreach (var gpu in gpus)
                {
                    result.Add(new SystemInfo.GpuInfo
                    {
                        Name = gpu.Name,
                        Manufacturer = gpu.Manufacturer,
                        Type = gpu.Type,
                        TotalMemory = gpu.TotalMemory,
                        UsedMemory = gpu.UsedMemory,
                        Usage = gpu.Usage,
                        Temperature = gpu.Temperature,
                        DriverVersion = gpu.DriverVersion,
                        PnpDeviceId = gpu.PnpDeviceId,
                        IsPrimary = result.Count == 0
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read GPU information", null, ex);
            }

            return result;
        }

        private List<SystemInfo.DiskInfo> CollectDisks()
        {
            var result = new List<SystemInfo.DiskInfo>();

            try
            {
                var readTotals = PerformanceCounterHelper.GetDiskReadBytesPerSecond();
                var writeTotals = PerformanceCounterHelper.GetDiskWriteBytesPerSecond();
                var activity = PerformanceCounterHelper.GetDiskActivity();
                var queue = PerformanceCounterHelper.GetDiskQueueLength();
                var responseTime = PerformanceCounterHelper.GetDiskResponseTimeMs();
                var temperature = PerformanceCounterHelper.GetDiskTemperature();

                var drives = PerformanceCounterHelper.GetDiskDriveInfo();
                var systemDiskCount = Math.Max(1, drives.Count(d => d.IsSystemDisk));

                foreach (var drive in drives)
                {
                    var isSystem = drive.IsSystemDisk;

                    result.Add(new SystemInfo.DiskInfo
                    {
                        DriveLetter = drive.DriveLetter,
                        Label = drive.Label,
                        Type = drive.Type,
                        FileSystem = drive.FileSystem,
                        TotalSize = drive.TotalSize,
                        FreeSpace = drive.FreeSpace,
                        IsSystemDisk = isSystem,
                        IsBootDisk = isSystem,
                        HealthStatus = "Unknown", // Only reported when a real SMART reading is available.
                        Temperature = temperature,
                        // Throughput counters are system wide; attribute to the system disk
                        // and leave other volumes at 0 rather than inventing per-volume numbers.
                        ReadBytesPerSecond = isSystem ? readTotals / systemDiskCount : 0,
                        WriteBytesPerSecond = isSystem ? writeTotals / systemDiskCount : 0,
                        ActiveTime = isSystem ? activity : 0f,
                        QueueLength = isSystem ? queue : 0f,
                        ResponseTimeMs = isSystem ? responseTime : 0f
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read disk information", null, ex);
            }

            return result;
        }

        private List<ProcessInfo> CollectProcesses(CancellationToken cancellationToken)
        {
            var processes = new List<ProcessInfo>();

            try
            {
                // Sample CPU once for the whole machine so per-process cost stays low.
                var processList = Process.GetProcesses();

                foreach (var process in processList)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    try
                    {
                        var info = new ProcessInfo(process);
                        ClassifyProcess(info);
                        processes.Add(info);
                    }
                    catch { }
                    finally
                    {
                        try { process.Dispose(); } catch { }
                    }
                }

                // One shared CPU sample per process batch (cheap, honest).
                MeasurePerProcessCpu(processes, cancellationToken);

                processes = processes
                    .OrderByDescending(p => p.WorkingSet)
                    .ToList();
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not enumerate processes", null, ex);
            }

            return processes;
        }

        /// <summary>
        /// Classify a process (category, risk, flags) using the rules engine constants
        /// and the user's whitelist / blacklist configuration.
        /// </summary>
        private void ClassifyProcess(ProcessInfo info)
        {
            info.IsService = ProcessHelper.IsServiceProcess(info.Id);
            info.Category = CriticalProcesses.GetProcessCategory(info.Name, info.Path, info.IsService);
            info.RiskLevel = CriticalProcesses.GetProcessRiskLevel(info.Name, info.Category);
            info.IsWindowsProcess = CriticalProcesses.IsWindowsSystemProcess(info.Name);
            info.IsDriver = CriticalProcesses.IsDriverProcess(info.Name);
            info.IsSecurity = CriticalProcesses.IsSecurityProcess(info.Name) ||
                              info.Category == ProcessCategory.Security;
            info.HasVisibleWindow = WindowsApiHelper.HasVisibleWindow(info.Id);
            info.IsForeground = WindowsApiHelper.IsForegroundProcess(info.Id);

            // A process counts as "in use" when it owns a visible window, owns the foreground window,
            // or is a fullscreen foreground window (an exclusive-fullscreen game). The union of these
            // signals is deliberately generous: a false "in use" only means the optimiser declines to
            // close something, while a false "idle" would close a program the user is using.
            info.IsActive = info.HasVisibleWindow ||
                            info.IsForeground ||
                            (info.IsForeground && WindowsApiHelper.IsForegroundWindowFullscreen());
            info.SessionId = WindowsApiHelper.GetProcessSessionId(info.Id);

            // "Background application" is a user program that behaves like a service:
            // it is running, has no window, and was started by the user rather than Windows.
            if (info.Category == ProcessCategory.UserApplication && !info.HasVisibleWindow)
            {
                info.Category = ProcessCategory.BackgroundApplication;
            }

            info.IsUserWhitelisted = IsUserWhitelisted(info);
            info.IsBlacklisted = IsBlacklisted(info);

            if (info.IsBlacklisted)
            {
                info.RiskLevel = RiskLevel.Critical;
                info.CanOptimize = false;
            }
        }

        private bool IsUserWhitelisted(ProcessInfo info)
        {
            return MatchesAny(_config.WhitelistedProcesses, info);
        }

        private bool IsBlacklisted(ProcessInfo info)
        {
            if (CriticalProcesses.IsCritical(info.Name))
                return true;

            return MatchesAny(_config.BlacklistedProcesses, info);
        }

        private static bool MatchesAny(IEnumerable<string> patterns, ProcessInfo info)
        {
            foreach (var pattern in patterns)
            {
                if (string.IsNullOrWhiteSpace(pattern)) continue;

                if (string.Equals(pattern, info.Name, StringComparison.OrdinalIgnoreCase)) return true;
                if (string.Equals(pattern, info.DisplayName, StringComparison.OrdinalIgnoreCase)) return true;
                if (string.Equals(pattern, info.Path, StringComparison.OrdinalIgnoreCase)) return true;
            }

            return false;
        }

        /// <summary>
        /// Measure CPU for all processes using two samples of TotalProcessorTime.
        /// This is the standard Windows approach (same as Task Manager) and costs one sleep.
        /// </summary>
        private void MeasurePerProcessCpu(List<ProcessInfo> processes, CancellationToken cancellationToken)
        {
            const int sampleWindowMs = 600;
            if (processes.Count == 0) return;

            var snapshot = new Dictionary<int, TimeSpan>();
            var timestamp = DateTime.UtcNow;

            foreach (var info in processes)
            {
                try
                {
                    using (var process = Process.GetProcessById(info.Id))
                    {
                        snapshot[info.Id] = process.TotalProcessorTime;
                    }
                }
                catch
                {
                    // Process exited or is protected - leave its CPU at 0.
                    snapshot[info.Id] = TimeSpan.Zero;
                }
            }

            cancellationToken.ThrowIfCancellationRequested();
            Thread.Sleep(sampleWindowMs);
            cancellationToken.ThrowIfCancellationRequested();

            var elapsed = (DateTime.UtcNow - timestamp).TotalMilliseconds;
            if (elapsed <= 0) return;

            var cores = Math.Max(1, Environment.ProcessorCount);

            foreach (var info in processes)
            {
                if (!snapshot.TryGetValue(info.Id, out var before) || before == TimeSpan.Zero)
                {
                    info.CpuUsage = 0f;
                    continue;
                }

                try
                {
                    using (var process = Process.GetProcessById(info.Id))
                    {
                        var after = process.TotalProcessorTime;
                        var cpuMs = (after - before).TotalMilliseconds;

                        // Normalised against all cores, matching Task Manager's behaviour.
                        var usage = cpuMs / (elapsed * cores) * 100.0;
                        info.CpuUsage = (float)Math.Max(0, Math.Min(100, usage));
                        info.TotalProcessorTime = after;
                    }
                }
                catch
                {
                    info.CpuUsage = 0f;
                }
            }
        }

        private List<SystemInfo.ServiceInfo> CollectServices()
        {
            var result = new List<SystemInfo.ServiceInfo>();

            try
            {
                var services = System.ServiceProcess.ServiceController.GetServices();

                foreach (var service in services)
                {
                    try
                    {
                        var isWindowsService = CriticalProcesses.IsWindowsSystemProcess(service.ServiceName) ||
                                               service.ServiceName.StartsWith("Windows", StringComparison.OrdinalIgnoreCase);

                        var serviceInfo = new SystemInfo.ServiceInfo
                        {
                            Name = service.ServiceName,
                            DisplayName = service.DisplayName,
                            Description = service.ServiceType.ToString(),
                            Status = service.Status.ToString(),
                            StartType = service.StartType.ToString(),
                            IsWindowsService = isWindowsService,
                            IsCritical = CriticalProcesses.IsCritical(service.ServiceName) ||
                                         _config.BlacklistedServices.Contains(service.ServiceName, StringComparer.OrdinalIgnoreCase),
                            Account = service.ServiceName
                        };

                        serviceInfo.RiskLevel = serviceInfo.IsCritical
                            ? RiskLevel.Critical
                            : isWindowsService ? RiskLevel.High : RiskLevel.Medium;

                        result.Add(serviceInfo);
                    }
                    catch { }
                    finally
                    {
                        try { service.Dispose(); } catch { }
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not enumerate services", null, ex);
            }

            return result.OrderBy(s => s.DisplayName, StringComparer.OrdinalIgnoreCase).ToList();
        }

        private List<SystemInfo.StartupItem> CollectStartupItems()
        {
            var result = new List<SystemInfo.StartupItem>();

            try
            {
                result = WindowsApiHelper.GetStartupItems();

                foreach (var item in result)
                {
                    item.IsBlacklisted = item.IsWindowsItem ||
                                         item.RiskLevel == RiskLevel.High ||
                                         item.RiskLevel == RiskLevel.Critical ||
                                         _config.BlacklistedStartupItems.Contains(item.Name, StringComparer.OrdinalIgnoreCase);

                    item.RiskLevel = DetermineStartupRisk(item);
                    item.Impact = DetermineStartupImpact(item);
                    item.EstimatedRamUsage = EstimateStartupRam(item);
                    item.Recommendation = BuildStartupRecommendation(item);
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not enumerate start-up items", null, ex);
            }

            return result
                .OrderByDescending(i => i.ImpactScore)
                .ThenBy(i => i.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private static RiskLevel DetermineStartupRisk(SystemInfo.StartupItem item)
        {
            if (item.IsWindowsItem || item.IsBlacklisted)
                return RiskLevel.Critical;

            var haystack = $"{item.Path} {item.CommandLine}".ToLowerInvariant();

            if (haystack.Contains("\\windows\\") || haystack.Contains("\\system32\\"))
                return RiskLevel.High;

            if (haystack.Contains("defender") || haystack.Contains("security") ||
                haystack.Contains("firewall") || haystack.Contains("antivirus"))
                return RiskLevel.High;

            if (haystack.Contains("onedrive") || haystack.Contains("driver") ||
                haystack.Contains("audio") || haystack.Contains("touchpad"))
                return RiskLevel.Medium;

            return RiskLevel.Low;
        }

        private static string DetermineStartupImpact(SystemInfo.StartupItem item)
        {
            // Impact is judged from what the entry actually costs once it is running.
            var running = ProcessHelper.GetProcessesByName(
                System.IO.Path.GetFileNameWithoutExtension(item.Name));

            var workingSet = running.Count == 0 ? 0 : running.Sum(p => p.WorkingSet);

            if (workingSet >= 150 * 1024 * 1024) return "High";
            if (workingSet >= 50 * 1024 * 1024) return "Medium";
            if (running.Count > 0) return "Low";

            // Not currently running: base it on the known app weight.
            return item.IsWindowsItem ? "Low" : "Medium";
        }

        private static long EstimateStartupRam(SystemInfo.StartupItem item)
        {
            var processName = System.IO.Path.GetFileNameWithoutExtension(item.Name);
            var running = ProcessHelper.GetProcessesByName(processName);

            if (running.Count > 0)
                return running.Sum(p => p.WorkingSet);

            return 0; // Unknown is reported as unknown - never invented.
        }

        private static string BuildStartupRecommendation(SystemInfo.StartupItem item)
        {
            if (item.IsWindowsItem)
                return "Windows component - keep enabled";

            if (item.RiskLevel == RiskLevel.High)
                return "High risk - leave enabled unless you know exactly what it does";

            if (item.RiskLevel == RiskLevel.Critical)
                return "Protected entry - the application will never disable this";

            return item.ImpactScore >= 2
                ? "Consider disabling - it costs noticeable memory at sign-in"
                : "Safe to disable if you do not need it at sign-in";
        }

        private List<SystemInfo.NetworkAdapterInfo> CollectNetworkAdapters()
        {
            var result = new List<SystemInfo.NetworkAdapterInfo>();

            try
            {
                foreach (var adapter in PerformanceCounterHelper.GetNetworkAdapterInfo())
                {
                    result.Add(new SystemInfo.NetworkAdapterInfo
                    {
                        Name = adapter.Name,
                        Description = adapter.Description,
                        Type = "Physical",
                        IsEnabled = adapter.IsEnabled,
                        IsConnected = adapter.IsEnabled,
                        DownloadSpeed = adapter.DownloadSpeed,
                        UploadSpeed = adapter.UploadSpeed,
                        MacAddress = adapter.MacAddress
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read network information", null, ex);
            }

            return result;
        }

        private void CollectSecurityInfo(SystemInfo info)
        {
            try
            {
                info.IsRealTimeProtectionEnabled = WindowsApiHelper.IsDefenderRealTimeProtectionEnabled();
                info.IsDefenderEnabled = info.IsRealTimeProtectionEnabled;
                info.IsFirewallEnabled = WindowsApiHelper.IsFirewallEnabled();
                info.IsUacEnabled = WindowsApiHelper.IsUacEnabled();
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read security status", null, ex);
            }
        }

        private void CollectPowerInfo(SystemInfo info)
        {
            try
            {
                info.IsOnBattery = WindowsApiHelper.IsOnBattery();
                info.BatteryPercentage = WindowsApiHelper.GetBatteryPercentage();
                info.BatteryLifeRemaining = WindowsApiHelper.GetBatteryLifeRemainingMinutes();
                info.BatteryStatus = info.IsOnBattery ? "On battery" : "Plugged in";
                info.CurrentPowerMode = GetPowerMode();
            }
            catch (Exception ex)
            {
                _logger.Warning("SystemScanner", "Could not read power information", null, ex);
            }
        }

        private PowerMode GetPowerMode()
        {
            if (WindowsApiHelper.IsOnBattery())
                return PowerMode.PowerSaver;

            return _config.PreferredPowerModeOnAc;
        }

        private static void CalculateCounts(SystemInfo info)
        {
            info.UserProcessCount = info.Processes.Count(p => !p.IsWindowsProcess && !p.IsDriver);
            info.SystemProcessCount = info.Processes.Count(p => p.IsWindowsProcess || p.IsDriver);
            info.BackgroundProcessCount = info.Processes.Count(p =>
                p.Category == ProcessCategory.BackgroundApplication &&
                !p.IsActive && !p.HasVisibleWindow);
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            try
            {
                _cancellation?.Dispose();
                _scanGate.Dispose();
                PerformanceCounterHelper.ResetCache();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>Components that can be refreshed individually.</summary>
    public enum ScanComponent
    {
        Processes,
        Memory,
        Cpu,
        Disks,
        Gpus,
        Services,
        Startup,
        Network,
        Security,
        All
    }

    /// <summary>Scan lifecycle event payload.</summary>
    public class ScanEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public TimeSpan Duration { get; set; }
        public string ErrorMessage { get; set; } = string.Empty;
        public Exception? Exception { get; set; }
        public SystemInfo? SystemInfo { get; set; }
    }

    /// <summary>Scan progress payload.</summary>
    public class ScanProgressEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public int Percentage { get; set; }
        public string Message { get; set; } = string.Empty;
    }
}

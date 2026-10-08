using System;
using System.Collections.Generic;
using System.Management;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Represents comprehensive system information
    /// </summary>
    public class SystemInfo
    {
        #region System Properties

        /// <summary>
        /// Operating system name
        /// </summary>
        public string OsName { get; set; } = string.Empty;

        /// <summary>
        /// Operating system version
        /// </summary>
        public string OsVersion { get; set; } = string.Empty;

        /// <summary>
        /// Operating system architecture (x86, x64, ARM64)
        /// </summary>
        public string OsArchitecture { get; set; } = string.Empty;

        /// <summary>
        /// Operating system build number
        /// </summary>
        public string OsBuild { get; set; } = string.Empty;

        /// <summary>
        /// Whether the OS is Windows 11
        /// </summary>
        public bool IsWindows11 { get; set; }

        /// <summary>
        /// Whether the OS is Windows 10
        /// </summary>
        public bool IsWindows10 { get; set; }

        /// <summary>
        /// Computer name
        /// </summary>
        public string ComputerName { get; set; } = string.Empty;

        /// <summary>
        /// User name
        /// </summary>
        public string UserName { get; set; } = string.Empty;

        /// <summary>
        /// Whether the user has administrator privileges
        /// </summary>
        public bool IsAdministrator { get; set; }

        #endregion

        #region CPU Information

        /// <summary>
        /// CPU name/model
        /// </summary>
        public string CpuName { get; set; } = string.Empty;

        /// <summary>
        /// CPU manufacturer
        /// </summary>
        public string CpuManufacturer { get; set; } = string.Empty;

        /// <summary>
        /// Number of CPU cores
        /// </summary>
        public int CpuCoreCount { get; set; }

        /// <summary>
        /// Number of logical processors
        /// </summary>
        public int CpuLogicalProcessorCount { get; set; }

        /// <summary>
        /// Number of physical cores (falls back to the logical count when WMI is unavailable).
        /// </summary>
        public int CpuPhysicalCoreCount { get; set; }

        /// <summary>
        /// CPU base clock speed in MHz
        /// </summary>
        public double CpuBaseClock { get; set; }

        /// <summary>
        /// CPU max clock speed in MHz
        /// </summary>
        public double CpuMaxClock { get; set; }

        /// <summary>
        /// Current CPU usage percentage (0-100)
        /// </summary>
        public float CpuUsage { get; set; }

        /// <summary>
        /// CPU usage per core (0-100)
        /// </summary>
        public float[] CpuCoreUsage { get; set; } = Array.Empty<float>();

        /// <summary>
        /// CPU temperature in Celsius (if available)
        /// </summary>
        public float? CpuTemperature { get; set; }

        /// <summary>
        /// CPU load percentage (0-100)
        /// </summary>
        public float CpuLoad { get; set; }

        /// <summary>
        /// CPU power state
        /// </summary>
        public string CpuPowerState { get; set; } = string.Empty;

        #endregion

        #region RAM Information

        /// <summary>
        /// Total physical RAM in bytes
        /// </summary>
        public long TotalPhysicalMemory { get; set; }

        /// <summary>
        /// Available physical RAM in bytes
        /// </summary>
        public long AvailablePhysicalMemory { get; set; }

        /// <summary>
        /// Used physical RAM in bytes
        /// </summary>
        public long UsedPhysicalMemory => TotalPhysicalMemory - AvailablePhysicalMemory;

        /// <summary>
        /// RAM usage percentage, in the range 0-100.
        ///
        /// The definition is the one Windows Task Manager uses for "In use":
        ///     (TotalPhysicalMemory - AvailablePhysicalMemory) / TotalPhysicalMemory * 100
        /// where <c>AvailablePhysicalMemory</c> already includes the reclaimable standby list.
        ///
        /// The result is clamped. A snapshot is a set of samples rather than a transaction, so a
        /// counter that is refreshed while the machine is paging can momentarily report more available
        /// memory than total. Without the clamp that produces a negative or greater-than-100
        /// percentage, which would then be drawn on the dashboard and written into the history file.
        /// </summary>
        public float RamUsagePercentage
        {
            get
            {
                if (TotalPhysicalMemory <= 0)
                    return 0f;

                var percentage = (double)UsedPhysicalMemory / TotalPhysicalMemory * 100.0;

                if (percentage < 0.0) return 0f;
                if (percentage > 100.0) return 100f;

                return (float)percentage;
            }
        }

        /// <summary>
        /// Memory in use by processes
        /// </summary>
        public long ProcessMemoryUsage { get; set; }

        /// <summary>
        /// Cached memory in bytes
        /// </summary>
        public long CachedMemory { get; set; }

        /// <summary>
        /// Standby memory in bytes
        /// </summary>
        public long StandbyMemory { get; set; }

        /// <summary>
        /// Free memory in bytes
        /// </summary>
        public long FreeMemory { get; set; }

        /// <summary>
        /// Paged pool memory in bytes
        /// </summary>
        public long PagedPoolMemory { get; set; }

        /// <summary>
        /// Non-paged pool memory in bytes
        /// </summary>
        public long NonPagedPoolMemory { get; set; }

        /// <summary>
        /// Page file usage
        /// </summary>
        public long PageFileUsage { get; set; }

        /// <summary>
        /// Page file limit
        /// </summary>
        public long PageFileLimit { get; set; }

        /// <summary>
        /// Page file usage percentage
        /// </summary>
        public float PageFileUsagePercentage
        {
            get
            {
                if (PageFileLimit == 0) return 0;
                return (float)((double)PageFileUsage / PageFileLimit * 100);
            }
        }

        #endregion

        #region GPU Information

        /// <summary>
        /// List of GPU information
        /// </summary>
        public List<GpuInfo> Gpus { get; set; } = new List<GpuInfo>();

        /// <summary>
        /// Primary GPU information
        /// </summary>
        public GpuInfo? PrimaryGpu => Gpus.Count > 0 ? Gpus[0] : null;

        /// <summary>
        /// Total GPU memory usage
        /// </summary>
        public long TotalGpuMemoryUsage { get; set; }

        /// <summary>
        /// Total GPU usage percentage
        /// </summary>
        public float TotalGpuUsage { get; set; }

        #endregion

        #region Disk Information

        /// <summary>
        /// List of disk drives
        /// </summary>
        public List<DiskInfo> Disks { get; set; } = new List<DiskInfo>();

        /// <summary>
        /// System disk (usually C:)
        /// </summary>
        public DiskInfo? SystemDisk => Disks.Find(d => d.IsSystemDisk);

        /// <summary>
        /// Total disk read speed in bytes per second
        /// </summary>
        public long TotalDiskReadSpeed { get; set; }

        /// <summary>
        /// Total disk write speed in bytes per second
        /// </summary>
        public long TotalDiskWriteSpeed { get; set; }

        /// <summary>
        /// Total disk activity percentage
        /// </summary>
        public float TotalDiskActivity { get; set; }

        #endregion

        #region Network Information

        /// <summary>
        /// Total network download speed in bytes per second
        /// </summary>
        public long NetworkDownloadSpeed { get; set; }

        /// <summary>
        /// Total network upload speed in bytes per second
        /// </summary>
        public long NetworkUploadSpeed { get; set; }

        /// <summary>
        /// List of network adapters
        /// </summary>
        public List<NetworkAdapterInfo> NetworkAdapters { get; set; } = new List<NetworkAdapterInfo>();

        #endregion

        #region Power Information

        /// <summary>
        /// Current power mode
        /// </summary>
        public PowerMode CurrentPowerMode { get; set; } = PowerMode.Balanced;

        /// <summary>
        /// Whether the system is on battery power
        /// </summary>
        public bool IsOnBattery { get; set; }

        /// <summary>
        /// Battery percentage (if on battery)
        /// </summary>
        public int BatteryPercentage { get; set; }

        /// <summary>
        /// Battery status
        /// </summary>
        public string BatteryStatus { get; set; } = string.Empty;

        /// <summary>
        /// Estimated battery life remaining (in minutes)
        /// </summary>
        public int BatteryLifeRemaining { get; set; }

        #endregion

        #region Security Information

        /// <summary>
        /// Whether Windows Defender is enabled
        /// </summary>
        public bool IsDefenderEnabled { get; set; }

        /// <summary>
        /// Whether real-time protection is enabled
        /// </summary>
        public bool IsRealTimeProtectionEnabled { get; set; }

        /// <summary>
        /// Whether firewall is enabled
        /// </summary>
        public bool IsFirewallEnabled { get; set; }

        /// <summary>
        /// Whether UAC is enabled
        /// </summary>
        public bool IsUacEnabled { get; set; }

        /// <summary>
        /// Last antivirus scan date
        /// </summary>
        public DateTime LastScanDate { get; set; }

        /// <summary>
        /// Number of threats detected
        /// </summary>
        public int ThreatCount { get; set; }

        #endregion

        #region Process Information

        /// <summary>
        /// Total number of running processes
        /// </summary>
        public int TotalProcessCount { get; set; }

        /// <summary>
        /// Number of user processes
        /// </summary>
        public int UserProcessCount { get; set; }

        /// <summary>
        /// Number of system processes
        /// </summary>
        public int SystemProcessCount { get; set; }

        /// <summary>
        /// Number of background processes
        /// </summary>
        public int BackgroundProcessCount { get; set; }

        /// <summary>
        /// List of all running processes
        /// </summary>
        public List<ProcessInfo> Processes { get; set; } = new List<ProcessInfo>();

        /// <summary>
        /// List of startup applications
        /// </summary>
        public List<StartupItem> StartupItems { get; set; } = new List<StartupItem>();

        /// <summary>
        /// List of running services
        /// </summary>
        public List<ServiceInfo> Services { get; set; } = new List<ServiceInfo>();

        #endregion

        #region Performance Metrics

        /// <summary>
        /// System responsiveness score (0-100)
        /// </summary>
        public int ResponsivenessScore { get; set; } = 100;

        /// <summary>
        /// System health score (0-100)
        /// </summary>
        public int SystemHealthScore { get; set; } = 100;

        /// <summary>
        /// Performance score breakdown
        /// </summary>
        public Dictionary<string, int> PerformanceScores { get; set; } = new Dictionary<string, int>();

        #endregion

        #region Optimization Information

        /// <summary>
        /// Whether system optimization is needed
        /// </summary>
        public bool NeedsOptimization { get; set; }

        /// <summary>
        /// Estimated RAM that can be recovered
        /// </summary>
        public long EstimatedRamRecovery { get; set; }

        /// <summary>
        /// Estimated CPU improvement percentage
        /// </summary>
        public float EstimatedCpuImprovement { get; set; }

        /// <summary>
        /// List of optimization recommendations
        /// </summary>
        public List<OptimizationRecommendation> Recommendations { get; set; } = new List<OptimizationRecommendation>();

        /// <summary>
        /// Current optimization plan
        /// </summary>
        public OptimizationPlan? CurrentOptimizationPlan { get; set; }

        #endregion

        #region Timestamp

        /// <summary>
        /// When the system info was collected
        /// </summary>
        public DateTime CollectedAt { get; set; } = DateTime.Now;

        #endregion

        #region Helper Properties

        /// <summary>
        /// Total RAM in GB
        /// </summary>
        public double TotalPhysicalMemoryGB => TotalPhysicalMemory / (1024.0 * 1024.0 * 1024.0);

        /// <summary>
        /// Used RAM in GB
        /// </summary>
        public double UsedPhysicalMemoryGB => UsedPhysicalMemory / (1024.0 * 1024.0 * 1024.0);

        /// <summary>
        /// Available RAM in GB
        /// </summary>
        public double AvailablePhysicalMemoryGB => AvailablePhysicalMemory / (1024.0 * 1024.0 * 1024.0);

        /// <summary>
        /// Formatted RAM usage string
        /// </summary>
        public string FormattedRamUsage => $"{UsedPhysicalMemoryGB:F2} GB / {TotalPhysicalMemoryGB:F2} GB ({RamUsagePercentage:F1}%)";

        /// <summary>
        /// Formatted CPU usage string
        /// </summary>
        public string FormattedCpuUsage => $"{CpuUsage:F1}%";

        /// <summary>
        /// Formatted GPU usage string
        /// </summary>
        public string FormattedGpuUsage => $"{TotalGpuUsage:F1}%";

        #endregion


        /// <summary>
        /// Create a copy of this snapshot.
        /// Process/service/startup collections are copied element-wise so that a
        /// before/after comparison cannot be corrupted by later refreshes.
        /// </summary>
        public SystemInfo Clone()
        {
            var clone = new SystemInfo
            {
                OsName = OsName,
                OsVersion = OsVersion,
                OsArchitecture = OsArchitecture,
                OsBuild = OsBuild,
                IsWindows11 = IsWindows11,
                IsWindows10 = IsWindows10,
                ComputerName = ComputerName,
                UserName = UserName,
                IsAdministrator = IsAdministrator,

                CpuName = CpuName,
                CpuManufacturer = CpuManufacturer,
                CpuCoreCount = CpuCoreCount,
                CpuLogicalProcessorCount = CpuLogicalProcessorCount,
                CpuPhysicalCoreCount = CpuPhysicalCoreCount,
                CpuBaseClock = CpuBaseClock,
                CpuMaxClock = CpuMaxClock,
                CpuUsage = CpuUsage,
                CpuCoreUsage = CpuCoreUsage == null ? Array.Empty<float>() : (float[])CpuCoreUsage.Clone(),
                CpuTemperature = CpuTemperature,
                CpuLoad = CpuLoad,
                CpuPowerState = CpuPowerState,

                TotalPhysicalMemory = TotalPhysicalMemory,
                AvailablePhysicalMemory = AvailablePhysicalMemory,
                ProcessMemoryUsage = ProcessMemoryUsage,
                CachedMemory = CachedMemory,
                StandbyMemory = StandbyMemory,
                FreeMemory = FreeMemory,
                PagedPoolMemory = PagedPoolMemory,
                NonPagedPoolMemory = NonPagedPoolMemory,
                PageFileUsage = PageFileUsage,
                PageFileLimit = PageFileLimit,

                TotalGpuMemoryUsage = TotalGpuMemoryUsage,
                TotalGpuUsage = TotalGpuUsage,

                TotalDiskReadSpeed = TotalDiskReadSpeed,
                TotalDiskWriteSpeed = TotalDiskWriteSpeed,
                TotalDiskActivity = TotalDiskActivity,

                NetworkDownloadSpeed = NetworkDownloadSpeed,
                NetworkUploadSpeed = NetworkUploadSpeed,

                CurrentPowerMode = CurrentPowerMode,
                IsOnBattery = IsOnBattery,
                BatteryPercentage = BatteryPercentage,
                BatteryStatus = BatteryStatus,
                BatteryLifeRemaining = BatteryLifeRemaining,

                IsDefenderEnabled = IsDefenderEnabled,
                IsRealTimeProtectionEnabled = IsRealTimeProtectionEnabled,
                IsFirewallEnabled = IsFirewallEnabled,
                IsUacEnabled = IsUacEnabled,
                LastScanDate = LastScanDate,
                ThreatCount = ThreatCount,

                TotalProcessCount = TotalProcessCount,
                UserProcessCount = UserProcessCount,
                SystemProcessCount = SystemProcessCount,
                BackgroundProcessCount = BackgroundProcessCount,

                ResponsivenessScore = ResponsivenessScore,
                SystemHealthScore = SystemHealthScore,
                NeedsOptimization = NeedsOptimization,
                EstimatedRamRecovery = EstimatedRamRecovery,
                EstimatedCpuImprovement = EstimatedCpuImprovement,

                CollectedAt = CollectedAt
            };

            clone.Gpus.AddRange(Gpus);
            clone.Disks.AddRange(Disks);
            clone.NetworkAdapters.AddRange(NetworkAdapters);
            clone.Processes.AddRange(Processes);
            clone.StartupItems.AddRange(StartupItems);
            clone.Services.AddRange(Services);
            clone.Recommendations.AddRange(Recommendations);

            foreach (var pair in PerformanceScores)
                clone.PerformanceScores[pair.Key] = pair.Value;

            return clone;
        }

        #region Nested Classes

        /// <summary>
        /// GPU information
        /// </summary>
        public class GpuInfo
        {
            /// <summary>
            /// GPU name
            /// </summary>
            public string Name { get; set; } = string.Empty;

            /// <summary>
            /// GPU manufacturer
            /// </summary>
            public string Manufacturer { get; set; } = string.Empty;

            /// <summary>
            /// GPU type (Integrated, Dedicated)
            /// </summary>
            public string Type { get; set; } = string.Empty;

            /// <summary>
            /// Total GPU memory in bytes
            /// </summary>
            public long TotalMemory { get; set; }

            /// <summary>
            /// Used GPU memory in bytes
            /// </summary>
            public long UsedMemory { get; set; }

            /// <summary>
            /// GPU usage percentage (0-100)
            /// </summary>
            public float Usage { get; set; }

            /// <summary>
            /// GPU temperature in Celsius (if available)
            /// </summary>
            public float? Temperature { get; set; }

            /// <summary>
            /// GPU driver version
            /// </summary>
            public string DriverVersion { get; set; } = string.Empty;

            /// <summary>
            /// Whether this is the primary GPU
            /// </summary>
            public bool IsPrimary { get; set; }

            /// <summary>
            /// Device id (WMI). Useful for distinguishing two adapters of the same model.
            /// </summary>
            public string PnpDeviceId { get; set; } = string.Empty;

            /// <summary>
            /// GPU memory usage percentage
            /// </summary>
            public float MemoryUsagePercentage
            {
                get
                {
                    if (TotalMemory == 0) return 0;
                    return (float)((double)UsedMemory / TotalMemory * 100);
                }
            }

            /// <summary>
            /// Formatted GPU memory string
            /// </summary>
            public string FormattedMemory => $"{UsedMemory / (1024.0 * 1024.0):F2} GB / {TotalMemory / (1024.0 * 1024.0):F2} GB";
        }

        /// <summary>
        /// Disk information
        /// </summary>
        public class DiskInfo
        {
            /// <summary>
            /// Drive letter (e.g., "C")
            /// </summary>
            public string DriveLetter { get; set; } = string.Empty;

            /// <summary>
            /// Drive label
            /// </summary>
            public string Label { get; set; } = string.Empty;

            /// <summary>
            /// Drive type (HDD, SSD, NVMe, etc.)
            /// </summary>
            public string Type { get; set; } = string.Empty;

            /// <summary>
            /// File system (NTFS, FAT32, etc.)
            /// </summary>
            public string FileSystem { get; set; } = string.Empty;

            /// <summary>
            /// Total size in bytes
            /// </summary>
            public long TotalSize { get; set; }

            /// <summary>
            /// Free space in bytes
            /// </summary>
            public long FreeSpace { get; set; }

            /// <summary>
            /// Used space in bytes
            /// </summary>
            public long UsedSpace => TotalSize - FreeSpace;

            /// <summary>
            /// Whether this is the system disk
            /// </summary>
            public bool IsSystemDisk { get; set; }

            /// <summary>
            /// Whether this is a boot disk
            /// </summary>
            public bool IsBootDisk { get; set; }

            /// <summary>
            /// Disk usage percentage
            /// </summary>
            public float UsagePercentage
            {
                get
                {
                    if (TotalSize == 0) return 0;
                    return (float)((double)UsedSpace / TotalSize * 100);
                }
            }

            /// <summary>
            /// Disk health status
            /// </summary>
            public string HealthStatus { get; set; } = "Good";

            /// <summary>
            /// Current read throughput in bytes per second (0 when not sampled).
            /// </summary>
            public long ReadBytesPerSecond { get; set; }

            /// <summary>
            /// Current write throughput in bytes per second (0 when not sampled).
            /// </summary>
            public long WriteBytesPerSecond { get; set; }

            /// <summary>
            /// Busy time in percent (0-100).
            /// </summary>
            public float ActiveTime { get; set; }

            /// <summary>
            /// Average disk queue length.
            /// </summary>
            public float QueueLength { get; set; }

            /// <summary>
            /// Average response time in milliseconds.
            /// </summary>
            public float ResponseTimeMs { get; set; }

            /// <summary>
            /// True when the volume is backed by flash storage (never defragmented).
            /// </summary>
            public bool IsSolidState => Type.IndexOf("SSD", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                        Type.IndexOf("NVMe", StringComparison.OrdinalIgnoreCase) >= 0;

            /// <summary>
            /// Disk temperature in Celsius (if available)
            /// </summary>
            public float? Temperature { get; set; }

            /// <summary>
            /// Formatted total size
            /// </summary>
            public string FormattedTotalSize => FormatBytes(TotalSize);

            /// <summary>
            /// Formatted free space
            /// </summary>
            public string FormattedFreeSpace => FormatBytes(FreeSpace);

            /// <summary>
            /// Formatted used space
            /// </summary>
            public string FormattedUsedSpace => FormatBytes(UsedSpace);

            private static string FormatBytes(long bytes)
            {
                string[] suffixes = { "B", "KB", "MB", "GB", "TB" };
                int counter = 0;
                decimal number = bytes;
                while (Math.Round(number / 1024) >= 1)
                {
                    number = number / 1024;
                    counter++;
                }
                return $"{number:n1} {suffixes[counter]}";
            }
        }

        /// <summary>
        /// Network adapter information
        /// </summary>
        public class NetworkAdapterInfo
        {
            /// <summary>
            /// Adapter name
            /// </summary>
            public string Name { get; set; } = string.Empty;

            /// <summary>
            /// Adapter description
            /// </summary>
            public string Description { get; set; } = string.Empty;

            /// <summary>
            /// Adapter type
            /// </summary>
            public string Type { get; set; } = string.Empty;

            /// <summary>
            /// Whether the adapter is enabled
            /// </summary>
            public bool IsEnabled { get; set; }

            /// <summary>
            /// Whether the adapter is connected
            /// </summary>
            public bool IsConnected { get; set; }

            /// <summary>
            /// Current download speed in bytes per second
            /// </summary>
            public long DownloadSpeed { get; set; }

            /// <summary>
            /// Current upload speed in bytes per second
            /// </summary>
            public long UploadSpeed { get; set; }

            /// <summary>
            /// Total bytes received
            /// </summary>
            public long TotalReceived { get; set; }

            /// <summary>
            /// Total bytes sent
            /// </summary>
            public long TotalSent { get; set; }

            /// <summary>
            /// MAC address
            /// </summary>
            public string MacAddress { get; set; } = string.Empty;

            /// <summary>
            /// IP addresses
            /// </summary>
            public List<string> IpAddresses { get; set; } = new List<string>();

            /// <summary>
            /// Formatted download speed
            /// </summary>
            public string FormattedDownloadSpeed => FormatSpeed(DownloadSpeed);

            /// <summary>
            /// Formatted upload speed
            /// </summary>
            public string FormattedUploadSpeed => FormatSpeed(UploadSpeed);

            private static string FormatSpeed(long bytesPerSecond)
            {
                if (bytesPerSecond < 1024)
                    return $"{bytesPerSecond} B/s";
                else if (bytesPerSecond < 1024 * 1024)
                    return $"{bytesPerSecond / 1024.0:F2} KB/s";
                else if (bytesPerSecond < 1024 * 1024 * 1024)
                    return $"{bytesPerSecond / (1024.0 * 1024.0):F2} MB/s";
                else
                    return $"{bytesPerSecond / (1024.0 * 1024.0 * 1024.0):F2} GB/s";
            }
        }

        /// <summary>
        /// Startup item information
        /// </summary>
        public class StartupItem
        {
            /// <summary>
            /// Item name
            /// </summary>
            public string Name { get; set; } = string.Empty;

            /// <summary>
            /// Item path
            /// </summary>
            public string Path { get; set; } = string.Empty;

            /// <summary>
            /// Item publisher
            /// </summary>
            public string Publisher { get; set; } = string.Empty;

            /// <summary>
            /// Startup source (Registry, Startup Folder, Task Scheduler, Service)
            /// </summary>
            public string Source { get; set; } = string.Empty;

            /// <summary>
            /// Startup impact (Low, Medium, High)
            /// </summary>
            public string Impact { get; set; } = "Medium";

            /// <summary>
            /// Whether the item is enabled
            /// </summary>
            public bool IsEnabled { get; set; } = true;

            /// <summary>
            /// Whether the item is a Windows system item
            /// </summary>
            public bool IsWindowsItem { get; set; }

            /// <summary>
            /// Risk level
            /// </summary>
            public RiskLevel RiskLevel { get; set; } = RiskLevel.Medium;

            /// <summary>
            /// Estimated RAM usage
            /// </summary>
            public long EstimatedRamUsage { get; set; }

            /// <summary>
            /// Recommendation
            /// </summary>
            public string Recommendation { get; set; } = string.Empty;

            /// <summary>
            /// Command line arguments
            /// </summary>
            public string Arguments { get; set; } = string.Empty;

            /// <summary>
            /// Registry key path (if applicable)
            /// </summary>
            public string RegistryPath { get; set; } = string.Empty;

            /// <summary>
            /// Task name (if from Task Scheduler)
            /// </summary>
            public string TaskName { get; set; } = string.Empty;

            /// <summary>
            /// Service name (if applicable)
            /// </summary>
            public string ServiceName { get; set; } = string.Empty;

            /// <summary>
            /// Full command line of the start-up entry.
            /// </summary>
            public string CommandLine { get; set; } = string.Empty;

            /// <summary>
            /// True when this entry must never be disabled by the application.
            /// </summary>
            public bool IsBlacklisted { get; set; }

            /// <summary>
            /// Numeric start-up impact used for sorting (0 = low, 1 = medium, 2 = high).
            /// </summary>
            public int ImpactScore
            {
                get
                {
                    if (string.Equals(Impact, "High", StringComparison.OrdinalIgnoreCase)) return 2;
                    if (string.Equals(Impact, "Medium", StringComparison.OrdinalIgnoreCase)) return 1;
                    return 0;
                }
            }

            /// <summary>
            /// Formatted estimated RAM usage.
            /// </summary>
            public string FormattedEstimatedRamUsage
            {
                get
                {
                    if (EstimatedRamUsage <= 0) return "unknown";

                    var mb = EstimatedRamUsage / (1024.0 * 1024.0);
                    return mb >= 1024
                        ? $"{mb / 1024.0:F2} GB"
                        : $"{mb:F1} MB";
                }
            }
        }

        /// <summary>
        /// Service information
        /// </summary>
        public class ServiceInfo
        {
            /// <summary>
            /// Service name
            /// </summary>
            public string Name { get; set; } = string.Empty;

            /// <summary>
            /// Service display name
            /// </summary>
            public string DisplayName { get; set; } = string.Empty;

            /// <summary>
            /// Service description
            /// </summary>
            public string Description { get; set; } = string.Empty;

            /// <summary>
            /// Service status
            /// </summary>
            public string Status { get; set; } = string.Empty;

            /// <summary>
            /// Service start type (Automatic, Manual, Disabled)
            /// </summary>
            public string StartType { get; set; } = string.Empty;

            /// <summary>
            /// Service process ID
            /// </summary>
            public int ProcessId { get; set; }

            /// <summary>
            /// Whether the service is Windows system service
            /// </summary>
            public bool IsWindowsService { get; set; }

            /// <summary>
            /// Whether the service is critical
            /// </summary>
            public bool IsCritical { get; set; }

            /// <summary>
            /// Risk level
            /// </summary>
            public RiskLevel RiskLevel { get; set; } = RiskLevel.Critical;

            /// <summary>
            /// Service account
            /// </summary>
            public string Account { get; set; } = string.Empty;

            /// <summary>
            /// Memory usage in bytes
            /// </summary>
            public long MemoryUsage { get; set; }

            /// <summary>
            /// CPU usage percentage
            /// </summary>
            public float CpuUsage { get; set; }

            /// <summary>
            /// Whether the service can be stopped
            /// </summary>
            public bool CanStop => Status == "Running" && StartType != "Disabled";

            /// <summary>
            /// Whether the service can be disabled
            /// </summary>
            public bool CanDisable => !IsCritical && !IsWindowsService;
        }

        /// <summary>
        /// Optimization recommendation
        /// </summary>
        public class OptimizationRecommendation
        {
            /// <summary>
            /// Recommendation title
            /// </summary>
            public string Title { get; set; } = string.Empty;

            /// <summary>
            /// Recommendation description
            /// </summary>
            public string Description { get; set; } = string.Empty;

            /// <summary>
            /// Recommendation category
            /// </summary>
            public string Category { get; set; } = string.Empty;

            /// <summary>
            /// Resource type affected
            /// </summary>
            public ResourceType ResourceType { get; set; } = ResourceType.RAM;

            /// <summary>
            /// Estimated improvement
            /// </summary>
            public string EstimatedImprovement { get; set; } = string.Empty;

            /// <summary>
            /// Risk level
            /// </summary>
            public RiskLevel RiskLevel { get; set; } = RiskLevel.Low;

            /// <summary>
            /// Whether the recommendation is AI-generated
            /// </summary>
            public bool IsAiGenerated { get; set; }

            /// <summary>
            /// Priority (1-10, higher is more important)
            /// </summary>
            public int Priority { get; set; } = 1;

            /// <summary>
            /// Action type
            /// </summary>
            public OptimizationActionType ActionType { get; set; } = OptimizationActionType.CloseProcess;

            /// <summary>
            /// Target process or service name
            /// </summary>
            public string Target { get; set; } = string.Empty;
        }

        #endregion
    }
}

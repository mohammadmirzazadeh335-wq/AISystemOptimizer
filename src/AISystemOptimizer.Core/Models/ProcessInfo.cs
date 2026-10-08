using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Represents detailed information about a running process
    /// </summary>
    public class ProcessInfo : IEquatable<ProcessInfo>, IComparable<ProcessInfo>
    {
        #region Properties

        /// <summary>
        /// Process ID
        /// </summary>
        public int Id { get; set; }

        /// <summary>
        /// Process name (e.g., "chrome.exe")
        /// </summary>
        public string Name { get; set; } = string.Empty;

        /// <summary>
        /// Full path to the executable
        /// </summary>
        public string Path { get; set; } = string.Empty;

        /// <summary>
        /// Process display name (friendly name)
        /// </summary>
        public string DisplayName { get; set; } = string.Empty;

        /// <summary>
        /// Process description
        /// </summary>
        public string Description { get; set; } = string.Empty;

        /// <summary>
        /// Publisher/company name
        /// </summary>
        public string Publisher { get; set; } = string.Empty;

        /// <summary>
        /// Product name
        /// </summary>
        public string ProductName { get; set; } = string.Empty;

        /// <summary>
        /// Product version
        /// </summary>
        public string Version { get; set; } = string.Empty;

        /// <summary>
        /// Process category
        /// </summary>
        public ProcessCategory Category { get; set; } = ProcessCategory.Unknown;

        /// <summary>
        /// Risk level for optimization
        /// </summary>
        public RiskLevel RiskLevel { get; set; } = RiskLevel.Critical;

        /// <summary>
        /// Current RAM usage in bytes
        /// </summary>
        public long WorkingSet { get; set; }

        /// <summary>
        /// Peak RAM usage in bytes
        /// </summary>
        public long PeakWorkingSet { get; set; }

        /// <summary>
        /// Private memory usage in bytes
        /// </summary>
        public long PrivateMemorySize { get; set; }

        /// <summary>
        /// Virtual memory usage in bytes
        /// </summary>
        public long VirtualMemorySize { get; set; }

        /// <summary>
        /// Paged memory usage in bytes
        /// </summary>
        public long PagedMemorySize { get; set; }

        /// <summary>
        /// Non-paged memory usage in bytes
        /// </summary>
        public long NonpagedSystemMemorySize { get; set; }

        /// <summary>
        /// CPU usage percentage (0-100)
        /// </summary>
        public float CpuUsage { get; set; }

        /// <summary>
        /// Total CPU time used by the process
        /// </summary>
        public TimeSpan TotalProcessorTime { get; set; }

        /// <summary>
        /// GPU usage percentage (0-100)
        /// </summary>
        public float GpuUsage { get; set; }

        /// <summary>
        /// GPU memory usage in bytes
        /// </summary>
        public long GpuMemoryUsage { get; set; }

        /// <summary>
        /// Disk read bytes per second
        /// </summary>
        public long DiskReadBytesPerSecond { get; set; }

        /// <summary>
        /// Disk write bytes per second
        /// </summary>
        public long DiskWriteBytesPerSecond { get; set; }

        /// <summary>
        /// Network bytes received per second
        /// </summary>
        public long NetworkReceivedBytesPerSecond { get; set; }

        /// <summary>
        /// Network bytes sent per second
        /// </summary>
        public long NetworkSentBytesPerSecond { get; set; }

        /// <summary>
        /// Process start time
        /// </summary>
        public DateTime StartTime { get; set; }

        /// <summary>
        /// Total time the process has been running
        /// </summary>
        public TimeSpan TotalRunningTime => DateTime.Now - StartTime;

        /// <summary>
        /// Process creation timestamp in UTC, read via GetProcessTimes.
        ///
        /// This - not <see cref="StartTime"/> - is the value used as the process identity for the
        /// anti-PID-reuse check: it is read from the kernel, is not affected by the local time zone
        /// or by daylight-saving transitions, and uniquely identifies one incarnation of a pid.
        /// <see cref="DateTime.MinValue"/> when it could not be read.
        /// </summary>
        public DateTime CreationTimeUtc { get; set; } = DateTime.MinValue;

        /// <summary>
        /// Parent process ID
        /// </summary>
        public int ParentId { get; set; }

        /// <summary>
        /// Parent process name
        /// </summary>
        public string ParentProcessName { get; set; } = string.Empty;

        /// <summary>
        /// Process priority class
        /// </summary>
        public ProcessPriorityClass PriorityClass { get; set; } = ProcessPriorityClass.Normal;

        /// <summary>
        /// Process state
        /// </summary>
        public ProcessState State { get; set; } = ProcessState.Running;

        /// <summary>
        /// Digital signature status
        /// </summary>
        public SignatureStatus SignatureStatus { get; set; } = SignatureStatus.Unsigned;

        /// <summary>
        /// Whether the process is a Windows system process
        /// </summary>
        public bool IsWindowsProcess { get; set; }

        /// <summary>
        /// Whether the process is a driver
        /// </summary>
        public bool IsDriver { get; set; }

        /// <summary>
        /// Whether the process belongs to the security stack (Defender, firewall, AV, UAC helpers).
        /// Security processes are excluded from every optimisation, always.
        /// </summary>
        public bool IsSecurity { get; set; }

        /// <summary>
        /// Whether the process is a service
        /// </summary>
        public bool IsService { get; set; }

        /// <summary>
        /// Service name if applicable
        /// </summary>
        public string ServiceName { get; set; } = string.Empty;

        /// <summary>
        /// Whether the process has a visible window
        /// </summary>
        public bool HasVisibleWindow { get; set; }

        /// <summary>
        /// Whether this process currently owns the foreground window (it is receiving user input).
        /// Captured at scan time and re-checked by the executor immediately before it acts.
        /// </summary>
        public bool IsForeground { get; set; }

        /// <summary>
        /// Whether the process is in the system's whitelist
        /// </summary>
        public bool IsWhitelisted { get; set; }

        /// <summary>
        /// Whether the process is in the user's custom whitelist
        /// </summary>
        public bool IsUserWhitelisted { get; set; }

        /// <summary>
        /// Whether the process is in the blacklist (never touch)
        /// </summary>
        public bool IsBlacklisted { get; set; }

        /// <summary>
        /// Whether the process is currently active (user is using it)
        /// </summary>
        public bool IsActive { get; set; }

        /// <summary>
        /// Whether the process can be safely terminated
        /// </summary>
        public bool CanBeTerminated =>
            RiskLevel == RiskLevel.Low || RiskLevel == RiskLevel.Medium;

        /// <summary>
        /// Set by the scanner / analyzer: true when this process is a legitimate
        /// optimization candidate (not critical, not in use, not protected).
        /// </summary>
        public bool CanOptimize { get; set; }

        /// <summary>
        /// Whether the process is a 32-bit process running on a 64-bit OS (Wow64).
        /// </summary>
        public bool IsWow64 { get; set; }

        /// <summary>
        /// AI-generated explanation about the process
        /// </summary>
        public string AiExplanation { get; set; } = string.Empty;

        /// <summary>
        /// AI-generated recommendation
        /// </summary>
        public string AiRecommendation { get; set; } = string.Empty;

        /// <summary>
        /// Whether AI analysis has been performed
        /// </summary>
        public bool AiAnalyzed { get; set; }

        /// <summary>
        /// Optimization recommendation
        /// </summary>
        public string Recommendation { get; set; } = string.Empty;

        /// <summary>
        /// Estimated RAM that can be recovered by optimizing this process
        /// </summary>
        public long EstimatedRamRecovery => IsActive ? 0 : WorkingSet;

        /// <summary>
        /// Command line arguments
        /// </summary>
        public string CommandLine { get; set; } = string.Empty;

        /// <summary>
        /// Thread count
        /// </summary>
        public int ThreadCount { get; set; }

        /// <summary>
        /// Handle count
        /// </summary>
        public int HandleCount { get; set; }

        /// <summary>
        /// Whether the process is 64-bit
        /// </summary>
        public bool Is64Bit { get; set; }

        /// <summary>
        /// Session ID
        /// </summary>
        public int SessionId { get; set; }

        /// <summary>
        /// User who owns the process
        /// </summary>
        public string UserName { get; set; } = string.Empty;

        /// <summary>
        /// List of child processes
        /// </summary>
        public List<ProcessInfo> ChildProcesses { get; set; } = new List<ProcessInfo>();

        /// <summary>
        /// Whether this is a system process (Session 0)
        /// </summary>
        public bool IsSystemProcess => SessionId == 0;

        #endregion

        #region Helper Properties

        /// <summary>
        /// RAM usage in MB
        /// </summary>
        public double WorkingSetMB => WorkingSet / (1024.0 * 1024.0);

        /// <summary>
        /// RAM usage in GB
        /// </summary>
        public double WorkingSetGB => WorkingSet / (1024.0 * 1024.0 * 1024.0);

        /// <summary>
        /// Formatted RAM usage string
        /// </summary>
        public string FormattedWorkingSet
        {
            get
            {
                if (WorkingSetGB >= 1)
                    return $"{WorkingSetGB:F2} GB";
                else if (WorkingSetMB >= 1)
                    return $"{WorkingSetMB:F2} MB";
                else
                    return $"{WorkingSet / 1024.0:F2} KB";
            }
        }

        /// <summary>
        /// Formatted CPU usage string
        /// </summary>
        public string FormattedCpuUsage => $"{CpuUsage:F1}%";

        /// <summary>
        /// Formatted GPU usage string
        /// </summary>
        public string FormattedGpuUsage => GpuUsage > 0 ? $"{GpuUsage:F1}%" : "N/A";

        /// <summary>
        /// Formatted start time
        /// </summary>
        public string FormattedStartTime => StartTime.ToString("HH:mm:ss");

        /// <summary>
        /// Formatted running time
        /// </summary>
        public string FormattedRunningTime
        {
            get
            {
                var ts = TotalRunningTime;
                if (ts.TotalHours >= 1)
                    return $"{ts.Hours}h {ts.Minutes}m {ts.Seconds}s";
                else if (ts.TotalMinutes >= 1)
                    return $"{ts.Minutes}m {ts.Seconds}s";
                else
                    return $"{ts.Seconds}s";
            }
        }

        #endregion

        #region Constructors

        /// <summary>
        /// Default constructor
        /// </summary>
        public ProcessInfo() { }

        /// <summary>
        /// Create ProcessInfo from System.Diagnostics.Process
        /// </summary>
        public ProcessInfo(Process process)
        {
            if (process == null) return;

            try
            {
                Id = process.Id;
                Name = process.ProcessName ?? string.Empty;
                
                try
                {
                    Path = process.MainModule?.FileName ?? string.Empty;
                    DisplayName = System.IO.Path.GetFileNameWithoutExtension(Name);
                }
                catch
                {
                    Path = string.Empty;
                    DisplayName = Name;
                }

                try
                {
                    var fileInfo = new FileInfo(Path);
                    if (fileInfo.Exists)
                    {
                        var versionInfo = FileVersionInfo.GetVersionInfo(Path);
                        Publisher = versionInfo.CompanyName ?? string.Empty;
                        ProductName = versionInfo.ProductName ?? string.Empty;
                        Version = versionInfo.ProductVersion ?? versionInfo.FileVersion ?? string.Empty;
                        Description = versionInfo.FileDescription ?? string.Empty;
                    }
                }
                catch { }

                WorkingSet = process.WorkingSet64;
                PeakWorkingSet = process.PeakWorkingSet64;
                PrivateMemorySize = process.PrivateMemorySize64;
                VirtualMemorySize = process.VirtualMemorySize64;
                PagedMemorySize = process.PagedMemorySize64;
                NonpagedSystemMemorySize = process.NonpagedSystemMemorySize64;
                TotalProcessorTime = process.TotalProcessorTime;
                StartTime = process.StartTime;

                // Kernel-authoritative identity: immune to clock/time-zone changes and unique
                // per incarnation of a pid. Used by the anti-PID-reuse guard. Left as MinValue
                // when the process is protected, which the safety layer treats as "unverifiable".
                CreationTimeUtc = WindowsApiHelper.GetProcessCreationTimeUtc(process.Id) ?? DateTime.MinValue;
                PriorityClass = process.PriorityClass;
                ThreadCount = process.Threads.Count;
                HandleCount = process.HandleCount;
                
                try
                {
                    UserName = process.StartInfo?.UserName ?? string.Empty;
                }
                catch { }

                try
                {
                    CommandLine = process.StartInfo?.Arguments ?? string.Empty;
                }
                catch { }

                try
                {
                    ParentId = GetParentProcessId(process);
                }
                catch { }

                try
                {
                    Is64Bit = Environment.Is64BitProcess || 
                             (process.MainModule != null && 
                              process.MainModule.ModuleName.Contains("Wow64") == false);
                }
                catch { }

                try
                {
                    SessionId = Process.GetCurrentProcess().SessionId;
                }
                catch { }

                try
                {
                    HasVisibleWindow = process.MainWindowHandle != IntPtr.Zero && 
                                     process.MainWindowTitle.Length > 0;
                }
                catch { }

                // Set defaults
                Category = ProcessCategory.Unknown;
                RiskLevel = RiskLevel.Critical;
                SignatureStatus = SignatureStatus.Unsigned;
                IsWindowsProcess = IsWindowsSystemProcess(Path);
                IsDriver = IsDriverProcess(Name, Path);
            }
            catch { }
        }

        #endregion

        #region Helper Methods

        /// <summary>
        /// Get parent process ID using Windows API
        /// </summary>
        private static int GetParentProcessId(Process process)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT ParentProcessId FROM Win32_Process WHERE ProcessId = " + process.Id))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return Convert.ToInt32(obj["ParentProcessId"]);
                    }
                }
            }
            catch { }
            return 0;
        }

        /// <summary>
        /// Check if process is a Windows system process
        /// </summary>
        private static bool IsWindowsSystemProcess(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;
            
            var lowerPath = path.ToLower();
            return lowerPath.Contains("\\windows\\") ||
                   lowerPath.Contains("\\system32\\") ||
                   lowerPath.Contains("\\syswow64\\") ||
                   lowerPath.Contains("\\microsoft\\");
        }

        /// <summary>
        /// Check if process is a driver
        /// </summary>
        private static bool IsDriverProcess(string name, string path)
        {
            if (string.IsNullOrEmpty(name)) return false;
            
            var lowerName = name.ToLower();
            var lowerPath = path.ToLower();
            
            // Common driver process names
            var driverNames = new[] {
                "ati", "nvidia", "intel", "amd", "radeon", "nv", "igfx", 
                "audio", "sound", "realtek", "conexant", "idt", "dolby",
                "network", "wifi", "ethernet", "broadcom", "intel", "qualcomm",
                "bluetooth", "bt", "touchpad", "synaptics", "elantech",
                "usb", "storage", "samsung", "sandisk", "wd", "seagate",
                "driver", "service", "helper", "manager"
            };
            
            foreach (var driver in driverNames)
            {
                if (lowerName.Contains(driver) || lowerPath.Contains(driver))
                    return true;
            }
            
            return false;
        }

        #endregion

        #region IEquatable Implementation

        public bool Equals(ProcessInfo? other)
        {
            if (other == null) return false;
            return Id == other.Id;
        }

        public override bool Equals(object? obj)
        {
            return Equals(obj as ProcessInfo);
        }

        public override int GetHashCode()
        {
            return Id.GetHashCode();
        }

        #endregion

        #region IComparable Implementation

        public int CompareTo(ProcessInfo? other)
        {
            if (other == null) return 1;
            return WorkingSet.CompareTo(other.WorkingSet);
        }

        #endregion

        #region Overrides

        public override string ToString()
        {
            return $"{DisplayName} (PID: {Id}, RAM: {FormattedWorkingSet}, CPU: {FormattedCpuUsage}, Category: {Category}, Risk: {RiskLevel})";
        }

        #endregion
    }
}

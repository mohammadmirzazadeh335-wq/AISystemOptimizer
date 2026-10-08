using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace AISystemOptimizer.Core.Constants
{
    /// <summary>
    /// Application-wide constants
    /// </summary>
    public static class AppConstants
    {
        #region Application Information

        /// <summary>
        /// Application name
        /// </summary>
        public const string AppName = "AI System Optimizer";

        /// <summary>
        /// Application description
        /// </summary>
        public const string AppDescription = "Intelligent Windows System Optimization Tool";

        /// <summary>
        /// Application version
        /// </summary>
        public static string AppVersion
        {
            get
            {
                try
                {
                    var assembly = Assembly.GetEntryAssembly();
                    if (assembly != null)
                    {
                        var version = assembly.GetName().Version;
                        if (version != null)
                            return version.ToString();
                    }
                }
                catch { }
                return "1.0.0";
            }
        }

        /// <summary>
        /// Application publisher
        /// </summary>
        public const string AppPublisher = "AI System Optimizer Team";

        /// <summary>
        /// Application copyright
        /// </summary>
        public const string AppCopyright = "© 2026 AI System Optimizer Team. All rights reserved.";

        /// <summary>
        /// Application website
        /// </summary>
        public const string AppWebsite = "https://github.com/AISystemOptimizer";

        /// <summary>
        /// Application support email
        /// </summary>
        public const string AppSupportEmail = "support@aisystemoptimizer.com";

        #endregion

        #region File and Directory Paths

        /// <summary>
        /// Application executable name
        /// </summary>
        public const string AppExecutableName = "AISystemOptimizer.exe";

        /// <summary>
        /// Application data directory name
        /// </summary>
        public const string AppDataDirectory = "AISystemOptimizer";

        /// <summary>
        /// Configuration file name
        /// </summary>
        public const string ConfigFileName = "config.json";

        /// <summary>
        /// Log directory name
        /// </summary>
        public const string LogDirectoryName = "Logs";

        /// <summary>
        /// Backup directory name
        /// </summary>
        public const string BackupDirectoryName = "Backups";

        /// <summary>
        /// Cache directory name
        /// </summary>
        public const string CacheDirectoryName = "Cache";

        /// <summary>
        /// Reports directory name
        /// </summary>
        public const string ReportsDirectoryName = "Reports";

        /// <summary>
        /// Directory holding the Game &amp; App Optimizer's data: application profiles, the never-optimise
        /// list and saved optimisation sessions. It sits beside the other data directories so that
        /// portable mode moves it too.
        /// </summary>
        public const string GameAppDirectoryName = "GameAppOptimizer";

        /// <summary>
        /// Environment variable that switches the application into true portable mode
        /// (all settings, logs, backups and reports live next to the executable).
        /// </summary>
        public const string PortableModeEnvironmentVariable = "AISYSTEMOPTIMIZER_PORTABLE";

        private static string? _resolvedDataPath;

        /// <summary>
        /// True when portable mode was requested through the environment variable.
        /// </summary>
        public static bool IsPortableMode
        {
            get
            {
                var value = Environment.GetEnvironmentVariable(PortableModeEnvironmentVariable);

                return !string.IsNullOrWhiteSpace(value) &&
                       (value.Equals("1", StringComparison.OrdinalIgnoreCase) ||
                        value.Equals("true", StringComparison.OrdinalIgnoreCase) ||
                        value.Equals("yes", StringComparison.OrdinalIgnoreCase));
            }
        }

        /// <summary>
        /// Get the application data directory path.
        ///
        ///   * normal mode    -> %LOCALAPPDATA%\AISystemOptimizer
        ///   * portable mode  -> a writable folder beside the executable (falls back to
        ///                       %LOCALAPPDATA% when the medium is read-only or locked down)
        /// </summary>
        public static string AppDataPath
        {
            get
            {
                if (_resolvedDataPath != null)
                    return _resolvedDataPath;

                _resolvedDataPath = ResolveDataPath();
                return _resolvedDataPath;
            }
        }

        private static string ResolveDataPath()
        {
            var roaming = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                AppDataDirectory);

            if (!IsPortableMode)
                return roaming;

            try
            {
                var executableDirectory = AppContext.BaseDirectory;

                if (string.IsNullOrWhiteSpace(executableDirectory))
                    return roaming;

                var portableDirectory = Path.Combine(executableDirectory, "AISystemOptimizerData");

                // Verify the location is actually writable before committing to it: a USB stick
                // with the write-protect tab on must not break the application.
                Directory.CreateDirectory(portableDirectory);

                var probe = Path.Combine(portableDirectory, ".write-test");

                using (var stream = File.Create(probe, 1, FileOptions.DeleteOnClose))
                {
                    stream.WriteByte(0);
                }

                return portableDirectory;
            }
            catch
            {
                return roaming;
            }
        }

        /// <summary>
        /// Get the configuration file path
        /// </summary>
        public static string ConfigFilePath => Path.Combine(AppDataPath, ConfigFileName);

        /// <summary>
        /// Get the log directory path
        /// </summary>
        public static string LogDirectoryPath => Path.Combine(AppDataPath, LogDirectoryName);

        /// <summary>
        /// Get the backup directory path
        /// </summary>
        public static string BackupDirectoryPath => Path.Combine(AppDataPath, BackupDirectoryName);

        /// <summary>
        /// Get the cache directory path
        /// </summary>
        public static string CacheDirectoryPath => Path.Combine(AppDataPath, CacheDirectoryName);

        /// <summary>
        /// Get the reports directory path
        /// </summary>
        public static string ReportsDirectoryPath => Path.Combine(AppDataPath, ReportsDirectoryName);

        /// <summary>Root of the Game &amp; App Optimizer's data.</summary>
        public static string GameAppDirectoryPath => Path.Combine(AppDataPath, GameAppDirectoryName);

        /// <summary>Directory holding one JSON file per application profile.</summary>
        public static string GameAppProfilesDirectoryPath =>
            Path.Combine(GameAppDirectoryPath, "profiles");

        /// <summary>File holding the user's never-optimise list.</summary>
        public static string GameAppNeverOptimizeFilePath =>
            Path.Combine(GameAppDirectoryPath, "never-optimize.json");

        /// <summary>File holding optimisation sessions that must be checkable for an interrupted run.</summary>
        public static string GameAppSessionsFilePath =>
            Path.Combine(GameAppDirectoryPath, "sessions.json");

        /// <summary>
        /// Get the full log file path
        /// </summary>
        public static string LogFilePath => Path.Combine(LogDirectoryPath, $"{DateTime.Now:yyyy-MM-dd}.log");

        /// <summary>
        /// Get the history file path
        /// </summary>
        public static string HistoryFilePath => Path.Combine(AppDataPath, "optimization_history.json");

        /// <summary>
        /// Get the whitelist file path
        /// </summary>
        public static string WhitelistFilePath => Path.Combine(AppDataPath, "whitelist.json");

        /// <summary>
        /// Get the blacklist file path
        /// </summary>
        public static string BlacklistFilePath => Path.Combine(AppDataPath, "blacklist.json");

        #endregion

        #region Default Values

        /// <summary>
        /// Default target RAM usage percentage
        /// </summary>
        public const int DefaultTargetRamUsage = 35;

        /// <summary>
        /// Default auto-optimize interval in minutes
        /// </summary>
        public const int DefaultAutoOptimizeInterval = 30;

        /// <summary>
        /// Default idle threshold in seconds
        /// </summary>
        public const int DefaultIdleThreshold = 60;

        /// <summary>
        /// Default minimum RAM usage to trigger optimization
        /// </summary>
        public const int DefaultMinRamUsageToOptimize = 50;

        /// <summary>
        /// Default minimum CPU usage to trigger optimization
        /// </summary>
        public const int DefaultMinCpuUsageToOptimize = 10;

        /// <summary>
        /// Default AI confidence threshold
        /// </summary>
        public const float DefaultAiConfidenceThreshold = 0.7f;

        /// <summary>
        /// Default maximum log file size in MB
        /// </summary>
        public const int DefaultMaxLogFileSizeMB = 10;

        /// <summary>
        /// Default number of log files to keep
        /// </summary>
        public const int DefaultMaxLogFiles = 5;

        /// <summary>
        /// Default number of backup versions to keep
        /// </summary>
        public const int DefaultBackupVersionsToKeep = 5;

        /// <summary>
        /// Default window transparency
        /// </summary>
        public const int DefaultWindowTransparency = 95;

        #endregion

        #region System Values

        /// <summary>
        /// Minimum RAM for optimization (in MB)
        /// </summary>
        public const long MinRamForOptimization = 1024; // 1 GB

        /// <summary>
        /// Minimum CPU cores for optimization
        /// </summary>
        public const int MinCpuCoresForOptimization = 2;

        /// <summary>
        /// Minimum disk space for optimization (in GB)
        /// </summary>
        public const long MinDiskSpaceForOptimization = 10; // 10 GB

        /// <summary>
        /// Maximum allowed RAM usage before warning
        /// </summary>
        public const float MaxRamUsageWarning = 90f;

        /// <summary>
        /// Maximum allowed CPU usage before warning
        /// </summary>
        public const float MaxCpuUsageWarning = 95f;

        /// <summary>
        /// Maximum allowed disk usage before warning
        /// </summary>
        public const float MaxDiskUsageWarning = 95f;

        #endregion

        #region Performance Counters

        /// <summary>
        /// Performance counter category for processor
        /// </summary>
        public const string ProcessorCategory = "Processor";

        /// <summary>
        /// Performance counter for processor usage
        /// </summary>
        public const string ProcessorUsageCounter = "% Processor Time";

        /// <summary>
        /// Performance counter instance for total processor
        /// </summary>
        public const string ProcessorTotalInstance = "_Total";

        /// <summary>
        /// Performance counter category for memory
        /// </summary>
        public const string MemoryCategory = "Memory";

        /// <summary>
        /// Performance counter for available memory
        /// </summary>
        public const string AvailableMemoryCounter = "Available MBytes";

        /// <summary>
        /// Performance counter for total memory
        /// </summary>
        public const string TotalMemoryCounter = "Total Physical Memory";

        /// <summary>
        /// Performance counter category for physical disk
        /// </summary>
        public const string DiskCategory = "PhysicalDisk";

        /// <summary>
        /// Performance counter for disk read
        /// </summary>
        public const string DiskReadCounter = "Disk Read Bytes/sec";

        /// <summary>
        /// Performance counter for disk write
        /// </summary>
        public const string DiskWriteCounter = "Disk Write Bytes/sec";

        /// <summary>
        /// Performance counter for disk activity
        /// </summary>
        public const string DiskActivityCounter = "% Disk Time";

        /// <summary>
        /// Performance counter category for network
        /// </summary>
        public const string NetworkCategory = "Network Interface";

        /// <summary>
        /// Performance counter for bytes received
        /// </summary>
        public const string NetworkReceivedCounter = "Bytes Received/sec";

        /// <summary>
        /// Performance counter for bytes sent
        /// </summary>
        public const string NetworkSentCounter = "Bytes Sent/sec";

        #endregion

        #region Windows API Constants

        /// <summary>
        /// WM_QUERYENDSESSION message
        /// </summary>
        public const int WM_QUERYENDSESSION = 0x0011;

        /// <summary>
        /// WM_ENDSESSION message
        /// </summary>
        public const int WM_ENDSESSION = 0x0016;

        /// <summary>
        /// ENDSESSION_CLOSEAPP flag
        /// </summary>
        public const int ENDSESSION_CLOSEAPP = 0x00000001;

        /// <summary>
        /// PROCESS_TERMINATE access right
        /// </summary>
        public const int PROCESS_TERMINATE = 0x0001;

        /// <summary>
        /// PROCESS_QUERY_INFORMATION access right
        /// </summary>
        public const int PROCESS_QUERY_INFORMATION = 0x0400;

        /// <summary>
        /// PROCESS_QUERY_LIMITED_INFORMATION access right
        /// </summary>
        public const int PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;

        /// <summary>
        /// PROCESS_SET_INFORMATION access right
        /// </summary>
        public const int PROCESS_SET_INFORMATION = 0x0200;

        /// <summary>
        /// PROCESS_SUSPEND_RESUME access right
        /// </summary>
        public const int PROCESS_SUSPEND_RESUME = 0x0800;

        /// <summary>
        /// PROCESS_ALL_ACCESS access right
        /// </summary>
        public const int PROCESS_ALL_ACCESS = 0x1F0FFF;

        /// <summary>
        /// SYNCHRONIZE access right
        /// </summary>
        public const int SYNCHRONIZE = 0x00100000;

        /// <summary>
        /// STANDARD_RIGHTS_REQUIRED
        /// </summary>
        public const int STANDARD_RIGHTS_REQUIRED = 0x000F0000;

        /// <summary>
        /// Token elevation type
        /// </summary>
        public const int TOKEN_ELEVATION_TYPE = 18;

        /// <summary>
        /// Token elevation type limited
        /// </summary>
        public const int TOKEN_ELEVATION_TYPE_LIMITED = 1;

        /// <summary>
        /// Token elevation type full
        /// </summary>
        public const int TOKEN_ELEVATION_TYPE_FULL = 2;

        #endregion

        #region Registry Keys

        /// <summary>
        /// Registry key for Windows startup
        /// </summary>
        public const string RegistryStartupKey = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run";

        /// <summary>
        /// Registry key for Windows startup (64-bit)
        /// </summary>
        public const string RegistryStartupKey64 = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run";

        /// <summary>
        /// Registry key for Windows startup (all users)
        /// </summary>
        public const string RegistryStartupAllUsersKey = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run";

        /// <summary>
        /// Registry key for Windows services
        /// </summary>
        public const string RegistryServicesKey = "SYSTEM\\CurrentControlSet\\Services";

        /// <summary>
        /// Registry key for Windows Defender
        /// </summary>
        public const string RegistryDefenderKey = "SOFTWARE\\Microsoft\\Windows Defender";

        /// <summary>
        /// Registry key for Windows Update
        /// </summary>
        public const string RegistryWindowsUpdateKey = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate";

        /// <summary>
        /// Registry key for power settings
        /// </summary>
        public const string RegistryPowerSettingsKey = "SYSTEM\\CurrentControlSet\\Control\\Power";

        /// <summary>
        /// Registry key for UAC settings
        /// </summary>
        public const string RegistryUacKey = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System";

        /// <summary>
        /// Registry value for UAC enable/disable
        /// </summary>
        public const string RegistryUacEnableLUA = "EnableLUA";

        #endregion

        #region WMI Queries

        /// <summary>
        /// WMI query for running processes
        /// </summary>
        public const string WmiProcessQuery = "SELECT * FROM Win32_Process";

        /// <summary>
        /// WMI query for services
        /// </summary>
        public const string WmiServiceQuery = "SELECT * FROM Win32_Service";

        /// <summary>
        /// WMI query for startup programs
        /// </summary>
        public const string WmiStartupQuery = "SELECT * FROM Win32_StartupCommand";

        /// <summary>
        /// WMI query for logical disks
        /// </summary>
        public const string WmiDiskQuery = "SELECT * FROM Win32_LogicalDisk";

        /// <summary>
        /// WMI query for physical disks
        /// </summary>
        public const string WmiPhysicalDiskQuery = "SELECT * FROM Win32_DiskDrive";

        /// <summary>
        /// WMI query for CPU information
        /// </summary>
        public const string WmiCpuQuery = "SELECT * FROM Win32_Processor";

        /// <summary>
        /// WMI query for memory information
        /// </summary>
        public const string WmiMemoryQuery = "SELECT * FROM Win32_PhysicalMemory";

        /// <summary>
        /// WMI query for GPU information
        /// </summary>
        public const string WmiGpuQuery = "SELECT * FROM Win32_VideoController";

        /// <summary>
        /// WMI query for network adapters
        /// </summary>
        public const string WmiNetworkAdapterQuery = "SELECT * FROM Win32_NetworkAdapter";

        /// <summary>
        /// WMI query for operating system information
        /// </summary>
        public const string WmiOsQuery = "SELECT * FROM Win32_OperatingSystem";

        /// <summary>
        /// WMI query for computer system information
        /// </summary>
        public const string WmiComputerSystemQuery = "SELECT * FROM Win32_ComputerSystem";

        #endregion

        #region Timeouts

        /// <summary>
        /// Default timeout for process termination in milliseconds
        /// </summary>
        public const int DefaultProcessTerminationTimeout = 5000;

        /// <summary>
        /// Default timeout for service operations in milliseconds
        /// </summary>
        public const int DefaultServiceOperationTimeout = 10000;

        /// <summary>
        /// Default timeout for WMI queries in milliseconds
        /// </summary>
        public const int DefaultWmiQueryTimeout = 5000;

        /// <summary>
        /// Default timeout for AI requests in seconds
        /// </summary>
        public const int DefaultAiRequestTimeout = 30;

        /// <summary>
        /// Default timeout for system scan in seconds
        /// </summary>
        public const int DefaultSystemScanTimeout = 60;

        /// <summary>
        /// Default timeout for optimization execution in seconds
        /// </summary>
        public const int DefaultOptimizationTimeout = 120;

        #endregion

        #region Error Messages

        /// <summary>
        /// Error message for access denied
        /// </summary>
        public const string ErrorAccessDenied = "Access denied. Please run the application as administrator.";

        /// <summary>
        /// Error message for process not found
        /// </summary>
        public const string ErrorProcessNotFound = "Process not found or already terminated.";

        /// <summary>
        /// Error message for service not found
        /// </summary>
        public const string ErrorServiceNotFound = "Service not found.";

        /// <summary>
        /// Error message for invalid operation
        /// </summary>
        public const string ErrorInvalidOperation = "Invalid operation for this process or service.";

        /// <summary>
        /// Error message for timeout
        /// </summary>
        public const string ErrorTimeout = "Operation timed out.";

        /// <summary>
        /// Error message for AI not available
        /// </summary>
        public const string ErrorAiNotAvailable = "AI service is not available.";

        /// <summary>
        /// Error message for AI request failed
        /// </summary>
        public const string ErrorAiRequestFailed = "AI request failed.";

        /// <summary>
        /// Error message for configuration not found
        /// </summary>
        public const string ErrorConfigNotFound = "Configuration file not found.";

        /// <summary>
        /// Error message for invalid configuration
        /// </summary>
        public const string ErrorInvalidConfig = "Invalid configuration.";

        #endregion

        #region Success Messages

        /// <summary>
        /// Success message for optimization completed
        /// </summary>
        public const string SuccessOptimizationCompleted = "Optimization completed successfully.";

        /// <summary>
        /// Success message for process terminated
        /// </summary>
        public const string SuccessProcessTerminated = "Process terminated successfully.";

        /// <summary>
        /// Success message for service stopped
        /// </summary>
        public const string SuccessServiceStopped = "Service stopped successfully.";

        /// <summary>
        /// Success message for service disabled
        /// </summary>
        public const string SuccessServiceDisabled = "Service disabled successfully.";

        /// <summary>
        /// Success message for startup disabled
        /// </summary>
        public const string SuccessStartupDisabled = "Startup item disabled successfully.";

        /// <summary>
        /// Success message for cache cleared
        /// </summary>
        public const string SuccessCacheCleared = "Cache cleared successfully.";

        #endregion

        #region Warnings

        /// <summary>
        /// Warning for high risk action
        /// </summary>
        public const string WarningHighRiskAction = "This is a high-risk action. Proceed with caution.";

        /// <summary>
        /// Warning for critical action
        /// </summary>
        public const string WarningCriticalAction = "This is a critical action that could cause system instability. Not recommended.";

        /// <summary>
        /// Warning for no optimization needed
        /// </summary>
        public const string WarningNoOptimizationNeeded = "System is already optimized. No significant improvements can be made.";

        /// <summary>
        /// Warning for low RAM
        /// </summary>
        public const string WarningLowRam = "System has low available RAM. Consider closing some applications.";

        /// <summary>
        /// Warning for high CPU usage
        /// </summary>
        public const string WarningHighCpuUsage = "System has high CPU usage. Some applications may be consuming excessive resources.";

        /// <summary>
        /// Warning for high disk usage
        /// </summary>
        public const string WarningHighDiskUsage = "System disk is nearly full. Consider freeing up some space.";

        #endregion

        #region AI Prompts

        /// <summary>
        /// AI prompt for single-process analysis.
        /// Placeholders are filled with string.Format:
        ///   {0} name, {1} path, {2} publisher, {3} description,
        ///   {4} RAM (MB), {5} CPU (%), {6} category, {7} risk level,
        ///   {8} has visible window, {9} is service
        /// </summary>
        public static readonly string AiProcessAnalysisPrompt = """
You are an expert Windows system analyst. Analyze the following process and provide:

1. What is this process?
2. What program or service does it belong to?
3. Is it a Windows system process?
4. Is it likely needed by the user?
5. Is it safe to terminate?
6. Will it restart automatically if terminated?
7. Does its RAM usage warrant optimization?

Provide your analysis in a clear, concise format. Be conservative with recommendations to terminate processes.

Process Information:
- Name: {0}
- Path: {1}
- Publisher: {2}
- Description: {3}
- RAM Usage: {4} MB
- CPU Usage: {5}%
- Category: {6}
- Risk Level: {7}
- Has Visible Window: {8}
- Is Service: {9}

Respond with the following JSON object and nothing else.
Do not add markdown code fences, comments or trailing text:

{{
  "process_name": "name",
  "program": "program name",
  "is_windows_process": true,
  "is_needed": true,
  "is_safe_to_terminate": false,
  "will_restart": false,
  "worth_optimizing": false,
  "explanation": "detailed factual explanation",
  "recommendation": "short actionable recommendation"
}}
""";

        /// <summary>
        /// AI prompt for whole-system optimization planning.
        /// Placeholders are filled with string.Format:
        ///   {0} OS, {1} CPU, {2} core count, {3} total RAM (GB), {4} RAM used (%),
        ///   {5} GPU, {6} disk summary, {7} disk used (%), {8} process count,
        ///   {9} startup item count, {10} service count, {11} top consumers table
        /// </summary>
        public static readonly string AiSystemOptimizationPrompt = """
You are an expert Windows system optimizer. Based on the following system information, provide optimization recommendations.

System Information:
- OS: {0}
- CPU: {1} ({2} cores)
- RAM: {3} GB ({4}% used)
- GPU: {5}
- Disk: {6} ({7}% used)
- Running Processes: {8}
- Startup Items: {9}
- Services: {10}

Top Resource Consumers:
{11}

Provide recommendations for:
1. Processes to close (only if genuinely safe)
2. Startup items to disable
3. Services to stop or disable (only if genuinely safe)
4. General system optimization suggestions

Rules you must follow:
- Be conservative. Prioritise stability over maximum RAM recovery.
- Never recommend disabling Windows Defender, Windows Firewall, UAC or critical services.
- Never recommend deleting system files, disabling the pagefile or editing unknown registry keys.
- If no meaningful optimization is possible, say so honestly.

Respond with the following JSON object and nothing else.
Do not add markdown code fences, comments or trailing text:

{{
  "recommendations": [
    {{
      "type": "close_process",
      "target": "process_name.exe",
      "reason": "reason for recommendation",
      "estimated_ram_recovery_mb": 100,
      "estimated_cpu_improvement_percent": 5,
      "risk_level": "low",
      "priority": 5
    }},
    {{
      "type": "disable_startup",
      "target": "startup_item_name",
      "reason": "reason for recommendation",
      "estimated_ram_recovery_mb": 50,
      "estimated_cpu_improvement_percent": 0,
      "risk_level": "low",
      "priority": 3
    }},
    {{
      "type": "general",
      "target": "general",
      "reason": "general advice for the user",
      "estimated_ram_recovery_mb": 0,
      "estimated_cpu_improvement_percent": 0,
      "risk_level": "low",
      "priority": 1
    }}
  ],
  "summary": "brief summary of optimization potential",
  "estimated_total_ram_recovery_mb": 500,
  "estimated_cpu_improvement_percent": 5
}}
""";

        #endregion
    }
}

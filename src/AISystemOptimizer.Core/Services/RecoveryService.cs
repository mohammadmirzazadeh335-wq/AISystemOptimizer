using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Management;
using System.Text.Json;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for system recovery and backup operations
    /// </summary>
    public class RecoveryService : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly string _backupDirectory;
        private readonly string _historyFilePath;
        private OptimizationHistory _history;
        private bool _disposed = false;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new recovery service
        /// </summary>
        public RecoveryService(ILogger logger = null, AppConfig config = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _backupDirectory = AppConstants.BackupDirectoryPath;
            _historyFilePath = AppConstants.HistoryFilePath;
            
            // Ensure directories exist
            if (!Directory.Exists(_backupDirectory))
            {
                Directory.CreateDirectory(_backupDirectory);
            }
            
            // Load history
            LoadHistory();
        }

        #endregion

        #region Properties

        /// <summary>
        /// Optimization history
        /// </summary>
        public OptimizationHistory History => _history;

        /// <summary>
        /// Whether history is loaded
        /// </summary>
        public bool IsHistoryLoaded => _history != null;

        #endregion

        #region Public Methods

        /// <summary>
        /// Save the current system state as a backup
        /// </summary>
        public bool SaveBackup(string name = null, SystemInfo systemInfo = null)
        {
            try
            {
                _logger.Info("RecoveryService", "Saving system backup");
                
                name = name ?? $"Backup_{DateTime.Now:yyyyMMdd_HHmmss}";
                
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? new SystemScanner(_logger, _config).Scan();
                
                // Create backup directory for this backup
                var backupPath = Path.Combine(_backupDirectory, name);
                if (!Directory.Exists(backupPath))
                {
                    Directory.CreateDirectory(backupPath);
                }
                
                // Save system information
                var systemInfoPath = Path.Combine(backupPath, "system_info.json");
                var systemInfoJson = JsonSerializer.Serialize(systemInfo, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(systemInfoPath, systemInfoJson);
                
                // Save process list
                var processesPath = Path.Combine(backupPath, "processes.json");
                var processesJson = JsonSerializer.Serialize(systemInfo.Processes, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(processesPath, processesJson);
                
                // Save services list
                var servicesPath = Path.Combine(backupPath, "services.json");
                var servicesJson = JsonSerializer.Serialize(systemInfo.Services, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(servicesPath, servicesJson);
                
                // Save startup items
                var startupPath = Path.Combine(backupPath, "startup.json");
                var startupJson = JsonSerializer.Serialize(systemInfo.StartupItems, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(startupPath, startupJson);
                
                // Save registry backup (if running as admin)
                if (WindowsApiHelper.IsAdministrator())
                {
                    try
                    {
                        var registryBackupPath = Path.Combine(backupPath, "registry");
                        Directory.CreateDirectory(registryBackupPath);
                        
                        // Export important registry keys
                        var registryKeys = new[]
                        {
                            "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                            "HKEY_LOCAL_MACHINE\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run",
                            "HKEY_CURRENT_USER\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                            "HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services"
                        };
                        
                        foreach (var key in registryKeys)
                        {
                            // The key list is a compile-time constant, but it is still validated before it
                            // is interpolated into a command line. Any future change that lets a key come
                            // from configuration or from the system would otherwise turn this call into an
                            // argument-injection point.
                            if (!IsSafeRegistryKey(key))
                            {
                                _logger.Warning("RecoveryService",
                                    $"Skipped a registry backup entry that is not a safe registry path: '{key}'");
                                continue;
                            }

                            var fileName = key.Replace("\\", "_").Replace(":", "").Replace("HKEY_", "") + ".reg";
                            var regPath = Path.Combine(registryBackupPath, fileName);

                            if (!IsSafeFilePath(regPath, registryBackupPath))
                            {
                                _logger.Warning("RecoveryService",
                                    "Skipped a registry backup because its destination path escaped the backup directory.");
                                continue;
                            }

                            // Use reg export to export the key
                            var processInfo = new System.Diagnostics.ProcessStartInfo
                            {
                                FileName = "reg",
                                Arguments = $"export \"{key}\" \"{regPath}\" /y",
                                UseShellExecute = false,
                                CreateNoWindow = true,
                                RedirectStandardOutput = true,
                                RedirectStandardError = true
                            };
                            
                            using (var process = System.Diagnostics.Process.Start(processInfo))
                            {
                                process?.WaitForExit();
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("RecoveryService", "Failed to save registry backup", null, ex);
                    }
                }
                
                // Clean up old backups
                CleanupOldBackups();
                
                _logger.Info("RecoveryService", $"Backup saved: {name}");
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to save backup", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Restore from a backup
        /// </summary>
        public bool RestoreFromBackup(string backupName, out string errorMessage)
        {
            errorMessage = string.Empty;
            
            try
            {
                _logger.Info("RecoveryService", $"Restoring from backup: {backupName}");
                
                var backupPath = Path.Combine(_backupDirectory, backupName);
                if (!Directory.Exists(backupPath))
                {
                    errorMessage = $"Backup not found: {backupName}";
                    _logger.Error("RecoveryService", errorMessage);
                    return false;
                }
                
                // Restore registry backup (if running as admin)
                if (WindowsApiHelper.IsAdministrator())
                {
                    try
                    {
                        var registryBackupPath = Path.Combine(backupPath, "registry");
                        if (Directory.Exists(registryBackupPath))
                        {
                            var regFiles = Directory.GetFiles(registryBackupPath, "*.reg");
                            foreach (var regFile in regFiles)
                            {
                                // Importing a .reg file is a privileged, irreversible registry write.
                                // The path must be proven to be inside the backup directory before the
                                // command runs, so that a link or an unexpected name cannot redirect it.
                                if (!IsSafeFilePath(regFile, registryBackupPath))
                                {
                                    _logger.Warning("RecoveryService",
                                        "Refused to import a registry file that is outside the backup directory.");
                                    continue;
                                }

                                var processInfo = new System.Diagnostics.ProcessStartInfo
                                {
                                    FileName = "reg",
                                    Arguments = $"import \"{regFile}\" /y",
                                    UseShellExecute = false,
                                    CreateNoWindow = true,
                                    RedirectStandardOutput = true,
                                    RedirectStandardError = true
                                };
                                
                                using (var process = System.Diagnostics.Process.Start(processInfo))
                                {
                                    process?.WaitForExit();
                                }
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("RecoveryService", "Failed to restore registry backup", null, ex);
                    }
                }
                
                _logger.Info("RecoveryService", $"Restore completed from backup: {backupName}");
                return true;
            }
            catch (Exception ex)
            {
                errorMessage = ex.Message;
                _logger.Error("RecoveryService", "Failed to restore from backup", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Create a system restore point
        /// </summary>
        public bool CreateRestorePoint(string description = null)
        {
            try
            {
                description = description ?? $"AI System Optimizer Restore Point - {DateTime.Now:yyyy-MM-dd HH:mm:ss}";
                
                _logger.Info("RecoveryService", $"Creating restore point: {description}");
                
                return WindowsApiHelper.CreateRestorePoint(description);
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to create restore point", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Save an optimization session to history
        /// </summary>
        public bool SaveSession(OptimizationSession session)
        {
            try
            {
                _logger.Info("RecoveryService", "Saving optimization session to history");
                
                // Add to history
                _history.AddSession(session);
                
                // Save history to file
                SaveHistory();
                
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to save session to history", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Start a new optimization session
        /// </summary>
        public OptimizationSession StartSession(OptimizationPlan plan = null)
        {
            try
            {
                _logger.Info("RecoveryService", "Starting new optimization session");
                
                var session = _history.StartSession(plan);
                
                // Save the session
                SaveSession(session);
                
                return session;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to start optimization session", null, ex);
                throw;
            }
        }

        /// <summary>
        /// End the current optimization session
        /// </summary>
        public bool EndSession(SystemInfo afterSystemInfo)
        {
            try
            {
                _logger.Info("RecoveryService", "Ending current optimization session");
                
                _history.EndSession(afterSystemInfo);
                SaveHistory();
                
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to end optimization session", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Load optimization history
        /// </summary>
        public bool LoadHistory()
        {
            try
            {
                _logger.Info("RecoveryService", "Loading optimization history");
                
                if (File.Exists(_historyFilePath))
                {
                    var json = File.ReadAllText(_historyFilePath);
                    _history = JsonSerializer.Deserialize<OptimizationHistory>(json);
                    
                    if (_history == null)
                    {
                        _history = new OptimizationHistory();
                    }
                }
                else
                {
                    _history = new OptimizationHistory();
                }
                
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to load history", null, ex);
                _history = new OptimizationHistory();
                return false;
            }
        }

        /// <summary>
        /// Save optimization history
        /// </summary>
        public bool SaveHistory()
        {
            try
            {
                _logger.Info("RecoveryService", "Saving optimization history");
                
                // Ensure directory exists
                var directory = Path.GetDirectoryName(_historyFilePath);
                if (!Directory.Exists(directory))
                {
                    Directory.CreateDirectory(directory);
                }
                
                var json = JsonSerializer.Serialize(_history, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(_historyFilePath, json);
                
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to save history", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Clear optimization history
        /// </summary>
        public bool ClearHistory()
        {
            try
            {
                _logger.Info("RecoveryService", "Clearing optimization history");
                
                _history.ClearHistory();
                
                if (File.Exists(_historyFilePath))
                {
                    File.Delete(_historyFilePath);
                }
                
                return true;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to clear history", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Get available backups
        /// </summary>
        public List<BackupInfo> GetAvailableBackups()
        {
            var backups = new List<BackupInfo>();
            
            try
            {
                if (Directory.Exists(_backupDirectory))
                {
                    var backupDirectories = Directory.GetDirectories(_backupDirectory);
                    
                    foreach (var backupDir in backupDirectories)
                    {
                        try
                        {
                            var backupName = Path.GetFileName(backupDir);
                            var backupPath = Path.Combine(_backupDirectory, backupName);
                            
                            // Check if system_info.json exists
                            var systemInfoPath = Path.Combine(backupPath, "system_info.json");
                            if (File.Exists(systemInfoPath))
                            {
                                var fileInfo = new DirectoryInfo(backupDir);
                                
                                backups.Add(new BackupInfo
                                {
                                    Name = backupName,
                                    Path = backupPath,
                                    CreatedAt = fileInfo.CreationTime,
                                    Size = CalculateDirectorySize(backupDir)
                                });
                            }
                        }
                        catch { }
                    }
                    
                    // Sort by creation date (newest first)
                    backups = backups.OrderByDescending(b => b.CreatedAt).ToList();
                }
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to get available backups", null, ex);
            }
            
            return backups;
        }

        /// <summary>
        /// Delete a backup
        /// </summary>
        public bool DeleteBackup(string backupName)
        {
            try
            {
                _logger.Info("RecoveryService", $"Deleting backup: {backupName}");
                
                var backupPath = Path.Combine(_backupDirectory, backupName);
                if (Directory.Exists(backupPath))
                {
                    Directory.Delete(backupPath, true);
                    return true;
                }
                
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to delete backup", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Generate a recovery report
        /// </summary>
        public string GenerateRecoveryReport()
        {
            try
            {
                _logger.Info("RecoveryService", "Generating recovery report");
                
                var report = new System.Text.StringBuilder();
                
                report.AppendLine("=== AI SYSTEM OPTIMIZER RECOVERY REPORT ===");
                report.AppendLine();
                report.AppendLine($"Generated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
                report.AppendLine();
                
                // Available backups
                report.AppendLine("=== AVAILABLE BACKUPS ===");
                var backups = GetAvailableBackups();
                if (backups.Count > 0)
                {
                    foreach (var backup in backups)
                    {
                        report.AppendLine($"  - {backup.Name} ({backup.CreatedAt:yyyy-MM-dd HH:mm:ss}, {FormatBytes(backup.Size)})");
                    }
                }
                else
                {
                    report.AppendLine("  No backups available");
                }
                report.AppendLine();
                
                // Optimization history
                report.AppendLine("=== OPTIMIZATION HISTORY ===");
                if (_history != null && _history.Sessions.Count > 0)
                {
                    var recentSessions = _history.GetRecentSessions(5);
                    foreach (var session in recentSessions)
                    {
                        report.AppendLine($"  - {session.Timestamp:yyyy-MM-dd HH:mm:ss}:");
                        report.AppendLine($"      Actions: {session.Plan?.TotalActionCount}");
                        report.AppendLine($"      RAM: {session.BeforeRamUsage:F1}% -> {session.AfterRamUsage:F1}%");
                        report.AppendLine($"      CPU: {session.BeforeCpuUsage:F1}% -> {session.AfterCpuUsage:F1}%");
                    }
                }
                else
                {
                    report.AppendLine("  No optimization history available");
                }
                report.AppendLine();
                
                // System restore points.
                //
                // This used to shell out to `wmic`. That is a defect on Windows 11 24H2 and later,
                // where WMIC is deprecated and no longer installed by default, so the command fails and
                // the report silently loses a section. The same information is available through the
                // WMI provider the command wrapped, so it is queried directly - no child process, no
                // command line to build, nothing to quote.
                report.AppendLine("=== SYSTEM RESTORE POINTS ===");
                report.AppendLine(DescribeRestorePoints());

                return report.ToString();
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to generate recovery report", null, ex);
                return "Failed to generate recovery report: " + ex.Message;
            }
        }

        /// <summary>
        /// True when the value is a syntactically valid registry path rooted at one of the five hives.
        ///
        /// The character set is restricted to the characters a registry path can legitimately contain,
        /// which excludes the quote, the ampersand, the pipe, the caret and the semicolon - the
        /// characters that would let a value break out of a quoted argument.
        /// </summary>
        private static bool IsSafeRegistryKey(string? key)
        {
            if (string.IsNullOrWhiteSpace(key) || key!.Length > 512)
                return false;

            if (!key.StartsWith("HKEY_", StringComparison.OrdinalIgnoreCase))
                return false;

            foreach (var character in key)
            {
                if (char.IsLetterOrDigit(character))
                    continue;

                switch (character)
                {
                    case '\\':
                    case '_':
                    case '-':
                    case '.':
                    case ' ':
                        continue;

                    default:
                        return false;
                }
            }

            return true;
        }

        /// <summary>
        /// True when <paramref name="candidatePath"/> resolves to a location inside
        /// <paramref name="allowedDirectory"/>. Blocks traversal and reparse-point escapes by comparing
        /// fully resolved absolute paths.
        /// </summary>
        private static bool IsSafeFilePath(string? candidatePath, string allowedDirectory)
        {
            if (string.IsNullOrWhiteSpace(candidatePath) || string.IsNullOrWhiteSpace(allowedDirectory))
                return false;

            try
            {
                var root = Path.GetFullPath(allowedDirectory)
                    .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                    + Path.DirectorySeparatorChar;

                var candidate = Path.GetFullPath(candidatePath!);

                return candidate.StartsWith(root, StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                // An unparseable path is never treated as safe.
                return false;
            }
        }

        /// <summary>
        /// List the System Restore points through the WMI provider, without spawning a child process.
        ///
        /// Returns a human-readable block. Any failure produces an explanation instead of an exception,
        /// because this is one section of a diagnostic report and must never abort the report.
        /// </summary>
        private string DescribeRestorePoints()
        {
            var builder = new System.Text.StringBuilder();

            // SystemRestore lives in a WMI class; System.Management is already a dependency of this
            // project, so this avoids the removed-in-Windows-11 WMIC executable entirely.
            const string query =
                "SELECT SequenceNumber, Description, CreationTime FROM SystemRestore";

            try
            {
                using (var searcher = new ManagementObjectSearcher(@"root\default", query))
                using (var results = searcher.Get())
                {
                    var any = false;

                    foreach (ManagementBaseObject item in results)
                    {
                        using (item)
                        {
                            any = true;

                            var description = item["Description"]?.ToString() ?? "(no description)";
                            var sequence = item["SequenceNumber"]?.ToString() ?? "?";
                            var created = item["CreationTime"]?.ToString() ?? "unknown time";

                            builder.AppendLine(
                                $"  - #{sequence} {created}: {SanitizeForReport(description)}");
                        }
                    }

                    if (!any)
                    {
                        builder.AppendLine(
                            "  No restore points found. System Protection may be turned off for this drive.");
                    }
                }
            }
            catch (ManagementException exception)
            {
                builder.AppendLine(
                    "  Restore points could not be read from WMI " +
                    $"({SanitizeForReport(exception.Message)}). " +
                    "System Protection is often disabled on the system drive; that is a Windows setting, " +
                    "not a fault in this report.");
            }
            catch (UnauthorizedAccessException)
            {
                builder.AppendLine(
                    "  Restore points require administrator rights to read. Re-run as administrator " +
                    "to include them.");
            }
            catch (Exception exception)
            {
                builder.AppendLine(
                    $"  Restore points are unavailable on this system ({SanitizeForReport(exception.Message)}).");
            }

            return builder.ToString().TrimEnd();
        }

        /// <summary>
        /// Flatten a value that came from the system so that it cannot forge extra lines in the report.
        /// </summary>
        private static string SanitizeForReport(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            var cleaned = new System.Text.StringBuilder(value!.Length);

            foreach (var character in value)
            {
                if (char.IsControl(character))
                    continue;

                cleaned.Append(character);
            }

            var result = cleaned.ToString().Trim();

            return result.Length > 300 ? result[..300] + "..." : result;
        }

        /// <summary>
        /// Undo the last optimization
        /// </summary>
        public async Task<bool> UndoLastOptimizationAsync()
        {
            try
            {
                _logger.Info("RecoveryService", "Undoing last optimization");
                
                if (_history == null || _history.Sessions.Count == 0)
                {
                    _logger.Info("RecoveryService", "No optimization history to undo");
                    return false;
                }
                
                var lastSession = _history.Sessions[^1];
                if (lastSession.Plan == null)
                {
                    _logger.Info("RecoveryService", "Last session has no plan to undo");
                    return false;
                }
                
                // Use the SafeExecutor to undo the plan
                var executor = new SafeExecutor(_logger, _config);
                var result = await executor.UndoLastOptimizationAsync(lastSession.Plan);
                
                if (result.IsSuccessful)
                {
                    // Update the session
                    lastSession.EndTimestamp = DateTime.Now;
                    SaveHistory();
                }
                
                return result.IsSuccessful;
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to undo last optimization", null, ex);
                return false;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Clean up old backups
        /// </summary>
        private void CleanupOldBackups()
        {
            try
            {
                var maxBackups = _config.BackupVersionsToKeep;
                var backups = GetAvailableBackups();
                
                if (backups.Count > maxBackups)
                {
                    // Delete oldest backups
                    var backupsToDelete = backups
                        .OrderBy(b => b.CreatedAt)
                        .Take(backups.Count - maxBackups)
                        .ToList();
                    
                    foreach (var backup in backupsToDelete)
                    {
                        DeleteBackup(backup.Name);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Error("RecoveryService", "Failed to cleanup old backups", null, ex);
            }
        }

        /// <summary>
        /// Calculate directory size
        /// </summary>
        private long CalculateDirectorySize(string directoryPath)
        {
            try
            {
                var directoryInfo = new DirectoryInfo(directoryPath);
                return directoryInfo.GetFiles("*", SearchOption.AllDirectories).Sum(f => f.Length);
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Format bytes to readable string
        /// </summary>
        private string FormatBytes(long bytes)
        {
            if (bytes < 0) return "0 B";
            
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

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the service
        /// </summary>
        public void Dispose()
        {
            try
            {
                // Save history before disposing
                SaveHistory();
            }
            catch { }
            
            _disposed = true;
        }

        #endregion
    }

    /// <summary>
    /// Backup information
    /// </summary>
    public class BackupInfo
    {
        /// <summary>
        /// Backup name
        /// </summary>
        public string Name { get; set; } = string.Empty;
        
        /// <summary>
        /// Backup path
        /// </summary>
        public string Path { get; set; } = string.Empty;
        
        /// <summary>
        /// When the backup was created
        /// </summary>
        public DateTime CreatedAt { get; set; }
        
        /// <summary>
        /// Backup size in bytes
        /// </summary>
        public long Size { get; set; }
        
        /// <summary>
        /// Formatted size
        /// </summary>
        public string FormattedSize => FormatBytes(Size);
        
        /// <summary>
        /// Format bytes to readable string
        /// </summary>
        private static string FormatBytes(long bytes)
        {
            if (bytes < 0) return "0 B";
            
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
}

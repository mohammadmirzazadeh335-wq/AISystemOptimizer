using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for managing startup applications
    /// </summary>
    public class StartupManager : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private List<SystemInfo.StartupItem> _startupItems;
        private DateTime _lastRefreshTime;

        // Remembers the exact command line removed from each start-up entry so Undo can restore it.
        private readonly Dictionary<string, string> _removedStartupValues =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private bool _disposed = false;

        #endregion

        #region Events

        /// <summary>
        /// Event raised when startup items are refreshed
        /// </summary>
        public event EventHandler<StartupEventArgs> StartupItemsRefreshed;

        /// <summary>
        /// Event raised when a startup item is enabled/disabled
        /// </summary>
        public event EventHandler<StartupItemEventArgs> StartupItemChanged;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new startup manager
        /// </summary>
        public StartupManager(ILogger logger = null, AppConfig config = null, SystemScanner scanner = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _startupItems = new List<SystemInfo.StartupItem>();
            _lastRefreshTime = DateTime.MinValue;
        }

        #endregion

        #region Properties

        /// <summary>
        /// List of startup items
        /// </summary>
        public List<SystemInfo.StartupItem> StartupItems => _startupItems;

        /// <summary>
        /// Number of startup items
        /// </summary>
        public int Count => _startupItems.Count;

        /// <summary>
        /// Number of enabled startup items
        /// </summary>
        public int EnabledCount => _startupItems.Count(s => s.IsEnabled);

        /// <summary>
        /// Number of disabled startup items
        /// </summary>
        public int DisabledCount => _startupItems.Count(s => !s.IsEnabled);

        /// <summary>
        /// Number of Windows startup items
        /// </summary>
        public int WindowsCount => _startupItems.Count(s => s.IsWindowsItem);

        /// <summary>
        /// Number of user startup items
        /// </summary>
        public int UserCount => _startupItems.Count(s => !s.IsWindowsItem);

        /// <summary>
        /// When the startup items were last refreshed
        /// </summary>
        public DateTime LastRefreshTime => _lastRefreshTime;

        /// <summary>
        /// Time since last refresh
        /// </summary>
        public TimeSpan TimeSinceLastRefresh => DateTime.Now - _lastRefreshTime;

        #endregion

        #region Public Methods

        /// <summary>
        /// Refresh the list of startup items
        /// </summary>
        public void Refresh()
        {
            try
            {
                _logger.Info("StartupManager", "Refreshing startup items");
                
                var systemInfo = _scanner.Scan();
                _startupItems = systemInfo.StartupItems;
                _lastRefreshTime = DateTime.Now;

                // Entries this application disabled in an earlier session are gone from the system, so
                // a fresh scan cannot see them. They are merged back in from their durable records so
                // that they stay visible and can still be re-enabled.
                MergeDisabledItemBackups();

                // Enhance with additional information
                EnhanceStartupItems();
                
                _logger.Info("StartupManager", 
                    $"Found {_startupItems.Count} startup items ({EnabledCount} enabled, {DisabledCount} disabled)");
                
                // Raise event
                StartupItemsRefreshed?.Invoke(this, new StartupEventArgs
                {
                    Timestamp = DateTime.Now,
                    StartupItems = _startupItems
                });
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", "Failed to refresh startup items", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Refresh the list of startup items asynchronously
        /// </summary>
        public async Task RefreshAsync()
        {
            try
            {
                _logger.Info("StartupManager", "Refreshing startup items asynchronously");
                
                var systemInfo = await _scanner.ScanAsync();
                _startupItems = systemInfo.StartupItems;
                _lastRefreshTime = DateTime.Now;

                MergeDisabledItemBackups();

                // Enhance with additional information
                EnhanceStartupItems();
                
                _logger.Info("StartupManager", 
                    $"Found {_startupItems.Count} startup items ({EnabledCount} enabled, {DisabledCount} disabled)");
                
                // Raise event
                StartupItemsRefreshed?.Invoke(this, new StartupEventArgs
                {
                    Timestamp = DateTime.Now,
                    StartupItems = _startupItems
                });
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", "Failed to refresh startup items asynchronously", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Add the entries this application removed in an earlier session back into the list, marked as
        /// disabled.
        ///
        /// Without this the user would disable a start-up entry, restart the optimizer and find the
        /// entry simply gone - no longer listed, therefore no longer re-enableable from the interface,
        /// even though its original value is sitting in the backup directory. An entry that is still
        /// present in the system is left alone; only genuinely absent ones are restored to the list.
        /// </summary>
        private void MergeDisabledItemBackups()
        {
            try
            {
                var records = StartupItemBackupStore.LoadAll();

                if (records.Count == 0)
                    return;

                var merged = 0;

                foreach (var record in records)
                {
                    var alreadyListed = _startupItems.Any(s =>
                        s.Name.Equals(record.Name, StringComparison.OrdinalIgnoreCase));

                    if (alreadyListed)
                        continue;

                    var item = record.ToStartupItem();
                    _startupItems.Add(item);
                    _removedStartupValues[item.Name] = record.OriginalValue;
                    merged++;
                }

                if (merged > 0)
                {
                    _logger.Info("StartupManager",
                        $"{merged} start-up entry(ies) disabled by an earlier session were restored to the list " +
                        "so that they can be re-enabled.");
                }
            }
            catch (Exception ex)
            {
                // Listing the remaining entries matters more than this merge.
                _logger.Warning("StartupManager",
                    "Could not read the saved start-up entry records", null, ex);
            }
        }

        /// <summary>
        /// Get a startup item by name
        /// </summary>
        public SystemInfo.StartupItem GetStartupItem(string name)
        {
            return _startupItems.FirstOrDefault(s => 
                s.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>
        /// Get startup items by category
        /// </summary>
        public List<SystemInfo.StartupItem> GetStartupItemsByCategory(string category)
        {
            return _startupItems
                .Where(s => s.Source.Contains(category, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }

        /// <summary>
        /// Get enabled startup items
        /// </summary>
        public List<SystemInfo.StartupItem> GetEnabledStartupItems()
        {
            return _startupItems.Where(s => s.IsEnabled).ToList();
        }

        /// <summary>
        /// Get disabled startup items
        /// </summary>
        public List<SystemInfo.StartupItem> GetDisabledStartupItems()
        {
            return _startupItems.Where(s => !s.IsEnabled).ToList();
        }

        /// <summary>
        /// Get Windows startup items
        /// </summary>
        public List<SystemInfo.StartupItem> GetWindowsStartupItems()
        {
            return _startupItems.Where(s => s.IsWindowsItem).ToList();
        }

        /// <summary>
        /// Get user startup items
        /// </summary>
        public List<SystemInfo.StartupItem> GetUserStartupItems()
        {
            return _startupItems.Where(s => !s.IsWindowsItem).ToList();
        }

        /// <summary>
        /// Get startup items sorted by impact
        /// </summary>
        public List<SystemInfo.StartupItem> GetStartupItemsByImpact(bool descending = true)
        {
            if (descending)
                return _startupItems.OrderByDescending(s => 
                    s.Impact == "High" ? 3 : s.Impact == "Medium" ? 2 : 1).ToList();
            else
                return _startupItems.OrderBy(s => 
                    s.Impact == "High" ? 3 : s.Impact == "Medium" ? 2 : 1).ToList();
        }

        /// <summary>
        /// Get startup items sorted by estimated RAM usage
        /// </summary>
        public List<SystemInfo.StartupItem> GetStartupItemsByRamUsage(bool descending = true)
        {
            if (descending)
                return _startupItems.OrderByDescending(s => s.EstimatedRamUsage).ToList();
            else
                return _startupItems.OrderBy(s => s.EstimatedRamUsage).ToList();
        }

        /// <summary>
        /// Enable a startup item
        /// </summary>
        public bool EnableStartupItem(string name)
        {
            try
            {
                _logger.Info("StartupManager", $"Enabling startup item: {name}");
                
                var startupItem = GetStartupItem(name);

                if (startupItem == null)
                {
                    // The entry may be one this application removed - it is then absent from the
                    // system, so the scan cannot list it. The durable record holds what is needed to
                    // put it back exactly as it was.
                    if (!StartupItemBackupStore.TryLoad(name, out var backup))
                    {
                        _logger.Warning("StartupManager", $"Startup item not found: {name}");
                        return false;
                    }

                    _logger.Info("StartupManager",
                        $"Re-creating start-up entry '{name}' from its saved value (removed {backup.RemovedAtUtc:O})");

                    startupItem = backup.ToStartupItem();
                    _removedStartupValues[startupItem.Name] = backup.OriginalValue;
                    _startupItems.Add(startupItem);
                }
                
                // Enable based on source
                var success = EnableStartupItemInternal(startupItem);
                
                if (success)
                {
                    startupItem.IsEnabled = true;

                    // The entry exists again, so the record has served its purpose.
                    StartupItemBackupStore.Delete(startupItem.Name);

                    // Raise event
                    StartupItemChanged?.Invoke(this, new StartupItemEventArgs
                    {
                        Timestamp = DateTime.Now,
                        StartupItem = startupItem,
                        Action = StartupItemAction.Enabled
                    });
                    
                    _logger.Info("StartupManager", $"Successfully enabled startup item: {name}");
                }
                else
                {
                    _logger.Warning("StartupManager", $"Failed to enable startup item: {name}");
                }
                
                return success;
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", $"Failed to enable startup item: {name}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Disable a startup item
        /// </summary>
        public bool DisableStartupItem(string name)
        {
            try
            {
                _logger.Info("StartupManager", $"Disabling startup item: {name}");
                
                var startupItem = GetStartupItem(name);
                if (startupItem == null)
                {
                    _logger.Warning("StartupManager", $"Startup item not found: {name}");
                    return false;
                }
                
                // Check if it's blacklisted
                if (startupItem.IsWindowsItem || 
                    _config.BlacklistedStartupItems.Contains(startupItem.Name, StringComparer.OrdinalIgnoreCase))
                {
                    _logger.Warning("StartupManager", 
                        $"Cannot disable blacklisted startup item: {name}");
                    return false;
                }
                
                // Disable based on source. The removed value is kept so Undo can restore it.
                var success = WindowsApiHelper.DisableStartupItem(startupItem, out var removedValue);

                if (success)
                {
                    _removedStartupValues[startupItem.Name] = removedValue;
                }
                
                if (success)
                {
                    startupItem.IsEnabled = false;
                    
                    // Raise event
                    StartupItemChanged?.Invoke(this, new StartupItemEventArgs
                    {
                        Timestamp = DateTime.Now,
                        StartupItem = startupItem,
                        Action = StartupItemAction.Disabled
                    });
                    
                    _logger.Info("StartupManager", $"Successfully disabled startup item: {name}");
                }
                else
                {
                    _logger.Warning("StartupManager", $"Failed to disable startup item: {name}");
                }
                
                return success;
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", $"Failed to disable startup item: {name}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Toggle a startup item
        /// </summary>
        public bool ToggleStartupItem(string name)
        {
            var startupItem = GetStartupItem(name);
            if (startupItem == null)
                return false;
            
            if (startupItem.IsEnabled)
                return DisableStartupItem(name);
            else
                return EnableStartupItem(name);
        }

        /// <summary>
        /// Disable multiple startup items
        /// </summary>
        public int DisableStartupItems(List<string> names)
        {
            var count = 0;
            foreach (var name in names)
            {
                if (DisableStartupItem(name))
                    count++;
            }
            return count;
        }

        /// <summary>
        /// Enable multiple startup items
        /// </summary>
        public int EnableStartupItems(List<string> names)
        {
            var count = 0;
            foreach (var name in names)
            {
                if (EnableStartupItem(name))
                    count++;
            }
            return count;
        }

        /// <summary>
        /// Disable all non-Windows startup items
        /// </summary>
        public int DisableAllNonWindowsStartupItems()
        {
            var nonWindowsItems = GetUserStartupItems()
                .Where(s => s.IsEnabled && !s.IsBlacklisted)
                .Select(s => s.Name)
                .ToList();
            
            return DisableStartupItems(nonWindowsItems);
        }

        /// <summary>
        /// Enable all startup items
        /// </summary>
        public int EnableAllStartupItems()
        {
            var disabledItems = GetDisabledStartupItems()
                .Where(s => !s.IsBlacklisted)
                .Select(s => s.Name)
                .ToList();
            
            return EnableStartupItems(disabledItems);
        }

        /// <summary>
        /// Get startup impact estimation
        /// </summary>
        public StartupImpact GetStartupImpact()
        {
            var impact = new StartupImpact();
            
            try
            {
                // Calculate based on enabled startup items
                impact.EnabledCount = EnabledCount;
                impact.DisabledCount = DisabledCount;
                
                // Estimate RAM usage
                impact.EstimatedRamUsage = _startupItems
                    .Where(s => s.IsEnabled)
                    .Sum(s => s.EstimatedRamUsage);
                
                // Estimate startup time impact
                impact.StartupTimeImpact = impact.EnabledCount switch
                {
                    0 => StartupTimeImpact.Fast,
                    1 or 2 => StartupTimeImpact.Fast,
                    3 or 4 or 5 => StartupTimeImpact.Medium,
                    6 or 7 or 8 => StartupTimeImpact.Slow,
                    _ => StartupTimeImpact.VerySlow
                };
                
                // Estimate boot time in seconds (rough estimate)
                impact.EstimatedBootTimeSeconds = impact.EnabledCount * 2;
                
                // Get high impact items
                impact.HighImpactItems = _startupItems
                    .Where(s => s.IsEnabled && s.Impact == "High")
                    .ToList();
                
                // Get medium impact items
                impact.MediumImpactItems = _startupItems
                    .Where(s => s.IsEnabled && s.Impact == "Medium")
                    .ToList();
                
                // Get low impact items
                impact.LowImpactItems = _startupItems
                    .Where(s => s.IsEnabled && s.Impact == "Low")
                    .ToList();
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", "Failed to get startup impact", null, ex);
            }
            
            return impact;
        }

        /// <summary>
        /// Get optimization recommendations for startup
        /// </summary>
        public List<StartupOptimizationRecommendation> GetOptimizationRecommendations()
        {
            var recommendations = new List<StartupOptimizationRecommendation>();
            
            try
            {
                // Get non-Windows startup items that are enabled
                var nonWindowsItems = GetUserStartupItems()
                    .Where(s => s.IsEnabled)
                    .OrderByDescending(s => s.EstimatedRamUsage)
                    .ToList();
                
                foreach (var item in nonWindowsItems)
                {
                    var recommendation = new StartupOptimizationRecommendation
                    {
                        StartupItem = item,
                        Action = StartupOptimizationAction.Disable,
                        Reason = $"Startup item consumes {item.EstimatedRamUsage / (1024.0 * 1024.0):F2} MB of RAM",
                        EstimatedRamRecovery = item.EstimatedRamUsage,
                        RiskLevel = item.RiskLevel,
                        Priority = item.Impact == "High" ? 10 : item.Impact == "Medium" ? 5 : 1
                    };
                    
                    recommendations.Add(recommendation);
                }
                
                // Sort by priority
                recommendations = recommendations.OrderByDescending(r => r.Priority).ToList();
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", "Failed to get optimization recommendations", null, ex);
            }
            
            return recommendations;
        }

        /// <summary>
        /// Get total estimated RAM usage by startup items
        /// </summary>
        public long GetTotalStartupRamUsage()
        {
            return _startupItems
                .Where(s => s.IsEnabled)
                .Sum(s => s.EstimatedRamUsage);
        }

        /// <summary>
        /// Check if a startup item is blacklisted
        /// </summary>
        public bool IsBlacklisted(string name)
        {
            var startupItem = GetStartupItem(name);
            if (startupItem == null)
                return false;
            
            return startupItem.IsWindowsItem ||
                   _config.BlacklistedStartupItems.Contains(name, StringComparer.OrdinalIgnoreCase);
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Enhance startup items with additional information
        /// </summary>
        private void EnhanceStartupItems()
        {
            try
            {
                foreach (var item in _startupItems)
                {
                    // Set risk level
                    item.RiskLevel = GetStartupItemRiskLevel(item);
                    
                    // Set recommendation
                    item.Recommendation = GetStartupItemRecommendation(item);
                    
                    // Estimate RAM usage if not set
                    if (item.EstimatedRamUsage == 0)
                    {
                        item.EstimatedRamUsage = EstimateRamUsage(item);
                    }
                    
                    // Set impact if not set
                    if (string.IsNullOrEmpty(item.Impact))
                    {
                        item.Impact = GetStartupItemImpact(item);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager", "Failed to enhance startup items", null, ex);
            }
        }

        /// <summary>
        /// Get risk level for a startup item
        /// </summary>
        private RiskLevel GetStartupItemRiskLevel(SystemInfo.StartupItem item)
        {
            if (item.IsWindowsItem)
                return RiskLevel.Critical;
            
            if (item.Path.Contains("\\Windows\\") || item.Path.Contains("\\System32\\"))
                return RiskLevel.High;
            
            if (item.Path.Contains("antivirus") || item.Path.Contains("security") || 
                item.Path.Contains("firewall") || item.Path.Contains("defender"))
                return RiskLevel.High;
            
            return RiskLevel.Low;
        }

        /// <summary>
        /// Get recommendation for a startup item
        /// </summary>
        private string GetStartupItemRecommendation(SystemInfo.StartupItem item)
        {
            if (item.IsWindowsItem)
                return "Windows system item - Do not disable";
            
            if (item.RiskLevel == RiskLevel.High)
                return "High risk - Disable with caution";
            
            if (item.Impact == "High")
                return "High startup impact - Consider disabling";
            
            return "Medium startup impact - Can be disabled if not needed";
        }

        /// <summary>
        /// Estimate RAM usage for a startup item
        /// </summary>
        private long EstimateRamUsage(SystemInfo.StartupItem item)
        {
            // Try to find the process and get its RAM usage
            var systemInfo = _scanner.LastScanResult;
            if (systemInfo != null)
            {
                var process = systemInfo.Processes.FirstOrDefault(p =>
                    p.Path.Equals(item.Path, StringComparison.OrdinalIgnoreCase) ||
                    p.Name.Equals(item.Name, StringComparison.OrdinalIgnoreCase));
                
                if (process != null)
                {
                    return process.WorkingSet;
                }
            }
            
            // Default estimates based on common applications
            var lowerName = item.Name.ToLower();
            
            if (lowerName.Contains("chrome") || lowerName.Contains("edge") || lowerName.Contains("firefox"))
                return 100 * 1024 * 1024; // 100 MB
            
            if (lowerName.Contains("steam") || lowerName.Contains("epic") || lowerName.Contains("origin"))
                return 150 * 1024 * 1024; // 150 MB
            
            if (lowerName.Contains("discord") || lowerName.Contains("slack") || lowerName.Contains("teams"))
                return 80 * 1024 * 1024; // 80 MB
            
            if (lowerName.Contains("spotify") || lowerName.Contains("music"))
                return 60 * 1024 * 1024; // 60 MB
            
            if (lowerName.Contains("onedrive") || lowerName.Contains("dropbox") || lowerName.Contains("google"))
                return 50 * 1024 * 1024; // 50 MB
            
            return 30 * 1024 * 1024; // Default 30 MB
        }

        /// <summary>
        /// Get impact level for a startup item
        /// </summary>
        private string GetStartupItemImpact(SystemInfo.StartupItem item)
        {
            // Try to find the process and get its RAM usage
            var systemInfo = _scanner.LastScanResult;
            if (systemInfo != null)
            {
                var process = systemInfo.Processes.FirstOrDefault(p =>
                    p.Path.Equals(item.Path, StringComparison.OrdinalIgnoreCase) ||
                    p.Name.Equals(item.Name, StringComparison.OrdinalIgnoreCase));
                
                if (process != null)
                {
                    var ramUsageMB = process.WorkingSet / (1024.0 * 1024.0);
                    
                    if (ramUsageMB > 100)
                        return "High";
                    else if (ramUsageMB > 50)
                        return "Medium";
                    else
                        return "Low";
                }
            }
            
            // Default to medium
            return "Medium";
        }

        /// <summary>
        /// Re-create a previously disabled start-up entry.
        /// Uses the exact command line that was captured when it was removed.
        /// </summary>
        private bool EnableStartupItemInternal(SystemInfo.StartupItem startupItem)
        {
            try
            {
                _removedStartupValues.TryGetValue(startupItem.Name, out var originalValue);

                if (string.IsNullOrEmpty(originalValue))
                    originalValue = startupItem.Path;

                var restored = WindowsApiHelper.RestoreStartupItem(startupItem, originalValue);

                if (restored)
                    _removedStartupValues.Remove(startupItem.Name);

                return restored;
            }
            catch (Exception ex)
            {
                _logger.Error("StartupManager",
                    $"Failed to re-create start-up entry: {startupItem.Name}", null, ex);
                return false;
            }
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the manager
        /// </summary>
        public void Dispose()
        {
            try
            {
                _scanner?.Dispose();
            }
            catch { }
            
            _disposed = true;
        }

        #endregion
    }

    /// <summary>
    /// Startup time impact enumeration
    /// </summary>
    public enum StartupTimeImpact
    {
        Fast,
        Medium,
        Slow,
        VerySlow
    }

    /// <summary>
    /// Startup impact information
    /// </summary>
    public class StartupImpact
    {
        /// <summary>
        /// Number of enabled startup items
        /// </summary>
        public int EnabledCount { get; set; }
        
        /// <summary>
        /// Number of disabled startup items
        /// </summary>
        public int DisabledCount { get; set; }
        
        /// <summary>
        /// Estimated total RAM usage by startup items
        /// </summary>
        public long EstimatedRamUsage { get; set; }
        
        /// <summary>
        /// Formatted estimated RAM usage
        /// </summary>
        public string FormattedEstimatedRamUsage => FormatBytes(EstimatedRamUsage);
        
        /// <summary>
        /// Overall startup time impact
        /// </summary>
        public StartupTimeImpact StartupTimeImpact { get; set; }
        
        /// <summary>
        /// Estimated boot time in seconds
        /// </summary>
        public int EstimatedBootTimeSeconds { get; set; }
        
        /// <summary>
        /// List of high impact startup items
        /// </summary>
        public List<SystemInfo.StartupItem> HighImpactItems { get; set; } = new List<SystemInfo.StartupItem>();
        
        /// <summary>
        /// List of medium impact startup items
        /// </summary>
        public List<SystemInfo.StartupItem> MediumImpactItems { get; set; } = new List<SystemInfo.StartupItem>();
        
        /// <summary>
        /// List of low impact startup items
        /// </summary>
        public List<SystemInfo.StartupItem> LowImpactItems { get; set; } = new List<SystemInfo.StartupItem>();
        
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

    /// <summary>
    /// Startup optimization action
    /// </summary>
    public enum StartupOptimizationAction
    {
        Disable,
        Enable,
        Delay
    }

    /// <summary>
    /// Startup optimization recommendation
    /// </summary>
    public class StartupOptimizationRecommendation
    {
        /// <summary>
        /// The startup item
        /// </summary>
        public SystemInfo.StartupItem StartupItem { get; set; }
        
        /// <summary>
        /// The recommended action
        /// </summary>
        public StartupOptimizationAction Action { get; set; }
        
        /// <summary>
        /// Reason for the recommendation
        /// </summary>
        public string Reason { get; set; } = string.Empty;
        
        /// <summary>
        /// Estimated RAM recovery
        /// </summary>
        public long EstimatedRamRecovery { get; set; }
        
        /// <summary>
        /// Formatted estimated RAM recovery
        /// </summary>
        public string FormattedEstimatedRamRecovery => FormatBytes(EstimatedRamRecovery);
        
        /// <summary>
        /// Risk level
        /// </summary>
        public RiskLevel RiskLevel { get; set; } = RiskLevel.Low;
        
        /// <summary>
        /// Priority (1-10)
        /// </summary>
        public int Priority { get; set; } = 1;
        
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

    /// <summary>
    /// Startup item action
    /// </summary>
    public enum StartupItemAction
    {
        Enabled,
        Disabled
    }

    /// <summary>
    /// Startup event arguments
    /// </summary>
    public class StartupEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public List<SystemInfo.StartupItem> StartupItems { get; set; } = new List<SystemInfo.StartupItem>();
    }

    /// <summary>
    /// Startup item event arguments
    /// </summary>
    public class StartupItemEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public SystemInfo.StartupItem StartupItem { get; set; }
        public StartupItemAction Action { get; set; }
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using System.ServiceProcess;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for managing Windows services
    /// </summary>
    public class ServiceManager : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private List<SystemInfo.ServiceInfo> _services;
        private DateTime _lastRefreshTime;
        private bool _disposed = false;
        /// <summary>
        /// Dependents that caused the most recent dependency-based refusal.
        /// </summary>
        private IReadOnlyList<string> _lastDependencyRefusal = Array.Empty<string>();


        #endregion

        #region Events

        /// <summary>
        /// Event raised when services are refreshed
        /// </summary>
        public event EventHandler<ServiceEventArgs> ServicesRefreshed;

        /// <summary>
        /// Event raised when a service status changes
        /// </summary>
        public event EventHandler<ServiceStatusEventArgs> ServiceStatusChanged;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new service manager
        /// </summary>
        public ServiceManager(ILogger logger = null, AppConfig config = null, SystemScanner scanner = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _services = new List<SystemInfo.ServiceInfo>();
            _lastRefreshTime = DateTime.MinValue;
        }

        #endregion

        #region Properties

        /// <summary>
        /// List of services
        /// </summary>
        public List<SystemInfo.ServiceInfo> Services => _services;

        /// <summary>
        /// Number of services
        /// </summary>
        public int Count => _services.Count;

        /// <summary>
        /// Number of running services
        /// </summary>
        public int RunningCount => _services.Count(s => s.Status == "Running");

        /// <summary>
        /// Number of stopped services
        /// </summary>
        public int StoppedCount => _services.Count(s => s.Status == "Stopped");

        /// <summary>
        /// Number of Windows services
        /// </summary>
        public int WindowsCount => _services.Count(s => s.IsWindowsService);

        /// <summary>
        /// Number of third-party services
        /// </summary>
        public int ThirdPartyCount => _services.Count(s => !s.IsWindowsService);

        /// <summary>
        /// Number of critical services
        /// </summary>
        public int CriticalCount => _services.Count(s => s.IsCritical);

        /// <summary>
        /// When the services were last refreshed
        /// </summary>
        public DateTime LastRefreshTime => _lastRefreshTime;

        /// <summary>
        /// Time since last refresh
        /// </summary>
        public TimeSpan TimeSinceLastRefresh => DateTime.Now - _lastRefreshTime;

        #endregion

        #region Public Methods

        /// <summary>
        /// Refresh the list of services
        /// </summary>
        public void Refresh()
        {
            try
            {
                _logger.Info("ServiceManager", "Refreshing services");
                
                var systemInfo = _scanner.Scan();
                _services = systemInfo.Services;
                _lastRefreshTime = DateTime.Now;
                
                // Enhance with additional information
                EnhanceServices();
                
                _logger.Info("ServiceManager", 
                    $"Found {_services.Count} services ({RunningCount} running, {StoppedCount} stopped)");
                
                // Raise event
                ServicesRefreshed?.Invoke(this, new ServiceEventArgs
                {
                    Timestamp = DateTime.Now,
                    Services = _services
                });
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", "Failed to refresh services", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Refresh the list of services asynchronously
        /// </summary>
        public async Task RefreshAsync()
        {
            try
            {
                _logger.Info("ServiceManager", "Refreshing services asynchronously");
                
                var systemInfo = await _scanner.ScanAsync();
                _services = systemInfo.Services;
                _lastRefreshTime = DateTime.Now;
                
                // Enhance with additional information
                EnhanceServices();
                
                _logger.Info("ServiceManager", 
                    $"Found {_services.Count} services ({RunningCount} running, {StoppedCount} stopped)");
                
                // Raise event
                ServicesRefreshed?.Invoke(this, new ServiceEventArgs
                {
                    Timestamp = DateTime.Now,
                    Services = _services
                });
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", "Failed to refresh services asynchronously", null, ex);
                throw;
            }
        }

        /// <summary>
        /// Get a service by name
        /// </summary>
        public SystemInfo.ServiceInfo GetService(string name)
        {
            return _services.FirstOrDefault(s => 
                s.Name.Equals(name, StringComparison.OrdinalIgnoreCase) ||
                s.DisplayName.Equals(name, StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>
        /// Get services by status
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetServicesByStatus(string status)
        {
            return _services.Where(s => s.Status.Equals(status, StringComparison.OrdinalIgnoreCase)).ToList();
        }

        /// <summary>
        /// Get running services
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetRunningServices()
        {
            return _services.Where(s => s.Status == "Running").ToList();
        }

        /// <summary>
        /// Get stopped services
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetStoppedServices()
        {
            return _services.Where(s => s.Status == "Stopped").ToList();
        }

        /// <summary>
        /// Get Windows services
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetWindowsServices()
        {
            return _services.Where(s => s.IsWindowsService).ToList();
        }

        /// <summary>
        /// Get third-party services
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetThirdPartyServices()
        {
            return _services.Where(s => !s.IsWindowsService).ToList();
        }

        /// <summary>
        /// Get critical services
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetCriticalServices()
        {
            return _services.Where(s => s.IsCritical).ToList();
        }

        /// <summary>
        /// Get services that can be stopped
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetStoppableServices()
        {
            return _services
                .Where(s => s.Status == "Running")
                .Where(s => !s.IsCritical)
                .Where(s => !s.IsWindowsService || !_config.BlacklistedServices.Contains(s.Name, StringComparer.OrdinalIgnoreCase))
                .ToList();
        }

        /// <summary>
        /// Get services that can be disabled
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetDisableableServices()
        {
            return _services
                .Where(s => !s.IsCritical)
                .Where(s => !s.IsWindowsService || !_config.BlacklistedServices.Contains(s.Name, StringComparer.OrdinalIgnoreCase))
                .ToList();
        }

        /// <summary>
        /// Get services sorted by name
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetServicesSortedByName(bool descending = false)
        {
            if (descending)
                return _services.OrderByDescending(s => s.DisplayName).ToList();
            else
                return _services.OrderBy(s => s.DisplayName).ToList();
        }

        /// <summary>
        /// Get services sorted by status
        /// </summary>
        public List<SystemInfo.ServiceInfo> GetServicesSortedByStatus(bool descending = false)
        {
            if (descending)
                return _services.OrderByDescending(s => s.Status).ToList();
            else
                return _services.OrderBy(s => s.Status).ToList();
        }

        /// <summary>
        /// Start a service
        /// </summary>
        public bool StartService(string serviceName)
        {
            try
            {
                _logger.Info("ServiceManager", $"Starting service: {serviceName}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Check if already running
                if (serviceInfo.Status == "Running")
                {
                    _logger.Info("ServiceManager", $"Service already running: {serviceName}");
                    return true;
                }
                
                // Start the service
                if (WindowsApiHelper.StartService(serviceName))
                {
                    serviceInfo.Status = "Running";
                    
                    // Raise event
                    ServiceStatusChanged?.Invoke(this, new ServiceStatusEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Service = serviceInfo,
                        OldStatus = "Stopped",
                        NewStatus = "Running"
                    });
                    
                    _logger.Info("ServiceManager", $"Successfully started service: {serviceName}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", $"Failed to start service: {serviceName}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", $"Failed to start service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Names of the services that depend on the given service.
        ///
        /// A service that other services depend on must never be stopped or disabled. Windows will
        /// either refuse the request or, worse, stop it and leave the dependents in a failed state.
        /// The dependency graph is therefore consulted before every service modification.
        ///
        /// When the graph cannot be read the result is null, which callers must interpret as
        /// "assume there are dependents" (fail closed).
        /// </summary>
        public IReadOnlyList<string>? GetDependentServices(string serviceName)
        {
            return WindowsApiHelper.GetDependentServiceNames(serviceName);
        }

        /// <summary>
        /// Dependents of a service that are currently running.
        /// Returns null when the dependency graph could not be read (caller must fail closed).
        /// </summary>
        private IReadOnlyList<string>? GetRunningDependents(string serviceName)
        {
            var dependents = GetDependentServices(serviceName);

            if (dependents == null)
                return null;

            if (dependents.Count == 0)
                return Array.Empty<string>();

            var running = new List<string>();

            foreach (var dependent in dependents)
            {
                try
                {
                    if (WindowsApiHelper.IsServiceRunning(dependent))
                        running.Add(dependent);
                }
                catch
                {
                    // An unreadable dependent is treated as running.
                    running.Add(dependent);
                }
            }

            return running;
        }

        /// <summary>
        /// Dependents that caused the most recent refusal, so the UI can explain itself.
        /// Empty when the last operation was not refused because of a dependency.
        /// </summary>
        public IReadOnlyList<string> LastDependencyRefusal => _lastDependencyRefusal;

        /// <summary>
        /// Stop a service
        /// </summary>
        public bool StopService(string serviceName)
        {
            try
            {
                _logger.Info("ServiceManager", $"Stopping service: {serviceName}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Check if already stopped
                if (serviceInfo.Status == "Stopped")
                {
                    _logger.Info("ServiceManager", $"Service already stopped: {serviceName}");
                    return true;
                }
                
                // Check if it's a critical service
                if (serviceInfo.IsCritical)
                {
                    _logger.Warning("ServiceManager", 
                        $"Cannot stop critical service: {serviceName}");
                    return false;
                }
                
                // Check if it's blacklisted
                if (_config.BlacklistedServices.Contains(serviceName, StringComparer.OrdinalIgnoreCase))
                {
                    _logger.Warning("ServiceManager", 
                        $"Cannot stop blacklisted service: {serviceName}");
                    return false;
                }
                
                // A running dependent means stopping this service would break it. Refuse and say so.
                var runningDependents = GetRunningDependents(serviceName);
                if (runningDependents == null)
                {
                    _logger.Warning("ServiceManager",
                        $"Cannot stop '{serviceName}': the dependency graph could not be read, " +
                        "so it cannot be proven that nothing depends on it.");
                    _lastDependencyRefusal = Array.Empty<string>();
                    return false;
                }

                if (runningDependents.Count > 0)
                {
                    _logger.Warning("ServiceManager",
                        $"Cannot stop '{serviceName}': these running services depend on it " +
                        $"({string.Join(", ", runningDependents)}).");

                    _lastDependencyRefusal = runningDependents;
                    return false;
                }

                // Stop the service
                if (WindowsApiHelper.StopService(serviceName))
                {
                    serviceInfo.Status = "Stopped";
                    
                    // Raise event
                    ServiceStatusChanged?.Invoke(this, new ServiceStatusEventArgs
                    {
                        Timestamp = DateTime.Now,
                        Service = serviceInfo,
                        OldStatus = "Running",
                        NewStatus = "Stopped"
                    });
                    
                    _logger.Info("ServiceManager", $"Successfully stopped service: {serviceName}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", $"Failed to stop service: {serviceName}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", $"Failed to stop service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Restart a service
        /// </summary>
        public bool RestartService(string serviceName)
        {
            try
            {
                _logger.Info("ServiceManager", $"Restarting service: {serviceName}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Stop the service first
                if (!StopService(serviceName))
                {
                    _logger.Warning("ServiceManager", 
                        $"Failed to stop service before restart: {serviceName}");
                    return false;
                }
                
                // Wait a bit before starting
                System.Threading.Thread.Sleep(1000);
                
                // Start the service
                if (StartService(serviceName))
                {
                    _logger.Info("ServiceManager", $"Successfully restarted service: {serviceName}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", $"Failed to start service after restart: {serviceName}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", $"Failed to restart service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Enable a service (set to automatic start)
        /// </summary>
        public bool EnableService(string serviceName)
        {
            try
            {
                _logger.Info("ServiceManager", $"Enabling service: {serviceName}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Check if already enabled
                if (serviceInfo.StartType == "Automatic")
                {
                    _logger.Info("ServiceManager", $"Service already enabled: {serviceName}");
                    return true;
                }
                
                // Enable the service
                if (WindowsApiHelper.EnableService(serviceName, true))
                {
                    serviceInfo.StartType = "Automatic";
                    
                    _logger.Info("ServiceManager", $"Successfully enabled service: {serviceName}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", $"Failed to enable service: {serviceName}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", $"Failed to enable service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Disable a service (set to disabled start)
        /// </summary>
        public bool DisableService(string serviceName)
        {
            try
            {
                _logger.Info("ServiceManager", $"Disabling service: {serviceName}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Check if it's a critical service
                if (serviceInfo.IsCritical)
                {
                    _logger.Warning("ServiceManager", 
                        $"Cannot disable critical service: {serviceName}");
                    return false;
                }
                
                // Check if it's blacklisted
                if (_config.BlacklistedServices.Contains(serviceName, StringComparer.OrdinalIgnoreCase))
                {
                    _logger.Warning("ServiceManager", 
                        $"Cannot disable blacklisted service: {serviceName}");
                    return false;
                }

                // Check for dependents. A service that something else depends on must not be stopped
                // or disabled: Windows would either refuse, or the dependent service would fail and
                // take a piece of the system down with it. This guard is what makes "disable a random
                // service" impossible rather than merely discouraged.
                var dependents = GetDependentServices(serviceName);

                if (dependents == null)
                {
                    _logger.Warning("ServiceManager",
                        $"Cannot disable '{serviceName}': the dependency graph could not be read, " +
                        "so it cannot be proven that nothing depends on it.");
                    _lastDependencyRefusal = Array.Empty<string>();
                    return false;
                }

                if (dependents.Count > 0)
                {
                    _logger.Warning("ServiceManager",
                        $"Cannot disable '{serviceName}': " +
                        $"{dependents.Count} service(s) depend on it ({string.Join(", ", dependents)}). " +
                        "Disabling it would break them.");

                    _lastDependencyRefusal = dependents;
                    return false;
                }

                // First, stop the service if it's running
                if (serviceInfo.Status == "Running")
                {
                    if (!StopService(serviceName))
                    {
                        _logger.Warning("ServiceManager", 
                            $"Failed to stop service before disabling: {serviceName}");
                        return false;
                    }
                }
                
                // Disable the service
                if (WindowsApiHelper.DisableService(serviceName))
                {
                    serviceInfo.StartType = "Disabled";
                    
                    _logger.Info("ServiceManager", $"Successfully disabled service: {serviceName}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", $"Failed to disable service: {serviceName}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", $"Failed to disable service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Set service startup type
        /// </summary>
        public bool SetServiceStartupType(string serviceName, ServiceStartMode startType)
        {
            try
            {
                _logger.Info("ServiceManager", 
                    $"Setting startup type for service: {serviceName} to {startType}");
                
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    _logger.Warning("ServiceManager", $"Service not found: {serviceName}");
                    return false;
                }
                
                // Set the startup type
                if (WindowsApiHelper.SetServiceStartType(serviceName, startType))
                {
                    serviceInfo.StartType = startType.ToString();
                    
                    _logger.Info("ServiceManager", 
                        $"Successfully set startup type for service: {serviceName} to {startType}");
                    return true;
                }
                
                _logger.Warning("ServiceManager", 
                    $"Failed to set startup type for service: {serviceName} to {startType}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", 
                    $"Failed to set startup type for service: {serviceName}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Get service status
        /// </summary>
        public ServiceStatusInfo GetServiceStatus(string serviceName)
        {
            try
            {
                var serviceInfo = GetService(serviceName);
                if (serviceInfo == null)
                {
                    return new ServiceStatusInfo
                    {
                        ServiceName = serviceName,
                        Exists = false
                    };
                }
                
                return new ServiceStatusInfo
                {
                    ServiceName = serviceInfo.Name,
                    DisplayName = serviceInfo.DisplayName,
                    Exists = true,
                    Status = serviceInfo.Status,
                    StartType = serviceInfo.StartType,
                    IsRunning = serviceInfo.Status == "Running",
                    IsEnabled = serviceInfo.StartType != "Disabled",
                    CanStop = serviceInfo.Status == "Running" && !serviceInfo.IsCritical,
                    CanStart = serviceInfo.Status == "Stopped",
                    CanDisable = !serviceInfo.IsCritical && !serviceInfo.IsWindowsService,
                    CanEnable = serviceInfo.StartType == "Disabled"
                };
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", 
                    $"Failed to get service status: {serviceName}", null, ex);
                
                return new ServiceStatusInfo
                {
                    ServiceName = serviceName,
                    Exists = false,
                    Error = ex.Message
                };
            }
        }

        /// <summary>
        /// Get optimization recommendations for services
        /// </summary>
        public List<ServiceOptimizationRecommendation> GetOptimizationRecommendations()
        {
            var recommendations = new List<ServiceOptimizationRecommendation>();
            
            try
            {
                // Get services that can be stopped
                var stoppableServices = GetStoppableServices()
                    .Where(s => s.Status == "Running")
                    .OrderByDescending(s => GetServiceImpact(s))
                    .ToList();
                
                foreach (var service in stoppableServices)
                {
                    var recommendation = new ServiceOptimizationRecommendation
                    {
                        Service = service,
                        Action = ServiceOptimizationAction.Stop,
                        Reason = $"Service is running but not critical",
                        EstimatedCpuImprovement = 5f, // Rough estimate
                        RiskLevel = service.RiskLevel,
                        Priority = GetServicePriority(service)
                    };
                    
                    recommendations.Add(recommendation);
                }
                
                // Get services that can be disabled
                var disableableServices = GetDisableableServices()
                    .Where(s => s.StartType != "Disabled")
                    .OrderByDescending(s => GetServiceImpact(s))
                    .ToList();
                
                foreach (var service in disableableServices)
                {
                    var recommendation = new ServiceOptimizationRecommendation
                    {
                        Service = service,
                        Action = ServiceOptimizationAction.Disable,
                        Reason = $"Service is not critical and can be disabled to improve startup time",
                        EstimatedRamRecovery = 10 * 1024 * 1024, // Rough estimate of 10 MB
                        RiskLevel = service.RiskLevel,
                        Priority = GetServicePriority(service) - 2 // Lower priority for disable vs stop
                    };
                    
                    recommendations.Add(recommendation);
                }
                
                // Sort by priority
                recommendations = recommendations.OrderByDescending(r => r.Priority).ToList();
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", "Failed to get optimization recommendations", null, ex);
            }
            
            return recommendations;
        }

        /// <summary>
        /// Check if a service is blacklisted
        /// </summary>
        public bool IsBlacklisted(string serviceName)
        {
            var serviceInfo = GetService(serviceName);
            if (serviceInfo == null)
                return false;
            
            return serviceInfo.IsCritical ||
                   serviceInfo.IsWindowsService && _config.BlacklistedServices.Contains(serviceName, StringComparer.OrdinalIgnoreCase);
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Enhance services with additional information
        /// </summary>
        private void EnhanceServices()
        {
            try
            {
                foreach (var service in _services)
                {
                    // Set risk level
                    service.RiskLevel = GetServiceRiskLevel(service);
                    
                    // Set whether it's a Windows service
                    service.IsWindowsService = CriticalProcesses.IsWindowsSystemProcess(service.Name);
                    
                    // Set whether it's critical
                    service.IsCritical = CriticalProcesses.IsCritical(service.Name);
                    
                    // Get memory usage if the service is running
                    if (service.Status == "Running" && service.ProcessId > 0)
                    {
                        var process = WindowsApiHelper.GetProcessById(service.ProcessId);
                        if (process != null)
                        {
                            service.MemoryUsage = process.WorkingSet64;
                            service.CpuUsage = WindowsApiHelper.GetProcessCpuUsage(service.ProcessId);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.Error("ServiceManager", "Failed to enhance services", null, ex);
            }
        }

        /// <summary>
        /// Get risk level for a service
        /// </summary>
        private RiskLevel GetServiceRiskLevel(SystemInfo.ServiceInfo service)
        {
            if (service.IsCritical)
                return RiskLevel.Critical;
            
            if (service.IsWindowsService)
                return RiskLevel.High;
            
            if (_config.BlacklistedServices.Contains(service.Name, StringComparer.OrdinalIgnoreCase))
                return RiskLevel.High;
            
            return RiskLevel.Medium;
        }

        /// <summary>
        /// Get impact score for a service (0-100)
        /// </summary>
        private int GetServiceImpact(SystemInfo.ServiceInfo service)
        {
            var score = 0;
            
            // Higher score for services with higher memory usage
            if (service.MemoryUsage > 0)
            {
                var mb = service.MemoryUsage / (1024.0 * 1024.0);
                score += (int)(mb / 10) * 10; // 10 MB = 10 points
            }
            
            // Higher score for services with higher CPU usage
            score += (int)(service.CpuUsage / 2); // 2% CPU = 1 point
            
            // Higher score for non-Windows services
            if (!service.IsWindowsService)
                score += 20;
            
            // Lower score for critical services
            if (service.IsCritical)
                score -= 50;
            
            // Ensure score is between 0 and 100
            return Math.Max(0, Math.Min(100, score));
        }

        /// <summary>
        /// Get priority for a service recommendation (0-10)
        /// </summary>
        private int GetServicePriority(SystemInfo.ServiceInfo service)
        {
            var impact = GetServiceImpact(service);
            
            // Convert impact score (0-100) to priority (0-10)
            return Math.Max(1, Math.Min(10, impact / 10));
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
    /// Service status information
    /// </summary>
    public class ServiceStatusInfo
    {
        /// <summary>
        /// Service name
        /// </summary>
        public string ServiceName { get; set; } = string.Empty;
        
        /// <summary>
        /// Service display name
        /// </summary>
        public string DisplayName { get; set; } = string.Empty;
        
        /// <summary>
        /// Whether the service exists
        /// </summary>
        public bool Exists { get; set; } = false;
        
        /// <summary>
        /// Service status
        /// </summary>
        public string Status { get; set; } = string.Empty;
        
        /// <summary>
        /// Service start type
        /// </summary>
        public string StartType { get; set; } = string.Empty;
        
        /// <summary>
        /// Whether the service is running
        /// </summary>
        public bool IsRunning { get; set; }
        
        /// <summary>
        /// Whether the service is enabled
        /// </summary>
        public bool IsEnabled { get; set; }
        
        /// <summary>
        /// Whether the service can be stopped
        /// </summary>
        public bool CanStop { get; set; }
        
        /// <summary>
        /// Whether the service can be started
        /// </summary>
        public bool CanStart { get; set; }
        
        /// <summary>
        /// Whether the service can be disabled
        /// </summary>
        public bool CanDisable { get; set; }
        
        /// <summary>
        /// Whether the service can be enabled
        /// </summary>
        public bool CanEnable { get; set; }
        
        /// <summary>
        /// Error message if any
        /// </summary>
        public string Error { get; set; } = string.Empty;
    }

    /// <summary>
    /// Service optimization action
    /// </summary>
    public enum ServiceOptimizationAction
    {
        Stop,
        Start,
        Disable,
        Enable,
        Restart
    }

    /// <summary>
    /// Service optimization recommendation
    /// </summary>
    public class ServiceOptimizationRecommendation
    {
        /// <summary>
        /// The service
        /// </summary>
        public SystemInfo.ServiceInfo Service { get; set; }
        
        /// <summary>
        /// The recommended action
        /// </summary>
        public ServiceOptimizationAction Action { get; set; }
        
        /// <summary>
        /// Reason for the recommendation
        /// </summary>
        public string Reason { get; set; } = string.Empty;
        
        /// <summary>
        /// Estimated CPU improvement percentage
        /// </summary>
        public float EstimatedCpuImprovement { get; set; }
        
        /// <summary>
        /// Estimated RAM recovery in bytes
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
    /// Service event arguments
    /// </summary>
    public class ServiceEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public List<SystemInfo.ServiceInfo> Services { get; set; } = new List<SystemInfo.ServiceInfo>();
    }

    /// <summary>
    /// Service status event arguments
    /// </summary>
    public class ServiceStatusEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public SystemInfo.ServiceInfo Service { get; set; }
        public string OldStatus { get; set; } = string.Empty;
        public string NewStatus { get; set; } = string.Empty;
    }
}

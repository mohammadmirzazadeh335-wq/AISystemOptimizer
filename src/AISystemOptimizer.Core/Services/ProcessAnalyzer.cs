using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for analyzing processes and identifying optimization opportunities
    /// </summary>
    public class ProcessAnalyzer : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SystemScanner _scanner;
        private readonly AIService _aiService;

        #endregion

        #region Events

        /// <summary>
        /// Event raised when a process analysis starts
        /// </summary>
        public event EventHandler<ProcessAnalysisEventArgs> AnalysisStarted;

        /// <summary>
        /// Event raised when a process analysis completes
        /// </summary>
        public event EventHandler<ProcessAnalysisEventArgs> AnalysisCompleted;

        /// <summary>
        /// Event raised when a process analysis fails
        /// </summary>
        public event EventHandler<ProcessAnalysisEventArgs> AnalysisFailed;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new process analyzer
        /// </summary>
        public ProcessAnalyzer(
            ILogger logger = null,
            AppConfig config = null,
            SystemScanner scanner = null,
            AIService aiService = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _scanner = scanner ?? new SystemScanner(logger, config);
            _aiService = aiService ?? new AIService(logger, config);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Analyze all processes and identify optimization opportunities
        /// </summary>
        public List<ProcessAnalysisResult> AnalyzeAllProcesses(SystemInfo systemInfo = null)
        {
            var results = new List<ProcessAnalysisResult>();
            
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? _scanner.Scan();
                
                _logger.Info("ProcessAnalyzer", "Starting process analysis");
                
                // Raise analysis started event
                AnalysisStarted?.Invoke(this, new ProcessAnalysisEventArgs
                {
                    Timestamp = DateTime.Now,
                    ProcessCount = systemInfo.Processes.Count
                });
                
                var stopwatch = System.Diagnostics.Stopwatch.StartNew();
                
                // Analyze each process
                foreach (var process in systemInfo.Processes)
                {
                    try
                    {
                        var result = AnalyzeProcess(process, systemInfo);
                        results.Add(result);
                    }
                    catch (Exception ex)
                    {
                        _logger.Error("ProcessAnalyzer", $"Failed to analyze process {process.Name}", null, ex);
                    }
                }
                
                // Sort results by optimization potential
                results = results.OrderByDescending(r => r.OptimizationScore).ToList();
                
                _logger.Info("ProcessAnalyzer", 
                    $"Process analysis completed in {stopwatch.ElapsedMilliseconds}ms. Found {results.Count(r => r.CanOptimize)} optimizable processes.");
                
                // Raise analysis completed event
                AnalysisCompleted?.Invoke(this, new ProcessAnalysisEventArgs
                {
                    Timestamp = DateTime.Now,
                    Duration = stopwatch.Elapsed,
                    ProcessCount = systemInfo.Processes.Count,
                    OptimizableCount = results.Count(r => r.CanOptimize),
                    Results = results
                });
            }
            catch (Exception ex)
            {
                _logger.Error("ProcessAnalyzer", "Process analysis failed", null, ex);
                
                // Raise analysis failed event
                AnalysisFailed?.Invoke(this, new ProcessAnalysisEventArgs
                {
                    Timestamp = DateTime.Now,
                    ErrorMessage = ex.Message,
                    Exception = ex
                });
                
                throw;
            }
            
            return results;
        }

        /// <summary>
        /// Analyze a specific process
        /// </summary>
        public ProcessAnalysisResult AnalyzeProcess(ProcessInfo process, SystemInfo systemInfo = null)
        {
            var result = new ProcessAnalysisResult { ProcessInfo = process };
            
            try
            {
                // Use provided system info or scan for it
                systemInfo = systemInfo ?? _scanner.Scan();
                
                // Basic analysis
                result.Category = process.Category;
                result.RiskLevel = process.RiskLevel;
                result.IsCritical = CriticalProcesses.IsCritical(process.Name);
                result.IsWindowsProcess = process.IsWindowsProcess;
                result.IsDriver = process.IsDriver;
                result.IsService = process.IsService;
                result.IsActive = process.IsActive;
                result.HasVisibleWindow = process.HasVisibleWindow;
                result.IsUserWhitelisted = IsUserWhitelisted(process);
                result.IsBlacklisted = IsBlacklisted(process);
                
                // Determine if the process can be optimized
                result.CanOptimize = CanOptimizeProcess(process, systemInfo);
                
                // Calculate optimization score
                result.OptimizationScore = CalculateOptimizationScore(process, systemInfo);
                
                // Get recommendations
                result.Recommendation = GetProcessRecommendation(process, systemInfo);
                result.RecommendationDetails = GetRecommendationDetails(process, systemInfo);
                
                // Get AI analysis if enabled
                if (_config.AiEnabled)
                {
                    try
                    {
                        result.AiAnalysis = _aiService.AnalyzeProcess(process);
                        result.AiAnalyzed = true;
                    }
                    catch (Exception ex)
                    {
                        _logger.Warning("ProcessAnalyzer", 
                            $"AI analysis failed for process {process.Name}", null, ex);
                        result.AiAnalyzed = false;
                    }
                }
                
                // Calculate estimated resource recovery
                result.EstimatedRamRecovery = CalculateEstimatedRamRecovery(process, systemInfo);
                result.EstimatedCpuImprovement = CalculateEstimatedCpuImprovement(process, systemInfo);
            }
            catch (Exception ex)
            {
                _logger.Error("ProcessAnalyzer", 
                    $"Failed to analyze process {process.Name}", null, ex);
                result.Error = ex.Message;
            }
            
            return result;
        }

        /// <summary>
        /// Analyze processes by category
        /// </summary>
        public List<ProcessAnalysisResult> AnalyzeByCategory(
            ProcessCategory category,
            SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults.Where(r => r.Category == category).ToList();
        }

        /// <summary>
        /// Analyze processes by risk level
        /// </summary>
        public List<ProcessAnalysisResult> AnalyzeByRiskLevel(
            RiskLevel riskLevel,
            SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults.Where(r => r.RiskLevel == riskLevel).ToList();
        }

        /// <summary>
        /// Get processes that can be safely optimized
        /// </summary>
        public List<ProcessAnalysisResult> GetOptimizableProcesses(SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults.Where(r => r.CanOptimize).ToList();
        }

        /// <summary>
        /// Get processes that are safe to close
        /// </summary>
        public List<ProcessAnalysisResult> GetSafeToCloseProcesses(SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults
                .Where(r => r.CanOptimize)
                .Where(r => r.RiskLevel == RiskLevel.Low)
                .Where(r => !r.IsActive)
                .Where(r => !r.HasVisibleWindow)
                .ToList();
        }

        /// <summary>
        /// Get background processes that can be optimized
        /// </summary>
        public List<ProcessAnalysisResult> GetBackgroundProcesses(SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults
                .Where(r => r.Category == ProcessCategory.BackgroundApplication)
                .Where(r => r.CanOptimize)
                .ToList();
        }

        /// <summary>
        /// Get processes that are using the most RAM
        /// </summary>
        public List<ProcessAnalysisResult> GetHighRamUsageProcesses(
            int count = 10,
            SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults
                .Where(r => !r.IsCritical)
                .OrderByDescending(r => r.ProcessInfo.WorkingSet)
                .Take(count)
                .ToList();
        }

        /// <summary>
        /// Get processes that are using the most CPU
        /// </summary>
        public List<ProcessAnalysisResult> GetHighCpuUsageProcesses(
            int count = 10,
            SystemInfo systemInfo = null)
        {
            var allResults = AnalyzeAllProcesses(systemInfo);
            return allResults
                .Where(r => !r.IsCritical)
                .OrderByDescending(r => r.ProcessInfo.CpuUsage)
                .Take(count)
                .ToList();
        }

        /// <summary>
        /// Check if a process is in the user's whitelist
        /// </summary>
        public bool IsUserWhitelisted(ProcessInfo process)
        {
            return _config.WhitelistedProcesses.Contains(process.Name, StringComparer.OrdinalIgnoreCase) ||
                   _config.WhitelistedProcesses.Contains(process.Path, StringComparer.OrdinalIgnoreCase) ||
                   _config.WhitelistedProcesses.Contains(process.DisplayName, StringComparer.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Check if a process is blacklisted
        /// </summary>
        public bool IsBlacklisted(ProcessInfo process)
        {
            return _config.BlacklistedProcesses.Contains(process.Name, StringComparer.OrdinalIgnoreCase) ||
                   _config.BlacklistedProcesses.Contains(process.Path, StringComparer.OrdinalIgnoreCase) ||
                   CriticalProcesses.IsCritical(process.Name);
        }

        /// <summary>
        /// Check if a process can be optimized
        /// </summary>
        public bool CanOptimizeProcess(ProcessInfo process, SystemInfo systemInfo = null)
        {
            // Cannot optimize critical processes
            if (CriticalProcesses.IsCritical(process.Name))
                return false;
            
            // Cannot optimize blacklisted processes
            if (IsBlacklisted(process))
                return false;
            
            // Cannot optimize user-whitelisted processes
            if (IsUserWhitelisted(process))
                return false;
            
            // Cannot optimize active processes
            if (process.IsActive)
                return false;
            
            // Cannot optimize processes with visible windows
            if (process.HasVisibleWindow)
                return false;
            
            // Cannot optimize system processes (unless explicitly allowed)
            if (process.IsWindowsProcess || process.IsDriver)
                return false;
            
            // Cannot optimize services (unless we're going to stop the service)
            if (process.IsService)
                return false;
            
            // Cannot optimize processes that are too risky
            if (process.RiskLevel == RiskLevel.Critical || process.RiskLevel == RiskLevel.High)
                return false;
            
            // For medium risk, check if we're in automatic mode
            if (process.RiskLevel == RiskLevel.Medium && !_config.AllowHighRiskActions)
                return false;
            
            // Process must have some resource usage to be worth optimizing
            if (process.WorkingSet < 10 * 1024 * 1024) // Less than 10 MB
                return false;
            
            return true;
        }

        /// <summary>
        /// Calculate optimization score for a process (0-100)
        /// </summary>
        public int CalculateOptimizationScore(ProcessInfo process, SystemInfo systemInfo)
        {
            var score = 0;
            
            // Higher score for higher RAM usage
            var ramScore = Math.Min(50, (int)(process.WorkingSet / (1024.0 * 1024.0 * 10))); // 10 MB = 1 point, max 50
            score += ramScore;
            
            // Higher score for higher CPU usage
            var cpuScore = Math.Min(20, (int)(process.CpuUsage / 5)); // 5% CPU = 1 point, max 20
            score += cpuScore;
            
            // Higher score for background processes
            if (process.Category == ProcessCategory.BackgroundApplication)
                score += 20;
            
            // Higher score for non-critical processes
            if (!CriticalProcesses.IsCritical(process.Name))
                score += 10;
            
            // Lower score for services
            if (process.IsService)
                score -= 10;
            
            // Lower score for visible processes
            if (process.HasVisibleWindow)
                score -= 20;
            
            // Lower score for active processes
            if (process.IsActive)
                score -= 30;
            
            // Lower score for medium risk processes
            if (process.RiskLevel == RiskLevel.Medium)
                score -= 15;
            
            // Lower score for high risk processes
            if (process.RiskLevel == RiskLevel.High)
                score -= 30;
            
            // Lower score for critical processes
            if (process.RiskLevel == RiskLevel.Critical)
                score = 0;
            
            // Ensure score is between 0 and 100
            return Math.Max(0, Math.Min(100, score));
        }

        /// <summary>
        /// Get recommendation for a process
        /// </summary>
        public string GetProcessRecommendation(ProcessInfo process, SystemInfo systemInfo)
        {
            if (CriticalProcesses.IsCritical(process.Name))
                return "DO NOT TOUCH - Critical system process";
            
            if (IsBlacklisted(process))
                return "DO NOT TOUCH - Blacklisted process";
            
            if (IsUserWhitelisted(process))
                return "DO NOT TOUCH - User whitelisted process";
            
            if (process.IsActive)
                return "DO NOT CLOSE - Process is currently active";
            
            if (process.HasVisibleWindow)
                return "DO NOT CLOSE - Process has visible window";
            
            if (process.RiskLevel == RiskLevel.Critical)
                return "DO NOT TOUCH - Critical risk";
            
            if (process.RiskLevel == RiskLevel.High)
                return "CAUTION - High risk process";
            
            if (process.Category == ProcessCategory.BackgroundApplication)
                return "RECOMMENDED - Close to recover RAM";
            
            if (process.Category == ProcessCategory.UserApplication && !process.IsActive)
                return "SUGGESTED - Close inactive application";
            
            if (process.Category == ProcessCategory.Launcher)
                return "SUGGESTED - Close launcher when not needed";
            
            if (process.Category == ProcessCategory.Updater)
                return "SUGGESTED - Close updater after completion";
            
            if (process.Category == ProcessCategory.CloudSync)
                return "SUGGESTED - Pause cloud sync when not needed";
            
            if (process.Category == ProcessCategory.Telemetry)
                return "SUGGESTED - Disable telemetry for better performance";
            
            return "NEUTRAL - No specific recommendation";
        }

        /// <summary>
        /// Get detailed recommendation for a process
        /// </summary>
        public string GetRecommendationDetails(ProcessInfo process, SystemInfo systemInfo)
        {
            var sb = new System.Text.StringBuilder();
            
            sb.AppendLine($"Process: {process.DisplayName} ({process.Name})");
            sb.AppendLine($"Category: {process.Category}");
            sb.AppendLine($"Risk Level: {process.RiskLevel}");
            sb.AppendLine($"RAM Usage: {process.FormattedWorkingSet}");
            sb.AppendLine($"CPU Usage: {process.FormattedCpuUsage}");
            
            if (process.IsService)
            {
                sb.AppendLine($"Service: {process.ServiceName}");
            }
            
            sb.AppendLine();
            sb.AppendLine("Recommendation:");
            sb.AppendLine(GetProcessRecommendation(process, systemInfo));
            
            // Add AI analysis if available
            if (_config.AiEnabled)
            {
                try
                {
                    var aiAnalysis = _aiService.AnalyzeProcess(process);
                    if (!string.IsNullOrEmpty(aiAnalysis))
                    {
                        sb.AppendLine();
                        sb.AppendLine("AI Analysis:");
                        sb.AppendLine(aiAnalysis);
                    }
                }
                catch { }
            }
            
            return sb.ToString();
        }

        /// <summary>
        /// Calculate estimated RAM recovery for a process
        /// </summary>
        public long CalculateEstimatedRamRecovery(ProcessInfo process, SystemInfo systemInfo)
        {
            // For background processes, we can recover most of the RAM
            if (process.Category == ProcessCategory.BackgroundApplication)
                return process.WorkingSet;
            
            // For user applications that are not active, we can recover most of the RAM
            if (process.Category == ProcessCategory.UserApplication && !process.IsActive)
                return process.WorkingSet;
            
            // For launchers and updaters, we can recover most of the RAM
            if (process.Category == ProcessCategory.Launcher || 
                process.Category == ProcessCategory.Updater)
                return process.WorkingSet;
            
            // For cloud sync, we might recover some RAM
            if (process.Category == ProcessCategory.CloudSync)
                return process.WorkingSet / 2;
            
            // For telemetry, we might recover some RAM
            if (process.Category == ProcessCategory.Telemetry)
                return process.WorkingSet / 2;
            
            // For other processes, assume we can recover half
            return process.WorkingSet / 2;
        }

        /// <summary>
        /// Calculate estimated CPU improvement for a process
        /// </summary>
        public float CalculateEstimatedCpuImprovement(ProcessInfo process, SystemInfo systemInfo)
        {
            // For background processes using CPU, we can recover most of the CPU usage
            if (process.Category == ProcessCategory.BackgroundApplication)
                return process.CpuUsage * 0.8f;
            
            // For user applications that are not active, we can recover most of the CPU usage
            if (process.Category == ProcessCategory.UserApplication && !process.IsActive)
                return process.CpuUsage * 0.8f;
            
            // For launchers and updaters, we can recover most of the CPU usage
            if (process.Category == ProcessCategory.Launcher || 
                process.Category == ProcessCategory.Updater)
                return process.CpuUsage * 0.8f;
            
            // For other processes, assume we can recover half
            return process.CpuUsage * 0.5f;
        }

        /// <summary>
        /// Get processes that are potential resource hogs
        /// </summary>
        public List<ProcessAnalysisResult> GetResourceHogs(
            float ramThresholdPercent = 5f,
            float cpuThresholdPercent = 5f,
            SystemInfo systemInfo = null)
        {
            systemInfo = systemInfo ?? _scanner.Scan();
            
            var results = new List<ProcessAnalysisResult>();
            var totalRam = systemInfo.TotalPhysicalMemory;
            
            foreach (var process in systemInfo.Processes)
            {
                var result = new ProcessAnalysisResult { ProcessInfo = process };
                
                // Check RAM usage
                var ramPercent = (double)process.WorkingSet / totalRam * 100;
                
                // Check CPU usage
                var cpuPercent = process.CpuUsage;
                
                // Check if it's a resource hog
                if (ramPercent >= ramThresholdPercent || cpuPercent >= cpuThresholdPercent)
                {
                    result.CanOptimize = CanOptimizeProcess(process, systemInfo);
                    result.OptimizationScore = CalculateOptimizationScore(process, systemInfo);
                    result.Recommendation = GetProcessRecommendation(process, systemInfo);
                    results.Add(result);
                }
            }
            
            // Sort by resource usage
            results = results
                .OrderByDescending(r => r.ProcessInfo.WorkingSet)
                .ThenByDescending(r => r.ProcessInfo.CpuUsage)
                .ToList();
            
            return results;
        }

        /// <summary>
        /// Get processes that are potential malware
        /// </summary>
        public List<ProcessAnalysisResult> GetPotentialMalware(SystemInfo systemInfo = null)
        {
            systemInfo = systemInfo ?? _scanner.Scan();
            
            var results = new List<ProcessAnalysisResult>();
            
            foreach (var process in systemInfo.Processes)
            {
                var result = new ProcessAnalysisResult { ProcessInfo = process };
                
                // Check for suspicious characteristics
                if (IsPotentialMalware(process))
                {
                    result.CanOptimize = false; // Don't optimize potential malware
                    result.OptimizationScore = 0;
                    result.Recommendation = "POTENTIAL MALWARE - Do not touch, investigate further";
                    result.RiskLevel = RiskLevel.Critical;
                    results.Add(result);
                }
            }
            
            return results;
        }

        /// <summary>
        /// Check if a process might be malware
        /// </summary>
        public bool IsPotentialMalware(ProcessInfo process)
        {
            // Check for unsigned executables in suspicious locations
            if (process.SignatureStatus == SignatureStatus.Unsigned ||
                process.SignatureStatus == SignatureStatus.InvalidSignature ||
                process.SignatureStatus == SignatureStatus.Suspicious)
            {
                var suspiciousLocations = new[]
                {
                    "C:\\Users\\",
                    "C:\\ProgramData\\",
                    "C:\\Temp\\",
                    "C:\\Windows\\Temp\\",
                    "C:\\",
                    "D:\\",
                    "E:\\"
                };
                
                foreach (var location in suspiciousLocations)
                {
                    if (process.Path.StartsWith(location, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
            
            // Check for known malware patterns in process name
            var malwarePatterns = new[]
            {
                "virus", "malware", "spy", "steal", "hack", "crack", "keygen",
                "trojan", "worm", "rootkit", "backdoor", "exploit", "inject",
                "bot", "miner", "ransom", "encrypt", "payload", "dropper",
                "adware", "pup.", "riskware", "suspicious", "unknown"
            };
            
            var lowerName = process.Name.ToLower();
            var lowerPath = process.Path.ToLower();
            
            foreach (var pattern in malwarePatterns)
            {
                if (lowerName.Contains(pattern) || lowerPath.Contains(pattern))
                    return true;
            }
            
            // Check for processes running from temporary directories
            if (process.Path.Contains("\\Temp\\") || 
                process.Path.Contains("\\Temporary\\") ||
                process.Path.Contains("\\Temp\\"))
                return true;
            
            // Check for processes with random names
            if (IsRandomName(process.Name))
                return true;
            
            return false;
        }

        /// <summary>
        /// Check if a name looks random (potential malware characteristic)
        /// </summary>
        private bool IsRandomName(string name)
        {
            // Check for names that are all lowercase letters
            if (name.Length >= 5 && name.All(c => c >= 'a' && c <= 'z'))
                return true;
            
            // Check for names that are all numbers
            if (name.Length >= 5 && name.All(c => c >= '0' && c <= '9'))
                return true;
            
            // Check for names that are random alphanumeric
            if (name.Length >= 8 && name.All(c => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')))
                return true;
            
            return false;
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the analyzer
        /// </summary>
        public void Dispose()
        {
            try
            {
                _scanner?.Dispose();
                _aiService?.Dispose();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Process analysis result
    /// </summary>
    public class ProcessAnalysisResult
    {
        /// <summary>
        /// Process information
        /// </summary>
        public ProcessInfo ProcessInfo { get; set; } = new ProcessInfo();
        
        /// <summary>
        /// Process category
        /// </summary>
        public ProcessCategory Category { get; set; } = ProcessCategory.Unknown;
        
        /// <summary>
        /// Risk level
        /// </summary>
        public RiskLevel RiskLevel { get; set; } = RiskLevel.Critical;
        
        /// <summary>
        /// Whether the process is critical
        /// </summary>
        public bool IsCritical { get; set; } = true;
        
        /// <summary>
        /// Whether the process is a Windows system process
        /// </summary>
        public bool IsWindowsProcess { get; set; }
        
        /// <summary>
        /// Whether the process is a driver
        /// </summary>
        public bool IsDriver { get; set; }
        
        /// <summary>
        /// Whether the process is a service
        /// </summary>
        public bool IsService { get; set; }
        
        /// <summary>
        /// Whether the process is active
        /// </summary>
        public bool IsActive { get; set; }
        
        /// <summary>
        /// Whether the process has a visible window
        /// </summary>
        public bool HasVisibleWindow { get; set; }
        
        /// <summary>
        /// Whether the process is in the user's whitelist
        /// </summary>
        public bool IsUserWhitelisted { get; set; }
        
        /// <summary>
        /// Whether the process is blacklisted
        /// </summary>
        public bool IsBlacklisted { get; set; }
        
        /// <summary>
        /// Whether the process can be optimized
        /// </summary>
        public bool CanOptimize { get; set; }
        
        /// <summary>
        /// Optimization score (0-100)
        /// </summary>
        public int OptimizationScore { get; set; }
        
        /// <summary>
        /// Recommendation
        /// </summary>
        public string Recommendation { get; set; } = string.Empty;
        
        /// <summary>
        /// Detailed recommendation
        /// </summary>
        public string RecommendationDetails { get; set; } = string.Empty;
        
        /// <summary>
        /// Estimated RAM recovery in bytes
        /// </summary>
        public long EstimatedRamRecovery { get; set; }
        
        /// <summary>
        /// Estimated CPU improvement percentage
        /// </summary>
        public float EstimatedCpuImprovement { get; set; }
        
        /// <summary>
        /// AI analysis
        /// </summary>
        public string AiAnalysis { get; set; } = string.Empty;
        
        /// <summary>
        /// Whether AI analysis was performed
        /// </summary>
        public bool AiAnalyzed { get; set; }
        
        /// <summary>
        /// Error message if analysis failed
        /// </summary>
        public string Error { get; set; } = string.Empty;
    }

    /// <summary>
    /// Process analysis event arguments
    /// </summary>
    public class ProcessAnalysisEventArgs : EventArgs
    {
        public DateTime Timestamp { get; set; }
        public TimeSpan Duration { get; set; }
        public int ProcessCount { get; set; }
        public int OptimizableCount { get; set; }
        public string ErrorMessage { get; set; } = string.Empty;
        public Exception Exception { get; set; }
        public List<ProcessAnalysisResult> Results { get; set; } = new List<ProcessAnalysisResult>();
    }
}

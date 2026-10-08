using System;
using System.Collections.Generic;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Represents the optimization history for the system
    /// </summary>
    public class OptimizationHistory
    {
        #region Properties

        /// <summary>
        /// List of all optimization sessions
        /// </summary>
        public List<OptimizationSession> Sessions { get; set; } = new List<OptimizationSession>();

        /// <summary>
        /// Current session
        /// </summary>
        public OptimizationSession? CurrentSession { get; set; }

        /// <summary>
        /// Total number of optimizations performed
        /// </summary>
        public int TotalOptimizationCount => Sessions.Count;

        /// <summary>
        /// Total RAM recovered across all sessions
        /// </summary>
        public long TotalRamRecovered
        {
            get
            {
                long total = 0;
                foreach (var session in Sessions)
                {
                    if (session.AfterSystemInfo != null && session.BeforeSystemInfo != null)
                    {
                        var beforeUsed = session.BeforeSystemInfo.TotalPhysicalMemory - 
                                       session.BeforeSystemInfo.AvailablePhysicalMemory;
                        var afterUsed = session.AfterSystemInfo.TotalPhysicalMemory - 
                                      session.AfterSystemInfo.AvailablePhysicalMemory;
                        total += beforeUsed - afterUsed;
                    }
                }
                return total;
            }
        }

        /// <summary>
        /// Average success rate
        /// </summary>
        public float AverageSuccessRate
        {
            get
            {
                if (Sessions.Count == 0) return 0;
                
                float total = 0;
                foreach (var session in Sessions)
                {
                    if (session.Plan != null)
                    {
                        total += session.Plan.SuccessRate;
                    }
                }
                return total / Sessions.Count;
            }
        }

        /// <summary>
        /// Last optimization date
        /// </summary>
        public DateTime? LastOptimizationDate
        {
            get
            {
                if (Sessions.Count == 0) return null;
                return Sessions[^1].Timestamp;
            }
        }

        /// <summary>
        /// Best optimization result (highest RAM recovery)
        /// </summary>
        public OptimizationSession? BestSession
        {
            get
            {
                if (Sessions.Count == 0) return null;
                
                OptimizationSession? best = null;
                long bestRecovery = 0;
                
                foreach (var session in Sessions)
                {
                    if (session.AfterSystemInfo != null && session.BeforeSystemInfo != null)
                    {
                        var beforeUsed = session.BeforeSystemInfo.TotalPhysicalMemory - 
                                       session.BeforeSystemInfo.AvailablePhysicalMemory;
                        var afterUsed = session.AfterSystemInfo.TotalPhysicalMemory - 
                                      session.AfterSystemInfo.AvailablePhysicalMemory;
                        var recovery = beforeUsed - afterUsed;
                        
                        if (recovery > bestRecovery)
                        {
                            bestRecovery = recovery;
                            best = session;
                        }
                    }
                }
                
                return best;
            }
        }

        #endregion

        #region Methods

        /// <summary>
        /// Start a new optimization session
        /// </summary>
        public OptimizationSession StartSession(OptimizationPlan? plan = null)
        {
            var session = new OptimizationSession
            {
                Id = Guid.NewGuid(),
                Timestamp = DateTime.Now,
                Plan = plan,
                BeforeSystemInfo = new SystemInfo()
            };
            
            CurrentSession = session;
            Sessions.Add(session);
            
            return session;
        }

        /// <summary>
        /// End the current session
        /// </summary>
        public void EndSession(SystemInfo afterSystemInfo)
        {
            if (CurrentSession != null)
            {
                CurrentSession.AfterSystemInfo = afterSystemInfo;
                CurrentSession.EndTimestamp = DateTime.Now;
                CurrentSession = null;
            }
        }

        /// <summary>
        /// Add a session to history
        /// </summary>
        public void AddSession(OptimizationSession session)
        {
            Sessions.Add(session);
            // Keep only the last 100 sessions to prevent memory issues
            if (Sessions.Count > 100)
            {
                Sessions.RemoveAt(0);
            }
        }

        /// <summary>
        /// Remove a session from history
        /// </summary>
        public bool RemoveSession(Guid sessionId)
        {
            var session = Sessions.Find(s => s.Id == sessionId);
            if (session != null)
            {
                Sessions.Remove(session);
                return true;
            }
            return false;
        }

        /// <summary>
        /// Clear all history
        /// </summary>
        public void ClearHistory()
        {
            Sessions.Clear();
            CurrentSession = null;
        }

        /// <summary>
        /// Get sessions by date range
        /// </summary>
        public List<OptimizationSession> GetSessionsByDateRange(DateTime start, DateTime end)
        {
            return Sessions.FindAll(s => s.Timestamp >= start && s.Timestamp <= end);
        }

        /// <summary>
        /// Get sessions by optimization mode
        /// </summary>
        public List<OptimizationSession> GetSessionsByMode(OptimizationMode mode)
        {
            return Sessions.FindAll(s => s.Plan != null && s.Plan.Mode == mode);
        }

        /// <summary>
        /// Get recent sessions
        /// </summary>
        public List<OptimizationSession> GetRecentSessions(int count = 10)
        {
            var recent = new List<OptimizationSession>();
            for (int i = Sessions.Count - 1; i >= 0 && recent.Count < count; i--)
            {
                recent.Add(Sessions[i]);
            }
            recent.Reverse();
            return recent;
        }

        /// <summary>
        /// Generate a summary report
        /// </summary>
        public string GenerateReport()
        {
            var report = new System.Text.StringBuilder();
            
            report.AppendLine("=== OPTIMIZATION HISTORY REPORT ===");
            report.AppendLine();
            report.AppendLine($"Total Sessions: {TotalOptimizationCount}");
            report.AppendLine($"Total RAM Recovered: {FormatBytes(TotalRamRecovered)}");
            report.AppendLine($"Average Success Rate: {AverageSuccessRate:F1}%");
            report.AppendLine($"Last Optimization: {(LastOptimizationDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "Never")}");
            report.AppendLine();
            
            if (BestSession != null)
            {
                var beforeUsed = BestSession.BeforeSystemInfo.TotalPhysicalMemory - 
                               BestSession.BeforeSystemInfo.AvailablePhysicalMemory;
                var afterUsed = BestSession.AfterSystemInfo.TotalPhysicalMemory - 
                              BestSession.AfterSystemInfo.AvailablePhysicalMemory;
                var recovery = beforeUsed - afterUsed;
                
                report.AppendLine("=== BEST SESSION ===");
                report.AppendLine($"Date: {BestSession.Timestamp:yyyy-MM-dd HH:mm:ss}");
                report.AppendLine($"RAM Recovered: {FormatBytes(recovery)}");
                report.AppendLine();
            }
            
            report.AppendLine("=== RECENT SESSIONS ===");
            foreach (var session in GetRecentSessions(5))
            {
                report.AppendLine($"\nSession: {session.Timestamp:yyyy-MM-dd HH:mm:ss}");
                report.AppendLine($"  Mode: {session.Plan?.Mode}");
                report.AppendLine($"  Actions: {session.Plan?.TotalActionCount}");
                report.AppendLine($"  Success Rate: {session.Plan?.SuccessRate:F1}%");
                
                if (session.BeforeSystemInfo != null && session.AfterSystemInfo != null)
                {
                    var beforeRam = session.BeforeSystemInfo.RamUsagePercentage;
                    var afterRam = session.AfterSystemInfo.RamUsagePercentage;
                    var beforeCpu = session.BeforeSystemInfo.CpuUsage;
                    var afterCpu = session.AfterSystemInfo.CpuUsage;
                    
                    report.AppendLine($"  RAM: {beforeRam:F1}% → {afterRam:F1}%");
                    report.AppendLine($"  CPU: {beforeCpu:F1}% → {afterCpu:F1}%");
                }
            }
            
            return report.ToString();
        }

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

        #endregion
    }

    /// <summary>
    /// Represents a single optimization session
    /// </summary>
    public class OptimizationSession
    {
        #region Properties

        /// <summary>
        /// Unique identifier for the session
        /// </summary>
        public Guid Id { get; set; } = Guid.NewGuid();

        /// <summary>
        /// When the session started
        /// </summary>
        public DateTime Timestamp { get; set; } = DateTime.Now;

        /// <summary>
        /// When the session ended
        /// </summary>
        public DateTime? EndTimestamp { get; set; }

        /// <summary>
        /// Duration of the session
        /// </summary>
        public TimeSpan Duration => EndTimestamp.HasValue ? 
            EndTimestamp.Value - Timestamp : TimeSpan.Zero;

        /// <summary>
        /// The optimization plan used in this session
        /// </summary>
        public OptimizationPlan? Plan { get; set; }

        /// <summary>
        /// System information before optimization
        /// </summary>
        public SystemInfo BeforeSystemInfo { get; set; } = new SystemInfo();

        /// <summary>
        /// System information after optimization
        /// </summary>
        public SystemInfo? AfterSystemInfo { get; set; }

        /// <summary>
        /// Whether the session was successful
        /// </summary>
        public bool IsSuccessful => Plan != null && Plan.IsSuccessful;

        /// <summary>
        /// RAM usage before optimization
        /// </summary>
        public float BeforeRamUsage => BeforeSystemInfo.RamUsagePercentage;

        /// <summary>
        /// RAM usage after optimization
        /// </summary>
        public float AfterRamUsage => AfterSystemInfo?.RamUsagePercentage ?? BeforeRamUsage;

        /// <summary>
        /// CPU usage before optimization
        /// </summary>
        public float BeforeCpuUsage => BeforeSystemInfo.CpuUsage;

        /// <summary>
        /// CPU usage after optimization
        /// </summary>
        public float AfterCpuUsage => AfterSystemInfo?.CpuUsage ?? BeforeCpuUsage;

        /// <summary>
        /// RAM improvement
        /// </summary>
        public float RamImprovement => BeforeRamUsage - AfterRamUsage;

        /// <summary>
        /// CPU improvement
        /// </summary>
        public float CpuImprovement => BeforeCpuUsage - AfterCpuUsage;

        /// <summary>
        /// Process count before optimization
        /// </summary>
        public int BeforeProcessCount => BeforeSystemInfo.TotalProcessCount;

        /// <summary>
        /// Process count after optimization
        /// </summary>
        public int AfterProcessCount => AfterSystemInfo?.TotalProcessCount ?? BeforeProcessCount;

        /// <summary>
        /// Process count improvement
        /// </summary>
        public int ProcessCountImprovement => BeforeProcessCount - AfterProcessCount;

        /// <summary>
        /// Notes about the session
        /// </summary>
        public string Notes { get; set; } = string.Empty;

        /// <summary>
        /// User who performed the optimization
        /// </summary>
        public string UserName { get; set; } = Environment.UserName;

        #endregion

        #region Helper Properties

        /// <summary>
        /// Formatted duration
        /// </summary>
        public string FormattedDuration
        {
            get
            {
                var ts = Duration;
                if (ts.TotalHours >= 1)
                    return $"{ts.Hours}h {ts.Minutes}m {ts.Seconds}s";
                else if (ts.TotalMinutes >= 1)
                    return $"{ts.Minutes}m {ts.Seconds}s";
                else
                    return $"{ts.Seconds}s";
            }
        }

        /// <summary>
        /// Formatted timestamp
        /// </summary>
        public string FormattedTimestamp => Timestamp.ToString("yyyy-MM-dd HH:mm:ss");

        /// <summary>
        /// Formatted end timestamp
        /// </summary>
        public string FormattedEndTimestamp => EndTimestamp?.ToString("yyyy-MM-dd HH:mm:ss") ?? "In Progress";

        #endregion

        #region Methods

        /// <summary>
        /// Generate a summary of the session
        /// </summary>
        public string GenerateSummary()
        {
            var summary = new System.Text.StringBuilder();
            
            summary.AppendLine($"Optimization Session: {Id}");
            summary.AppendLine($"Timestamp: {FormattedTimestamp}");
            summary.AppendLine($"Duration: {FormattedDuration}");
            summary.AppendLine($"User: {UserName}");
            summary.AppendLine();
            
            if (Plan != null)
            {
                summary.AppendLine($"Plan: {Plan.Name}");
                summary.AppendLine($"Mode: {Plan.Mode}");
                summary.AppendLine($"Actions: {Plan.TotalActionCount}");
                summary.AppendLine($"Success Rate: {Plan.SuccessRate:F1}%");
                summary.AppendLine();
            }
            
            summary.AppendLine("=== System Metrics ===");
            summary.AppendLine($"RAM Usage: {BeforeRamUsage:F1}% → {AfterRamUsage:F1}% (Δ: {RamImprovement:+0.00;-0.00}%)");
            summary.AppendLine($"CPU Usage: {BeforeCpuUsage:F1}% → {AfterCpuUsage:F1}% (Δ: {CpuImprovement:+0.00;-0.00}%)");
            summary.AppendLine($"Process Count: {BeforeProcessCount} → {AfterProcessCount} (Δ: {ProcessCountImprovement:+0;-0})");
            
            if (!string.IsNullOrEmpty(Notes))
            {
                summary.AppendLine();
                summary.AppendLine("=== Notes ===");
                summary.AppendLine(Notes);
            }
            
            return summary.ToString();
        }

        #endregion
    }
}

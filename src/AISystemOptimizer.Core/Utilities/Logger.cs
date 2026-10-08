using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using System.Linq;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Logging levels
    /// </summary>
    public enum LogLevel
    {
        Verbose,
        Debug,
        Info,
        Warning,
        Error,
        Critical
    }

    /// <summary>
    /// Log entry structure
    /// </summary>
    public class LogEntry
    {
        public DateTime Timestamp { get; set; } = DateTime.Now;
        public LogLevel Level { get; set; } = LogLevel.Info;
        public string Source { get; set; } = string.Empty;
        public string Message { get; set; } = string.Empty;
        public string? Details { get; set; }
        public Exception? Exception { get; set; }
        public string StackTrace => Exception?.StackTrace ?? string.Empty;
        
        public override string ToString()
        {
            var sb = new StringBuilder();
            sb.Append($"[{Timestamp:yyyy-MM-dd HH:mm:ss.fff}] ");
            sb.Append($"[{Level.ToString().ToUpper()}] ");
            sb.Append($"[{Source}] ");
            sb.Append(Message);
            
            if (!string.IsNullOrEmpty(Details))
            {
                sb.Append($"\nDetails: {Details}");
            }
            
            if (Exception != null)
            {
                sb.Append($"\nException: {Exception.Message}\n{StackTrace}");
            }
            
            return sb.ToString();
        }
    }

    /// <summary>
    /// Logger interface
    /// </summary>
    public interface ILogger
    {
        void Log(LogLevel level, string source, string message, string? details = null, Exception? exception = null);
        void Verbose(string source, string message, string? details = null);
        void Debug(string source, string message, string? details = null);
        void Info(string source, string message, string? details = null);
        void Warning(string source, string message, string? details = null, Exception? exception = null);
        void Error(string source, string message, string? details = null, Exception? exception = null);
        void Critical(string source, string message, string? details = null, Exception? exception = null);
        void Flush();
        void Clear();
        List<LogEntry> GetLogEntries(int count = 100);
        List<LogEntry> GetLogEntries(LogLevel minLevel, int count = 100);
        List<LogEntry> GetLogEntriesBySource(string source, int count = 100);
    }

    /// <summary>
    /// File logger implementation
    /// </summary>
    public class FileLogger : ILogger, IDisposable
    {
        #region Private Fields

        private readonly string _logDirectory;
        private readonly string _logFilePath;
        private readonly LogLevel _minLogLevel;
        private readonly int _maxFileSizeMB;
        private readonly int _maxFiles;
        private readonly object _lock = new object();
        private readonly Queue<LogEntry> _logBuffer = new Queue<LogEntry>();
        private readonly Timer _flushTimer;
        private bool _disposed = false;
        private readonly List<LogEntry> _recentLogs = new List<LogEntry>();
        private const int MaxRecentLogs = 1000;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new file logger
        /// </summary>
        public FileLogger(
            string logDirectory = null,
            string logFileName = null,
            LogLevel minLogLevel = LogLevel.Info,
            int maxFileSizeMB = 10,
            int maxFiles = 5)
        {
            _logDirectory = logDirectory ?? AppConstants.LogDirectoryPath;
            _logFilePath = logFileName ?? Path.Combine(_logDirectory, $"{DateTime.Now:yyyy-MM-dd}.log");
            _minLogLevel = minLogLevel;
            _maxFileSizeMB = maxFileSizeMB;
            _maxFiles = maxFiles;
            
            // Ensure directory exists
            if (!Directory.Exists(_logDirectory))
            {
                Directory.CreateDirectory(_logDirectory);
            }
            
            // Set up auto-flush timer
            _flushTimer = new Timer(FlushBuffer, null, TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5));
        }

        /// <summary>
        /// Create a file logger with configuration
        /// </summary>
        public FileLogger(AppConfig config)
            : this(
                config.LogFilePath,
                null,
                ParseLogLevel(config.LogLevel),
                config.MaxLogFileSizeMB,
                config.MaxLogFiles)
        {
        }

        #endregion

        #region Properties

        /// <summary>
        /// Minimum log level to write
        /// </summary>
        public LogLevel MinLogLevel => _minLogLevel;

        /// <summary>
        /// Current log file path
        /// </summary>
        public string LogFilePath => _logFilePath;

        #endregion

        #region Public Methods

        /// <summary>
        /// Log a message
        /// </summary>
        public void Log(LogLevel level, string source, string message, string? details = null, Exception? exception = null)
        {
            if (level < _minLogLevel) return;
            
            var entry = new LogEntry
            {
                Timestamp = DateTime.Now,
                Level = level,
                Source = source,
                Message = message,
                Details = details,
                Exception = exception
            };
            
            lock (_lock)
            {
                _logBuffer.Enqueue(entry);
                _recentLogs.Add(entry);
                
                // Keep only the most recent logs in memory
                if (_recentLogs.Count > MaxRecentLogs)
                {
                    _recentLogs.RemoveAt(0);
                }
            }
            
            // Write to file immediately for errors and critical
            if (level == LogLevel.Error || level == LogLevel.Critical)
            {
                WriteToFile(entry);
            }
        }

        /// <summary>
        /// Log a verbose message
        /// </summary>
        public void Verbose(string source, string message, string? details = null)
        {
            Log(LogLevel.Verbose, source, message, details);
        }

        /// <summary>
        /// Log a debug message
        /// </summary>
        public void Debug(string source, string message, string? details = null)
        {
            Log(LogLevel.Debug, source, message, details);
        }

        /// <summary>
        /// Log an info message
        /// </summary>
        public void Info(string source, string message, string? details = null)
        {
            Log(LogLevel.Info, source, message, details);
        }

        /// <summary>
        /// Log a warning message
        /// </summary>
        public void Warning(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Warning, source, message, details, exception);
        }

        /// <summary>
        /// Log an error message
        /// </summary>
        public void Error(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Error, source, message, details, exception);
        }

        /// <summary>
        /// Log a critical message
        /// </summary>
        public void Critical(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Critical, source, message, details, exception);
        }

        /// <summary>
        /// Flush the log buffer to file
        /// </summary>
        public void Flush()
        {
            lock (_lock)
            {
                while (_logBuffer.Count > 0)
                {
                    var entry = _logBuffer.Dequeue();
                    WriteToFile(entry);
                }
            }
        }

        /// <summary>
        /// Clear all log files
        /// </summary>
        public void Clear()
        {
            lock (_lock)
            {
                try
                {
                    // Delete all log files in the directory
                    var files = Directory.GetFiles(_logDirectory, "*.log");
                    foreach (var file in files)
                    {
                        try
                        {
                            File.Delete(file);
                        }
                        catch { }
                    }
                    
                    _recentLogs.Clear();
                    _logBuffer.Clear();
                }
                catch { }
            }
        }

        /// <summary>
        /// Get recent log entries
        /// </summary>
        public List<LogEntry> GetLogEntries(int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                var startIndex = Math.Max(0, _recentLogs.Count - count);
                for (int i = startIndex; i < _recentLogs.Count; i++)
                {
                    result.Add(_recentLogs[i]);
                }
                return result;
            }
        }

        /// <summary>
        /// Get log entries filtered by minimum level
        /// </summary>
        public List<LogEntry> GetLogEntries(LogLevel minLevel, int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                for (int i = _recentLogs.Count - 1; i >= 0 && result.Count < count; i--)
                {
                    if (_recentLogs[i].Level >= minLevel)
                    {
                        result.Insert(0, _recentLogs[i]);
                    }
                }
                return result;
            }
        }

        /// <summary>
        /// Get log entries by source
        /// </summary>
        public List<LogEntry> GetLogEntriesBySource(string source, int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                for (int i = _recentLogs.Count - 1; i >= 0 && result.Count < count; i--)
                {
                    if (_recentLogs[i].Source.Equals(source, StringComparison.OrdinalIgnoreCase))
                    {
                        result.Insert(0, _recentLogs[i]);
                    }
                }
                return result;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Write a log entry to file
        /// </summary>
        private void WriteToFile(LogEntry entry)
        {
            try
            {
                lock (_lock)
                {
                    // Check if we need to rotate logs
                    if (File.Exists(_logFilePath))
                    {
                        var fileInfo = new FileInfo(_logFilePath);
                        if (fileInfo.Length > _maxFileSizeMB * 1024 * 1024)
                        {
                            RotateLogs();
                        }
                    }
                    
                    // Append to the log file
                    using (var writer = File.AppendText(_logFilePath))
                    {
                        writer.WriteLine(entry.ToString());
                    }
                }
            }
            catch { }
        }

        /// <summary>
        /// Rotate log files
        /// </summary>
        private void RotateLogs()
        {
            try
            {
                var files = Directory.GetFiles(_logDirectory, "*.log");
                Array.Sort(files, StringComparer.OrdinalIgnoreCase);
                
                // Keep only the most recent files
                if (files.Length > _maxFiles)
                {
                    for (int i = 0; i < files.Length - _maxFiles; i++)
                    {
                        try
                        {
                            File.Delete(files[i]);
                        }
                        catch { }
                    }
                }
                
                // Rename current log file with timestamp
                var timestamp = DateTime.Now.ToString("yyyy-MM-dd-HH-mm-ss");
                var newPath = Path.Combine(_logDirectory, $"{timestamp}.log");
                
                if (File.Exists(_logFilePath))
                {
                    File.Move(_logFilePath, newPath);
                }
            }
            catch { }
        }

        /// <summary>
        /// Flush buffer callback
        /// </summary>
        private void FlushBuffer(object? state)
        {
            try
            {
                Flush();
            }
            catch { }
        }

        /// <summary>
        /// Parse log level from string
        /// </summary>
        private static LogLevel ParseLogLevel(string level)
        {
            return level switch
            {
                "Verbose" => LogLevel.Verbose,
                "Debug" => LogLevel.Debug,
                "Info" => LogLevel.Info,
                "Warning" => LogLevel.Warning,
                "Error" => LogLevel.Error,
                "Critical" => LogLevel.Critical,
                _ => LogLevel.Info
            };
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the logger
        /// </summary>
        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        /// <summary>
        /// Dispose implementation
        /// </summary>
        protected virtual void Dispose(bool disposing)
        {
            if (!_disposed)
            {
                if (disposing)
                {
                    _flushTimer?.Dispose();
                    Flush();
                }
                _disposed = true;
            }
        }

        /// <summary>
        /// Finalizer
        /// </summary>
        ~FileLogger()
        {
            Dispose(false);
        }

        #endregion
    }

    /// <summary>
    /// Console logger implementation
    /// </summary>
    public class ConsoleLogger : ILogger
    {
        #region Private Fields

        private readonly LogLevel _minLogLevel;
        private readonly object _lock = new object();
        private readonly List<LogEntry> _recentLogs = new List<LogEntry>();
        private const int MaxRecentLogs = 1000;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new console logger
        /// </summary>
        public ConsoleLogger(LogLevel minLogLevel = LogLevel.Info)
        {
            _minLogLevel = minLogLevel;
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Log a message
        /// </summary>
        public void Log(LogLevel level, string source, string message, string? details = null, Exception? exception = null)
        {
            if (level < _minLogLevel) return;
            
            var entry = new LogEntry
            {
                Timestamp = DateTime.Now,
                Level = level,
                Source = source,
                Message = message,
                Details = details,
                Exception = exception
            };
            
            lock (_lock)
            {
                _recentLogs.Add(entry);
                
                if (_recentLogs.Count > MaxRecentLogs)
                {
                    _recentLogs.RemoveAt(0);
                }
            }
            
            WriteToConsole(entry);
        }

        /// <summary>
        /// Log a verbose message
        /// </summary>
        public void Verbose(string source, string message, string? details = null)
        {
            Log(LogLevel.Verbose, source, message, details);
        }

        /// <summary>
        /// Log a debug message
        /// </summary>
        public void Debug(string source, string message, string? details = null)
        {
            Log(LogLevel.Debug, source, message, details);
        }

        /// <summary>
        /// Log an info message
        /// </summary>
        public void Info(string source, string message, string? details = null)
        {
            Log(LogLevel.Info, source, message, details);
        }

        /// <summary>
        /// Log a warning message
        /// </summary>
        public void Warning(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Warning, source, message, details, exception);
        }

        /// <summary>
        /// Log an error message
        /// </summary>
        public void Error(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Error, source, message, details, exception);
        }

        /// <summary>
        /// Log a critical message
        /// </summary>
        public void Critical(string source, string message, string? details = null, Exception? exception = null)
        {
            Log(LogLevel.Critical, source, message, details, exception);
        }

        /// <summary>
        /// Flush the logger (not applicable for console)
        /// </summary>
        public void Flush() { }

        /// <summary>
        /// Clear the logger (not applicable for console)
        /// </summary>
        public void Clear()
        {
            lock (_lock)
            {
                _recentLogs.Clear();
            }
        }

        /// <summary>
        /// Get recent log entries
        /// </summary>
        public List<LogEntry> GetLogEntries(int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                var startIndex = Math.Max(0, _recentLogs.Count - count);
                for (int i = startIndex; i < _recentLogs.Count; i++)
                {
                    result.Add(_recentLogs[i]);
                }
                return result;
            }
        }

        /// <summary>
        /// Get log entries filtered by minimum level
        /// </summary>
        public List<LogEntry> GetLogEntries(LogLevel minLevel, int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                for (int i = _recentLogs.Count - 1; i >= 0 && result.Count < count; i--)
                {
                    if (_recentLogs[i].Level >= minLevel)
                    {
                        result.Insert(0, _recentLogs[i]);
                    }
                }
                return result;
            }
        }

        /// <summary>
        /// Get log entries by source
        /// </summary>
        public List<LogEntry> GetLogEntriesBySource(string source, int count = 100)
        {
            lock (_lock)
            {
                var result = new List<LogEntry>();
                for (int i = _recentLogs.Count - 1; i >= 0 && result.Count < count; i--)
                {
                    if (_recentLogs[i].Source.Equals(source, StringComparison.OrdinalIgnoreCase))
                    {
                        result.Insert(0, _recentLogs[i]);
                    }
                }
                return result;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Write a log entry to console
        /// </summary>
        private void WriteToConsole(LogEntry entry)
        {
            try
            {
                var originalColor = Console.ForegroundColor;
                
                // Set color based on log level
                Console.ForegroundColor = entry.Level switch
                {
                    LogLevel.Verbose => ConsoleColor.Gray,
                    LogLevel.Debug => ConsoleColor.DarkGray,
                    LogLevel.Info => ConsoleColor.White,
                    LogLevel.Warning => ConsoleColor.Yellow,
                    LogLevel.Error => ConsoleColor.Red,
                    LogLevel.Critical => ConsoleColor.DarkRed,
                    _ => ConsoleColor.White
                };
                
                Console.WriteLine(entry.ToString());
                Console.ForegroundColor = originalColor;
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Composite logger that writes to multiple loggers
    /// </summary>
    public class CompositeLogger : ILogger, IDisposable
    {
        #region Private Fields

        private readonly List<ILogger> _loggers = new List<ILogger>();
        private bool _disposed = false;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a composite logger
        /// </summary>
        public CompositeLogger(params ILogger[] loggers)
        {
            _loggers.AddRange(loggers);
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Log a message
        /// </summary>
        public void Log(LogLevel level, string source, string message, string? details = null, Exception? exception = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Log(level, source, message, details, exception);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log a verbose message
        /// </summary>
        public void Verbose(string source, string message, string? details = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Verbose(source, message, details);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log a debug message
        /// </summary>
        public void Debug(string source, string message, string? details = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Debug(source, message, details);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log an info message
        /// </summary>
        public void Info(string source, string message, string? details = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Info(source, message, details);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log a warning message
        /// </summary>
        public void Warning(string source, string message, string? details = null, Exception? exception = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Warning(source, message, details, exception);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log an error message
        /// </summary>
        public void Error(string source, string message, string? details = null, Exception? exception = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Error(source, message, details, exception);
                }
                catch { }
            }
        }

        /// <summary>
        /// Log a critical message
        /// </summary>
        public void Critical(string source, string message, string? details = null, Exception? exception = null)
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Critical(source, message, details, exception);
                }
                catch { }
            }
        }

        /// <summary>
        /// Flush all loggers
        /// </summary>
        public void Flush()
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Flush();
                }
                catch { }
            }
        }

        /// <summary>
        /// Clear all loggers
        /// </summary>
        public void Clear()
        {
            foreach (var logger in _loggers)
            {
                try
                {
                    logger.Clear();
                }
                catch { }
            }
        }

        /// <summary>
        /// Get log entries from the first logger
        /// </summary>
        public List<LogEntry> GetLogEntries(int count = 100)
        {
            if (_loggers.Count > 0)
            {
                return _loggers[0].GetLogEntries(count);
            }
            return new List<LogEntry>();
        }

        /// <summary>
        /// Get log entries filtered by minimum level from the first logger
        /// </summary>
        public List<LogEntry> GetLogEntries(LogLevel minLevel, int count = 100)
        {
            if (_loggers.Count > 0)
            {
                return _loggers[0].GetLogEntries(minLevel, count);
            }
            return new List<LogEntry>();
        }

        /// <summary>
        /// Get log entries by source from the first logger
        /// </summary>
        public List<LogEntry> GetLogEntriesBySource(string source, int count = 100)
        {
            if (_loggers.Count > 0)
            {
                return _loggers[0].GetLogEntriesBySource(source, count);
            }
            return new List<LogEntry>();
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the composite logger
        /// </summary>
        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        /// <summary>
        /// Dispose implementation
        /// </summary>
        protected virtual void Dispose(bool disposing)
        {
            if (!_disposed)
            {
                if (disposing)
                {
                    Flush();
                    foreach (var logger in _loggers.OfType<IDisposable>())
                    {
                        try
                        {
                            logger.Dispose();
                        }
                        catch { }
                    }
                }
                _disposed = true;
            }
        }

        /// <summary>
        /// Finalizer
        /// </summary>
        ~CompositeLogger()
        {
            Dispose(false);
        }

        #endregion
    }

    /// <summary>
    /// Logger factory
    /// </summary>
    public static class LoggerFactory
    {
        #region Private Fields

        private static ILogger _defaultLogger = null;
        private static readonly object _lock = new object();

        #endregion

        #region Public Methods

        /// <summary>
        /// Get the default logger
        /// </summary>
        public static ILogger GetLogger()
        {
            lock (_lock)
            {
                if (_defaultLogger == null)
                {
                    _defaultLogger = CreateLogger();
                }
                return _defaultLogger;
            }
        }

        /// <summary>
        /// Get (and cache) a logger configured from <see cref="AppConfig"/>.
        /// </summary>
        public static ILogger GetLogger(AppConfig config)
        {
            lock (_lock)
            {
                if (_defaultLogger == null)
                {
                    _defaultLogger = CreateLogger(config);
                }
                return _defaultLogger;
            }
        }

        /// <summary>
        /// Create a logger based on configuration
        /// </summary>
        public static ILogger CreateLogger(AppConfig config = null)
        {
            var loggers = new List<ILogger>();
            
            // Always add file logger if logging is enabled
            if (config == null || config.LoggingEnabled)
            {
                var fileLogger = new FileLogger(
                    config?.LogFilePath ?? AppConstants.LogDirectoryPath,
                    null,
                    config != null ? ParseLogLevel(config.LogLevel) : LogLevel.Info,
                    config?.MaxLogFileSizeMB ?? AppConstants.DefaultMaxLogFileSizeMB,
                    config?.MaxLogFiles ?? AppConstants.DefaultMaxLogFiles);
                
                loggers.Add(fileLogger);
            }
            
            // Add console logger if enabled
            if (config != null && config.LogToConsole)
            {
                loggers.Add(new ConsoleLogger(config.LoggingEnabled ? 
                    ParseLogLevel(config.LogLevel) : LogLevel.Info));
            }
            
            // If only one logger, return it directly
            if (loggers.Count == 1)
            {
                return loggers[0];
            }
            
            // Otherwise return a composite logger
            return new CompositeLogger(loggers.ToArray());
        }

        /// <summary>
        /// Reset the default logger
        /// </summary>
        public static void ResetDefaultLogger()
        {
            lock (_lock)
            {
                if (_defaultLogger is IDisposable disposable)
                {
                    disposable.Dispose();
                }
                _defaultLogger = null;
            }
        }

        /// <summary>
        /// Set the default logger
        /// </summary>
        public static void SetDefaultLogger(ILogger logger)
        {
            lock (_lock)
            {
                if (_defaultLogger is IDisposable disposable)
                {
                    disposable.Dispose();
                }
                _defaultLogger = logger;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Parse log level from string
        /// </summary>
        private static LogLevel ParseLogLevel(string level)
        {
            return level switch
            {
                "Verbose" => LogLevel.Verbose,
                "Debug" => LogLevel.Debug,
                "Info" => LogLevel.Info,
                "Warning" => LogLevel.Warning,
                "Error" => LogLevel.Error,
                "Critical" => LogLevel.Critical,
                _ => LogLevel.Info
            };
        }

        #endregion
    }
}

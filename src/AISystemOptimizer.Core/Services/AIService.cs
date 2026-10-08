using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.AI;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.Services
{
    /// <summary>
    /// Service for AI-powered analysis and recommendations
    /// </summary>
    public class AIService : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private OllamaClient _ollamaClient;
        private OpenAiCompatibleClient _openAiCompatibleClient;
        private readonly object _clientLock = new object();
        private bool _disposed = false;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new AI service
        /// </summary>
        public AIService(ILogger logger = null, AppConfig config = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
        }

        #endregion

        #region Properties

        /// <summary>
        /// Whether AI is enabled
        /// </summary>
        public bool IsEnabled => _config.AiEnabled;

        /// <summary>
        /// Whether AI is available
        /// </summary>
        public bool IsAvailable => CheckAvailability();

        #endregion

        #region Public Methods

        /// <summary>
        /// Analyze a process using AI
        /// </summary>
        public string AnalyzeProcess(ProcessInfo process)
        {
            if (!IsEnabled || !IsAvailable)
                return string.Empty;
            
            try
            {
                _logger.Info("AIService", $"Analyzing process: {process.Name}");
                
                // Build the prompt
                var prompt = BuildProcessAnalysisPrompt(process);
                
                // Send to AI service
                var response = SendToAIService(prompt);
                
                // Parse the response
                var analysis = ParseProcessAnalysisResponse(response, process);
                
                _logger.Info("AIService", $"Process analysis completed: {process.Name}");
                
                return analysis;
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", 
                    $"Failed to analyze process: {process.Name}", null, ex);
                return string.Empty;
            }
        }

        /// <summary>
        /// Analyze the system using AI
        /// </summary>
        public string AnalyzeSystem(SystemInfo systemInfo)
        {
            if (!IsEnabled || !IsAvailable)
                return string.Empty;
            
            try
            {
                _logger.Info("AIService", "Analyzing system");
                
                // Build the prompt
                var prompt = BuildSystemAnalysisPrompt(systemInfo);
                
                // Send to AI service
                var response = SendToAIService(prompt);
                
                // Parse the response
                var analysis = ParseSystemAnalysisResponse(response, systemInfo);
                
                _logger.Info("AIService", "System analysis completed");
                
                return analysis;
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", "Failed to analyze system", null, ex);
                return string.Empty;
            }
        }

        /// <summary>
        /// Get optimization recommendations using AI
        /// </summary>
        public List<SystemInfo.OptimizationRecommendation> GetOptimizationRecommendations(SystemInfo systemInfo)
        {
            var recommendations = new List<SystemInfo.OptimizationRecommendation>();
            
            if (!IsEnabled || !IsAvailable)
                return recommendations;
            
            try
            {
                _logger.Info("AIService", "Getting optimization recommendations");
                
                // Build the prompt
                var prompt = BuildOptimizationPrompt(systemInfo);
                
                // Send to AI service
                var response = SendToAIService(prompt);
                
                // Parse the response
                recommendations = ParseOptimizationRecommendations(response, systemInfo);
                
                _logger.Info("AIService", 
                    $"Retrieved {recommendations.Count} optimization recommendations");
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", "Failed to get optimization recommendations", null, ex);
            }
            
            return recommendations;
        }

        /// <summary>
        /// Explain a process using AI
        /// </summary>
        public string ExplainProcess(ProcessInfo process)
        {
            if (!IsEnabled || !IsAvailable)
                return string.Empty;
            
            try
            {
                _logger.Info("AIService", $"Explaining process: {process.Name}");
                
                // Build a simple explanation prompt
                var prompt = $"Explain what the Windows process '{process.Name}' does in simple terms. " +
                           "Be concise and accurate. Only provide factual information.";
                
                // Send to AI service
                var response = SendToAIService(prompt);
                
                _logger.Info("AIService", $"Process explanation completed: {process.Name}");
                
                return response;
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", 
                    $"Failed to explain process: {process.Name}", null, ex);
                return string.Empty;
            }
        }

        /// <summary>
        /// Check if a process is safe to close using AI
        /// </summary>
        public bool IsSafeToClose(ProcessInfo process)
        {
            if (!IsEnabled || !IsAvailable)
                return false;
            
            try
            {
                _logger.Info("AIService", $"Checking if process is safe to close: {process.Name}");
                
                // Build the prompt
                var prompt = $"Is it safe to close the Windows process '{process.Name}'? " +
                           "Consider if it's a critical system process, if it's needed by applications, " +
                           "and if it will cause data loss or system instability. " +
                           "Respond with ONLY 'YES' or 'NO'.";
                
                // Send to AI service
                var response = SendToAIService(prompt);
                
                // Parse the response
                var isSafe = response.Trim().Equals("YES", StringComparison.OrdinalIgnoreCase);
                
                _logger.Info("AIService", 
                    $"Safe to close check completed: {process.Name} -> {isSafe}");
                
                return isSafe;
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", 
                    $"Failed to check if process is safe to close: {process.Name}", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Check AI availability
        /// </summary>
        public bool CheckAvailability()
        {
            if (!_config.AiEnabled)
                return false;
            
            try
            {
                // Check if the AI provider is available
                switch (_config.AiProvider.ToLower())
                {
                    case "ollama":
                        return CheckOllamaAvailability();
                    
                    case "local":
                    case "llama.cpp":
                        return CheckLocalAIAvailability();
                    
                    default:
                        return false;
                }
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", "Failed to check AI availability", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Test AI connection
        /// </summary>
        public async Task<bool> TestConnectionAsync()
        {
            if (!_config.AiEnabled)
                return false;
            
            try
            {
                // Test with a simple prompt
                var testPrompt = "Respond with ONLY the word 'OK' if you are working correctly.";
                var response = await SendToAIServiceAsync(testPrompt);
                
                return response.Trim().Equals("OK", StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", "Failed to test AI connection", null, ex);
                return false;
            }
        }

        /// <summary>
        /// Get AI model information
        /// </summary>
        public async Task<string> GetModelInfoAsync()
        {
            if (!IsEnabled || !IsAvailable)
                return string.Empty;
            
            try
            {
                switch (_config.AiProvider.ToLower())
                {
                    case "ollama":
                        var client = GetOllamaClient();
                        var serverInfo = await client.GetServerInfoAsync();
                        return $"Ollama {serverInfo.Version}";
                    
                    default:
                        return _config.AiModel;
                }
            }
            catch (Exception ex)
            {
                _logger.Error("AIService", "Failed to get model info", null, ex);
                return string.Empty;
            }
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Send a prompt to the AI service
        /// </summary>
        private string SendToAIService(string prompt, int timeoutSeconds = 30)
        {
            try
            {
                var task = SendToAIServiceAsync(prompt, timeoutSeconds);
                task.Wait(timeoutSeconds * 1000);
                return task.Result;
            }
            catch (AggregateException ae)
            {
                if (ae.InnerException is TimeoutException)
                    throw new TimeoutException("AI request timed out");
                throw ae.InnerException ?? ae;
            }
        }

        /// <summary>
        /// Ask the configured model one question and return its answer as text.
        ///
        /// Added for the Game &amp; App Optimizer, which needs a free-form prompt rather than one of the
        /// fixed analyses above. It uses the same provider selection, endpoint policy and timeout as every
        /// other call here: there is no second way to reach a model in this application.
        ///
        /// The answer is <b>text</b>. It is validated by the caller against a strict schema and turned into
        /// recommendations; nothing in this method interprets it, and an unavailable model returns an empty
        /// string rather than an invented answer.
        /// </summary>
        public async Task<string> AskAsync(string prompt)
        {
            if (string.IsNullOrWhiteSpace(prompt))
                return string.Empty;

            if (!IsEnabled)
            {
                _logger.Info("AIService", "The model was asked for a recommendation while AI is switched off.");
                return string.Empty;
            }

            if (!IsAvailable)
            {
                _logger.Info("AIService", "The model was asked for a recommendation but no model is available.");
                return string.Empty;
            }

            try
            {
                return await SendToAIServiceAsync(prompt, _config.AiRequestTimeout).ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                _logger.Warning("AIService", $"The model could not be asked: {exception.Message}");
                return string.Empty;
            }
        }

        /// <summary>
        /// Send a prompt to the AI service asynchronously
        /// </summary>
        private async Task<string> SendToAIServiceAsync(string prompt, int timeoutSeconds = 30)
        {
            using (var cts = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSeconds)))
            {
                switch (_config.AiProvider.ToLower())
                {
                    case "ollama":
                        var client = GetOllamaClient();
                        return await client.GenerateAsync(prompt, _config.AiModel, cancellationToken: cts.Token);
                    
                    case "local":
                    case "llamacpp":
                    case "llama.cpp":
                        // llama-server speaks the OpenAI-compatible chat API, which is a different
                        // endpoint and payload from Ollama's. Sending the request to Ollama instead -
                        // as an earlier build did - meant a user who configured llama.cpp was not
                        // actually running llama.cpp.
                        var openAiClient = GetOpenAiCompatibleClient();
                        return await openAiClient.GenerateAsync(
                            prompt, _config.AiModel, cancellationToken: cts.Token);
                    
                    default:
                        throw new InvalidOperationException("Unsupported AI provider");
                }
            }
        }

        /// <summary>
        /// Get or create the Ollama client
        /// </summary>
        private OllamaClient GetOllamaClient()
        {
            if (_ollamaClient == null)
            {
                lock (_clientLock)
                {
                    if (_ollamaClient == null)
                    {
                        _ollamaClient = new OllamaClient(_logger, _config);
                    }
                }
            }
            return _ollamaClient;
        }

        /// <summary>
        /// Get or create the OpenAI-compatible client used by the llama.cpp / local provider.
        /// </summary>
        private OpenAiCompatibleClient GetOpenAiCompatibleClient()
        {
            if (_openAiCompatibleClient == null)
            {
                lock (_clientLock)
                {
                    if (_openAiCompatibleClient == null)
                    {
                        _openAiCompatibleClient = new OpenAiCompatibleClient(_logger, _config);
                    }
                }
            }

            return _openAiCompatibleClient;
        }

        /// <summary>
        /// Check if Ollama is available
        /// </summary>
        private bool CheckOllamaAvailability()
        {
            try
            {
                var client = GetOllamaClient();
                return client.IsAvailable;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Check if local AI is available
        /// </summary>
        private bool CheckLocalAIAvailability()
        {
            // Ask the server the user actually configured. Reporting "AI available" because a
            // different server happened to be listening would be misleading.
            switch ((_config.AiProvider ?? string.Empty).Trim().ToLowerInvariant())
            {
                case "local":
                case "llamacpp":
                case "llama.cpp":
                    return CheckOpenAiCompatibleAvailability();

                case "ollama":
                default:
                    return CheckOllamaAvailability();
            }
        }

        /// <summary>
        /// True when the configured OpenAI-compatible server answers.
        /// </summary>
        private bool CheckOpenAiCompatibleAvailability()
        {
            try
            {
                return GetOpenAiCompatibleClient().CheckServerAvailability();
            }
            catch (Exception exception)
            {
                _logger.Info("AIService",
                    $"The local AI server could not be reached: {exception.Message}");
                return false;
            }
        }

        /// <summary>
        /// Build process analysis prompt
        /// </summary>
        private string BuildProcessAnalysisPrompt(ProcessInfo process)
        {
            var prompt = new StringBuilder();
            
            prompt.AppendLine("You are an expert Windows system analyst. Analyze the following process:");
            prompt.AppendLine();
            prompt.AppendLine($"Process Name: {process.Name}");
            prompt.AppendLine($"Display Name: {process.DisplayName}");
            prompt.AppendLine($"Path: {process.Path}");
            prompt.AppendLine($"Publisher: {process.Publisher}");
            prompt.AppendLine($"Description: {process.Description}");
            prompt.AppendLine($"Category: {process.Category}");
            prompt.AppendLine($"RAM Usage: {process.WorkingSetMB:F2} MB");
            prompt.AppendLine($"CPU Usage: {process.CpuUsage:F1}%");
            prompt.AppendLine($"Has Visible Window: {process.HasVisibleWindow}");
            prompt.AppendLine($"Is Service: {process.IsService}");
            prompt.AppendLine($"Is Windows Process: {process.IsWindowsProcess}");
            prompt.AppendLine($"Is Driver: {process.IsDriver}");
            prompt.AppendLine();
            
            prompt.AppendLine("Provide analysis in the following format:");
            prompt.AppendLine();
            prompt.AppendLine("1. What is this process?");
            prompt.AppendLine("2. What program or service does it belong to?");
            prompt.AppendLine("3. Is it a Windows system process?");
            prompt.AppendLine("4. Is it likely needed by the user?");
            prompt.AppendLine("5. Is it safe to terminate?");
            prompt.AppendLine("6. Will it restart automatically if terminated?");
            prompt.AppendLine("7. Does its RAM usage warrant optimization?");
            prompt.AppendLine();
            
            prompt.AppendLine("Respond in a clear, concise format. Be conservative with recommendations.");
            
            return prompt.ToString();
        }

        /// <summary>
        /// Build system analysis prompt
        /// </summary>
        private string BuildSystemAnalysisPrompt(SystemInfo systemInfo)
        {
            var prompt = new StringBuilder();
            
            prompt.AppendLine("You are an expert Windows system optimizer. Analyze the following system:");
            prompt.AppendLine();
            prompt.AppendLine($"OS: {systemInfo.OsName} {systemInfo.OsVersion} ({systemInfo.OsArchitecture})");
            prompt.AppendLine($"CPU: {systemInfo.CpuName} ({systemInfo.CpuCoreCount} cores)");
            prompt.AppendLine($"RAM: {systemInfo.TotalPhysicalMemoryGB:F2} GB ({systemInfo.RamUsagePercentage:F1}% used)");
            prompt.AppendLine($"GPU: {systemInfo.PrimaryGpu?.Name ?? "None"}");
            prompt.AppendLine();
            
            // Add top resource consumers
            var topProcesses = systemInfo.Processes
                .OrderByDescending(p => p.WorkingSet)
                .Take(5)
                .ToList();
            
            prompt.AppendLine("Top RAM Consumers:");
            foreach (var process in topProcesses)
            {
                prompt.AppendLine($"  - {process.DisplayName}: {process.WorkingSetMB:F2} MB");
            }
            prompt.AppendLine();
            
            prompt.AppendLine("Provide:");
            prompt.AppendLine("1. Overall system health assessment");
            prompt.AppendLine("2. Main performance bottlenecks");
            prompt.AppendLine("3. Optimization recommendations");
            prompt.AppendLine("4. Estimated improvement potential");
            prompt.AppendLine();
            
            prompt.AppendLine("Be concise and provide actionable recommendations.");
            
            return prompt.ToString();
        }

        /// <summary>
        /// Build optimization prompt
        /// </summary>
        private string BuildOptimizationPrompt(SystemInfo systemInfo)
        {
            var prompt = new StringBuilder();
            
            prompt.AppendLine("You are an expert Windows system optimizer. Based on the following system information,");
            prompt.AppendLine("provide specific, actionable optimization recommendations.");
            prompt.AppendLine();
            
            prompt.AppendLine($"System: {systemInfo.OsName} {systemInfo.OsVersion}");
            prompt.AppendLine($"RAM: {systemInfo.RamUsagePercentage:F1}% used ({systemInfo.UsedPhysicalMemoryGB:F2} GB / {systemInfo.TotalPhysicalMemoryGB:F2} GB)");
            prompt.AppendLine($"CPU: {systemInfo.CpuUsage:F1}% used");
            prompt.AppendLine($"Processes: {systemInfo.TotalProcessCount} running");
            prompt.AppendLine($"Startup Items: {systemInfo.StartupItems.Count} enabled");
            prompt.AppendLine($"Services: {systemInfo.Services.Count} running");
            prompt.AppendLine();
            
            // Add top resource consumers
            var topProcesses = systemInfo.Processes
                .Where(p => !CriticalProcesses.IsCritical(p.Name))
                .OrderByDescending(p => p.WorkingSet)
                .Take(5)
                .ToList();
            
            prompt.AppendLine("Top Resource Consumers (non-critical):");
            foreach (var process in topProcesses)
            {
                prompt.AppendLine($"  - {process.DisplayName}: RAM={process.WorkingSetMB:F2} MB, CPU={process.CpuUsage:F1}%");
            }
            prompt.AppendLine();
            
            // Add startup items
            var startupItems = systemInfo.StartupItems
                .Where(s => !s.IsWindowsItem)
                .OrderByDescending(s => s.EstimatedRamUsage)
                .Take(5)
                .ToList();
            
            prompt.AppendLine("Startup Items (non-Windows):");
            foreach (var item in startupItems)
            {
                prompt.AppendLine($"  - {item.Name}: RAM={item.EstimatedRamUsage / (1024.0 * 1024.0):F2} MB");
            }
            prompt.AppendLine();
            
            prompt.AppendLine("Provide recommendations in the following JSON format:");
            prompt.AppendLine("{");
            prompt.AppendLine("  \"recommendations\": [");
            prompt.AppendLine("    {");
            prompt.AppendLine("      \"type\": \"close_process\" or \"disable_startup\" or \"stop_service\" or \"general\",");
            prompt.AppendLine("      \"target\": \"process_name.exe\" or \"startup_item_name\" or \"service_name\",");
            prompt.AppendLine("      \"reason\": \"explanation of why this is recommended\",");
            prompt.AppendLine("      \"estimated_ram_recovery_mb\": 100,");
            prompt.AppendLine("      \"estimated_cpu_improvement_percent\": 5,");
            prompt.AppendLine("      \"risk_level\": \"low\" or \"medium\" or \"high\",");
            prompt.AppendLine("      \"priority\": 1-10");
            prompt.AppendLine("    }");
            prompt.AppendLine("  ],");
            prompt.AppendLine("  \"summary\": \"brief summary of optimization potential\"");
            prompt.AppendLine("}");
            
            return prompt.ToString();
        }

        /// <summary>
        /// Parse process analysis response
        /// </summary>
        private string ParseProcessAnalysisResponse(string response, ProcessInfo process)
        {
            try
            {
                // Try to parse as JSON first
                if (response.Trim().StartsWith("{") && response.Trim().EndsWith("}"))
                {
                    var json = JsonDocument.Parse(response);
                    var root = json.RootElement;
                    
                    var sb = new StringBuilder();
                    
                    if (root.TryGetProperty("explanation", out var explanation))
                        sb.AppendLine($"Explanation: {explanation.GetString()}");
                    
                    if (root.TryGetProperty("recommendation", out var recommendation))
                        sb.AppendLine($"Recommendation: {recommendation.GetString()}");
                    
                    if (sb.Length == 0)
                        return response; // Return raw response if we can't parse it
                    
                    return sb.ToString();
                }
                
                return response;
            }
            catch
            {
                return response;
            }
        }

        /// <summary>
        /// Parse system analysis response
        /// </summary>
        private string ParseSystemAnalysisResponse(string response, SystemInfo systemInfo)
        {
            if (string.IsNullOrWhiteSpace(response))
                return string.Empty;

            var trimmed = response.Trim();

            // The prompt asks for {"summary": "...", "confidence": 0.0}. When the model complies, the
            // summary is presented on its own so the user is not shown raw JSON. When it does not, the
            // text is shown as-is rather than discarded - a local model that answered in prose still
            // said something useful.
            if (!trimmed.StartsWith("{", StringComparison.Ordinal) ||
                !trimmed.EndsWith("}", StringComparison.Ordinal))
            {
                return trimmed;
            }

            try
            {
                using var document = System.Text.Json.JsonDocument.Parse(trimmed);

                var builder = new StringBuilder();

                if (document.RootElement.TryGetProperty("summary", out var summary) &&
                    summary.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    builder.Append(summary.GetString());
                }

                if (document.RootElement.TryGetProperty("confidence", out var confidence) &&
                    confidence.ValueKind == System.Text.Json.JsonValueKind.Number &&
                    confidence.TryGetDouble(out var value))
                {
                    if (builder.Length > 0)
                        builder.Append(' ');

                    builder.Append($"(model confidence: {Math.Clamp(value, 0d, 1d):P0})");
                }

                return builder.Length > 0 ? builder.ToString() : trimmed;
            }
            catch (System.Text.Json.JsonException)
            {
                // Not the JSON we asked for. Show what the model actually said.
                return trimmed;
            }
        }

        #endregion

        #region AI output parsing

        /// <summary>
        /// Parse optimization recommendations from an AI response.
        ///
        /// The parsing rules - strict allow-lists, range checks, target validation and treating model
        /// output as data rather than as a command - live in <see cref="AiRecommendationParser"/> so
        /// that they can be unit tested without a running model.
        /// </summary>
        private List<SystemInfo.OptimizationRecommendation> ParseOptimizationRecommendations(
            string response,
            SystemInfo systemInfo)
        {
            return _recommendationParser.Parse(response, systemInfo);
        }

        /// <summary>
        /// Strict parser for AI recommendations. Shared, stateless and testable.
        /// </summary>
        private static readonly AiRecommendationParser _recommendationParser = new AiRecommendationParser();

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the service
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
                    _ollamaClient?.Dispose();
                    _ollamaClient = null;

                    _openAiCompatibleClient?.Dispose();
                    _openAiCompatibleClient = null;
                }
                _disposed = true;
            }
        }

        /// <summary>
        /// Finalizer
        /// </summary>
        ~AIService()
        {
            Dispose(false);
        }

        #endregion
    }
}

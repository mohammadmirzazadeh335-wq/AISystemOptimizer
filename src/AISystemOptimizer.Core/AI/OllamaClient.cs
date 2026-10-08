using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.AI
{
    /// <summary>
    /// Client for communicating with Ollama API
    /// </summary>
    public class OllamaClient : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private HttpClient _httpClient;
        private readonly string _baseUrl;
        private readonly object _httpClientLock = new object();
        private bool _disposed = false;
        private readonly SemaphoreSlim _requestSemaphore;

        #endregion

        #region Constructors

        /// <summary>
        /// Create a new Ollama client
        /// </summary>
        public OllamaClient(ILogger logger = null, AppConfig config = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            var requested = _config.OllamaServerUrl ?? "http://localhost:11434";

            // Same rule as the OpenAI-compatible client: system information only goes somewhere this
            // application is willing to send it.
            if (!AiEndpointPolicy.IsPermitted(requested, _config.AllowRemoteAiServer))
            {
                var decision = AiEndpointPolicy.Evaluate(requested, _config.AllowRemoteAiServer);

                _logger.Warning("OllamaClient",
                    $"Refusing AI server address '{requested}'. {AiEndpointPolicy.Describe(decision)}");

                requested = "http://localhost:11434";
            }

            _baseUrl = requested;
            _requestSemaphore = new SemaphoreSlim(_config.MaxConcurrentAiRequests, _config.MaxConcurrentAiRequests);
        }

        #endregion

        #region Properties

        /// <summary>
        /// Whether the client is available
        /// </summary>
        public bool IsAvailable => CheckServerAvailability();

        /// <summary>
        /// Base URL of the Ollama server
        /// </summary>
        public string BaseUrl => _baseUrl;

        #endregion

        #region Public Methods

        /// <summary>
        /// Send a prompt to the Ollama API and get a response
        /// </summary>
        public async Task<string> GenerateAsync(
            string prompt,
            string model = null,
            float temperature = 0.7f,
            int maxTokens = 512,
            CancellationToken cancellationToken = default)
        {
            // Use semaphore to limit concurrent requests
            await _requestSemaphore.WaitAsync(cancellationToken);
            
            try
            {
                model = model ?? _config.AiModel ?? "llama3.2:3b";
                
                _logger.Info("OllamaClient", 
                    $"Generating response for model: {model}, prompt length: {prompt.Length}");
                
                // Build the request
                var request = new
                {
                    model = model,
                    prompt = prompt,
                    stream = false,
                    options = new
                    {
                        temperature = temperature,
                        num_predict = maxTokens
                    }
                };
                
                // Create HTTP client if needed
                if (_httpClient == null)
                {
                    lock (_httpClientLock)
                    {
                        if (_httpClient == null)
                        {
                            _httpClient = CreateHttpClient();
                        }
                    }
                }
                
                // Send the request
                var response = await _httpClient.PostAsync(
                    "/api/generate",
                    new StringContent(JsonSerializer.Serialize(request), Encoding.UTF8, "application/json"),
                    cancellationToken);
                
                // Check if the request was successful
                response.EnsureSuccessStatusCode();
                
                // Read and parse the response
                var responseContent = await response.Content.ReadAsStringAsync();
                var json = JsonDocument.Parse(responseContent);
                var root = json.RootElement;
                
                // Extract the response text
                if (root.TryGetProperty("response", out var responseProperty))
                {
                    var responseText = responseProperty.GetString();
                    
                    _logger.Info("OllamaClient", 
                        $"Generated response, length: {responseText.Length}");
                    
                    return responseText;
                }
                else
                {
                    _logger.Warning("OllamaClient", "No response in API response");
                    return string.Empty;
                }
            }
            catch (HttpRequestException ex)
            {
                _logger.Error("OllamaClient", "HTTP request failed", null, ex);
                throw new AIException("Failed to connect to Ollama server", ex);
            }
            catch (TaskCanceledException)
            {
                _logger.Warning("OllamaClient", "Request was cancelled");
                throw;
            }
            catch (Exception ex)
            {
                _logger.Error("OllamaClient", "Failed to generate response", null, ex);
                throw new AIException("Failed to generate response", ex);
            }
            finally
            {
                _requestSemaphore.Release();
            }
        }

        /// <summary>
        /// Stream a completion from Ollama (NDJSON chunks).
        /// The stream is parsed outside of a try/catch so that C# allows <c>yield return</c>;
        /// malformed chunks are skipped instead of aborting the stream.
        /// </summary>
        public async IAsyncEnumerable<string> GenerateStreamAsync(
            string? prompt,
            string? model = null,
            float temperature = 0.7f,
            int maxTokens = 512,
            [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(prompt))
                yield break;

            await _requestSemaphore.WaitAsync(cancellationToken);

            try
            {
                model ??= _config.AiModel;

                var request = new
                {
                    model,
                    prompt,
                    stream = true,
                    options = new
                    {
                        temperature,
                        num_predict = maxTokens
                    }
                };

                EnsureHttpClient();

                using var response = await _httpClient!.PostAsync(
                    "/api/generate",
                    new StringContent(JsonSerializer.Serialize(request), Encoding.UTF8, "application/json"),
                    cancellationToken);

                if (!response.IsSuccessStatusCode)
                    throw new AIException($"Ollama returned {(int)response.StatusCode} ({response.ReasonPhrase}).");

                using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                using var reader = new System.IO.StreamReader(stream);

                while (!reader.EndOfStream && !cancellationToken.IsCancellationRequested)
                {
                    var line = await reader.ReadLineAsync();
                    if (string.IsNullOrWhiteSpace(line))
                        continue;

                    if (TryParseStreamChunk(line, out var chunk) && chunk.Length > 0)
                        yield return chunk;
                }
            }
            finally
            {
                _requestSemaphore.Release();
            }
        }

        /// <summary>
        /// Parse one NDJSON line from the streaming endpoint. Never throws.
        /// </summary>
        private static bool TryParseStreamChunk(string line, out string chunk)
        {
            chunk = string.Empty;

            try
            {
                using var json = JsonDocument.Parse(line);
                var root = json.RootElement;

                if (root.TryGetProperty("response", out var responseProperty))
                {
                    chunk = responseProperty.GetString() ?? string.Empty;
                    return true;
                }
            }
            catch (JsonException)
            {
                // Ignore malformed lines: streaming must stay resilient.
            }
            catch (ObjectDisposedException)
            {
            }

            return false;
        }

        /// <summary>
        /// Lazily create the shared HttpClient (thread safe).
        /// </summary>
        private void EnsureHttpClient()
        {
            if (_httpClient != null) return;

            lock (_httpClientLock)
            {
                _httpClient ??= CreateHttpClient();
            }
        }


        /// <summary>
        /// List available models on the Ollama server
        /// </summary>
        public async Task<List<string>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            var models = new List<string>();
            
            try
            {
                // Create HTTP client if needed
                if (_httpClient == null)
                {
                    lock (_httpClientLock)
                    {
                        if (_httpClient == null)
                        {
                            _httpClient = CreateHttpClient();
                        }
                    }
                }
                
                // Send the request
                var response = await _httpClient.GetAsync("/api/tags", cancellationToken);
                
                // Check if the request was successful
                response.EnsureSuccessStatusCode();
                
                // Read and parse the response
                var responseContent = await response.Content.ReadAsStringAsync();
                var json = JsonDocument.Parse(responseContent);
                var root = json.RootElement;
                
                if (root.TryGetProperty("models", out var modelsProperty) &&
                    modelsProperty.ValueKind == JsonValueKind.Array)
                {
                    foreach (var model in modelsProperty.EnumerateArray())
                    {
                        if (model.TryGetProperty("name", out var nameProperty))
                        {
                            models.Add(nameProperty.GetString());
                        }
                    }
                }
                
                _logger.Info("OllamaClient", $"Found {models.Count} models on server");
            }
            catch (HttpRequestException ex)
            {
                _logger.Error("OllamaClient", "Failed to list models", null, ex);
                throw new AIException("Failed to connect to Ollama server", ex);
            }
            catch (Exception ex)
            {
                _logger.Error("OllamaClient", "Failed to list models", null, ex);
                throw new AIException("Failed to list models", ex);
            }
            
            return models;
        }

        /// <summary>
        /// Check if the Ollama server is available
        /// </summary>
        public bool CheckServerAvailability()
        {
            try
            {
                // Create HTTP client if needed
                if (_httpClient == null)
                {
                    lock (_httpClientLock)
                    {
                        if (_httpClient == null)
                        {
                            _httpClient = CreateHttpClient();
                        }
                    }
                }
                
                // Try to get the server status
                var response = _httpClient.GetAsync("/api/tags").Result;
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Test the connection to the Ollama server
        /// </summary>
        public async Task<bool> TestConnectionAsync(CancellationToken cancellationToken = default)
        {
            try
            {
                // Create HTTP client if needed
                if (_httpClient == null)
                {
                    lock (_httpClientLock)
                    {
                        if (_httpClient == null)
                        {
                            _httpClient = CreateHttpClient();
                        }
                    }
                }
                
                // Try a simple request
                var response = await _httpClient.GetAsync("/api/tags", cancellationToken);
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Get server information
        /// </summary>
        public async Task<OllamaServerInfo> GetServerInfoAsync(CancellationToken cancellationToken = default)
        {
            try
            {
                // Create HTTP client if needed
                if (_httpClient == null)
                {
                    lock (_httpClientLock)
                    {
                        if (_httpClient == null)
                        {
                            _httpClient = CreateHttpClient();
                        }
                    }
                }
                
                // Try to get the server version
                var response = await _httpClient.GetAsync("/api/version", cancellationToken);
                
                if (response.IsSuccessStatusCode)
                {
                    var responseContent = await response.Content.ReadAsStringAsync();
                    var json = JsonDocument.Parse(responseContent);
                    var root = json.RootElement;
                    
                    var info = new OllamaServerInfo();
                    
                    if (root.TryGetProperty("version", out var versionProperty))
                        info.Version = versionProperty.GetString();
                    
                    return info;
                }
            }
            catch (Exception ex)
            {
                _logger.Error("OllamaClient", "Failed to get server info", null, ex);
            }
            
            return new OllamaServerInfo();
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Create an HTTP client for the Ollama API
        /// </summary>
        private HttpClient CreateHttpClient()
        {
            var handler = new HttpClientHandler();
            
            // Configure for local development (ignore SSL errors)
            if (_baseUrl.StartsWith("http://localhost") || 
                _baseUrl.StartsWith("http://127.0.0.1"))
            {
                handler.ServerCertificateCustomValidationCallback = 
                    (message, cert, chain, errors) => true;
            }
            
            var client = new HttpClient(handler);
            client.BaseAddress = new Uri(_baseUrl);
            client.Timeout = TimeSpan.FromSeconds(_config.AiRequestTimeout);
            client.DefaultRequestHeaders.Add("Accept", "application/json");
            client.DefaultRequestHeaders.Add("Content-Type", "application/json");
            
            return client;
        }

        #endregion

        #region IDisposable Implementation

        /// <summary>
        /// Dispose the client
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
                    _httpClient?.Dispose();
                    _httpClient = null;
                    _requestSemaphore?.Dispose();
                }
                _disposed = true;
            }
        }

        /// <summary>
        /// Finalizer
        /// </summary>
        ~OllamaClient()
        {
            Dispose(false);
        }

        #endregion
    }

    /// <summary>
    /// Ollama server information
    /// </summary>
    public class OllamaServerInfo
    {
        /// <summary>
        /// Server version
        /// </summary>
        public string Version { get; set; } = string.Empty;

        /// <summary>
        /// Whether the server is available
        /// </summary>
        public bool IsAvailable => !string.IsNullOrEmpty(Version);
    }

    /// <summary>
    /// AI exception
    /// </summary>
    public class AIException : Exception
    {
        /// <summary>
        /// Create a new AI exception
        /// </summary>
        public AIException(string message, Exception innerException = null)
            : base(message, innerException)
        {
        }
    }
}

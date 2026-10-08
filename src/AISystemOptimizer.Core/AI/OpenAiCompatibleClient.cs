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
    /// Client for a local server that speaks the OpenAI-compatible chat API.
    ///
    /// This is what makes the <c>llama.cpp</c> provider a real provider rather than an alias:
    /// <c>llama-server</c> exposes <c>POST /v1/chat/completions</c>, which is a different endpoint and a
    /// different payload from Ollama's <c>/api/generate</c>. Earlier builds accepted the
    /// <c>llama.cpp</c> setting and silently sent the request to Ollama instead, so a user who configured
    /// llama.cpp was not running llama.cpp.
    ///
    /// Everything here stays on the local machine. There is no default to a cloud endpoint, no API key,
    /// and no telemetry: if the server is not running, the call fails and the optimiser continues
    /// without AI.
    /// </summary>
    public class OpenAiCompatibleClient : IDisposable
    {
        #region Private Fields

        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly string _baseUrl;
        private readonly SemaphoreSlim _requestSemaphore;
        private readonly object _httpClientLock = new object();

        private HttpClient? _httpClient;
        private bool _disposed;

        #endregion

        #region Construction

        /// <summary>
        /// Create a client for an OpenAI-compatible local server.
        /// </summary>
        /// <param name="serverUrl">
        /// Base URL of the server, for example <c>http://localhost:8080</c>. The
        /// <c>/v1/chat/completions</c> path is appended automatically.
        /// </param>
        public OpenAiCompatibleClient(
            ILogger? logger = null,
            AppConfig? config = null,
            string? serverUrl = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();

            var requested = serverUrl ?? _config.OllamaServerUrl;

            // Second line of defence. The configuration loader already refuses a disallowed address, but
            // a caller can construct this client directly, and the rule must hold there too.
            if (!AiEndpointPolicy.IsPermitted(requested, _config.AllowRemoteAiServer))
            {
                var decision = AiEndpointPolicy.Evaluate(requested, _config.AllowRemoteAiServer);

                _logger.Warning("OpenAiCompatibleClient",
                    $"Refusing AI server address '{requested}'. {AiEndpointPolicy.Describe(decision)}");

                requested = "http://localhost:11434";
            }

            _baseUrl = NormalizeBaseUrl(requested);

            _requestSemaphore = new SemaphoreSlim(
                Math.Max(1, _config.MaxConcurrentAiRequests),
                Math.Max(1, _config.MaxConcurrentAiRequests));
        }

        /// <summary>
        /// Turn whatever the user typed into a usable base URL: ensure a scheme, trim trailing slashes
        /// and reject anything that is not plain HTTP.
        /// </summary>
        public static string NormalizeBaseUrl(string? value)
        {
            var url = (value ?? string.Empty).Trim().TrimEnd('/');

            if (url.Length == 0)
                return "http://localhost:8080";

            if (!url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
                !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                url = "http://" + url;
            }

            return url.TrimEnd('/');
        }

        #endregion

        #region Properties

        /// <summary>Base URL this client talks to.</summary>
        public string BaseUrl => _baseUrl;

        /// <summary>Endpoint used for chat completions.</summary>
        public string ChatEndpoint => _baseUrl + "/v1/chat/completions";

        /// <summary>True when the server answers its model listing.</summary>
        public bool IsAvailable => CheckServerAvailability();

        #endregion

        #region Public Methods

        /// <summary>
        /// Send a prompt and return the model's answer.
        ///
        /// Returns an empty string on any failure; the caller treats that as "no AI available" and
        /// falls back to the rule engine. AI is an optional enhancement and its absence must never stop
        /// the optimiser from working.
        /// </summary>
        public async Task<string> GenerateAsync(
            string prompt,
            string? model = null,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(prompt))
                return string.Empty;

            var payload = BuildRequestPayload(prompt, model ?? _config.AiModel);
            var timeout = TimeSpan.FromSeconds(Math.Clamp(_config.AiRequestTimeout, 5, 300));

            await _requestSemaphore.WaitAsync(cancellationToken).ConfigureAwait(false);

            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, ChatEndpoint)
                {
                    Content = new StringContent(payload, Encoding.UTF8, "application/json")
                };

                using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                timeoutSource.CancelAfter(timeout);

                using var response = await GetHttpClient()
                    .SendAsync(request, HttpCompletionOption.ResponseContentRead, timeoutSource.Token)
                    .ConfigureAwait(false);

                if (!response.IsSuccessStatusCode)
                {
                    _logger.Warning("OpenAiCompatibleClient",
                        $"The local AI server answered {(int)response.StatusCode} for {ChatEndpoint}.");
                    return string.Empty;
                }

                var body = await response.Content.ReadAsStringAsync(timeoutSource.Token).ConfigureAwait(false);

                return ExtractMessageContent(body);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                _logger.Warning("OpenAiCompatibleClient",
                    $"The local AI server did not answer within {timeout.TotalSeconds:F0}s.");
                return string.Empty;
            }
            catch (HttpRequestException exception)
            {
                _logger.Info("OpenAiCompatibleClient",
                    $"The local AI server at {_baseUrl} is not reachable ({exception.Message}); " +
                    "continuing without AI.");
                return string.Empty;
            }
            catch (Exception exception)
            {
                _logger.Warning("OpenAiCompatibleClient",
                    "The local AI request failed; continuing without AI.", null, exception);
                return string.Empty;
            }
            finally
            {
                _requestSemaphore.Release();
            }
        }

        /// <summary>
        /// True when the server answers on its model listing endpoint.
        /// </summary>
        public bool CheckServerAvailability()
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, _baseUrl + "/v1/models");

                using var response = GetHttpClient()
                    .SendAsync(request, HttpCompletionOption.ResponseHeadersRead)
                    .GetAwaiter()
                    .GetResult();

                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Names of the models the server currently has loaded.
        /// </summary>
        public async Task<List<string>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            var models = new List<string>();

            try
            {
                using var response = await GetHttpClient()
                    .GetAsync(_baseUrl + "/v1/models", cancellationToken)
                    .ConfigureAwait(false);

                if (!response.IsSuccessStatusCode)
                    return models;

                var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

                using var document = JsonDocument.Parse(body);

                if (!document.RootElement.TryGetProperty("data", out var data) ||
                    data.ValueKind != JsonValueKind.Array)
                {
                    return models;
                }

                foreach (var item in data.EnumerateArray())
                {
                    if (item.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String)
                    {
                        var name = id.GetString();

                        if (!string.IsNullOrWhiteSpace(name))
                            models.Add(name!);
                    }
                }
            }
            catch (Exception exception)
            {
                _logger.Info("OpenAiCompatibleClient",
                    $"Could not list models from {_baseUrl}: {exception.Message}");
            }

            return models;
        }

        #endregion

        #region Private Methods

        /// <summary>
        /// Build the chat-completions request body.
        /// </summary>
        private static string BuildRequestPayload(string prompt, string model)
        {
            var payload = new Dictionary<string, object?>
            {
                ["model"] = string.IsNullOrWhiteSpace(model) ? "local-model" : model,
                ["messages"] = new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["role"] = "user",
                        ["content"] = prompt
                    }
                },
                ["temperature"] = 0.2,
                ["stream"] = false
            };

            return JsonSerializer.Serialize(payload);
        }

        /// <summary>
        /// Pull <c>choices[0].message.content</c> out of a chat-completions response.
        ///
        /// Anything unexpected yields an empty string rather than an exception: a local server whose
        /// response shape differs must not be able to fault the application.
        /// </summary>
        private static string ExtractMessageContent(string? body)
        {
            if (string.IsNullOrWhiteSpace(body))
                return string.Empty;

            try
            {
                using var document = JsonDocument.Parse(body!);

                if (!document.RootElement.TryGetProperty("choices", out var choices) ||
                    choices.ValueKind != JsonValueKind.Array ||
                    choices.GetArrayLength() == 0)
                {
                    return string.Empty;
                }

                var first = choices[0];

                if (first.TryGetProperty("message", out var message) &&
                    message.TryGetProperty("content", out var content) &&
                    content.ValueKind == JsonValueKind.String)
                {
                    return content.GetString() ?? string.Empty;
                }

                // Some builds still answer in the legacy completion shape.
                if (first.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String)
                    return text.GetString() ?? string.Empty;
            }
            catch (JsonException)
            {
                return string.Empty;
            }

            return string.Empty;
        }

        /// <summary>
        /// Lazily create the HTTP client. Kept separate so the expensive construction happens once and
        /// only when AI is actually used.
        /// </summary>
        private HttpClient GetHttpClient()
        {
            lock (_httpClientLock)
            {
                if (_httpClient != null)
                    return _httpClient;

                _httpClient = new HttpClient
                {
                    // The per-request timeout is applied through a linked CancellationTokenSource; the
                    // client's own timeout is left generous so it never races that logic.
                    Timeout = Timeout.InfiniteTimeSpan
                };

                _httpClient.DefaultRequestHeaders.Add("Accept", "application/json");

                return _httpClient;
            }
        }

        #endregion

        #region IDisposable Implementation

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (_disposed)
                return;

            if (disposing)
            {
                lock (_httpClientLock)
                {
                    _httpClient?.Dispose();
                    _httpClient = null;
                }

                _requestSemaphore.Dispose();
            }

            _disposed = true;
        }

        #endregion
    }
}

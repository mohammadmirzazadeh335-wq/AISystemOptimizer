using System;
using System.Linq;
using System.Net;

namespace AISystemOptimizer.Core.AI
{
    /// <summary>
    /// Decides which addresses the application is willing to send system information to.
    ///
    /// WHY THIS EXISTS
    /// The application describes itself as local-only AI: no cloud dependency, no API key, nothing
    /// leaves the machine. That promise was only a default, not an enforced rule - the server URL was a
    /// free-text string that was passed to the HTTP client unchecked. A configuration file could
    /// therefore point it at any host on the internet, and the process inventory, service list and
    /// start-up items sent as prompt context would have gone there. On a tool that reads the user's
    /// entire process table, "we only do this locally" has to be a constraint the code enforces, not a
    /// sentence in a README.
    ///
    /// THE RULE
    ///   * Loopback is always allowed. That is the shape every supported local runtime uses.
    ///   * A private network address is allowed only when the user has explicitly opted in. Running a
    ///     model server on another machine in the same home network is a real scenario, but it is a
    ///     deliberate choice and it must be made deliberately, in writing, in the configuration file.
    ///   * Everything else - any public address, any address that cannot be resolved, anything that
    ///     hides behind a redirect - is refused.
    /// </summary>
    public static class AiEndpointPolicy
    {
        /// <summary>
        /// Outcome of evaluating a configured AI server address.
        /// </summary>
        public enum Decision
        {
            /// <summary>A loopback address. Always permitted.</summary>
            LocalPermitted,

            /// <summary>A private-network address that the user has explicitly allowed.</summary>
            PrivateNetworkPermitted,

            /// <summary>A private-network address, but the opt-in setting is off.</summary>
            PrivateNetworkNotOptedIn,

            /// <summary>A public or otherwise disallowed address.</summary>
            Rejected
        }

        /// <summary>
        /// Evaluate an address against the policy.
        /// </summary>
        /// <param name="serverUrl">The configured base URL.</param>
        /// <param name="allowPrivateNetwork">
        /// True only when the user has turned on <c>allowRemoteAiServer</c> in the configuration.
        /// </param>
        public static Decision Evaluate(string? serverUrl, bool allowPrivateNetwork)
        {
            if (string.IsNullOrWhiteSpace(serverUrl))
                return Decision.LocalPermitted; // An empty value means "the default", which is loopback.

            if (!Uri.TryCreate(NormalizeForParsing(serverUrl), UriKind.Absolute, out var uri))
                return Decision.Rejected;

            if (!uri.Scheme.Equals(Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
                !uri.Scheme.Equals(Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
            {
                // file://, ftp://, and anything else the HTTP client would not handle the way the user
                // expects. There is no reason for an AI endpoint to use any other scheme.
                return Decision.Rejected;
            }

            if (IsLoopback(uri))
                return Decision.LocalPermitted;

            if (IsPrivateNetwork(uri.Host))
                return allowPrivateNetwork
                    ? Decision.PrivateNetworkPermitted
                    : Decision.PrivateNetworkNotOptedIn;

            return Decision.Rejected;
        }

        /// <summary>
        /// True when the address may be used as configured.
        /// </summary>
        public static bool IsPermitted(string? serverUrl, bool allowPrivateNetwork)
        {
            var decision = Evaluate(serverUrl, allowPrivateNetwork);

            return decision == Decision.LocalPermitted ||
                   decision == Decision.PrivateNetworkPermitted;
        }

        /// <summary>
        /// A short explanation suitable for a log line or a settings screen.
        /// </summary>
        public static string Describe(Decision decision) => decision switch
        {
            Decision.LocalPermitted =>
                "The address is on this machine. Permitted.",

            Decision.PrivateNetworkPermitted =>
                "The address is on the local network and remote AI servers have been allowed in the " +
                "configuration. Permitted.",

            Decision.PrivateNetworkNotOptedIn =>
                "The address is on the local network. Set \"allowRemoteAiServer\": true in config.json " +
                "if the AI server really runs on another machine, otherwise it will not be used.",

            _ =>
                "The address is not on this machine or on the local network. This application sends " +
                "your process and service list to its AI server, so it will only talk to a local one. " +
                "The address was refused."
        };

        /// <summary>
        /// True for a loopback host, including the literal names Windows and Unix resolve locally.
        /// </summary>
        private static bool IsLoopback(Uri uri)
        {
            if (uri.IsLoopback)
                return true;

            var host = StripBrackets(uri.Host);

            if (host.Equals("localhost", StringComparison.OrdinalIgnoreCase))
                return true;

            if (host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase))
                return true;

            // 0.0.0.0 and :: mean "all interfaces" for a server; a client connecting to them is
            // connecting to this machine.
            if (host == "0.0.0.0" || host == "::" || host == "[::]")
                return true;

            return IPAddress.TryParse(host, out var address) && IPAddress.IsLoopback(address);
        }

        /// <summary>
        /// True for the private ranges that RFC 1918 and RFC 4193 reserve for local networks.
        /// </summary>
        private static bool IsPrivateNetwork(string host)
        {
            host = StripBrackets(host);

            // A single-label hostname such as "workstation" can only resolve on the local network -
            // unless it is a scheme name that leaked through, which the parser now prevents.
            if (!host.Contains(".", StringComparison.Ordinal) && !IPAddress.TryParse(host, out _))
                return true;

            // A scheme name is never a host.
            if (host.Equals("ftp", StringComparison.OrdinalIgnoreCase) ||
                host.Equals("file", StringComparison.OrdinalIgnoreCase) ||
                host.Equals("ssh", StringComparison.OrdinalIgnoreCase) ||
                host.Equals("telnet", StringComparison.OrdinalIgnoreCase) ||
                host.Equals("gopher", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (host.EndsWith(".local", StringComparison.OrdinalIgnoreCase) ||
                host.EndsWith(".lan", StringComparison.OrdinalIgnoreCase) ||
                host.EndsWith(".internal", StringComparison.OrdinalIgnoreCase) ||
                host.EndsWith(".home", StringComparison.OrdinalIgnoreCase) ||
                host.EndsWith(".home.arpa", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!IPAddress.TryParse(host, out var address))
            {
                // A fully qualified public-looking name. Not a local network address.
                return false;
            }

            if (address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
            {
                var octets = address.GetAddressBytes();

                return octets[0] == 10 ||
                       (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
                       (octets[0] == 192 && octets[1] == 168) ||
                       (octets[0] == 169 && octets[1] == 254); // link-local
            }

            if (address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6)
            {
                // fc00::/7 unique-local, and fe80::/10 link-local.
                var bytes = address.GetAddressBytes();

                return (bytes[0] & 0xFE) == 0xFC ||
                       (bytes[0] == 0xFE && (bytes[1] & 0xC0) == 0x80);
            }

            return false;
        }

        private static string StripBrackets(string host)
        {
            if (string.IsNullOrEmpty(host))
                return string.Empty;

            return host.StartsWith("[", StringComparison.Ordinal) && host.EndsWith("]", StringComparison.Ordinal)
                ? host[1..^1]
                : host;
        }

        private static string NormalizeForParsing(string value)
        {
            var trimmed = value.Trim();

            // Only prepend a scheme when the value carries no scheme at all. Doing it unconditionally
            // turns "ftp://example.com" into "http://ftp://example.com", whose host is the single-label
            // name "ftp" - which the private-network rule then accepts. That is how a disallowed scheme
            // slipped through on the first attempt.
            var schemeSeparator = trimmed.IndexOf("://", StringComparison.Ordinal);

            if (schemeSeparator >= 0)
                return trimmed;

            return "http://" + trimmed;
        }
    }
}

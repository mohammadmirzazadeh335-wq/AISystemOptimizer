using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>Anything that can open a TCP connection to a host on behalf of the game or a test.</summary>
    public interface IConnector
    {
        Socket Connect(string host, int port);
        /// <summary>Short label for logs and reports ("direct", "socks5 127.0.0.1:1080", …).</summary>
        string Describe { get; }
    }

    /// <summary>Opens connections through an HTTP proxy using the CONNECT method.</summary>
    public sealed class HttpProxyClient : IConnector
    {
        public string Host = "127.0.0.1";
        public int Port = 8080;
        public string User = "";
        public string Password = "";
        public int TimeoutMs = 6000;

        public HttpProxyClient() { }

        public HttpProxyClient(string host, int port, string user, string password, int timeoutMs)
        {
            Host = host;
            Port = port;
            User = user ?? "";
            Password = password ?? "";
            TimeoutMs = timeoutMs;
        }

        public string Describe { get { return "http " + Host + ":" + Port; } }

        public Socket Connect(string targetHost, int targetPort)
        {
            IPAddress proxyIp;
            if (!IPAddress.TryParse(Host, out proxyIp))
            {
                var resolved = NetUtil.ResolveSimple(Host);
                if (resolved.Count == 0) throw new Exception("proxy host does not resolve: " + Host);
                if (!IPAddress.TryParse(resolved[0], out proxyIp)) throw new Exception("bad proxy address");
            }

            var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                socket.NoDelay = true;
                socket.ReceiveTimeout = TimeoutMs;
                socket.SendTimeout = TimeoutMs;
                IAsyncResult ar = socket.BeginConnect(proxyIp, Port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(TimeoutMs)) throw new Exception("proxy connect timeout");
                socket.EndConnect(ar);

                var request = new StringBuilder();
                request.Append("CONNECT ").Append(targetHost).Append(':').Append(targetPort).Append(" HTTP/1.1\r\n");
                request.Append("Host: ").Append(targetHost).Append(':').Append(targetPort).Append("\r\n");
                if (!string.IsNullOrEmpty(User))
                {
                    string token = Convert.ToBase64String(Encoding.UTF8.GetBytes(User + ":" + Password));
                    request.Append("Proxy-Authorization: Basic ").Append(token).Append("\r\n");
                }
                request.Append("Proxy-Connection: keep-alive\r\n");
                request.Append("User-Agent: ServerHelp/1.0\r\n\r\n");

                byte[] payload = Encoding.ASCII.GetBytes(request.ToString());
                socket.Send(payload);

                string statusLine = ReadLine(socket);
                if (statusLine.Length == 0) throw new Exception("the proxy closed the connection");
                int code = ParseStatusCode(statusLine);
                // drain the rest of the response headers
                string line;
                int guard = 0;
                do { line = ReadLine(socket); guard++; } while (line.Length > 0 && guard < 64);

                if (code != 200)
                    throw new Exception("proxy refused CONNECT (" + statusLine.Trim() + ")");
                return socket;
            }
            catch
            {
                try { socket.Close(); } catch { }
                throw;
            }
        }

        private static int ParseStatusCode(string statusLine)
        {
            int firstSpace = statusLine.IndexOf(' ');
            if (firstSpace < 0) return -1;
            int value = 0;
            for (int i = firstSpace + 1; i < statusLine.Length && i < firstSpace + 4; i++)
            {
                char c = statusLine[i];
                if (c < '0' || c > '9') break;
                value = value * 10 + (c - '0');
            }
            return value;
        }

        /// <summary>Reads one header line, tolerating a CRLF-free proxy.</summary>
        public static string ReadLine(Socket socket)
        {
            var buffer = new List<byte>();
            var one = new byte[1];
            while (buffer.Count < 4096)
            {
                int read = socket.Receive(one, 0, 1, SocketFlags.None);
                if (read <= 0) break;
                if (one[0] == (byte)'\n') break;
                if (one[0] != (byte)'\r') buffer.Add(one[0]);
            }
            return Encoding.ASCII.GetString(buffer.ToArray());
        }
    }

    /// <summary>Result of probing a Telegram MTProto proxy with the real protocol.</summary>
    public sealed class MtprotoResult
    {
        public bool Ok;                 // verified end to end: the proxy answered req_pq with our nonce echoed
        public bool Connected;          // the TCP connection worked, so there is a delay to report
        public bool Handshake;          // the proxy accepted our obfuscated2/fake-TLS handshake (secret is right)
        public int DelayMs = -1;        // the honest delay: req_pq -> resPQ, or the handshake when that failed
        public string Detail = "";
        public string Status = "";
        public string Mode = "";        // "fake-TLS", "secured (dd)", "classic obfuscated2"
        public string Domain = "";
        public int Dc = 2;
    }

    /// <summary>
    /// Checks a Telegram MTProto proxy by speaking the real protocol: obfuscated2 handshake
    /// (classic, <c>dd</c> secured or <c>ee</c> fake-TLS) followed by one unauthenticated
    /// <c>req_pq_multi</c> / <c>resPQ</c> round trip. That proves the proxy works, proves the
    /// secret is right and gives a real delay - a TCP probe cannot tell any of that.
    /// The implementation lives in <see cref="MtprotoClient"/>.
    /// </summary>
    public static class MtprotoProbe
    {
        public static MtprotoResult Test(string host, int port, string secret, int timeoutMs)
        {
            return Test(host, port, secret, 2, timeoutMs);
        }

        public static MtprotoResult Test(string host, int port, string secret, int dc, int timeoutMs)
        {
            var result = new MtprotoResult();
            if (string.IsNullOrEmpty(host) || port <= 0)
            {
                result.Detail = L.T("آدرس پروکسی ناقص است", "the proxy address is incomplete");
                return result;
            }

            MtprotoCheck check = MtprotoClient.Check(host, port, secret, dc, timeoutMs);
            result.Connected = check.Connected;
            result.Handshake = check.Verified || check.ServerDigestOk || (check.Connected && check.Mode == MtprotoMode.Classic);
            result.Ok = check.Verified;
            result.DelayMs = check.DelayMs;
            result.Status = check.Status;
            result.Detail = check.Detail;
            result.Mode = check.Mode == MtprotoMode.FakeTls
                ? "fake-TLS"
                : (check.Mode == MtprotoMode.Secured ? "secured (dd)" : "classic obfuscated2");
            result.Domain = check.Domain;
            result.Dc = check.Dc;

            if (result.Ok)
            {
                result.Detail = L.T("پروکسی تأیید شد — resPQ از دیتاسنتر ", "the proxy is verified - resPQ from DC ") +
                                L.N(result.Dc) + " • " + result.Detail;
            }
            else if (result.Handshake)
            {
                result.Detail = L.T("هندشیک سالم بود ولی تلگرام جواب نداد. ", "the handshake was fine but Telegram did not answer. ") +
                                result.Detail;
            }
            return result;
        }
    }
}

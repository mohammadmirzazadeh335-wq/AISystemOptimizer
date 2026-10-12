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

    /// <summary>Result of probing a Telegram MTProto proxy.</summary>
    public sealed class MtprotoResult
    {
        public bool Ok;                 // the TCP connection worked, so a delay exists
        public bool Handshake;          // the proxy answered the obfuscated probe
        public int DelayMs = -1;
        public string Detail = "";
    }

    /// <summary>
    /// Checks a Telegram MTProto proxy without logging in to Telegram: connect, send 64 random
    /// bytes (the obfuscated protocol header) and see whether the proxy answers. Secrets starting
    /// with "dd"/"ee" use the fake-TLS mode, which only answers a full TLS handshake, so those are
    /// reported with the TCP delay and a note instead of a false negative.
    /// </summary>
    public static class MtprotoProbe
    {
        public static MtprotoResult Test(string host, int port, string secret, int timeoutMs)
        {
            var result = new MtprotoResult();
            if (string.IsNullOrEmpty(host) || port <= 0)
            {
                result.Detail = L.T("آدرس پروکسی ناقص است", "the proxy address is incomplete");
                return result;
            }

            long start = DateTime.UtcNow.Ticks;
            Socket socket = null;
            try
            {
                socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
                socket.NoDelay = true;
                socket.ReceiveTimeout = timeoutMs;
                socket.SendTimeout = timeoutMs;

                IPAddress address;
                IAsyncResult ar;
                if (IPAddress.TryParse(host, out address))
                {
                    ar = socket.BeginConnect(address, port, null, null);
                }
                else
                {
                    ar = socket.BeginConnect(host, port, null, null);
                }
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                {
                    try { socket.Close(); } catch { }
                    result.Detail = L.T("اتصال برقرار نشد (timeout)", "could not connect (timeout)");
                    return result;
                }
                socket.EndConnect(ar);
                result.Ok = true;

                var random = new Random();
                var probe = new byte[64];
                random.NextBytes(probe);
                socket.Send(probe);

                var buffer = new byte[4];
                bool answered = false;
                try
                {
                    socket.ReceiveTimeout = Math.Max(700, timeoutMs / 2);
                    int read = socket.Receive(buffer);
                    answered = read > 0;
                }
                catch (SocketException se)
                {
                    if (se.SocketErrorCode == SocketError.ConnectionReset) answered = false;
                    else if (se.SocketErrorCode != SocketError.TimedOut) throw;
                }

                result.Handshake = answered;
                bool fakeTls = !string.IsNullOrEmpty(secret) &&
                               (secret.StartsWith("dd", StringComparison.OrdinalIgnoreCase) ||
                                secret.StartsWith("ee", StringComparison.OrdinalIgnoreCase));
                if (answered)
                    result.Detail = L.T("پروکسی MTProto پاسخ داد (هندشیک سالم)", "the MTProto proxy answered the handshake, so it is alive");
                else if (fakeTls)
                    result.Detail = L.T("حالت fake-TLS: بدون هندشیک کامل TLS پاسخ نمی‌دهد؛ تأخیر TCP اندازه‌گیری شد.",
                                        "fake-TLS mode: it only answers a full TLS handshake, so the TCP delay was measured instead");
                else
                    result.Detail = L.T("به probe پاسخ نداد ولی پورت باز است", "no answer to the probe, but the port is open");
            }
            catch (Exception ex)
            {
                result.Ok = false;
                result.Detail = ex.Message;
            }
            finally
            {
                if (socket != null) { try { socket.Close(); } catch { } }
            }

            result.DelayMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            return result;
        }
    }
}

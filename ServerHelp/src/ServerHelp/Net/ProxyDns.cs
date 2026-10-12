using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>
    /// Resolves a name the way the tunnel would: the query is put inside the same route the game
    /// uses, so a resolver that is blocked, poisoned or simply unreachable on the local line cannot
    /// matter. This is the "DNS on the VPN" the game needs when the local DNS cannot be used at all.
    /// </summary>
    public static class ProxyDns
    {
        /// <summary>
        /// Runs one A query through a SOCKS proxy (which may be the local tunnel port).
        /// The resolver itself is reached over TCP, so a truncated answer is impossible.
        /// </summary>
        public static DnsAnswer ResolveThrough(string proxyHost, int proxyPort, string dnsServer, string host,
                                               int timeoutMs, string user, string password)
        {
            var answer = new DnsAnswer();
            answer.Server = dnsServer + " (via " + proxyHost + ":" + proxyPort + ")";
            long start = DateTime.UtcNow.Ticks;
            try
            {
                var proxy = string.IsNullOrEmpty(user)
                    ? new Socks5Client(proxyHost, proxyPort, timeoutMs)
                    : new Socks5Client(proxyHost, proxyPort, user, password, timeoutMs);
                using (Socket socket = proxy.Connect(dnsServer, 53))
                {
                    socket.ReceiveTimeout = timeoutMs;
                    socket.SendTimeout = timeoutMs;
                    byte[] query = DnsClient.BuildQuery(host, 1);
                    byte[] framed = new byte[query.Length + 2];
                    framed[0] = (byte)(query.Length >> 8);
                    framed[1] = (byte)(query.Length & 0xFF);
                    Buffer.BlockCopy(query, 0, framed, 2, query.Length);
                    socket.Send(framed);

                    byte[] response = ReadTcpDns(socket, timeoutMs);
                    if (response == null || response.Length < 12)
                    {
                        answer.Error = L.T("پاسخ DNS از داخل تونل نرسید", "no DNS answer came back through the tunnel");
                    }
                    else
                    {
                        DnsClient.ParseAnswers(response, answer);
                    }
                }
            }
            catch (Exception ex)
            {
                answer.Error = ex.Message;
            }
            answer.Ok = answer.Addresses.Count > 0;
            if (!answer.Ok && string.IsNullOrEmpty(answer.Error))
                answer.Error = L.T("رکورد A پیدا نشد", "no A record in the answer");
            answer.ElapsedMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            return answer;
        }

        private static byte[] ReadTcpDns(Socket socket, int timeoutMs)
        {
            var header = new byte[2];
            if (!ReadExact(socket, header, 2, timeoutMs)) return null;
            int length = (header[0] << 8) | header[1];
            if (length <= 0 || length > 4096) return null;
            var body = new byte[length];
            return ReadExact(socket, body, length, timeoutMs) ? body : null;
        }

        private static bool ReadExact(Socket socket, byte[] buffer, int count, int timeoutMs)
        {
            int read = 0;
            long deadline = DateTime.UtcNow.Ticks + timeoutMs * TimeSpan.TicksPerMillisecond;
            while (read < count)
            {
                if (DateTime.UtcNow.Ticks > deadline) return false;
                int got = socket.Receive(buffer, read, count - read, SocketFlags.None);
                if (got <= 0) return false;
                read += got;
            }
            return true;
        }

        /// <summary>
        /// The honest test of a filtered connection: what the system resolver says against what the
        /// resolver inside the tunnel says. A different answer is proof of a poisoned or hijacked
        /// local DNS, which is one of the reasons a Minecraft join fails.
        /// </summary>
        public static string Compare(string host, string systemAnswer, DnsAnswer throughTunnel)
        {
            var sb = new System.Text.StringBuilder();
            sb.Append(L.T("DNS سیستم: ", "system DNS: ")).Append(string.IsNullOrEmpty(systemAnswer) ? "—" : systemAnswer);
            sb.Append("   |   ").Append(L.T("DNS از داخل تونل: ", "DNS through the tunnel: "))
              .Append(throughTunnel.Ok ? string.Join(", ", throughTunnel.Addresses.ToArray()) +
                                        " (" + throughTunnel.ElapsedMs + " ms)" : throughTunnel.Error);
            if (throughTunnel.Ok && !string.IsNullOrEmpty(systemAnswer))
            {
                bool same = true;
                foreach (string ip in throughTunnel.Addresses)
                    if (systemAnswer.IndexOf(ip, StringComparison.Ordinal) < 0) same = false;
                if (!same)
                {
                    sb.Append(Environment.NewLine);
                    sb.Append(L.T("هشدار: جواب سیستم با جواب تونل یکی نیست — DNS محلی دست‌کاری شده است. " +
                                  "برنامه آدرس درست را در hosts ثابت می‌کند تا بازی به آدرس اشتباه نرود.",
                                  "warning: the local answer differs from the tunnel answer - the local DNS is " +
                                  "being tampered with. The app pins the correct address in the hosts file so " +
                                  "the game cannot be sent to the wrong one."));
                }
            }
            return sb.ToString();
        }
    }
}

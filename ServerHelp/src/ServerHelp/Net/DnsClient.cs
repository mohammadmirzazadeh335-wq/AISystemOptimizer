using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>A resolver as the user typed it: udp:// · tcp:// · tls:// (DoT) · https:// (DoH).</summary>
    public sealed class ResolverSpec
    {
        public string Scheme = "udp";
        public string Host = "";        // address or name of the resolver
        public int Port;
        public string Url = "";         // for DoH
        public string Raw = "";         // exactly what the user wrote

        public string Endpoint
        {
            get
            {
                if (Scheme == "https") return Url;
                return Scheme + "://" + Host + ":" + Port.ToString(CultureInfo.InvariantCulture);
            }
        }

        /// <summary>Reads any of the accepted spellings; returns null when nothing usable is inside.</summary>
        public static ResolverSpec Parse(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            string value = text.Trim();
            var spec = new ResolverSpec();
            spec.Raw = value;

            int schemeEnd = value.IndexOf("://", StringComparison.Ordinal);
            string scheme = schemeEnd > 0 ? value.Substring(0, schemeEnd).ToLowerInvariant() : "";
            string rest = schemeEnd > 0 ? value.Substring(schemeEnd + 3) : value;

            if (scheme == "https" || scheme == "doh" || scheme == "http")
            {
                string url = scheme == "doh" ? "https://" + rest : value;
                if (url.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) url = "https://" + url.Substring(7);
                // The JSON API of Cloudflare/Google is what the app understands best; anything
                // else is tried as the standard RFC 8484 wire format.
                spec.Scheme = "https";
                spec.Url = url;
                try
                {
                    var uri = new Uri(url);
                    spec.Host = uri.Host;
                    spec.Port = uri.Port;
                }
                catch { spec.Host = rest; }
                return spec;
            }

            if (scheme == "tls" || scheme == "dot") spec.Scheme = "tls";
            else if (scheme == "tcp") spec.Scheme = "tcp";
            else if (scheme == "udp" || scheme == "dns") spec.Scheme = "udp";
            else if (scheme.Length > 0 && scheme != "system") return null;

            if (scheme == "system") { spec.Scheme = "system"; return spec; }

            int slash = rest.IndexOf('/');
            if (slash >= 0) rest = rest.Substring(0, slash);
            int colon = rest.LastIndexOf(':');
            if (colon > 0)
            {
                int port;
                if (int.TryParse(rest.Substring(colon + 1), NumberStyles.Integer, CultureInfo.InvariantCulture, out port))
                {
                    spec.Port = port;
                    rest = rest.Substring(0, colon);
                }
            }
            if (spec.Port <= 0) spec.Port = spec.Scheme == "tls" ? 853 : 53;
            spec.Host = rest.Trim('[', ']');
            if (string.IsNullOrEmpty(spec.Host)) return null;
            return spec;
        }
    }

    public sealed class DnsAnswer
    {
        public bool Ok;
        public List<string> Addresses = new List<string>();
        public int ElapsedMs = -1;
        public string Server = "";
        public string Error = "";

        public string First { get { return Addresses.Count > 0 ? Addresses[0] : ""; } }

        public string Summary
        {
            get
            {
                if (!Ok) return L.T("بی‌پاسخ", "no answer") + (string.IsNullOrEmpty(Error) ? "" : " (" + Error + ")");
                return string.Join(", ", Addresses.ToArray()) + " • " + ElapsedMs.ToString(CultureInfo.InvariantCulture) + " ms";
            }
        }
    }

    /// <summary>
    /// A DNS client with no dependencies: plain UDP, TCP, DNS-over-TLS and DNS-over-HTTPS.
    /// It exists because a poisoned system resolver is one of the reasons the game cannot connect,
    /// and because the delay of each resolver has to be measurable before it is used.
    /// </summary>
    public static class DnsClient
    {
        public static DnsAnswer Resolve(string specText, string host, int timeoutMs)
        {
            var spec = ResolverSpec.Parse(specText);
            if (spec == null)
            {
                var bad = new DnsAnswer();
                bad.Server = specText;
                bad.Error = L.T("آدرس DNS نامعتبر", "invalid DNS address");
                return bad;
            }
            return Resolve(spec, host, timeoutMs);
        }

        public static DnsAnswer Resolve(ResolverSpec spec, string host, int timeoutMs)
        {
            var answer = new DnsAnswer();
            answer.Server = spec.Endpoint;
            long start = DateTime.UtcNow.Ticks;
            try
            {
                if (spec.Scheme == "system")
                {
                    foreach (string ip in NetUtil.ResolveSimple(host)) answer.Addresses.Add(ip);
                    answer.Ok = answer.Addresses.Count > 0;
                    if (!answer.Ok) answer.Error = L.T("رزولوگر سیستم جواب نداد", "the system resolver gave no answer");
                }
                else if (spec.Scheme == "https")
                {
                    ResolveDoh(spec, host, timeoutMs, answer);
                }
                else if (spec.Scheme == "tls")
                {
                    byte[] response = ExchangeOverTls(spec, BuildQuery(host, 1), timeoutMs);
                    ParseAnswers(response, answer);
                }
                else if (spec.Scheme == "tcp")
                {
                    byte[] response = ExchangeOverTcp(spec, BuildQuery(host, 1), timeoutMs);
                    ParseAnswers(response, answer);
                }
                else
                {
                    byte[] response = ExchangeOverUdp(spec, BuildQuery(host, 1), timeoutMs);
                    ParseAnswers(response, answer);
                    if (!answer.Ok)
                    {
                        // A truncated UDP answer is normal on big zones: retry over TCP.
                        byte[] retry = ExchangeOverTcp(spec, BuildQuery(host, 1), timeoutMs);
                        ParseAnswers(retry, answer);
                    }
                }
                answer.Ok = answer.Addresses.Count > 0;
                if (!answer.Ok && string.IsNullOrEmpty(answer.Error)) answer.Error = L.T("رکورد A پیدا نشد", "no A record in the answer");
            }
            catch (Exception ex)
            {
                answer.Ok = false;
                answer.Error = ex.Message;
            }
            answer.ElapsedMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            return answer;
        }

        // ------------------------------------------------------------------ transport

        private static byte[] ExchangeOverUdp(ResolverSpec spec, byte[] query, int timeoutMs)
        {
            IPAddress address;
            if (!IPAddress.TryParse(spec.Host, out address))
            {
                var resolved = NetUtil.ResolveSimple(spec.Host);
                if (resolved.Count == 0) throw new Exception(L.T("آدرس DNS پیدا نشد: ", "DNS address does not resolve: ") + spec.Host);
                if (!IPAddress.TryParse(resolved[0], out address)) throw new Exception("bad resolver address");
            }

            using (var udp = new UdpClient(address.AddressFamily))
            {
                udp.Client.ReceiveTimeout = timeoutMs;
                udp.Connect(address, spec.Port);
                udp.Send(query, query.Length);
                var remote = new IPEndPoint(address.AddressFamily == AddressFamily.InterNetworkV6 ? IPAddress.IPv6Any : IPAddress.Any, 0);
                IAsyncResult ar = udp.BeginReceive(null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) throw new Exception(L.T("پاسخی از DNS نیامد", "the DNS server did not answer"));
                return udp.EndReceive(ar, ref remote);
            }
        }

        private static byte[] ExchangeOverTcp(ResolverSpec spec, byte[] query, int timeoutMs)
        {
            IPAddress address;
            if (!IPAddress.TryParse(spec.Host, out address))
            {
                var resolved = NetUtil.ResolveSimple(spec.Host);
                if (resolved.Count == 0) throw new Exception(L.T("آدرس DNS پیدا نشد: ", "DNS address does not resolve: ") + spec.Host);
                IPAddress.TryParse(resolved[0], out address);
            }

            using (var socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp))
            {
                socket.NoDelay = true;
                socket.ReceiveTimeout = timeoutMs;
                socket.SendTimeout = timeoutMs;
                IAsyncResult ar = socket.BeginConnect(address, spec.Port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) throw new Exception(L.T("اتصال به DNS برقرار نشد", "could not reach the DNS server"));
                socket.EndConnect(ar);

                var framed = new byte[query.Length + 2];
                framed[0] = (byte)(query.Length >> 8);
                framed[1] = (byte)(query.Length & 0xFF);
                Buffer.BlockCopy(query, 0, framed, 2, query.Length);
                socket.Send(framed);

                byte[] lengthBytes = ReadExact(socket, 2);
                int length = (lengthBytes[0] << 8) | lengthBytes[1];
                return ReadExact(socket, length);
            }
        }

        private static byte[] ExchangeOverTls(ResolverSpec spec, byte[] query, int timeoutMs)
        {
            IPAddress address;
            if (!IPAddress.TryParse(spec.Host, out address))
            {
                var resolved = NetUtil.ResolveSimple(spec.Host);
                if (resolved.Count == 0) throw new Exception(L.T("آدرس DNS پیدا نشد: ", "DNS address does not resolve: ") + spec.Host);
                IPAddress.TryParse(resolved[0], out address);
            }

            using (var tcp = new TcpClient())
            {
                IAsyncResult ar = tcp.BeginConnect(address, spec.Port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) throw new Exception(L.T("اتصال DoT برقرار نشد", "the DoT connection failed"));
                tcp.EndConnect(ar);
                tcp.ReceiveTimeout = timeoutMs;
                tcp.SendTimeout = timeoutMs;

                using (var ssl = new SslStream(tcp.GetStream(), false, delegate (object s, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) { return true; }))
                {
                    ssl.AuthenticateAsClient(spec.Host, null, SslProtocols.Tls12, false);
                    var framed = new byte[query.Length + 2];
                    framed[0] = (byte)(query.Length >> 8);
                    framed[1] = (byte)(query.Length & 0xFF);
                    Buffer.BlockCopy(query, 0, framed, 2, query.Length);
                    ssl.Write(framed, 0, framed.Length);
                    ssl.Flush();

                    byte[] lengthBytes = ReadExact(ssl, 2);
                    int length = (lengthBytes[0] << 8) | lengthBytes[1];
                    byte[] response = new byte[length];
                    int got = 0;
                    while (got < length)
                    {
                        int read = ssl.Read(response, got, length - got);
                        if (read <= 0) throw new Exception("connection closed while reading the answer");
                        got += read;
                    }
                    return response;
                }
            }
        }

        private static void ResolveDoh(ResolverSpec spec, string host, int timeoutMs, DnsAnswer answer)
        {
            string url = spec.Url;
            string separator = url.IndexOf('?') >= 0 ? "&" : "?";
            string jsonUrl = url + separator + "name=" + Uri.EscapeDataString(host) + "&type=A";

            // 1. the JSON API (Cloudflare, Google, NextDNS, AdGuard … all speak it)
            try
            {
                using (var request = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Get, jsonUrl))
                {
                    request.Headers.TryAddWithoutValidation("accept", "application/dns-json");
                    var task = NetUtil.Http.SendAsync(request);
                    if (task.Wait(timeoutMs))
                    {
                        var response = task.Result;
                        string text = response.Content.ReadAsStringAsync().Result;
                        if (response.IsSuccessStatusCode)
                        {
                            var d = Json.ParseObject(text);
                            var answers = Json.Arr(Json.Get(d, "Answer"));
                            if (answers != null)
                            {
                                foreach (object o in answers)
                                {
                                    var item = Json.Obj(o);
                                    if (item == null) continue;
                                    if (Json.GetInt(item, "type", 0) != 1) continue;
                                    string data = Json.GetStr(item, "data", "");
                                    if (!string.IsNullOrEmpty(data)) answer.Addresses.Add(data);
                                }
                            }
                            if (answer.Addresses.Count > 0) return;
                        }
                    }
                }
            }
            catch (Exception ex) { Log.Debug("DoH json api failed: " + ex.Message); }

            // 2. the RFC 8484 wire format as a fallback
            try
            {
                var content = new System.Net.Http.ByteArrayContent(BuildQuery(host, 1));
                content.Headers.TryAddWithoutValidation("content-type", "application/dns-message");
                using (var request = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Post, url))
                {
                    request.Content = content;
                    request.Headers.TryAddWithoutValidation("accept", "application/dns-message");
                    var task = NetUtil.Http.SendAsync(request);
                    if (task.Wait(timeoutMs))
                    {
                        byte[] bytes = task.Result.Content.ReadAsByteArrayAsync().Result;
                        ParseAnswers(bytes, answer);
                    }
                }
            }
            catch (Exception ex)
            {
                if (answer.Addresses.Count == 0) answer.Error = ex.Message;
            }
        }

        // ------------------------------------------------------------------ wire format

        /// <summary>Builds a single-question query (A = 1, AAAA = 28).</summary>
        public static byte[] BuildQuery(string host, int queryType)
        {
            var random = new Random();
            ushort id = (ushort)random.Next(1, 60000);
            var query = new List<byte>();
            query.Add((byte)(id >> 8)); query.Add((byte)(id & 0xFF));
            query.Add(0x01); query.Add(0x00);   // standard query, recursion desired
            query.Add(0x00); query.Add(0x01);   // QDCOUNT
            query.Add(0x00); query.Add(0x00);   // ANCOUNT
            query.Add(0x00); query.Add(0x00);   // NSCOUNT
            query.Add(0x00); query.Add(0x00);   // ARCOUNT
            foreach (string label in host.TrimEnd('.').Split('.'))
            {
                byte[] bytes = Encoding.ASCII.GetBytes(label);
                if (bytes.Length > 63) throw new Exception("label too long in " + host);
                query.Add((byte)bytes.Length);
                query.AddRange(bytes);
            }
            query.Add(0x00);
            query.Add((byte)(queryType >> 8)); query.Add((byte)(queryType & 0xFF));
            query.Add(0x00); query.Add(0x01);   // class IN
            return query.ToArray();
        }

        /// <summary>Reads every A/AAAA record out of an answer, skipping CNAME chains.</summary>
        public static void ParseAnswers(byte[] response, DnsAnswer answer)
        {
            if (response == null || response.Length < 12) return;
            int rcode = response[3] & 0x0F;
            int qd = (response[4] << 8) | response[5];
            int an = (response[6] << 8) | response[7];
            int i = 12;
            for (int q = 0; q < qd && i < response.Length; q++)
            {
                i = SkipName(response, i);
                i += 4;
            }
            for (int a = 0; a < an && i + 10 <= response.Length; a++)
            {
                i = SkipName(response, i);
                if (i + 10 > response.Length) break;
                int type = (response[i] << 8) | response[i + 1];
                int length = (response[i + 8] << 8) | response[i + 9];
                i += 10;
                if (i + length > response.Length) break;
                if (type == 1 && length == 4)
                    answer.Addresses.Add(new IPAddress(new byte[] { response[i], response[i + 1], response[i + 2], response[i + 3] }).ToString());
                else if (type == 28 && length == 16)
                {
                    var bytes = new byte[16];
                    Buffer.BlockCopy(response, i, bytes, 0, 16);
                    answer.Addresses.Add(new IPAddress(bytes).ToString());
                }
                i += length;
            }
            if (rcode != 0 && answer.Addresses.Count == 0)
                answer.Error = "DNS rcode " + rcode.ToString(CultureInfo.InvariantCulture);
        }

        private static int SkipName(byte[] buffer, int index)
        {
            while (index < buffer.Length)
            {
                int length = buffer[index];
                if (length == 0) return index + 1;
                if ((length & 0xC0) == 0xC0) return index + 2;
                index += length + 1;
            }
            return index;
        }

        private static byte[] ReadExact(Socket socket, int count)
        {
            var buffer = new byte[count];
            int got = 0;
            while (got < count)
            {
                int read = socket.Receive(buffer, got, count - got, SocketFlags.None);
                if (read <= 0) throw new Exception("connection closed while reading");
                got += read;
            }
            return buffer;
        }

        private static byte[] ReadExact(System.IO.Stream stream, int count)
        {
            var buffer = new byte[count];
            int got = 0;
            while (got < count)
            {
                int read = stream.Read(buffer, got, count - got);
                if (read <= 0) throw new Exception("connection closed while reading");
                got += read;
            }
            return buffer;
        }
    }
}

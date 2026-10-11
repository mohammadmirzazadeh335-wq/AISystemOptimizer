using ServerHelp.Core;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace ServerHelp.Net
{
    /// <summary>Low level network probing: TCP RTT, ICMP, raw DNS and DNS-over-HTTPS.</summary>
    public static class NetUtil
    {
        private static HttpClient _http;

        public static HttpClient Http
        {
            get
            {
                if (_http == null)
                {
                    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                    var handler = new HttpClientHandler();
                    handler.UseProxy = false;      // never inherit a broken system proxy
                    handler.AllowAutoRedirect = true;
                    _http = new HttpClient(handler);
                    _http.Timeout = TimeSpan.FromSeconds(8);
                }
                return _http;
            }
        }

        // ------------------------------------------------------------------ TCP

        /// <summary>TCP connect time in milliseconds, or -1 when the connect failed/timed out.</summary>
        public static int TcpPing(IPAddress ip, int port, int timeoutMs)
        {
            try
            {
                using (var socket = new Socket(ip.AddressFamily, SocketType.Stream, ProtocolType.Tcp))
                {
                    socket.NoDelay = true;
                    long start = DateTime.UtcNow.Ticks;
                    IAsyncResult ar = socket.BeginConnect(ip, port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                    {
                        try { socket.Close(); } catch { }
                        return -1;
                    }
                    socket.EndConnect(ar);
                    int ms = (int)((DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    try { socket.Close(); } catch { }
                    return ms < 1 ? 1 : ms;
                }
            }
            catch { return -1; }
        }

        public static int TcpPing(string host, int port, int timeoutMs)
        {
            IPAddress ip;
            if (IPAddress.TryParse(host, out ip)) return TcpPing(ip, port, timeoutMs);
            foreach (string s in ResolveSimple(host))
            {
                if (IPAddress.TryParse(s, out ip))
                {
                    int rtt = TcpPing(ip, port, timeoutMs);
                    if (rtt >= 0) return rtt;
                }
            }
            return -1;
        }

        /// <summary>
        /// Connects and reports how the peer behaved: 0 = connected, 1 = refused,
        /// 2 = timeout, 3 = reset immediately (typical of SNI/IP filtering), -1 = other error.
        /// </summary>
        public static int TcpProbe(IPAddress ip, int port, int timeoutMs, out int rttMs)
        {
            rttMs = -1;
            try
            {
                using (var socket = new Socket(ip.AddressFamily, SocketType.Stream, ProtocolType.Tcp))
                {
                    long start = DateTime.UtcNow.Ticks;
                    IAsyncResult ar = socket.BeginConnect(ip, port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                    {
                        try { socket.Close(); } catch { }
                        return 2;
                    }
                    socket.EndConnect(ar);
                    rttMs = (int)((DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    // A filtered Minecraft port frequently accepts the connection and then resets
                    // as soon as the first bytes arrive; that is a different symptom from a timeout.
                    try
                    {
                        socket.ReceiveTimeout = 1500;
                        socket.SendTimeout = 1500;
                        socket.Send(new byte[] { 0x00 });
                        var buf = new byte[1];
                        int n = socket.Receive(buf);
                        if (n == 0) return 3;   // graceful close right away
                    }
                    catch (SocketException se)
                    {
                        if (se.SocketErrorCode == SocketError.ConnectionReset) return 3;
                        if (se.SocketErrorCode == SocketError.TimedOut) return 0; // open, silent: expected for MC
                    }
                    catch { }
                    try { socket.Close(); } catch { }
                    return 0;
                }
            }
            catch (SocketException se)
            {
                if (se.SocketErrorCode == SocketError.ConnectionRefused) return 1;
                if (se.SocketErrorCode == SocketError.TimedOut) return 2;
                return -1;
            }
            catch { return -1; }
        }

        // ------------------------------------------------------------------ ICMP

        public static int IcmpPing(IPAddress ip, int timeoutMs)
        {
            try
            {
                using (var ping = new Ping())
                {
                    PingReply reply = ping.Send(ip, timeoutMs);
                    if (reply != null && reply.Status == IPStatus.Success) return (int)reply.RoundtripTime;
                }
            }
            catch { }
            return -1;
        }

        // ------------------------------------------------------------------- DNS

        public static List<string> ResolveSimple(string host)
        {
            var result = new List<string>();
            try
            {
                IPAddress[] addrs = Dns.GetHostAddresses(host);
                foreach (IPAddress a in addrs)
                    if (a.AddressFamily == AddressFamily.InterNetwork) result.Add(a.ToString());
                if (result.Count == 0)
                    foreach (IPAddress a in addrs) result.Add(a.ToString());
            }
            catch (Exception ex) { Log.Debug("system resolve failed for " + host + ": " + ex.Message); }
            return result;
        }

        /// <summary>Minimal A-record query over UDP against one resolver.</summary>
        public static List<string> DnsQuery(string resolverIp, string host, int timeoutMs)
        {
            var result = new List<string>();
            try
            {
                IPAddress server;
                if (!IPAddress.TryParse(resolverIp, out server)) return result;

                var rnd = new Random();
                ushort id = (ushort)rnd.Next(1, 60000);
                var query = new List<byte>();
                query.Add((byte)(id >> 8)); query.Add((byte)(id & 0xFF));
                query.Add(0x01); query.Add(0x00);   // standard query, recursion desired
                query.Add(0x00); query.Add(0x01);   // QDCOUNT
                query.Add(0x00); query.Add(0x00);   // ANCOUNT
                query.Add(0x00); query.Add(0x00);   // NSCOUNT
                query.Add(0x00); query.Add(0x00);   // ARCOUNT
                foreach (string label in host.Split('.'))
                {
                    byte[] bytes = Encoding.ASCII.GetBytes(label);
                    query.Add((byte)bytes.Length);
                    query.AddRange(bytes);
                }
                query.Add(0x00);
                query.Add(0x00); query.Add(0x01);   // QTYPE A
                query.Add(0x00); query.Add(0x01);   // QCLASS IN

                using (var udp = new UdpClient())
                {
                    udp.Client.ReceiveTimeout = timeoutMs;
                    udp.Connect(server, 53);
                    byte[] payload = query.ToArray();
                    udp.Send(payload, payload.Length);
                    IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
                    IAsyncResult ar = udp.BeginReceive(null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) return result;
                    byte[] resp = udp.EndReceive(ar, ref remote);
                    result.AddRange(ParseAnswers(resp));
                }
            }
            catch (Exception ex) { Log.Debug("dns query " + resolverIp + " failed: " + ex.Message); }
            return result;
        }

        private static List<string> ParseAnswers(byte[] resp)
        {
            var list = new List<string>();
            try
            {
                if (resp.Length < 12) return list;
                int qd = (resp[4] << 8) | resp[5];
                int an = (resp[6] << 8) | resp[7];
                int i = 12;
                for (int q = 0; q < qd; q++)
                {
                    i = SkipName(resp, i);
                    i += 4;
                }
                for (int a = 0; a < an; a++)
                {
                    i = SkipName(resp, i);
                    if (i + 10 > resp.Length) break;
                    int type = (resp[i] << 8) | resp[i + 1];
                    int rdlen = (resp[i + 8] << 8) | resp[i + 9];
                    i += 10;
                    if (type == 1 && rdlen == 4 && i + 4 <= resp.Length)
                        list.Add(new IPAddress(new byte[] { resp[i], resp[i + 1], resp[i + 2], resp[i + 3] }).ToString());
                    i += rdlen;
                }
            }
            catch { }
            return list;
        }

        private static int SkipName(byte[] buf, int i)
        {
            while (i < buf.Length)
            {
                int len = buf[i];
                if (len == 0) return i + 1;
                if ((len & 0xC0) == 0xC0) return i + 2;
                i += len + 1;
            }
            return i;
        }

        /// <summary>DNS over HTTPS (Cloudflare/Google JSON API). Returns an ipv4 address or null.</summary>
        public static string ResolveDoh(string url, string host, int timeoutMs)
        {
            try
            {
                string request = url + (url.Contains("?") ? "&" : "?") + "name=" + Uri.EscapeDataString(host) + "&type=A";
                var task = Http.GetStringAsync(request);
                if (!task.Wait(timeoutMs)) return null;
                var d = Json.ParseObject(task.Result);
                var answers = Json.Arr(Json.Get(d, "Answer"));
                if (answers == null) return null;
                foreach (object o in answers)
                {
                    var ad = Json.Obj(o);
                    if (ad == null) continue;
                    if (Json.GetInt(ad, "type", 0) == 1)
                    {
                        string data = Json.GetStr(ad, "data", null);
                        if (!string.IsNullOrEmpty(data)) return data;
                    }
                }
            }
            catch (Exception ex) { Log.Debug("DoH failed via " + url + ": " + ex.Message); }
            return null;
        }

        // ------------------------------------------------------------------ misc

        public static string LocalIpv4()
        {
            try
            {
                using (var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp))
                {
                    socket.Connect("1.1.1.1", 53);
                    var ep = socket.LocalEndPoint as IPEndPoint;
                    if (ep != null) return ep.Address.ToString();
                }
            }
            catch { }
            return "";
        }

        public static bool IsPrivate(string ipString)
        {
            IPAddress ip;
            if (!IPAddress.TryParse(ipString, out ip)) return false;
            byte[] b = ip.GetAddressBytes();
            if (b.Length != 4) return false;
            if (b[0] == 10) return true;
            if (b[0] == 172 && b[1] >= 16 && b[1] <= 31) return true;
            if (b[0] == 192 && b[1] == 168) return true;
            if (b[0] == 127) return true;
            if (b[0] == 169 && b[1] == 254) return true;
            return false;
        }

        public static void RunParallel(List<Action> jobs, int maxParallel, int overallTimeoutMs)
        {
            var threads = new List<Thread>();
            var gate = new SemaphoreSlim(maxParallel, maxParallel);
            long deadline = DateTime.UtcNow.Ticks + overallTimeoutMs * TimeSpan.TicksPerMillisecond;
            foreach (Action job in jobs)
            {
                Action wrapped = (Action)delegate
                {
                    gate.Wait(5000);
                    try
                    {
                        if (DateTime.UtcNow.Ticks < deadline) job();
                    }
                    catch (Exception ex) { Log.Debug("parallel job failed: " + ex.Message); }
                    finally { gate.Release(); }
                };
                var t = new Thread(delegate () { wrapped(); });
                t.IsBackground = true;
                t.Start();
                threads.Add(t);
            }
            long remaining = deadline - DateTime.UtcNow.Ticks;
            int waitMs = (int)Math.Max(200, remaining / TimeSpan.TicksPerMillisecond + 500);
            foreach (Thread t in threads) t.Join(waitMs);
        }
    }
}

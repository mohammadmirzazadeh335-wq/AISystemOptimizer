using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>One check of the line, with the honest number it produced.</summary>
    public sealed class LineProbe
    {
        public string Name = "";
        public bool Ok;
        public int DelayMs = -1;
        public string Detail = "";
    }

    /// <summary>
    /// What the line looks like at this moment. The names are the ones an Iranian user knows:
    /// the international route may be cut while the domestic route still works, the name server may
    /// answer nothing, or only the TLS handshake may be blocked - and each of those needs a
    /// different fix.
    /// </summary>
    public enum LineVerdict
    {
        Unknown,
        Open,             // international works, plain line is usable
        DnsBroken,        // the local resolver is dead or lying
        TlsBlocked,       // TCP leaves the country, TLS does not survive (SNI filtering)
        NationalOnly,     // international reachable only through something else
        FullyFiltered,    // nothing international answers
        ServerBlocked     // the line is fine, the game server is not reachable
    }

    /// <summary>
    /// Tests the line the way a Minecraft join tests it: name resolution, TCP to the server, TLS to
    /// the outside world, and a DNS query over UDP. The result explains what is broken and which fix
    /// (hosts, DNS inside the tunnel, a proxy, or a relay chain) actually applies.
    /// </summary>
    public static class LineDoctor
    {
        /// <summary>A host that answers over TLS from anywhere, used as the canary.</summary>
        private const string CanaryHost = "cp.cloudflare.com";

        public static List<LineProbe> Probe(string serverHost, string serverIp, int serverPort, int timeoutMs)
        {
            var probes = new List<LineProbe>();
            int budget = Math.Max(1200, timeoutMs);

            // ---- 1. does the outside world answer at all (plain TCP, no TLS)?
            var tcp = new LineProbe();
            tcp.Name = L.T("دسترسی TCP بین‌المللی (پورت ۴۴۳)", "international TCP (port 443)");
            long start = DateTime.UtcNow.Ticks;
            int tcpResult = NetUtil.TcpPing("1.1.1.1", 443, budget);
            tcp.Ok = tcpResult > 0;
            tcp.DelayMs = tcpResult;
            tcp.Detail = tcp.Ok
                ? L.T("دست می‌رسد", "reachable") + " • " + tcpResult + " ms"
                : L.T("جواب نداد — احتمالاً مسیر بین‌المللی بسته است", "no answer - the international route looks blocked");
            probes.Add(tcp);

            // ---- 2. does a TLS handshake survive (SNI filtering shows up exactly here)?
            var tls = new LineProbe();
            tls.Name = L.T("هندشیک TLS به یک سرور خارجی", "TLS handshake to an outside server");
            var tlsResult = TlsHandshake(CanaryHost, 443, budget, out string tlsError);
            tls.Ok = tlsResult > 0;
            tls.DelayMs = tlsResult;
            tls.Detail = tls.Ok
                ? L.T("سالم است", "healthy") + " • " + tlsResult + " ms"
                : tlsError;
            probes.Add(tls);

            // ---- 3. system resolver against a real DNS query over UDP
            var dns = new LineProbe();
            dns.Name = L.T("حل نام دامنه (DNS سیستم)", "name resolution (system DNS)");
            var systemIps = NetUtil.ResolveSimple(CanaryHost);
            dns.Ok = systemIps.Count > 0;
            dns.Detail = dns.Ok
                ? string.Join(", ", systemIps.ToArray())
                : L.T("سیستم هیچ جوابی نداد", "the system resolver answered nothing");
            probes.Add(dns);

            var udp = new LineProbe();
            udp.Name = L.T("پرس‌وجوی DNS روی UDP به 1.1.1.1", "DNS query over UDP to 1.1.1.1");
            start = DateTime.UtcNow.Ticks;
            var direct = NetUtil.DnsQuery("1.1.1.1", CanaryHost, budget);
            udp.Ok = direct.Count > 0;
            udp.DelayMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            udp.Detail = udp.Ok
                ? string.Join(", ", direct.ToArray()) + " • " + udp.DelayMs + " ms"
                : L.T("بدون پاسخ — DNS روی UDP مسدود است", "no answer - DNS over UDP is blocked");
            probes.Add(udp);

            // ---- 4. the game server itself, straight from this line
            var game = new LineProbe();
            game.Name = L.T("سرور بازی بدون تونل", "the game server without a tunnel");
            string target = string.IsNullOrEmpty(serverIp) ? serverHost : serverIp;
            int gamePort = serverPort > 0 ? serverPort : 25565;
            if (!string.IsNullOrEmpty(target))
            {
                int result = NetUtil.TcpPing(target, gamePort, budget);
                game.Ok = result > 0;
                game.DelayMs = result;
                game.Detail = game.Ok
                    ? target + ":" + gamePort + " • " + result + " ms"
                    : target + ":" + gamePort + " — " + L.T("بی‌پاسخ (یا کلید TCP ندارد)",
                                                           "no answer (or it does not answer TCP)");
            }
            else
            {
                game.Detail = L.T("آدرس سرور مشخص نیست", "the server address is not set");
            }
            probes.Add(game);
            return probes;
        }

        private static int TlsHandshake(string host, int port, int timeoutMs, out string error)
        {
            error = "";
            long start = DateTime.UtcNow.Ticks;
            try
            {
                var addresses = NetUtil.ResolveSimple(host);
                if (addresses.Count == 0) addresses = NetUtil.DnsQuery("1.1.1.1", host, timeoutMs);
                if (addresses.Count == 0)
                {
                    error = L.T("نام سرور خارجی حل نشد", "the outside host name did not resolve");
                    return -1;
                }
                using (var client = new TcpClient())
                {
                    var connect = client.BeginConnect(Addresses(addresses), port, null, null);
                    if (!connect.AsyncWaitHandle.WaitOne(timeoutMs))
                    {
                        error = L.T("اتصال TCP برقرار نشد", "the TCP connection was not established");
                        return -1;
                    }
                    client.EndConnect(connect);
                    using (var ssl = new SslStream(client.GetStream(), false, delegate { return true; }))
                    {
                        var task = ssl.AuthenticateAsClientAsync(host);
                        if (!task.Wait(timeoutMs))
                        {
                            error = L.T("هندشیک TLS تمام نشد — نشانه فیلتر SNI",
                                        "the TLS handshake never finished - the classic SNI filtering sign");
                            return -1;
                        }
                    }
                }
                return (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            }
            catch (Exception ex)
            {
                Exception inner = ex is AggregateException && ex.InnerException != null ? ex.InnerException : ex;
                error = L.T("هندشیک TLS شکست خورد: ", "the TLS handshake failed: ") + inner.Message;
                return -1;
            }
        }

        private static IPAddress[] Addresses(List<string> ips)
        {
            var list = new List<IPAddress>();
            foreach (string ip in ips)
            {
                IPAddress parsed;
                if (IPAddress.TryParse(ip, out parsed)) list.Add(parsed);
            }
            return list.ToArray();
        }

        /// <summary>Turns the probes into one verdict and the advice that belongs to it.</summary>
        public static LineVerdict Verdict(List<LineProbe> probes, out string advice)
        {
            advice = "";
            if (probes == null || probes.Count < 5) return LineVerdict.Unknown;

            LineProbe tcp = probes[0], tls = probes[1], dns = probes[2], udp = probes[3], game = probes[4];

            if (!tcp.Ok && !udp.Ok)
            {
                advice = L.T("مسیر بین‌المللی بسته است (اینترنت ملی). تیک «DNS از داخل تونل» را روشن بگذارید و " +
                              "از «بهینه‌سازی مسیر بازی» استفاده کنید: مسیر باید از یک پروکسی داخلی شروع شود و " +
                              "از خارج ادامه پیدا کند (زنجیره رله).",
                              "the international route is closed (national internet). Keep DNS inside the tunnel " +
                              "on, and use Optimise game route: the route should start from a domestic hop and " +
                              "continue abroad (a relay chain).");
                return LineVerdict.NationalOnly;
            }
            if (!tcp.Ok && udp.Ok)
            {
                advice = L.T("DNS کار می‌کند ولی TCP بین‌المللی جواب نمی‌دهد: خط فقط برای نام‌ها باز است. " +
                              "برای بازی یک پروکسی یا زنجیره رله لازم است.",
                              "DNS works but international TCP does not: the line is only open for names. " +
                              "The game needs a proxy or a relay chain.");
                return LineVerdict.FullyFiltered;
            }
            if (tcp.Ok && !tls.Ok)
            {
                advice = L.T("TCP می‌رود بیرون ولی TLS شکست می‌خورد: فیلترینگ روی SNI. در تنظیمات اتصال، " +
                              "«تکه‌تکه‌کردن TLS» را روشن کنید و مسیر را دوباره اندازه بگیرید؛ اگر جواب " +
                              "نداد از یک پروکسی با fake-TLS یا زنجیره رله استفاده کنید.",
                              "TCP leaves the country but TLS fails: SNI filtering. Turn on TLS fragmentation " +
                              "for the connection and measure the route again; if that does not help, use a " +
                              "proxy with fake-TLS or a relay chain.");
                return LineVerdict.TlsBlocked;
            }
            if (!dns.Ok)
            {
                advice = L.T("خط بین‌المللی باز است ولی DNS سیستم جواب نمی‌دهد؛ DNS داخل تونل (یا یک سرور DNS " +
                              "دستی) این را حل می‌کند و آدرس درست در hosts ثابت می‌شود.",
                              "the international line is open but the system resolver answers nothing; DNS " +
                              "inside the tunnel (or a DNS server you add yourself) fixes it and the correct " +
                              "address gets pinned in hosts.");
                return LineVerdict.DnsBroken;
            }
            if (!game.Ok && tcp.Ok && tls.Ok)
            {
                advice = L.T("خط سالم است ولی سرور بازی از این خط جواب نمی‌دهد: احتمالاً سرور روی همان پورت " +
                              "بسته است یا باید مسیر بازی از پروکسی برود. «Optimise game route» را بزنید.",
                              "the line is healthy but the game server does not answer from it: either the " +
                              "server is closed on that port or the game has to go through a proxy. Run " +
                              "Optimise game route.");
                return LineVerdict.ServerBlocked;
            }
            if (!game.Ok)
            {
                advice = L.T("سرور بازی جواب نداد؛ یک مسیر پروکسی را امتحان کنید.",
                             "the game server did not answer; try a proxy route.");
                return LineVerdict.ServerBlocked;
            }
            advice = L.T("همه‌چیز از این خط مستقیم کار می‌کند؛ نیازی به تونل نیست (اگر پینگ پایین است، " +
                          "همان حالت مستقیم را استفاده کنید).",
                          "everything works straight from this line; no tunnel is needed (if the ping is good, " +
                          "keep the direct route).");
            return LineVerdict.Open;
        }

        public static string VerdictTitle(LineVerdict verdict)
        {
            switch (verdict)
            {
                case LineVerdict.Open: return L.T("خط باز است", "the line is open");
                case LineVerdict.DnsBroken: return L.T("DNS خراب است", "the resolver is broken");
                case LineVerdict.TlsBlocked: return L.T("فیلترینگ روی TLS/SNI", "TLS/SNI filtering");
                case LineVerdict.NationalOnly: return L.T("اینترنت ملی (فقط داخلی)", "national internet (domestic only)");
                case LineVerdict.FullyFiltered: return L.T("بین‌المللی مسدود است", "international is blocked");
                case LineVerdict.ServerBlocked: return L.T("مسیر سرور بازی بسته است", "the game server path is closed");
                default: return L.T("نامشخص", "unknown");
            }
        }

        /// <summary>The whole report as text, for the log window and the message box.</summary>
        public static string Report(List<LineProbe> probes, LineVerdict verdict, string advice)
        {
            var sb = new StringBuilder();
            sb.AppendLine(L.T("نتیجه: ", "result: ") + VerdictTitle(verdict));
            sb.AppendLine();
            foreach (LineProbe probe in probes)
            {
                sb.AppendLine((probe.Ok ? "✓ " : "✗ ") + probe.Name + " — " + probe.Detail);
            }
            if (!string.IsNullOrEmpty(advice))
            {
                sb.AppendLine();
                sb.AppendLine(L.T("پیشنهاد: ", "advice: ") + advice);
            }
            return sb.ToString();
        }
    }
}

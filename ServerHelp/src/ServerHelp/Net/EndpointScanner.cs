using ServerHelp.Core;
using System;
using System.Collections.Generic;
using System.Net;
using System.Threading;

namespace ServerHelp.Net
{
    /// <summary>
    /// Ranks Cloudflare WARP anycast addresses. ICMP and a TCP handshake to port 443 do not measure
    /// the WireGuard path itself, but they reliably rank anycast proximity, so the tunnel group is
    /// then handed the best handful of candidates and sing-box picks the true winner.
    /// </summary>
    public static class EndpointScanner
    {
        public sealed class ScanResult
        {
            public List<WarpEndpoint> Endpoints = new List<WarpEndpoint>();
            public int Probed;
            public int Reachable;
            public long ElapsedMs;
        }

        public static ScanResult Scan(int probeTimeoutMs, List<string> seedIps, Action<string> report)
        {
            var started = DateTime.UtcNow;
            var result = new ScanResult();
            if (seedIps == null || seedIps.Count == 0) seedIps = WarpEndpoints.SeedAddresses();

            var candidates = new List<WarpEndpoint>();
            // one probe per address for ICMP/TCP, then the best addresses get port variants
            foreach (string ip in seedIps)
            {
                var e = new WarpEndpoint();
                e.Ip = ip;
                e.Port = WarpEndpoints.Ports[0];
                candidates.Add(e);
            }

            int probed = 0, reachable = 0;
            var gate = new SemaphoreSlim(32, 32);
            var threads = new List<Thread>();
            var lockObj = new object();

            foreach (WarpEndpoint e in candidates)
            {
                WarpEndpoint local = e;
                var t = new Thread(delegate ()
                {
                    gate.Wait();
                    try
                    {
                        IPAddress ip;
                        if (!IPAddress.TryParse(local.Ip, out ip)) return;
                        local.IcmpRtt = NetUtil.IcmpPing(ip, probeTimeoutMs);
                        local.TcpRtt = NetUtil.TcpPing(ip, 443, probeTimeoutMs);
                        lock (lockObj)
                        {
                            probed++;
                            if (local.Score < 9999) reachable++;
                            if (report != null && probed % 12 == 0)
                                report(L.T("اسکن سرورهای WARP: ", "WARP scan: ") + probed + "/" + candidates.Count);
                        }
                    }
                    catch { }
                    finally { gate.Release(); }
                });
                t.IsBackground = true;
                t.Start();
                threads.Add(t);
            }
            foreach (Thread t in threads) t.Join(probeTimeoutMs + 4000);

            result.Probed = probed;
            result.Reachable = reachable;
            result.Endpoints = candidates;
            result.ElapsedMs = (long)(DateTime.UtcNow - started).TotalMilliseconds;
            return result;
        }

        /// <summary>Adds port variants of the best addresses, because a blocked port is common.</summary>
        public static List<WarpEndpoint> WithPortVariants(List<WarpEndpoint> best, int portCount)
        {
            var result = new List<WarpEndpoint>();
            foreach (WarpEndpoint e in best)
            {
                int n = 0;
                foreach (int port in WarpEndpoints.Ports)
                {
                    var copy = new WarpEndpoint();
                    copy.Ip = e.Ip;
                    copy.Port = port;
                    copy.IcmpRtt = e.IcmpRtt;
                    copy.TcpRtt = e.TcpRtt;
                    result.Add(copy);
                    n++;
                    if (n >= portCount) break;
                }
            }
            return result;
        }
    }
}

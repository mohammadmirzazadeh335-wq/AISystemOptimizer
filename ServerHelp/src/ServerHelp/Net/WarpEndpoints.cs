using System;
using System.Collections.Generic;
using System.Net;

namespace ServerHelp.Net
{
    public sealed class WarpEndpoint
    {
        public string Ip = "";
        public int Port = 2408;
        public int TcpRtt = -1;      // handshake to port 443 of the same anycast address
        public int IcmpRtt = -1;
        public int TunnelRtt = -1;   // real latency through the tunnel (measured later)

        public int Score { get { return TcpRtt >= 0 ? TcpRtt : (IcmpRtt >= 0 ? IcmpRtt + 5 : 9999); } }

        public string Address { get { return Ip + ":" + Port; } }

        public string Report
        {
            get
            {
                string tcp = TcpRtt >= 0 ? (TcpRtt + " ms") : "  -  ";
                string icmp = IcmpRtt >= 0 ? (IcmpRtt + " ms") : "  -  ";
                string tunnel = TunnelRtt >= 0 ? (TunnelRtt + " ms") : "  -  ";
                return Ip.PadRight(16) + " :" + Port.ToString().PadRight(6) + "  icmp " + icmp.PadLeft(7) +
                       "  tcp443 " + tcp.PadLeft(7) + "  tunnel " + tunnel.PadLeft(7);
            }
        }
    }

    /// <summary>Cloudflare WARP anycast addresses and the ports its WireGuard endpoints listen on.</summary>
    public static class WarpEndpoints
    {
        public static readonly int[] Ports = new int[]
        {
            2408, 500, 894, 890, 1701, 8854, 943, 928, 968, 987, 891, 903, 946, 955, 1002, 1010, 1156, 1387
        };

        /// <summary>Addresses that are known to answer; used as the seed for every scan.</summary>
        private static readonly string[] SeedIps = new string[]
        {
            "162.159.192.1", "162.159.192.2", "162.159.192.53", "162.159.192.121", "162.159.192.133",
            "162.159.192.157", "162.159.192.165", "162.159.192.200", "162.159.192.212", "162.159.192.240",
            "162.159.193.10", "162.159.193.22", "162.159.193.30", "162.159.193.51", "162.159.193.100",
            "162.159.193.150", "162.159.193.200", "162.159.193.225", "162.159.193.250",
            "162.159.195.1", "162.159.195.2", "162.159.195.10", "162.159.195.50", "162.159.195.100",
            "162.159.195.150", "162.159.195.200", "162.159.195.230",
            "162.159.204.1", "162.159.204.50", "162.159.204.100", "162.159.204.150",
            "188.114.96.1", "188.114.96.10", "188.114.96.50", "188.114.96.100", "188.114.96.150", "188.114.96.200",
            "188.114.97.1", "188.114.97.10", "188.114.97.50", "188.114.97.100", "188.114.97.150", "188.114.97.200",
            "188.114.98.1", "188.114.98.10", "188.114.98.50", "188.114.98.100", "188.114.98.150", "188.114.98.224",
            "188.114.99.1", "188.114.99.10", "188.114.99.50", "188.114.99.100", "188.114.99.150", "188.114.99.224"
        };

        public static List<string> SeedAddresses()
        {
            return new List<string>(SeedIps);
        }

        /// <summary>Picks the highest scoring (lowest latency) endpoints, one entry per address.</summary>
        public static List<WarpEndpoint> PickBest(List<WarpEndpoint> all, int count)
        {
            var sorted = new List<WarpEndpoint>(all);
            sorted.Sort(delegate (WarpEndpoint a, WarpEndpoint b) { return a.Score.CompareTo(b.Score); });

            var chosen = new List<WarpEndpoint>();
            var usedIps = new HashSet<string>(StringComparer.Ordinal);
            foreach (WarpEndpoint e in sorted)
            {
                if (e.Score >= 9999) break;
                if (!usedIps.Add(e.Ip)) continue;
                chosen.Add(e);
                if (chosen.Count >= count) break;
            }
            // If the probe found nothing at all (ICMP blocked, TCP 443 filtered) still try the
            // classic anycast addresses so the tunnel has a chance, with the default port.
            if (chosen.Count == 0)
            {
                foreach (string ip in SeedIps)
                {
                    var e = new WarpEndpoint();
                    e.Ip = ip;
                    e.Port = 2408;
                    chosen.Add(e);
                    if (chosen.Count >= count) break;
                }
            }
            return chosen;
        }
    }
}

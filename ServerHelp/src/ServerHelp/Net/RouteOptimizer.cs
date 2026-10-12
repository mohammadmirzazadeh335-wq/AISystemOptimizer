using System;
using System.Collections.Generic;
using System.Globalization;
using ServerHelp.Core;
using ServerHelp.Tunnel;

namespace ServerHelp.Net
{
    /// <summary>
    /// One way to reach the game server: a single proxy, a tunnel the app builds, a chain of two
    /// proxies, or the plain connection.
    /// </summary>
    public sealed class RouteCandidate
    {
        public string Name = "";
        public ConnectionEntry First;          // entry the traffic enters (null = direct line)
        public ConnectionEntry Second;         // entry it leaves through (a chained relay)
        public string Tag = "";
        public string SecondTag = "";
        public int GamePingMs = -1;            // measured with a real Minecraft handshake
        public int HopPingMs = -1;             // measured to the first hop itself
        public string Status = "";
        public string Detail = "";
        public bool Ok;

        public bool IsDirect { get { return First == null; } }
        public bool IsChain { get { return First != null && Second != null; } }
        public int Hops { get { return First == null ? 0 : (Second == null ? 1 : 2); } }

        public string Describe()
        {
            if (IsDirect) return L.T("اتصال مستقیم (بدون تونل)", "direct line (no tunnel)");
            if (IsChain) return First.Name + "  →  " + Second.Name;
            return First.Name;
        }

        /// <summary>The name the settings use to pin this route again on the next run.</summary>
        public string PinName { get { return First == null ? "" : First.Name; } }
        public string PinSecondName { get { return Second == null ? "" : Second.Name; } }
    }

    /// <summary>
    /// Runs the candidates through the real Minecraft handshake and keeps the fastest one. This is
    /// the part a dashboard ping cannot do: a proxy can be 20 ms away and still give 300 ms inside
    /// the game, and only a real handshake to the real server shows it.
    /// </summary>
    public static class RouteOptimizer
    {
        /// <summary>
        /// Builds the list to try. Chains are formed from the pool of working proxies: one entry
        /// (usually something close, that a filtered line reaches well) and one exit, which is how a
        /// relay network is normally put together by hand.
        /// </summary>
        public static List<RouteCandidate> Plan(List<ConnectionEntry> connections, bool includeDirect,
                                                int maxChains, bool includeUnmeasured)
        {
            var list = new List<RouteCandidate>();
            var pool = new List<ConnectionEntry>();
            foreach (ConnectionEntry entry in connections)
            {
                if (!entry.Enabled || !entry.CanCarryGame) continue;
                if (entry.Kind == ConnectionKind.Warp) continue;          // WARP needs the scan, handled separately
                if (entry.Missing().Length > 0) continue;
                pool.Add(entry);
            }

            if (includeDirect)
            {
                var direct = new RouteCandidate();
                direct.Name = L.T("اتصال مستقیم", "direct line");
                list.Add(direct);
            }

            foreach (ConnectionEntry entry in pool)
            {
                var candidate = new RouteCandidate();
                candidate.First = entry;
                candidate.Name = entry.Name;
                list.Add(candidate);
            }

            // ---- chains: entry × exit, entries first, exits last (a relay is entered near home)
            if (maxChains > 0 && pool.Count >= 2)
            {
                var byDistance = new List<ConnectionEntry>(pool);
                byDistance.Sort(delegate (ConnectionEntry a, ConnectionEntry b)
                {
                    int left = a.LastDelayMs > 0 ? a.LastDelayMs : int.MaxValue;
                    int right = b.LastDelayMs > 0 ? b.LastDelayMs : int.MaxValue;
                    return left.CompareTo(right);
                });

                int made = 0;
                foreach (ConnectionEntry entry in byDistance)          // entered first
                {
                    if (made >= maxChains) break;
                    foreach (ConnectionEntry exit in byDistance)       // left last
                    {
                        if (made >= maxChains) break;
                        if (exit == entry) continue;
                        if (exit.Kind != ConnectionKind.Socks5 && exit.Kind != ConnectionKind.Http &&
                            exit.Kind != ConnectionKind.SingBoxOutbound && exit.Kind != ConnectionKind.OpenVpn) continue;
                        var chain = new RouteCandidate();
                        chain.First = entry;
                        chain.Second = exit;
                        chain.Name = entry.Name + " → " + exit.Name;
                        list.Add(chain);
                        made++;
                    }
                }
            }
            return list;
        }

        /// <summary>
        /// Measures one candidate for real: a throwaway sing-box with just a local SOCKS port (no TUN,
        /// no routes) followed by a Minecraft status ping to the server through it. Nothing on the
        /// machine is changed while this runs.
        /// </summary>
        public static void Measure(RouteCandidate candidate, string gameHost, int gamePort,
                                   int dnsAddressTimeoutMs, int timeoutMs, out string error)
        {
            error = "";
            candidate.Ok = false;
            candidate.GamePingMs = -1;
            try
            {
                if (candidate.IsDirect)
                {
                    McStatus status = McPing.Status(gameHost, gamePort, timeoutMs, null);
                    candidate.GamePingMs = status == null || !status.Ok ? -1 : Math.Max(1, status.LatencyMs);
                    candidate.Ok = candidate.GamePingMs > 0;
                    candidate.Status = candidate.Ok
                        ? L.T("سریع‌ترین حالت ممکن بدون تونل", "the fastest the line can do without a tunnel")
                        : L.T("اتصال مستقیم جواب نداد", "the direct line did not answer");
                    if (!candidate.Ok) error = candidate.Status;
                    return;
                }

                int port = ProbeTunnel.NextPort();
                var plan = new TunnelPlan();
                plan.IncludeTun = false;                 // a measurement must not touch routes
                plan.SocksPort = port;
                plan.ClashController = "";
                plan.LogPath = "";
                plan.BuildUrlTest = false;
                plan.DnsThroughRoute = false;            // keep the probe small; the game name is not needed
                string tag = "hop-1";
                string exitTag = "hop-2";
                candidate.Tag = tag;
                candidate.SecondTag = candidate.IsChain ? exitTag : "";

                if (candidate.First.Kind == ConnectionKind.WireGuard || candidate.First.Kind == ConnectionKind.OpenVpn)
                    plan.ExtraEndpoints.Add(ConnectionRoute.BuildEndpoint(candidate.First, tag));
                else
                    plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(candidate.First, tag));

                if (candidate.IsChain)
                {
                    // the exit is dialled through the entry: that is the relay chain
                    Dictionary<string, object> exit;
                    if (candidate.Second.Kind == ConnectionKind.WireGuard || candidate.Second.Kind == ConnectionKind.OpenVpn)
                    {
                        exit = ConnectionRoute.BuildEndpoint(candidate.Second, exitTag);
                        plan.ExtraEndpoints.Add(exit);
                    }
                    else
                    {
                        exit = ConnectionRoute.BuildOutbound(candidate.Second, exitTag);
                        plan.ExtraOutbounds.Add(exit);
                    }
                    exit["detour"] = tag;
                    plan.RouteTag = exitTag;
                }
                else
                {
                    plan.RouteTag = tag;
                }

                string json = SingBoxConfig.Build(plan);
                ProbeTunnel probe;
                string startError;
                if (!ProbeTunnel.TryStart(json, port, Math.Max(4000, timeoutMs * 2), out probe, out startError))
                {
                    error = startError;
                    candidate.Status = L.T("مسیر بالا نیامد", "the route did not come up");
                    return;
                }

                try
                {
                    var proxy = new Socks5Client("127.0.0.1", port, Math.Min(6000, timeoutMs));
                    long start = DateTime.UtcNow.Ticks;
                    McStatus status = McPing.Status(gameHost, gamePort, timeoutMs, proxy);
                    int handshake = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    candidate.HopPingMs = handshake;
                    candidate.GamePingMs = status != null && status.Ok ? Math.Max(1, status.LatencyMs) : -1;
                    candidate.Ok = status != null && status.Ok;
                    candidate.Status = candidate.Ok
                        ? L.T("کار می‌کند", "works")
                        : L.T("از این مسیر جواب نداد", "no answer through this route");
                    if (!candidate.Ok) error = candidate.Status;
                }
                finally
                {
                    probe.Stop();
                }
            }
            catch (Exception ex)
            {
                error = ex.Message;
                candidate.Status = ex.Message;
            }
        }

        /// <summary>Sorts the measured candidates: working first, then by the real game ping.</summary>
        public static List<RouteCandidate> Rank(List<RouteCandidate> candidates)
        {
            var ranked = new List<RouteCandidate>(candidates);
            ranked.Sort(delegate (RouteCandidate a, RouteCandidate b)
            {
                if (a.Ok != b.Ok) return a.Ok ? -1 : 1;
                int left = a.GamePingMs > 0 ? a.GamePingMs : int.MaxValue;
                int right = b.GamePingMs > 0 ? b.GamePingMs : int.MaxValue;
                if (left != right) return left.CompareTo(right);
                return string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase);
            });
            return ranked;
        }

        public static string Describe(RouteCandidate candidate, int baselineMs)
        {
            string ping = candidate.GamePingMs > 0
                ? candidate.GamePingMs.ToString(CultureInfo.InvariantCulture) + " ms"
                : "—";
            string delta = "";
            if (candidate.GamePingMs > 0 && baselineMs > 0)
            {
                int difference = candidate.GamePingMs - baselineMs;
                delta = difference <= 0
                    ? "  (" + L.N(Math.Abs(difference)) + L.T(" ms بهتر از مستقیم", " ms better than direct") + ")"
                    : "  (" + L.N(difference) + L.T(" ms بدتر از مستقیم", " ms worse than direct") + ")";
            }
            return candidate.Describe() + "  —  " + ping + delta +
                   (candidate.Status.Length > 0 ? "  •  " + candidate.Status : "");
        }
    }
}

using System;
using System.Collections.Generic;
using ServerHelp.Core;
using ServerHelp.Net;

namespace ServerHelp.Tunnel
{
    /// <summary>Everything that decides what the generated sing-box configuration looks like.</summary>
    public sealed class TunnelPlan
    {
        public WarpCredentials Credentials;
        public List<WarpEndpoint> Endpoints = new List<WarpEndpoint>();
        /// <summary>Ready-made outbound objects (a proxy the user entered, or a pasted config).</summary>
        public List<object> ExtraOutbounds = new List<object>();
        /// <summary>Ready-made endpoint objects (a manually entered WireGuard peer).</summary>
        public List<object> ExtraEndpoints = new List<object>();
        /// <summary>Tags that should take part in the automatic best-route group.</summary>
        public List<string> MemberTags = new List<string>();
        /// <summary>The tag the game traffic is routed to, when the caller already knows it.</summary>
        public string RouteTag = "";
        /// <summary>Groups several routes so sing-box itself keeps the fastest one alive.</summary>
        public bool BuildUrlTest = true;

        public List<string> ServerIps = new List<string>();

        public bool IncludeTun = true;
        public string TunName = "ServerHelp";
        public string TunAddress = "172.19.19.1/30";
        public int TunMtu = 1420;
        public string TunStack = "mixed";

        public int SocksPort = 22345;
        public string ClashController = "127.0.0.1:22346";
        public string ClashSecret = "";

        public int WarpMtu = 1280;
        public int KeepAliveSeconds = 25;
        public string UrlTestUrl = "https://cp.cloudflare.com/generate_204";
        public string UrlTestInterval = "3m";
        public int UrlTestTolerance = 30;

        /// <summary>Resolve names through the chosen route instead of the (possibly blocked) local DNS.</summary>
        public bool DnsThroughRoute = true;
        /// <summary>Resolver the route talks to when the route is a proxy (TCP/53, sent inside the tunnel).</summary>
        public string DnsAddress = "1.1.1.1";
        /// <summary>When set, the pushed resolvers of that OpenVPN endpoint are used instead.</summary>
        public string DnsOpenVpnTag = "";
        /// <summary>Server names the game needs; they are always sent to the tunnel resolver.</summary>
        public List<string> GameDomains = new List<string>();
        /// <summary>"ipv4_only" keeps a broken IPv6 from adding seconds to every lookup.</summary>
        public string DnsStrategy = "ipv4_only";

        public string LogPath = AppPaths.SingBoxLog;
        public string LogLevel = "warn";

        /// <summary>Tag filled in by <see cref="SingBoxConfig.Build"/>: where the game is routed.</summary>
        public string ResolvedTag = "";

        public string GroupTag { get { return "warp-auto"; } }
        public string LocalDnsTag { get { return "local-dns"; } }
        public string TunnelDnsTag { get { return "tunnel-dns"; } }
    }

    /// <summary>
    /// Builds the split tunnel configuration: only the Minecraft server address is routed into the
    /// tunnel, everything else on the machine keeps using the plain connection. The exact JSON
    /// shape is validated against sing-box's official schema (docs/schema.json, v1.14.3).
    /// </summary>
    public static class SingBoxConfig
    {
        public static string Build(TunnelPlan plan)
        {
            if (plan.Endpoints != null && plan.Endpoints.Count > 0 && plan.Credentials == null)
                throw new InvalidOperationException("WARP endpoints need a WARP account to build a tunnel with");

            var warpTags = new List<string>();
            // Tags that may be used to reach the game: taken from the caller (already tested
            // routes) plus whatever tag the pasted objects carry.
            var routeMembers = new List<string>();
            if (plan.MemberTags != null) routeMembers.AddRange(plan.MemberTags);
            var w = new JsonWriter(true);
            w.StartObject();

            // ---- log
            w.Name("log").StartObject();
            w.Prop("level", plan.LogLevel);
            w.Prop("timestamp", true);
            if (!string.IsNullOrEmpty(plan.LogPath)) w.Prop("output", plan.LogPath);
            w.EndObject();

            // ---- inbounds
            w.Name("inbounds").StartArray();
            if (plan.IncludeTun)
            {
                var routes = new List<string>();
                foreach (string ip in plan.ServerIps) routes.Add(ip + "/32");
                w.StartObject();
                w.Prop("type", "tun");
                w.Prop("tag", "tun-in");
                w.Prop("interface_name", plan.TunName);
                w.Name("address").StartArray();
                w.Value(plan.TunAddress);
                w.EndArray();
                w.Prop("mtu", plan.TunMtu);
                w.Prop("stack", plan.TunStack);
                // auto_route with an explicit route list: the interface only carries the server,
                // so the game is tunnelled and every other program stays untouched.
                w.Prop("auto_route", routes.Count > 0);
                w.Prop("strict_route", false);
                if (routes.Count > 0)
                {
                    w.Name("route_address").StartArray();
                    foreach (string r in routes) w.Value(r);
                    w.EndArray();
                }
                w.EndObject();
            }
            w.StartObject();
            w.Prop("type", "mixed");
            w.Prop("tag", "proxy-in");
            w.Prop("listen", "127.0.0.1");
            w.Prop("listen_port", plan.SocksPort);
            w.EndObject();
            w.EndArray();

            // ---- endpoints: WARP peers, plus anything the user pasted (a manual WireGuard peer)
            w.Name("endpoints").StartArray();
            if (plan.Endpoints != null && plan.Credentials != null)
            {
                int index = 0;
                foreach (WarpEndpoint endpoint in plan.Endpoints)
                {
                    index++;
                    string tag = "warp-" + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
                    warpTags.Add(tag);
                    w.StartObject();
                    w.Prop("type", "wireguard");
                    w.Prop("tag", tag);
                    w.Name("address").StartArray();
                    w.Value(plan.Credentials.AddressV4 + "/32");
                    if (!string.IsNullOrEmpty(plan.Credentials.AddressV6))
                        w.Value(plan.Credentials.AddressV6 + "/128");
                    w.EndArray();
                    w.Prop("private_key", plan.Credentials.PrivateKey);
                    w.Prop("mtu", plan.WarpMtu);
                    w.Name("peers").StartArray();
                    w.StartObject();
                    w.Prop("address", endpoint.Ip);
                    w.Prop("port", endpoint.Port);
                    w.Prop("public_key", plan.Credentials.PeerPublicKey);
                    w.Name("allowed_ips").StartArray();
                    w.Value("0.0.0.0/0");
                    w.Value("::/0");
                    w.EndArray();
                    w.Prop("persistent_keepalive_interval", plan.KeepAliveSeconds);
                    if (plan.Credentials.Reserved != null && plan.Credentials.Reserved.Length == 3)
                    {
                        w.Name("reserved").StartArray();
                        foreach (int b in plan.Credentials.Reserved) w.Value(b);
                        w.EndArray();
                    }
                    w.EndObject();
                    w.EndArray();
                    w.EndObject();
                }
            }
            if (plan.ExtraEndpoints != null)
            {
                foreach (object endpoint in plan.ExtraEndpoints)
                {
                    EnsureLocalResolver(endpoint, plan);
                    w.ValueRaw(Json.Serialize(endpoint));
                    string tag = TagOf(endpoint);
                    if (!string.IsNullOrEmpty(tag)) routeMembers.Add(tag);
                }
            }
            w.EndArray();

            // ---- outbounds
            w.Name("outbounds").StartArray();

            if (plan.ExtraOutbounds != null)
            {
                foreach (object outbound in plan.ExtraOutbounds)
                {
                    EnsureLocalResolver(outbound, plan);
                    w.ValueRaw(Json.Serialize(outbound));
                    string tag = TagOf(outbound);
                    if (!string.IsNullOrEmpty(tag)) routeMembers.Add(tag);
                }
            }

            // The group is always written when more than one route exists; with a single route the
            // traffic is handed straight to it so no time is spent testing.
            var tags = new List<string>();
            tags.AddRange(warpTags);
            tags.AddRange(routeMembers);
            var unique = new List<string>();
            foreach (string tag in tags) if (!string.IsNullOrEmpty(tag) && !unique.Contains(tag)) unique.Add(tag);

            string routeTag;
            if (!string.IsNullOrEmpty(plan.RouteTag))
            {
                routeTag = plan.RouteTag;
            }
            else if (unique.Count == 0)
            {
                routeTag = "direct";
            }
            else if (unique.Count == 1 || !plan.BuildUrlTest)
            {
                routeTag = unique[0];
            }
            else
            {
                routeTag = plan.GroupTag;
                w.StartObject();
                w.Prop("type", "urltest");
                w.Prop("tag", plan.GroupTag);
                w.Name("outbounds").StartArray();
                foreach (string tag in unique) w.Value(tag);
                w.EndArray();
                w.Prop("url", plan.UrlTestUrl);
                w.Prop("interval", plan.UrlTestInterval);
                w.Prop("tolerance", plan.UrlTestTolerance);
                w.Prop("idle_timeout", "30m");
                w.Prop("interrupt_exist_connections", false);
                w.EndObject();
            }

            w.StartObject();
            w.Prop("type", "direct");
            w.Prop("tag", "direct");
            w.EndObject();
            w.EndArray();

            // ---- experimental (Clash API for live latency reporting)
            if (!string.IsNullOrEmpty(plan.ClashController))
            {
                w.Name("experimental").StartObject();
                w.Name("clash_api").StartObject();
                w.Prop("external_controller", plan.ClashController);
                if (!string.IsNullOrEmpty(plan.ClashSecret)) w.Prop("secret", plan.ClashSecret);
                w.EndObject();
                w.EndObject();
            }

            // ---- dns: the reason the game cannot be reached on a filtered line is very often the
            // resolver, so name lookups are pushed through the same route the game uses. A resolver
            // the user added by hand only fixes the hosts file; this fixes the protocol itself.
            // sing-box 1.12 and newer refuse a configuration in which a dial field has no resolver
            // ("missing route.default_domain_resolver"), so the dns block and that default are always
            // written: without them the engine would reject the whole tunnel.
            {
                w.Name("dns").StartObject();
                w.Name("servers").StartArray();

                w.StartObject();
                w.Prop("type", "local");
                w.Prop("tag", plan.LocalDnsTag);
                w.EndObject();

                bool tunnelledDns = plan.DnsThroughRoute && routeTag != "direct";
                if (tunnelledDns && !string.IsNullOrEmpty(plan.DnsOpenVpnTag))
                {
                    // an OpenVPN server pushes its own resolvers; using them is both faster and
                    // closer to the exit, which is exactly what a low ping route wants
                    w.StartObject();
                    w.Prop("type", "openvpn");
                    w.Prop("tag", plan.TunnelDnsTag);
                    w.Prop("endpoint", plan.DnsOpenVpnTag);
                    w.Prop("accept_default_resolvers", true);
                    w.Prop("accept_search_domain", false);
                    w.EndObject();
                }
                else if (tunnelledDns)
                {
                    w.StartObject();
                    w.Prop("type", "tcp");
                    w.Prop("tag", plan.TunnelDnsTag);
                    w.Prop("server", plan.DnsAddress);
                    w.Prop("server_port", 53);
                    w.Prop("detour", routeTag);
                    w.Name("domain_resolver").Value(plan.LocalDnsTag);
                    w.EndObject();
                }
                w.EndArray();

                if (tunnelledDns)
                {
                    var rules = new List<string>();
                    foreach (string domain in plan.GameDomains)
                        if (!string.IsNullOrEmpty(domain) && !IsIpLiteral(domain)) rules.Add(domain);
                    if (rules.Count > 0)
                    {
                        w.Name("rules").StartArray();
                        w.StartObject();
                        w.Name("domain").StartArray();
                        foreach (string domain in rules) w.Value(domain);
                        w.EndArray();
                        w.Prop("server", plan.TunnelDnsTag);
                        w.EndObject();
                        w.EndArray();
                    }
                    w.Prop("final", plan.TunnelDnsTag);
                }
                else
                {
                    w.Prop("final", plan.LocalDnsTag);
                }
                if (!string.IsNullOrEmpty(plan.DnsStrategy)) w.Prop("strategy", plan.DnsStrategy);
                w.EndObject();
            }

            // ---- route
            w.Name("route").StartObject();
            w.Prop("auto_detect_interface", true);
            w.Prop("final", "direct");
            // dial fields without their own resolver (the proxies the user entered, for example)
            // resolve names through the local resolver: asking the tunnel for the tunnel's own
            // address would be a circle
            w.Prop("default_domain_resolver", plan.LocalDnsTag);
            w.Name("rules").StartArray();
            if (routeTag != "direct")
            {
                w.StartObject();
                w.Name("inbound").StartArray();
                w.Value("proxy-in");
                w.EndArray();
                w.Prop("action", "route");
                w.Prop("outbound", routeTag);
                w.EndObject();
                foreach (string ip in plan.ServerIps)
                {
                    w.StartObject();
                    w.Name("ip_cidr").StartArray();
                    w.Value(ip + "/32");
                    w.EndArray();
                    w.Prop("action", "route");
                    w.Prop("outbound", routeTag);
                    w.EndObject();
                }
            }
            else
            {
                // Nothing to route through: the SOCKS port still works and goes direct, which
                // keeps the tunnel from becoming a black hole.
                w.StartObject();
                w.Name("inbound").StartArray();
                w.Value("proxy-in");
                w.EndArray();
                w.Prop("action", "route");
                w.Prop("outbound", "direct");
                w.EndObject();
            }
            w.EndArray();
            w.EndObject();

            w.EndObject();
            plan.ResolvedTag = routeTag;
            return w.ToString();
        }

        /// <summary>
        /// An outbound whose server is a domain needs a resolver of its own, otherwise it would ask
        /// the tunnel DNS for its own address: a circle. The local resolver breaks the circle.
        /// </summary>
        private static void EnsureLocalResolver(object value, TunnelPlan plan)
        {
            if (!plan.DnsThroughRoute) return;
            var obj = Json.Obj(value);
            if (obj == null || obj.Count == 0) return;
            string type = Json.GetStr(obj, "type", "");
            if (type == "direct" || type == "block" || type == "dns" || type == "selector" || type == "urltest") return;
            if (Json.Get(obj, "domain_resolver") != null) return;

            string server = Json.GetStr(obj, "server", "");
            if (server.Length > 0)
            {
                if (!IsIpLiteral(server)) obj["domain_resolver"] = plan.LocalDnsTag;
                return;
            }

            // endpoints keep the far end inside peers[]
            var peers = Json.Arr(Json.Get(obj, "peers"));
            if (peers == null) return;
            foreach (object item in peers)
            {
                var peer = Json.Obj(item);
                if (peer == null) continue;
                string address = Json.GetStr(peer, "address", "");
                if (address.Length > 0 && !IsIpLiteral(address))
                {
                    obj["domain_resolver"] = plan.LocalDnsTag;
                    return;
                }
            }
        }

        private static bool IsIpLiteral(string text)
        {
            System.Net.IPAddress parsed;
            return System.Net.IPAddress.TryParse(text, out parsed);
        }

        /// <summary>The part of a tag that has to be unique: two "warp" entries must not share one.</summary>
        private static string TagOf(object outbound)
        {
            var d = Json.Obj(outbound);
            if (d == null) return "";
            return Json.GetStr(d, "tag", "");
        }
    }
}

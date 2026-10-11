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

        public string LogPath = AppPaths.SingBoxLog;
        public string LogLevel = "warn";

        public string GroupTag { get { return "warp-auto"; } }
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
            if (plan.Endpoints == null || plan.Endpoints.Count == 0)
                throw new InvalidOperationException("no WARP endpoints to build a tunnel with");

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

            // ---- endpoints (WireGuard is an endpoint since sing-box 1.11)
            w.Name("endpoints").StartArray();
            var tags = new List<string>();
            int index = 0;
            foreach (WarpEndpoint endpoint in plan.Endpoints)
            {
                index++;
                string tag = "warp-" + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
                tags.Add(tag);
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
                w.Name("reserved").StartArray();
                foreach (int b in plan.Credentials.Reserved) w.Value(b);
                w.EndArray();
                w.EndObject();
                w.EndArray();
                w.EndObject();
            }
            w.EndArray();

            // ---- outbounds
            w.Name("outbounds").StartArray();
            w.StartObject();
            w.Prop("type", "urltest");
            w.Prop("tag", plan.GroupTag);
            w.Name("outbounds").StartArray();
            foreach (string tag in tags) w.Value(tag);
            w.EndArray();
            w.Prop("url", plan.UrlTestUrl);
            w.Prop("interval", plan.UrlTestInterval);
            w.Prop("tolerance", plan.UrlTestTolerance);
            w.Prop("idle_timeout", "30m");
            w.Prop("interrupt_exist_connections", false);
            w.EndObject();
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

            // ---- route
            w.Name("route").StartObject();
            w.Prop("auto_detect_interface", true);
            w.Prop("final", "direct");
            w.Name("rules").StartArray();
            w.StartObject();
            w.Name("inbound").StartArray();
            w.Value("proxy-in");
            w.EndArray();
            w.Prop("action", "route");
            w.Prop("outbound", plan.GroupTag);
            w.EndObject();
            foreach (string ip in plan.ServerIps)
            {
                w.StartObject();
                w.Name("ip_cidr").StartArray();
                w.Value(ip + "/32");
                w.EndArray();
                w.Prop("action", "route");
                w.Prop("outbound", plan.GroupTag);
                w.EndObject();
            }
            w.EndArray();
            w.EndObject();

            w.EndObject();
            return w.ToString();
        }
    }
}

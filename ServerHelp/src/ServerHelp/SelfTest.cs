using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using ServerHelp.Core;
using ServerHelp.Net;
using ServerHelp.Tunnel;

namespace ServerHelp
{
    /// <summary>
    /// Headless checks that run before anything is shipped: every configuration the app can generate
    /// is written out and handed to the real sing-box binary with <c>check</c>. A schema mistake in
    /// the tunnel config would otherwise only appear on the user's machine, in the middle of a game.
    ///
    /// Exit code 0 = everything passed. Run with: ServerHelp.exe --selftest
    /// </summary>
    internal static class SelfTest
    {
        public static int Run(string[] args)
        {
            var failures = new List<string>();
            var passes = new List<string>();

            Console.WriteLine("Server Help self test");

            // the engine travels inside the exe, exactly as it does for a user; unpack it first so
            // the configurations can be validated by the real thing
            var runner = new SingBoxRunner();
            string engineError;
            runner.EnsureBinaries(false, null, out engineError);
            Console.WriteLine("engine: " + (File.Exists(AppPaths.SingBoxExe) ? AppPaths.SingBoxExe : "MISSING - " + engineError));
            Console.WriteLine();

            // ---- 1. the connection parser: every shape a user can paste
            CheckParser(failures, passes);

            // ---- 2. an OpenVPN profile: parsing and the endpoint it turns into
            CheckOvpn(failures, passes);

            // ---- 3. every tunnel configuration, validated by the engine itself
            CheckConfigs(failures, passes);

            // ---- 4. the route optimiser plans chains sensibly
            CheckOptimizer(failures, passes);

            Console.WriteLine();
            foreach (string line in passes) Console.WriteLine("  ok    " + line);
            foreach (string line in failures) Console.WriteLine("  FAIL  " + line);
            Console.WriteLine();
            Console.WriteLine(passes.Count + " passed, " + failures.Count + " failed");
            return failures.Count == 0 ? 0 : 1;
        }

        private static void Expect(bool condition, string what, List<string> failures, List<string> passes)
        {
            if (condition) { if (passes.Count < 60) passes.Add(what); }
            else failures.Add(what);
        }

        private static void CheckParser(List<string> failures, List<string> passes)
        {
            string error;
            var socks = ConnectionParser.ParseLine("1.2.3.4:1080", out error);
            Expect(socks != null && socks.Kind == ConnectionKind.Socks5 && socks.Host == "1.2.3.4" && socks.Port == 1080,
                   "plain host:port becomes a SOCKS5 proxy", failures, passes);

            var tg = ConnectionParser.ParseLine("tg://proxy?server=1.2.3.4&port=443&secret=dd0123456789abcdef0123456789abcdef", out error);
            Expect(tg != null && tg.Kind == ConnectionKind.Mtproto && tg.Port == 443,
                   "tg:// link becomes an MTProto entry", failures, passes);

            var dns = ConnectionParser.ParseLine("tls://1.1.1.1:853", out error);
            Expect(dns != null && dns.Kind == ConnectionKind.Dns, "tls:// becomes a DNS entry", failures, passes);

            var wg = ConnectionParser.ParseLine(
                "[Interface]\nPrivateKey = aGVsbG8=\nAddress = 172.16.0.2/32\n[Peer]\nPublicKey = d29ybGQ=\nEndpoint = 5.6.7.8:2408\n",
                out error);
            Expect(wg != null && wg.Kind == ConnectionKind.WireGuard && wg.PeerPort == 2408,
                   "a WireGuard ini becomes an entry", failures, passes);

            var many = ConnectionParser.ParseBlob("1.2.3.4:1080\n5.6.7.8:8080\n", out List<string> problems);
            Expect(many.Count == 2, "two lines become two entries", failures, passes);
        }

        private static void CheckOvpn(List<string> failures, List<string> passes)
        {
            string profile = SampleOvpn() + "cipher AES-256-CBC\nauth SHA256\nkey-direction 1\n" +
                             "tls-auth [inline] 1\n<ca>\n" + SampleCert() + "</ca>\n" +
                             "<tls-auth>\n" + SampleStaticKey() + "</tls-auth>\n";

            OvpnProfile parsed = OvpnProfile.Parse(profile, "");
            Expect(parsed.Ok && parsed.Host == "198.51.100.9" && parsed.Port == 443,
                   ".ovpn remote line becomes the endpoint", failures, passes);
            Expect(parsed.Network == "udp" && parsed.Auth == "SHA256" && parsed.KeyDirection == 1,
                   ".ovpn options are read (proto, auth, key-direction)", failures, passes);
            Expect(parsed.CaCert.Length > 0 && parsed.TlsAuthKey.Length > 0,
                   ".ovpn inline certificates are kept", failures, passes);
            Expect(parsed.NeedsCredentials, ".ovpn asks for an account when it needs one", failures, passes);

            Dictionary<string, object> endpoint = parsed.ToEndpoint("ovpn-1", "user@example.com", "secret");
            Expect(Json.GetStr(endpoint, "type", "") == "openvpn-client" &&
                   Json.GetStr(endpoint, "server", "") == "198.51.100.9" &&
                   Json.GetInt(endpoint, "server_port", 0) == 443,
                   ".ovpn turns into an openvpn-client endpoint", failures, passes);
            var tls = Json.Obj(Json.Get(endpoint, "tls"));
            Expect(tls != null && Json.Get(tls, "certificate") != null && Json.Get(tls, "control_wrap") != null,
                   "the endpoint carries the CA and the tls-auth key", failures, passes);

            string error;
            var entry = ConnectionParser.FromOvpn(profile, "bear-latvia.ovpn", out error);
            Expect(entry != null && entry.Kind == ConnectionKind.OpenVpn && entry.NeedsCredentials,
                   "an .ovpn paste becomes an OpenVPN connection entry", failures, passes);

            var blob = ConnectionParser.ParseBlob(profile, out List<string> problems);
            Expect(blob.Count == 1 && blob[0].Kind == ConnectionKind.OpenVpn,
                   "an .ovpn profile pasted among other lines stays one entry", failures, passes);
        }

        /// <summary>The head of a realistic .ovpn profile without the certificates.</summary>
        private static string SampleOvpn()
        {
            return "client\ndev tun\nproto udp\nremote 198.51.100.9 443\nresolv-retry infinite\n" +
                   "nobind\npersist-key\nremote-cert-tls server\ncomp-lzo no\nverb 3\nauth-user-pass\n";
        }

        /// <summary>A real certificate: the engine parses these fields, so a fake one must not be used.</summary>
        private static string SampleCert()
        {
            return "-----BEGIN CERTIFICATE-----\nMIIDJTCCAg2gAwIBAgIUJqjxjnPDCLJqRNbE4lhswgs6pTYwDQYJKoZIhvcNAQEL\nBQAwIjEgMB4GA1UEAwwXU2VydmVySGVscCBTZWxmIFRlc3QgQ0EwHhcNMjYxMDEy\nMTMwMTQ5WhcNMzYxMDA5MTMwMTQ5WjAiMSAwHgYDVQQDDBdTZXJ2ZXJIZWxwIFNl\nbGYgVGVzdCBDQTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANHP7E9K\nF5myT3bDzb0PhCJU6BAz+akbjun3GaB3hCsc9JiyKcNzzZoSssxdkz56EuADFdG7\nx3N+AZivtr81ooYckV/JdxzQSnWuGXYC5oF2+zj0Yy1/tQ7FkuAsYDeY4SZBObaW\nSZb7EGiBeC40zS5qH7ShYRipHRl98svWZpOaAmR6azy2uqAg1CakhAS09XKlMq0g\n58HiJry3E0VqflrFTgjrz+sAxdbFMnXBKtFW50l8IYBvlqVOlTuslX4co5VAVIpZ\nGrHuj4gY26Uz6FR4so70/UM+cHUWFq7w+VkeWp34sIHYHsrrlw07YQF28SVsAiHm\nAU8UgYajmlEfqZMCAwEAAaNTMFEwHQYDVR0OBBYEFHxpAvR6AMOFrDgUeezy5tnP\ngIAJMB8GA1UdIwQYMBaAFHxpAvR6AMOFrDgUeezy5tnPgIAJMA8GA1UdEwEB/wQF\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAFdVMdr2bfDTGrYub7VreBshDG2PA7Dd\nIIXqr9Aii2XY9SLpiU1r0fQ2+xvYAYIAKVIndWE4Gt46F6GO47eV5/7SXccMeTpf\nt0kkt9UV+vrPyVF8vf6ajET9tP7SaZRKPvSpmVvoAP38xfZOdHBpAQyoT8QVQ2QI\nS+Ng2IZMfcmIW/GFVonWBJru30wxHtZ3L61eAZ4z0YTPZZMo4GjWFejJnBtsGTWJ\n0aIn6ndEvztLikp/xIK41oQAKIzDoYpvlxPri/O8Y8FarjegqFBI8Uc42x9i0pHT\n1wpL3DUZUjjVmU7zApJ29/g02+1e98HCHA4+fFY5HMRo2cCg0odV7Qw=\n-----END CERTIFICATE-----\n";
        }

        private static string SampleStaticKey()
        {
            return "3d989cd1f5e5d405166a7666a053f54a\n2cfe83bb7c79beae2fed1d579f864c53\n4a833c0fc8d57e32dd60a97001d4a0d7\nf8d63f601969f671ff4bd21c8ac5a13e\n8ddc6ea3c50e08d4fa8802fefb7cc524\nfd49200fafc7952df846122134edf9cd\nb69b72120643177033344483d700578c\n4339e94315958dd7a16f408b59097f8d\nefe3f4eea0f19419b50bb71e7d2d9a57\n13d6d03e0a41c8d6c7198281c5c59769\n0e5270184b5bccf07640cb2e0b06e097\nb966bb0e7c5f2b2412db2d440ffd5e81\nfc0a8438d7c1871506ad5afa89d17f7f\n93c18e4d1ddce062327ef09899355200\nf45e14380d72e1c35c9523d53f236028\nf80b7e8ef48c9aa0b3617ea7490871e5\n";
        }

        private static void CheckConfigs(List<string> failures, List<string> passes)
        {
            var settings = new AppSettings();
            var server = new ServerProfile();
            server.Host = "smp3.mcsh.io";
            server.DirectIp = "163.5.201.3";
            server.Port = 11005;

            // ---- a plain proxy route with DNS through the tunnel
            var socks = ConnectionEntry.Create("home socks", ConnectionKind.Socks5);
            socks.Host = "203.0.113.7";
            socks.Port = 1080;

            var plan = new TunnelPlan();
            plan.IncludeTun = true;
            plan.ServerIps.Add("163.5.201.3");
            plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(socks, "hop-1"));
            plan.MemberTags.Add("hop-1");
            plan.RouteTag = "hop-1";
            plan.DnsThroughRoute = true;
            plan.GameDomains.Add("smp3.mcsh.io");
            RunCheck("proxy route with DNS inside the tunnel", SingBoxConfig.Build(plan), failures, passes);

            // ---- a relay chain: the exit is dialled through the entry
            var exit = ConnectionEntry.Create("latvia exit", ConnectionKind.Http);
            exit.Host = "exit.example.net";
            exit.Port = 8080;
            var chainPlan = new TunnelPlan();
            chainPlan.IncludeTun = true;
            chainPlan.ServerIps.Add("163.5.201.3");
            chainPlan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(socks, "hop-1"));
            Dictionary<string, object> exitObject = ConnectionRoute.BuildOutbound(exit, "hop-2");
            exitObject["detour"] = "hop-1";
            chainPlan.ExtraOutbounds.Add(exitObject);
            chainPlan.RouteTag = "hop-2";
            chainPlan.DnsThroughRoute = true;
            RunCheck("two hop relay chain", SingBoxConfig.Build(chainPlan), failures, passes);

            // ---- the OpenVPN route (this is the TunnelBear shape)
            var ovpnEntry = ConnectionEntry.Create("bear", ConnectionKind.OpenVpn);
            ovpnEntry.Host = "198.51.100.9";
            ovpnEntry.Port = 443;
            ovpnEntry.User = "account";
            ovpnEntry.Password = "password";
            OvpnProfile profile = OvpnProfile.Parse(
                SampleOvpn() + "<ca>\n" + SampleCert() + "</ca>\n<tls-auth>\n" + SampleStaticKey() + "</tls-auth>\n", "");
            var ovpnPlan = new TunnelPlan();
            ovpnPlan.IncludeTun = true;
            ovpnPlan.ServerIps.Add("163.5.201.3");
            ovpnPlan.ExtraEndpoints.Add(profile.ToEndpoint("hop-1", ovpnEntry.User, ovpnEntry.Password));
            ovpnPlan.MemberTags.Add("hop-1");
            ovpnPlan.RouteTag = "hop-1";
            ovpnPlan.DnsThroughRoute = true;
            ovpnPlan.DnsOpenVpnTag = "hop-1";
            ovpnPlan.GameDomains.Add("smp3.mcsh.io");
            RunCheck("OpenVPN route with the server pushed resolvers", SingBoxConfig.Build(ovpnPlan), failures, passes);

            // ---- split tunnel without a server address (the DNS only mode)
            var dnsPlan = new TunnelPlan();
            dnsPlan.IncludeTun = false;
            dnsPlan.DnsThroughRoute = true;
            dnsPlan.RouteTag = "direct";
            RunCheck("DNS only mode", SingBoxConfig.Build(dnsPlan), failures, passes);
        }

        private static void CheckOptimizer(List<string> failures, List<string> passes)
        {
            var list = new List<ConnectionEntry>();
            var a = ConnectionEntry.Create("entry", ConnectionKind.Socks5);
            a.Host = "203.0.113.7"; a.Port = 1080; a.LastDelayMs = 30;
            var b = ConnectionEntry.Create("exit", ConnectionKind.Http);
            b.Host = "198.51.100.20"; b.Port = 8080; b.LastDelayMs = 180;
            list.Add(a);
            list.Add(b);

            List<RouteCandidate> candidates = RouteOptimizer.Plan(list, true, 2, false);
            Expect(candidates.Count >= 4, "the optimiser plans direct, single and chained routes", failures, passes);
            bool hasChain = false;
            foreach (RouteCandidate candidate in candidates) if (candidate.IsChain && candidate.Hops == 2) hasChain = true;
            Expect(hasChain, "the optimiser offers a two hop relay", failures, passes);
        }

        /// <summary>Writes the config and asks the bundled engine whether it would run it.</summary>
        private static void RunCheck(string name, string json, List<string> failures, List<string> passes)
        {
            if (!File.Exists(AppPaths.SingBoxExe))
            {
                failures.Add(name + ": the tunnel engine is not bundled, so the configuration cannot be validated");
                return;
            }
            AppPaths.EnsureAll();
            string path = Path.Combine(AppPaths.Cache, "selftest-" + name.Replace(' ', '-') + ".json");
            File.WriteAllText(path, json, new UTF8Encoding(false));
            Shell.Result result = Shell.Run(AppPaths.SingBoxExe, "check -c " + Shell.Quote(path), 30000);
            if (result.Ok) passes.Add(name + " is accepted by the engine");
            else failures.Add(name + " was rejected: " + Short(result.All));
        }

        private static string Short(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            string single = text.Replace("\r", " ").Replace("\n", " ").Trim();
            return single.Length > 300 ? single.Substring(0, 300) : single;
        }
    }
}

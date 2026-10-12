using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using ServerHelp.Core;
using ServerHelp.Tunnel;

namespace ServerHelp.Net
{
    /// <summary>The outcome of one live test, including the real delay of that route.</summary>
    public sealed class ConnectionTestResult
    {
        public bool Ok;
        public int DelayMs = -1;
        public string Status = "";
        public string Detail = "";
        public bool CanCarryGame = true;
        /// <summary>
        /// True when the kind was not measured on purpose inside the one minute budget (it is brought
        /// up at launch instead). A caller must never read this as "it does not work": that mistake
        /// is what used to throw a pinned WireGuard or OpenVPN route away.
        /// </summary>
        public bool Deferred;

        public static ConnectionTestResult Fail(string status, string detail, bool canCarryGame)
        {
            var r = new ConnectionTestResult();
            r.Ok = false;
            r.Status = status;
            r.Detail = detail;
            r.CanCarryGame = canCarryGame;
            return r;
        }
    }

    /// <summary>
    /// Turns a connection entry into the objects a sing-box configuration is made of, and tests one
    /// entry for real (handshake + delay through the actual game path).
    /// </summary>
    public static class ConnectionRoute
    {
        /// <summary>Outbound (or endpoint) object for entries that are used in front of the game.</summary>
        /// <summary>Set from the settings: fragment the handshake even when the entry says nothing.</summary>
        public static bool FragmentTlsByDefault;

        public static Dictionary<string, object> BuildOutbound(ConnectionEntry entry, string tag)
        {
            Dictionary<string, object> outbound = BuildOutboundRaw(entry, tag);
            ApplyTlsFragment(outbound, entry.FragmentTls || FragmentTlsByDefault);
            return outbound;
        }

        /// <summary>
        /// Splits the TLS ClientHello into pieces. On lines where the filter reads the SNI from the
        /// first packet, this is what makes a proxy work without any other change. sing-box supports
        /// it on every outbound that has a tls object.
        /// </summary>
        public static void ApplyTlsFragment(Dictionary<string, object> outbound, bool fragment)
        {
            if (!fragment || outbound == null) return;
            var tls = Json.Obj(Json.Get(outbound, "tls"));
            if (tls == null)
            {
                // drop it on the clean config: nothing else is needed when it never becomes a tunnel
                return;
            }
            tls["fragment"] = true;
            tls["fragment_fallback_delay"] = "500ms";
            tls["record_fragment"] = true;
        }

        private static Dictionary<string, object> BuildOutboundRaw(ConnectionEntry entry, string tag)
        {
            switch (entry.Kind)
            {
                case ConnectionKind.Socks5:
                    {
                        var o = Base("socks", tag, entry.Host, entry.Port);
                        o["version"] = "5";
                        if (!string.IsNullOrEmpty(entry.User)) o["username"] = entry.User;
                        if (!string.IsNullOrEmpty(entry.Password)) o["password"] = entry.Password;
                        return o;
                    }
                case ConnectionKind.Http:
                    {
                        var o = Base("http", tag, entry.Host, entry.Port);
                        if (!string.IsNullOrEmpty(entry.User)) o["username"] = entry.User;
                        if (!string.IsNullOrEmpty(entry.Password)) o["password"] = entry.Password;
                        return o;
                    }
                case ConnectionKind.SingBoxOutbound:
                case ConnectionKind.SingBoxConfig:
                    {
                        var parsed = Json.ParseObject(entry.Config);
                        if (parsed == null) throw new Exception(L.T("کانفیگ JSON خوانده نشد", "the JSON config could not be read"));
                        string type = Json.GetStr(parsed, "type", "");
                        if (string.IsNullOrEmpty(type)) throw new Exception(L.T("کانفیگ بدون فیلد type است", "the config has no type field"));
                        parsed["tag"] = tag;
                        return parsed;
                    }
                default:
                    throw new Exception("this kind cannot be an outbound");
            }
        }

        /// <summary>WireGuard endpoint object built from the fields of a manual entry.</summary>
        public static Dictionary<string, object> BuildEndpoint(ConnectionEntry entry, string tag)
        {
            if (entry.Kind == ConnectionKind.OpenVpn)
            {
                var profile = OvpnProfile.Parse(entry.Config, "");
                if (!profile.Ok) throw new Exception(L.T("فایل .ovpn خط remote ندارد", "the .ovpn profile has no remote line"));
                return profile.ToEndpoint(tag, entry.User, entry.Password);
            }
            if (entry.Kind != ConnectionKind.WireGuard)
                throw new Exception(L.T("این نوع کانفیگ WireGuard نیست", "this entry is not a WireGuard config"));

            var o = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            o["type"] = "wireguard";
            o["tag"] = tag;
            var addresses = new List<object>();
            if (!string.IsNullOrEmpty(entry.Address)) addresses.Add(StripMask(entry.Address) + "/32");
            if (!string.IsNullOrEmpty(entry.AddressV6)) addresses.Add(StripMask(entry.AddressV6) + "/128");
            if (addresses.Count == 0) throw new Exception(L.T("آدرس کلاینت WireGuard تعیین نشده", "the WireGuard client address is not set"));
            o["address"] = addresses;
            if (string.IsNullOrEmpty(entry.Secret)) throw new Exception(L.T("کلید خصوصی WireGuard تعیین نشده", "the WireGuard private key is not set"));
            o["private_key"] = entry.Secret;
            o["mtu"] = (double)(entry.Mtu > 0 ? entry.Mtu : 1280);

            var peer = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            peer["address"] = StripMask(entry.PeerHost);
            peer["port"] = (double)(entry.PeerPort > 0 ? entry.PeerPort : entry.Port);
            peer["public_key"] = entry.PeerPublicKey;
            var allowed = new List<object>();
            allowed.Add("0.0.0.0/0");
            allowed.Add("::/0");
            peer["allowed_ips"] = allowed;
            peer["persistent_keepalive_interval"] = (double)25;
            var reserved = ParseReserved(entry.Reserved);
            if (reserved != null) peer["reserved"] = reserved;

            var peers = new List<object>();
            peers.Add(peer);
            o["peers"] = peers;
            return o;
        }

        private static Dictionary<string, object> Base(string type, string tag, string server, int port)
        {
            if (string.IsNullOrEmpty(server)) throw new Exception(L.T("آدرس سرور خالی است", "the server address is empty"));
            if (port <= 0) throw new Exception(L.T("پورت تعیین نشده", "the port is not set"));
            var o = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            o["type"] = type;
            o["tag"] = tag;
            o["server"] = server;
            o["server_port"] = (double)port;
            return o;
        }

        private static List<object> ParseReserved(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            var parts = text.Split(new char[] { ',', ' ', ';' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 3) return null;
            var list = new List<object>();
            foreach (string part in parts)
            {
                int value;
                if (!int.TryParse(part.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out value)) return null;
                if (value < 0 || value > 255) return null;
                list.Add((double)value);
            }
            return list;
        }

        private static string StripMask(string address)
        {
            if (string.IsNullOrEmpty(address)) return "";
            int slash = address.IndexOf('/');
            return (slash > 0 ? address.Substring(0, slash) : address).Trim();
        }

        public static string TagFor(ConnectionEntry entry)
        {
            return "conn-" + (string.IsNullOrEmpty(entry.Id) ? ConnectionEntry.NewId() : entry.Id);
        }
    }

    /// <summary>
    /// Runs the real test of one connection. Nothing here changes the machine: everything either
    /// talks through a proxy socket or starts a throwaway sing-box with a local SOCKS port only.
    /// </summary>
    public static class ConnectionTester
    {
        /// <param name="quick">Only cheap tests: used inside the one minute launch budget.</param>
        public static ConnectionTestResult Test(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs, bool quick)
        {
            var result = new ConnectionTestResult();
            if (entry == null) return ConnectionTestResult.Fail(L.T("ورودی خالی", "empty entry"), "", true);

            string missing = entry.Missing();
            if (missing.Length > 0)
                return ConnectionTestResult.Fail(L.T("ناقص", "incomplete"), L.T("این فیلدها لازم است: ", "these fields are required: ") + missing, entry.CanCarryGame);

            try
            {
                switch (entry.Kind)
                {
                    case ConnectionKind.Dns:
                        return TestDns(entry, targetHost, timeoutMs);
                    case ConnectionKind.Mtproto:
                        return TestMtproto(entry, timeoutMs);
                    case ConnectionKind.Socks5:
                        return TestSocks5(entry, targetHost, targetPort, timeoutMs);
                    case ConnectionKind.Http:
                        return TestHttp(entry, targetHost, targetPort, timeoutMs);
                    case ConnectionKind.WireGuard:
                        return TestSingBoxRoute(entry, targetHost, targetPort, timeoutMs, quick);
                    case ConnectionKind.SingBoxOutbound:
                        return TestSingBoxRoute(entry, targetHost, targetPort, timeoutMs, quick);
                    case ConnectionKind.SingBoxConfig:
                        return TestFullConfig(entry, targetHost, targetPort, timeoutMs, quick);
                    case ConnectionKind.Warp:
                        return TestWarp(entry, targetHost, targetPort, timeoutMs, quick);
                    default:
                        return ConnectionTestResult.Fail(L.T("نوع ناشناخته", "unknown kind"), "", true);
                }
            }
            catch (Exception ex)
            {
                // A test always answers: any surprise in a pasted config or in the engine comes back
                // as a failed result, because the callers (dialog, table, pipeline) have no handler
                // for an exception thrown on their worker thread.
                return ConnectionTestResult.Fail(L.T("تست شکست خورد", "the test failed"), ex.Message, entry.CanCarryGame);
            }
        }

        // ------------------------------------------------------------------ cheap kinds

        private static ConnectionTestResult TestDns(ConnectionEntry entry, string targetHost, int timeoutMs)
        {
            var answer = DnsClient.Resolve(entry.DnsUrl, targetHost, timeoutMs);
            var result = new ConnectionTestResult();
            result.CanCarryGame = false;
            result.Ok = answer.Ok;
            result.DelayMs = answer.ElapsedMs;
            result.Status = answer.Ok ? L.T("رزولو شد", "resolved") : L.T("بی‌پاسخ", "no answer");
            result.Detail = answer.Ok
                ? targetHost + " → " + string.Join(", ", answer.Addresses.ToArray())
                : answer.Error;
            return result;
        }

        /// <summary>
        /// Real MTProto check: obfuscated2 / fake-TLS handshake plus req_pq_multi -> resPQ. Only a
        /// proxy that really forwards to Telegram can pass, so this is proof, not a guess.
        /// </summary>
        private static ConnectionTestResult TestMtproto(ConnectionEntry entry, int timeoutMs)
        {
            var probe = MtprotoProbe.Test(entry.Host, entry.Port, entry.Secret, entry.Dc, timeoutMs);
            var result = new ConnectionTestResult();
            result.CanCarryGame = false;
            result.Ok = probe.Ok;
            result.DelayMs = probe.Connected ? probe.DelayMs : -1;
            result.Status = probe.Ok
                ? (probe.Status.Length > 0 ? probe.Status : L.T("تأیید شد", "verified"))
                : (probe.Connected ? probe.Status : L.T("وصل نشد", "unreachable"));
            result.Detail = probe.Detail +
                            " • " + L.T("حالت: ", "mode: ") + probe.Mode +
                            (probe.Domain.Length > 0 ? " • " + L.T("دامنه: ", "domain: ") + probe.Domain : "") +
                            (probe.Ok ? " • DC" + probe.Dc : "") +
                            " • " + L.T("فقط تلگرام؛ بازی از آن عبور نمی‌کند.", "Telegram only; the game cannot go through it.");
            return result;
        }

        private static ConnectionTestResult TestSocks5(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs)
        {
            var proxy = new Socks5Client(entry.Host, entry.Port, entry.User, entry.Password, timeoutMs);
            long start = DateTime.UtcNow.Ticks;
            try
            {
                using (Socket socket = proxy.Connect(string.IsNullOrEmpty(targetHost) ? "1.1.1.1" : targetHost,
                                                     string.IsNullOrEmpty(targetHost) ? 443 : targetPort))
                {
                    int handshake = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    socket.Close();
                    return MeasureThrough(entry, proxy, targetHost, targetPort, timeoutMs, handshake,
                                          L.T("پروکسی SOCKS5 کار می‌کند", "the SOCKS5 proxy works"));
                }
            }
            catch (Exception ex)
            {
                return ConnectionTestResult.Fail(L.T("قطع", "failed"), ex.Message, entry.CanCarryGame);
            }
        }

        private static ConnectionTestResult TestHttp(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs)
        {
            var proxy = new HttpProxyClient(entry.Host, entry.Port, entry.User, entry.Password, timeoutMs);
            long start = DateTime.UtcNow.Ticks;
            try
            {
                using (Socket socket = proxy.Connect(string.IsNullOrEmpty(targetHost) ? "1.1.1.1" : targetHost,
                                                     string.IsNullOrEmpty(targetHost) ? 443 : targetPort))
                {
                    int handshake = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    socket.Close();
                    return MeasureThrough(entry, proxy, targetHost, targetPort, timeoutMs, handshake,
                                          L.T("پروکسی HTTP کار می‌کند", "the HTTP proxy works"));
                }
            }
            catch (Exception ex)
            {
                return ConnectionTestResult.Fail(L.T("قطع", "failed"), ex.Message, entry.CanCarryGame);
            }
        }

        /// <summary>
        /// Measures the game path through a working connector: the Minecraft ping first (that is the
        /// number the player cares about), then a plain TCP connect as a fallback.
        /// </summary>
        private static ConnectionTestResult MeasureThrough(ConnectionEntry entry, IConnector connector,
                                                          string targetHost, int targetPort, int timeoutMs,
                                                          int handshakeMs, string okStatus)
        {
            var result = new ConnectionTestResult();
            result.Ok = true;
            result.CanCarryGame = entry.CanCarryGame;
            result.DelayMs = handshakeMs;
            result.Status = okStatus;
            result.Detail = L.T("دست‌دادن: ", "handshake: ") + L.N(handshakeMs) + " ms";

            if (string.IsNullOrEmpty(targetHost)) return result;

            var status = McPing.Status(targetHost, targetPort, Math.Min(4000, timeoutMs), connector);
            if (status != null && status.Ok)
            {
                result.DelayMs = status.LatencyMs;
                result.Status = L.T("بازی از این مسیر", "game path");
                result.Detail = L.T("پینگ بازی: ", "game ping: ") + L.N(status.LatencyMs) + " ms" +
                                (string.IsNullOrEmpty(status.Motd) ? "" : " • " + status.Motd);
                return result;
            }

            long start = DateTime.UtcNow.Ticks;
            try
            {
                using (Socket socket = connector.Connect(targetHost, targetPort)) socket.Close();
                int tcp = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                result.DelayMs = tcp;
                result.Status = L.T("TCP از این مسیر", "TCP path");
                result.Detail = L.T("سرور بازی به پینگ Minecraft جواب نداد، ولی اتصال TCP برقرار شد: ",
                                    "the game server did not answer the Minecraft ping, but the TCP connection worked: ") +
                                L.N(tcp) + " ms";
                return result;
            }
            catch (Exception ex)
            {
                // The proxy works but the game server is not reachable through it: that is
                // important to report separately.
                result.Status = L.T("پروکسی سالم، سرور نه", "proxy fine, server not");
                result.Detail = L.T("پروکسی جواب داد ولی سرور بازی از این مسیر پاسخ نداد: ",
                                    "the proxy answered but the game server did not respond through it: ") +
                                ex.Message + " • " + (status != null ? status.Error : "");
                return result;
            }
        }

        // ------------------------------------------------------------------ started routes

        private static ConnectionTestResult TestSingBoxRoute(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs, bool quick)
        {
            var result = new ConnectionTestResult();
            result.CanCarryGame = true;
            if (quick)
            {
                result.Ok = false;
                result.Deferred = true;
                result.Status = L.T("در بودجه یک‌دقیقه‌ای تست نشد", "not tested inside the one minute budget");
                result.Detail = L.T("این نوع اتصال هنگام اجرا بالا می‌آید؛ برای تست کامل در تب اتصالات دکمه تست را بزنید.",
                                    "this kind is brought up at launch time; press Test in the Connections tab for a full test.");
                return result;
            }

            int port = ProbeTunnel.NextPort();
            var plan = new TunnelPlan();
            plan.IncludeTun = false;                     // a test must not touch routes
            plan.SocksPort = port;
            plan.ClashController = "";                   // no extra listener while probing
            plan.LogPath = "";
            plan.BuildUrlTest = false;
            string tag = ConnectionRoute.TagFor(entry);
            try
            {
                if (entry.Kind == ConnectionKind.WireGuard || entry.Kind == ConnectionKind.OpenVpn)
                    plan.ExtraEndpoints.Add(ConnectionRoute.BuildEndpoint(entry, tag));
                else plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(entry, tag));
            }
            catch (Exception ex)
            {
                return ConnectionTestResult.Fail(L.T("کانفیگ ناقص", "incomplete config"), ex.Message, true);
            }
            plan.RouteTag = tag;

            string error;
            string json = SingBoxConfig.Build(plan);
            ProbeTunnel probe;
            if (!ProbeTunnel.TryStart(json, port, Math.Max(3000, timeoutMs * 2), out probe, out error))
                return ConnectionTestResult.Fail(L.T("بالا نیامد", "did not start"), error, true);

            try
            {
                var proxy = new Socks5Client("127.0.0.1", port, Math.Min(5000, timeoutMs));
                return MeasureThrough(entry, proxy, targetHost, targetPort, timeoutMs, 0,
                                      L.T("کانفیگ بالا آمد", "the config started"));
            }
            finally
            {
                probe.Stop();
            }
        }

        private static ConnectionTestResult TestFullConfig(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs, bool quick)
        {
            var result = new ConnectionTestResult();
            result.CanCarryGame = true;
            if (quick)
            {
                result.Ok = false;
                result.Deferred = true;
                result.Status = L.T("در بودجه یک‌دقیقه‌ای تست نشد", "not tested inside the one minute budget");
                result.Detail = L.T("کانفیگ کامل هنگام اجرا بالا می‌آید.", "the full config is brought up at launch time.");
                return result;
            }

            Dictionary<string, object> parsed;
            try { parsed = Json.ParseObject(entry.Config); }
            catch (Exception ex) { return ConnectionTestResult.Fail(L.T("JSON نامعتبر", "invalid JSON"), ex.Message, true); }

            if (HasTunInbound(entry.Config))
            {
                // Starting it would create a TUN interface, which is exactly what a *test* must not
                // do, so only the configuration itself is verified here. The copy that check runs on
                // is thrown away again: a user's configuration carries their proxies and passwords,
                // and a test must not leave a second copy of that lying in the cache folder.
                string checkPath = WriteTempConfig(entry.Config);
                try
                {
                    var check = Shell.Run(AppPaths.SingBoxExe, "check -c " + Shell.Quote(checkPath), 20000);
                    result.Ok = check.Ok;
                    result.Status = check.Ok ? L.T("کانفیگ معتبر (TUN)", "valid config (TUN)") : L.T("کانفیگ نامعتبر", "invalid config");
                    result.Detail = check.Ok
                        ? L.T("این کانفیگ اینترفیس TUN می‌سازد، پس در تست اجرا نشد تا مسیرهای ویندوز دست‌نخورده بماند؛ هنگام بازی خودش بالا می‌آید.",
                              "this config creates a TUN interface, so it was not started during the test to keep the Windows routing untouched; it comes up when you play.")
                        : Shorten(check.All);
                    return result;
                }
                finally { DeleteQuietly(checkPath); }
            }

            int port = ProbeTunnel.NextPort();
            string rewritten = RewriteSocksPort(entry.Config, port);
            string error;
            ProbeTunnel probe;
            if (!ProbeTunnel.TryStart(rewritten, port, Math.Max(3000, timeoutMs * 2), out probe, out error))
                return ConnectionTestResult.Fail(L.T("بالا نیامد", "did not start"), error, true);

            try
            {
                var proxy = new Socks5Client("127.0.0.1", port, Math.Min(5000, timeoutMs));
                return MeasureThrough(entry, proxy, targetHost, targetPort, timeoutMs, 0,
                                      L.T("کانفیگ بالا آمد", "the config started"));
            }
            finally
            {
                probe.Stop();
            }
        }

        private static ConnectionTestResult TestWarp(ConnectionEntry entry, string targetHost, int targetPort, int timeoutMs, bool quick)
        {
            var result = new ConnectionTestResult();
            result.CanCarryGame = true;

            if (!System.IO.File.Exists(AppPaths.SingBoxExe))
                return ConnectionTestResult.Fail(L.T("موتور تونل نیست", "engine missing"),
                    L.T("یک‌بار برنامه را اجرا کنید تا sing-box دانلود شود.", "run the app once so sing-box is fetched."), true);

            WarpCredentials credentials = WarpAccount.Load();
            if (credentials == null && quick)
            {
                result.Ok = false;
                result.Deferred = true;
                result.Status = L.T("حساب WARP ساخته نشده", "no WARP account yet");
                result.Detail = L.T("هنگام اجرا ساخته می‌شود.", "it is created at launch time.");
                return result;
            }
            if (credentials == null)
            {
                string privateKey, publicKey, error;
                var runner = new SingBoxRunner();
                if (!runner.GenerateKeyPair(out privateKey, out publicKey, out error))
                    return ConnectionTestResult.Fail(L.T("کلید ساخته نشد", "key generation failed"), error, true);
                credentials = WarpAccount.Register(privateKey, publicKey, out error);
                if (credentials == null)
                    return ConnectionTestResult.Fail(L.T("ثبت WARP نشد", "WARP registration failed"), error, true);
            }

            var scan = EndpointScanner.Scan(Math.Min(2000, Math.Max(800, timeoutMs)), null, null);
            var best = WarpEndpoints.PickBest(scan.Endpoints, quick ? 2 : 4);
            if (best.Count == 0)
                return ConnectionTestResult.Fail(L.T("آدرس WARP پیدا نشد", "no reachable WARP address"), "", true);

            int port = ProbeTunnel.NextPort();
            var plan = new TunnelPlan();
            plan.Credentials = credentials;
            plan.Endpoints = best;
            plan.IncludeTun = false;
            plan.SocksPort = port;
            plan.ClashController = "";
            plan.LogPath = "";
            plan.BuildUrlTest = best.Count > 1;

            string json = SingBoxConfig.Build(plan);
            string error2;
            ProbeTunnel probe;
            if (!ProbeTunnel.TryStart(json, port, Math.Max(4000, timeoutMs * 2), out probe, out error2))
                return ConnectionTestResult.Fail(L.T("تونل بالا نیامد", "the tunnel did not start"), error2, true);

            try
            {
                var proxy = new Socks5Client("127.0.0.1", port, Math.Min(6000, timeoutMs));
                var measured = MeasureThrough(entry, proxy, targetHost, targetPort, timeoutMs, 0,
                                              L.T("تونل WARP بالا آمد", "the WARP tunnel is up"));
                measured.Detail += " • " + L.T("آدرس‌های تست‌شده: ", "endpoints probed: ") + best.Count.ToString(CultureInfo.InvariantCulture);
                return measured;
            }
            finally
            {
                probe.Stop();
            }
        }

        // ------------------------------------------------------------------ helpers

        /// <summary>
        /// True when a pasted full config would create a TUN interface. Neither a test nor a quick
        /// fetch may start one: that is a change to the machine, and the user did not ask for it.
        /// </summary>
        public static bool HasTunInbound(string configJson)
        {
            try
            {
                var parsed = Json.ParseObject(configJson);
                var inbounds = Json.Arr(Json.Get(parsed, "inbounds"));
                if (inbounds == null) return false;
                foreach (object item in inbounds)
                {
                    var inbound = Json.Obj(item);
                    if (inbound != null && Json.GetStr(inbound, "type", "") == "tun") return true;
                }
            }
            catch { }
            return false;
        }

        /// <summary>Rewrites the local socks port of a full config so it can run beside the live session.</summary>
        public static string RewriteSocksPort(string configJson, int port)
        {
            try
            {
                var parsed = Json.ParseObject(configJson);
                var inbounds = Json.Arr(Json.Get(parsed, "inbounds"));
                if (inbounds == null) return configJson;
                bool changed = false;
                foreach (object item in inbounds)
                {
                    var inbound = Json.Obj(item);
                    if (inbound == null) continue;
                    string type = Json.GetStr(inbound, "type", "");
                    if (type != "mixed" && type != "socks" && type != "http") continue;
                    if (!changed)
                    {
                        inbound["listen_port"] = (double)port;
                        changed = true;
                    }
                }
                return changed ? Json.Serialize(parsed) : configJson;
            }
            catch { return configJson; }
        }

        /// <summary>
        /// Removes a throwaway file. The shared configuration is never touched: it is owned by the
        /// launch pipeline, and that is also what WriteTempConfig falls back to when writing fails.
        /// </summary>
        private static void DeleteQuietly(string path)
        {
            try
            {
                if (string.IsNullOrEmpty(path)) return;
                if (string.Equals(path, AppPaths.SingBoxConfig, StringComparison.OrdinalIgnoreCase)) return;
                if (System.IO.File.Exists(path)) System.IO.File.Delete(path);
            }
            catch { }
        }

        private static string WriteTempConfig(string json)
        {
            try
            {
                AppPaths.EnsureAll();
                string path = System.IO.Path.Combine(AppPaths.Cache, "probe-check-" + Guid.NewGuid().ToString("N").Substring(0, 6) + ".json");
                System.IO.File.WriteAllText(path, json, new System.Text.UTF8Encoding(false));
                return path;
            }
            catch { return AppPaths.SingBoxConfig; }
        }

        private static string Shorten(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            text = text.Replace("\r", " ").Replace("\n", " ").Trim();
            return text.Length <= 240 ? text : text.Substring(0, 240) + "…";
        }
    }
}

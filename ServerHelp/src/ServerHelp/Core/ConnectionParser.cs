using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>
    /// Reads a connection in almost any shape the user may paste into the app: plain
    /// host:port[:secret] lines, SOCKS5/HTTP/MTProto URLs, DNS servers (udp/tcp/DoT/DoH),
    /// WireGuard (wg-quick ini or JSON), full sing-box configs and the usual share links
    /// (vless/vmess/trojan/shadowsocks/hysteria2/tuic) which are turned into sing-box outbounds.
    /// </summary>
    public static class ConnectionParser
    {
        /// <summary>Parses a whole text block; unparsable lines land in <paramref name="errors"/>.</summary>
        public static List<ConnectionEntry> ParseMany(string text, out List<string> errors)
        {
            return ParseBlob(text, out errors);
        }

        /// <summary>
        /// Reads a whole blob: one entry per line, a multi line sing-box/WireGuard config, or a
        /// base64 subscription (the format every proxy seller hands out). Every failed line is
        /// reported instead of being dropped silently.
        /// </summary>
        public static List<ConnectionEntry> ParseBlob(string text, out List<string> problems)
        {
            var entries = new List<ConnectionEntry>();
            problems = new List<string>();
            if (string.IsNullOrEmpty(text)) return entries;

            string cleaned = text.Replace("\r\n", "\n").Replace("\r", "\n").Trim();
            if (cleaned.Length == 0) return entries;

            // a subscription is one big base64 blob
            string decoded = TryDecodeBase64Blob(cleaned);
            if (decoded != null) cleaned = decoded;

            var lines = new List<string>(cleaned.Split('\n'));
            var buffer = new List<string>();
            int depth = 0;

            foreach (string rawLine in lines)
            {
                string line = rawLine.Trim();
                if (line.Length == 0)
                {
                    if (buffer.Count > 0) Flush(buffer, entries, problems);
                    continue;
                }
                if (line.StartsWith("#") || line.StartsWith("//")) continue;

                bool startsJson = line.StartsWith("{");
                bool startsIni = line.Equals("[Interface]", StringComparison.OrdinalIgnoreCase);
                bool startsEntry = LooksLikeNewEntry(line);

                if (buffer.Count == 0)
                {
                    if (startsJson || startsIni)
                    {
                        buffer.Add(line);
                        depth += CountBraces(line);
                        if (startsJson && depth <= 0) Flush(buffer, entries, problems);
                        continue;
                    }
                    ConnectionEntry single = ParseLine(line, out string error);
                    if (single != null) entries.Add(single);
                    else if (error.Length > 0) problems.Add(Trim(line, 40) + " — " + error);
                    continue;
                }

                // we are inside a multi line block
                bool inJson = buffer[0].StartsWith("{");
                if (startsEntry && !inJson && !startsIni)
                {
                    Flush(buffer, entries, problems);           // the ini ended, a new entry began
                    ConnectionEntry single = ParseLine(line, out string error);
                    if (single != null) entries.Add(single);
                    else if (error.Length > 0) problems.Add(Trim(line, 40) + " — " + error);
                    continue;
                }

                buffer.Add(line);
                if (inJson)
                {
                    depth += CountBraces(line);
                    if (depth <= 0) Flush(buffer, entries, problems);
                }
            }
            if (buffer.Count > 0) Flush(buffer, entries, problems);

            if (entries.Count == 0 && problems.Count == 0)
                problems.Add(L.T("چیزی برای افزودن پیدا نشد", "nothing could be imported"));
            return entries;
        }

        /// <summary>Crosses the line out as "a new entry starts here" (share link, URI, host:port).</summary>
        private static bool LooksLikeNewEntry(string line)
        {
            if (line.StartsWith("tg://") || line.StartsWith("mtproto://") || line.StartsWith("wireguard://")) return true;
            if (line.StartsWith("vless://") || line.StartsWith("vmess://") || line.StartsWith("trojan://") ||
                line.StartsWith("ss://") || line.StartsWith("hysteria2://") || line.StartsWith("hy2://") ||
                line.StartsWith("tuic://") || line.StartsWith("socks5://") || line.StartsWith("socks://")) return true;
            if (line.StartsWith("http://") || line.StartsWith("https://")) return true;
            if (line.IndexOf('=') >= 0) return false;              // key = value, part of an ini
            return false;
        }

        private static int CountBraces(string line)
        {
            int open = 0, close = 0;
            for (int i = 0; i < line.Length; i++)
            {
                if (line[i] == '{') open++;
                else if (line[i] == '}') close++;
            }
            return open - close;
        }

        private static void Flush(List<string> buffer, List<ConnectionEntry> entries, List<string> problems)
        {
            string block = string.Join("\n", buffer.ToArray());
            buffer.Clear();
            if (block.Trim().Length == 0) return;
            ConnectionEntry entry = ParseLine(block, out string error);
            if (entry != null) entries.Add(entry);
            else if (error.Length > 0) problems.Add(Trim(block, 40) + " — " + error);
        }

        // ------------------------------------------------------------------ files

        /// <summary>Writes the whole list to a JSON file the app can read back on another machine.</summary>
        public static string SerializeList(List<ConnectionEntry> entries)
        {
            var writer = new JsonWriter(true);
            writer.StartObject();
            writer.Prop("app", "ServerHelp");
            writer.Prop("version", 1);
            writer.Prop("saved", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            writer.PropName("connections");
            writer.StartArray();
            foreach (ConnectionEntry entry in entries) entry.WriteTo(writer);
            writer.EndArray();
            writer.EndObject();
            return writer.ToString();
        }

        public static List<ConnectionEntry> ParseListFile(string json, out string error)
        {
            error = "";
            var list = new List<ConnectionEntry>();
            try
            {
                Dictionary<string, object> root = Json.ParseObject(json);
                if (root == null) { error = L.T("فایل JSON خوانده نشد", "the JSON file cannot be read"); return list; }
                object raw = Json.Get(root, "connections");
                List<object> array = Json.Arr(raw);
                if (array == null) { error = L.T("کلید connections در فایل نیست", "the file has no connections key"); return list; }
                foreach (object item in array)
                {
                    ConnectionEntry entry = ConnectionEntry.Read(Json.Obj(item));
                    if (entry != null) list.Add(entry);
                }
                if (list.Count == 0) error = L.T("فایل خالی است", "the file is empty");
            }
            catch (Exception ex)
            {
                error = ex.Message;
            }
            return list;
        }

        /// <summary>Subscriptions are base64; returns the decoded text or null when it is not one.</summary>
        public static string TryDecodeBase64Blob(string text)
        {
            string compact = text.Replace(" ", "").Replace("\n", "").Replace("\t", "").Replace("-", "+").Replace("_", "/");
            if (compact.Length < 32) return null;
            bool looksBase64 = true;
            for (int i = 0; i < compact.Length; i++)
            {
                char c = compact[i];
                bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '+' || c == '/' || c == '=';
                if (!ok) { looksBase64 = false; break; }
            }
            if (!looksBase64) return null;
            try
            {
                while (compact.Length % 4 != 0) compact += "=";
                byte[] bytes = Convert.FromBase64String(compact);
                string decoded = System.Text.Encoding.UTF8.GetString(bytes);
                // only treat it as a subscription when the result really holds links or JSON
                if (decoded.Contains("://") || decoded.Contains("[Interface]") || decoded.Contains("outbounds"))
                    return decoded;
                return null;
            }
            catch { return null; }
        }

        /// <summary>A single line. Never throws: the reason lands in <paramref name="error"/>.</summary>
        public static ConnectionEntry ParseLine(string line, out string error)
        {
            error = "";
            if (string.IsNullOrEmpty(line)) { error = ""; return null; }
            string text = line.Trim();

            try
            {
                if (text.StartsWith("{")) return FromJson(text, out error);
                if (text.StartsWith("[") && text.IndexOf("[Interface]", StringComparison.OrdinalIgnoreCase) >= 0)
                    return FromWireGuardIni(text, out error);

                string lower = text.ToLowerInvariant();

                if (lower.StartsWith("tg://") || lower.StartsWith("mtproto://") ||
                    lower.StartsWith("https://t.me/proxy") || lower.StartsWith("http://t.me/proxy") ||
                    lower.StartsWith("t.me/proxy")) return FromMtprotoUri(text, out error);
                if (lower.StartsWith("vless://")) return FromVless(text, out error);
                if (lower.StartsWith("vmess://")) return FromVmess(text, out error);
                if (lower.StartsWith("trojan://")) return FromTrojan(text, out error);
                if (lower.StartsWith("ss://")) return FromShadowsocks(text, out error);
                if (lower.StartsWith("hysteria2://") || lower.StartsWith("hy2://")) return FromHysteria2(text, out error);
                if (lower.StartsWith("tuic://")) return FromTuic(text, out error);

                if (lower.StartsWith("tls://") || lower.StartsWith("dot://")) return FromDnsServer(text, "tls", out error);
                if (lower.StartsWith("udp://")) return FromDnsServer(text, "udp", out error);
                if (lower.StartsWith("tcp://")) return FromDnsServer(text, "tcp", out error);
                if (lower.StartsWith("dns://")) return FromDnsServer(text, "udp", out error);
                if (lower.StartsWith("doh://")) return FromDnsServer(text.Replace("doh://", "https://"), "https", out error);
                if (lower.StartsWith("https://") && LooksLikeDoh(text)) return FromDnsServer(text, "https", out error);
                if (lower.StartsWith("http://") || lower.StartsWith("https://")) return FromHttpProxy(text, out error);
                if (lower.StartsWith("socks5://") || lower.StartsWith("socks5h://") || lower.StartsWith("socks://"))
                    return FromSocksUri(text, out error);
                if (lower.StartsWith("wireguard://")) return FromWireGuardUri(text, out error);

                return FromPlain(text, out error);
            }
            catch (Exception ex)
            {
                error = L.T("خوانده نشد: ", "could not be read: ") + ex.Message + "  [" + Trim(text, 60) + "]";
                return null;
            }
        }

        // ------------------------------------------------------------------ plain lines

        private static ConnectionEntry FromPlain(string text, out string error)
        {
            error = "";
            string[] parts = text.Split(':');
            if (parts.Length >= 3 && IsPort(parts[1]) && LooksLikeSecret(parts[2]))
            {
                // Telegram shares its proxies as server:port:secret
                var e = ConnectionEntry.Create("MTProto " + parts[0], ConnectionKind.Mtproto);
                e.Host = parts[0];
                e.Port = int.Parse(parts[1], CultureInfo.InvariantCulture);
                e.Secret = parts[2];
                MtprotoSecret shared = MtprotoSecret.Parse(parts[2]);
                if (!shared.Ok)
                {
                    error = L.T("سکرت MTProto خوانده نشد: ", "the MTProto secret cannot be read: ") + shared.Error;
                    return null;
                }
                e.Name = "MTProto " + shared.ModeTitle + " " + parts[0];
                if (shared.Mode == MtprotoMode.FakeTls && shared.Domain.Length > 0)
                    e.Notes = L.T("دامنه: ", "domain: ") + shared.Domain;
                return e;
            }
            if (parts.Length == 4 && IsPort(parts[1]))
            {
                var e = ConnectionEntry.Create("SOCKS5 " + parts[0], ConnectionKind.Socks5);
                e.Host = parts[0];
                e.Port = int.Parse(parts[1], CultureInfo.InvariantCulture);
                e.User = parts[2];
                e.Password = parts[3];
                return e;
            }
            if (parts.Length == 1 && IsIp(text)) return MakeDns("udp://" + text + ":53");
            if (parts.Length == 2 && IsPort(parts[1]))
            {
                int port = int.Parse(parts[1], CultureInfo.InvariantCulture);
                if (port == 53 || port == 853) return MakeDns((port == 853 ? "tls://" : "udp://") + parts[0] + ":" + port);
                var e = ConnectionEntry.Create("SOCKS5 " + parts[0], ConnectionKind.Socks5);
                e.Host = parts[0];
                e.Port = port;
                e.Notes = L.T("نوع پیش‌فرض SOCKS5 است؛ اگر پروکسی HTTP یا DNS است نوع را تغییر دهید.",
                              "Assumed SOCKS5; change the kind if this is an HTTP proxy or a DNS server.");
                return e;
            }
            error = L.T("الگو شناسایی نشد: ", "unrecognised format: ") + Trim(text, 60);
            return null;
        }

        private static bool LooksLikeDoh(string url)
        {
            string lower = url.ToLowerInvariant();
            if (lower.IndexOf("/dns-query", StringComparison.Ordinal) >= 0) return true;
            if (lower.IndexOf("/resolve", StringComparison.Ordinal) >= 0) return true;
            if (lower.IndexOf("dns-json", StringComparison.Ordinal) >= 0) return true;
            return false;
        }

        // ------------------------------------------------------------------ proxies

        private static ConnectionEntry FromSocksUri(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var e = ConnectionEntry.Create("SOCKS5", ConnectionKind.Socks5);
            e.Host = uri.Host;
            e.Port = uri.Port > 0 ? uri.Port : 1080;
            ParseUserInfo(uri, e);
            if (string.IsNullOrEmpty(e.Host)) { error = L.T("آدرس پروکسی خالی است", "the proxy address is empty"); return null; }
            Label(e, uri, "SOCKS5");
            return e;
        }

        private static ConnectionEntry FromHttpProxy(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var e = ConnectionEntry.Create("HTTP", ConnectionKind.Http);
            e.Host = uri.Host;
            e.Port = uri.Port > 0 ? uri.Port : 8080;
            ParseUserInfo(uri, e);
            if (string.IsNullOrEmpty(e.Host)) { error = L.T("آدرس پروکسی خالی است", "the proxy address is empty"); return null; }
            Label(e, uri, "HTTP");
            return e;
        }

        private static ConnectionEntry FromMtprotoUri(string text, out string error)
        {
            error = "";
            var query = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            string host = "";
            int port = 443;

            if (text.ToLowerInvariant().StartsWith("tg://"))
            {
                query = ParseQuery(text.Substring(text.IndexOf('?') + 1));
                host = Get(query, "server");
                port = ParseInt(Get(query, "port"), 443);
            }
            else
            {
                int at = text.IndexOf("://", StringComparison.Ordinal) + 3;
                string rest = text.Substring(at);
                int hash = rest.IndexOf('#');
                if (hash >= 0) rest = rest.Substring(0, hash);
                int q = rest.IndexOf('?');
                if (q >= 0) { query = ParseQuery(rest.Substring(q + 1)); rest = rest.Substring(0, q); }
                int colon = rest.LastIndexOf(':');
                if (colon > 0) { host = rest.Substring(0, colon); port = ParseInt(rest.Substring(colon + 1), 443); }
                else host = rest;
            }

            string secret = Get(query, "secret");
            if (string.IsNullOrEmpty(host) || string.IsNullOrEmpty(secret))
            {
                error = L.T("پروکسی MTProto بدون server/secret", "MTProto proxy without server/secret");
                return null;
            }
            var e = ConnectionEntry.Create("MTProto " + host, ConnectionKind.Mtproto);
            e.Host = host;
            e.Port = port;
            e.Secret = secret;
            e.Dc = ParseInt(Get(query, "dc"), 2);
            if (e.Dc < 1 || e.Dc > 5) e.Dc = 2;

            MtprotoSecret parsed = MtprotoSecret.Parse(secret);
            if (!parsed.Ok)
            {
                error = L.T("سکرت MTProto خوانده نشد: ", "the MTProto secret cannot be read: ") + parsed.Error;
                return null;
            }
            string name = Get(query, "name");
            e.Name = string.IsNullOrEmpty(name)
                ? "MTProto " + parsed.ModeTitle + " " + host
                : "MTProto " + name;
            e.Notes = L.T("پروکسی تلگرام (", "Telegram proxy (") + parsed.ModeTitle + ") — " +
                      L.T("با پروتکل واقعی تست می‌شود ولی نمی‌تواند ترافیک بازی را حمل کند.",
                          "it is verified with the real protocol, but it cannot carry the game traffic.");
            if (parsed.Mode == MtprotoMode.FakeTls && parsed.Domain.Length > 0)
                e.Notes += " " + L.T("دامنه: ", "domain: ") + parsed.Domain;
            return e;
        }

        // ------------------------------------------------------------------ dns

        private static ConnectionEntry FromDnsServer(string text, string scheme, out string error)
        {
            error = "";
            var e = ConnectionEntry.Create("DNS", ConnectionKind.Dns);
            e.UseForGame = false;

            if (scheme == "https")
            {
                e.DnsUrl = text.TrimEnd('/');
                if (!e.DnsUrl.StartsWith("http", StringComparison.OrdinalIgnoreCase)) e.DnsUrl = "https://" + e.DnsUrl;
                Label(e, new Uri(e.DnsUrl), "DNS over HTTPS");
                return e;
            }

            string rest = text.Substring(text.IndexOf("://", StringComparison.Ordinal) + 3);
            int slash = rest.IndexOf('/');
            if (slash >= 0) rest = rest.Substring(0, slash);
            int colon = rest.LastIndexOf(':');
            int port = scheme == "tls" ? 853 : 53;
            if (colon > 0 && IsPort(rest.Substring(colon + 1)))
            {
                port = int.Parse(rest.Substring(colon + 1), CultureInfo.InvariantCulture);
                rest = rest.Substring(0, colon);
            }
            if (string.IsNullOrEmpty(rest)) { error = L.T("آدرس DNS خالی است", "the DNS address is empty"); return null; }
            e.DnsUrl = scheme + "://" + rest + ":" + port.ToString(CultureInfo.InvariantCulture);
            e.Name = "DNS " + scheme + " " + rest;
            return e;
        }

        private static ConnectionEntry MakeDns(string url)
        {
            var e = ConnectionEntry.Create("DNS " + url, ConnectionKind.Dns);
            e.DnsUrl = url;
            e.UseForGame = false;
            return e;
        }

        /// <summary>Port of the local SOCKS/mixed inbound inside a full config, or 0.</summary>
        public static int FindSocksPort(Dictionary<string, object> config)
        {
            var inbounds = Json.Arr(Json.Get(config, "inbounds"));
            if (inbounds == null) return 0;
            foreach (object item in inbounds)
            {
                var inbound = Json.Obj(item);
                if (inbound == null) continue;
                string type = Json.GetStr(inbound, "type", "");
                if (type != "mixed" && type != "socks" && type != "http") continue;
                int port = Json.GetInt(inbound, "listen_port", 0);
                if (port > 0) return port;
            }
            return 0;
        }

        // ------------------------------------------------------------------ wireguard

        private static ConnectionEntry FromWireGuardIni(string text, out string error)
        {
            error = "";
            var e = ConnectionEntry.Create("WireGuard", ConnectionKind.WireGuard);
            string section = "";
            foreach (string rawLine in text.Replace("\r\n", "\n").Split('\n'))
            {
                string line = rawLine.Trim();
                if (line.Length == 0 || line.StartsWith("#") || line.StartsWith(";")) continue;
                if (line.StartsWith("[")) { section = line.Trim('[', ']').ToLowerInvariant(); continue; }
                int eq = line.IndexOf('=');
                if (eq <= 0) continue;
                string key = line.Substring(0, eq).Trim().ToLowerInvariant();
                string value = line.Substring(eq + 1).Trim();

                if (section == "interface")
                {
                    if (key == "privatekey") e.Secret = value;
                    else if (key == "address")
                    {
                        foreach (string piece in value.Split(','))
                        {
                            string address = piece.Trim();
                            if (address.IndexOf(':') >= 0) { if (string.IsNullOrEmpty(e.AddressV6)) e.AddressV6 = StripMask(address); }
                            else if (string.IsNullOrEmpty(e.Address)) e.Address = StripMask(address);
                        }
                    }
                    else if (key == "mtu") e.Mtu = ParseInt(value, 1280);
                }
                else if (section == "peer")
                {
                    if (key == "publickey") e.PeerPublicKey = value;
                    else if (key == "endpoint")
                    {
                        int colon = value.LastIndexOf(':');
                        if (colon > 0) { e.PeerHost = value.Substring(0, colon).Trim('[', ']'); e.PeerPort = ParseInt(value.Substring(colon + 1), 2408); }
                        else e.PeerHost = value;
                    }
                    else if (key == "reserved") e.Reserved = value.Replace(" ", "");
                }
            }
            if (string.IsNullOrEmpty(e.PeerPublicKey) || string.IsNullOrEmpty(e.PeerHost))
            {
                error = L.T("کانفیگ WireGuard ناقص است (Peer/PublicKey)", "incomplete WireGuard config (Peer/PublicKey)");
                return null;
            }
            e.Port = e.PeerPort;
            return e;
        }

        private static ConnectionEntry FromWireGuardUri(string text, out string error)
        {
            error = "";
            var query = ParseQuery(text.Substring(text.IndexOf('?') + 1));
            var e = ConnectionEntry.Create("WireGuard", ConnectionKind.WireGuard);
            e.Secret = Get(query, "private_key");
            e.Address = StripMask(Get(query, "address"));
            e.PeerPublicKey = Get(query, "public_key");
            string endpoint = Get(query, "endpoint");
            int colon = endpoint.LastIndexOf(':');
            if (colon > 0) { e.PeerHost = endpoint.Substring(0, colon); e.PeerPort = ParseInt(endpoint.Substring(colon + 1), 2408); }
            else e.PeerHost = endpoint;
            e.Port = e.PeerPort;
            e.Reserved = Get(query, "reserved");
            if (string.IsNullOrEmpty(e.PeerPublicKey)) { error = L.T("کلید عمومی سرور پیدا نشد", "peer public key not found"); return null; }
            return e;
        }

        // ------------------------------------------------------------------ raw json

        private static ConnectionEntry FromJson(string text, out string error)
        {
            error = "";
            var d = Json.ParseObject(text);
            if (d == null) { error = L.T("JSON خوانده نشد", "the JSON could not be read"); return null; }

            bool isFull = Json.Get(d, "inbounds") != null || Json.Get(d, "outbounds") != null ||
                          Json.Get(d, "route") != null || Json.Get(d, "log") != null;

            if (isFull)
            {
                var e = ConnectionEntry.Create("sing-box config", ConnectionKind.SingBoxConfig);
                e.Config = text;
                e.LocalSocksPort = FindSocksPort(d);
                e.Notes = e.LocalSocksPort > 0
                    ? L.T("کانفیگ کامل؛ پورت SOCKS داخل آن پیدا شد.", "full config; the local SOCKS port was found inside it.")
                    : L.T("کانفیگ کامل بدون inbound لوکال: با -DsocksProxy قابل استفاده نیست.",
                          "full config without a local inbound: it cannot be used as a proxy for the game.");
                return e;
            }

            string type = Json.GetStr(d, "type", "");

            if (type == "wireguard")
            {
                var e = ConnectionEntry.Create("WireGuard", ConnectionKind.WireGuard);
                e.Secret = Json.GetStr(d, "private_key", "");
                var addresses = Json.Arr(Json.Get(d, "address"));
                if (addresses != null)
                {
                    foreach (object a in addresses)
                    {
                        string address = Json.Str(a, "");
                        if (address.IndexOf(':') >= 0) { if (string.IsNullOrEmpty(e.AddressV6)) e.AddressV6 = StripMask(address); }
                        else if (string.IsNullOrEmpty(e.Address)) e.Address = StripMask(address);
                    }
                }
                e.Mtu = Json.GetInt(d, "mtu", 1280);
                var peers = Json.Arr(Json.Get(d, "peers"));
                if (peers != null && peers.Count > 0)
                {
                    var peer = Json.Obj(peers[0]);
                    if (peer != null)
                    {
                        e.PeerPublicKey = Json.GetStr(peer, "public_key", "");
                        e.PeerHost = Json.GetStr(peer, "address", "");
                        e.PeerPort = Json.GetInt(peer, "port", 2408);
                        var reserved = Json.Arr(Json.Get(peer, "reserved"));
                        if (reserved != null)
                        {
                            var parts = new List<string>();
                            foreach (object b in reserved) parts.Add(Convert.ToInt32(b, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture));
                            e.Reserved = string.Join(",", parts.ToArray());
                        }
                    }
                }
                e.Port = e.PeerPort;
                return e;
            }

            if (type.Length == 0) { error = L.T("JSON، هم کانفیگ کامل است هم outbound ندارد", "the JSON is neither a full config nor an outbound (no type)"); return null; }

            var outboundEntry = ConnectionEntry.Create("config " + type, ConnectionKind.SingBoxOutbound);
            outboundEntry.Config = text;
            return outboundEntry;
        }

        // ------------------------------------------------------------------ share links

        private static ConnectionEntry FromVless(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var query = ParseQuery(uri.Query.TrimStart('?'));
            string uuid = uri.UserInfo;
            if (string.IsNullOrEmpty(uuid) || string.IsNullOrEmpty(uri.Host))
            {
                error = L.T("لینک VLESS ناقص است", "incomplete VLESS link");
                return null;
            }
            var o = NewOutbound("vless");
            o["server"] = uri.Host;
            o["server_port"] = (double)(uri.Port > 0 ? uri.Port : 443);
            o["uuid"] = Uri.UnescapeDataString(uuid);
            string flow = Get(query, "flow");
            if (!string.IsNullOrEmpty(flow)) o["flow"] = flow;

            AddTransport(o, query, uri.Host);
            if (AddTls(o, query, uri.Host, Get(query, "security")))
            {
                string fp = Get(query, "fp");
                if (!string.IsNullOrEmpty(fp)) SetUtls(o, fp);
                string pbk = Get(query, "pbk");
                if (!string.IsNullOrEmpty(pbk)) SetReality(o, pbk, Get(query, "sid"));
            }

            var e = ConnectionEntry.Create(Name(uri, "VLESS " + uri.Host), ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = L.T("از لینک VLESS ساخته شد.", "built from a VLESS link.");
            return e;
        }

        private static ConnectionEntry FromTrojan(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var query = ParseQuery(uri.Query.TrimStart('?'));
            if (string.IsNullOrEmpty(uri.Host) || string.IsNullOrEmpty(uri.UserInfo))
            {
                error = L.T("لینک Trojan ناقص است", "incomplete Trojan link");
                return null;
            }
            var o = NewOutbound("trojan");
            o["server"] = uri.Host;
            o["server_port"] = (double)(uri.Port > 0 ? uri.Port : 443);
            o["password"] = Uri.UnescapeDataString(uri.UserInfo);
            AddTransport(o, query, uri.Host);
            AddTls(o, query, uri.Host, string.IsNullOrEmpty(Get(query, "security")) ? "tls" : Get(query, "security"));
            string fp = Get(query, "fp");
            if (!string.IsNullOrEmpty(fp)) SetUtls(o, fp);

            var e = ConnectionEntry.Create(Name(uri, "Trojan " + uri.Host), ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = L.T("از لینک Trojan ساخته شد.", "built from a Trojan link.");
            return e;
        }

        private static ConnectionEntry FromShadowsocks(string text, out string error)
        {
            error = "";
            string body = text.Substring("ss://".Length);
            string name = "";
            int hash = body.IndexOf('#');
            if (hash >= 0) { name = Uri.UnescapeDataString(body.Substring(hash + 1)); body = body.Substring(0, hash); }
            string plugin = "";
            int q = body.IndexOf('?');
            if (q >= 0)
            {
                var query = ParseQuery(body.Substring(q + 1));
                plugin = Get(query, "plugin");
                body = body.Substring(0, q);
            }

            string method = "", password = "", host = "";
            int port = 0;

            int at = body.LastIndexOf('@');
            if (at > 0)
            {
                string userInfo = body.Substring(0, at);
                string decoded;
                if (!TryBase64(userInfo, out decoded)) decoded = Uri.UnescapeDataString(userInfo);
                int colon = decoded.IndexOf(':');
                if (colon > 0) { method = decoded.Substring(0, colon); password = decoded.Substring(colon + 1); }
                string serverPart = body.Substring(at + 1).TrimEnd('/');
                int sp = serverPart.LastIndexOf(':');
                if (sp > 0) { host = serverPart.Substring(0, sp); port = ParseInt(serverPart.Substring(sp + 1), 0); }
                else host = serverPart;
            }
            else
            {
                string decoded;
                if (!TryBase64(body, out decoded)) { error = L.T("لینک Shadowsocks خوانده نشد", "the Shadowsocks link could not be read"); return null; }
                int sp = decoded.LastIndexOf(':');
                if (sp > 0) { port = ParseInt(decoded.Substring(sp + 1), 0); decoded = decoded.Substring(0, sp); }
                int at2 = decoded.LastIndexOf('@');
                if (at2 < 0) { error = L.T("لینک Shadowsocks ناقص است", "incomplete Shadowsocks link"); return null; }
                host = decoded.Substring(at2 + 1);
                string userInfo = decoded.Substring(0, at2);
                int colon = userInfo.IndexOf(':');
                if (colon > 0) { method = userInfo.Substring(0, colon); password = userInfo.Substring(colon + 1); }
            }

            if (string.IsNullOrEmpty(host) || port <= 0 || string.IsNullOrEmpty(method))
            {
                error = L.T("لینک Shadowsocks ناقص است", "incomplete Shadowsocks link");
                return null;
            }

            var o = NewOutbound("shadowsocks");
            o["server"] = host;
            o["server_port"] = (double)port;
            o["method"] = method;
            o["password"] = password;

            var e = ConnectionEntry.Create(string.IsNullOrEmpty(name) ? "Shadowsocks " + host : name, ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = string.IsNullOrEmpty(plugin)
                ? L.T("از لینک Shadowsocks ساخته شد.", "built from a Shadowsocks link.")
                : L.T("پلاگین این لینک پشتیبانی نشد: ", "unsupported plugin in this link: ") + plugin;
            return e;
        }

        private static ConnectionEntry FromVmess(string text, out string error)
        {
            error = "";
            string body = text.Substring("vmess://".Length).Trim();
            string decoded;
            if (!TryBase64(body, out decoded))
            {
                error = L.T("لینک VMess خوانده نشد", "the VMess link could not be read");
                return null;
            }
            var d = Json.ParseObject(decoded);
            if (d == null) { error = L.T("JSON داخل VMess معتبر نیست", "the JSON inside the VMess link is invalid"); return null; }

            string host = Json.GetStr(d, "add", "");
            int port = Json.GetInt(d, "port", 0);
            string uuid = Json.GetStr(d, "id", "");
            if (string.IsNullOrEmpty(host) || string.IsNullOrEmpty(uuid))
            {
                error = L.T("لینک VMess ناقص است", "incomplete VMess link");
                return null;
            }

            var o = NewOutbound("vmess");
            o["server"] = host;
            o["server_port"] = (double)port;
            o["uuid"] = uuid;
            string security = Json.GetStr(d, "scy", "");
            o["security"] = string.IsNullOrEmpty(security) ? "auto" : security;
            int alterId = Json.GetInt(d, "aid", 0);
            if (alterId > 0) o["alter_id"] = (double)alterId;

            var query = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            query["type"] = Json.GetStr(d, "net", "tcp");
            query["path"] = Json.GetStr(d, "path", "");
            query["host"] = Json.GetStr(d, "host", "");
            query["serviceName"] = Json.GetStr(d, "path", "");
            query["sni"] = Json.GetStr(d, "sni", "");
            query["fp"] = Json.GetStr(d, "fp", "");
            query["security"] = Json.GetStr(d, "tls", "");
            AddTransport(o, query, host);
            AddTls(o, query, host, Json.GetStr(d, "tls", ""));

            var e = ConnectionEntry.Create(Name(null, Json.GetStr(d, "ps", "VMess " + host)), ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = L.T("از لینک VMess ساخته شد.", "built from a VMess link.");
            return e;
        }

        private static ConnectionEntry FromHysteria2(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var query = ParseQuery(uri.Query.TrimStart('?'));
            if (string.IsNullOrEmpty(uri.Host))
            {
                error = L.T("لینک Hysteria2 ناقص است", "incomplete Hysteria2 link");
                return null;
            }
            var o = NewOutbound("hysteria2");
            o["server"] = uri.Host;
            o["server_port"] = (double)(uri.Port > 0 ? uri.Port : 443);
            if (!string.IsNullOrEmpty(uri.UserInfo)) o["password"] = Uri.UnescapeDataString(uri.UserInfo);
            AddTls(o, query, uri.Host, "tls");
            string obfs = Get(query, "obfs");
            string obfsPassword = Get(query, "obfs-password");
            if (!string.IsNullOrEmpty(obfs) || !string.IsNullOrEmpty(obfsPassword))
            {
                var obfsObject = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                obfsObject["type"] = string.IsNullOrEmpty(obfs) ? "salamander" : obfs;
                if (!string.IsNullOrEmpty(obfsPassword)) obfsObject["password"] = obfsPassword;
                o["obfs"] = obfsObject;
            }

            var e = ConnectionEntry.Create(Name(uri, "Hysteria2 " + uri.Host), ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = L.T("از لینک Hysteria2 ساخته شد.", "built from a Hysteria2 link.");
            return e;
        }

        private static ConnectionEntry FromTuic(string text, out string error)
        {
            error = "";
            Uri uri = new Uri(text);
            var query = ParseQuery(uri.Query.TrimStart('?'));
            if (string.IsNullOrEmpty(uri.Host))
            {
                error = L.T("لینک TUIC ناقص است", "incomplete TUIC link");
                return null;
            }
            var o = NewOutbound("tuic");
            o["server"] = uri.Host;
            o["server_port"] = (double)(uri.Port > 0 ? uri.Port : 443);
            string info = Uri.UnescapeDataString(uri.UserInfo ?? "");
            int colon = info.IndexOf(':');
            if (colon > 0) { o["uuid"] = info.Substring(0, colon); o["password"] = info.Substring(colon + 1); }
            else if (info.Length > 0) o["password"] = info;
            AddTls(o, query, uri.Host, "tls");
            string congestion = Get(query, "congestion_control");
            if (!string.IsNullOrEmpty(congestion)) o["congestion_control"] = congestion;

            var e = ConnectionEntry.Create(Name(uri, "TUIC " + uri.Host), ConnectionKind.SingBoxOutbound);
            e.Config = Json.Serialize(o);
            e.Notes = L.T("از لینک TUIC ساخته شد.", "built from a TUIC link.");
            return e;
        }

        // ------------------------------------------------------------------ outbound helpers

        private static Dictionary<string, object> NewOutbound(string type)
        {
            var o = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            o["type"] = type;
            o["tag"] = "conn-" + type;
            return o;
        }

        private static void AddTransport(Dictionary<string, object> outbound, Dictionary<string, string> query, string host)
        {
            string type = (Get(query, "type") ?? "").ToLowerInvariant();
            if (type.Length == 0 || type == "tcp" || type == "none") return;

            var transport = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            var headers = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            string headerHost = Get(query, "host");
            if (string.IsNullOrEmpty(headerHost)) headerHost = host;
            if (!string.IsNullOrEmpty(headerHost)) headers["Host"] = headerHost;

            switch (type)
            {
                case "ws":
                    transport["type"] = "ws";
                    string path = Get(query, "path");
                    if (!string.IsNullOrEmpty(path)) transport["path"] = path;
                    if (headers.Count > 0) transport["headers"] = headers;
                    break;
                case "grpc":
                    transport["type"] = "grpc";
                    string service = Get(query, "serviceName");
                    if (!string.IsNullOrEmpty(service)) transport["service_name"] = service;
                    break;
                case "http":
                case "h2":
                    transport["type"] = "http";
                    if (headers.Count > 0) transport["headers"] = headers;
                    string httpPath = Get(query, "path");
                    if (!string.IsNullOrEmpty(httpPath)) transport["path"] = httpPath;
                    break;
                case "httpupgrade":
                    transport["type"] = "httpupgrade";
                    if (headers.Count > 0) transport["headers"] = headers;
                    string upgradePath = Get(query, "path");
                    if (!string.IsNullOrEmpty(upgradePath)) transport["path"] = upgradePath;
                    break;
                case "quic":
                    transport["type"] = "quic";
                    break;
                default:
                    // Unknown transport: keep the parameters in a note instead of writing a
                    // configuration sing-box would refuse to load.
                    outbound["_unsupported_transport"] = type;
                    return;
            }
            outbound["transport"] = transport;
        }

        /// <summary>Adds the tls block when the link asks for one. Returns true when TLS is on.</summary>
        private static bool AddTls(Dictionary<string, object> outbound, Dictionary<string, string> query, string host, string security)
        {
            string mode = (security ?? "").ToLowerInvariant();
            bool reality = mode == "reality";
            bool enabled = reality || mode == "tls" || mode == "xtls";
            if (!enabled)
            {
                string sni = Get(query, "sni");
                if (!string.IsNullOrEmpty(sni)) enabled = true;
            }
            if (!enabled) return false;

            var tls = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            tls["enabled"] = true;
            string serverName = Get(query, "sni");
            if (string.IsNullOrEmpty(serverName)) serverName = Get(query, "peer");
            if (string.IsNullOrEmpty(serverName)) serverName = host;
            tls["server_name"] = serverName;
            if (IsTrue(Get(query, "allowInsecure")) || IsTrue(Get(query, "insecure"))) tls["insecure"] = true;
            string alpn = Get(query, "alpn");
            if (!string.IsNullOrEmpty(alpn))
            {
                var list = new List<object>();
                foreach (string piece in alpn.Split(',')) if (piece.Trim().Length > 0) list.Add(piece.Trim());
                if (list.Count > 0) tls["alpn"] = list;
            }
            if (reality)
            {
                var realityBlock = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                realityBlock["enabled"] = true;
                string publicKey = Get(query, "pbk");
                if (!string.IsNullOrEmpty(publicKey)) realityBlock["public_key"] = publicKey;
                string shortId = Get(query, "sid");
                if (!string.IsNullOrEmpty(shortId)) realityBlock["short_id"] = shortId;
                tls["reality"] = realityBlock;
            }
            outbound["tls"] = tls;
            return true;
        }

        private static void SetUtls(Dictionary<string, object> outbound, string fingerprint)
        {
            var tls = Json.Obj(Json.Get(outbound, "tls"));
            if (tls == null) return;
            var utls = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            utls["enabled"] = true;
            if (!string.IsNullOrEmpty(fingerprint)) utls["fingerprint"] = fingerprint;
            tls["utls"] = utls;
        }

        private static void SetReality(Dictionary<string, object> outbound, string publicKey, string shortId)
        {
            var tls = Json.Obj(Json.Get(outbound, "tls"));
            if (tls == null) return;
            var reality = Json.Obj(Json.Get(tls, "reality"));
            if (reality == null)
            {
                reality = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                tls["reality"] = reality;
            }
            reality["enabled"] = true;
            reality["public_key"] = publicKey;
            if (!string.IsNullOrEmpty(shortId)) reality["short_id"] = shortId;
        }

        // ------------------------------------------------------------------ small helpers

        private static void ParseUserInfo(Uri uri, ConnectionEntry entry)
        {
            if (string.IsNullOrEmpty(uri.UserInfo)) return;
            string info = Uri.UnescapeDataString(uri.UserInfo);
            int colon = info.IndexOf(':');
            if (colon > 0) { entry.User = info.Substring(0, colon); entry.Password = info.Substring(colon + 1); }
            else entry.User = info;
        }

        private static void Label(ConnectionEntry entry, Uri uri, string prefix)
        {
            string name = Name(uri, prefix + " " + uri.Host);
            entry.Name = name;
        }

        private static string Name(Uri uri, string fallback)
        {
            try
            {
                if (uri != null && !string.IsNullOrEmpty(uri.Fragment))
                {
                    string name = Uri.UnescapeDataString(uri.Fragment.TrimStart('#')).Trim();
                    if (name.Length > 0) return name;
                }
            }
            catch { }
            return fallback;
        }

        private static Dictionary<string, string> ParseQuery(string query)
        {
            var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (string.IsNullOrEmpty(query)) return result;
            foreach (string piece in query.TrimStart('?').Split('&'))
            {
                if (piece.Length == 0) continue;
                int eq = piece.IndexOf('=');
                string key = eq < 0 ? piece : piece.Substring(0, eq);
                string value = eq < 0 ? "" : piece.Substring(eq + 1);
                try { value = Uri.UnescapeDataString(value.Replace("+", " ")); }
                catch { }
                if (key.Length > 0) result[key] = value;
            }
            return result;
        }

        private static string Get(Dictionary<string, string> query, string key)
        {
            if (query == null) return "";
            string value;
            return query.TryGetValue(key, out value) ? (value ?? "") : "";
        }

        private static bool IsTrue(string value)
        {
            if (string.IsNullOrEmpty(value)) return false;
            string v = value.Trim().ToLowerInvariant();
            return v == "1" || v == "true" || v == "yes";
        }

        private static int ParseInt(string value, int fallback)
        {
            int parsed;
            if (int.TryParse((value ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out parsed)) return parsed;
            return fallback;
        }

        private static bool IsPort(string value)
        {
            int port;
            if (!int.TryParse((value ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out port)) return false;
            return port > 0 && port <= 65535;
        }

        private static bool IsIp(string value)
        {
            System.Net.IPAddress parsed;
            return System.Net.IPAddress.TryParse(value, out parsed);
        }

        /// <summary>Telegram secrets are long hex or base64 blobs; user names are not.</summary>
        private static bool LooksLikeSecret(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length < 16) return false;
            foreach (char c in value)
            {
                bool ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F') ||
                          c == '+' || c == '/' || c == '=' || c == '-' || c == '_';
                if (!ok) return false;
            }
            return true;
        }

        private static string StripMask(string address)
        {
            if (string.IsNullOrEmpty(address)) return "";
            int slash = address.IndexOf('/');
            return (slash > 0 ? address.Substring(0, slash) : address).Trim();
        }

        private static bool TryBase64(string text, out string decoded)
        {
            decoded = "";
            if (string.IsNullOrEmpty(text)) return false;
            string value = text.Trim().Replace('-', '+').Replace('_', '/');
            while (value.Length % 4 != 0) value += "=";
            try
            {
                byte[] bytes = Convert.FromBase64String(value);
                decoded = Encoding.UTF8.GetString(bytes);
                return true;
            }
            catch { return false; }
        }

        private static string Trim(string text, int max)
        {
            if (text == null) return "";
            return text.Length <= max ? text : text.Substring(0, max) + "…";
        }
    }
}

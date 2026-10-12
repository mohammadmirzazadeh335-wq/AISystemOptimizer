using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>
    /// What a connection entry actually is. <see cref="Warp"/>, <see cref="Dns"/> and
    /// <see cref="Mtproto"/> are special: WARP is built by the app itself, DNS only fixes name
    /// resolution and an MTProto proxy can carry Telegram but never a Minecraft connection.
    /// </summary>
    public enum ConnectionKind
    {
        Warp = 0,
        Dns = 1,
        Socks5 = 2,
        Http = 3,
        Mtproto = 4,
        WireGuard = 5,
        /// <summary>One sing-box outbound object pasted as JSON (vless/vmess/trojan/ss/…).</summary>
        SingBoxOutbound = 6,
        /// <summary>A complete sing-box config, run exactly as pasted.</summary>
        SingBoxConfig = 7
    }

    /// <summary>One way to reach the game server: a tunnel, a proxy, a resolver or a raw config.</summary>
    public sealed class ConnectionEntry
    {
        public string Id = "";
        public string Name = "";
        public ConnectionKind Kind = ConnectionKind.Socks5;
        public bool Enabled = true;
        /// <summary>May take part in the automatic selection for the game path.</summary>
        public bool UseForGame = true;

        // proxy / server side
        public string Host = "";
        public int Port;
        public string User = "";
        public string Password = "";
        /// <summary>MTProto secret, or an extra password for kinds that need one.</summary>
        public string Secret = "";

        // WireGuard
        public string Address = "";          // client address, e.g. 172.16.0.2
        public string AddressV6 = "";
        public string PeerPublicKey = "";
        public string PeerHost = "";         // endpoint host or IP
        public int PeerPort = 2408;
        public string Reserved = "";         // "0,0,0" when the server needs reserved bytes
        public int Mtu = 1280;

        // DNS
        public string DnsUrl = "";           // udp://1.1.1.1:53 · tcp:// · tls://1.1.1.1 · https://…

        // pasted configuration
        public string Config = "";           // JSON of an outbound object or of a whole config
        public int LocalSocksPort;           // where a full config listens locally

        public int Dc = 2;                   // Telegram data centre for MTProto proxies (1..5)
        public string Notes = "";

        // last live test
        public int LastDelayMs = -1;
        public string LastStatus = "";
        public string LastError = "";
        public string LastTestUtc = "";

        public ConnectionKindInfo Info { get { return ConnectionKindInfo.Of(Kind); } }

        public bool CanCarryGame { get { return Info.CanCarryGame; } }

        /// <summary>What the test should connect through for this kind (host:port).</summary>
        public string ServerEndpoint
        {
            get
            {
                if (Kind == ConnectionKind.WireGuard) return PeerHost + ":" + PeerPort.ToString(CultureInfo.InvariantCulture);
                if (Kind == ConnectionKind.Dns) return DnsUrl;
                return Host + ":" + Port.ToString(CultureInfo.InvariantCulture);
            }
        }

        public string Target
        {
            get
            {
                switch (Kind)
                {
                    case ConnectionKind.Warp:
                        return L.T("خودکار: اسکن + حساب WARP", "automatic: scan + WARP account");
                    case ConnectionKind.Dns:
                        return string.IsNullOrEmpty(DnsUrl) ? L.T("تعیین نشده", "not set") : DnsUrl;
                    case ConnectionKind.SingBoxOutbound:
                    case ConnectionKind.SingBoxConfig:
                        {
                            string summary = RawSummary();
                            if (!string.IsNullOrEmpty(summary)) return summary;
                            return Kind == ConnectionKind.SingBoxConfig
                                ? L.T("کانفیگ کامل", "full config")
                                : L.T("کانفیگ دستی", "manual config");
                        }
                    default:
                        {
                            string user = string.IsNullOrEmpty(User) ? "" : User + "@";
                            string port = Port > 0 ? ":" + Port.ToString(CultureInfo.InvariantCulture) : "";
                            if (Kind == ConnectionKind.WireGuard && !string.IsNullOrEmpty(PeerHost))
                                return PeerHost + ":" + PeerPort.ToString(CultureInfo.InvariantCulture);
                            return user + (string.IsNullOrEmpty(Host) ? L.T("تعیین نشده", "not set") : Host) + port;
                        }
                }
            }
        }

        /// <summary>Best effort description of a pasted config: its type and server.</summary>
        public string RawSummary()
        {
            if (string.IsNullOrEmpty(Config)) return "";
            try
            {
                var d = Json.ParseObject(Config);
                if (d == null) return "";
                string type = Json.GetStr(d, "type", "");
                if (type.Length == 0) return "";
                if (Kind == ConnectionKind.SingBoxConfig)
                {
                    int port = LocalSocksPort;
                    if (port <= 0) port = ConnectionParser.FindSocksPort(d);
                    return type + (port > 0 ? " • socks " + port.ToString(CultureInfo.InvariantCulture) : "");
                }
                string server = Json.GetStr(d, "server", "");
                int serverPort = Json.GetInt(d, "server_port", 0);
                if (server.Length == 0) return type;
                return type + " • " + server + (serverPort > 0 ? ":" + serverPort.ToString(CultureInfo.InvariantCulture) : "");
            }
            catch { return L.T("کانفیگ نامعتبر", "invalid config"); }
        }

        public string StatusText
        {
            get
            {
                if (string.IsNullOrEmpty(LastStatus)) return "—";
                if (LastDelayMs > 0) return LastStatus + " • " + LastDelayMs.ToString(CultureInfo.InvariantCulture) + " ms";
                return LastStatus;
            }
        }

        /// <summary>Fields that still have to be filled in before the entry can work.</summary>
        public string Missing()
        {
            var missing = new List<string>();
            switch (Kind)
            {
                case ConnectionKind.Warp:
                    break;
                case ConnectionKind.Dns:
                    if (string.IsNullOrEmpty(DnsUrl)) missing.Add(L.T("آدرس DNS", "DNS server"));
                    break;
                case ConnectionKind.WireGuard:
                    if (string.IsNullOrEmpty(Address)) missing.Add(L.T("آدرس کلاینت", "client address"));
                    if (string.IsNullOrEmpty(PeerPublicKey)) missing.Add(L.T("کلید عمومی سرور", "peer public key"));
                    if (string.IsNullOrEmpty(PeerHost)) missing.Add(L.T("آدرس سرور", "peer address"));
                    break;
                case ConnectionKind.SingBoxOutbound:
                case ConnectionKind.SingBoxConfig:
                    if (string.IsNullOrEmpty(Config)) missing.Add(L.T("کانفیگ JSON", "JSON config"));
                    break;
                case ConnectionKind.Mtproto:
                    if (string.IsNullOrEmpty(Host)) missing.Add(L.T("آدرس", "address"));
                    if (Port <= 0) missing.Add(L.T("پورت", "port"));
                    if (string.IsNullOrEmpty(Secret)) missing.Add(L.T("سکرت", "secret"));
                    if (Dc < 1 || Dc > 5) missing.Add(L.T("شماره دیتاسنتر (۱ تا ۵)", "data centre number (1 to 5)"));
                    break;
                default:
                    if (string.IsNullOrEmpty(Host)) missing.Add(L.T("آدرس", "address"));
                    if (Port <= 0) missing.Add(L.T("پورت", "port"));
                    break;
            }
            return string.Join(", ", missing.ToArray());
        }

        /// <summary>True when two entries carry the same connection settings (the test result is ignored).</summary>
        public bool SameConfig(ConnectionEntry other)
        {
            if (other == null) return false;
            return Kind == other.Kind
                && string.Equals(Host, other.Host, StringComparison.OrdinalIgnoreCase)
                && Port == other.Port
                && string.Equals(User, other.User, StringComparison.Ordinal)
                && string.Equals(Password, other.Password, StringComparison.Ordinal)
                && string.Equals(Secret, other.Secret, StringComparison.Ordinal)
                && Dc == other.Dc
                && string.Equals(DnsUrl, other.DnsUrl, StringComparison.OrdinalIgnoreCase)
                && string.Equals(Address, other.Address, StringComparison.Ordinal)
                && string.Equals(AddressV6, other.AddressV6, StringComparison.Ordinal)
                && string.Equals(PeerPublicKey, other.PeerPublicKey, StringComparison.Ordinal)
                && string.Equals(PeerHost, other.PeerHost, StringComparison.OrdinalIgnoreCase)
                && PeerPort == other.PeerPort
                && string.Equals(Reserved, other.Reserved, StringComparison.Ordinal)
                && Mtu == other.Mtu
                && string.Equals(Config, other.Config, StringComparison.Ordinal)
                && LocalSocksPort == other.LocalSocksPort;
        }

        public void ForgetTest()
        {
            LastDelayMs = -1;
            LastStatus = "";
            LastError = "";
            LastTestUtc = "";
        }

        public void CopyTestFrom(ConnectionEntry other)
        {
            if (other == null) { ForgetTest(); return; }
            LastDelayMs = other.LastDelayMs;
            LastStatus = other.LastStatus;
            LastError = other.LastError;
            LastTestUtc = other.LastTestUtc;
        }

        /// <summary>The parsed Telegram secret (only meaningful for MTProto entries).</summary>
        public MtprotoSecret TelegramSecret()
        {
            return MtprotoSecret.Parse(Secret);
        }

        public ConnectionEntry Clone()
        {
            return (ConnectionEntry)MemberwiseClone();
        }

        public static ConnectionEntry Create(string name, ConnectionKind kind)
        {
            var e = new ConnectionEntry();
            e.Id = NewId();
            e.Name = name;
            e.Kind = kind;
            if (kind == ConnectionKind.Dns)
            {
                e.DnsUrl = "udp://1.1.1.1:53";
                e.UseForGame = false;
            }
            else if (kind == ConnectionKind.Socks5 || kind == ConnectionKind.Http)
            {
                e.Port = kind == ConnectionKind.Socks5 ? 1080 : 8080;
            }
            else if (kind == ConnectionKind.Mtproto)
            {
                e.Port = 443;
                e.Dc = 2;
                e.UseForGame = false;          // an MTProxy only carries Telegram, so it can never route the game
                e.Notes = L.T("فقط برای تلگرام؛ بازی از این پروکسی عبور نمی‌کند.",
                              "Telegram only; the game cannot be carried by it.");
            }
            else if (kind == ConnectionKind.WireGuard)
            {
                e.Port = 2408;
                e.PeerPort = 2408;
            }
            else if (kind == ConnectionKind.SingBoxConfig)
            {
                e.LocalSocksPort = 22470;
            }
            return e;
        }

        public static string NewId()
        {
            return Guid.NewGuid().ToString("N").Substring(0, 8);
        }

        // ------------------------------------------------------------------ json

        public void WriteTo(JsonWriter w)
        {
            w.StartObject();
            w.Prop("id", string.IsNullOrEmpty(Id) ? NewId() : Id);
            w.Prop("name", Name);
            w.Prop("kind", (int)Kind);
            w.Prop("enabled", Enabled);
            w.Prop("useForGame", UseForGame);
            w.Prop("host", Host);
            w.Prop("port", Port);
            w.Prop("user", User);
            w.Prop("password", Password);
            w.Prop("secret", Secret);
            w.Prop("dc", Dc);
            w.Prop("address", Address);
            w.Prop("addressV6", AddressV6);
            w.Prop("peerPublicKey", PeerPublicKey);
            w.Prop("peerHost", PeerHost);
            w.Prop("peerPort", PeerPort);
            w.Prop("reserved", Reserved);
            w.Prop("mtu", Mtu);
            w.Prop("dnsUrl", DnsUrl);
            w.Prop("config", Config);
            w.Prop("localSocksPort", LocalSocksPort);
            w.Prop("notes", Notes);
            w.Prop("lastDelayMs", LastDelayMs);
            w.Prop("lastStatus", LastStatus);
            w.Prop("lastError", LastError);
            w.Prop("lastTestUtc", LastTestUtc);
            w.EndObject();
        }

        public static ConnectionEntry Read(Dictionary<string, object> d)
        {
            if (d == null) return null;
            var e = new ConnectionEntry();
            e.Id = Json.GetStr(d, "id", "");
            if (string.IsNullOrEmpty(e.Id)) e.Id = NewId();
            e.Name = Json.GetStr(d, "name", "");
            int kind = Json.GetInt(d, "kind", (int)ConnectionKind.Socks5);
            if (kind < 0 || kind > (int)ConnectionKind.SingBoxConfig) kind = (int)ConnectionKind.Socks5;
            e.Kind = (ConnectionKind)kind;
            e.Enabled = Json.GetBool(d, "enabled", true);
            e.UseForGame = Json.GetBool(d, "useForGame", true);
            e.Host = Json.GetStr(d, "host", "");
            e.Port = Json.GetInt(d, "port", 0);
            e.User = Json.GetStr(d, "user", "");
            e.Password = Json.GetStr(d, "password", "");
            e.Secret = Json.GetStr(d, "secret", "");
            e.Dc = Json.GetInt(d, "dc", 2);
            e.Address = Json.GetStr(d, "address", "");
            e.AddressV6 = Json.GetStr(d, "addressV6", "");
            e.PeerPublicKey = Json.GetStr(d, "peerPublicKey", "");
            e.PeerHost = Json.GetStr(d, "peerHost", "");
            e.PeerPort = Json.GetInt(d, "peerPort", 2408);
            e.Reserved = Json.GetStr(d, "reserved", "");
            e.Mtu = Json.GetInt(d, "mtu", 1280);
            e.DnsUrl = Json.GetStr(d, "dnsUrl", "");
            e.Config = Json.GetStr(d, "config", "");
            e.LocalSocksPort = Json.GetInt(d, "localSocksPort", 0);
            e.Notes = Json.GetStr(d, "notes", "");
            e.LastDelayMs = Json.GetInt(d, "lastDelayMs", -1);
            e.LastStatus = Json.GetStr(d, "lastStatus", "");
            e.LastError = Json.GetStr(d, "lastError", "");
            e.LastTestUtc = Json.GetStr(d, "lastTestUtc", "");
            if (string.IsNullOrEmpty(e.Name)) e.Name = ConnectionKindInfo.Of(e.Kind).En;
            return e;
        }

        /// <summary>Colourless one line summary used in reports.</summary>
        public string Line()
        {
            string state = !Enabled ? L.T("خاموش", "off")
                         : LastDelayMs > 0 ? LastDelayMs.ToString(CultureInfo.InvariantCulture) + " ms"
                         : string.IsNullOrEmpty(LastStatus) ? L.T("تست نشده", "not tested") : LastStatus;
            return Name + " [" + Info.Title + "] " + Target + " — " + state;
        }
    }

    /// <summary>Static description of a connection kind.</summary>
    public sealed class ConnectionKindInfo
    {
        public ConnectionKind Kind;
        public string Fa = "";
        public string En = "";
        /// <summary>False for kinds that can measure a delay but cannot carry the game traffic.</summary>
        public bool CanCarryGame = true;
        /// <summary>True when the kind is put in front of the game as a real tunnel or proxy.</summary>
        public bool IsRouted = false;
        /// <summary>True when the kind only helps name resolution.</summary>
        public bool IsResolver = false;
        /// <summary>Plain words about what this kind of connection can actually carry.</summary>
        public string Fa2 = "";
        public string En2 = "";
        /// <summary>A short marker for the delay column when the number is not a game ping.</summary>
        public string DelayNote = "";

        public string Carries
        {
            get
            {
                if (En2.Length > 0) return L.T(Fa2, En2);
                return CanCarryGame ? L.T("بازی", "the game") : L.T("—", "—");
            }
        }

        public string Title { get { return L.T(Fa, En); } }

        private static readonly ConnectionKindInfo[] All = new ConnectionKindInfo[]
        {
            new ConnectionKindInfo { Kind = ConnectionKind.Warp, En = "Cloudflare WARP", Fa = "تونل WARP کلادفلر", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" },
            new ConnectionKindInfo { Kind = ConnectionKind.Dns, En = "DNS server", Fa = "سرور DNS", CanCarryGame = false, IsResolver = true, En2 = "names only", Fa2 = "فقط نام‌ها", DelayNote = "dns" },
            new ConnectionKindInfo { Kind = ConnectionKind.Socks5, En = "SOCKS5 proxy", Fa = "پروکسی SOCKS5", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" },
            new ConnectionKindInfo { Kind = ConnectionKind.Http, En = "HTTP proxy", Fa = "پروکسی HTTP", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" },
            new ConnectionKindInfo { Kind = ConnectionKind.Mtproto, En = "Telegram MTProto", Fa = "پروکسی MTProto تلگرام", CanCarryGame = false, En2 = "Telegram only", Fa2 = "فقط تلگرام", DelayNote = "tg" },
            new ConnectionKindInfo { Kind = ConnectionKind.WireGuard, En = "WireGuard config", Fa = "کانفیگ WireGuard", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" },
            new ConnectionKindInfo { Kind = ConnectionKind.SingBoxOutbound, En = "Manual outbound JSON", Fa = "کانفیگ دستی (outbound)", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" },
            new ConnectionKindInfo { Kind = ConnectionKind.SingBoxConfig, En = "Full sing-box config", Fa = "کانفیگ کامل sing-box", CanCarryGame = true, IsRouted = true, En2 = "the game", Fa2 = "بازی" }
        };

        public static ConnectionKindInfo Of(ConnectionKind kind)
        {
            foreach (ConnectionKindInfo info in All) if (info.Kind == kind) return info;
            return All[2];
        }

        public static List<ConnectionKindInfo> AllKinds()
        {
            return new List<ConnectionKindInfo>(All);
        }
    }
}

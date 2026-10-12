using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>
    /// Reads an OpenVPN configuration file (.ovpn) — the format TunnelBear, most VPN providers and
    /// the OpenVPN GUI hand out — and turns it into a sing-box <c>openvpn-client</c> endpoint.
    ///
    /// This is what makes "connect to TunnelBear with OpenVPN" possible without installing anything:
    /// sing-box 1.14 speaks the OpenVPN protocol itself, and because the app only ever routes the
    /// game server address into the endpoint, the rest of the machine is untouched.
    /// </summary>
    public sealed class OvpnProfile
    {
        public string SourceName = "";
        public List<string> Remotes = new List<string>();     // "host:port:network"
        public string Network = "udp";                        // proto udp|tcp
        public string Dev = "";
        public string Topology = "";
        public string Cipher = "";                            // legacy single cipher
        public List<string> DataCiphers = new List<string>();
        public string Auth = "";
        public string CompLzo = "";
        public string Compress = "";
        public bool RouteNoPull;
        public bool RemoteCertTlsServer;
        public string VerifyX509Name = "";
        public string TlsVersionMin = "";
        public int Mtu;
        public int Fragment;
        public int KeyDirection = -1;                          // tls-auth key-direction
        public string TlsAuthKind = "";                        // tls_auth · tls_crypt · tls_crypt_v2
        public string TlsAuthKey = "";                         // inline <tls-auth>/<tls-crypt> body
        public string CaCert = "";                             // inline <ca>
        public string ClientCert = "";                         // inline <cert>
        public string ClientKey = "";                          // inline <key>
        public bool NeedsCredentials;                          // auth-user-pass without stored creds
        public string AuthUserPassFile = "";
        public string Ping = "";
        public string PingRestart = "";
        public string RenegSec = "";
        public string ServerName = "";                          // from verify-x509-name / remote name
        public List<string> Warnings = new List<string>();

        public bool Ok { get { return Remotes.Count > 0; } }

        public string Host
        {
            get
            {
                string[] parts = Remotes.Count > 0 ? Remotes[0].Split(':') : new string[0];
                return parts.Length > 0 ? parts[0] : "";
            }
        }

        public int Port
        {
            get
            {
                string[] parts = Remotes.Count > 0 ? Remotes[0].Split(':') : new string[0];
                int port;
                return parts.Length > 1 && int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out port)
                    ? port : 1194;
            }
        }

        public string Summary()
        {
            var sb = new StringBuilder();
            sb.Append(Host).Append(':').Append(Port.ToString(CultureInfo.InvariantCulture));
            sb.Append(" • ").Append(Network.ToUpperInvariant());
            if (DataCiphers.Count > 0) sb.Append(" • ").Append(string.Join("/", DataCiphers.ToArray()));
            else if (Cipher.Length > 0) sb.Append(" • ").Append(Cipher);
            if (TlsAuthKind.Length > 0) sb.Append(" • ").Append(TlsAuthKind.Replace('_', '-'));
            if (CaCert.Length > 0) sb.Append(" • CA ✓");
            if (ClientCert.Length > 0 && ClientKey.Length > 0) sb.Append(" • client cert ✓");
            if (NeedsCredentials) sb.Append(" • ").Append(L.T("نیازمند نام کاربری/رمز", "username/password needed"));
            return sb.ToString();
        }

        /// <summary>True when the text really looks like an OpenVPN profile.</summary>
        public static bool LooksLike(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            if (text.IndexOf("<ca>", StringComparison.OrdinalIgnoreCase) >= 0 &&
                text.IndexOf("client", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (text.IndexOf("-----BEGIN CERTIFICATE-----", StringComparison.Ordinal) >= 0 &&
                text.IndexOf("remote ", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            bool remote = false, proto = false, dev = false;
            foreach (string raw in text.Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line[0] == '#' || line[0] == ';') continue;
                if (line.StartsWith("remote ", StringComparison.OrdinalIgnoreCase)) remote = true;
                if (line.StartsWith("proto ", StringComparison.OrdinalIgnoreCase)) proto = true;
                if (line.StartsWith("dev ", StringComparison.OrdinalIgnoreCase)) dev = true;
            }
            return remote && (proto || dev);
        }

        /// <summary>Parses a profile. Missing certificates are reported in <see cref="Warnings"/>.</summary>
        public static OvpnProfile Parse(string text, string sourceName)
        {
            var profile = new OvpnProfile();
            profile.SourceName = sourceName ?? "";
            if (string.IsNullOrEmpty(text)) return profile;

            string[] lines = text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
            string pendingTag = "";
            var inline = new StringBuilder();

            foreach (string rawLine in lines)
            {
                string line = rawLine.Trim();

                // ---- inline blocks (<ca>…</ca>, <tls-auth>…</tls-auth>, …)
                if (pendingTag.Length > 0)
                {
                    if (line.Length > 0 && line[0] == '<' && line.IndexOf("</", StringComparison.Ordinal) == 0)
                    {
                        Store(profile, pendingTag, inline.ToString());
                        pendingTag = "";
                        inline.Length = 0;
                        continue;
                    }
                    inline.Append(line).Append('\n');
                    continue;
                }
                if (line.Length > 0 && line[0] == '<' && line.IndexOf("</", StringComparison.Ordinal) < 0)
                {
                    pendingTag = line.Substring(1, line.Length - 2).Trim().ToLowerInvariant();
                    inline.Length = 0;
                    continue;
                }

                if (line.Length == 0 || line[0] == '#' || line[0] == ';') continue;
                string[] words = SplitWords(line);
                if (words.Length == 0) continue;
                string key = words[0].ToLowerInvariant();
                string value = words.Length > 1 ? words[1] : "";

                switch (key)
                {
                    case "remote":
                        if (words.Length > 1)
                        {
                            string network = words.Length > 3 ? words[3].ToLowerInvariant() : "";
                            profile.Remotes.Add(words[1] + ":" + (words.Length > 2 ? words[2] : "1194") +
                                                (network.Length > 0 ? ":" + network : ""));
                        }
                        break;
                    case "proto":
                        profile.Network = value.StartsWith("tcp", StringComparison.OrdinalIgnoreCase) ? "tcp" : "udp";
                        break;
                    case "dev":
                    case "dev-type":
                        profile.Dev = value;
                        break;
                    case "topology":
                        profile.Topology = value;
                        break;
                    case "cipher":
                        profile.Cipher = value.ToUpperInvariant();
                        break;
                    case "data-ciphers":
                    case "ncp-ciphers":
                        foreach (string cipher in value.Split(':'))
                            if (cipher.Trim().Length > 0) profile.DataCiphers.Add(cipher.Trim().ToUpperInvariant());
                        break;
                    case "auth":
                        profile.Auth = value.ToUpperInvariant();
                        break;
                    case "comp-lzo":
                        profile.CompLzo = value.Length > 0 ? value.ToLowerInvariant() : "yes";
                        break;
                    case "compress":
                        profile.Compress = value.Length > 0 ? value.ToLowerInvariant() : "yes";
                        break;
                    case "route-nopull":
                        profile.RouteNoPull = true;
                        break;
                    case "remote-cert-tls":
                        if (value.Equals("server", StringComparison.OrdinalIgnoreCase)) profile.RemoteCertTlsServer = true;
                        break;
                    case "verify-x509-name":
                        // "verify-x509-name bear-1234 name" or just the name
                        if (value.Length > 0) profile.VerifyX509Name = value;
                        break;
                    case "tls-version-min":
                        profile.TlsVersionMin = value;
                        break;
                    case "tls-auth":
                        profile.TlsAuthKind = "tls_auth";
                        // the key file itself is picked up further down when it sits next to the profile;
                        // a file name must never be stored as if it were the key

                        if (words.Length > 2) profile.KeyDirection = DirectionOf(words[2]);
                        break;
                    case "tls-crypt":
                        profile.TlsAuthKind = "tls_crypt";
                        break;
                    case "tls-crypt-v2":
                        profile.TlsAuthKind = "tls_crypt_v2";
                        break;
                    case "key-direction":
                        profile.KeyDirection = DirectionOf(value);
                        break;
                    case "auth-user-pass":
                        if (value.Length > 0) profile.AuthUserPassFile = value;
                        profile.NeedsCredentials = true;
                        break;
                    case "mtu":
                    case "tun-mtu":
                        profile.Mtu = ParseInt(value, profile.Mtu);
                        break;
                    case "fragment":
                        profile.Fragment = ParseInt(value, 0);
                        break;
                    case "ping":
                        profile.Ping = value;
                        break;
                    case "ping-restart":
                        profile.PingRestart = value;
                        break;
                    case "reneg-sec":
                        profile.RenegSec = value;
                        break;
                    case "remote-random":
                        profile.Warnings.Add(L.T("remote-random پشتیبانی نمی‌شود؛ ترتیب لیست حفظ شد.",
                                                 "remote-random is not supported; the list order is kept."));
                        break;
                    case "sndbuf":
                    case "rcvbuf":
                    case "persist-key":
                    case "persist-tun":
                    case "nobind":
                    case "resolv-retry":
                    case "block-outside-dns":
                    case "redirect-gateway":
                    case "dhcp-option":
                        // handled by sing-box itself or irrelevant for a split tunnel
                        break;
                    case "management":
                    case "management-hold":
                    case "script-security":
                    case "up":
                    case "down":
                        profile.Warnings.Add(L.T("گزینه اسکریپت/مدیریت (", "a script/management option (") + key +
                                             L.T(") نادیده گرفته شد؛ برنامه فقط ترافیک بازی را تونل می‌کند.",
                                                ") was ignored; the app only tunnels the game traffic."));
                        break;
                }

                // file references: when the profile sits next to its certificates we can pick them up
                if (key == "ca" && value.Length > 0) RememberFile(profile, "ca-file", value, sourceName);
                if (key == "cert" && value.Length > 0) RememberFile(profile, "cert-file", value, sourceName);
                if (key == "key" && value.Length > 0) RememberFile(profile, "key-file", value, sourceName);
                if ((key == "tls-auth" || key == "tls-crypt" || key == "tls-crypt-v2") && value.Length > 0)
                    RememberFile(profile, "tls-file", value, sourceName);
            }
            if (pendingTag.Length > 0 && inline.Length > 0) Store(profile, pendingTag, inline.ToString());

            if (profile.Remotes.Count == 0)
                profile.Warnings.Add(L.T("در فایل هیچ خط remote پیدا نشد.", "the file has no remote line."));
            else
            {
                string[] parts = profile.Remotes[0].Split(':');
                if (parts.Length > 3) profile.Network = parts[3];
            }
            if (profile.CaCert.Length == 0)
                profile.Warnings.Add(L.T("گواهی CA داخل فایل نیست (فایل‌های جداگانه قابل خواندن نیستند).",
                                         "the CA certificate is not inside the file (separate files cannot be read)."));
            if (profile.TlsAuthKind.Length > 0 && profile.TlsAuthKey.Length == 0)
                profile.Warnings.Add(L.T("کلید ", "the ") + profile.TlsAuthKind.Replace('_', '-') +
                                     L.T(" داخل فایل نیست؛ اتصال احتمالاً برقرار نمی‌شود.",
                                        " key is not inside the file; the connection will probably fail."));
            return profile;
        }

        private static void Store(OvpnProfile profile, string tag, string body)
        {
            string text = body.Trim();
            switch (tag)
            {
                case "ca": profile.CaCert = text; break;
                case "cert": profile.ClientCert = text; break;
                case "key": profile.ClientKey = text; break;
                case "tls-auth": profile.TlsAuthKey = text; if (profile.TlsAuthKind.Length == 0) profile.TlsAuthKind = "tls_auth"; break;
                case "tls-crypt": profile.TlsAuthKey = text; profile.TlsAuthKind = "tls_crypt"; break;
                case "tls-crypt-v2": profile.TlsAuthKey = text; profile.TlsAuthKind = "tls_crypt_v2"; break;
                default:
                    profile.Warnings.Add(L.T("بلوک ناشناخته نادیده گرفته شد: ", "unknown inline block ignored: ") + tag);
                    break;
            }
        }

        /// <summary>Reads a certificate/key that the profile references but does not contain.</summary>
        private static void RememberFile(OvpnProfile profile, string slot, string fileName, string sourceName)
        {
            try
            {
                if (string.IsNullOrEmpty(sourceName)) return;
                string folder = Path.GetDirectoryName(sourceName);
                if (string.IsNullOrEmpty(folder)) return;
                string path = Path.Combine(folder, fileName);
                if (!File.Exists(path)) return;
                string body = File.ReadAllText(path);
                switch (slot)
                {
                    case "ca-file": if (profile.CaCert.Length == 0) profile.CaCert = body.Trim(); break;
                    case "cert-file": if (profile.ClientCert.Length == 0) profile.ClientCert = body.Trim(); break;
                    case "key-file": if (profile.ClientKey.Length == 0) profile.ClientKey = body.Trim(); break;
                    case "tls-file": if (profile.TlsAuthKey.Length == 0) profile.TlsAuthKey = body.Trim(); break;
                }
            }
            catch { }
        }

        private static int DirectionOf(string value)
        {
            if (value == "1") return 1;
            if (value == "0") return 0;
            return -1;
        }

        private static int ParseInt(string value, int fallback)
        {
            int parsed;
            return int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out parsed) ? parsed : fallback;
        }

        private static string[] SplitWords(string line)
        {
            var words = new List<string>();
            var current = new StringBuilder();
            bool quoted = false;
            foreach (char c in line)
            {
                if (c == '"') { quoted = !quoted; continue; }
                if (!quoted && (c == ' ' || c == '\t'))
                {
                    if (current.Length > 0) { words.Add(current.ToString()); current.Length = 0; }
                    continue;
                }
                current.Append(c);
            }
            if (current.Length > 0) words.Add(current.ToString());
            return words.ToArray();
        }

        /// <summary>
        /// Builds the sing-box endpoint. The endpoint is deliberately passive: it never changes system
        /// routes by itself (route_no_pull) — the app decides that only the game address goes through.
        /// </summary>
        public Dictionary<string, object> ToEndpoint(string tag, string username, string password)
        {
            var endpoint = new Dictionary<string, object>();
            endpoint["type"] = "openvpn-client";
            endpoint["tag"] = tag;
            endpoint["mode"] = "tls";
            if (Remotes.Count > 1)
            {
                var servers = new List<object>();
                foreach (string remote in Remotes)
                {
                    string[] parts = remote.Split(':');
                    var server = new Dictionary<string, object>();
                    server["server"] = parts[0];
                    server["server_port"] = ParseInt(parts.Length > 1 ? parts[1] : "1194", 1194);
                    string network = parts.Length > 3 && parts[3].Length > 0 ? parts[3] : Network;
                    server["network"] = network;
                    servers.Add(server);
                }
                endpoint["servers"] = servers;
            }
            else
            {
                endpoint["server"] = Host;
                endpoint["server_port"] = Port;
            }
            endpoint["network"] = Network;
            if (username.Length > 0) endpoint["username"] = username;
            if (password.Length > 0) endpoint["password"] = password;
            endpoint["route_no_pull"] = true;              // the app routes the game itself
            endpoint["redirect_gateway"] = false;
            if (Mtu > 0) endpoint["mtu"] = Mtu;
            if (Fragment >= 68) endpoint["fragment"] = Fragment;
            if (Ping.Length > 0) endpoint["ping_interval"] = WholeSeconds(Ping);
            if (PingRestart.Length > 0) endpoint["ping_restart"] = WholeSeconds(PingRestart);
            if (RenegSec.Length > 0) endpoint["renegotiate_interval"] = WholeSeconds(RenegSec);
            if (CompLzo.Length > 0 && CompLzo != "no") endpoint["compression_lzo"] = CompLzo == "yes" ? "adaptive" : CompLzo;
            if (Compress.Length > 0 && Compress != "no") endpoint["compression"] = Compress == "yes" ? "stub-v2" : Compress;
            if (DataCiphers.Count > 0) endpoint["data_ciphers"] = ToObjects(DataCiphers);
            else if (Cipher.Length > 0) endpoint["data_ciphers_fallback"] = Cipher;
            if (Auth.Length > 0) endpoint["auth"] = Auth;

            var tls = new Dictionary<string, object>();
            if (CaCert.Length > 0) tls["certificate"] = SplitPemObjects(CaCert);
            if (ClientCert.Length > 0 && ClientKey.Length > 0)
            {
                tls["client_certificate"] = SplitPemObjects(ClientCert);
                tls["client_key"] = SplitPemObjects(ClientKey);
            }
            if (VerifyX509Name.Length > 0) tls["server_name"] = VerifyX509Name;
            else if (RemoteCertTlsServer && Host.Length > 0 && !IsIp(Host)) tls["server_name"] = Host;
            if (RemoteCertTlsServer) tls["remote_certificate_tls"] = "server";
            if (TlsVersionMin.Length > 0) tls["version_min"] = TlsVersionMin;
            if (TlsAuthKind.Length > 0 && TlsAuthKey.Length > 0)
            {
                var wrap = new Dictionary<string, object>();
                wrap["type"] = TlsAuthKind;
                wrap["key"] = SplitPemObjects(TlsAuthKey);
                // OpenVPN: key-direction 1 is the client side, 0 the server side
                if (TlsAuthKind == "tls_auth" && KeyDirection >= 0) wrap["direction"] = KeyDirection == 1 ? "client" : "server";
                tls["control_wrap"] = wrap;
            }
            endpoint["tls"] = tls;
            return endpoint;
        }

        private static string WholeSeconds(string value)
        {
            string trimmed = value.Trim();
            if (trimmed.Length == 0) return trimmed;
            char last = trimmed[trimmed.Length - 1];
            if (last < '0' || last > '9') return trimmed;
            return trimmed + "s";
        }

        private static bool IsIp(string text)
        {
            System.Net.IPAddress parsed;
            return System.Net.IPAddress.TryParse(text, out parsed);
        }

        private static List<object> ToObjects(List<string> values)
        {
            var list = new List<object>();
            foreach (string value in values) list.Add(value);
            return list;
        }

        /// <summary>
        /// The certificate fields take a list of PEM blocks; keeping them as an array of strings is
        /// what sing-box expects, and it keeps the JSON readable in the log.
        /// </summary>
        private static List<object> SplitPemObjects(string pem)
        {
            var list = new List<object>();
            string text = pem.Replace("\r\n", "\n").Trim();
            int index = 0;
            while (true)
            {
                int start = text.IndexOf("-----BEGIN", index, StringComparison.Ordinal);
                if (start < 0) break;
                int marker = text.IndexOf("-----", start + 10, StringComparison.Ordinal);
                if (marker < 0) break;
                string label = text.Substring(start + 10, marker - start - 10).Trim();
                int end = text.IndexOf("-----END " + label + "-----", marker, StringComparison.Ordinal);
                if (end < 0) break;
                int endOfBlock = text.IndexOf("-----", end + 9 + label.Length, StringComparison.Ordinal);
                if (endOfBlock < 0) endOfBlock = text.Length;
                else endOfBlock += 5;
                list.Add(text.Substring(start, endOfBlock - start));
                index = endOfBlock;
            }
            if (list.Count == 0 && text.Length > 0) list.Add(text);
            return list;
        }
    }
}

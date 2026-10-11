using ServerHelp.Core;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace ServerHelp.Net
{
    /// <summary>Everything WireGuard needs in order to talk to Cloudflare WARP.</summary>
    public sealed class WarpCredentials
    {
        public string PrivateKey = "";
        public string PublicKey = "";
        public string PeerPublicKey = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=";
        public string AddressV4 = "172.16.0.2";
        public string AddressV6 = "";
        public int[] Reserved = new int[] { 0, 0, 0 };
        public string ClientId = "";
        public string EndpointHost = "engage.cloudflareclient.com:2408";
        public string RegisteredAt = "";
        public string Source = "built-in";

        public bool HasPeer { get { return !string.IsNullOrEmpty(PeerPublicKey); } }

        public string Summary
        {
            get
            {
                string masked = PrivateKey.Length > 6 ? PrivateKey.Substring(0, 4) + "…" : "?";
                return "v4=" + AddressV4 + " v6=" + (AddressV6.Length > 12 ? AddressV6.Substring(0, 12) + "…" : AddressV6) +
                       " key=" + masked + " reserved=[" + Reserved[0] + "," + Reserved[1] + "," + Reserved[2] + "] src=" + Source;
            }
        }
    }

    /// <summary>
    /// Talks to Cloudflare's free WARP registration API, exactly like wgcf / warp-plus do:
    /// a fresh WireGuard key pair is registered and the returned peer key, interface addresses and
    /// reserved bytes become our tunnel identity. Cached on disk so later runs are instant.
    /// </summary>
    public static class WarpAccount
    {
        private const string ApiBase = "https://api.cloudflareclient.com";
        private static readonly string[] ApiVersions = new string[] { "v0a2158", "v0i1909051800" };

        public static WarpCredentials Load()
        {
            try
            {
                if (!File.Exists(AppPaths.WarpAccountFile)) return null;
                var d = Json.ParseObject(File.ReadAllText(AppPaths.WarpAccountFile, Encoding.UTF8));
                var c = new WarpCredentials();
                c.PrivateKey = Json.GetStr(d, "privateKey", "");
                c.PublicKey = Json.GetStr(d, "publicKey", "");
                c.PeerPublicKey = Json.GetStr(d, "peerPublicKey", c.PeerPublicKey);
                c.AddressV4 = Json.GetStr(d, "addressV4", c.AddressV4);
                c.AddressV6 = Json.GetStr(d, "addressV6", c.AddressV6);
                c.ClientId = Json.GetStr(d, "clientId", "");
                c.EndpointHost = Json.GetStr(d, "endpointHost", c.EndpointHost);
                c.RegisteredAt = Json.GetStr(d, "registeredAt", "");
                c.Source = "cache";
                var res = Json.Arr(Json.Get(d, "reserved"));
                if (res != null && res.Count == 3)
                {
                    var arr = new int[3];
                    for (int i = 0; i < 3; i++) arr[i] = (int)Convert.ToDouble(res[i], CultureInfo.InvariantCulture);
                    c.Reserved = arr;
                }
                if (string.IsNullOrEmpty(c.PrivateKey)) return null;
                Log.Info("WARP account loaded from cache (" + c.Summary + ")");
                return c;
            }
            catch (Exception ex)
            {
                Log.Warn("could not read cached WARP account: " + ex.Message);
                return null;
            }
        }

        public static void Save(WarpCredentials c)
        {
            try
            {
                AppPaths.EnsureAll();
                var w = new JsonWriter(true);
                w.StartObject();
                w.Prop("privateKey", c.PrivateKey);
                w.Prop("publicKey", c.PublicKey);
                w.Prop("peerPublicKey", c.PeerPublicKey);
                w.Prop("addressV4", c.AddressV4);
                w.Prop("addressV6", c.AddressV6);
                w.Prop("clientId", c.ClientId);
                w.Prop("endpointHost", c.EndpointHost);
                w.Prop("registeredAt", c.RegisteredAt);
                w.Name("reserved").StartArray();
                foreach (int b in c.Reserved) w.Value(b);
                w.EndArray();
                w.EndObject();
                File.WriteAllText(AppPaths.WarpAccountFile, w.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex) { Log.Warn("could not save WARP account: " + ex.Message); }
        }

        /// <summary>Registers a new key pair with Cloudflare. Returns null and sets error on failure.</summary>
        public static WarpCredentials Register(string privateKey, string publicKey, out string error)
        {
            error = "";
            foreach (string version in ApiVersions)
            {
                string body = BuildRegistrationBody(publicKey);
                string text = null;
                try
                {
                    text = PostJson(ApiBase + "/" + version + "/reg", body, "api.cloudflareclient.com");
                }
                catch (Exception ex)
                {
                    error = "api.cloudflareclient.com (" + version + "): " + ex.Message;
                    Log.Warn("WARP registration attempt failed: " + error);
                    continue;
                }
                if (string.IsNullOrEmpty(text))
                {
                    error = "empty answer from " + version;
                    continue;
                }
                try
                {
                    var creds = ParseRegistration(text, privateKey, publicKey);
                    if (creds != null)
                    {
                        creds.Source = "registered";
                        creds.RegisteredAt = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + "Z";
                        Save(creds);
                        Log.Info("WARP account registered: " + creds.Summary);
                        return creds;
                    }
                    error = "could not parse the registration answer";
                }
                catch (Exception ex)
                {
                    error = "parse error: " + ex.Message;
                }
            }
            return null;
        }

        private static string BuildRegistrationBody(string publicKey)
        {
            string tos = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
            var w = new JsonWriter(false);
            w.StartObject();
            w.Prop("key", publicKey);
            w.Prop("install_id", "");
            w.Prop("fcm_token", "");
            w.Prop("tos", tos);
            w.Prop("model", "PC");
            w.Prop("serial_number", "");
            w.Prop("locale", "en_US");
            w.EndObject();
            return w.ToString();
        }

        public static WarpCredentials ParseRegistration(string json, string privateKey, string publicKey)
        {
            var d = Json.ParseObject(json);
            var config = Json.Obj(Json.Get(d, "config"));
            if (config == null) return null;

            var creds = new WarpCredentials();
            creds.PrivateKey = privateKey;
            creds.PublicKey = publicKey;
            creds.ClientId = Json.GetStr(config, "client_id", "");

            var iface = Json.Obj(Json.Get(config, "interface"));
            if (iface != null)
            {
                var addresses = Json.Obj(Json.Get(iface, "addresses"));
                if (addresses != null)
                {
                    creds.AddressV4 = Json.GetStr(addresses, "v4", creds.AddressV4);
                    creds.AddressV6 = Json.GetStr(addresses, "v6", "");
                }
            }

            var peers = Json.Arr(Json.Get(config, "peers"));
            if (peers != null)
            {
                foreach (object o in peers)
                {
                    var pd = Json.Obj(o);
                    if (pd == null) continue;
                    creds.PeerPublicKey = Json.GetStr(pd, "public_key", creds.PeerPublicKey);
                    var ep = Json.Obj(Json.Get(pd, "endpoint"));
                    if (ep != null) creds.EndpointHost = Json.GetStr(ep, "host", creds.EndpointHost);
                    break;
                }
            }

            if (!string.IsNullOrEmpty(creds.ClientId))
            {
                try
                {
                    byte[] raw = Convert.FromBase64String(creds.ClientId);
                    if (raw.Length >= 3) creds.Reserved = new int[] { raw[0], raw[1], raw[2] };
                }
                catch { }
            }

            if (!creds.HasPeer) return null;
            return creds;
        }

        /// <summary>
        /// POSTs JSON. Falls back to a hand rolled TLS request against a DNS-over-HTTPS resolved
        /// address, because a poisoned system DNS would otherwise block registration completely.
        /// </summary>
        private static string PostJson(string url, string body, string host)
        {
            string firstError = null;
            try
            {
                using (var request = new HttpRequestMessage(HttpMethod.Post, url))
                {
                    request.Content = new StringContent(body, Encoding.UTF8, "application/json");
                    AddHeaders(request);
                    var task = NetUtil.Http.SendAsync(request);
                    if (task.Wait(15000))
                    {
                        var response = task.Result;
                        string text = response.Content.ReadAsStringAsync().Result;
                        if (response.IsSuccessStatusCode) return text;
                        firstError = "HTTP " + (int)response.StatusCode + ": " + Truncate(text, 300);
                    }
                    else firstError = "timeout";
                }
            }
            catch (Exception ex) { firstError = ex.Message; }

            Log.Warn("direct WARP registration failed (" + firstError + "), retrying over DoH-resolved address");
            try
            {
                string ip = NetUtil.ResolveDoh("https://1.1.1.1/dns-query", host, 6000);
                if (string.IsNullOrEmpty(ip)) ip = NetUtil.ResolveDoh("https://8.8.8.8/resolve", host, 6000);
                if (string.IsNullOrEmpty(ip)) throw new Exception("DoH could not resolve " + host);
                Log.Info("using DoH address " + ip + " for " + host);
                return PostJsonOverTls(ip, host, url, body);
            }
            catch (Exception ex)
            {
                throw new Exception(firstError + " / DoH path: " + ex.Message);
            }
        }

        private static void AddHeaders(HttpRequestMessage request)
        {
            request.Headers.TryAddWithoutValidation("User-Agent", "okhttp/3.12.1");
            request.Headers.TryAddWithoutValidation("CF-Client-Version", "a-6.11-2223");
            request.Headers.TryAddWithoutValidation("Accept", "application/json");
        }

        private static string PostJsonOverTls(string ip, string host, string url, string body)
        {
            var uri = new Uri(url);
            byte[] payload = Encoding.UTF8.GetBytes(body);
            using (var tcp = new TcpClient())
            {
                IAsyncResult ar = tcp.BeginConnect(IPAddress.Parse(ip), 443, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(8000)) throw new Exception("tls connect timeout");
                tcp.EndConnect(ar);
                using (var ssl = new SslStream(tcp.GetStream(), false, delegate (object s, X509Certificate c, X509Chain ch, SslPolicyErrors e) { return true; }))
                {
                    ssl.AuthenticateAsClient(host, null, SslProtocols.Tls12, false);
                    var sb = new StringBuilder();
                    sb.Append("POST ").Append(uri.PathAndQuery).Append(" HTTP/1.1\r\n");
                    sb.Append("Host: ").Append(host).Append("\r\n");
                    sb.Append("User-Agent: okhttp/3.12.1\r\n");
                    sb.Append("CF-Client-Version: a-6.11-2223\r\n");
                    sb.Append("Accept: application/json\r\n");
                    sb.Append("Content-Type: application/json; charset=UTF-8\r\n");
                    sb.Append("Content-Length: ").Append(payload.Length).Append("\r\n");
                    sb.Append("Connection: close\r\n\r\n");
                    byte[] head = Encoding.ASCII.GetBytes(sb.ToString());
                    ssl.Write(head, 0, head.Length);
                    ssl.Write(payload, 0, payload.Length);
                    ssl.Flush();
                    using (var reader = new StreamReader(ssl, Encoding.UTF8))
                    {
                        string all = reader.ReadToEnd();
                        int split = all.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                        if (split < 0) throw new Exception("bad HTTP answer");
                        string headers = all.Substring(0, split);
                        string content = all.Substring(split + 4);
                        if (headers.IndexOf(" 200 ", StringComparison.Ordinal) < 0 &&
                            headers.IndexOf(" 201 ", StringComparison.Ordinal) < 0)
                            throw new Exception("HTTP status: " + headers.Split('\n')[0].Trim() + " " + Truncate(content, 200));
                        if (content.IndexOf("chunked", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            headers.IndexOf("Transfer-Encoding: chunked", StringComparison.OrdinalIgnoreCase) >= 0)
                            content = Dechunk(content);
                        return content;
                    }
                }
            }
        }

        private static string Dechunk(string body)
        {
            var sb = new StringBuilder();
            int i = 0;
            while (i < body.Length)
            {
                int eol = body.IndexOf("\r\n", i, StringComparison.Ordinal);
                if (eol < 0) break;
                string sizeHex = body.Substring(i, eol - i).Trim();
                int size;
                if (!int.TryParse(sizeHex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out size)) break;
                if (size == 0) break;
                int start = eol + 2;
                if (start + size > body.Length) size = body.Length - start;
                sb.Append(body.Substring(start, size));
                i = start + size + 2;
            }
            return sb.ToString();
        }

        private static string Truncate(string s, int max)
        {
            if (s == null) return "";
            return s.Length <= max ? s : s.Substring(0, max);
        }
    }
}

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>
    /// Downloads a subscription link: the address providers hand out that returns a list of share
    /// links encoded in base64. It can go out directly or through one of the connections the user
    /// already has, which is the only way to fetch it when the link itself is filtered.
    /// </summary>
    public static class Subscription
    {
        public sealed class FetchResult
        {
            public bool Ok;
            public string Text = "";
            public string Error = "";
            public int Bytes;
            public int DelayMs = -1;
            public string Via = "direct";
        }

        public static FetchResult Fetch(string url, int timeoutMs, ConnectionEntry via)
        {
            var result = new FetchResult();
            if (string.IsNullOrEmpty(url)) { result.Error = L.T("آدرس اشتراک خالی است", "the subscription address is empty"); return result; }
            if (!url.StartsWith("http", StringComparison.OrdinalIgnoreCase)) url = "https://" + url;

            Uri uri;
            try { uri = new Uri(url); }
            catch (Exception ex) { result.Error = L.T("آدرس درست نیست: ", "the address is not valid: ") + ex.Message; return result; }

            long start = DateTime.UtcNow.Ticks;
            try
            {
                string body = via == null ? FetchDirect(uri, timeoutMs) : FetchThrough(via, uri, timeoutMs);
                result.Text = body;
                result.Bytes = body.Length;
                result.Ok = body.Trim().Length > 0;
                result.Via = via == null ? L.T("مستقیم", "direct") : via.Name;
                if (!result.Ok) result.Error = L.T("پاسخ خالی بود", "the answer was empty");
            }
            catch (Exception ex)
            {
                result.Error = ex.Message;
                Exception inner = ex;
                while (inner.InnerException != null) inner = inner.InnerException;
                if (inner != ex) result.Error += " — " + inner.Message;
            }
            result.DelayMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
            return result;
        }

        private static string FetchDirect(Uri uri, int timeoutMs)
        {
            var request = (HttpWebRequest)WebRequest.Create(uri);
            request.Timeout = timeoutMs;
            request.ReadWriteTimeout = timeoutMs;
            request.UserAgent = "ServerHelp/" + "1.0";
            request.AllowAutoRedirect = true;
            request.Proxy = null;                       // never inherit a broken system proxy
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var reader = new System.IO.StreamReader(stream, Encoding.UTF8))
                return reader.ReadToEnd();
        }

        /// <summary>
        /// A plain HTTP GET over a socket that is already established through one of the connections
        /// (SOCKS5, HTTP CONNECT or the local port of a tunnel). Redirects are followed by hand so a
        /// provider that redirects to a CDN still works.
        /// </summary>
        private static string FetchThrough(ConnectionEntry entry, Uri uri, int timeoutMs)
        {
            IConnector connector;
            if (entry.Kind == ConnectionKind.Socks5)
                connector = new Socks5Client(entry.Host, entry.Port, entry.User, entry.Password, timeoutMs);
            else if (entry.Kind == ConnectionKind.Http)
                connector = new HttpProxyClient(entry.Host, entry.Port, entry.User, entry.Password, timeoutMs);
            else if (entry.Kind == ConnectionKind.SingBoxConfig && entry.LocalSocksPort > 0)
                connector = new Socks5Client("127.0.0.1", entry.LocalSocksPort, timeoutMs);
            else
                // a tunnel-backed kind has to be brought up first; the caller does that
                throw new Exception(L.T("این نوع اتصال هنوز آماده نیست؛ یک پروکسی SOCKS5/HTTP انتخاب کنید " +
                                        "یا مستقیم امتحان کنید.",
                                        "this kind is not up yet; pick a SOCKS5/HTTP proxy or try direct."));

            string current = uri.ToString();
            for (int hop = 0; hop < 4; hop++)
            {
                var target = new Uri(current);
                int port = target.Port > 0 ? target.Port : (target.Scheme == "https" ? 443 : 80);
                Socket socket = connector.Connect(target.Host, port);
                using (socket)
                {
                    System.IO.Stream stream = new NetworkStream(socket);
                    if (target.Scheme == "https")
                    {
                        var ssl = new System.Net.Security.SslStream(stream, false, delegate { return true; });
                        ssl.AuthenticateAsClient(target.Host);
                        stream = ssl;
                    }
                    socket.SendTimeout = timeoutMs;
                    socket.ReceiveTimeout = timeoutMs;
                    string path = string.IsNullOrEmpty(target.PathAndQuery) ? "/" : target.PathAndQuery;
                    string request = "GET " + path + " HTTP/1.1\r\nHost: " + target.Host +
                                     "\r\nUser-Agent: ServerHelp\r\nAccept: */*\r\nConnection: close\r\n\r\n";
                    byte[] head = Encoding.ASCII.GetBytes(request);
                    stream.Write(head, 0, head.Length);
                    stream.Flush();

                    var buffer = new byte[8192];
                    var body = new StringBuilder();
                    var raw = new System.IO.MemoryStream();
                    int read;
                    while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        raw.Write(buffer, 0, read);
                        if (raw.Length > 4 * 1024 * 1024) break;     // a subscription is never this big
                    }
                    string text = Encoding.UTF8.GetString(raw.ToArray());
                    int headerEnd = text.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                    string headerText = headerEnd > 0 ? text.Substring(0, headerEnd) : text;
                    string bodyText = headerEnd > 0 ? text.Substring(headerEnd + 4) : "";
                    body.Append(bodyText);

                    // chunked or plain: both end up in bodyText as-is, the parser tolerates the noise
                    if (headerText.Contains(" 30") || headerText.Contains(" 301") || headerText.Contains(" 302") ||
                        headerText.Contains(" 307") || headerText.Contains(" 308"))
                    {
                        string location = FindHeader(headerText, "Location");
                        if (!string.IsNullOrEmpty(location))
                        {
                            current = location.StartsWith("http", StringComparison.OrdinalIgnoreCase)
                                ? location
                                : new Uri(target, location).ToString();
                            continue;
                        }
                    }
                    return CleanBody(headerText, body.ToString());
                }
            }
            throw new Exception(L.T("تعداد ریدایرکت‌ها زیاد بود", "too many redirects"));
        }

        /// <summary>Strips chunked framing so the base64 body is exactly what the provider sent.</summary>
        private static string CleanBody(string headers, string body)
        {
            if (headers.IndexOf("chunked", StringComparison.OrdinalIgnoreCase) < 0) return body;
            var sb = new StringBuilder();
            int index = 0;
            while (index < body.Length)
            {
                int lineEnd = body.IndexOf("\r\n", index, StringComparison.Ordinal);
                if (lineEnd < 0) break;
                string sizeLine = body.Substring(index, lineEnd - index).Trim();
                int size;
                if (!int.TryParse(sizeLine, System.Globalization.NumberStyles.HexNumber,
                                  System.Globalization.CultureInfo.InvariantCulture, out size)) break;
                index = lineEnd + 2;
                if (size == 0) break;
                if (index + size > body.Length) size = body.Length - index;
                sb.Append(body.Substring(index, size));
                index += size + 2;
            }
            return sb.ToString();
        }

        private static string FindHeader(string headers, string name)
        {
            foreach (string line in headers.Split('\n'))
            {
                string trimmed = line.Trim();
                if (trimmed.StartsWith(name + ":", StringComparison.OrdinalIgnoreCase))
                    return trimmed.Substring(name.Length + 1).Trim();
            }
            return "";
        }

        /// <summary>
        /// A subscription is a base64 blob that decodes to one share link per line. Both the raw
        /// shape and the already decoded shape are accepted.
        /// </summary>
        public static List<ConnectionEntry> Parse(string body, out List<string> problems)
        {
            problems = new List<string>();
            var entries = new List<ConnectionEntry>();
            if (string.IsNullOrEmpty(body)) return entries;

            string text = body.Trim();
            if (text.IndexOf("://", StringComparison.Ordinal) < 0)
            {
                string decoded = ConnectionParser.TryDecodeBase64Blob(text);
                if (!string.IsNullOrEmpty(decoded)) text = decoded;
            }

            List<string> local;
            var parsed = ConnectionParser.ParseBlob(text, out local);
            foreach (string problem in local) problems.Add(problem);
            entries.AddRange(parsed);
            return entries;
        }
    }
}

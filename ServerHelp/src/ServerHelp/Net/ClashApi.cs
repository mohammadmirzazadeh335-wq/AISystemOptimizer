using ServerHelp.Core;
using System;
using System.Collections.Generic;

namespace ServerHelp.Net
{
    /// <summary>
    /// Thin client for sing-box's Clash API. It answers two questions the UI cares about:
    /// which WARP endpoint the auto group picked, and how fast each endpoint really is.
    /// </summary>
    public static class ClashApi
    {
        public static string Get(string controller, string secret, string path, int timeoutMs)
        {
            try
            {
                string url = "http://" + controller + path;
                using (var handler = new System.Net.Http.HttpClientHandler())
                {
                    handler.UseProxy = false;
                    using (var http = new System.Net.Http.HttpClient(handler))
                    {
                        http.Timeout = TimeSpan.FromMilliseconds(timeoutMs);
                        var request = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Get, url);
                        if (!string.IsNullOrEmpty(secret))
                            request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + secret);
                        var task = http.SendAsync(request);
                        if (!task.Wait(timeoutMs + 500)) return null;
                        var response = task.Result;
                        if (!response.IsSuccessStatusCode) return null;
                        var read = response.Content.ReadAsStringAsync();
                        if (!read.Wait(2000)) return null;
                        return read.Result;
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Debug("clash api " + path + " failed: " + ex.Message);
                return null;
            }
        }

        /// <summary>Tag currently selected inside an auto/selector group, or null.</summary>
        public static string Selected(string controller, string secret, string groupTag)
        {
            string text = Get(controller, secret, "/proxies/" + Uri.EscapeDataString(groupTag), 2500);
            if (string.IsNullOrEmpty(text)) return null;
            try
            {
                var d = Core.Json.ParseObject(text);
                return Core.Json.GetStr(d, "now", null);
            }
            catch { return null; }
        }

        /// <summary>Real latency of one outbound/endpoint through the tunnel, in milliseconds.</summary>
        public static int Delay(string controller, string secret, string tag, string testUrl, int timeoutMs)
        {
            string path = "/proxies/" + Uri.EscapeDataString(tag) + "/delay?timeout=" + timeoutMs +
                          "&url=" + Uri.EscapeDataString(testUrl);
            string text = Get(controller, secret, path, timeoutMs + 1500);
            if (string.IsNullOrEmpty(text)) return -1;
            try
            {
                var d = Core.Json.ParseObject(text);
                return Core.Json.GetInt(d, "delay", -1);
            }
            catch { return -1; }
        }

        public static List<string> Names(string controller, string secret)
        {
            var list = new List<string>();
            string text = Get(controller, secret, "/proxies", 3000);
            if (string.IsNullOrEmpty(text)) return list;
            try
            {
                var d = Core.Json.ParseObject(text);
                var proxies = Core.Json.Obj(Core.Json.Get(d, "proxies"));
                if (proxies != null) foreach (var kv in proxies) list.Add(kv.Key);
            }
            catch { }
            return list;
        }
    }
}

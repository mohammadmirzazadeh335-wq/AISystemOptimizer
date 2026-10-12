using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net.Security;
using System.Net.Sockets;
using System.Text;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>How steady a route is: the numbers a player actually feels.</summary>
    public sealed class QualityResult
    {
        public int Samples;
        public int Lost;
        public int MinMs = -1;
        public int AvgMs = -1;
        public int MaxMs = -1;
        public int JitterMs = -1;
        public int SpeedKbps = -1;
        public string Detail = "";

        public int LossPercent
        {
            get { return Samples <= 0 ? -1 : (int)Math.Round(Lost * 100.0 / Samples); }
        }

        public bool Ok { get { return AvgMs > 0; } }

        /// <summary>One line for the table: "42 ms ±6 · loss 0% · 890 KB/s".</summary>
        public string Summary()
        {
            if (!Ok) return Detail.Length > 0 ? Detail : L.T("اندازه‌گیری نشد", "not measured");
            var sb = new StringBuilder();
            sb.Append(AvgMs).Append(" ms");
            if (JitterMs > 0) sb.Append(" ±").Append(JitterMs);
            if (Samples > 1) sb.Append(" • ").Append(L.T("افت ", "loss ")).Append(LossPercent).Append('%');
            if (SpeedKbps > 0) sb.Append(" • ").Append(SpeedKbps).Append(L.T(" کیلوبایت/ثانیه", " KB/s"));
            return sb.ToString();
        }

        /// <summary>A single word a player understands, used as the quality column.</summary>
        public string Grade()
        {
            if (!Ok) return L.T("بد", "bad");
            if (LossPercent >= 20) return L.T("پرافت", "lossy");
            if (JitterMs >= 40) return L.T("لرزان", "unstable");
            if (AvgMs < 90 && JitterMs < 15) return L.T("عالی", "excellent");
            if (AvgMs < 160) return L.T("خوب", "good");
            if (AvgMs < 260) return L.T("متوسط", "fair");
            return L.T("ضعیف", "poor");
        }
    }

    /// <summary>
    /// Measures what a dashboard ping never shows: the spread. Five measurements through the same
    /// route give the average, the jitter (how much the delay moves between samples) and the loss,
    /// which is what decides whether the game feels smooth or rubber bands.
    /// </summary>
    public static class QualityTest
    {
        public static QualityResult Measure(IConnector connector, string host, int port, int samples, int timeoutMs)
        {
            var result = new QualityResult();
            if (samples < 2) samples = 2;
            if (samples > 20) samples = 20;

            var delays = new List<int>();
            var failures = new List<string>();
            for (int i = 0; i < samples; i++)
            {
                try
                {
                    McStatus status = McPing.Status(host, port, timeoutMs, connector);
                    if (status != null && status.Ok) delays.Add(Math.Max(1, status.LatencyMs));
                    else failures.Add(status == null || string.IsNullOrEmpty(status.Error) ? "no answer" : status.Error);
                }
                catch (Exception ex)
                {
                    failures.Add(ex.Message);
                }
                if (i + 1 < samples) System.Threading.Thread.Sleep(120);
            }

            result.Samples = samples;
            result.Lost = failures.Count;
            if (delays.Count == 0)
            {
                result.Detail = failures.Count > 0
                    ? L.T("هیچ پاسخی نیامد: ", "nothing answered: ") + Shorten(failures[0])
                    : L.T("هیچ پاسخی نیامد", "nothing answered");
                return result;
            }

            int min = int.MaxValue, max = 0, sum = 0;
            foreach (int delay in delays)
            {
                if (delay < min) min = delay;
                if (delay > max) max = delay;
                sum += delay;
            }
            result.MinMs = min;
            result.MaxMs = max;
            result.AvgMs = (int)Math.Round((double)sum / delays.Count);

            // jitter: the average size of the step between one sample and the next
            int movement = 0;
            for (int i = 1; i < delays.Count; i++) movement += Math.Abs(delays[i] - delays[i - 1]);
            result.JitterMs = delays.Count > 1 ? (int)Math.Round((double)movement / (delays.Count - 1)) : 0;
            if (result.Lost > 0)
                result.Detail = L.T("در ", "during ") + samples + L.T(" نمونه، ", " samples, ") + result.Lost +
                                L.T(" پاسخ نیامد", " did not answer");
            return result;
        }

        /// <summary>
        /// Small download through the same route. It answers the question "can this path carry data
        /// at all", which is what matters before a game is launched through it.
        /// </summary>
        public static int DownloadSpeed(IConnector connector, int bytes, int timeoutMs)
        {
            const string host = "speed.cloudflare.com";
            string path = "/__down?bytes=" + bytes.ToString(CultureInfo.InvariantCulture);
            long start = DateTime.UtcNow.Ticks;
            try
            {
                Socket socket = connector.Connect(host, 443);
                using (socket)
                using (var ssl = new SslStream(new NetworkStream(socket), false, delegate { return true; }))
                {
                    ssl.AuthenticateAsClient(host);
                    socket.SendTimeout = timeoutMs;
                    socket.ReceiveTimeout = timeoutMs;
                    ssl.WriteTimeout = timeoutMs;
                    ssl.ReadTimeout = timeoutMs;
                    string request = "GET " + path + " HTTP/1.1\r\nHost: " + host +
                                     "\r\nUser-Agent: ServerHelp\r\nConnection: close\r\nAccept: */*\r\n\r\n";
                    byte[] head = Encoding.ASCII.GetBytes(request);
                    ssl.Write(head);
                    ssl.Flush();

                    var buffer = new byte[16384];
                    int total = 0;
                    bool headersDone = false;
                    while (true)
                    {
                        int read = ssl.Read(buffer, 0, buffer.Length);
                        if (read <= 0) break;
                        if (!headersDone)
                        {
                            // the body starts after the blank line; a handful of bytes at most is lost
                            string text = Encoding.ASCII.GetString(buffer, 0, Math.Min(read, 2048));
                            int blank = text.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                            if (blank >= 0)
                            {
                                headersDone = true;
                                total += Math.Max(0, read - (blank + 4));
                                start = DateTime.UtcNow.Ticks;      // time the body only
                            }
                            continue;
                        }
                        total += read;
                        if (total >= bytes) break;
                        if ((DateTime.UtcNow.Ticks - start) > timeoutMs * TimeSpan.TicksPerMillisecond) break;
                    }
                    double seconds = Math.Max(0.05, (DateTime.UtcNow.Ticks - start) / (double)TimeSpan.TicksPerSecond);
                    if (total <= 0) return -1;
                    return (int)Math.Round(total / 1024.0 / seconds);
                }
            }
            catch (Exception ex)
            {
                Log.Debug("speed test failed: " + ex.Message);
                return -1;
            }
        }

        private static string Shorten(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            return text.Length > 120 ? text.Substring(0, 120) : text;
        }
    }
}

using ServerHelp.Core;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace ServerHelp.Net
{
    public enum LoginVerdict
    {
        Unknown = 0,
        /// <summary>Server asked for encryption: an official (premium) account is required.</summary>
        OnlineMode = 1,
        /// <summary>Server rejected us for another reason (whitelist, full, old client) - it is cracked-friendly.</summary>
        OfflineReachable = 2,
        /// <summary>Login succeeded, we were inside the server for a moment.</summary>
        Success = 3,
        Failed = 4
    }

    public sealed class McStatus
    {
        public bool Ok;
        public string Error = "";
        public string Motd = "";
        public string VersionName = "";
        public int PlayersOnline = -1;
        public int PlayersMax = -1;
        public int LatencyMs = -1;
        public string Raw = "";
        public string Via = "";

        public string Short
        {
            get
            {
                if (!Ok) return L.T("بی‌پاسخ", "no answer");
                return L.N(LatencyMs) + L.T(" میلی‌ثانیه", " ms") +
                       (PlayersOnline >= 0 ? ("  " + L.N(PlayersOnline) + "/" + L.N(PlayersMax)) : "");
            }
        }
    }

    /// <summary>Minecraft Server List Ping and a login probe, direct or through a SOCKS proxy.</summary>
    public static class McPing
    {
        public const int ModernProtocol = 767;   // 1.21.x
        public const int LegacyProtocol = 47;    // 1.8

        public static McStatus Status(string host, int port, int timeoutMs, Socks5Client proxy)
        {
            int[] protocols = new int[] { ModernProtocol, LegacyProtocol, -1 };
            McStatus last = null;
            foreach (int proto in protocols)
            {
                last = StatusOnce(host, port, timeoutMs, proxy, proto);
                if (last.Ok) return last;
                if (last.Error != null && last.Error.IndexOf("reset", StringComparison.OrdinalIgnoreCase) >= 0) break;
            }
            return last;
        }

        private static McStatus StatusOnce(string host, int port, int timeoutMs, Socks5Client proxy, int protocol)
        {
            var status = new McStatus();
            status.Via = proxy == null ? L.T("مستقیم", "direct") : L.T("تونل", "tunnel");
            Socket socket = null;
            try
            {
                long start = DateTime.UtcNow.Ticks;
                socket = Open(host, port, timeoutMs, proxy);
                socket.ReceiveTimeout = timeoutMs;
                socket.SendTimeout = timeoutMs;

                var payload = new List<byte>();
                payload.Add(0x00);                              // packet id
                payload.AddRange(VarInt(protocol));
                byte[] name = Encoding.UTF8.GetBytes(host);
                payload.AddRange(VarInt(name.Length));
                payload.AddRange(name);
                payload.Add((byte)(port >> 8));
                payload.Add((byte)(port & 0xFF));
                payload.AddRange(VarInt(1));                    // next state: status
                SendPacket(socket, payload.ToArray());
                SendPacket(socket, new byte[] { 0x00 });

                byte[] json = ReadPacket(socket, out int packetId);
                status.LatencyMs = (int)((DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                if (packetId != 0) { status.Error = "unexpected packet " + packetId; return status; }

                int idx = 0;
                int len = ReadVarInt(json, ref idx);
                string text = Encoding.UTF8.GetString(json, idx, Math.Min(len, json.Length - idx));
                status.Raw = text;
                var d = Json.Obj(Json.Parse(text));
                if (d != null)
                {
                    status.Motd = CleanMotd(Json.GetStr(d, "description", ""));
                    var players = Json.Obj(Json.Get(d, "players"));
                    if (players != null)
                    {
                        status.PlayersOnline = Json.GetInt(players, "online", -1);
                        status.PlayersMax = Json.GetInt(players, "max", -1);
                    }
                    var version = Json.Obj(Json.Get(d, "version"));
                    if (version != null) status.VersionName = Json.GetStr(version, "name", "");
                }
                status.Ok = true;
                return status;
            }
            catch (Exception ex)
            {
                status.Error = ex.Message;
                return status;
            }
            finally
            {
                if (socket != null) { try { socket.Close(); } catch { } }
            }
        }

        /// <summary>
        /// Starts a login and looks at the very first answer: an encryption request means the
        /// server runs in online (premium) mode - useful to know before launching the game.
        /// </summary>
        public static LoginVerdict LoginProbe(string host, int port, string nickname, int timeoutMs, Socks5Client proxy, out string message)
        {
            message = "";
            Socket socket = null;
            try
            {
                socket = Open(host, port, timeoutMs, proxy);
                socket.ReceiveTimeout = timeoutMs;
                socket.SendTimeout = timeoutMs;

                var handshake = new List<byte>();
                handshake.Add(0x00);
                handshake.AddRange(VarInt(ModernProtocol));
                byte[] name = Encoding.UTF8.GetBytes(host);
                handshake.AddRange(VarInt(name.Length));
                handshake.AddRange(name);
                handshake.Add((byte)(port >> 8));
                handshake.Add((byte)(port & 0xFF));
                handshake.AddRange(VarInt(2));      // login
                SendPacket(socket, handshake.ToArray());

                byte[] nick = Encoding.UTF8.GetBytes(string.IsNullOrEmpty(nickname) ? "ServerHelp" : nickname);
                var login = new List<byte>();
                login.Add(0x00);
                login.AddRange(VarInt(nick.Length));
                login.AddRange(nick);
                if (ModernProtocol >= 764)
                {
                    login.AddRange(OfflineUuidBytes(nickname));
                }
                SendPacket(socket, login.ToArray());

                byte[] body = ReadPacket(socket, out int id);
                switch (id)
                {
                    case 0x01:
                        message = L.T("سرور در حالت آنلاین (پریمیوم) است؛ برای ورود باید اکانت رسمی ماینکرفت داشته باشید.",
                                      "The server is in online (premium) mode: an official Minecraft account is required.");
                        return LoginVerdict.OnlineMode;
                    case 0x02:
                        message = L.T("ورود آزمایشی موفق بود؛ سرور آفلاین است و مشکلی برای اتصال نیست.",
                                      "Test login succeeded: the server is cracked-friendly.");
                        return LoginVerdict.Success;
                    case 0x00:
                        message = ParseKick(body);
                        return LoginVerdict.OfflineReachable;
                    default:
                        message = "packet " + id;
                        return LoginVerdict.Unknown;
                }
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return LoginVerdict.Failed;
            }
            finally
            {
                if (socket != null) { try { socket.Close(); } catch { } }
            }
        }

        private static string ParseKick(byte[] body)
        {
            try
            {
                int idx = 0;
                int len = ReadVarInt(body, ref idx);
                string json = Encoding.UTF8.GetString(body, idx, Math.Min(len, body.Length - idx));
                var d = Json.Obj(Json.Parse(json));
                if (d != null)
                {
                    object text = Json.Get(d, "text");
                    if (text is string) return (string)text;
                    var extra = Json.Arr(Json.Get(d, "extra"));
                    if (extra != null)
                    {
                        var sb = new StringBuilder();
                        foreach (object o in extra)
                        {
                            var od = Json.Obj(o);
                            if (od != null) sb.Append(Json.GetStr(od, "text", ""));
                        }
                        if (sb.Length > 0) return sb.ToString();
                    }
                }
                return json;
            }
            catch { return ""; }
        }

        // ------------------------------------------------------------------ plumbing

        private static Socket Open(string host, int port, int timeoutMs, Socks5Client proxy)
        {
            if (proxy != null) return proxy.Connect(host, port);

            IPAddress ip;
            if (IPAddress.TryParse(host, out ip))
            {
                var s = new Socket(ip.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
                s.NoDelay = true;
                IAsyncResult ar = s.BeginConnect(ip, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) { try { s.Close(); } catch { } throw new Exception("connect timeout"); }
                s.EndConnect(ar);
                return s;
            }

            var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            socket.NoDelay = true;
            IAsyncResult ar2 = socket.BeginConnect(host, port, null, null);
            if (!ar2.AsyncWaitHandle.WaitOne(timeoutMs)) { try { socket.Close(); } catch { } throw new Exception("connect timeout"); }
            socket.EndConnect(ar2);
            return socket;
        }

        private static void SendPacket(Socket socket, byte[] payload)
        {
            byte[] len = VarInt(payload.Length);
            byte[] buffer = new byte[len.Length + payload.Length];
            Buffer.BlockCopy(len, 0, buffer, 0, len.Length);
            Buffer.BlockCopy(payload, 0, buffer, len.Length, payload.Length);
            socket.Send(buffer);
        }

        private static byte[] ReadPacket(Socket socket, out int packetId)
        {
            int length = ReadVarInt(socket);
            byte[] body = Socks5Client.ReadExact(socket, length);
            int idx = 0;
            packetId = ReadVarInt(body, ref idx);
            int rest = body.Length - idx;
            byte[] result = new byte[rest];
            Buffer.BlockCopy(body, idx, result, 0, rest);
            return result;
        }

        public static byte[] VarInt(int value)
        {
            var bytes = new List<byte>();
            uint v = (uint)value;
            while (true)
            {
                if ((v & ~0x7FU) == 0) { bytes.Add((byte)v); return bytes.ToArray(); }
                bytes.Add((byte)((v & 0x7F) | 0x80));
                v >>= 7;
            }
        }

        public static int ReadVarInt(byte[] data, ref int index)
        {
            int value = 0, position = 0;
            while (true)
            {
                if (index >= data.Length) throw new Exception("varint out of range");
                byte b = data[index++];
                value |= (b & 0x7F) << position;
                if ((b & 0x80) == 0) return value;
                position += 7;
                if (position > 35) throw new Exception("varint too big");
            }
        }

        private static int ReadVarInt(Socket socket)
        {
            int value = 0, position = 0;
            while (true)
            {
                byte[] one = Socks5Client.ReadExact(socket, 1);
                byte b = one[0];
                value |= (b & 0x7F) << position;
                if ((b & 0x80) == 0) return value;
                position += 7;
                if (position > 35) throw new Exception("varint too big");
            }
        }

        public static byte[] OfflineUuidBytes(string nickname)
        {
            // Same scheme as the vanilla server: md5 of "OfflinePlayer:<name>" with version 3 bits.
            try
            {
                using (var md5 = System.Security.Cryptography.MD5.Create())
                {
                    byte[] hash = md5.ComputeHash(Encoding.UTF8.GetBytes("OfflinePlayer:" + nickname));
                    hash[6] = (byte)((hash[6] & 0x0F) | 0x30);
                    hash[8] = (byte)((hash[8] & 0x3F) | 0x80);
                    return hash;
                }
            }
            catch { return new byte[16]; }
        }

        public static string OfflineUuid(string nickname)
        {
            byte[] b = OfflineUuidBytes(nickname);
            var sb = new StringBuilder(36);
            for (int i = 0; i < 16; i++)
            {
                if (i == 4 || i == 6 || i == 8 || i == 10) sb.Append('-');
                sb.Append(b[i].ToString("x2", CultureInfo.InvariantCulture));
            }
            return sb.ToString();
        }

        private static string CleanMotd(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return "";
            var sb = new StringBuilder();
            foreach (char c in raw)
            {
                if (c == '\u00a7') { sb.Append(' '); continue; }
                sb.Append(c);
            }
            return sb.ToString().Trim();
        }
    }
}

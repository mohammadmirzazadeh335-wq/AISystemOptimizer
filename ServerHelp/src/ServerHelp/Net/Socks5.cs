using System;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace ServerHelp.Net
{
    /// <summary>
    /// Minimal SOCKS5 client. The tunnel exposes a local SOCKS port, which lets the app measure
    /// the real game latency through the tunnel before Minecraft is even started.
    /// </summary>
    public sealed class Socks5Client : IConnector
    {
        public string Host = "127.0.0.1";
        public int Port = 22345;
        public int TimeoutMs = 5000;
        public string User = "";
        public string Password = "";

        public Socks5Client() { }

        public Socks5Client(string host, int port, int timeoutMs)
        {
            Host = host;
            Port = port;
            TimeoutMs = timeoutMs;
        }

        public Socks5Client(string host, int port, string user, string password, int timeoutMs)
        {
            Host = host;
            Port = port;
            User = user ?? "";
            Password = password ?? "";
            TimeoutMs = timeoutMs;
        }

        public string Describe { get { return "socks5 " + Host + ":" + Port; } }

        /// <summary>Opens a TCP connection to targetHost:targetPort through the proxy.</summary>
        public Socket Connect(string targetHost, int targetPort)
        {
            IPAddress proxyIp;
            if (!IPAddress.TryParse(Host, out proxyIp))
            {
                var addrs = NetUtil.ResolveSimple(Host);
                if (addrs.Count == 0) throw new Exception("proxy host does not resolve: " + Host);
                if (!IPAddress.TryParse(addrs[0], out proxyIp)) throw new Exception("bad proxy address");
            }

            var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                socket.NoDelay = true;
                socket.ReceiveTimeout = TimeoutMs;
                socket.SendTimeout = TimeoutMs;

                IAsyncResult ar = socket.BeginConnect(proxyIp, Port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(TimeoutMs)) throw new Exception("proxy connect timeout");
                socket.EndConnect(ar);

                // greeting: version 5 with the methods we support (no-auth, and user/password
                // when the entry carries credentials)
                bool needsAuth = !string.IsNullOrEmpty(User);
                byte[] greeting = needsAuth ? new byte[] { 0x05, 0x02, 0x00, 0x02 } : new byte[] { 0x05, 0x01, 0x00 };
                socket.Send(greeting);
                byte[] greet = ReadExact(socket, 2);
                if (greet[0] != 0x05) throw new Exception("not a socks5 proxy");
                if (greet[1] == 0x02)
                {
                    if (!needsAuth) throw new Exception("socks5 proxy requires a user name and password");
                    var auth = new System.Collections.Generic.List<byte>();
                    byte[] user = Encoding.UTF8.GetBytes(User);
                    byte[] pass = Encoding.UTF8.GetBytes(Password);
                    if (user.Length > 255 || pass.Length > 255) throw new Exception("proxy credentials too long");
                    auth.Add(0x01);
                    auth.Add((byte)user.Length); auth.AddRange(user);
                    auth.Add((byte)pass.Length); auth.AddRange(pass);
                    socket.Send(auth.ToArray());
                    byte[] authReply = ReadExact(socket, 2);
                    if (authReply[1] != 0x00) throw new Exception("the socks5 proxy rejected the user name or password");
                }
                else if (greet[1] != 0x00)
                {
                    throw new Exception("socks5 proxy requires authentication (" + greet[1] + ")");
                }

                // request
                var req = new System.Collections.Generic.List<byte>();
                req.Add(0x05); req.Add(0x01); req.Add(0x00); // connect, reserved
                IPAddress targetIp;
                if (IPAddress.TryParse(targetHost, out targetIp) && targetIp.AddressFamily == AddressFamily.InterNetwork)
                {
                    req.Add(0x01);
                    req.AddRange(targetIp.GetAddressBytes());
                }
                else if (IPAddress.TryParse(targetHost, out targetIp))
                {
                    req.Add(0x04);
                    req.AddRange(targetIp.GetAddressBytes());
                }
                else
                {
                    byte[] name = Encoding.ASCII.GetBytes(targetHost);
                    if (name.Length > 255) throw new Exception("host name too long");
                    req.Add(0x03);
                    req.Add((byte)name.Length);
                    req.AddRange(name);
                }
                req.Add((byte)(targetPort >> 8));
                req.Add((byte)(targetPort & 0xFF));
                socket.Send(req.ToArray());

                byte[] head = ReadExact(socket, 4);
                if (head[0] != 0x05) throw new Exception("bad socks5 reply");
                if (head[1] != 0x00) throw new Exception("socks5 connect failed, code " + head[1]);
                int skip;
                switch (head[3])
                {
                    case 0x01: skip = 4; break;
                    case 0x04: skip = 16; break;
                    case 0x03: skip = ReadExact(socket, 1)[0]; break;
                    default: throw new Exception("bad socks5 address type");
                }
                ReadExact(socket, skip + 2);
                return socket;
            }
            catch
            {
                try { socket.Close(); } catch { }
                throw;
            }
        }

        public static byte[] ReadExact(Socket socket, int count)
        {
            var buf = new byte[count];
            int got = 0;
            while (got < count)
            {
                int n = socket.Receive(buf, got, count - got, SocketFlags.None);
                if (n <= 0) throw new Exception("connection closed while reading");
                got += n;
            }
            return buf;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using ServerHelp.Core;

namespace ServerHelp.Net
{
    /// <summary>What a real MTProto check found out about a Telegram proxy.</summary>
    public sealed class MtprotoCheck
    {
        public bool Connected;            // TCP reached the proxy
        public bool HelloAnswered;        // fake-TLS: the proxy answered our ClientHello at all
        public bool ServerDigestOk;       // fake-TLS: the ServerHello carried our HMAC, so the secret is right
        public bool Verified;             // full req_pq_multi -> resPQ round trip through the proxy
        public bool NonceEchoed;          // the reply contained our nonce
        public int ConnectMs = -1;
        public int HandshakeMs = -1;
        public int RttMs = -1;            // the honest delay: req_pq -> resPQ
        public int Dc = 2;
        public MtprotoMode Mode = MtprotoMode.FakeTls;
        public string Domain = "";
        public string Status = "";        // one short line for the list
        public string Detail = "";        // what exactly happened

        /// <summary>The delay we report: the protocol round trip when we have one, the handshake otherwise.</summary>
        public int DelayMs
        {
            get
            {
                if (RttMs > 0) return RttMs;
                if (HandshakeMs > 0) return HandshakeMs;
                return ConnectMs;
            }
        }
    }

    /// <summary>
    /// Speaks the real MTProto proxy protocol: obfuscated2 (classic, <c>dd</c> secured and
    /// <c>ee</c> fake-TLS), the padded-intermediate framing, and the first step of the Telegram
    /// handshake (<c>req_pq_multi</c> -> <c>resPQ</c>). A proxy that answers that with our nonce
    /// echoed is proven to work and to have the right secret - a port scanner cannot fake it.
    ///
    /// Wire format references: core.telegram.org/mtproto/mtproto-transports,
    /// core.telegram.org/mtproto/auth_key, and the servers 9seconds/mtg + alexbers/mtprotoproxy.
    /// </summary>
    public sealed class MtprotoClient : IDisposable
    {
        private const uint CtorReqPqMulti = 0xbe7e8ef1;
        private const uint CtorResPQ = 0x05162463;
        private const uint CtorMsgContainer = 0x73f1f8dc;

        private const int FrameHeader = 4;
        private const int MaxRecordPayload = 16384;
        private const int MaxFrame = 1024 * 1024;

        // socket bytes and the plain MTProto bytes after the TLS records are stripped
        private readonly byte[] _raw = new byte[65536];
        private int _rawFrom, _rawTo;
        private readonly byte[] _plain = new byte[65536];
        private int _plainFrom, _plainTo;

        private Socket _socket;
        private AesCtr _enc, _dec;
        private bool _tls;
        private int _timeoutMs = 3000;

        public bool TlsLayer { get { return _tls; } }
        public bool SocketOpened { get; private set; }
        public bool ServerDigestOk { get; private set; }
        public bool HelloAnswered { get; private set; }

        // ------------------------------------------------------------------ randomness

        private static readonly RandomNumberGenerator Rng = RandomNumberGenerator.Create();

        private static void RandomBytes(byte[] buffer)
        {
            lock (Rng) { Rng.GetBytes(buffer); }
        }

        private static byte[] RandomBytes(int count)
        {
            var buffer = new byte[count];
            RandomBytes(buffer);
            return buffer;
        }

        // ------------------------------------------------------------------ connecting

        public static bool ConnectSocket(string host, int port, int timeoutMs, out Socket socket, out string error)
        {
            socket = null;
            error = "";
            Socket candidate = null;
            try
            {
                candidate = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
                candidate.NoDelay = true;
                candidate.ReceiveTimeout = timeoutMs;
                candidate.SendTimeout = timeoutMs;

                IPAddress address;
                IAsyncResult ar = IPAddress.TryParse(host, out address)
                    ? candidate.BeginConnect(address, port, null, null)
                    : candidate.BeginConnect(host, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                {
                    try { candidate.Close(); } catch { }
                    error = L.T("اتصال TCP برقرار نشد (timeout)", "the TCP connection timed out");
                    return false;
                }
                candidate.EndConnect(ar);
                socket = candidate;
                return true;
            }
            catch (Exception ex)
            {
                if (candidate != null) { try { candidate.Close(); } catch { } }
                error = ex.Message;
                return false;
            }
        }

        /// <summary>Opens the tunnel: TCP, fake-TLS when the secret needs it, then the 64 byte obfuscated2 header.</summary>
        public bool Connect(string host, int port, MtprotoSecret secret, int dc, int timeoutMs, out string error)
        {
            error = "";
            _timeoutMs = Math.Max(700, timeoutMs);
            if (secret == null || !secret.Ok)
            {
                error = secret == null ? L.T("سکرت خالی است", "the secret is empty") : secret.Error;
                return false;
            }

            Socket socket;
            if (!ConnectSocket(host, port, _timeoutMs, out socket, out error)) return false;
            _socket = socket;
            SocketOpened = true;

            try
            {
                _tls = secret.Mode == MtprotoMode.FakeTls;
                if (_tls && !FakeTlsHello(secret, out error)) return false;
                SendObfuscated2(secret, dc);
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        // ------------------------------------------------------------------ fake TLS

        /// <summary>
        /// Sends a ClientHello whose Random field is HMAC(secret, whole message with Random zeroed),
        /// with the current unix time xor-ed into the last four bytes - that is how Telegram keeps
        /// fake TLS private. The fronting domain goes into the SNI extension.
        /// </summary>
        private bool FakeTlsHello(MtprotoSecret secret, out string error)
        {
            error = "";
            byte[] random = RandomBytes(32);
            byte[] sessionId = RandomBytes(32);
            byte[] keyShare = RandomBytes(32);

            string domain = secret.Domain.Length > 0 ? secret.Domain : "www.microsoft.com";
            byte[] domainBytes = System.Text.Encoding.ASCII.GetBytes(domain);

            var body = new List<byte>();
            body.Add(0x03); body.Add(0x03);                  // client_version: TLS 1.2
            body.AddRange(random);                           // Random: becomes the digest in place
            body.Add((byte)sessionId.Length);
            body.AddRange(sessionId);
            body.AddRange(new byte[] { 0x00, 0x06, 0x0a, 0x0a, 0x13, 0x01, 0x13, 0x02 });  // cipher suites: grease + two real ones
            body.AddRange(new byte[] { 0x01, 0x00 });        // one compression method: null

            var extensions = new List<byte>();
            var names = new List<byte>();
            names.Add(0x00);                                 // host_name
            names.Add((byte)(domainBytes.Length >> 8));
            names.Add((byte)(domainBytes.Length & 0xff));
            names.AddRange(domainBytes);
            var sni = new List<byte> { 0x00, 0x00 };         // server_name list type + length set below
            sni[0] = (byte)(names.Count >> 8); sni[1] = (byte)(names.Count & 0xff);
            AddExtension(extensions, 0x0000, sni);
            AddExtension(extensions, 0x002b, new List<byte> { 0x03, 0x04 });                        // supported_versions
            var ks = new List<byte> { 0x00, 0x1d, 0x00, 0x20 };                                      // x25519 key share
            ks.AddRange(keyShare);
            AddExtension(extensions, 0x0033, ks);
            AddExtension(extensions, 0x000d, new List<byte> { 0x00, 0x04, 0x04, 0x03, 0x08, 0x04 });  // signature algorithms

            // real ClientHellos are 512+ bytes; proxies refuse anything smaller
            int targetBody = 513;                            // -> record length 517
            int need = targetBody - (body.Count + 2 + extensions.Count);
            if (need < 4) need = 4;
            var padding = new List<byte>();
            for (int i = 0; i < need - 4; i++) padding.Add(0x00);
            AddExtension(extensions, 0x0015, padding);       // padding extension
            body.Add((byte)(extensions.Count >> 8)); body.Add((byte)(extensions.Count & 0xff));
            body.AddRange(extensions);

            var record = new List<byte>();
            int bodyLen = body.Count + 4;
            record.Add(0x16);                                // handshake record
            record.Add(0x03); record.Add(0x01);
            record.Add((byte)(bodyLen >> 8)); record.Add((byte)(bodyLen & 0xff));
            record.Add(0x01);                                // client_hello
            record.Add((byte)(body.Count >> 16)); record.Add((byte)((body.Count >> 8) & 0xff)); record.Add((byte)(body.Count & 0xff));
            record.AddRange(body);

            byte[] hello = record.ToArray();
            byte[] digest = ClientHelloDigest(hello, secret.Key);
            Buffer.BlockCopy(digest, 0, hello, 11, 32);
            Send(hello);

            // the proxy answers with ServerHello + ChangeCipherSpec + a chunk of random "certificate";
            // the HMAC covers all of it at once, so they have to be collected before checking
            var blob = new List<byte>();
            int records = 0;
            while (records < 8)
            {
                byte[] header;
                if (!ReadExactRaw(5, out header))
                {
                    error = L.T("پروکسی جواب ClientHello را نداد (سکرت/دامنه اشتباه؟)",
                                "the proxy never answered the ClientHello (wrong secret or domain?)");
                    return false;
                }
                int len = (header[3] << 8) | header[4];
                if (len <= 0 || len > 16384)
                {
                    error = L.T("طول رکورد TLS نامعتبر است", "the TLS record length is invalid");
                    return false;
                }
                byte[] payload;
                if (!ReadExactRaw(len, out payload))
                {
                    error = L.T("رکورد TLS ناقص رسید", "the TLS record arrived incomplete");
                    return false;
                }
                records++;
                HelloAnswered = true;
                blob.AddRange(header);
                blob.AddRange(payload);
                if (header[0] == 0x17) break;                // application data = the fake certificate: done
                if (header[0] != 0x16 && header[0] != 0x14)
                {
                    error = L.T("رکورد ناشناس رسید (سکرت اشتباه؟)", "an unknown record arrived (wrong secret?)");
                    return false;
                }
            }

            if (blob.Count < 43 || blob[0] != 0x16)
            {
                error = L.T("پاسخ پروکسی ServerHello نبود", "the proxy's answer was not a ServerHello");
                return false;
            }
            ServerDigestOk = CheckServerDigest(blob.ToArray(), secret.Key, digest);
            if (!ServerDigestOk)
                error = L.T("هندشیک تی‌ال‌اس با سکرت ما هم‌خوان نبود (سکرت غلط)",
                            "the TLS handshake did not match our secret (wrong secret)");
            return ServerDigestOk;
        }

        /// <summary>HMAC-SHA256 over the ClientHello with the Random zeroed, plus the unix time in the tail.</summary>
        private static byte[] ClientHelloDigest(byte[] hello, byte[] key)
        {
            var copy = new byte[hello.Length];
            Buffer.BlockCopy(hello, 0, copy, 0, hello.Length);
            for (int i = 0; i < 32; i++) copy[11 + i] = 0;

            byte[] digest;
            using (var hmac = new HMACSHA256(key)) digest = hmac.ComputeHash(copy);

            long now = (long)(DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
            byte[] stamp = BitConverter.GetBytes((uint)now);
            if (!BitConverter.IsLittleEndian) Array.Reverse(stamp);
            for (int i = 0; i < 4; i++) digest[28 + i] = (byte)(digest[28 + i] ^ stamp[i]);
            return digest;
        }

        /// <summary>The answer must be HMAC(secret, clientRandom + answer with the Random zeroed).</summary>
        private static bool CheckServerDigest(byte[] blob, byte[] key, byte[] clientRandom)
        {
            if (blob.Length < 43) return false;
            var copy = new byte[32 + blob.Length];
            Buffer.BlockCopy(clientRandom, 0, copy, 0, 32);
            Buffer.BlockCopy(blob, 0, copy, 32, blob.Length);
            for (int i = 0; i < 32; i++) copy[32 + 11 + i] = 0;

            byte[] digest;
            using (var hmac = new HMACSHA256(key)) digest = hmac.ComputeHash(copy);

            for (int i = 0; i < 32; i++)
                if (digest[i] != blob[11 + i]) return false;
            return true;
        }

        private static void AddExtension(List<byte> extensions, int type, List<byte> data)
        {
            extensions.Add((byte)(type >> 8)); extensions.Add((byte)(type & 0xff));
            extensions.Add((byte)(data.Count >> 8)); extensions.Add((byte)(data.Count & 0xff));
            extensions.AddRange(data);
        }

        // ------------------------------------------------------------------ obfuscated2

        /// <summary>The 64 byte header: AES keys, the transport tag and the DC number, all encrypted in place.</summary>
        private void SendObfuscated2(MtprotoSecret secret, int dc)
        {
            var frame = new byte[64];
            while (true)
            {
                RandomBytes(frame);
                uint head = BitConverter.ToUInt32(frame, 0);
                if (frame[0] == 0xef) continue;
                if (head == 0x44414548 || head == 0x54534f50 || head == 0x20544547) continue;   // HEAD, POST, "GET "
                if (head == 0xeeeeeeee || head == 0xdddddddd) continue;
                if (frame[0] == 0x16 && frame[1] == 0x03 && frame[2] == 0x01) continue;
                if (BitConverter.ToUInt32(frame, 4) == 0) continue;
                break;
            }

            bool classic = secret.Mode == MtprotoMode.Classic;
            frame[56] = classic ? (byte)0xee : (byte)0xdd;
            frame[57] = classic ? (byte)0xee : (byte)0xdd;
            frame[58] = classic ? (byte)0xee : (byte)0xdd;
            frame[59] = classic ? (byte)0xee : (byte)0xdd;

            short dcValue = (short)(dc <= 0 ? 2 : dc);
            frame[60] = (byte)(dcValue & 0xff);
            frame[61] = (byte)((dcValue >> 8) & 0xff);

            var prefix = new byte[48];
            Buffer.BlockCopy(frame, 8, prefix, 0, 48);

            var encKey = new byte[32];
            Buffer.BlockCopy(prefix, 0, encKey, 0, 32);
            var encIv = new byte[16];
            Buffer.BlockCopy(prefix, 32, encIv, 0, 16);
            _enc = new AesCtr(Sha256With(encKey, secret.Key), encIv);

            var reversed = new byte[48];
            for (int i = 0; i < 48; i++) reversed[i] = prefix[47 - i];
            var decKey = new byte[32];
            Buffer.BlockCopy(reversed, 0, decKey, 0, 32);
            var decIv = new byte[16];
            Buffer.BlockCopy(reversed, 32, decIv, 0, 16);
            _dec = new AesCtr(Sha256With(decKey, secret.Key), decIv);

            _enc.Xor(frame, 0, frame.Length);
            // the key and iv travel in the clear (they are what the server derives its ciphers
            // from), so they have to be put back after the encryption pass
            Buffer.BlockCopy(prefix, 0, frame, 8, 48);
            SendFrameBytes(frame);
        }

        private static byte[] Sha256With(byte[] prefix, byte[] key)
        {
            using (var sha = SHA256.Create())
            {
                var buffer = new byte[prefix.Length + key.Length];
                Buffer.BlockCopy(prefix, 0, buffer, 0, prefix.Length);
                Buffer.BlockCopy(key, 0, buffer, prefix.Length, key.Length);
                return sha.ComputeHash(buffer);
            }
        }

        // ------------------------------------------------------------------ framing

        /// <summary>Sends a payload as one (padded) intermediate frame.</summary>
        public void SendFrame(byte[] payload)
        {
            int padding = (4 - (payload.Length % 4)) % 4;
            int length = payload.Length + padding;
            var frame = new byte[FrameHeader + length];
            frame[0] = (byte)(length & 0xff);
            frame[1] = (byte)((length >> 8) & 0xff);
            frame[2] = (byte)((length >> 16) & 0xff);
            frame[3] = (byte)((length >> 24) & 0xff);
            Buffer.BlockCopy(payload, 0, frame, FrameHeader, payload.Length);
            if (padding > 0) Buffer.BlockCopy(RandomBytes(padding), 0, frame, FrameHeader + payload.Length, padding);
            _enc.Xor(frame, 0, frame.Length);
            SendFrameBytes(frame);
        }

        /// <summary>Reads one frame back, or null when the proxy says nothing.</summary>
        public byte[] ReadFrame()
        {
            byte[] header;
            if (!ReadPlain(FrameHeader, out header)) return null;
            _dec.Xor(header, 0, header.Length);      // the length prefix is inside the encrypted stream
            int length = header[0] | (header[1] << 8) | (header[2] << 16) | (header[3] << 24);
            if (length <= 0 || length > MaxFrame) return null;
            byte[] body;
            if (!ReadPlain(length, out body)) return null;
            _dec.Xor(body, 0, body.Length);
            return body;
        }

        private void SendFrameBytes(byte[] data)
        {
            if (_tls)
            {
                for (int offset = 0; offset < data.Length; offset += MaxRecordPayload)
                {
                    int take = Math.Min(MaxRecordPayload, data.Length - offset);
                    var record = new byte[5 + take];
                    record[0] = 0x17; record[1] = 0x03; record[2] = 0x03;
                    record[3] = (byte)(take >> 8); record[4] = (byte)(take & 0xff);
                    Buffer.BlockCopy(data, offset, record, 5, take);
                    Send(record);
                }
            }
            else
            {
                Send(data);
            }
        }

        private void Send(byte[] data)
        {
            int sent = 0;
            while (sent < data.Length)
                sent += _socket.Send(data, sent, data.Length - sent, SocketFlags.None);
        }

        // ------------------------------------------------------------------ reading

        private long _deadlineTicks;

        /// <summary>Reads plaintext (after TLS unwrapping) with a rolling deadline.</summary>
        private bool ReadPlain(int count, out byte[] data)
        {
            if (_deadlineTicks == 0)
                _deadlineTicks = DateTime.UtcNow.Ticks + TimeSpan.TicksPerMillisecond * _timeoutMs;
            return ReadFrom(count, _tls, out data);
        }

        /// <summary>Reads raw bytes from the wire (used during the TLS handshake).</summary>
        private bool ReadExactRaw(int count, out byte[] data)
        {
            if (_deadlineTicks == 0)
                _deadlineTicks = DateTime.UtcNow.Ticks + TimeSpan.TicksPerMillisecond * _timeoutMs;
            return ReadFrom(count, false, out data);
        }

        private bool ReadFrom(int count, bool unwrapTls, out byte[] data)
        {
            data = new byte[count];
            int filled = 0;
            while (filled < count)
            {
                if (unwrapTls && _plainFrom == _plainTo) { _plainFrom = 0; _plainTo = 0; }
                if (!unwrapTls)
                {
                    int have = _rawTo - _rawFrom;
                    if (have > 0)
                    {
                        int take = Math.Min(have, count - filled);
                        Buffer.BlockCopy(_raw, _rawFrom, data, filled, take);
                        _rawFrom += take;
                        filled += take;
                        continue;
                    }
                }
                else
                {
                    int have = _plainTo - _plainFrom;
                    if (have > 0)
                    {
                        int take = Math.Min(have, count - filled);
                        Buffer.BlockCopy(_plain, _plainFrom, data, filled, take);
                        _plainFrom += take;
                        filled += take;
                        continue;
                    }
                }

                if (DateTime.UtcNow.Ticks > _deadlineTicks) return false;
                if (!Fill(unwrapTls)) return false;
            }
            return true;
        }

        /// <summary>One socket read; when unwrapping, records are split into plaintext.</summary>
        private bool Fill(bool unwrapTls)
        {
            Compact();
            int read;
            try
            {
                _socket.ReceiveTimeout = _timeoutMs;
                read = _socket.Receive(_raw, _rawTo, _raw.Length - _rawTo, SocketFlags.None);
            }
            catch (SocketException ex)
            {
                if (ex.SocketErrorCode == SocketError.TimedOut || ex.SocketErrorCode == SocketError.WouldBlock) return false;
                throw;
            }
            if (read <= 0) return false;
            _rawTo += read;
            if (unwrapTls) UnwrapRecords();
            return true;
        }

        private void Compact()
        {
            if (_rawFrom == 0) return;
            if (_rawFrom == _rawTo) { _rawFrom = _rawTo = 0; return; }
            Buffer.BlockCopy(_raw, _rawFrom, _raw, 0, _rawTo - _rawFrom);
            _rawTo -= _rawFrom;
            _rawFrom = 0;
        }

        private void CompactPlain()
        {
            if (_plainFrom == 0) return;
            if (_plainFrom == _plainTo) { _plainFrom = _plainTo = 0; return; }
            Buffer.BlockCopy(_plain, _plainFrom, _plain, 0, _plainTo - _plainFrom);
            _plainTo -= _plainFrom;
            _plainFrom = 0;
        }

        /// <summary>Turns the raw TLS records into a plain byte stream (CCS and handshake records are dropped).</summary>
        private void UnwrapRecords()
        {
            while (_rawTo - _rawFrom >= 5)
            {
                byte type = _raw[_rawFrom];
                int len = (_raw[_rawFrom + 3] << 8) | _raw[_rawFrom + 4];
                if (len <= 0 || len > 16384 + 24) return;              // nonsense: wait for more, or give up
                if (_rawTo - _rawFrom < 5 + len) return;               // the record is still on its way
                if (type == 0x17)
                {
                    if (_plainTo + len > _plain.Length) return;        // no room: let the caller drain first
                    Buffer.BlockCopy(_raw, _rawFrom + 5, _plain, _plainTo, len);
                    _plainTo += len;
                }
                _rawFrom += 5 + len;
            }
            Compact();
        }

        // ------------------------------------------------------------------ telegram handshake

        /// <summary>
        /// Sends <c>req_pq_multi</c> and waits for <c>resPQ</c>. This is the real proof that the
        /// proxy forwards to Telegram and that the secret is right.
        /// </summary>
        public bool Verify(int timeoutMs, out int rttMs, out bool nonceEchoed, out string detail)
        {
            rttMs = -1;
            nonceEchoed = false;
            detail = "";
            _timeoutMs = Math.Max(700, timeoutMs);
            _deadlineTicks = 0;
            CompactPlain();

            byte[] nonce = RandomBytes(16);
            var tl = new byte[20];
            tl[0] = (byte)(CtorReqPqMulti & 0xff); tl[1] = 0x8e; tl[2] = 0x7e; tl[3] = 0xbe;
            Buffer.BlockCopy(nonce, 0, tl, 4, 16);

            var message = new byte[20 + tl.Length];                    // auth_key_id(8, zero) + msg_id(8) + len(4) + data
            Buffer.BlockCopy(MessageId(), 0, message, 8, 8);
            message[16] = (byte)tl.Length;
            Buffer.BlockCopy(tl, 0, message, 20, tl.Length);

            long start = DateTime.UtcNow.Ticks;
            try
            {
                SendFrame(message);
            }
            catch (Exception ex)
            {
                detail = L.T("ارسال به پروکسی ناموفق بود: ", "sending to the proxy failed: ") + ex.Message;
                return false;
            }

            _deadlineTicks = DateTime.UtcNow.Ticks + TimeSpan.TicksPerMillisecond * Math.Max(1200, timeoutMs);
            byte[] reply = ReadFrame();
            if (reply == null)
            {
                detail = L.T("پروکسی به req_pq جواب نداد (سکرت اشتباه یا پروکسی خراب)",
                             "the proxy did not answer req_pq (wrong secret or the proxy is broken)");
                return false;
            }
            rttMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);

            nonceEchoed = FindNonce(reply, nonce) >= 0;
            if (reply.Length >= 24)
            {
                uint ctor = BitConverter.ToUInt32(reply, 20);
                if (ctor == CtorResPQ && reply.Length >= 40)
                {
                    bool same = true;
                    for (int i = 0; i < 16; i++)
                        if (reply[24 + i] != nonce[i]) { same = false; break; }
                    if (same)
                    {
                        detail = L.T("resPQ واقعی از دیتاسنتر تلگرام رسید", "a real resPQ came back from a Telegram DC");
                        return true;
                    }
                    detail = L.T("resPQ رسید ولی nonce ما را برنگرداند", "a resPQ arrived but it did not echo our nonce");
                    return false;
                }
                if (ctor == CtorMsgContainer)
                {
                    detail = L.T("جواب در msg_container بود و nonce اکو شد", "the answer came inside a msg_container and the nonce matched");
                    return nonceEchoed;
                }
                detail = L.T("جواب تلگرام نبود (constructor ناشناس)", "the answer was not Telegram (unknown constructor)");
                return false;
            }

            detail = nonceEchoed
                ? L.T("nonce برگشت ولی قالب پیام غیرعادی بود", "the nonce came back but the framing was unusual")
                : L.T("جواب پروکسی شبیه پیام تلگرام نبود", "the proxy's answer did not look like a Telegram message");
            return false;
        }

        private static int FindNonce(byte[] data, byte[] nonce)
        {
            for (int i = 0; i + nonce.Length <= data.Length; i++)
            {
                bool hit = true;
                for (int j = 0; j < nonce.Length; j++)
                    if (data[i + j] != nonce[j]) { hit = false; break; }
                if (hit) return i;
            }
            return -1;
        }

        /// <summary>MTProto message id: seconds in the high half, nanoseconds in the low half, low two bits cleared.</summary>
        private static byte[] MessageId()
        {
            long ticks = DateTime.UtcNow.Ticks;
            ulong seconds = (ulong)(ticks / TimeSpan.TicksPerSecond);
            ulong sub = (ulong)((ticks % TimeSpan.TicksPerSecond) * 4294967296L / TimeSpan.TicksPerSecond);
            ulong id = (seconds << 32) | (sub & 0xffffffffUL);
            id &= 0xfffffffffffffffcUL;
            byte[] bytes = BitConverter.GetBytes(id);
            if (!BitConverter.IsLittleEndian) Array.Reverse(bytes);
            return bytes;
        }

        public void Dispose()
        {
            try { if (_socket != null) _socket.Close(); } catch { }
            _socket = null;
            if (_enc != null) { _enc.Dispose(); _enc = null; }
            if (_dec != null) { _dec.Dispose(); _dec = null; }
        }

        // ------------------------------------------------------------------ high level

        /// <summary>Connect, handshake, then req_pq -> resPQ. Never throws, always explains itself.</summary>
        public static MtprotoCheck Check(string host, int port, string secretText, int dc, int timeoutMs)
        {
            var check = new MtprotoCheck { Dc = dc <= 0 ? 2 : dc };
            MtprotoSecret secret = MtprotoSecret.Parse(secretText);
            check.Mode = secret.Mode;
            check.Domain = secret.Domain;
            if (!secret.Ok)
            {
                check.Status = L.T("سکرت نامعتبر", "invalid secret");
                check.Detail = L.T("سکرت خوانده نشد: ", "the secret cannot be read: ") + secret.Error;
                return check;
            }

            long start = DateTime.UtcNow.Ticks;
            using (var client = new MtprotoClient())
            {
                string error;
                if (!client.Connect(host, port, secret, dc, timeoutMs, out error))
                {
                    check.ConnectMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                    check.Connected = client.SocketOpened;
                    check.HelloAnswered = client.HelloAnswered;
                    check.ServerDigestOk = client.ServerDigestOk;
                    check.Status = check.Connected
                        ? L.T("هندشیک ناتمام", "handshake incomplete")
                        : L.T("وصل نشد", "unreachable");
                    check.Detail = error;
                    return check;
                }

                check.Connected = true;
                check.ConnectMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                check.HelloAnswered = client.HelloAnswered;
                check.ServerDigestOk = client.ServerDigestOk;

                int rtt;
                bool nonce;
                string detail;
                bool ok = client.Verify(Math.Max(1200, timeoutMs), out rtt, out nonce, out detail);
                check.HandshakeMs = (int)Math.Max(1, (DateTime.UtcNow.Ticks - start) / TimeSpan.TicksPerMillisecond);
                check.RttMs = rtt;
                check.Verified = ok;
                check.NonceEchoed = nonce;
                check.Detail = detail;

                if (ok) check.Status = L.T("تأیید شد (resPQ)", "verified (resPQ)");
                else if (nonce) check.Status = L.T("نیمه‌کاره", "partial");
                else if (client.TlsLayer && !client.ServerDigestOk) check.Status = L.T("سکرت قبول نشد", "secret rejected");
                else if (client.TlsLayer) check.Status = L.T("هندشیک سالم، جواب تلگرام نه", "handshake ok, no Telegram reply");
                else check.Status = L.T("جوابی از تلگرام نیامد", "no reply from Telegram");
                return check;
            }
        }

        /// <summary>The delay to one Telegram data centre through this proxy, or -1.</summary>
        public static int PingDc(string host, int port, string secretText, int dc, int timeoutMs)
        {
            return Check(host, port, secretText, dc, timeoutMs).DelayMs;
        }

        /// <summary>Telegram's five data centres, for the latency table.</summary>
        public static readonly int[] DataCenters = { 1, 2, 3, 4, 5 };
    }
}

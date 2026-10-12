using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>How an MTProto (Telegram) proxy expects the client to start the conversation.</summary>
    public enum MtprotoMode
    {
        /// <summary>Plain obfuscated2 with the abridged/intermediate tag - the oldest form, easy to spot for DPI.</summary>
        Classic = 0,
        /// <summary>obfuscated2 with the <c>dd</c> (padded intermediate) tag - no fake TLS layer.</summary>
        Secured = 1,
        /// <summary>obfuscated2 wrapped in a fake TLS session (<c>ee</c> secret with a fronting domain).</summary>
        FakeTls = 2
    }

    /// <summary>
    /// One MTProto proxy secret, decoded. Telegram hands secrets out in several shapes:
    /// <c>tg://proxy?secret=dd…</c>, <c>https://t.me/proxy?secret=ee…</c>, a bare 32 hex
    /// character string, or the same bytes base64 encoded. All of them end up here as a
    /// 16 byte key plus, for fake TLS, the domain that has to go into the ClientHello SNI.
    /// </summary>
    public sealed class MtprotoSecret
    {
        public MtprotoMode Mode = MtprotoMode.FakeTls;
        public byte[] Key = new byte[0];      // the 16 raw bytes, never the "ee"/"dd" prefix
        public string Domain = "";
        public string Error = "";

        public bool Ok { get { return Error.Length == 0 && Key.Length == 16; } }

        /// <summary>Short name of a mode, for the UI and the log.</summary>
        public static string ModeName(MtprotoMode mode)
        {
            switch (mode)
            {
                case MtprotoMode.FakeTls: return "fake-TLS";
                case MtprotoMode.Secured: return "secured (dd)";
                default: return "classic obfuscated2";
            }
        }

        public string ModeTitle { get { return ModeName(Mode); } }

        /// <summary>One line for the UI and the log.</summary>
        public string Describe()
        {
            if (!Ok) return L.T("سکرت خوانده نشد: ", "cannot read the secret: ") + Error;
            string text = ModeTitle;
            if (Mode == MtprotoMode.FakeTls)
                text += Domain.Length > 0
                    ? " • " + L.T("دامنه: ", "domain: ") + Domain
                    : " • " + L.T("بدون دامنه (SNI خالی)", "no domain (empty SNI)");
            text += " • " + L.T("کلید ", "key ") + Hex(Key);
            return text;
        }

        /// <summary>Re-builds a link Telegram itself understands from the stored parts.</summary>
        public string ToLink(string host, int port)
        {
            if (!Ok || string.IsNullOrEmpty(host) || port <= 0) return "";
            string secret;
            switch (Mode)
            {
                case MtprotoMode.FakeTls:
                    secret = "ee" + Hex(Key) + Domain;
                    break;
                case MtprotoMode.Secured:
                    secret = "dd" + Hex(Key);
                    break;
                default:
                    secret = Hex(Key);
                    break;
            }
            return "tg://proxy?server=" + Uri.EscapeDataString(host) + "&port=" +
                   port.ToString(CultureInfo.InvariantCulture) + "&secret=" + Uri.EscapeDataString(secret);
        }

        public static string Hex(byte[] bytes)
        {
            var sb = new StringBuilder(bytes.Length * 2);
            for (int i = 0; i < bytes.Length; i++) sb.Append(bytes[i].ToString("x2", CultureInfo.InvariantCulture));
            return sb.ToString();
        }

        /// <summary>Pull the secret out of a link, or take it as a bare secret.</summary>
        public static string ExtractSecretText(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            text = text.Trim();
            int question = text.IndexOf('?');
            if (question >= 0 && (text.StartsWith("tg://", StringComparison.OrdinalIgnoreCase) ||
                                  text.IndexOf("/proxy", StringComparison.OrdinalIgnoreCase) > 0 ||
                                  text.StartsWith("mtproto://", StringComparison.OrdinalIgnoreCase)))
            {
                string query = text.Substring(question + 1);
                foreach (string part in query.Split('&'))
                {
                    int eq = part.IndexOf('=');
                    if (eq <= 0) continue;
                    string name = part.Substring(0, eq).Trim().ToLowerInvariant();
                    if (name == "secret")
                        return Unescape(part.Substring(eq + 1).Trim());
                }
            }
            if (text.StartsWith("mtproto://", StringComparison.OrdinalIgnoreCase))
                text = text.Substring("mtproto://".Length).Trim();
            return Unescape(text.Trim());
        }

        private static string Unescape(string value)
        {
            if (value.IndexOf('%') < 0) return value;
            try { return Uri.UnescapeDataString(value); }
            catch { return value; }
        }

        public static MtprotoSecret Parse(string text)
        {
            var result = new MtprotoSecret();
            string secret = ExtractSecretText(text);
            if (secret.Length == 0)
            {
                result.Error = L.T("خالی است", "it is empty");
                return result;
            }

            // shape 1: prefix + 32 hex characters, optionally followed by the fronting domain
            if (secret.Length > 32)
            {
                string head = secret.Substring(0, 2).ToLowerInvariant();
                if ((head == "dd" || head == "ee") && IsHex(secret.Substring(2, 32)))
                {
                    result.Key = FromHex(secret.Substring(2, 32));
                    if (head == "dd")
                    {
                        result.Mode = MtprotoMode.Secured;
                        result.Domain = "";   // dd secrets never carry a domain
                        return result;
                    }
                    result.Mode = MtprotoMode.FakeTls;
                    result.Domain = DecodeDomain(secret.Substring(34));
                    if (result.Domain.Length == 0)
                        result.Error = L.T("دامنه در سکرت تی‌ال‌اس خالی است", "the fake-TLS secret has no domain");
                    return result;
                }
            }

            // shape 2: raw bytes (the usual 32 hex characters, or the base64 form)
            byte[] bytes = FromHexOrBase64(secret);
            if (bytes == null || bytes.Length == 0)
            {
                result.Error = L.T("نه هگز است و نه base64", "it is neither hex nor base64");
                return result;
            }

            if (bytes.Length >= 17 && bytes[0] == 0xee)
            {
                result.Mode = MtprotoMode.FakeTls;
                result.Key = Slice(bytes, 1, 16);
                result.Domain = DecodeDomain(Encoding.UTF8.GetString(bytes, 17, bytes.Length - 17));
                if (result.Domain.Length == 0)
                    result.Error = L.T("دامنه در سکرت تی‌ال‌اس خالی است", "the fake-TLS secret has no domain");
                return result;
            }
            if (bytes.Length >= 17 && bytes[0] == 0xdd)
            {
                result.Mode = MtprotoMode.Secured;
                result.Key = Slice(bytes, 1, 16);
                return result;
            }

            result.Mode = MtprotoMode.Classic;
            if (bytes.Length == 16)
            {
                result.Key = bytes;
                return result;
            }
            if (bytes.Length == 17 && bytes[0] == 0x00)   // some generators pad the secret
            {
                result.Key = Slice(bytes, 1, 16);
                return result;
            }
            result.Error = L.T("طول سکرت ", "the secret is ") + bytes.Length +
                           L.T(" بایت است، باید ۱۶ باشد", " bytes, it has to be 16");
            return result;
        }

        /// <summary>Turns whatever follows the key into a domain: plain text, or hex when the bytes are not printable.</summary>
        private static string DecodeDomain(string tail)
        {
            if (string.IsNullOrEmpty(tail)) return "";
            tail = tail.Trim().Trim('\0');
            if (tail.Length == 0) return "";

            bool printable = true;
            for (int i = 0; i < tail.Length; i++)
            {
                char c = tail[i];
                if (c < 0x20 || c > 0x7e) { printable = false; break; }
            }
            if (printable) return tail.Trim().TrimEnd('/');

            // not printable: the domain was appended as hex characters
            if (IsHex(tail)) return FromHexAscii(tail);
            return "";
        }

        private static string FromHexAscii(string hex)
        {
            var sb = new StringBuilder(hex.Length / 2);
            for (int i = 0; i + 1 < hex.Length; i += 2)
                sb.Append((char)int.Parse(hex.Substring(i, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
            return sb.ToString().Trim().Trim('\0');
        }

        private static byte[] FromHexOrBase64(string text)
        {
            string clean = text.Replace(" ", "").Replace("-", "").Replace("\r", "").Replace("\n", "");
            if (IsHex(clean)) return FromHex(clean);
            // base64, standard or url-safe
            string normal = clean.Replace('-', '+').Replace('_', '/');
            while (normal.Length % 4 != 0) normal += "=";
            try { return Convert.FromBase64String(normal); }
            catch { return null; }
        }

        public static bool IsHex(string text)
        {
            if (string.IsNullOrEmpty(text) || text.Length % 2 != 0) return false;
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                bool hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
                if (!hex) return false;
            }
            return true;
        }

        public static byte[] FromHex(string hex)
        {
            var bytes = new byte[hex.Length / 2];
            for (int i = 0; i < bytes.Length; i++)
                bytes[i] = byte.Parse(hex.Substring(i * 2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            return bytes;
        }

        private static byte[] Slice(byte[] source, int offset, int count)
        {
            var slice = new byte[count];
            Buffer.BlockCopy(source, offset, slice, 0, count);
            return slice;
        }

        /// <summary>All secrets found in a blob of text - used by the bulk import preview.</summary>
        public static List<string> SplitSecrets(string text)
        {
            var found = new List<string>();
            if (string.IsNullOrEmpty(text)) return found;
            foreach (string line in text.Split('\n'))
            {
                string trimmed = line.Trim();
                if (trimmed.Length == 0) continue;
                string secret = ExtractSecretText(trimmed);
                if (secret.Length >= 32) found.Add(trimmed);
            }
            return found;
        }
    }
}

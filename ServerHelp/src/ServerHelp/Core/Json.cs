using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace ServerHelp.Core
{
    /// <summary>
    /// Minimal JSON reader/writer. Deliberately dependency free: the app ships as a single exe
    /// with no NuGet runtime dependencies, and .NET Frameworks's own serialisers are awkward.
    /// Parsed values are: Dictionary&lt;string,object&gt;, List&lt;object&gt;, string, double, bool, null.
    /// </summary>
    public static class Json
    {
        // ---------------------------------------------------------------- reading

        public static object Parse(string text)
        {
            if (text == null) return null;
            int i = 0;
            SkipWs(text, ref i);
            object v = ParseValue(text, ref i);
            return v;
        }

        public static Dictionary<string, object> ParseObject(string text)
        {
            var d = Parse(text) as Dictionary<string, object>;
            if (d == null) throw new FormatException("JSON root is not an object");
            return d;
        }

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length)
            {
                char c = s[i];
                if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { i++; continue; }
                break;
            }
        }

        private static object ParseValue(string s, ref int i)
        {
            SkipWs(s, ref i);
            if (i >= s.Length) throw new FormatException("Unexpected end of JSON");
            char c = s[i];
            if (c == '{') return ParseObj(s, ref i);
            if (c == '[') return ParseArr(s, ref i);
            if (c == '"') return ParseString(s, ref i);
            if (c == 't') { Expect(s, ref i, "true"); return true; }
            if (c == 'f') { Expect(s, ref i, "false"); return false; }
            if (c == 'n') { Expect(s, ref i, "null"); return null; }
            return ParseNumber(s, ref i);
        }

        private static void Expect(string s, ref int i, string word)
        {
            if (i + word.Length > s.Length || string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
                throw new FormatException("Invalid JSON literal at " + i);
            i += word.Length;
        }

        private static Dictionary<string, object> ParseObj(string s, ref int i)
        {
            var d = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            i++; // {
            while (true)
            {
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("Unterminated object");
                if (s[i] == '}') { i++; return d; }
                if (s[i] == ',') { i++; continue; }
                string key = ParseString(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("Expected ':' after key " + key);
                i++;
                d[key] = ParseValue(s, ref i);
            }
        }

        private static List<object> ParseArr(string s, ref int i)
        {
            var list = new List<object>();
            i++; // [
            while (true)
            {
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("Unterminated array");
                if (s[i] == ']') { i++; return list; }
                if (s[i] == ',') { i++; continue; }
                list.Add(ParseValue(s, ref i));
            }
        }

        private static string ParseString(string s, ref int i)
        {
            SkipWs(s, ref i);
            if (i >= s.Length || s[i] != '"') throw new FormatException("Expected string at " + i);
            i++;
            var sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                if (i >= s.Length) break;
                char e = s[i++];
                switch (e)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 <= s.Length)
                        {
                            int code = int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                            sb.Append((char)code);
                            i += 4;
                        }
                        break;
                    default: sb.Append(e); break;
                }
            }
            throw new FormatException("Unterminated string");
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length)
            {
                char c = s[i];
                if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') i++;
                else break;
            }
            string num = s.Substring(start, i - start);
            double d;
            if (double.TryParse(num, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) return d;
            throw new FormatException("Invalid number '" + num + "'");
        }

        // ------------------------------------------------------------- accessors

        public static Dictionary<string, object> Obj(object o)
        {
            return o as Dictionary<string, object>;
        }

        public static List<object> Arr(object o)
        {
            return o as List<object>;
        }

        public static object Get(Dictionary<string, object> d, string key)
        {
            if (d == null) return null;
            object v;
            return d.TryGetValue(key, out v) ? v : null;
        }

        public static string GetStr(Dictionary<string, object> d, string key, string def)
        {
            object v = Get(d, key);
            if (v == null) return def;
            if (v is string) return (string)v;
            if (v is bool) return ((bool)v) ? "true" : "false";
            if (v is double) return ((double)v).ToString(CultureInfo.InvariantCulture);
            if (v is int) return ((int)v).ToString(CultureInfo.InvariantCulture);
            if (v is long) return ((long)v).ToString(CultureInfo.InvariantCulture);
            return def;
        }

        public static int GetInt(Dictionary<string, object> d, string key, int def)
        {
            object v = Get(d, key);
            if (v == null) return def;
            if (v is double) return (int)Math.Round((double)v);
            if (v is int) return (int)v;
            if (v is long) return (int)(long)v;
            int i;
            if (v is string && int.TryParse((string)v, out i)) return i;
            return def;
        }

        public static bool GetBool(Dictionary<string, object> d, string key, bool def)
        {
            object v = Get(d, key);
            if (v == null) return def;
            if (v is bool) return (bool)v;
            if (v is double) return ((double)v) != 0;
            if (v is string)
            {
                string s = ((string)v).Trim().ToLowerInvariant();
                if (s == "true" || s == "1" || s == "yes") return true;
                if (s == "false" || s == "0" || s == "no") return false;
            }
            return def;
        }

        public static string Str(object o, string def)
        {
            return (o is string) ? (string)o : def;
        }

        public static List<string> StrList(object o)
        {
            var result = new List<string>();
            var list = o as List<object>;
            if (list != null)
            {
                foreach (object item in list) if (item is string) result.Add((string)item);
            }
            else if (o is string) result.Add((string)o);
            return result;
        }

        // -------------------------------------------------------------- writing

        public static string Escape(string s)
        {
            if (s == null) return "null";
            var sb = new StringBuilder(s.Length + 8);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        public static string Num(double d)
        {
            return d.ToString("0.###", CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// Writes any value produced by <see cref="Parse"/> back out as JSON. Used to embed a
        /// pasted outbound or endpoint object inside a generated configuration.
        /// </summary>
        public static string Serialize(object value)
        {
            var sb = new StringBuilder();
            WriteValue(sb, value);
            return sb.ToString();
        }

        private static void WriteValue(StringBuilder sb, object value)
        {
            if (value == null) { sb.Append("null"); return; }
            if (value is string) { sb.Append(Escape((string)value)); return; }
            if (value is bool) { sb.Append(((bool)value) ? "true" : "false"); return; }
            if (value is double) { sb.Append(Num((double)value)); return; }
            if (value is float) { sb.Append(Num((float)value)); return; }
            if (value is int || value is long || value is short || value is byte)
            {
                sb.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
                return;
            }

            var map = value as Dictionary<string, object>;
            if (map != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (var pair in map)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    sb.Append(Escape(pair.Key)).Append(':');
                    WriteValue(sb, pair.Value);
                }
                sb.Append('}');
                return;
            }

            var list = value as System.Collections.IEnumerable;
            if (list != null)
            {
                sb.Append('[');
                bool first = true;
                foreach (object item in list)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteValue(sb, item);
                }
                sb.Append(']');
                return;
            }

            sb.Append(Escape(value.ToString()));
        }
    }

    /// <summary>Tiny indentation-aware JSON writer, so generated config files stay readable.</summary>
    public sealed class JsonWriter
    {
        private readonly StringBuilder _sb = new StringBuilder();
        private int _depth;
        private bool _needComma;
        private readonly bool _pretty;

        public JsonWriter(bool pretty)
        {
            _pretty = pretty;
        }

        private void Indent()
        {
            if (!_pretty) return;
            _sb.Append('\n');
            for (int i = 0; i < _depth; i++) _sb.Append("  ");
        }

        private void Pre()
        {
            if (_needComma) _sb.Append(',');
            _needComma = false;
        }

        public JsonWriter StartObject()
        {
            Pre();
            _sb.Append('{');
            _depth++;
            _needComma = false;
            return this;
        }

        public JsonWriter EndObject()
        {
            _depth--;
            if (_pretty) Indent();
            _sb.Append('}');
            _needComma = true;
            return this;
        }

        /// <summary>Writes a property name followed by a value the caller writes itself (array, object).</summary>
        public JsonWriter PropName(string name)
        {
            Pre();
            _sb.Append(Json.Escape(name)).Append(':');
            return this;
        }

        public JsonWriter StartArray()
        {
            Pre();
            _sb.Append('[');
            _depth++;
            _needComma = false;
            return this;
        }

        public JsonWriter EndArray()
        {
            _depth--;
            if (_pretty) Indent();
            _sb.Append(']');
            _needComma = true;
            return this;
        }

        public JsonWriter Name(string name)
        {
            Pre();
            if (_pretty) Indent();
            _sb.Append(Json.Escape(name)).Append(": ");
            _needComma = false;
            return this;
        }

        public JsonWriter Value(string s)
        {
            Pre();
            _sb.Append(Json.Escape(s));
            _needComma = true;
            return this;
        }

        public JsonWriter ValueRaw(string raw)
        {
            Pre();
            _sb.Append(raw);
            _needComma = true;
            return this;
        }

        public JsonWriter Value(bool b)
        {
            Pre();
            _sb.Append(b ? "true" : "false");
            _needComma = true;
            return this;
        }

        public JsonWriter Value(int i)
        {
            Pre();
            _sb.Append(i.ToString(CultureInfo.InvariantCulture));
            _needComma = true;
            return this;
        }

        public JsonWriter Prop(string name, string value) { return Name(name).Value(value); }
        public JsonWriter Prop(string name, bool value) { return Name(name).Value(value); }
        public JsonWriter Prop(string name, int value) { return Name(name).Value(value); }

        public override string ToString()
        {
            return _sb.ToString();
        }
    }
}

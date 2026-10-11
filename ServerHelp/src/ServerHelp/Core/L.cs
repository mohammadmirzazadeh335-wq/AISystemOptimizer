using System;

namespace ServerHelp.Core
{
    /// <summary>
    /// Two-language (Persian/English) text. Inline pairs keep the UI code readable and make it
    /// impossible to forget a translation.
    /// </summary>
    public static class L
    {
        public const string Fa = "fa";
        public const string En = "en";

        private static string _lang = Fa;

        public static string Lang { get { return _lang; } }

        public static bool IsRtl { get { return _lang == Fa; } }

        public static event Action Changed;

        public static void SetLang(string lang)
        {
            string next = (lang == En) ? En : Fa;
            if (next == _lang) return;
            _lang = next;
            Action h = Changed;
            if (h != null) h();
        }

        /// <summary>Persian when the UI language is Persian, English otherwise.</summary>
        public static string T(string fa, string en)
        {
            return _lang == En ? en : fa;
        }

        /// <summary>Persian digits when running in Persian, plain otherwise.</summary>
        public static string N(int value)
        {
            string s = value.ToString(System.Globalization.CultureInfo.InvariantCulture);
            if (_lang == En) return s;
            var sb = new System.Text.StringBuilder();
            foreach (char c in s)
            {
                if (c >= '0' && c <= '9') sb.Append((char)('۰' + (c - '0')));
                else sb.Append(c);
            }
            return sb.ToString();
        }

        public static string N(double value, int digits)
        {
            string s = value.ToString("0." + new string('#', digits), System.Globalization.CultureInfo.InvariantCulture);
            if (_lang == En) return s;
            var sb = new System.Text.StringBuilder();
            foreach (char c in s)
            {
                if (c >= '0' && c <= '9') sb.Append((char)('۰' + (c - '0')));
                else sb.Append(c);
            }
            return sb.ToString();
        }
    }
}

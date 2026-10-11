using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace ServerHelp.Core
{
    public enum LogLevel { Debug = 0, Info = 1, Warn = 2, Error = 3 }

    /// <summary>Thread safe logger: console-free app, so everything goes to a file plus the UI.</summary>
    public static class Log
    {
        private static readonly object Gate = new object();
        private static StreamWriter _writer;
        private static string _pending = "";

        public static LogLevel Level = LogLevel.Info;

        /// <summary>Raised for every line; the UI subscribes and marshals to the UI thread.</summary>
        public static event Action<string> Line;

        public static void Open()
        {
            lock (Gate)
            {
                try
                {
                    AppPaths.EnsureAll();
                    string path = AppPaths.AppLog;
                    // keep the last 3 runs only
                    try
                    {
                        if (File.Exists(path) && new FileInfo(path).Length > 3 * 1024 * 1024)
                            File.Move(path, path + ".old");
                    }
                    catch { }
                    _writer = new StreamWriter(new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8);
                    _writer.AutoFlush = true;
                }
                catch { _writer = null; }
            }
        }

        public static void Close()
        {
            lock (Gate)
            {
                if (_writer != null) { try { _writer.Flush(); _writer.Dispose(); } catch { } _writer = null; }
            }
        }

        public static void Debug(string msg) { Write(LogLevel.Debug, msg, null); }
        public static void Info(string msg) { Write(LogLevel.Info, msg, null); }
        public static void Warn(string msg) { Write(LogLevel.Warn, msg, null); }
        public static void Error(string msg) { Write(LogLevel.Error, msg, null); }
        public static void Error(string msg, Exception ex) { Write(LogLevel.Error, msg, ex); }

        private static void Write(LogLevel level, string msg, Exception ex)
        {
            if (level < Level) return;
            string stamp = DateTime.Now.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
            string body = msg;
            if (ex != null)
            {
                body = msg + " :: " + ex.GetType().Name + ": " + ex.Message;
                if (level == LogLevel.Error && ex.StackTrace != null) body += Environment.NewLine + ex.StackTrace;
            }
            string line = "[" + stamp + "] " + level.ToString().ToUpperInvariant().PadRight(5) + " " + body;
            lock (Gate)
            {
                if (_writer != null) { try { _writer.WriteLine(line); } catch { } }
                else
                {
                    _pending += line + Environment.NewLine;
                    if (_pending.Length > 200000) _pending = _pending.Substring(_pending.Length - 100000);
                }
            }
            Action<string> h = Line;
            if (h != null) { try { h(line); } catch { } }
        }

        public static string Recent()
        {
            lock (Gate) { return _pending; }
        }

        public static void FlushPending()
        {
            lock (Gate)
            {
                if (_writer == null || _pending.Length == 0) return;
                try { _writer.Write(_pending); _writer.Flush(); } catch { }
                _pending = "";
            }
        }

        /// <summary>Tail of a text file, used to surface sing-box's own log in the UI.</summary>
        public static string TailFile(string path, int maxChars)
        {
            try
            {
                if (!File.Exists(path)) return "";
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    long len = fs.Length;
                    int take = (int)Math.Min(len, maxChars);
                    fs.Seek(len - take, SeekOrigin.Begin);
                    var buf = new byte[take];
                    fs.Read(buf, 0, take);
                    var sb = new StringBuilder(new string(Encoding.UTF8.GetChars(buf)));
                    var lines = new List<string>(sb.ToString().Replace("\r\n", "\n").Split('\n'));
                    while (lines.Count > 0 && lines[0].Length == 0) lines.RemoveAt(0);
                    return string.Join(Environment.NewLine, lines.ToArray());
                }
            }
            catch { return ""; }
        }
    }
}

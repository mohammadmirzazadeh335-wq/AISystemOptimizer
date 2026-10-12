using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace ServerHelp.Core
{
    /// <summary>
    /// Startup work: single instance, logging, settings, and a friendly relaunch when the manifest
    /// elevation was refused (TUN and power plans need administrator rights).
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            // Headless check for CI: writes every configuration the app can make and asks the
            // bundled engine to validate it. No window, no mutex, no settings are touched.
            if (args != null && args.Length > 0 && args[0] == "--selftest")
            {
                Environment.ExitCode = SelfTest.Run(args);
                return;
            }

            bool createdNew;
            using (var mutex = new System.Threading.Mutex(true, "ServerHelp_SingleInstance_9F1C", out createdNew))
            {
                if (!createdNew)
                {
                    MessageBox.Show(
                        L.T("برنامه Server Help از قبل باز است.", "Server Help is already running."),
                        "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                AppPaths.EnsureAll();
                Log.Open();
                Log.Info("=== Server Help starting (v" + Version() + ", " + (IsAdmin() ? "admin" : "user") + ") ===");
                Log.Info("data folder: " + AppPaths.Data);
                Log.FlushPending();

                var settings = SettingsStore.Load();
                L.SetLang(settings.Language);

                if (!IsAdmin())
                {
                    Log.Warn("running without administrator rights: TUN, routes, hosts and power plans are limited");
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                try
                {
                    Application.Run(new Ui.MainForm(settings));
                }
                catch (Exception ex)
                {
                    Log.Error("unhandled UI exception", ex);
                    MessageBox.Show(ex.Message, "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                finally
                {
                    SettingsStore.Save(settings);
                    Log.Info("=== Server Help closed ===");
                    Log.Close();
                }
            }
        }

        public static bool IsAdmin()
        {
            try
            {
                var identity = System.Security.Principal.WindowsIdentity.GetCurrent();
                var principal = new System.Security.Principal.WindowsPrincipal(identity);
                return principal.IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator);
            }
            catch { return false; }
        }

        public static string Version()
        {
            try
            {
                var version = Assembly.GetExecutingAssembly().GetName().Version;
                if (version == null) return "1.0.0";
                // CI puts the build number in the fourth part; a local build leaves it at zero, which
                // is not worth showing - but "1.0.0.57" tells the user which download they are running
                return version.Revision > 0 ? version.ToString(4) : version.ToString(3);
            }
            catch { return "1.0.0"; }
        }
    }

    /// <summary>Small helpers shared by the UI: fonts, rounded panels, icon drawing.</summary>
    public static class UiKit
    {
        public static Font UiFont(float size, bool bold)
        {
            string[] names = new string[] { "Segoe UI", "Tahoma", "Arial" };
            foreach (string name in names)
            {
                try
                {
                    var font = new Font(name, size, bold ? FontStyle.Bold : FontStyle.Regular, GraphicsUnit.Point);
                    if (string.Equals(font.FontFamily.Name, name, StringComparison.OrdinalIgnoreCase)) return font;
                    font.Dispose();
                }
                catch { }
            }
            return new Font(FontFamily.GenericSansSerif, size, bold ? FontStyle.Bold : FontStyle.Regular);
        }

        public static Icon BuildIcon()
        {
            try
            {
                var bitmap = new Bitmap(64, 64);
                using (var g = Graphics.FromImage(bitmap))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.Clear(Color.Transparent);
                    using (var brush = new LinearGradientBrush(new Rectangle(0, 0, 64, 64), Color.FromArgb(0x2E, 0xA0, 0x43), Color.FromArgb(0x14, 0x5A, 0x8C), 45f))
                    {
                        g.FillEllipse(brush, 2, 2, 60, 60);
                    }
                    using (var pen = new Pen(Color.White, 4f))
                    {
                        g.DrawLine(pen, 20, 42, 27, 30);
                        g.DrawLine(pen, 27, 30, 33, 40);
                        g.DrawLine(pen, 33, 40, 44, 22);
                    }
                }
                IntPtr handle = bitmap.GetHicon();
                return Icon.FromHandle(handle);
            }
            catch { return null; }
        }

        public static Label Title(string text)
        {
            var label = new Label();
            label.Text = text;
            label.Font = UiFont(14f, true);
            label.AutoSize = true;
            return label;
        }

        public static Label Sub(string text)
        {
            var label = new Label();
            label.Text = text;
            label.Font = UiFont(9f, false);
            label.ForeColor = Color.FromArgb(90, 90, 90);
            label.AutoSize = true;
            return label;
        }

        public static Panel Card()
        {
            var panel = new Panel();
            panel.BorderStyle = BorderStyle.FixedSingle;
            panel.BackColor = Color.White;
            panel.Padding = new Padding(10);
            return panel;
        }
    }
}

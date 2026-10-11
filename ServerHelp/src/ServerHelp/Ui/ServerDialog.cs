using System;
using System.Drawing;
using System.Windows.Forms;
using ServerHelp.Core;

namespace ServerHelp.Ui
{
    /// <summary>Small dialog for adding or editing a server profile.</summary>
    public sealed class ServerDialog : Form
    {
        private readonly TextBox _name = new TextBox();
        private readonly TextBox _host = new TextBox();
        private readonly NumericUpDown _port = new NumericUpDown();
        private readonly TextBox _direct = new TextBox();
        private readonly CheckBox _preferDomain = new CheckBox();

        public ServerProfile Profile { get; private set; }

        public ServerDialog(ServerProfile existing)
        {
            bool rtl = L.IsRtl;
            RightToLeft = rtl ? RightToLeft.Yes : RightToLeft.No;
            RightToLeftLayout = rtl;
            Font = UiKit.UiFont(9.75f, false);
            Text = existing == null ? L.T("افزودن سرور", "Add server") : L.T("ویرایش سرور", "Edit server");
            Width = 470;
            Height = 400;
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;

            Profile = existing == null ? new ServerProfile() : existing.Clone();
            if (existing == null)
            {
                Profile.Name = "Server";
                Profile.Host = "";
                Profile.Port = 25565;
                Profile.DirectIp = "";
            }

            _name.Text = Profile.Name;
            _host.Text = Profile.Host;
            _port.Minimum = 1;
            _port.Maximum = 65535;
            _port.Value = Math.Min(65535, Math.Max(1, Profile.Port));
            _direct.Text = Profile.DirectIp;
            _preferDomain.Text = L.T("اتصال با نام دامنه (توصیه‌شده)", "Connect using the domain name (recommended)");
            _preferDomain.Checked = Profile.PreferDomain;
            _preferDomain.Width = 420;
            _preferDomain.AutoSize = false;
            _preferDomain.Height = 26;

            int y = 14;
            AddRow(L.T("نام سرور", "Server name"), _name, ref y);
            AddRow(L.T("آدرس (دامنه یا IP)", "Address (domain or IP)"), _host, ref y);
            AddRow(L.T("پورت", "Port"), _port, ref y);
            AddRow(L.T("IP جایگزین (اختیاری)", "Fallback IP (optional)"), _direct, ref y);

            _preferDomain.Left = 16;
            _preferDomain.Top = y;
            Controls.Add(_preferDomain);
            y += 34;

            var hint = new Label();
            hint.Text = L.T("مثال: smp3.mcsh.io و پورت 11005 — اگر DNS اینترنت شما آدرس را برنمی‌گرداند، IP جایگزین کمک می‌کند.",
                            "Example: smp3.mcsh.io on port 11005 — the fallback IP helps when your DNS cannot resolve the name.");
            hint.Left = 16;
            hint.Top = y;
            hint.Width = 420;
            hint.Height = 42;
            hint.ForeColor = Color.FromArgb(100, 100, 100);
            Controls.Add(hint);
            y += 48;

            var ok = new Button();
            ok.Text = L.T("ذخیره", "Save");
            ok.Width = 110;
            ok.Left = 16;
            ok.Top = y + 8;
            ok.DialogResult = DialogResult.OK;
            ok.Click += delegate
            {
                Profile.Name = _name.Text.Trim();
                if (Profile.Name.Length == 0) Profile.Name = "Server";
                Profile.Host = _host.Text.Trim();
                Profile.Port = (int)_port.Value;
                Profile.DirectIp = _direct.Text.Trim();
                Profile.PreferDomain = _preferDomain.Checked;
            };
            Controls.Add(ok);

            var cancel = new Button();
            cancel.Text = L.T("انصراف", "Cancel");
            cancel.Width = 110;
            cancel.Left = 136;
            cancel.Top = y + 8;
            cancel.DialogResult = DialogResult.Cancel;
            Controls.Add(cancel);

            AcceptButton = ok;
            CancelButton = cancel;
        }

        private void AddRow(string label, Control input, ref int y)
        {
            var caption = new Label();
            caption.Text = label;
            caption.AutoSize = true;
            caption.Left = 16;
            caption.Top = y;
            Controls.Add(caption);
            input.Left = 16;
            input.Top = y + 20;
            input.Width = 420;
            Controls.Add(input);
            y += 52;
        }
    }
}

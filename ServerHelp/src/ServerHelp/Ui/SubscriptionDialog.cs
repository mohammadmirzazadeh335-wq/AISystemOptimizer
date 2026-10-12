using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using ServerHelp.Core;

namespace ServerHelp.Ui
{
    /// <summary>
    /// Asks for a subscription link and, when the link itself is filtered, which existing connection
    /// should fetch it. Providers hand these links out as a base64 list of share links; fetching them
    /// through a working proxy is often the only way to get them at all.
    /// </summary>
    public sealed class SubscriptionDialog : Form
    {
        private readonly TextBox _url;
        private readonly ComboBox _via;

        public string Url { get { return _url.Text.Trim(); } }
        public int ViaIndex { get { return _via.SelectedIndex < 0 ? 0 : _via.SelectedIndex; } }

        public SubscriptionDialog(List<string> viaChoices)
        {
            bool rtl = L.IsRtl;
            RightToLeft = rtl ? RightToLeft.Yes : RightToLeft.No;
            RightToLeftLayout = rtl;
            Font = UiKit.UiFont(9.75f, false);
            Text = L.T("افزودن از لینک اشتراک", "Add from a subscription link");
            Width = 620;
            Height = 300;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MinimizeBox = false;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterParent;

            var hint = new Label();
            hint.Text = L.T("لینک اشتراک (همان آدرسی که سرویس‌دهنده می‌دهد و با باز کردنش متن base64 می‌آید):",
                            "the subscription link (the address your provider gives you, which returns base64 text):");
            hint.AutoSize = true;
            hint.Location = new Point(14, 14);
            Controls.Add(hint);

            _url = new TextBox();
            _url.Left = 14;
            _url.Top = 38;
            _url.Width = 570;
            Controls.Add(_url);

            var viaLabel = new Label();
            viaLabel.Text = L.T("دریافت از طریق:", "fetch through:");
            viaLabel.AutoSize = true;
            viaLabel.Location = new Point(14, 78);
            Controls.Add(viaLabel);

            _via = new ComboBox();
            _via.DropDownStyle = ComboBoxStyle.DropDownList;
            _via.Left = 150;
            _via.Top = 74;
            _via.Width = 300;
            if (viaChoices != null) foreach (string choice in viaChoices) _via.Items.Add(choice);
            if (_via.Items.Count > 0) _via.SelectedIndex = 0;
            Controls.Add(_via);

            var note = new Label();
            note.Text = L.T("اگر خودِ لینک اشتراک فیلتر است، یکی از اتصال‌های سالم را انتخاب کنید تا از داخل آن گرفته شود.",
                            "if the subscription link itself is blocked, pick a working connection so it is fetched through it.");
            note.ForeColor = Color.FromArgb(110, 118, 130);
            note.Left = 14;
            note.Top = 106;
            note.Width = 570;
            note.Height = 40;
            Controls.Add(note);

            var ok = new Button();
            ok.Text = L.T("دریافت و افزودن", "Fetch and add");
            ok.Width = 170;
            ok.Left = 14;
            ok.Top = 200;
            ok.DialogResult = DialogResult.OK;
            Controls.Add(ok);

            var cancel = new Button();
            cancel.Text = L.T("انصراف", "Cancel");
            cancel.Width = 110;
            cancel.Left = 194;
            cancel.Top = 200;
            cancel.DialogResult = DialogResult.Cancel;
            Controls.Add(cancel);

            AcceptButton = ok;
            CancelButton = cancel;
            // an empty or hand-typed address would fail after the dialog closed; say so while the
            // user is still looking at the box
            FormClosing += delegate (object sender, FormClosingEventArgs e)
            {
                if (DialogResult != DialogResult.OK) return;
                string text = _url.Text.Trim();
                if (text.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                    text.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) return;
                e.Cancel = true;
                MessageBox.Show(this,
                    L.T("آدرس اشتراک باید با http:// یا https:// شروع شود.",
                        "the subscription address must start with http:// or https://"),
                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                _url.Focus();
            };
            Theme.Apply(this);
            Theme.StyleButton(ok, true);
        }
    }
}

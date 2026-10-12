using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using ServerHelp.Core;

namespace ServerHelp.Ui
{
    /// <summary>
    /// Bulk import: paste as many lines as you like — SOCKS5/HTTP/MTProto proxies, DNS servers,
    /// WireGuard configs, share links or raw sing-box JSON — and they are turned into entries.
    /// </summary>
    public sealed class ImportDialog : Form
    {
        private readonly TextBox _input;
        private readonly ListView _preview;
        private readonly Label _summary;
        private List<ConnectionEntry> _entries = new List<ConnectionEntry>();

        public List<ConnectionEntry> Entries
        {
            get
            {
                Parse();
                return _entries;
            }
        }

        public ImportDialog(string initialText)
        {
            bool rtl = L.IsRtl;
            RightToLeft = rtl ? RightToLeft.Yes : RightToLeft.No;
            RightToLeftLayout = rtl;
            Font = UiKit.UiFont(9.75f, false);
            Text = L.T("افزودن دسته‌ای اتصال‌ها", "Import connections");
            Width = 760;
            Height = 620;
            StartPosition = FormStartPosition.CenterParent;

            var hint = new Label();
            hint.Dock = DockStyle.Top;
            hint.Height = 62;
            hint.Padding = new Padding(10, 8, 10, 0);
            hint.Text = L.T(
                "هر خط یک اتصال. نمونه‌ها:  1.2.3.4:1080 · socks5://user:pass@1.2.3.4:1080 · http://1.2.3.4:8080\n" +
                "8.8.8.8 · udp://1.1.1.1:53 · tls://1.1.1.1 · https://cloudflare-dns.com/dns-query\n" +
                "server:443:ee0f...  (پروکسی تلگرام) · vless:// / vmess:// / trojan:// / ss:// / hysteria2:// / tuic://\n" +
                "[Interface] ... [Peer] ... (WireGuard) · یا کانفیگ JSON کامل sing-box",
                "One connection per line. Examples:  1.2.3.4:1080 · socks5://user:pass@1.2.3.4:1080 · http://1.2.3.4:8080\n" +
                "8.8.8.8 · udp://1.1.1.1:53 · tls://1.1.1.1 · https://cloudflare-dns.com/dns-query\n" +
                "server:443:ee0f...  (Telegram proxy) · vless:// / vmess:// / trojan:// / ss:// / hysteria2:// / tuic://\n" +
                "[Interface] ... [Peer] ... (WireGuard) · or a complete sing-box JSON config");
            Controls.Add(hint);

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 46;
            buttons.FlowDirection = FlowDirection.LeftToRight;
            buttons.Padding = new Padding(8, 6, 8, 0);

            var parse = new Button();
            parse.Text = L.T("بررسی و پیش‌نمایش", "Check and preview");
            parse.Width = 170;
            parse.Click += delegate { Parse(); };
            buttons.Controls.Add(parse);

            var paste = new Button();
            paste.Text = L.T("چسباندن از کلیپ‌بورد", "Paste from clipboard");
            paste.Width = 170;
            paste.Click += delegate
            {
                try { if (Clipboard.ContainsText()) _input.Text = Clipboard.GetText(); }
                catch { }
                Parse();
            };
            buttons.Controls.Add(paste);

            var ok = new Button();
            ok.Text = L.T("افزودن به لیست", "Add to the list");
            ok.Width = 150;
            ok.DialogResult = DialogResult.OK;
            ok.Click += delegate { Parse(); };
            buttons.Controls.Add(ok);
            Theme.Apply(this);
            Theme.StyleButton(ok, true);

            var cancel = new Button();
            cancel.Text = L.T("انصراف", "Cancel");
            cancel.Width = 110;
            cancel.DialogResult = DialogResult.Cancel;
            buttons.Controls.Add(cancel);

            Controls.Add(buttons);

            _preview = new ListView();
            _preview.Dock = DockStyle.Bottom;
            _preview.Height = 210;
            _preview.View = View.Details;
            _preview.FullRowSelect = true;
            _preview.GridLines = true;
            _preview.Columns.Add(L.T("نام", "Name"), 190);
            _preview.Columns.Add(L.T("نوع", "Kind"), 150);
            _preview.Columns.Add(L.T("مقصد", "Target"), 240);
            _preview.Columns.Add(L.T("وضعیت", "Result"), 300);
            Controls.Add(_preview);

            _summary = new Label();
            _summary.Dock = DockStyle.Bottom;
            _summary.Height = 24;
            _summary.Padding = new Padding(10, 2, 10, 0);
            Controls.Add(_summary);

            _input = new TextBox();
            _input.Multiline = true;
            _input.ScrollBars = ScrollBars.Both;
            _input.WordWrap = false;
            _input.Dock = DockStyle.Fill;
            _input.Font = new Font("Consolas", 9.5f);
            _input.Text = initialText ?? "";
            Controls.Add(_input);
            _input.BringToFront();
        }

        private void Parse()
        {
            List<string> errors;
            _entries = ConnectionParser.ParseMany(_input.Text, out errors);

            _preview.Items.Clear();
            foreach (ConnectionEntry entry in _entries)
            {
                var item = new ListViewItem(entry.Name);
                item.SubItems.Add(entry.Info.Title);
                item.SubItems.Add(entry.Target);
                string missing = entry.Missing();
                item.SubItems.Add(missing.Length == 0 ? L.T("آماده", "ready") : L.T("ناقص: ", "incomplete: ") + missing);
                if (missing.Length > 0) item.ForeColor = Color.FromArgb(180, 110, 0);
                _preview.Items.Add(item);
            }
            foreach (string error in errors)
            {
                var item = new ListViewItem(L.T("خوانده نشد", "not recognised"));
                item.SubItems.Add("—");
                item.SubItems.Add("—");
                item.SubItems.Add(error);
                item.ForeColor = Color.FromArgb(180, 40, 40);
                _preview.Items.Add(item);
            }

            _summary.Text = L.T("پیدا شد: ", "found: ") + _entries.Count + L.T(" اتصال", " connection(s)") +
                            (errors.Count > 0 ? L.T(" • خطا: ", " • errors: ") + errors.Count : "");
        }
    }
}

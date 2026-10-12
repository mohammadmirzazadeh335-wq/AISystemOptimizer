using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using ServerHelp.Core;
using ServerHelp.Net;

namespace ServerHelp.Ui
{
    /// <summary>
    /// Editor for one connection. Every field the app knows about is here; the ones that do not
    /// apply to the chosen kind are hidden, and the Test button measures the real delay before the
    /// entry is saved.
    /// </summary>
    public sealed class ConnectionDialog : Form
    {
        private readonly bool _rtl = L.IsRtl;
        private readonly AppSettings _settings;
        private readonly ServerProfile _server;

        private ComboBox _kindCombo;
        private TextBox _name;
        private CheckBox _enabled;
        private CheckBox _useForGame;

        private Label _lblHost, _lblPort, _lblUser, _lblPassword, _lblSecret, _lblDns, _lblAddress, _lblAddressV6,
                      _lblPeerKey, _lblPeerHost, _lblPeerPort, _lblReserved, _lblMtu, _lblConfig, _lblSocksPort, _lblNotes;
        private TextBox _host, _user, _password, _secret, _dns, _address, _addressV6, _peerKey, _peerHost, _reserved, _config, _notes;
        private Button _ovpnBrowse;
        private Label _ovpnHint;
        private CheckBox _fragment;
        private NumericUpDown _port, _peerPort, _mtu, _socksPort;
        private NumericUpDown _dc;
        private Label _lblDc, _secretHint;

        private Label _result;
        private Button _test;
        private Button _ok;

        public ConnectionEntry Entry { get; private set; }
        private ConnectionEntry _original;

        public ConnectionDialog(ConnectionEntry existing, AppSettings settings, ServerProfile server)
        {
            _settings = settings;
            _server = server ?? (settings != null ? settings.GetActiveServer() : AppSettings.DefaultServer());

            RightToLeft = _rtl ? RightToLeft.Yes : RightToLeft.No;
            RightToLeftLayout = _rtl;
            Font = UiKit.UiFont(9.75f, false);
            Text = existing == null ? L.T("افزودن اتصال", "Add connection") : L.T("ویرایش اتصال", "Edit connection");
            Width = 640;
            Height = 700;
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.Sizable;
            MinimizeBox = false;
            MaximizeBox = false;

            Entry = existing == null ? ConnectionEntry.Create("", ConnectionKind.Socks5) : existing.Clone();
            _original = Entry.Clone();
            _original.ForgetTest();   // only results measured in this dialog count

            var panel = new Panel();
            panel.Dock = DockStyle.Fill;
            panel.AutoScroll = true;
            panel.Padding = new Padding(12);
            Controls.Add(panel);

            int y = 8;

            var lblKind = Caption(L.T("نوع اتصال", "Connection kind"));
            lblKind.Location = new Point(12, y);
            panel.Controls.Add(lblKind);

            _kindCombo = new ComboBox();
            _kindCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _kindCombo.Left = 12;
            _kindCombo.Top = y + 20;
            _kindCombo.Width = 340;
            foreach (ConnectionKindInfo info in ConnectionKindInfo.AllKinds()) _kindCombo.Items.Add(info.Title);
            _kindCombo.SelectedIndex = IndexOfKind(Entry.Kind);
            _kindCombo.SelectedIndexChanged += delegate { OnKindChanged(); };
            panel.Controls.Add(_kindCombo);
            y += 54;

            _name = TextField(panel, L.T("نام", "Name"), ref y, Entry.Name, 340);
            _enabled = CheckField(panel, L.T("فعال", "Enabled"), ref y, Entry.Enabled);
            _useForGame = CheckField(panel, L.T("در انتخاب خودکار مسیر بازی شرکت کند", "Let the automatic game route pick it"), ref y, Entry.UseForGame);

            _host = TextField(panel, L.T("آدرس سرور/پروکسی", "Server or proxy address"), ref y, Entry.Host, 240, out _lblHost);
            _port = NumberField(panel, L.T("پورت", "Port"), ref y, Entry.Port, 1, 65535, out _lblPort);
            _user = TextField(panel, L.T("نام کاربری (اختیاری)", "User name (optional)"), ref y, Entry.User, 240, out _lblUser);
            _password = TextField(panel, L.T("رمز (اختیاری)", "Password (optional)"), ref y, Entry.Password, 240, out _lblPassword);
            _password.UseSystemPasswordChar = true;

            _dns = TextField(panel, L.T("آدرس DNS (udp:// یا tcp:// یا tls:// یا https://)", "DNS address (udp:// tcp:// tls:// https://)"),
                        ref y, Entry.DnsUrl, 420, out _lblDns);

            _secret = TextField(panel, L.T("سکرت (MTProto: tg://… یا host:port:secret — WireGuard: PrivateKey)",
                                          "Secret (MTProto: tg://… or host:port:secret - WireGuard: PrivateKey)"),
                           ref y, Entry.Secret, 420, out _lblSecret);
            _secret.TextChanged += delegate { UpdateSecretHint(); };

            _secretHint = new Label();
            _secretHint.Left = 12;
            _secretHint.Top = y;
            _secretHint.Width = 460;
            _secretHint.Height = 20;
            _secretHint.ForeColor = Color.FromArgb(90, 90, 90);
            panel.Controls.Add(_secretHint);
            y += 26;

            _dc = NumberField(panel, L.T("دیتاسنتر تلگرام (۱ تا ۵)", "Telegram data centre (1 to 5)"),
                              ref y, Entry.Dc <= 0 ? 2 : Entry.Dc, 1, 5, out _lblDc);
            _address = TextField(panel, L.T("آدرس کلاینت WireGuard", "WireGuard client address"), ref y, Entry.Address, 240, out _lblAddress);
            _addressV6 = TextField(panel, L.T("آدرس IPv6 (اختیاری)", "IPv6 address (optional)"), ref y, Entry.AddressV6, 300, out _lblAddressV6);
            _peerKey = TextField(panel, L.T("کلید عمومی سرور (PublicKey)", "Peer public key"), ref y, Entry.PeerPublicKey, 420, out _lblPeerKey);
            _peerHost = TextField(panel, L.T("آدرس سرور WireGuard", "WireGuard peer address"), ref y, Entry.PeerHost, 300, out _lblPeerHost);
            _peerPort = NumberField(panel, L.T("پورت سرور WireGuard", "WireGuard peer port"), ref y, Entry.PeerPort, 1, 65535, out _lblPeerPort);
            _reserved = TextField(panel, L.T("بایت‌های reserved مثل 0,0,0 (اختیاری)", "Reserved bytes such as 0,0,0 (optional)"),
                             ref y, Entry.Reserved, 200, out _lblReserved);
            _mtu = NumberField(panel, L.T("MTU", "MTU"), ref y, Entry.Mtu <= 0 ? 1280 : Entry.Mtu, 576, 1500, out _lblMtu);

            var lblConfig = Caption(L.T("کانفیگ JSON (outbound یا کانفیگ کامل sing-box)", "JSON config (an outbound or a full sing-box config)"));
            lblConfig.Location = new Point(12, y);
            panel.Controls.Add(lblConfig);
            _lblConfig = lblConfig;
            _config = new TextBox();
            _config.Multiline = true;
            _config.ScrollBars = ScrollBars.Both;
            _config.WordWrap = false;
            _config.Left = 12;
            _config.Top = y + 20;
            _config.Width = 560;
            _config.Height = 150;
            _config.Font = new Font("Consolas", 9f);
            _config.Text = Entry.Config;
            _config.TextChanged += delegate { OnConfigChanged(); };   // once, not once per kind change
            panel.Controls.Add(_config);

            // the .ovpn helpers sit above the box they fill, and only for that kind
            _ovpnBrowse = new Button();
            _ovpnBrowse.Text = L.T("خواندن از فایل .ovpn…", "Load an .ovpn file…");
            _ovpnBrowse.Width = 190;
            _ovpnBrowse.Left = 12;
            _ovpnBrowse.Top = _config.Top + _config.Height + 6;
            _ovpnBrowse.Click += delegate { LoadOvpnFile(); };
            panel.Controls.Add(_ovpnBrowse);

            _ovpnHint = new Label();
            _ovpnHint.Left = 214;
            _ovpnHint.Top = _ovpnBrowse.Top + 4;
            _ovpnHint.Width = 360;
            _ovpnHint.Height = 32;
            _ovpnHint.ForeColor = Color.FromArgb(120, 120, 120);
            panel.Controls.Add(_ovpnHint);

            y += 224;

            _socksPort = NumberField(panel, L.T("پورت SOCKS محلی کانفیگ کامل", "Local SOCKS port of a full config"),
                                ref y, Entry.LocalSocksPort, 0, 65535, out _lblSocksPort);

            _fragment = new CheckBox();
            _fragment.Text = L.T("تکه‌تکه‌کردن TLS برای این اتصال (کمک به خطی که SNI را می‌بندد)",
                                 "Fragment TLS for this connection (helps where SNI is blocked)");
            _fragment.AutoSize = true;
            _fragment.Checked = Entry.FragmentTls;
            _fragment.Left = 12;
            _fragment.Top = y;
            panel.Controls.Add(_fragment);
            y += 30;

            _notes = TextField(panel, L.T("یادداشت", "Notes"), ref y, Entry.Notes, 420, out _lblNotes);

            y += 10;
            _test = new Button();
            _test.Text = L.T("تست و اندازه‌گیری تأخیر", "Test and measure the delay");
            _test.Left = 12;
            _test.Top = y;
            _test.Width = 220;
            _test.Click += delegate { RunTest(); };
            panel.Controls.Add(_test);

            _ok = new Button();
            _ok.Text = L.T("ذخیره", "Save");
            _ok.Left = 244;
            _ok.Top = y;
            _ok.Width = 120;
            _ok.DialogResult = DialogResult.OK;
            _ok.Click += delegate { Collect(); };
            panel.Controls.Add(_ok);

            var cancel = new Button();
            cancel.Text = L.T("انصراف", "Cancel");
            cancel.Left = 376;
            cancel.Top = y;
            cancel.Width = 120;
            cancel.DialogResult = DialogResult.Cancel;
            panel.Controls.Add(cancel);
            y += 40;

            _result = new Label();
            _result.Left = 12;
            _result.Top = y;
            _result.Width = 570;
            _result.Height = 60;
            _result.Text = L.T("برای دیدن تأخیر واقعی، دکمه تست را بزنید.", "Press Test to see the real delay.");
            panel.Controls.Add(_result);

            AcceptButton = _ok;
            CancelButton = cancel;
            // Saving an entry with holes in it is allowed, but never silent: the row would sit in the
            // table looking ready while the pipeline skips it.
            FormClosing += delegate (object sender, FormClosingEventArgs e)
            {
                if (DialogResult != DialogResult.OK) return;
                Collect();
                // two connections with the same name would make the pin and the route chooser
                // ambiguous, so the second one gets a number - with the user's agreement
                if (_settings != null && Entry.Name.Length > 0)
                {
                    ConnectionEntry clash = _settings.FindConnection(Entry.Name);
                    if (clash != null && clash.Id != Entry.Id)
                    {
                        DialogResult rename = MessageBox.Show(this,
                            L.T("اتصالی با همین نام هست: ", "another connection already uses the name: ") +
                            Entry.Name + L.T(" — نام شماره‌دار بگذارم؟", " — use a numbered name?"),
                            "Server Help", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                        if (rename != DialogResult.Yes) { e.Cancel = true; return; }
                        string baseName = Entry.Name;
                        int number = 2;
                        while (_settings.FindConnection(baseName + " " + number) != null) number++;
                        Entry.Name = baseName + " " + number;
                    }
                }
                string missing = Entry.Missing();
                if (missing.Length == 0) return;
                DialogResult answer = MessageBox.Show(this,
                    L.T("این فیلدها هنوز خالی است: ", "these fields are still empty: ") + missing +
                    Environment.NewLine + Environment.NewLine +
                    L.T("با همین حال ذخیره شود؟ (می‌توانید بعداً ویرایش کنید)", "save it like this? (you can edit it later)"),
                    "Server Help", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                if (answer == DialogResult.No) e.Cancel = true;
            };
            OnKindChanged();
            Theme.Apply(this);
            Theme.StyleButton(_ok, true);
            Theme.StyleButton(_test, false);
        }

        // ------------------------------------------------------------------ fields

        private Label Caption(string text)
        {
            var label = new Label();
            label.Text = text;
            label.AutoSize = true;
            label.ForeColor = Color.FromArgb(70, 78, 92);
            return label;
        }

        private TextBox TextField(Panel panel, string caption, ref int y, string value, int width)
        {
            Label unused;
            return TextField(panel, caption, ref y, value, width, out unused);
        }

        private TextBox TextField(Panel panel, string caption, ref int y, string value, int width, out Label label)
        {
            label = Caption(caption);
            label.Location = new Point(12, y);
            panel.Controls.Add(label);
            var box = new TextBox();
            box.Left = 12;
            box.Top = y + 20;
            box.Width = width;
            box.Text = value ?? "";
            panel.Controls.Add(box);
            y += 52;
            return box;
        }

        private NumericUpDown NumberField(Panel panel, string caption, ref int y, int value, int min, int max, out Label label)
        {
            label = Caption(caption);
            label.Location = new Point(12, y);
            panel.Controls.Add(label);
            var box = new NumericUpDown();
            box.Left = 12;
            box.Top = y + 20;
            box.Width = 120;
            box.Minimum = min;
            box.Maximum = max;
            box.Value = Math.Min(max, Math.Max(min, value));
            panel.Controls.Add(box);
            y += 52;
            return box;
        }

        private CheckBox CheckField(Panel panel, string caption, ref int y, bool value)
        {
            var box = new CheckBox();
            box.Text = caption;
            box.AutoSize = true;
            box.Left = 12;
            box.Top = y;
            box.Checked = value;
            panel.Controls.Add(box);
            y += 30;
            return box;
        }

        // ------------------------------------------------------------------ kinds

        private ConnectionKind CurrentKind
        {
            get
            {
                // the combo lists the kinds in their own order; the enum value is not the row number
                List<ConnectionKindInfo> kinds = ConnectionKindInfo.AllKinds();
                int index = _kindCombo.SelectedIndex;
                if (index < 0 || index >= kinds.Count) return ConnectionKind.Socks5;
                return kinds[index].Kind;
            }
        }

        private static int IndexOfKind(ConnectionKind kind)
        {
            List<ConnectionKindInfo> kinds = ConnectionKindInfo.AllKinds();
            for (int i = 0; i < kinds.Count; i++) if (kinds[i].Kind == kind) return i;
            return 2;   // SOCKS5
        }

        private void Show(Control control, bool visible)
        {
            if (control != null) control.Visible = visible;
        }

        private void OnKindChanged()
        {
            ConnectionKind kind = CurrentKind;
            bool isSocks = kind == ConnectionKind.Socks5;
            bool isHttp = kind == ConnectionKind.Http;
            bool isMtproto = kind == ConnectionKind.Mtproto;
            bool isProxy = isSocks || isHttp || isMtproto;
            bool isWireGuard = kind == ConnectionKind.WireGuard;
            bool isDns = kind == ConnectionKind.Dns;
            bool isRaw = kind == ConnectionKind.SingBoxOutbound || kind == ConnectionKind.SingBoxConfig;
            bool isWarp = kind == ConnectionKind.Warp;

            Show(_lblHost, isProxy || isWireGuard);
            Show(_host, isProxy || isWireGuard);
            Show(_lblPort, isProxy);
            Show(_port, isProxy);
            Show(_lblUser, isSocks || isHttp);
            Show(_user, isSocks || isHttp);
            Show(_lblPassword, isSocks || isHttp);
            Show(_password, isSocks || isHttp);

            Show(_lblDns, isDns);
            Show(_dns, isDns);

            Show(_lblSecret, isMtproto || isWireGuard);
            Show(_secret, isMtproto || isWireGuard);
            _secret.UseSystemPasswordChar = isWireGuard;   // a TG secret has to stay readable
            Show(_lblDc, isMtproto);
            Show(_dc, isMtproto);
            Show(_secretHint, isMtproto || isWireGuard);

            Show(_lblAddress, isWireGuard);
            Show(_address, isWireGuard);
            Show(_lblAddressV6, isWireGuard);
            Show(_addressV6, isWireGuard);
            Show(_lblPeerKey, isWireGuard);
            Show(_peerKey, isWireGuard);
            Show(_lblPeerHost, isWireGuard);
            Show(_peerHost, isWireGuard);
            Show(_lblPeerPort, isWireGuard);
            Show(_peerPort, isWireGuard);
            Show(_lblReserved, isWireGuard);
            Show(_reserved, isWireGuard);
            Show(_lblMtu, isWireGuard);
            Show(_mtu, isWireGuard);

            bool isOvpn = kind == ConnectionKind.OpenVpn;
            Show(_lblConfig, isRaw || isOvpn);
            Show(_config, isRaw || isOvpn);
            if (isOvpn)
                _lblConfig.Text = L.T("متن فایل .ovpn (TunnelBear و مانند آن) را اینجا بچسبانید یا از فایل بخوانید:",
                                     "paste the .ovpn profile here (TunnelBear and similar) or load it from a file:");
            else if (isRaw)
                _lblConfig.Text = L.T("کانفیگ JSON", "JSON configuration");
            Show(_lblSocksPort, kind == ConnectionKind.SingBoxConfig);
            Show(_socksPort, kind == ConnectionKind.SingBoxConfig);

            // WARP and DNS carry no host:port of their own
            if (isWarp || isDns)
            {
                Show(_lblHost, false);
                Show(_host, false);
                Show(_lblPort, false);
                Show(_port, false);
            }

            // an OpenVPN profile brings its own server address and its own certificates; the only
            // thing it may still need from the user is the account of the provider
            if (isOvpn)
            {
                Show(_lblHost, false);
                Show(_host, false);
                Show(_lblPort, false);
                Show(_port, false);
                OvpnProfile profile = OvpnProfile.Parse(_config.Text, "");
                Show(_lblUser, true);
                Show(_user, true);
                Show(_lblPassword, true);
                Show(_password, true);
                _lblUser.Text = L.T("نام کاربری حساب (اگر سرویس‌دهنده می‌خواهد)",
                                    "account username (only when the provider asks for one)");
                _lblPassword.Text = L.T("رمز حساب", "account password");
                if (_ovpnHint != null)
                {
                    _ovpnHint.Text = profile.Ok
                        ? "✓ " + profile.Summary() + (profile.Warnings.Count > 0
                            ? "  •  " + string.Join(" ", profile.Warnings.ToArray()) : "")
                        : L.T("فایل .ovpn را از فایل بخوانید یا متنش را بچسبانید.", "load or paste an .ovpn profile.");
                    _ovpnHint.ForeColor = profile.Ok ? Color.FromArgb(24, 120, 50) : Color.FromArgb(120, 120, 120);
                }
            }
            if (_ovpnBrowse != null) Show(_ovpnBrowse, isOvpn);

            bool tlsCapable = kind == ConnectionKind.SingBoxOutbound || isOvpn;
            if (_fragment != null)
            {
                Show(_fragment, tlsCapable);
                if (!tlsCapable) _fragment.Checked = false;
            }

            // only the kinds that can really carry a game may join the automatic route
            _useForGame.Enabled = ConnectionKindInfo.Of(kind).CanCarryGame;
            if (!_useForGame.Enabled) _useForGame.Checked = false;

            OnConfigChanged();
        }

        /// <summary>
        /// Live feedback while the config is typed or pasted: the .ovpn summary, the secret hint and
        /// whether the fragment switch can apply. A half pasted JSON is normal while typing, so the
        /// parse is guarded and an unreadable config leaves the switch alone instead of moving it.
        /// </summary>
        private void OnConfigChanged()
        {
            UpdateSecretHint();
            if (_fragment == null || !_fragment.Visible) return;
            if (CurrentKind != ConnectionKind.SingBoxOutbound)
            {
                _fragment.Enabled = true;
                return;
            }
            bool parsedOk = false;
            bool hasTls = false;
            try
            {
                Dictionary<string, object> parsed = Json.ParseObject(_config.Text);
                parsedOk = true;
                hasTls = parsed != null && Json.Get(parsed, "tls") != null;
            }
            catch { parsedOk = false; }
            if (!parsedOk) return;
            _fragment.Enabled = hasTls;
            if (!hasTls) _fragment.Checked = false;
        }

        /// <summary>Live explanation of what the pasted secret means - the main MTProto debug aid.</summary>
        private void UpdateSecretHint()
        {
            if (_secretHint == null) return;
            ConnectionKind kind = CurrentKind;
            if (kind == ConnectionKind.Mtproto)
            {
                string text = _secret.Text.Trim();
                if (text.Length == 0)
                {
                    _secretHint.ForeColor = Color.FromArgb(120, 120, 120);
                    _secretHint.Text = L.T("سکرت را بچسبانید: tg://proxy?server=…&port=…&secret=… یا host:port:secret",
                                           "paste the secret: tg://proxy?server=…&port=…&secret=… or host:port:secret");
                    return;
                }
                MtprotoSecret parsed = MtprotoSecret.Parse(text);
                if (!parsed.Ok)
                {
                    _secretHint.ForeColor = Color.FromArgb(180, 40, 40);
                    _secretHint.Text = "✗ " + parsed.Error;
                    return;
                }
                _secretHint.ForeColor = Color.FromArgb(24, 120, 50);
                _secretHint.Text = "✓ " + parsed.Describe();
                if (parsed.Mode == MtprotoMode.FakeTls && parsed.Domain.Length == 0)
                {
                    _secretHint.ForeColor = Color.FromArgb(180, 110, 0);
                    _secretHint.Text = "! " + L.T("این سکرت fake-TLS بدون دامنه است؛ معمولاً کار نمی‌کند.",
                                                  "this fake-TLS secret has no domain; it usually will not work.");
                }
                return;
            }

            if (kind == ConnectionKind.OpenVpn)
            {
                OvpnProfile profile = OvpnProfile.Parse(_config == null ? "" : _config.Text, "");
                if (_ovpnHint == null) return;
                if (!profile.Ok)
                {
                    _ovpnHint.ForeColor = Color.FromArgb(120, 120, 120);
                    _ovpnHint.Text = L.T("فایل .ovpn را از فایل بخوانید یا متنش را بچسبانید.",
                                         "load or paste an .ovpn profile.");
                    return;
                }
                _ovpnHint.ForeColor = profile.Warnings.Count > 0 ? Color.FromArgb(180, 110, 0) : Color.FromArgb(24, 120, 50);
                _ovpnHint.Text = (profile.Warnings.Count > 0 ? "! " : "✓ ") + profile.Summary() +
                                 (profile.Warnings.Count > 0 ? "  •  " + string.Join(" ", profile.Warnings.ToArray()) : "");
                return;
            }

            if (kind == ConnectionKind.WireGuard)
            {
                string key = _secret.Text.Trim();
                int length = key.Length;
                if (length == 0)
                {
                    _secretHint.ForeColor = Color.FromArgb(120, 120, 120);
                    _secretHint.Text = L.T("PrivateKey وایرگارد ۴۴ کاراکتر base64 است.",
                                           "a WireGuard PrivateKey is 44 base64 characters.");
                }
                else if (length != 44)
                {
                    _secretHint.ForeColor = Color.FromArgb(180, 110, 0);
                    _secretHint.Text = L.T("طول کلید ", "the key is ") + L.N(length) +
                                       L.T(" کاراکتر است، باید ۴۴ باشد.", " characters, it should be 44.");
                }
                else
                {
                    _secretHint.ForeColor = Color.FromArgb(24, 120, 50);
                    _secretHint.Text = "✓ " + L.T("طول کلید درست است", "the key length is right");
                }
                return;
            }

            _secretHint.Text = "";
        }


        /// <summary>Loads an .ovpn profile: the file may name certificates beside it, so the path is passed on.</summary>
        private void LoadOvpnFile()
        {
            using (var dialog = new OpenFileDialog())
            {
                dialog.Title = L.T("انتخاب فایل OpenVPN", "Choose an OpenVPN profile");
                dialog.Filter = "OpenVPN (*.ovpn)|*.ovpn|" + L.T("همه فایل‌ها", "all files") + " (*.*)|*.*";
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    string text = File.ReadAllText(dialog.FileName);
                    OvpnProfile profile = OvpnProfile.Parse(text, dialog.FileName);
                    if (!profile.Ok)
                    {
                        MessageBox.Show(L.T("این فایل کانفیگ OpenVPN نیست: ", "this file is not an OpenVPN profile: ") +
                                        string.Join(" ", profile.Warnings.ToArray()),
                            "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        return;
                    }
                    _config.Text = text;
                    _name.Text = ConnectionParser.OvpnName(dialog.FileName, profile);
                    if (profile.NeedsCredentials && _user.Text.Length == 0)
                        _user.Focus();
                    else
                        OnKindChanged();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.Message, "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }

        // ------------------------------------------------------------------ actions

        /// <summary>The one place the dialog writes back what the .ovpn said about itself.</summary>
        private void CollectOvpnFlags(ConnectionEntry entry)
        {
            if (entry == null || entry.Kind != ConnectionKind.OpenVpn) return;
            OvpnProfile profile = OvpnProfile.Parse(entry.Config, "");
            entry.NeedsCredentials = profile.NeedsCredentials;
            if (profile.Ok)
            {
                entry.Host = profile.Host;
                entry.Port = profile.Port;
                // the summary only fills a note the user left empty: their own words stay
                if (entry.Notes.Length == 0) entry.Notes = profile.Summary();
            }
        }

        private void Collect()
        {
            Entry.Kind = CurrentKind;
            Entry.Name = _name.Text.Trim();
            if (Entry.Name.Length == 0) Entry.Name = Entry.Info.Title + " " + (_host.Text.Trim().Length > 0 ? _host.Text.Trim() : Entry.Id);
            Entry.Enabled = _enabled.Checked;
            Entry.UseForGame = _useForGame.Checked;
            Entry.Host = _host.Text.Trim();
            Entry.Port = (int)_port.Value;
            Entry.User = _user.Text.Trim();
            Entry.Password = _password.Text;
            Entry.Secret = _secret.Text.Trim();
            Entry.DnsUrl = _dns.Text.Trim();
            Entry.Address = _address.Text.Trim();
            Entry.AddressV6 = _addressV6.Text.Trim();
            Entry.PeerPublicKey = _peerKey.Text.Trim();
            Entry.PeerHost = _peerHost.Text.Trim();
            Entry.PeerPort = (int)_peerPort.Value;
            Entry.Reserved = _reserved.Text.Trim();
            Entry.Mtu = (int)_mtu.Value;
            Entry.Config = _config.Text.Trim();
            Entry.LocalSocksPort = (int)_socksPort.Value;
            Entry.FragmentTls = _fragment != null && _fragment.Checked;
            Entry.Notes = _notes.Text.Trim();
            Entry.Dc = (int)_dc.Value;
            CollectOvpnFlags(Entry);

            // a changed address invalidates the delay that was measured for the old one
            if (_original != null && !_original.SameConfig(Entry)) Entry.ForgetTest();
        }

        private void RunTest()
        {
            Collect();
            string missing = Entry.Missing();
            if (missing.Length > 0)
            {
                _result.ForeColor = Color.FromArgb(180, 40, 40);
                _result.Text = L.T("این فیلدها لازم است: ", "these fields are required: ") + missing;
                return;
            }

            _test.Enabled = false;
            _result.ForeColor = Color.FromArgb(60, 60, 60);
            _result.Text = L.T("در حال تست…", "testing…");

            string host = _server != null ? _server.Host : "";
            int port = _server != null ? _server.Port : 25565;
            int timeout = _settings != null ? _settings.ConnectionTestTimeoutMs : 3000;
            ConnectionEntry snapshot = Entry.Clone();

            var thread = new Thread(delegate ()
            {
                ConnectionTestResult result;
                try { result = ConnectionTester.Test(snapshot, host, port, timeout, false); }
                catch (Exception ex)
                {
                    // the dialog must always come back, so a surprise is reported like a failed test
                    result = ConnectionTestResult.Fail(L.T("تست شکست خورد", "the test failed"), ex.Message,
                                                       snapshot.CanCarryGame);
                }
                try
                {
                    BeginInvoke((Action)delegate
                    {
                        _test.Enabled = true;
                        if (Entry.SameConfig(snapshot))   // fields were not edited while the test ran
                        {
                            Entry.LastDelayMs = result.Ok ? result.DelayMs : -1;
                            Entry.LastStatus = result.Status;
                            Entry.LastError = result.Ok ? "" : result.Detail;
                            Entry.LastTestUtc = DateTime.Now.ToString("HH:mm:ss");
                        }
                        _result.ForeColor = result.Ok ? Color.FromArgb(24, 120, 50) : Color.FromArgb(180, 40, 40);
                        _result.Text = (result.Ok ? L.T("کار کرد", "works") : L.T("کار نکرد", "failed")) + " • " + result.Status +
                                       (result.DelayMs > 0 ? " • " + L.N(result.DelayMs) + " ms" : "") +
                                       Environment.NewLine + result.Detail +
                                       (snapshot.CanCarryGame ? "" : Environment.NewLine + L.T("این نوع نمی‌تواند ترافیک بازی را حمل کند.", "this kind cannot carry the game traffic."));
                    });
                }
                catch { }
            });
            thread.IsBackground = true;
            thread.Start();
        }
    }
}

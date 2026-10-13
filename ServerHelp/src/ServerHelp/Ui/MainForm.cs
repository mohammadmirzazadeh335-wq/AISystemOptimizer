using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using ServerHelp.Core;
using ServerHelp.Mc;
using ServerHelp.Net;
using ServerHelp.Orchestration;
using ServerHelp.Sys;
using ServerHelp.Tunnel;

namespace ServerHelp.Ui
{
    public sealed class MainForm : Form
    {
        private readonly AppSettings _settings;
        private readonly LaunchPipeline _pipeline = new LaunchPipeline();

        private SHTabs _tabs;
        private SHHeader _header;
        private SHGauge _gaugePing, _gaugeRoute, _gaugeTunnel;
        private SHProgress _runProgress;
        private ComboBox _versionCombo;
        private ComboBox _serverCombo;
        private TextBox _nicknameBox;
        private SHButton _playButton;
        private Button _stopButton;
        private Label _statusLabel;
        private Label _bannerLabel;
        private Label _timerLabel;
        private Label _pingLabel;
        private ListView _stepList;
        private ListView _serverList;
        private ListView _versionList;
        private TextBox _planBox;
        private string _planBuildingFor = "";      // keeps one preparation per version in flight
        private bool _routeBusy;                   // one route hunt at a time
        private bool _stabilityBusy;               // one measurement at a time (tests, stability, speed)
        private ListView _endpointList;
        private TextBox _logBox;
        private TextBox _versionsDirBox;
        private TextBox _gameDirBox;
        private CheckBox _chkOptimize, _chkPower, _chkTrim, _chkClose, _chkPriority, _chkTuneNetwork, _chkFirewall, _chkTimer;
        private CheckBox _chkAikar, _chkQuickPlay, _chkHosts, _chkKeepTunnel, _chkAutoRestore, _chkMinimize, _chkOpenGl;
        private CheckBox _chkTuningAsk;
        private bool _optimizerBusy;               // only one "tune the system now" at a time
        private CheckBox _chkDnsInTunnel;
        private CheckBox _chkFragment;
        private NumericUpDown _chainCount;
        private NumericUpDown _retestMinutes;
        private System.Windows.Forms.Timer _retestTimer;
        private System.Windows.Forms.Timer _startupRetest;
        private ComboBox _tunnelCombo;
        private NumericUpDown _heapBox, _endpointBox;
        private TextBox _extraJvmBox;
        private Label _serverInfoLabel;
        private Label _tunnelInfoLabel;

        // ---- the connections tab
        private ListView _connectionList;
        private ComboBox _pinCombo;
        private CheckBox _chkFallback, _chkFailover, _chkKillSwitch;
        private NumericUpDown _connTimeoutBox;
        private Label _connectionSummary;
        private bool _connectionsBusy;
        private readonly List<string[]> _stepRows = new List<string[]>();  // kept across a window rebuild
        private int _pendingConnectionRow = -1;        // the row to reselect after a rebuild
        private int _pendingVersionIndex = -1;         // ditto for the version list
        private bool _serversBusy;                     // repopulating the server combo is not a choice

        private List<McVersion> _versions = new List<McVersion>();
        private List<WarpEndpoint> _lastScan = new List<WarpEndpoint>();
        private Thread _worker;
        private Stopwatch _runWatch;
        private readonly System.Windows.Forms.Timer _tick = new System.Windows.Forms.Timer();
        private string _gameDir = "";
        private string _javaPath = "";
        private bool _closing;

        public MainForm(AppSettings settings)
        {
            _settings = settings;
            Icon = UiKit.BuildIcon();
            Width = 1000;
            Height = 720;
            MinimumSize = new Size(880, 620);
            StartPosition = FormStartPosition.CenterScreen;
            DoubleBuffered = true;

            BuildUi();
            Shown += delegate { OnShownFirst(); };
            FormClosing += OnClosing;

            _tick.Interval = 250;
            _tick.Tick += delegate { Tick(); };
            _tick.Start();

            Log.Line += delegate (string line) { Ui(delegate { AppendLog(line); }); };
            _pipeline.Game.Exited += delegate (int code) { Ui(delegate { OnGameExited(code); }); };
            // Subscribed once: subscribing inside every run would add the same row twice.
            _pipeline.StepChanged += delegate (PipelineStep step)
            {
                Ui(delegate
                {
                    AddStepRow(step.Title, step.StateTextFa, step.Detail, step.State);
                    UpdateHeaderPills();
                });
            };
            _pipeline.Progress += delegate (string message) { Ui(delegate { SetStatus(message); }); };
            _pipeline.Finished += delegate (LaunchReport report) { Ui(delegate { OnPipelineFinished(report); }); };
        }

        // ------------------------------------------------------------------ UI build

        private void BuildUi()
        {
            SuspendLayout();
            bool rtl = L.IsRtl;
            RightToLeft = rtl ? RightToLeft.Yes : RightToLeft.No;
            RightToLeftLayout = rtl;
            Font = UiKit.UiFont(9.75f, false);
            Text = L.T("Server Help — دستیار سرور ماینکرفت", "Server Help — Minecraft server helper");
            BackColor = Theme.Background;

            // a language switch rebuilds the whole window: come back to the tab the user was on, and
            // to the row of the connections table, instead of dropping them at the top of the app
            int keepTab = _tabs != null ? _tabs.SelectedIndex : 0;
            if (_connectionList != null && _connectionList.SelectedIndices.Count > 0)
                _pendingConnectionRow = _connectionList.SelectedIndices[0];
            if (_versionCombo != null && _versionCombo.SelectedIndex >= 0)
                _pendingVersionIndex = _versionCombo.SelectedIndex;
            while (Controls.Count > 0) Controls[0].Dispose();

            // Docking works out when the Fill control is added first, then the Top/Bottom ones.
            _tabs = new SHTabs();
            _tabs.Dock = DockStyle.Fill;
            Controls.Add(_tabs);

            _header = new SHHeader();
            _header.Title = "Server Help";
            _header.Subtitle = L.T("شبکه را تشخیص می‌دهد، کم‌پینگ‌ترین مسیر را می‌سازد، سیستم را بهینه می‌کند و بازی را اجرا می‌کند",
                                   "detects the network, builds the lowest ping route, tunes the system and launches the game");
            _header.Right1 = L.T("شبکه: بررسی نشده", "network: unchecked");
            _header.Right1Color = Theme.Warn;
            _header.Right2 = L.T("تونل: خاموش", "tunnel: off");
            _header.Right2Color = Theme.SubText;
            Controls.Add(_header);

            _tabs.TabPages.Add(BuildHomeTab());
            _tabs.TabPages.Add(BuildServersTab());
            _tabs.TabPages.Add(BuildConnectionsTab());
            _tabs.TabPages.Add(BuildNetworkTab());
            _tabs.TabPages.Add(BuildOptimizeTab());
            _tabs.TabPages.Add(BuildVersionsTab());
            _tabs.TabPages.Add(BuildSettingsTab());
            _tabs.TabPages.Add(BuildLogTab());

            if (keepTab > 0 && keepTab < _tabs.TabPages.Count) _tabs.SelectedIndex = keepTab;

            var footer = new SHPanel();
            footer.Dock = DockStyle.Bottom;
            footer.Height = 34;
            footer.Radius = 0;
            footer.ShowStripe = false;
            footer.Padding = new Padding(10, 0, 10, 0);
            footer.BackColor = Color.FromArgb(0xFA, 0xFB, 0xFD);
            Controls.Add(footer);
            footer.BringToFront();

            _statusLabel = new Label();
            _statusLabel.Text = L.T("آماده", "ready");
            _statusLabel.AutoSize = true;
            _statusLabel.ForeColor = Theme.SubText;
            _statusLabel.Location = new Point(12, 9);
            footer.Controls.Add(_statusLabel);

            _pingLabel = new Label();
            _pingLabel.AutoSize = true;
            _pingLabel.ForeColor = Theme.SubText;
            _pingLabel.Location = new Point(430, 9);
            footer.Controls.Add(_pingLabel);

            _timerLabel = new Label();
            _timerLabel.AutoSize = true;
            _timerLabel.ForeColor = Theme.SubText;
            _timerLabel.Location = new Point(710, 9);
            footer.Controls.Add(_timerLabel);

            ResumeLayout(true);
            RefreshVersions();
            RefreshServerList();
            RefreshConnections();
            Theme.Apply(this);
            // Apply puts every text box on the body font, so the log's fixed width face is set again
            if (_logBox != null) _logBox.Font = UiKit.MonoFont(9f);
            UpdateHeaderPills();
            UpdatePlanPreview();
            ConnectionRoute.FragmentTlsByDefault = _settings.FragmentTls;
            RestartRetestTimer();
            RetestStaleAtStartup();
        }

        /// <summary>Keeps the chips in the header honest about the current state.</summary>
        private void UpdateHeaderPills()
        {
            if (_header == null) return;
            LaunchReport report = _pipeline.Report;
            bool checkedNetwork = report.Strategy.Length > 0;

            string network;
            Color networkColor;
            if (!checkedNetwork)
            {
                network = L.T("شبکه: بررسی نشده", "network: unchecked");
                networkColor = Theme.Warn;
            }
            else if (report.Strategy == "direct")
            {
                network = L.T("شبکه: مسیر مستقیم سالم", "network: direct works") +
                          (report.DirectPing > 0 ? " • " + L.N(report.DirectPing) + " ms" : "");
                networkColor = Theme.Good;
            }
            else
            {
                network = L.T("شبکه: مسیر مستقیم فیلتر شده", "network: direct is filtered") +
                          (report.DirectPing > 0 ? " • " + L.N(report.DirectPing) + " ms" : "");
                networkColor = Theme.Info;
            }

            string tunnel = report.TunnelUp
                ? L.T("تونل: فعال", "tunnel: up") +
                  (report.ConnectionUsed.Length > 0 ? " • " + report.ConnectionUsed : "") +
                  (report.TunnelPing > 0 ? " • " + L.N(report.TunnelPing) + " ms" : "")
                : L.T("تونل: خاموش", "tunnel: off");

            _header.Right1 = network;
            _header.Right1Color = networkColor;
            _header.Right2 = tunnel;
            _header.Right2Color = report.TunnelUp ? Theme.Good : Theme.SubText;
            _header.Invalidate();

            if (_gaugePing != null)
            {
                int ping = report.TunnelPing > 0 ? report.TunnelPing : report.DirectPing;
                _gaugePing.Unknown = ping <= 0;
                _gaugePing.Unit = "ms";
                _gaugePing.Caption = report.TunnelPing > 0 ? L.T("پینگ از داخل تونل", "ping inside the tunnel")
                                                           : L.T("پینگ سرور بازی", "game server ping");
                _gaugePing.Note = ping > 0 ? (ping < 120 ? L.T("عالی", "great") : (ping < 220 ? L.T("قابل قبول", "fine") : L.T("بالا", "high"))) : "";
                _gaugePing.RingColor = ping <= 0 ? Theme.SubText : (ping < 120 ? Theme.Good : (ping < 220 ? Theme.Warn : Theme.Bad));
                _gaugePing.Value = ping <= 0 ? 0f : Math.Max(0.05f, Math.Min(1f, 1f - Math.Min(400, ping) / 400f));
                _gaugePing.Invalidate();
            }

            if (_gaugeRoute != null)
            {
                string route = report.Strategy.Length == 0 ? "—" : report.Strategy;
                _gaugeRoute.Unit = route;
                _gaugeRoute.Caption = L.T("مسیر انتخابی", "chosen route");
                _gaugeRoute.Unknown = report.Strategy.Length == 0;
                _gaugeRoute.Value = report.Strategy == "direct" ? 1f
                                  : (report.Strategy == "none" ? 0.15f : 0.75f);
                _gaugeRoute.RingColor = report.Strategy == "direct" ? Theme.Good : Theme.Info;
                _gaugeRoute.Note = report.ConnectionUsed.Length > 0
                    ? report.ConnectionUsed + (report.ConnectionDelayMs > 0 ? " • " + L.N(report.ConnectionDelayMs) + " ms" : "")
                    : "";
                _gaugeRoute.Invalidate();
            }

            if (_gaugeTunnel != null)
            {
                _gaugeTunnel.Unknown = !report.TunnelUp;
                _gaugeTunnel.Caption = L.T("تونل", "tunnel");
                _gaugeTunnel.Unit = report.TunnelUp
                    ? (report.ProxyOnlyMode ? L.T("پروکسی محلی", "local proxy") : "TUN")
                    : L.T("خاموش", "off");
                _gaugeTunnel.Value = report.TunnelUp ? 1f : 0f;
                _gaugeTunnel.RingColor = report.TunnelUp ? Theme.Good : Theme.SubText;
                _gaugeTunnel.Note = report.HostsApplied ? L.T("hosts ثبت شده", "hosts pinned") : "";
                _gaugeTunnel.Invalidate();
            }
        }

        private TabPage BuildConnectionsTab()
        {
            var page = new TabPage(L.T("اتصالات", "Connections"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("اتصالات — هر راهی که بازی می‌تواند از آن رد شود", "Connections — every route the game can use");

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Top;
            // rows of buttons that wrap: the bar has to grow with them, or the last row is simply
            // cut off in a narrower window (that is how "Load from file" and "Subscription link"
            // ended up half invisible)
            buttons.AutoSize = true;
            buttons.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            buttons.FlowDirection = FlowDirection.LeftToRight;

            var add = new Button(); add.Text = L.T("افزودن", "Add"); add.Width = 100;
            add.Click += delegate { EditConnection(null); };
            var edit = new Button(); edit.Text = L.T("ویرایش", "Edit"); edit.Width = 100;
            edit.Click += delegate { EditConnection(SelectedConnection()); };
            var remove = new Button(); remove.Text = L.T("حذف", "Remove"); remove.Width = 100;
            remove.Click += delegate { RemoveConnection(); };
            var toggle = new Button(); toggle.Text = L.T("روشن/خاموش", "Enable / disable"); toggle.Width = 140;
            toggle.Click += delegate { ToggleConnection(); };
            var testOne = new Button(); testOne.Text = L.T("تست انتخاب‌شده", "Test selected"); testOne.Width = 150;
            testOne.Click += delegate { TestConnections(false); };
            var testAll = new Button(); testAll.Text = L.T("تست همه و گرفتن تأخیر", "Test all and take delays"); testAll.Width = 210;
            testAll.Click += delegate { TestConnections(true); };
            var import = new Button(); import.Text = L.T("افزودن دسته‌ای", "Import many"); import.Width = 140;
            import.Click += delegate { ImportConnections(); };
            var up = new Button(); up.Text = L.T("بالا", "Up"); up.Width = 70;
            up.Click += delegate { MoveConnection(-1); };
            var down = new Button(); down.Text = L.T("پایین", "Down"); down.Width = 70;
            down.Click += delegate { MoveConnection(1); };
            var clean = new Button(); clean.Text = L.T("استفاده از خودکار", "Use automatic"); clean.Width = 150;
            clean.Click += delegate { PinConnection(""); };

            buttons.Controls.Add(add);
            buttons.Controls.Add(edit);
            buttons.Controls.Add(remove);
            buttons.Controls.Add(toggle);
            buttons.Controls.Add(testOne);
            buttons.Controls.Add(testAll);
            buttons.Controls.Add(import);
            buttons.Controls.Add(up);
            buttons.Controls.Add(down);
            var duplicate = new Button(); duplicate.Text = L.T("کپی", "Duplicate"); duplicate.Width = 90;
            duplicate.Click += delegate { DuplicateConnection(); };
            var sort = new Button(); sort.Text = L.T("ترتیب: تأخیر", "Sort: delay"); sort.Width = 130;
            sort.Click += delegate { SortConnectionsByDelay(); };
            var export = new Button(); export.Text = L.T("ذخیره در فایل", "Save to file"); export.Width = 140;
            export.Click += delegate { ExportConnections(); };
            var importFile = new Button(); importFile.Text = L.T("خواندن از فایل", "Load from file"); importFile.Width = 150;
            importFile.Click += delegate { LoadConnectionsFromFile(); };

            buttons.Controls.Add(clean);
            buttons.Controls.Add(duplicate);
            buttons.Controls.Add(sort);
            buttons.Controls.Add(export);
            buttons.Controls.Add(importFile);
            card.Controls.Add(buttons);

            // second row: what a filtered line needs - find out what is broken, then measure the
            // routes properly (jitter, loss, throughput) instead of trusting one number
            var measuring = new FlowLayoutPanel();
            measuring.Dock = DockStyle.Top;
            // rows of buttons that wrap: the bar has to grow with them, or the last row is simply
            // cut off in a narrower window (that is how "Load from file" and "Subscription link"
            // ended up half invisible)
            measuring.AutoSize = true;
            measuring.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            measuring.FlowDirection = FlowDirection.LeftToRight;

            var diagnose = new Button();
            diagnose.Text = L.T("تشخیص خط (اینترنت ملی)", "Diagnose the line (national internet)");
            diagnose.Width = 260;
            diagnose.Click += delegate { DiagnoseLine(); };
            measuring.Controls.Add(diagnose);

            var stability = new Button();
            stability.Text = L.T("تست پایداری انتخاب‌شده", "Stability test (selected)");
            stability.Width = 210;
            stability.Click += delegate { StabilityTest(false); };
            measuring.Controls.Add(stability);

            var stabilityAll = new Button();
            stabilityAll.Text = L.T("پایداری همه", "Stability for all");
            stabilityAll.Width = 150;
            stabilityAll.Click += delegate { StabilityTest(true); };
            measuring.Controls.Add(stabilityAll);

            var speed = new Button();
            speed.Text = L.T("تست سرعت انتخاب‌شده", "Speed test (selected)");
            speed.Width = 190;
            speed.Click += delegate { SpeedTestSelected(); };
            measuring.Controls.Add(speed);

            var subscription = new Button();
            subscription.Text = L.T("اشتراک از لینک", "Subscription link");
            subscription.Width = 160;
            subscription.Click += delegate { ImportSubscription(); };
            measuring.Controls.Add(subscription);

            card.Controls.Add(measuring);

            // third row: the Telegram side of things, because an MTProxy needs its own tools
            var telegram = new FlowLayoutPanel();
            telegram.Dock = DockStyle.Top;
            // rows of buttons that wrap: the bar has to grow with them, or the last row is simply
            // cut off in a narrower window (that is how "Load from file" and "Subscription link"
            // ended up half invisible)
            telegram.AutoSize = true;
            telegram.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            telegram.FlowDirection = FlowDirection.LeftToRight;

            var verify = new Button();
            verify.Text = L.T("تست واقعی MTProto", "Verify MTProto for real");
            verify.Width = 190;
            verify.Click += delegate { VerifyMtprotoSelected(); };
            telegram.Controls.Add(verify);

            var rank = new Button();
            rank.Text = L.T("رتبه‌بندی دیتاسنترهای تلگرام", "Rank Telegram data centres");
            rank.Width = 220;
            rank.Click += delegate { RankTelegramDcs(); };
            telegram.Controls.Add(rank);

            var optimise = new Button();
            optimise.Text = L.T("بهینه‌سازی مسیر بازی (پینگ واقعی)", "Optimise game route (real ping)");
            optimise.Width = 240;
            optimise.Click += delegate { OptimiseGameRoute(); };
            telegram.Controls.Add(optimise);

            var dnsTest = new Button();
            dnsTest.Text = L.T("تست DNS داخل تونل", "Test DNS inside the tunnel");
            dnsTest.Width = 200;
            dnsTest.Click += delegate { TestDnsThroughTunnel(); };
            telegram.Controls.Add(dnsTest);

            var copyLink = new Button();
            copyLink.Text = L.T("کپی لینک تلگرام", "Copy tg:// link");
            copyLink.Width = 160;
            copyLink.Click += delegate { CopyTelegramLink(); };
            telegram.Controls.Add(copyLink);

            var tgHint = UiKit.Sub(L.T("پروکسی MTProto فقط ترافیک تلگرام را حمل می‌کند؛ برای بازی از WARP یا پروکسی‌های دیگر استفاده کنید.",
                                       "an MTProxy only carries Telegram traffic; for the game use WARP or another proxy"));
            tgHint.AutoSize = true;
            tgHint.Height = 30;
            telegram.Controls.Add(tgHint);
            card.Controls.Add(telegram);

            var options = new FlowLayoutPanel();
            options.Dock = DockStyle.Top;
            // rows of buttons that wrap: the bar has to grow with them, or the last row is simply
            // cut off in a narrower window (that is how "Load from file" and "Subscription link"
            // ended up half invisible)
            options.AutoSize = true;
            options.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            options.FlowDirection = FlowDirection.LeftToRight;

            var pinLabel = UiKit.Sub(L.T("مسیر ثابت بازی:", "Pinned game route:"));
            pinLabel.Width = 130;
            pinLabel.Height = 30;
            options.Controls.Add(pinLabel);

            _pinCombo = new ComboBox();
            _pinCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _pinCombo.Width = 300;
            if (_versionCombo != null) _versionCombo.SelectedIndexChanged += delegate { UpdatePlanPreview(); };
            _pinCombo.SelectedIndexChanged += delegate
            {
                if (_connectionsBusy) return;
                if (_pinCombo.SelectedIndex < 0) return;
                PinConnection(_pinCombo.SelectedIndex == 0 ? "" : _pinCombo.Items[_pinCombo.SelectedIndex].ToString());
            };
            options.Controls.Add(_pinCombo);

            _chkDnsInTunnel = new CheckBox();
            _chkDnsInTunnel.Text = L.T("DNS از داخل تونل (برای اینترنت ملی که DNS ندارد)",
                                       "DNS inside the tunnel (for lines where DNS does not work)");
            _chkDnsInTunnel.AutoSize = true;
            _chkDnsInTunnel.Checked = _settings.DnsThroughTunnel;
            _chkDnsInTunnel.CheckedChanged += delegate
            {
                _settings.DnsThroughTunnel = _chkDnsInTunnel.Checked;
                SettingsStore.Save(_settings);
                SetStatus(_chkDnsInTunnel.Checked
                    ? L.T("نام‌ها از داخل تونل حل می‌شوند", "names will be resolved inside the tunnel")
                    : L.T("نام‌ها با DNS سیستم حل می‌شوند", "names will be resolved by the system DNS"));
            };
            options.Controls.Add(_chkDnsInTunnel);

            var chainLabel = UiKit.Sub(L.T("زنجیره رله:", "relay chains:"));
            chainLabel.Width = 90;
            chainLabel.Height = 30;
            options.Controls.Add(chainLabel);

            _chkFragment = new CheckBox();
            _chkFragment.Text = L.T("تکه‌تکه‌کردن TLS (برای خطی که SNI را می‌بندد)",
                                    "Fragment TLS (for lines that block on SNI)");
            _chkFragment.AutoSize = true;
            _chkFragment.Checked = _settings.FragmentTls;
            _chkFragment.CheckedChanged += delegate
            {
                _settings.FragmentTls = _chkFragment.Checked;
                ConnectionRoute.FragmentTlsByDefault = _chkFragment.Checked;
                SettingsStore.Save(_settings);
                SetStatus(_chkFragment.Checked
                    ? L.T("هندشیک TLS مسیرها تکه‌تکه می‌شود", "route TLS handshakes will be fragmented")
                    : L.T("هندشیک TLS عادی است", "route TLS handshakes are normal"));
            };
            options.Controls.Add(_chkFragment);

            var retestLabel = UiKit.Sub(L.T("تست دوره‌ای (دقیقه):", "retest every (min):"));
            retestLabel.Width = 140;
            retestLabel.Height = 30;
            options.Controls.Add(retestLabel);

            _retestMinutes = new NumericUpDown();
            _retestMinutes.Minimum = 0;
            _retestMinutes.Maximum = 720;
            _retestMinutes.Value = Math.Max(0, Math.Min(720, _settings.RetestMinutes));
            _retestMinutes.Width = 60;
            _retestMinutes.ValueChanged += delegate
            {
                _settings.RetestMinutes = (int)_retestMinutes.Value;
                SettingsStore.Save(_settings);
                RestartRetestTimer();
            };
            options.Controls.Add(_retestMinutes);

            _chainCount = new NumericUpDown();
            _chainCount.Minimum = 0;
            _chainCount.Maximum = 12;
            _chainCount.Value = Math.Max(0, Math.Min(12, _settings.OptimiseChains));
            _chainCount.Width = 60;
            _chainCount.ValueChanged += delegate
            {
                _settings.OptimiseChains = (int)_chainCount.Value;
                SettingsStore.Save(_settings);
            };
            options.Controls.Add(_chainCount);

            _chkFallback = new CheckBox();
            _chkFallback.Text = L.T("اگر مسیر انتخابی کار نکرد، مسیر خودکار امتحان شود", "If the chosen route fails, use the automatic one");
            _chkFallback.AutoSize = true;
            _chkFallback.Checked = _settings.AllowRouteFallback;
            _chkFallback.CheckedChanged += delegate { _settings.AllowRouteFallback = _chkFallback.Checked; SettingsStore.Save(_settings); };
            options.Controls.Add(_chkFallback);

            _chkFailover = new CheckBox();
            _chkFailover.Text = L.T("پروکسی‌های سالم در یک گروه با انتخاب سریع‌ترین", "Group healthy proxies and keep the fastest");
            _chkFailover.AutoSize = true;
            _chkFailover.Checked = _settings.ProxyFailover;
            _chkFailover.CheckedChanged += delegate { _settings.ProxyFailover = _chkFailover.Checked; SettingsStore.Save(_settings); };
            options.Controls.Add(_chkFailover);

            _chkKillSwitch = new CheckBox();
            _chkKillSwitch.Text = L.T("قطع امن (kill-switch): اگر تونل قطع شد، بازی بسته و آدرس سیاه‌چاله شود",
                                      "Kill switch: if the tunnel dies, close the game and blackhole the address");
            _chkKillSwitch.AutoSize = true;
            _chkKillSwitch.Checked = _settings.KillSwitch;
            _chkKillSwitch.CheckedChanged += delegate { _settings.KillSwitch = _chkKillSwitch.Checked; SettingsStore.Save(_settings); };
            options.Controls.Add(_chkKillSwitch);

            var timeoutLabel = UiKit.Sub(L.T("مهلت هر تست (میلی‌ثانیه):", "Test timeout (ms):"));
            timeoutLabel.Width = 150;
            timeoutLabel.Height = 30;
            options.Controls.Add(timeoutLabel);

            _connTimeoutBox = new NumericUpDown();
            _connTimeoutBox.Minimum = 700;
            _connTimeoutBox.Maximum = 20000;
            _connTimeoutBox.Increment = 500;
            _connTimeoutBox.Width = 100;
            _connTimeoutBox.Value = Math.Min(20000, Math.Max(700, _settings.ConnectionTestTimeoutMs));
            _connTimeoutBox.ValueChanged += delegate { _settings.ConnectionTestTimeoutMs = (int)_connTimeoutBox.Value; SettingsStore.Save(_settings); };
            options.Controls.Add(_connTimeoutBox);

            card.Controls.Add(options);

            _connectionSummary = UiLabel("—");
            _connectionSummary.Dock = DockStyle.Bottom;
            // one line at a wide window, two at a narrow one: give it the room, and a tooltip rather
            // than a silently cut sentence
            _connectionSummary.Height = 48;
            _connectionSummary.AutoEllipsis = true;
            card.Controls.Add(_connectionSummary);

            _connectionList = new ListView();
            _connectionList.Dock = DockStyle.Fill;
            _connectionList.View = View.Details;
            _connectionList.FullRowSelect = true;
            _connectionList.GridLines = true;
            _connectionList.MultiSelect = false;
            _connectionList.Columns.Add(L.T("نام", "Name"), 170);
            _connectionList.Columns.Add(L.T("نوع", "Kind"), 150);
            _connectionList.Columns.Add(L.T("مقصد", "Target"), 230);
            _connectionList.Columns.Add(L.T("تأخیر", "Delay"), 90);
            _connectionList.Columns.Add(L.T("چه چیزی از آن رد می‌شود", "Carries"), 120);
            _connectionList.Columns.Add(L.T("کیفیت (پایداری)", "Quality (stability)"), 190);
            _connectionList.Columns.Add(L.T("وضعیت", "Status"), 240);
            _connectionList.Columns.Add(L.T("آخرین تست", "Last test"), 110);
            _connectionList.Columns.Add(L.T("فعال", "On"), 60);
            _connectionList.DoubleClick += delegate { EditConnection(SelectedConnection()); };
            card.Controls.Add(_connectionList);

            // Dock layout runs from the back of the z-order to the front: the first control it reaches
            // takes the outermost strip. Bringing the rows forward in the order they are meant to be
            // read - the buttons, the measuring row, the Telegram row, the options, the summary bar and
            // then the table that fills what is left - is the only thing that decides their order.
            buttons.BringToFront();
            measuring.BringToFront();
            telegram.BringToFront();
            options.BringToFront();
            _connectionSummary.BringToFront();
            _connectionList.BringToFront();

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildHomeTab()
        {
            var page = new TabPage(L.T("خانه و اجرا", "Home & Play"));
            page.Padding = new Padding(12);

            var top = new SHPanel();
            top.Dock = DockStyle.Top;
            top.Height = 360;
            top.Title = L.T("خانه و اجرا", "Home and play");

            // Everything below is hand-placed, so the width it is placed against is worked out here and
            // the wide controls are anchored to both edges: nothing is ever wider than the panel (the
            // play button used to run past the right edge and the plan box used to sit on top of the
            // nickname box and the progress bar).
            int panelWidth = Math.Max(820, ClientSize.Width - 40);
            int rightX = 456;                        // the gauges end here
            int rightW = panelWidth - rightX - 12;   // the plan box and the play button fill this

            var lblServer = UiKit.Sub(L.T("سرور:", "Server:"));
            lblServer.Location = new Point(12, 80);
            top.Controls.Add(lblServer);

            _serverCombo = new ComboBox();
            _serverCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _serverCombo.Location = new Point(12, 100);
            _serverCombo.Width = 300;
            _serverCombo.SelectedIndexChanged += delegate
            {
                if (_serversBusy) return;   // this change came from repopulating the list
                if (_serverCombo.SelectedIndex >= 0) SelectServer(_serverCombo.SelectedIndex);
            };
            top.Controls.Add(_serverCombo);

            var lblVersion = UiKit.Sub(L.T("نسخه ماینکرفت:", "Minecraft version:"));
            lblVersion.Location = new Point(330, 80);
            top.Controls.Add(lblVersion);

            _versionCombo = new ComboBox();
            _versionCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _versionCombo.Location = new Point(330, 100);
            _versionCombo.Width = 280;
            top.Controls.Add(_versionCombo);

            var checkButton = new Button();
            checkButton.Text = L.T("بررسی سرور", "Check server");
            checkButton.Height = 30;
            checkButton.Width = 150;
            checkButton.Location = new Point(630, 98);
            checkButton.Click += delegate { CheckServerAsync(); };
            top.Controls.Add(checkButton);

            // what optimisation this version will get; filled as soon as a version is picked
            _planBox = new TextBox();
            _planBox.Multiline = true;
            _planBox.ReadOnly = true;
            _planBox.ScrollBars = ScrollBars.Vertical;
            _planBox.BorderStyle = BorderStyle.None;
            _planBox.BackColor = Theme.Surface;
            _planBox.ForeColor = Theme.Text;
            _planBox.Font = UiKit.UiFont(9f, false);
            _planBox.Location = new Point(rightX, 192);
            _planBox.Size = new Size(rightW, 96);
            _planBox.TabStop = false;
            _planBox.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            top.Controls.Add(_planBox);

            // the three dials: ping, chosen route, tunnel state
            _gaugePing = new SHGauge();
            _gaugePing.Location = new Point(12, 200);
            _gaugePing.Size = new Size(144, 150);   // ring + caption + note, all inside the control
            _gaugePing.Unknown = true;
            _gaugePing.Unit = "ms";
            _gaugePing.Caption = L.T("پینگ سرور بازی", "game server ping");
            top.Controls.Add(_gaugePing);

            _gaugeRoute = new SHGauge();
            _gaugeRoute.Location = new Point(160, 200);
            _gaugeRoute.Size = new Size(144, 150);
            _gaugeRoute.Unknown = true;
            _gaugeRoute.Unit = "—";
            _gaugeRoute.Caption = L.T("مسیر انتخابی", "chosen route");
            _gaugeRoute.RingColor = Theme.Info;
            top.Controls.Add(_gaugeRoute);

            _gaugeTunnel = new SHGauge();
            _gaugeTunnel.Location = new Point(308, 200);
            _gaugeTunnel.Size = new Size(144, 150);
            _gaugeTunnel.Unknown = true;
            _gaugeTunnel.Unit = L.T("خاموش", "off");
            _gaugeTunnel.Caption = L.T("تونل", "tunnel");
            top.Controls.Add(_gaugeTunnel);

            _runProgress = new SHProgress();
            _runProgress.Location = new Point(12, 44);
            _runProgress.Width = panelWidth - 24 - 170;
            _runProgress.Height = 28;
            _runProgress.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            _runProgress.Caption = L.T("آماده — دکمه اجرا را بزنید", "ready - press play");
            _runProgress.BarColor = Theme.Accent;
            top.Controls.Add(_runProgress);

            var lblNick = UiKit.Sub(L.T("نام بازیکن (آفلاین):", "Player name (offline):"));
            lblNick.Location = new Point(12, 130);
            top.Controls.Add(lblNick);

            _nicknameBox = new TextBox();
            _nicknameBox.Location = new Point(12, 150);
            _nicknameBox.Width = 240;
            _nicknameBox.Text = _settings.Nickname;
            _nicknameBox.TextChanged += delegate { _settings.Nickname = _nicknameBox.Text.Trim(); };
            _nicknameBox.Validated += delegate { SettingsStore.Save(_settings); };
            top.Controls.Add(_nicknameBox);

            _playButton = new SHButton();
            _playButton.Text = L.T("بهینه‌سازی و اجرای بازی", "Optimise and play");
            _playButton.Accent = true;
            _playButton.Font = UiKit.UiFont(11.5f, true);
            _playButton.Height = 46;
            _playButton.Width = rightW;
            _playButton.Location = new Point(rightX, 296);
            _playButton.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            _playButton.Click += delegate { StartPipeline(); };
            top.Controls.Add(_playButton);

            _stopButton = new Button();
            _stopButton.Text = L.T("توقف و بازگردانی", "Stop and restore");
            _stopButton.Height = 30;
            _stopButton.Width = 150;
            _stopButton.Location = new Point(panelWidth - 12 - 150, 44);
            _stopButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            _stopButton.Enabled = false;
            _stopButton.Click += delegate { StopEverything(); };
            top.Controls.Add(_stopButton);

            _serverInfoLabel = new Label();
            _serverInfoLabel.AutoSize = false;
            _serverInfoLabel.Width = panelWidth - 276;
            _serverInfoLabel.Height = 44;
            _serverInfoLabel.Location = new Point(264, 148);
            _serverInfoLabel.AutoEllipsis = true;      // a long MOTD line is cut, never spilling over
            _serverInfoLabel.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            _serverInfoLabel.Text = "—";
            top.Controls.Add(_serverInfoLabel);

            var steps = new SHPanel();
            steps.Dock = DockStyle.Fill;
            steps.Title = L.T("مراحل (کمتر از یک دقیقه)", "steps (under one minute)");

            _stepList = new ListView();
            _stepList.Dock = DockStyle.Fill;
            _stepList.View = View.Details;
            _stepList.FullRowSelect = true;
            _stepList.GridLines = true;
            _stepList.Columns.Add(L.T("مرحله", "Step"), 320);
            _stepList.Columns.Add(L.T("وضعیت", "State"), 90);
            _stepList.Columns.Add(L.T("جزئیات", "Detail"), 430);
            steps.Controls.Add(_stepList);

            // whatever the launch table already showed is put back after a rebuild
            foreach (string[] row in _stepRows)
            {
                if (row.Length < 4) continue;
                StepState state;
                if (!Enum.TryParse<StepState>(row[3], out state)) state = StepState.Skip;
                DrawStepRow(row[0], row[1], row[2], state);
            }

            page.Controls.Add(steps);
            page.Controls.Add(top);
            return page;
        }

        private TabPage BuildServersTab()
        {
            var page = new TabPage(L.T("سرورها", "Servers"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("سرورها — لیست خودتان", "Servers — your own list");

            _serverList = new ListView();
            _serverList.Dock = DockStyle.Fill;
            _serverList.View = View.Details;
            _serverList.FullRowSelect = true;
            _serverList.GridLines = true;
            _serverList.Columns.Add(L.T("نام", "Name"), 160);
            _serverList.Columns.Add(L.T("آدرس", "Address"), 260);
            _serverList.Columns.Add(L.T("IP جایگزین", "Fallback IP"), 160);
            _serverList.Columns.Add(L.T("فعال", "Active"), 80);
            card.Controls.Add(_serverList);

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 46;
            buttons.FlowDirection = FlowDirection.LeftToRight;

            var add = new Button(); add.Text = L.T("افزودن", "Add"); add.Width = 100;
            add.Click += delegate { EditServer(null); };
            var edit = new Button(); edit.Text = L.T("ویرایش", "Edit"); edit.Width = 100;
            edit.Click += delegate { EditServer(SelectedServer()); };
            var remove = new Button(); remove.Text = L.T("حذف", "Remove"); remove.Width = 100;
            remove.Click += delegate { RemoveServer(); };
            var activate = new Button(); activate.Text = L.T("انتخاب", "Make active"); activate.Width = 130;
            activate.Click += delegate { ActivateServer(); };

            buttons.Controls.Add(add);
            buttons.Controls.Add(edit);
            buttons.Controls.Add(remove);
            buttons.Controls.Add(activate);
            card.Controls.Add(buttons);

            var hint = UiLabel(L.T("سرور پیش‌فرض: smp3.mcsh.io:11005 — می‌توانید هر سرور دیگری اضافه کنید؛" +
                                   " آدرس و پورت به‌صورت خودکار به تونل و hosts داده می‌شوند.",
                                   "Default server: smp3.mcsh.io:11005 — add any other server; its address and port " +
                                   "are wired into the tunnel and hosts automatically."));
            hint.Dock = DockStyle.Bottom;
            hint.Height = 48;          // the sentence wraps to two lines in a narrow window
            hint.AutoEllipsis = true;
            card.Controls.Add(hint);

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildNetworkTab()
        {
            var page = new TabPage(L.T("شبکه و تونل", "Network & tunnel"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("شبکه و DNS", "Network and DNS");

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Top;
            // rows of buttons that wrap: the bar has to grow with them, or the last row is simply
            // cut off in a narrower window (that is how "Load from file" and "Subscription link"
            // ended up half invisible)
            buttons.AutoSize = true;
            buttons.AutoSizeMode = AutoSizeMode.GrowAndShrink;

            var scan = new Button(); scan.Text = L.T("اسکن endpointهای WARP", "Scan WARP endpoints"); scan.Width = 210;
            scan.Click += delegate { ScanEndpointsAsync(); };
            var diag = new Button(); diag.Text = L.T("تست اتصال سرور", "Test server path"); diag.Width = 160;
            diag.Click += delegate { CheckServerAsync(); };
            var tunnel = new Button(); tunnel.Text = L.T("روشن/خاموش کردن تونل", "Toggle tunnel"); tunnel.Width = 170;
            tunnel.Click += delegate { ToggleTunnel(); };
            var clean = new Button(); clean.Text = L.T("پاک‌سازی (hosts/route)", "Clean up (hosts/route)"); clean.Width = 190;
            clean.Click += delegate { _pipeline.Shutdown(false); SetStatus(L.T("پاک‌سازی انجام شد", "cleanup done")); };
            var delays = new Button(); delays.Text = L.T("اندازه‌گیری تأخیر سرورها", "Measure server delays"); delays.Width = 200;
            delays.Click += delegate { MeasureEndpointDelays(); };

            buttons.Controls.Add(scan);
            buttons.Controls.Add(delays);
            buttons.Controls.Add(diag);
            buttons.Controls.Add(tunnel);
            buttons.Controls.Add(clean);
            card.Controls.Add(buttons);

            _tunnelInfoLabel = UiLabel("—");
            _tunnelInfoLabel.Dock = DockStyle.Top;
            _tunnelInfoLabel.Height = 48;
            card.Controls.Add(_tunnelInfoLabel);

            _endpointList = new ListView();
            _endpointList.Dock = DockStyle.Fill;
            _endpointList.View = View.Details;
            _endpointList.FullRowSelect = true;
            _endpointList.GridLines = true;
            _endpointList.Columns.Add(L.T("آدرس", "Address"), 180);
            _endpointList.Columns.Add("ICMP", 90);
            _endpointList.Columns.Add("TCP 443", 110);
            _endpointList.Columns.Add(L.T("امتیاز", "Score"), 90);
            _endpointList.Columns.Add(L.T("تأخیر واقعی (پورت تونل)", "Real delay (tunnel port)"), 170);
            _endpointList.Columns.Add(L.T("تأخیر از داخل تونل", "Delay inside the tunnel"), 180);
            card.Controls.Add(_endpointList);

            // same rule here: without this the table is laid out first and the buttons are drawn over
            // its columns
            buttons.BringToFront();
            _tunnelInfoLabel.BringToFront();
            _endpointList.BringToFront();

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildOptimizeTab()
        {
            var page = new TabPage(L.T("بهینه‌سازی", "Optimisation"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("بهینه‌سازی سیستم (همه برگشت‌پذیر)", "System optimisation (all reversible)");

            var panel = new FlowLayoutPanel();
            panel.Dock = DockStyle.Fill;
            panel.FlowDirection = FlowDirection.TopDown;
            panel.WrapContents = false;
            panel.AutoScroll = true;

            _chkOptimize = Check(L.T("بهینه‌سازی سیستم هنگام اجرا", "Tune the system on launch"), _settings.OptimizeSystem, delegate (bool v) { _settings.OptimizeSystem = v; });
            _chkPower = Check(L.T("طرح انرژی حداکثر کارایی", "High performance power plan"), _settings.HighPerformancePowerPlan, delegate (bool v) { _settings.HighPerformancePowerPlan = v; });
            _chkTuneNetwork = Check(L.T("کاهش throttle شبکه + پاک‌کردن کش DNS", "Lower network throttling + flush DNS"), _settings.TuneNetwork, delegate (bool v) { _settings.TuneNetwork = v; });
            _chkFirewall = Check(L.T("قواعد فایروال برای بازی و تونل", "Firewall rules for the game and tunnel"), _settings.AddFirewallRules, delegate (bool v) { _settings.AddFirewallRules = v; });
            _chkTrim = Check(L.T("آزادسازی حافظه برنامه‌های بی‌کار", "Free idle applications' memory"), _settings.TrimMemory, delegate (bool v) { _settings.TrimMemory = v; });
            _chkClose = Check(L.T("بستن برنامه‌های سنگین پس‌زمینه (مرورگر، دیسکورد…)", "Close heavy background apps (browser, Discord…)"), _settings.CloseBackgroundApps, delegate (bool v) { _settings.CloseBackgroundApps = v; });
            _chkPriority = Check(L.T("اولویت بالا برای java/بازی", "High priority for java/game"), _settings.SetJavaPriority, delegate (bool v) { _settings.SetJavaPriority = v; });
            _chkTimer = Check(L.T("دقت تایمر ۱ میلی‌ثانیه‌ای", "1 ms system timer resolution"), _settings.TimerResolution, delegate (bool v) { _settings.TimerResolution = v; });

            _chkAikar = Check(L.T("فلاگ‌های بهینه‌سازی JVM (Aikar + حافظه)", "JVM tuning flags (Aikar + memory)"), _settings.UseAikarFlags, delegate (bool v) { _settings.UseAikarFlags = v; });
            _chkQuickPlay = Check(L.T("ورود خودکار به سرور هنگام اجرا", "Auto join the server on launch"), _settings.QuickPlay, delegate (bool v) { _settings.QuickPlay = v; });
            _chkHosts = Check(L.T("تثبیت آدرس سرور در فایل hosts", "Pin the server address in the hosts file"), _settings.UseHostsFile, delegate (bool v) { _settings.UseHostsFile = v; });
            _chkKeepTunnel = Check(L.T("نگه‌داشتن تونل بعد از بستن بازی", "Keep the tunnel after the game closes"), _settings.KeepTunnelAfterGame, delegate (bool v) { _settings.KeepTunnelAfterGame = v; });
            _chkAutoRestore = Check(L.T("بازگردانی تنظیمات هنگام خروج", "Restore settings on exit"), _settings.AutoRestoreOnExit, delegate (bool v) { _settings.AutoRestoreOnExit = v; });
            _chkMinimize = Check(L.T("کوچک‌کردن پنجره هنگام بازی", "Minimise the window while playing"), _settings.MinimizeWhilePlaying, delegate (bool v) { _settings.MinimizeWhilePlaying = v; });
            _chkTuningAsk = Check(L.T("قبل از تغییرات سیستم اجازه بگیر (توصیه‌شده)", "Ask before changing system settings (recommended)"),
                                  _settings.ConfirmTuning, delegate (bool v) { _settings.ConfirmTuning = v; });

            var heapLabel = UiKit.Sub(L.T("حداکثر حافظه بازی (مگابایت، ۰ = خودکار)", "Max game memory (MB, 0 = automatic)"));
            _heapBox = new NumericUpDown();
            _heapBox.Minimum = 0; _heapBox.Maximum = 32768; _heapBox.Increment = 512;
            _heapBox.Value = Math.Min(32768, Math.Max(0, _settings.MaxHeapMb));
            _heapBox.Width = 120;
            _heapBox.ValueChanged += delegate { _settings.MaxHeapMb = (int)_heapBox.Value; };

            var epLabel = UiKit.Sub(L.T("تعداد endpointهای WARP در گروه خودکار", "WARP endpoints inside the auto group"));
            _endpointBox = new NumericUpDown();
            _endpointBox.Minimum = 1; _endpointBox.Maximum = 24;
            _endpointBox.Value = Math.Min(24, Math.Max(1, _settings.MaxEndpoints));
            _endpointBox.Width = 80;
            _endpointBox.ValueChanged += delegate { _settings.MaxEndpoints = (int)_endpointBox.Value; };

            var modeLabel = UiKit.Sub(L.T("حالت شبکه", "Network mode"));
            _tunnelCombo = new ComboBox();
            _tunnelCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _tunnelCombo.Width = 320;
            _tunnelCombo.Items.Add(L.T("خودکار (تشخیص و انتخاب بهترین راه)", "Automatic (diagnose and pick)"));
            _tunnelCombo.Items.Add(L.T("همیشه تونل WARP", "Always use the WARP tunnel"));
            _tunnelCombo.Items.Add(L.T("فقط اصلاح DNS", "DNS fix only"));
            _tunnelCombo.Items.Add(L.T("دست نزن", "Do not touch"));
            _tunnelCombo.SelectedIndex = (int)_settings.Tunnel;
            _tunnelCombo.SelectedIndexChanged += delegate { _settings.Tunnel = (TunnelMode)_tunnelCombo.SelectedIndex; };

            var extraLabel = UiKit.Sub(L.T("فلگ‌های اضافی JVM", "Extra JVM flags"));
            _extraJvmBox = new TextBox();
            _extraJvmBox.Width = 420;
            _extraJvmBox.Text = _settings.ExtraJvmArgs;
            _extraJvmBox.TextChanged += delegate { _settings.ExtraJvmArgs = _extraJvmBox.Text.Trim(); };

            var runNow = new Button();
            runNow.Text = L.T("همین حالا بهینه‌سازی کن", "Run optimisation now");
            runNow.Width = 220;
            runNow.Click += delegate { RunOptimizerNow(); };

            var restore = new Button();
            restore.Text = L.T("بازگردانی همه تغییرات", "Restore everything");
            restore.Width = 220;
            restore.Click += delegate
            {
                if (_optimizerBusy)
                {
                    SetStatus(L.T("بهینه‌سازی در جریان است؛ چند لحظه بعد دوباره امتحان کنید",
                                  "an optimisation is running; try again in a moment"));
                    return;
                }
                _pipeline.Shutdown(false);
                SetStatus(L.T("تنظیمات سیستم بازگردانی شد", "system settings restored"));
            };

            _chkOpenGl = Check(L.T("خط لوله OpenGL جاوا (برای درایورهای اینتل)",
                                   "Java OpenGL pipeline (helps some Intel drivers)"),
                               _settings.OpenGlPipeline, delegate (bool v) { _settings.OpenGlPipeline = v; });

            // One column of fifteen switches all looks the same, so the tab is cut into four captions:
            // what happens to Windows, to the game, to the connection, and to the window.
            runNow.Margin = new Padding(3, 18, 3, 3);
            restore.Margin = runNow.Margin;
            var secSystem = UiKit.Section(L.T("سیستم و ویندوز", "Windows and the system"));
            var secGame = UiKit.Section(L.T("بازی و جاوا", "The game and Java"));
            var secNet = UiKit.Section(L.T("شبکه و تونل", "Network and the tunnel"));
            var secApp = UiKit.Section(L.T("رفتار برنامه", "How the app behaves"));
            var restoreHint = UiKit.Sub(L.T("هر تغییر بالا با «بازگردانی همه تغییرات» یا هنگام بستن برنامه (اگر روشن باشد) برمی‌گردد.",
                                            "Every change above is undone by \u201crestore everything\u201d or when the app closes, if that switch is on."));
            restoreHint.MaximumSize = new Size(760, 0);      // wraps instead of running off the card

            panel.Controls.Add(secSystem);
            panel.Controls.Add(_chkOptimize);
            panel.Controls.Add(_chkPower);
            panel.Controls.Add(_chkTuneNetwork);
            panel.Controls.Add(_chkFirewall);
            panel.Controls.Add(_chkTrim);
            panel.Controls.Add(_chkClose);
            panel.Controls.Add(_chkPriority);
            panel.Controls.Add(_chkTimer);

            panel.Controls.Add(secGame);
            panel.Controls.Add(_chkAikar);
            panel.Controls.Add(_chkOpenGl);
            panel.Controls.Add(heapLabel);
            panel.Controls.Add(_heapBox);
            panel.Controls.Add(extraLabel);
            panel.Controls.Add(_extraJvmBox);
            panel.Controls.Add(_chkQuickPlay);

            panel.Controls.Add(secNet);
            panel.Controls.Add(modeLabel);
            panel.Controls.Add(_tunnelCombo);
            panel.Controls.Add(epLabel);
            panel.Controls.Add(_endpointBox);
            panel.Controls.Add(_chkHosts);

            panel.Controls.Add(secApp);
            panel.Controls.Add(_chkTuningAsk);
            panel.Controls.Add(_chkKeepTunnel);
            panel.Controls.Add(_chkAutoRestore);
            panel.Controls.Add(_chkMinimize);

            panel.Controls.Add(runNow);
            panel.Controls.Add(restore);
            panel.Controls.Add(restoreHint);

            card.Controls.Add(panel);
            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildVersionsTab()
        {
            var page = new TabPage(L.T("نسخه‌ها", "Versions"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("نسخه‌های ماینکرفت روی این سیستم", "Minecraft versions on this PC");

            var top = new Panel();
            top.Dock = DockStyle.Top;
            top.Height = 76;

            var lbl = UiKit.Sub(L.T("پوشه نسخه‌ها:", "Versions folder:"));
            lbl.Location = new Point(8, 6);
            top.Controls.Add(lbl);

            _versionsDirBox = new TextBox();
            _versionsDirBox.Location = new Point(8, 26);
            _versionsDirBox.Width = 560;
            _versionsDirBox.Text = VersionScanner.ResolveVersionsDir(_settings.GameDirOverride, _settings.VersionsDir);
            _versionsDirBox.TextChanged += delegate
            {
                _settings.VersionsDir = _versionsDirBox.Text.Trim();
                if (Directory.Exists(_settings.VersionsDir)) RefreshVersions();
            };
            top.Controls.Add(_versionsDirBox);

            var browse = new Button();
            browse.Text = L.T("انتخاب پوشه", "Browse");
            browse.Location = new Point(578, 25);
            browse.Width = 110;
            browse.Click += delegate
            {
                using (var dialog = new FolderBrowserDialog())
                {
                    dialog.Description = L.T("پوشه versions ماینکرفت را انتخاب کنید", "Pick the Minecraft versions folder");
                    if (Directory.Exists(_versionsDirBox.Text)) dialog.SelectedPath = _versionsDirBox.Text;
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                    {
                        _versionsDirBox.Text = dialog.SelectedPath;
                        _settings.GameDirOverride = Directory.GetParent(dialog.SelectedPath) != null
                            ? Directory.GetParent(dialog.SelectedPath).FullName : _settings.GameDirOverride;
                        RefreshVersions();
                    }
                }
            };
            top.Controls.Add(browse);

            var refresh = new Button();
            refresh.Text = L.T("بازخوانی", "Refresh");
            refresh.Location = new Point(696, 25);
            refresh.Width = 110;
            refresh.Click += delegate { RefreshVersions(); };
            top.Controls.Add(refresh);

            card.Controls.Add(top);

            _versionList = new ListView();
            _versionList.Dock = DockStyle.Fill;
            _versionList.View = View.Details;
            _versionList.FullRowSelect = true;
            _versionList.GridLines = true;
            _versionList.Columns.Add(L.T("نسخه", "Version"), 180);
            _versionList.Columns.Add(L.T("نوع", "Type"), 110);
            _versionList.Columns.Add(L.T("نیازمندی", "Details"), 320);
            _versionList.Columns.Add(L.T("مسیر", "Folder"), 420);
            _versionList.DoubleClick += delegate { UseSelectedVersion(); };
            _versionList.SelectedIndexChanged += delegate { UpdatePlanPreview(); };
            card.Controls.Add(_versionList);

            var bottom = UiLabel(L.T("نسخه‌ها از پوشه TLauncher/ماینکرفت خوانده می‌شوند. با دوبار کلیک، نسخه انتخاب می‌شود.",
                                     "Versions are read from the TLauncher/Minecraft folder. Double click a row to select it."));
            bottom.Dock = DockStyle.Bottom;
            bottom.Height = 44;        // the sentence wraps to two lines in a narrow window
            bottom.AutoEllipsis = true;
            card.Controls.Add(bottom);

            // the rows have to be laid out before the list fills the rest, or the version row ends up
            // drawn over the list's column headers
            top.BringToFront();
            bottom.BringToFront();
            _versionList.BringToFront();

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildSettingsTab()
        {
            var page = new TabPage(L.T("تنظیمات", "Settings"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("تنظیمات", "Settings");

            var panel = new FlowLayoutPanel();
            panel.Dock = DockStyle.Fill;
            panel.FlowDirection = FlowDirection.TopDown;
            panel.WrapContents = false;
            panel.AutoScroll = true;

            var langLabel = UiKit.Sub(L.T("زبان برنامه", "Interface language"));
            var langCombo = new ComboBox();
            langCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            langCombo.Width = 220;
            langCombo.Items.Add("فارسی");
            langCombo.Items.Add("English");
            langCombo.SelectedIndex = L.Lang == L.En ? 1 : 0;
            langCombo.SelectedIndexChanged += delegate
            {
                string next = langCombo.SelectedIndex == 1 ? L.En : L.Fa;
                if (next == L.Lang) return;
                _settings.Language = next;
                L.SetLang(next);
                SettingsStore.Save(_settings);
                // the rebuild disposes this very combo box, so let the event finish first: the window
                // is put together again on the next message instead of inside its own event
                BeginInvoke((MethodInvoker)delegate
                {
                    BuildUi();
                    SetStatus(L.T("زبان تغییر کرد", "language changed"));
                });
            };

            var gameDirLabel = UiKit.Sub(L.T("پوشه بازی (.minecraft)", "Game folder (.minecraft)"));
            _gameDirBox = new TextBox();
            _gameDirBox.Width = 520;
            _gameDirBox.Text = _settings.GameDirOverride;
            _gameDirBox.TextChanged += delegate
            {
                _settings.GameDirOverride = _gameDirBox.Text.Trim();
                if (Directory.Exists(_settings.GameDirOverride)) RefreshVersions();
            };
            _gameDirBox.Validated += delegate { SettingsStore.Save(_settings); };

            var pickDir = new Button();
            pickDir.Text = L.T("انتخاب پوشه بازی", "Pick the game folder");
            pickDir.Width = 200;
            pickDir.Click += delegate
            {
                using (var dialog = new FolderBrowserDialog())
                {
                    dialog.Description = L.T("پوشه .minecraft را انتخاب کنید", "Pick the .minecraft folder");
                    if (Directory.Exists(_gameDirBox.Text)) dialog.SelectedPath = _gameDirBox.Text;
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                    {
                        _gameDirBox.Text = dialog.SelectedPath;
                        RefreshVersions();
                    }
                }
            };

            var javaLabel = UiKit.Sub(L.T("مسیر Java (اختیاری)", "Java path (optional)"));
            var javaBox = new TextBox();
            javaBox.Width = 520;
            javaBox.Text = _settings.JavaPathOverride;
            javaBox.TextChanged += delegate { _settings.JavaPathOverride = javaBox.Text.Trim(); };
            javaBox.Validated += delegate { SettingsStore.Save(_settings); };

            var folderButton = new Button();
            folderButton.Text = L.T("بازکردن پوشه داده‌ها", "Open the data folder");
            folderButton.Width = 200;
            folderButton.Click += delegate { Process.Start("explorer.exe", AppPaths.Data); };

            // the version line is how a user checks which download they are running: it carries the
            // build number the release workflow stamped
            var creditLabel = UiLabel(L.T("Server Help v" + Program.Version() + " — تونل: sing-box " + SingBoxRunner.PinnedVersion +
                                          " + Cloudflare WARP. هیچ داده‌ای از شما جایی ارسال نمی‌شود.",
                                          "Server Help v" + Program.Version() + " — tunnel: sing-box " + SingBoxRunner.PinnedVersion +
                                          " + Cloudflare WARP. Nothing about you leaves this machine."));
            creditLabel.Width = 640;
            // measured rather than guessed: the version line is long in both languages, and the label
            // used to be told "two lines" by hand. Any later growth - a longer build stamp, a wider
            // Persian face - now makes the label taller instead of cutting the last line.
            using (var creditFont = UiKit.UiFont(9.75f, false))
                creditLabel.Height = UiKit.WrappedHeight(creditLabel.Text, creditFont, creditLabel.Width, 40);

            panel.Controls.Add(langLabel);
            panel.Controls.Add(langCombo);
            panel.Controls.Add(gameDirLabel);
            panel.Controls.Add(_gameDirBox);
            panel.Controls.Add(pickDir);
            panel.Controls.Add(javaLabel);
            panel.Controls.Add(javaBox);
            panel.Controls.Add(folderButton);
            panel.Controls.Add(creditLabel);

            card.Controls.Add(panel);
            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildLogTab()
        {
            var page = new TabPage(L.T("گزارش", "Log"));
            page.Padding = new Padding(12);

            var card = new SHPanel();
            card.Dock = DockStyle.Fill;
            card.Title = L.T("گزارش", "Log");

            _logBox = new TextBox();
            _logBox.Multiline = true;
            _logBox.ScrollBars = ScrollBars.Both;
            _logBox.WordWrap = false;
            _logBox.Dock = DockStyle.Fill;
            _logBox.Font = UiKit.MonoFont(9f);
            _logBox.ReadOnly = true;

            // a rebuild (a language switch) must not wipe the visible log, and at startup there is
            // always something to show - the lines written before the window existed
            try { _logBox.Text = Log.TailFile(AppPaths.AppLog, 60000); }
            catch { }
            card.Controls.Add(_logBox);

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 42;
            var openLogs = new Button(); openLogs.Text = L.T("پوشه لاگ‌ها", "Log folder"); openLogs.Width = 130;
            openLogs.Click += delegate { Process.Start("explorer.exe", AppPaths.Logs); };
            var clear = new Button(); clear.Text = L.T("پاک‌کردن نمایش", "Clear view"); clear.Width = 130;
            clear.Click += delegate { _logBox.Clear(); };
            var singboxLog = new Button(); singboxLog.Text = L.T("لاگ تونل", "Tunnel log"); singboxLog.Width = 130;
            singboxLog.Click += delegate
            {
                string tail = Log.TailFile(AppPaths.SingBoxLog, 6000);
                _logBox.AppendText(Environment.NewLine + "----- sing-box -----" + Environment.NewLine + tail + Environment.NewLine);
            };
            buttons.Controls.Add(openLogs);
            buttons.Controls.Add(singboxLog);
            buttons.Controls.Add(clear);
            card.Controls.Add(buttons);

            page.Controls.Add(card);
            return page;
        }

        private CheckBox Check(string text, bool value, Action<bool> onChange)
        {
            var box = new CheckBox();
            box.Text = text;
            box.Checked = value;
            box.AutoSize = true;
            box.CheckedChanged += delegate { onChange(box.Checked); SettingsStore.Save(_settings); };
            return box;
        }

        private Label UiLabel(string text)
        {
            var label = new Label();
            label.Text = text;
            label.AutoSize = false;
            label.Height = 46;
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.AutoEllipsis = true;       // a long sentence in a narrow window is cut, not clipped away
            return label;
        }

        // ------------------------------------------------------------------ lifecycle

        private void OnShownFirst()
        {
            string detected = VersionScanner.DetectGameDir(_settings.GameDirOverride);
            if (!string.IsNullOrEmpty(detected) && string.IsNullOrEmpty(_settings.GameDirOverride))
            {
                _settings.GameDirOverride = detected;
                Log.Info("game folder detected: " + detected);
            }
            _gameDir = string.IsNullOrEmpty(_settings.GameDirOverride) ? detected : _settings.GameDirOverride;
            if (string.IsNullOrEmpty(_settings.Nickname))
            {
                string guess = VersionScanner.GuessNickname(_gameDir);
                _settings.Nickname = string.IsNullOrEmpty(guess) ? "Player" : guess;
                if (_nicknameBox != null) _nicknameBox.Text = _settings.Nickname;
            }
            // A session that was killed while the kill switch was armed leaves a black hole route
            // behind: just opening the app clears the ones belonging to the servers it knows, so the
            // user never has to repair the routing table by hand.
            var addresses = new List<string>();
            foreach (ServerProfile known in _settings.Servers)
            {
                if (!string.IsNullOrEmpty(known.DirectIp)) addresses.Add(known.DirectIp);
                System.Net.IPAddress parsed;
                if (!string.IsNullOrEmpty(known.Host) && System.Net.IPAddress.TryParse(known.Host, out parsed))
                    addresses.Add(known.Host);
            }
            List<string> leftovers = RouteTable.CleanLeftoverBlackholes(addresses);
            if (leftovers.Count > 0)
            {
                AppendLog(L.T("مسیرهای مسدودِ جامانده از اجرای قبلی پاک شد: ",
                              "blocked routes left behind by an earlier run were removed: ") +
                          string.Join(", ", leftovers.ToArray()));
                SetStatus(L.T("مسیرهای جامانده پاک شد", "leftover routes cleaned"));
            }
            // A crash leaves more than a route behind: the tunnel engine itself may still be running,
            // and our line in the hosts file may still pin the server name to an address that is no
            // longer routed. Both go now, before the first version scan and the first server check, so
            // a machine that was switched off in the middle of a game starts from a clean state.
            int strayEngines = SingBoxRunner.KillStrayEngines();
            if (strayEngines > 0)
            {
                AppendLog(L.T("موتور تونلِ جامانده از اجرای قبلی بسته شد: ", "a tunnel engine left behind by an earlier run was stopped: ")
                          + L.N(strayEngines));
                SetStatus(L.T("موتور جامانده بسته شد", "stray engine stopped"));
            }
            if (HostsFile.HasBlock())
            {
                HostsFile.Remove();
                AppendLog(L.T("خط جاماندهٔ فایل hosts از اجرای قبلی پاک شد",
                              "the hosts entry left behind by an earlier run was removed"));
            }
            RefreshVersions();
            CheckServerAsync();
            AppendLog(Log.Recent());
        }

        private void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (_closing) return;
            _closing = true;
            try
            {
                if (_pipeline.GameRunning)
                {
                    var answer = MessageBox.Show(
                        L.T("بازی در حال اجراست. بستن برنامه بازی را هم می‌بندد. ادامه؟",
                            "The game is running. Closing the helper will close the game too. Continue?"),
                        "Server Help", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                    if (answer == DialogResult.No) { _closing = false; e.Cancel = true; return; }
                    _pipeline.Game.Kill();
                }
                // The tunnel is always taken down when the window closes, whatever the "keep the
                // tunnel" switch says: that switch is about the gap between two game sessions while
                // the app is still open. Leaving a sing-box process and its interface behind after
                // the app is gone is exactly the kind of leftover this app promises not to leave.
                _pipeline.Shutdown(false);
                // A measurement may still be running in the background; its throwaway engine is a real
                // process and has to go with the window.
                ProbeTunnel.StopAll();
                if (_worker != null) _worker.Interrupt();
            }
            catch (Exception ex) { Log.Warn("closing: " + ex.Message); }
            SettingsStore.Save(_settings);
        }

        private void Tick()
        {
            if (_runWatch != null && _runWatch.IsRunning)
            {
                long ms = _runWatch.ElapsedMilliseconds;
                string text = L.T("زمان: ", "elapsed: ") + L.N(ms / 1000.0, 1) + L.T(" ثانیه از ", " s of ") + L.N(60) + L.T(" ثانیه", " s");
                if (ms > LaunchPipeline.BudgetMs) text += "  ⚠ " + L.T("از بودجه یک‌دقیقه‌ای گذشت", "over the one minute budget");
                _timerLabel.Text = text;
                if (_runProgress != null)
                {
                    _runProgress.Value = Math.Min(1f, ms / (float)LaunchPipeline.BudgetMs);
                    _runProgress.BarColor = ms > LaunchPipeline.BudgetMs ? Theme.Warn : Theme.Accent;
                    if (_runProgress.Caption.Length == 0 || _runProgress.Caption.StartsWith("!"))
                        _runProgress.Caption = text;
                    _runProgress.Invalidate();
                }
            }
            if (_pipeline.TunnelRunning)
            {
                string message;
                if (_pipeline.Tunnel.DiedUnexpectedly(out message))
                {
                    AppendLog(L.T("تونل قطع شد: ", "tunnel died: ") + message);
                    _tunnelInfoLabel.Text = L.T("تونل قطع شد", "tunnel stopped");
                }
            }
        }

        private void Ui(Action action)
        {
            try
            {
                if (_closing || IsDisposed) return;
                if (InvokeRequired) BeginInvoke(action);
                else action();
            }
            catch { }
        }

        // ------------------------------------------------------------------ actions

        private void RefreshServerList()
        {
            if (_serverList == null) return;

            // repopulating the combo is not the user picking another server
            _serversBusy = true;
            try
            {
                // the table is cleared and refilled in one go: no flicker, no scroll jump and no
                // lost selection
                _serverList.BeginUpdate();
                try
                {
                    _serverList.Items.Clear();
                    if (_serverCombo != null)
                    {
                        int keep = _serverCombo.SelectedIndex;
                        if (keep < 0)
                        {
                            // nothing to keep - a rebuilt window, say: come back to the server that is actually active
                            // instead of silently switching to the first one in the list
                            for (int i = 0; i < _settings.Servers.Count; i++)
                                if (string.Equals(_settings.Servers[i].Name, _settings.ActiveServer, StringComparison.OrdinalIgnoreCase)) keep = i;
                        }
                        _serverCombo.BeginUpdate();
                        try
                        {
                            _serverCombo.Items.Clear();
                            foreach (ServerProfile profile in _settings.Servers) _serverCombo.Items.Add(profile.Name);
                            _serverCombo.SelectedIndex = Math.Max(0, Math.Min(keep, _serverCombo.Items.Count - 1));
                        }
                        finally { _serverCombo.EndUpdate(); }
                    }
                    foreach (ServerProfile profile in _settings.Servers)
                    {
                        var item = new ListViewItem(profile.Name);
                        item.SubItems.Add(profile.Endpoint);
                        item.SubItems.Add(string.IsNullOrEmpty(profile.DirectIp) ? "—" : profile.DirectIp);
                        item.SubItems.Add(string.Equals(profile.Name, _settings.ActiveServer, StringComparison.OrdinalIgnoreCase)
                            ? L.T("بله", "yes") : "—");
                        _serverList.Items.Add(item);
                    }
                }
                finally { _serverList.EndUpdate(); }
            }
            finally { _serversBusy = false; }
        }

        private ServerProfile SelectedServer()
        {
            if (_settings.Servers.Count == 0) _settings.Servers.Add(AppSettings.DefaultServer());
            return _settings.GetActiveServer();
        }

        private void SelectServer(int index)
        {
            if (index < 0 || index >= _settings.Servers.Count) return;
            _settings.ActiveServer = _settings.Servers[index].Name;
            RefreshServerList();
            UpdateServerInfo();
        }

        private void ActivateServer()
        {
            if (_serverList.SelectedIndices.Count == 0) return;
            int index = _serverList.SelectedIndices[0];
            if (index < _settings.Servers.Count) SelectServer(index);
        }

        private void RemoveServer()
        {
            if (_serverList.SelectedIndices.Count == 0) return;
            int index = _serverList.SelectedIndices[0];
            if (index < _settings.Servers.Count && _settings.Servers.Count > 1)
            {
                _settings.Servers.RemoveAt(index);
                if (_settings.GetActiveServer() == null) _settings.ActiveServer = _settings.Servers[0].Name;
                RefreshServerList();
            }
        }

        private void EditServer(ServerProfile profile)
        {
            using (var dialog = new ServerDialog(profile))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                if (profile == null)
                {
                    _settings.Servers.Add(dialog.Profile);
                    _settings.ActiveServer = dialog.Profile.Name;
                }
                else
                {
                    int index = _settings.Servers.IndexOf(profile);
                    if (index >= 0)
                    {
                        bool wasActive = string.Equals(_settings.ActiveServer, profile.Name, StringComparison.OrdinalIgnoreCase);
                        _settings.Servers[index] = dialog.Profile;
                        if (wasActive) _settings.ActiveServer = dialog.Profile.Name;
                    }
                }
                RefreshServerList();
                UpdateServerInfo();
                SettingsStore.Save(_settings);
            }
        }

        // ------------------------------------------------------------------ connections

        private void RefreshConnections()
        {
            if (_connectionList == null) return;
            // the table is rebuilt in one go after every result: it must not flicker, and the row the user
            // was working on has to stay the selected one
            _connectionList.BeginUpdate();
            try
            {
                // the table is rebuilt after every result: keep the row the user was working on selected
                int wanted = _connectionList.SelectedIndices.Count > 0
                    ? _connectionList.SelectedIndices[0]
                    : _pendingConnectionRow;
                _pendingConnectionRow = -1;   // asked for once, by the rebuild that was about to happen
                _connectionList.Items.Clear();
                foreach (ConnectionEntry entry in _settings.Connections)
                {
                    var item = new ListViewItem(entry.Name);
                    item.SubItems.Add(entry.Info.Title);
                    item.SubItems.Add(entry.Target);
                    // a Telegram or DNS number is not a game ping, and the table has to say so
                    string note = entry.Info.DelayNote;
                    item.SubItems.Add(entry.LastDelayMs > 0
                        ? L.N(entry.LastDelayMs) + " ms" + (note.Length > 0 ? "  (" + note + ")" : "")
                        : "—");
                    item.SubItems.Add(entry.Info.Carries);
                    item.SubItems.Add(entry.QualityText().Length > 0 ? entry.QualityText() : "—");
                    item.SubItems.Add(string.IsNullOrEmpty(entry.LastStatus) ? L.T("تست نشده", "not tested") : entry.StatusText);
                    // a bare clock time would make yesterday's measurement look like today's
                    string tested = entry.TestedText();
                    item.SubItems.Add(tested.Length > 0 ? tested : "—");
                    item.SubItems.Add(entry.Enabled ? L.T("بله", "yes") : L.T("خیر", "no"));
                    if (!entry.Enabled) item.ForeColor = Color.FromArgb(140, 140, 140);
                    else if (entry.LastDelayMs > 0) item.ForeColor = Color.FromArgb(24, 120, 50);
                    else if (!string.IsNullOrEmpty(entry.LastError)) item.ForeColor = Color.FromArgb(180, 40, 70);
                    _connectionList.Items.Add(item);
                }

                if (wanted >= 0 && _connectionList.Items.Count > 0)
                    _connectionList.Items[Math.Min(wanted, _connectionList.Items.Count - 1)].Selected = true;
            }
            finally { _connectionList.EndUpdate(); }

            _connectionsBusy = true;
            try
            {
                _pinCombo.BeginUpdate();
                try
                {
                    _pinCombo.Items.Clear();
                    _pinCombo.Items.Add(L.T("خودکار (سریع‌ترین)", "Automatic (fastest)"));
                    foreach (ConnectionEntry entry in _settings.Connections)
                    {
                        if (!entry.Enabled) continue;
                        if (!entry.CanCarryGame) continue;      // DNS and TG proxies are never a game route
                        _pinCombo.Items.Add(entry.Name);
                    }
                    int index = 0;
                    if (!string.IsNullOrEmpty(_settings.PinnedConnection))
                    {
                        for (int i = 1; i < _pinCombo.Items.Count; i++)
                            if (string.Equals(_pinCombo.Items[i].ToString(), _settings.PinnedConnection, StringComparison.OrdinalIgnoreCase)) index = i;
                    }
                    _pinCombo.SelectedIndex = index;
                }
                finally { _pinCombo.EndUpdate(); }
            }
            finally { _connectionsBusy = false; }

            UpdateConnectionSummary();
        }

        /// <summary>
        /// The one line under the table: how many entries there are and what the next launch does
        /// with them. While a launch is in flight it also says that the running one took its own copy
        /// of the list when Play was pressed, so an edit made now belongs to the next run.
        /// </summary>
        private void UpdateConnectionSummary()
        {
            if (_connectionSummary == null) return;
            int on = 0, working = 0;
            foreach (ConnectionEntry entry in _settings.Connections)
            {
                if (entry.Enabled) on++;
                if (entry.LastDelayMs > 0) working++;
            }
            string running = _worker != null && _worker.IsAlive
                ? L.T("    |  اجرای در حال انجام با فهرست لحظه‌ی فشردن Play کار می‌کند؛ تغییرها برای اجرای بعدی است",
                      "    |  the running launch uses the list as it was when Play was pressed; edits apply to the next run")
                : "";
            _connectionSummary.Text = L.T("اتصال‌ها: ", "connections: ") + L.N(_settings.Connections.Count) +
                                      L.T(" • روشن: ", " • on: ") + L.N(on) +
                                      L.T(" • تست‌شده با تأخیر: ", " • measured: ") + L.N(working) +
                                      L.T("    |  مسیر انتخابی: ", "    |  chosen route: ") +
                                      ChosenRouteText() + running;
        }

        /// <summary>
        /// What the next launch will actually do. A pin that points at a connection which was
        /// removed, switched off or renamed away must say so here: otherwise the table claims a
        /// route that the pipeline is not going to use.
        /// </summary>
        private string ChosenRouteText()
        {
            string automatic = L.T("خودکار (همه تست و سریع‌ترین انتخاب می‌شود)",
                                   "automatic (all are tested, the fastest wins)");
            string pinnedName = _settings.PinnedConnection == null ? "" : _settings.PinnedConnection.Trim();
            if (pinnedName.Length == 0) return automatic;
            ConnectionEntry pinned = _settings.FindConnection(pinnedName);
            if (pinned == null)
                return pinnedName + L.T(" (پیدا نشد؛ مسیر خودکار استفاده می‌شود)",
                                        " (not found; the automatic route is used)");
            if (!pinned.Enabled)
                return pinned.Name + L.T(" (خاموش است؛ مسیر خودکار استفاده می‌شود)",
                                         " (switched off; the automatic route is used)");
            if (!pinned.CanCarryGame)
                return pinned.Name + L.T(" (ترافیک بازی را حمل نمی‌کند)", " (it cannot carry the game traffic)");
            string chain = _settings.PinnedChainHop == null ? "" : _settings.PinnedChainHop.Trim();
            if (chain.Length > 0)
            {
                // Same rule the run uses, so the line cannot advertise a chain that would not be built.
                ConnectionEntry hop = LaunchPipeline.FindChainHop(_settings, _settings.Connections, pinned);
                if (hop == null)
                    return pinned.Name + L.T(" → گام دوم زنجیره قابل استفاده نیست (تک‌مرحله‌ای اجرا می‌شود)",
                                             " → the pinned second hop cannot be used (it runs single hop)");
                return pinned.Name + " → " + hop.Name;
            }
            return pinned.Name;
        }

        private ConnectionEntry SelectedConnection()
        {
            if (_connectionList == null || _connectionList.SelectedIndices.Count == 0) return null;
            int index = _connectionList.SelectedIndices[0];
            if (index < 0 || index >= _settings.Connections.Count) return null;
            return _settings.Connections[index];
        }

        private void EditConnection(ConnectionEntry existing)
        {
            using (var dialog = new ConnectionDialog(existing, _settings, SelectedServer()))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                ConnectionEntry result = dialog.Entry;
                if (existing == null)
                {
                    _settings.Connections.Add(result);
                }
                else
                {
                    int index = _settings.Connections.IndexOf(existing);
                    if (index >= 0) _settings.Connections[index] = result;
                    // the pin is stored by name: a rename would silently stop it from matching
                    if (existing.Name != result.Name)
                    {
                        if (string.Equals(_settings.PinnedConnection, existing.Name, StringComparison.OrdinalIgnoreCase))
                            _settings.PinnedConnection = result.Name;
                        if (string.Equals(_settings.PinnedChainHop, existing.Name, StringComparison.OrdinalIgnoreCase))
                            _settings.PinnedChainHop = result.Name;
                    }
                }
                SettingsStore.Save(_settings);
                RefreshConnections();
                SetStatus(L.T("اتصال ذخیره شد: ", "connection saved: ") + result.Name);
            }
        }

        private void RemoveConnection()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null) return;
            // Deleting is the one thing in this table that cannot be undone, and an entry holds
            // credentials the user typed in: ask first, with the name in the question.
            var answer = MessageBox.Show(this,
                L.T("این اتصال حذف شود؟", "Delete this connection?") + Environment.NewLine + Environment.NewLine +
                entry.Name + "  (" + entry.Info.Title + ")" + Environment.NewLine + Environment.NewLine +
                L.T("حذف قابل برگشت نیست؛ اگر فقط می‌خواهید فعلاً استفاده نشود، به‌جای حذف خاموشش کنید.",
                    "Deleting cannot be undone; if you only want it out of the way for now, switch it off instead."),
                L.T("حذف اتصال", "Delete connection"), MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (answer != DialogResult.Yes) return;

            _settings.Connections.Remove(entry);
            // A pin is stored by name, and the entry that carried it is gone: leaving the name behind
            // makes the line under the table (and the plan) point at a connection that no longer exists.
            var dropped = new List<string>();
            if (string.Equals(_settings.PinnedConnection, entry.Name, StringComparison.OrdinalIgnoreCase))
            {
                _settings.PinnedConnection = "";
                dropped.Add(L.T("مسیر ثابت", "the pinned route"));
            }
            if (string.Equals(_settings.PinnedChainHop, entry.Name, StringComparison.OrdinalIgnoreCase))
            {
                _settings.PinnedChainHop = "";
                dropped.Add(L.T("گام دوم زنجیره", "the second hop of the chain"));
            }
            SettingsStore.Save(_settings);
            RefreshConnections();
            string note = dropped.Count > 0
                ? L.T(" — ", " — ") + string.Join(L.T(" و ", " and "), dropped.ToArray()) + L.T(" هم برداشته شد", " was released too")
                : "";
            AppendLog("[connections] removed " + entry.Name + (note.Length > 0 ? note : ""));
            SetStatus(L.T("اتصال حذف شد: ", "connection deleted: ") + entry.Name + note);
        }

        private void ToggleConnection()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null) return;
            entry.Enabled = !entry.Enabled;
            SettingsStore.Save(_settings);
            RefreshConnections();
        }

        private void MoveConnection(int delta)
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null) return;
            int index = _settings.Connections.IndexOf(entry);
            int target = index + delta;
            if (index < 0 || target < 0 || target >= _settings.Connections.Count) return;
            _settings.Connections.RemoveAt(index);
            _settings.Connections.Insert(target, entry);
            SettingsStore.Save(_settings);
            RefreshConnections();
            if (target < _connectionList.Items.Count) _connectionList.Items[target].Selected = true;
        }

        private void PinConnection(string name)
        {
            _settings.PinnedConnection = name ?? "";
            SettingsStore.Save(_settings);
            RefreshConnections();
            if (string.IsNullOrEmpty(_settings.PinnedConnection))
                SetStatus(L.T("حالت خودکار: هر بار سریع‌ترین اتصال انتخاب می‌شود", "automatic mode: the fastest connection wins each run"));
            else
                SetStatus(L.T("مسیر ثابت شد: ", "route pinned: ") + _settings.PinnedConnection);
        }

        private void ImportConnections()
        {
            using (var dialog = new ImportDialog(""))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                List<ConnectionEntry> imported = dialog.Entries;
                if (imported.Count == 0)
                {
                    SetStatus(L.T("چیزی برای افزودن پیدا نشد", "nothing to import"));
                    return;
                }
                foreach (ConnectionEntry entry in imported)
                {
                    // keep names unique so the pin list stays readable
                    string name = entry.Name;
                    int suffix = 2;
                    while (_settings.FindConnection(name) != null) name = entry.Name + " " + suffix++;
                    entry.Name = name;
                    _settings.Connections.Add(entry);
                }
                SettingsStore.Save(_settings);
                RefreshConnections();
                SetStatus(L.T("افزوده شد: ", "imported: ") + L.N(imported.Count) + L.T(" اتصال", " connection(s)"));
            }
        }

        private void TestConnections(bool all)
        {
            var targets = new List<ConnectionEntry>();
            if (all)
            {
                foreach (ConnectionEntry entry in _settings.Connections) if (entry.Enabled) targets.Add(entry);
            }
            else
            {
                ConnectionEntry entry = SelectedConnection();
                if (entry == null)
                {
                    SetStatus(L.T("اول یک اتصال را انتخاب کنید", "select a connection first"));
                    return;
                }
                targets.Add(entry);
            }
            if (targets.Count == 0)
            {
                SetStatus(L.T("اتصال روشنی برای تست نیست", "no enabled connection to test"));
                return;
            }

            var profile = SelectedServer();
            int timeout = _settings.ConnectionTestTimeoutMs;
            string host = profile.Host;
            int port = profile.Port;
            if (!BeginMeasurement()) return;
            SetStatus(L.T("تست اتصال‌ها…", "testing connections…"));

            var thread = new Thread(delegate ()
            {
                try { RunConnectionTests(targets, host, port, timeout); }
                finally { EndMeasurement(); }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>Measures the entries one after another, updating the table after each result.</summary>
        private void RunConnectionTests(List<ConnectionEntry> targets, string host, int port, int timeout)
        {
            int done = 0;
            foreach (ConnectionEntry entry in targets)
            {
                done++;
                ConnectionEntry local = entry;
                int index = done;                       // 1 of 3, not 2 of 3
                int total = targets.Count;
                Ui(delegate
                {
                    SetStatus("(" + L.N(index) + "/" + L.N(total) + ") " + L.T("تست: ", "testing: ") + local.Name);
                });
                ConnectionTestResult result = ConnectionTester.Test(local, host, port, timeout, false);
                local.LastDelayMs = result.Ok ? result.DelayMs : -1;
                local.LastStatus = result.Status;
                local.LastError = result.Ok ? "" : result.Detail;
                local.MarkTested();
                string line = local.Name + " [" + local.Info.Title + "] — " +
                              (result.Ok ? L.T("کار کرد", "works") : L.T("کار نکرد", "failed")) +
                              (result.DelayMs > 0 ? " • " + L.N(result.DelayMs) + " ms" : "") +
                              (string.IsNullOrEmpty(result.Detail) ? "" : " • " + result.Detail);
                AppendLog("[connection] " + line);
                Ui(delegate
                {
                    RefreshConnections();
                    SetStatus(line);
                });
            }
            Ui(delegate
            {
                SettingsStore.Save(_settings);
                RefreshConnections();
                SetStatus(L.T("تست اتصال‌ها تمام شد", "connection tests finished"));
            });
        }

        /// <summary>Runs the real MTProto handshake + req_pq on the selected proxy and reports it.</summary>
        /// <summary>
        /// One heavy measurement at a time. A stability run, a speed test and a connection test each
        /// bring up their own throwaway engine, and two of them at once would fight over the same
        /// machine. The periodic retest asks the same flag, so it can never start on top of a manual
        /// run.
        /// </summary>
        private bool BeginMeasurement()
        {
            if (_stabilityBusy)
            {
                SetStatus(L.T("یک اندازه‌گیری دیگر در جریان است؛ چند لحظه صبر کنید",
                              "another measurement is already running; give it a moment"));
                return false;
            }
            _stabilityBusy = true;
            return true;
        }

        /// <summary>Releases the flag on the UI thread, whatever happened in the worker.</summary>
        private void EndMeasurement()
        {
            Ui(delegate { _stabilityBusy = false; });
        }

        /// <summary>
        /// Keeps the measured delays honest: with a timer set, the connections are re-measured in the
        /// background every few minutes, so a route that died during the evening is noticed before the
        /// game is launched through it. It never touches the game while it runs.
        /// </summary>
        private void RestartRetestTimer()
        {
            if (_retestTimer != null)
            {
                _retestTimer.Stop();
                _retestTimer.Dispose();
                _retestTimer = null;
            }
            int minutes = _settings.RetestMinutes;
            if (minutes <= 0) return;
            _retestTimer = new System.Windows.Forms.Timer();
            _retestTimer.Interval = Math.Max(1, minutes) * 60 * 1000;
            _retestTimer.Tick += delegate
            {
                if (_worker != null && _worker.IsAlive) return;          // a launch is running
                if (_pipeline.GameRunning) return;                      // the game is playing
                if (_connectionsBusy || _stabilityBusy) return;         // a manual test is running
                AppendLog("[retest] measuring " + _settings.Connections.Count + " connection(s)");
                TestConnections(true);
            };
            _retestTimer.Start();
        }

        /// <summary>
        /// The periodic retest only fires once a whole interval has passed, so with "every 12 hours" a
        /// number measured last week would sit in the table looking current. One measurement a few
        /// seconds after the window opens closes that gap - and it is skipped when the saved numbers
        /// are still inside the interval, so opening the app twice in a row probes nothing twice.
        /// </summary>
        private void RetestStaleAtStartup()
        {
            if (_settings.RetestMinutes <= 0 || _settings.Connections == null) return;
            bool stale = false;
            foreach (ConnectionEntry entry in _settings.Connections)
            {
                if (!entry.Enabled) continue;
                if (!entry.MeasurementOlderThan(_settings.RetestMinutes)) continue;
                stale = true;
                break;
            }
            if (!stale) return;
            _startupRetest = new System.Windows.Forms.Timer();
            _startupRetest.Interval = 8000;      // let the window finish drawing and the server check start
            _startupRetest.Tick += delegate
            {
                _startupRetest.Stop();
                _startupRetest.Dispose();
                _startupRetest = null;
                if (_worker != null && _worker.IsAlive) return;          // a launch is running
                if (_pipeline.GameRunning) return;                      // the game is playing
                if (_connectionsBusy || _stabilityBusy) return;         // a measurement is running
                AppendLog("[retest] the saved delays are older than " + _settings.RetestMinutes + " min; measuring now");
                TestConnections(true);
            };
            _startupRetest.Start();
        }

        /// <summary>
        /// Diagnoses the line: is the international route open, is TLS filtered, is the resolver
        /// lying, does the game server answer at all. Every check reports the real number it saw and
        /// the verdict comes with the fix that belongs to it.
        /// </summary>
        private void DiagnoseLine()
        {
            var profile = SelectedServer();
            if (profile == null)
            {
                SetStatus(L.T("اول یک سرور انتخاب کنید", "select a server first"));
                return;
            }
            string host = profile.Host;
            string ip = profile.DirectIp;
            int port = profile.Port;
            int timeout = Math.Max(2500, _settings.ConnectionTestTimeoutMs);

            if (!BeginMeasurement()) return;
            SetStatus(L.T("تشخیص خط…", "diagnosing the line…"));
            var thread = new Thread(delegate ()
            {
              try
              {
                var probes = LineDoctor.Probe(host, ip, port, timeout);
                string advice;
                LineVerdict verdict = LineDoctor.Verdict(probes, out advice);
                string text = LineDoctor.Report(probes, verdict, advice);
                Ui(delegate
                {
                    AppendLog("[line] " + LineDoctor.VerdictTitle(verdict));
                    foreach (LineProbe probe in probes)
                        AppendLog("[line] " + (probe.Ok ? "ok " : "no ") + probe.Name + " — " + probe.Detail);
                    SetStatus(L.T("تشخیص خط: ", "line diagnosis: ") + LineDoctor.VerdictTitle(verdict));
                    // the advice is a suggestion, never applied behind the user's back
                    DialogResult answer = MessageBox.Show(this,
                        text + Environment.NewLine +
                        L.T("آیا پیشنهاد بالا اعمال شود؟ (فقط تنظیمات همین برنامه تغییر می‌کند)",
                            "Apply the advice above? (only this program's own settings change)"),
                        L.T("تشخیص خط", "Line diagnosis"), MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                    if (answer == DialogResult.Yes) ApplyLineAdvice(verdict);
                });
              }
              finally { EndMeasurement(); }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>Applies only what this app owns: its own switches, never a Windows setting.</summary>
        private void ApplyLineAdvice(LineVerdict verdict)
        {
            switch (verdict)
            {
                case LineVerdict.DnsBroken:
                case LineVerdict.NationalOnly:
                case LineVerdict.FullyFiltered:
                    _settings.DnsThroughTunnel = true;
                    if (_chkDnsInTunnel != null) _chkDnsInTunnel.Checked = true;
                    SettingsStore.Save(_settings);
                    SetStatus(L.T("DNS داخل تونل روشن شد", "DNS inside the tunnel is on"));
                    break;
                case LineVerdict.TlsBlocked:
                    {
                        ConnectionEntry entry = SelectedConnection();
                        if (entry != null && entry.CanCarryGame)
                        {
                            entry.FragmentTls = true;
                            SettingsStore.Save(_settings);
                            RefreshConnections();
                            SetStatus(L.T("تکه‌تکه‌کردن TLS برای ", "TLS fragmentation is on for ") + entry.Name);
                        }
                        else
                        {
                            _settings.FragmentTls = true;
                            if (_chkFragment != null) _chkFragment.Checked = true;   // the switch moves too
                            SettingsStore.Save(_settings);
                            SetStatus(L.T("تکه‌تکه‌کردن TLS برای همه مسیرهای جدید روشن شد",
                                          "TLS fragmentation is on for every new route"));
                        }
                        break;
                    }
                case LineVerdict.ServerBlocked:
                    SetStatus(L.T("سرور بازی از این خط جواب نمی‌دهد؛ «بهینه‌سازی مسیر بازی» را بزنید",
                                  "the game server does not answer from this line; run Optimise game route"));
                    OptimiseGameRoute();
                    break;
                default:
                    SetStatus(L.T("تغییری لازم نیست", "nothing needs changing"));
                    break;
            }
        }

        /// <summary>
        /// Five measurements through the selected connection: the average, the jitter and the loss.
        /// A route can look fast once and still rubber band all evening; this is the number that
        /// says which one it is.
        /// </summary>
        private void StabilityTest(bool all)
        {
            var targets = new List<ConnectionEntry>();
            if (all)
            {
                foreach (ConnectionEntry entry in _settings.Connections)
                    if (entry.Enabled && entry.CanCarryGame) targets.Add(entry);
            }
            else
            {
                ConnectionEntry entry = SelectedConnection();
                if (entry == null)
                {
                    SetStatus(L.T("اول یک اتصال را انتخاب کنید", "select a connection first"));
                    return;
                }
                targets.Add(entry);
            }
            if (targets.Count == 0)
            {
                SetStatus(L.T("اتصالی برای تست نیست", "there is nothing to test"));
                return;
            }
            if (_pipeline.GameRunning || _worker != null && _worker.IsAlive)
            {
                SetStatus(L.T("پایپ‌لاین در حال اجراست؛ بعد از اجرای بازی تست کنید",
                              "the pipeline is running; test after the game has started"));
                return;
            }

            var profile = SelectedServer();
            int timeout = Math.Min(4000, Math.Max(2000, _settings.ConnectionTestTimeoutMs));
            if (!BeginMeasurement()) return;
            SetStatus(L.T("تست پایداری…", "measuring stability…"));

            var thread = new Thread(delegate ()
            {
              try
              {
                int index = 0;
                foreach (ConnectionEntry entry in targets)
                {
                    index++;
                    int shown = index;
                    Ui(delegate
                    {
                        SetStatus(L.T("پایداری ", "stability ") + L.N(shown) + "/" + L.N(targets.Count) +
                                  " — " + entry.Name);
                    });
                    var result = new QualityResult();
                    try
                    {
                        result = MeasureEntry(entry, profile, timeout, false);
                    }
                    catch (Exception ex)
                    {
                        result.Detail = ex.Message;
                    }
                    QualityResult captured = result;
                    ConnectionEntry target = entry;
                    Ui(delegate
                    {
                        target.LastPingMin = captured.MinMs;
                        target.LastPingMax = captured.MaxMs;
                        target.LastJitterMs = captured.JitterMs;
                        target.LastLossPercent = captured.LossPercent;
                        if (captured.AvgMs > 0)
                        {
                            target.LastDelayMs = captured.AvgMs;
                            target.LastStatus = L.T("پایدار ", "stable ") + captured.Grade();
                        }
                        target.MarkTested();
                        AppendLog("[quality] " + target.Name + " — " + captured.Summary());
                        SettingsStore.Save(_settings);
                        RefreshConnections();
                    });
                }
              }
              finally
              {
                EndMeasurement();
                Ui(delegate { SetStatus(L.T("تست پایداری تمام شد", "the stability test is done")); });
              }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>Runs the five-sample measurement through whichever route the entry describes.</summary>
        private QualityResult MeasureEntry(ConnectionEntry entry, ServerProfile profile, int timeout, bool withSpeed)
        {
            string host = profile == null ? "" : profile.Host;
            int port = profile == null ? 25565 : profile.Port;
            if (string.IsNullOrEmpty(host)) host = L.T("سرور بازی", "the game server");
            if (port <= 0) port = 25565;

            if (entry.Kind == ConnectionKind.Socks5)
                return QualityTest.Measure(new Socks5Client(entry.Host, entry.Port, entry.User, entry.Password, timeout),
                                           host, port, 5, timeout);
            if (entry.Kind == ConnectionKind.Http)
                return QualityTest.Measure(new HttpProxyClient(entry.Host, entry.Port, entry.User, entry.Password, timeout),
                                           host, port, 5, timeout);
            if (entry.Kind == ConnectionKind.Dns)
            {
                var result = new QualityResult();
                int total = 0, ok = 0;
                for (int i = 0; i < 5; i++)
                {
                    DnsAnswer answer = DnsClient.Resolve(entry.DnsUrl, host, timeout);
                    if (answer.Ok) { ok++; total += answer.ElapsedMs; }
                    System.Threading.Thread.Sleep(80);
                }
                result.Samples = 5;
                result.Lost = 5 - ok;
                if (ok > 0) result.AvgMs = total / ok;
                result.MinMs = result.AvgMs;
                result.MaxMs = result.AvgMs;
                result.Detail = L.T("تست DNS", "a DNS test");
                return result;
            }

            // everything else runs by bringing the route up in a throwaway engine, which is exactly
            // what the launch will do, so the numbers are the numbers the game will see
            ProbeTunnel probe;
            string error;
            int socksPort = StartProbeFor(entry, timeout, out probe, out error);
            if (socksPort <= 0)
            {
                var failed = new QualityResult();
                failed.Detail = error;
                return failed;
            }
            try
            {
                var client = new Socks5Client("127.0.0.1", socksPort, timeout);
                QualityResult result = QualityTest.Measure(client, host, port, 5, timeout);
                if (withSpeed && result.Ok)
                    result.SpeedKbps = QualityTest.DownloadSpeed(client, 512 * 1024, Math.Max(4000, timeout * 2));
                return result;
            }
            finally
            {
                probe.Stop();
            }
        }

        /// <summary>
        /// Brings one connection up in a throwaway engine on a free local port - no TUN, no route
        /// changes, nothing else on the machine is touched - and returns that port. Every measurement
        /// uses it, and so does fetching a subscription through a connection that needs its own engine.
        /// </summary>
        private static int StartProbeFor(ConnectionEntry entry, int timeout, out ProbeTunnel probe, out string error)
        {
            probe = null;
            error = "";
            try
            {
                if (entry.Kind == ConnectionKind.SingBoxConfig)
                    return StartFullConfigProbe(entry, timeout, out probe, out error);

                int socksPort = ProbeTunnel.NextPort();
                var plan = new TunnelPlan();
                plan.IncludeTun = false;
                plan.SocksPort = socksPort;
                plan.ClashController = "";               // no extra listener while probing
                plan.LogPath = "";
                plan.BuildUrlTest = false;
                plan.DnsThroughRoute = false;
                string tag = ConnectionRoute.TagFor(entry);
                if (entry.Kind == ConnectionKind.WireGuard || entry.Kind == ConnectionKind.OpenVpn)
                    plan.ExtraEndpoints.Add(ConnectionRoute.BuildEndpoint(entry, tag));
                else
                    plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(entry, tag));
                plan.RouteTag = tag;

                string json = SingBoxConfig.Build(plan);
                ProbeTunnel started;
                if (!ProbeTunnel.TryStart(json, socksPort, Math.Max(4000, timeout * 2), out started, out error))
                {
                    probe = null;
                    return 0;
                }
                probe = started;
                return socksPort;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                probe = null;
                return 0;
            }
        }

        /// <summary>
        /// A full config runs exactly as the user pasted it, on a free port of our own. A config that
        /// would create a TUN interface is refused: that is a change to the machine, and this is a
        /// measurement, not a launch.
        /// </summary>
        private static int StartFullConfigProbe(ConnectionEntry entry, int timeout, out ProbeTunnel probe, out string error)
        {
            probe = null;
            error = "";
            if (ConnectionTester.HasTunInbound(entry.Config))
            {
                error = L.T("این کانفیگ اینترفیس TUN می‌سازد، پس برای اندازه‌گیری بالا نمی‌آید.",
                            "this config creates a TUN interface, so it is not started for a measurement.");
                return 0;
            }
            int declared;
            try
            {
                declared = ConnectionParser.FindSocksPort(Json.ParseObject(entry.Config));
            }
            catch (Exception ex)
            {
                error = L.T("کانفیگ JSON خوانده نشد: ", "the JSON config could not be read: ") + ex.Message;
                return 0;
            }
            if (declared <= 0)
            {
                error = L.T("این کانفیگ inbound لوکال (socks/mixed) ندارد، پس مسیری برای اندازه‌گیری نیست.",
                            "this config has no local socks/mixed inbound, so there is no path to measure.");
                return 0;
            }
            int free = ProbeTunnel.NextPort();
            string rewritten = ConnectionTester.RewriteSocksPort(entry.Config, free);
            ProbeTunnel started;
            if (!ProbeTunnel.TryStart(rewritten, free, Math.Max(4000, timeout * 2), out started, out error))
            {
                probe = null;
                return 0;
            }
            probe = started;
            return free;
        }

        /// <summary>How much data this route can actually carry - a path that cannot download is no path.</summary>
        private void SpeedTestSelected()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null)
            {
                SetStatus(L.T("اول یک اتصال را انتخاب کنید", "select a connection first"));
                return;
            }
            var profile = SelectedServer();
            int timeout = Math.Min(4000, Math.Max(2000, _settings.ConnectionTestTimeoutMs));
            if (!BeginMeasurement()) return;
            SetStatus(L.T("تست سرعت ", "measuring the speed through ") + entry.Name + " …");

            var thread = new Thread(delegate ()
            {
                try
                {
                    QualityResult result = MeasureEntry(entry, profile, timeout, true);
                    Ui(delegate
                    {
                        entry.LastSpeedKbps = result.SpeedKbps;
                        entry.MarkTested();
                        SettingsStore.Save(_settings);
                        RefreshConnections();
                        SetStatus(result.SpeedKbps > 0
                            ? entry.Name + L.T(" — سرعت: ", " — speed: ") + L.N(result.SpeedKbps) +
                              L.T(" کیلوبایت/ثانیه", " KB/s")
                            : L.T("سرعت اندازه‌گیری نشد: ", "the speed could not be measured: ") + result.Detail);
                        AppendLog("[speed] " + entry.Name + " — " +
                                  (result.SpeedKbps > 0 ? L.N(result.SpeedKbps) + " KB/s" : result.Detail));
                    });
                }
                catch (Exception ex)
                {
                    Ui(delegate { SetStatus(L.T("تست سرعت شکست خورد: ", "the speed test failed: ") + ex.Message); });
                }
                finally { EndMeasurement(); }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>
        /// Fetches a subscription link (the base64 list providers hand out) and adds everything the
        /// parser understands. It can go out through one of the existing connections, which is the
        /// only way to get the link at all when the subscription host itself is filtered.
        /// </summary>
        private void ImportSubscription()
        {
            var choices = new List<string>();
            var usable = new List<ConnectionEntry>();
            choices.Add(L.T("مستقیم", "Direct"));
            foreach (ConnectionEntry entry in _settings.Connections)
            {
                if (!entry.Enabled) continue;
                if (!CanFetchThrough(entry)) continue;   // a DNS server or a TG proxy cannot download
                choices.Add(entry.Name);
                usable.Add(entry);
            }

            using (var dialog = new SubscriptionDialog(choices))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                string url = dialog.Url;
                ConnectionEntry via = dialog.ViaIndex > 0 && dialog.ViaIndex <= usable.Count
                    ? usable[dialog.ViaIndex - 1] : null;
                int timeout = Math.Max(4000, _settings.ConnectionTestTimeoutMs * 2);
                SetStatus(L.T("دریافت اشتراک…", "fetching the subscription…"));

                var thread = new Thread(delegate ()
                {
                    IConnector connector = null;
                    ProbeTunnel probe = null;
                    string startError = "";
                    if (via != null && via.Kind != ConnectionKind.Socks5 && via.Kind != ConnectionKind.Http &&
                        !(via.Kind == ConnectionKind.SingBoxConfig && via.LocalSocksPort > 0))
                    {
                        // a WireGuard, an .ovpn or a pasted config cannot fetch on its own: start it
                        // for this one download on a free local port, and stop it right after
                        int port = StartProbeFor(via, timeout, out probe, out startError);
                        if (port > 0) connector = new Socks5Client("127.0.0.1", port, timeout);
                    }
                    if (via != null && connector == null && startError.Length > 0)
                    {
                        string reason = startError;
                        Ui(delegate
                        {
                            SetStatus(L.T("اشتراک خوانده نشد: ", "the subscription could not be fetched: ") + reason);
                            MessageBox.Show(this,
                                L.T("این اتصال برای گرفتن لینک بالا نیامد: ",
                                    "this connection could not be started for the fetch: ") + reason,
                                "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        });
                        return;
                    }
                    try
                    {
                        Subscription.FetchResult fetched = Subscription.Fetch(url, timeout, via, connector);
                        if (!fetched.Ok)
                        {
                            Ui(delegate
                            {
                                SetStatus(L.T("اشتراک خوانده نشد: ", "the subscription could not be fetched: ") + fetched.Error);
                                MessageBox.Show(this,
                                    L.T("اشتراک خوانده نشد: ", "the subscription could not be fetched: ") + fetched.Error +
                                    Environment.NewLine + Environment.NewLine +
                                    L.T("اگر لینک اشتراک فیلتر است، آن را از طریق یکی از اتصال‌های سالم بگیرید.",
                                        "if the link itself is filtered, fetch it through one of the working connections."),
                                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                            });
                            return;
                        }

                        List<string> problems;
                        List<ConnectionEntry> entries = Subscription.Parse(fetched.Text, out problems);
                        Ui(delegate
                        {
                            int added = 0;
                            foreach (ConnectionEntry entry in entries)
                            {
                                // importing the same subscription twice must not produce look-alike names:
                                // the second import gets "node-2 2", not another "node-2"
                                string wanted = entry.Name.Length > 0 ? entry.Name : entry.Info.Title;
                                string name = wanted;
                                int suffix = 2;
                                while (_settings.FindConnection(name) != null) name = wanted + " " + suffix++;
                                entry.Name = name;
                                entry.Id = ConnectionEntry.NewId();
                                _settings.Connections.Add(entry);
                                added++;
                            }
                            SettingsStore.Save(_settings);
                            RefreshConnections();
                            AppendLog("[subscription] " + fetched.Via + " • " + fetched.Bytes + " bytes • " +
                                      added + " connection(s)");
                            foreach (string problem in problems) AppendLog("[subscription] skipped: " + problem);
                            SetStatus(L.T("از اشتراک افزوده شد: ", "added from the subscription: ") + L.N(added) +
                                      L.T(" اتصال", " connection(s)"));
                            if (added == 0)
                                MessageBox.Show(this,
                                    L.T("در این اشتراک چیزی که برنامه بشناسد نبود. اگر لینک اشتراک به‌جای متن، " +
                                        "یک صفحه وب بود، از خود سرویس‌دهنده لینک خام (base64) را بگیرید.",
                                        "nothing in this subscription could be recognised. If the link returned a web " +
                                        "page instead of text, ask the provider for the raw (base64) link."),
                                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        });
    
                    }
                    finally
                    {
                        if (probe != null) probe.Stop();
                    }
                });
                thread.IsBackground = true;
                thread.Start();
            }
        }

        /// <summary>
        /// Which connections can download a web page for us: a SOCKS5 or HTTP proxy, anything the app
        /// can bring up in a throwaway engine (WireGuard, .ovpn, a pasted outbound, a full config), or
        /// a full config that only needs its own local port. A DNS server and a Telegram proxy cannot
        /// fetch anything, so they are not offered - an option that cannot work is worse than no option.
        /// </summary>
        private static bool CanFetchThrough(ConnectionEntry entry)
        {
            if (entry == null) return false;
            switch (entry.Kind)
            {
                case ConnectionKind.Socks5:
                case ConnectionKind.Http:
                case ConnectionKind.WireGuard:
                case ConnectionKind.OpenVpn:
                case ConnectionKind.SingBoxOutbound:
                case ConnectionKind.SingBoxConfig:
                    return true;
                default:
                    return false;      // DNS, MTProto and WARP
            }
        }

        /// <summary>
        /// Packet-raft style route hunting: every candidate (the plain line, each connection, and
        /// relay chains of two) is brought up in a throwaway engine and measured with a real
        /// Minecraft handshake to the real server. The winner can be pinned, and it is the route the
        /// game will use from then on.
        /// </summary>
        private void OptimiseGameRoute()
        {
            if (_routeBusy)
            {
                SetStatus(L.T("بهینه‌سازی مسیر در جریان است", "a route optimisation is already running"));
                return;
            }
            var profile = SelectedServer();
            if (profile == null)
            {
                SetStatus(L.T("اول یک سرور انتخاب کنید", "select a server first"));
                return;
            }

            string host = profile.Host;
            int port = profile.Port;
            int timeout = Math.Max(2500, _settings.ConnectionTestTimeoutMs);
            int chains = _settings.OptimiseChains;

            _routeBusy = true;
            SetStatus(L.T("بهینه‌سازی مسیر بازی…", "optimising the game route…"));
            AppendLog("[route] optimising for " + host + ":" + port);

            var thread = new Thread(delegate ()
            {
                try
                {
                    List<RouteCandidate> candidates = RouteOptimizer.Plan(_settings.Connections, true, chains, true);
                    // the direct line first, because it is the baseline every other route is compared to
                    var measured = new List<RouteCandidate>();
                    int baseline = -1;
                    int index = 0;
                    foreach (RouteCandidate candidate in candidates)
                    {
                        index++;
                        int shown = index;
                        Ui(delegate
                        {
                            SetStatus(L.T("بهینه‌سازی مسیر ", "optimising route ") + L.N(shown) + "/" +
                                      L.N(candidates.Count) + " — " + candidate.Describe());
                        });
                        string error;
                        RouteOptimizer.Measure(candidate, host, port, timeout, timeout, out error);
                        measured.Add(candidate);
                        if (candidate.IsDirect && candidate.Ok) baseline = candidate.GamePingMs;

                        var line = RouteOptimizer.Describe(candidate, baseline);
                        Ui(delegate { AppendLog("[route] " + line); });
                    }

                    List<RouteCandidate> ranked = RouteOptimizer.Rank(measured);
                    RouteCandidate winner = ranked.Count > 0 && ranked[0].Ok ? ranked[0] : null;

                    var report = new System.Text.StringBuilder();
                    report.AppendLine(L.T("مسیرها روی سرور واقعی بازی اندازه‌گیری شدند:", "every route was measured on the real game server:"));
                    foreach (RouteCandidate candidate in ranked) report.AppendLine(RouteOptimizer.Describe(candidate, baseline));
                    if (winner != null)
                    {
                        report.AppendLine();
                        report.AppendLine(L.T("سریع‌ترین مسیر: ", "the fastest route: ") + winner.Describe());
                    }

                    Ui(delegate
                    {
                        _routeBusy = false;
                        SetStatus(winner == null
                            ? L.T("هیچ مسیری جواب نداد", "no route answered")
                            : L.T("سریع‌ترین مسیر: ", "fastest route: ") + winner.Describe() +
                              (winner.GamePingMs > 0 ? " • " + L.N(winner.GamePingMs) + " ms" : ""));

                        if (winner == null)
                        {
                            MessageBox.Show(this, report.ToString(), L.T("بهینه‌سازی مسیر", "Route optimisation"),
                                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
                            return;
                        }
                        DialogResult answer = MessageBox.Show(this,
                            report.ToString() + Environment.NewLine +
                            L.T("همین مسیر برای بازی پین شود؟", "pin this route for the game?"),
                            L.T("بهینه‌سازی مسیر", "Route optimisation"),
                            MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                        if (answer == DialogResult.Yes)
                        {
                            _settings.PinnedConnection = winner.PinName;
                            _settings.PinnedChainHop = winner.PinSecondName;
                            SettingsStore.Save(_settings);
                            RefreshConnections();
                            SetStatus(L.T("مسیر پین شد: ", "route pinned: ") + winner.Describe());
                        }
                    });
                }
                catch (Exception ex)
                {
                    Log.Error("route optimisation failed", ex);
                    Ui(delegate
                    {
                        _routeBusy = false;
                        SetStatus(L.T("بهینه‌سازی مسیر شکست خورد: ", "route optimisation failed: ") + ex.Message);
                    });
                }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>
        /// Proves the DNS story on the user's own machine: what the local resolver says against what
        /// the resolver inside the running tunnel says. Different answers mean the local one is
        /// tampered with - the usual reason a Minecraft join fails on a filtered line.
        /// </summary>
        private void TestDnsThroughTunnel()
        {
            var profile = SelectedServer();
            if (profile == null || string.IsNullOrEmpty(profile.Host))
            {
                SetStatus(L.T("اول یک سرور انتخاب کنید", "select a server first"));
                return;
            }
            if (!_pipeline.TunnelRunning)
            {
                SetStatus(L.T("تونل بالا نیست؛ اول «بهینه‌سازی و اجرای بازی» را بزنید، بعد این تست را.",
                              "the tunnel is not up; press Optimise and play once, then run this test."));
                return;
            }

            string host = profile.Host;
            int timeout = Math.Min(6000, Math.Max(3000, _settings.ConnectTimeoutMs));
            string resolver = "1.1.1.1";
            foreach (ConnectionEntry entry in _settings.Connections)
            {
                if (!entry.Enabled || !entry.Info.IsResolver) continue;
                ResolverSpec spec = ResolverSpec.Parse(entry.DnsUrl);
                if (spec != null && (spec.Scheme == "udp" || spec.Scheme == "tcp")) resolver = spec.Host;
            }

            SetStatus(L.T("تست DNS از داخل تونل…", "testing DNS through the tunnel…"));
            var thread = new Thread(delegate ()
            {
                string systemAnswer = "";
                try { systemAnswer = string.Join(", ", NetUtil.ResolveSimple(host).ToArray()); }
                catch { }
                int socksPort = _pipeline.Report.ProxyPort > 0 ? _pipeline.Report.ProxyPort : _pipeline.SocksPort;
                DnsAnswer answer = ProxyDns.ResolveThrough("127.0.0.1", socksPort, resolver, host, timeout, "", "");
                string text = ProxyDns.Compare(host, systemAnswer, answer);
                Ui(delegate
                {
                    AppendLog("[dns] " + text.Replace(Environment.NewLine, " | "));
                    SetStatus(answer.Ok
                        ? L.T("DNS از داخل تونل جواب داد", "DNS through the tunnel answered")
                        : L.T("DNS از داخل تونل جواب نداد", "DNS through the tunnel did not answer"));
                    MessageBox.Show(this, text, L.T("DNS", "DNS"), MessageBoxButtons.OK,
                                    answer.Ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void VerifyMtprotoSelected()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null)
            {
                SetStatus(L.T("اول یک اتصال MTProto را انتخاب کنید", "select an MTProto entry first"));
                return;
            }
            if (entry.Kind != ConnectionKind.Mtproto)
            {
                SetStatus(L.T("این اتصال MTProto نیست:", "this entry is not MTProto: ") + entry.Info.Title);
                return;
            }
            var secret = MtprotoSecret.Parse(entry.Secret);
            if (!secret.Ok)
            {
                SetStatus(L.T("سکرت خوانده نشد: ", "the secret cannot be read: ") + secret.Error);
                return;
            }

            int timeout = _settings.ConnectionTestTimeoutMs;
            SetStatus(L.T("تست واقعی MTProto: ", "verifying MTProto: ") + entry.Name);
            var thread = new Thread(delegate ()
            {
                MtprotoCheck check = MtprotoClient.Check(entry.Host, entry.Port, entry.Secret, entry.Dc, timeout);
                string line = entry.Name + " — " + check.Status +
                              (check.DelayMs > 0 ? " • " + L.N(check.DelayMs) + " ms" : "") +
                              " • " + MtprotoSecret.ModeName(check.Mode) +
                              (check.Domain.Length > 0 ? " • " + check.Domain : "") +
                              " • DC" + check.Dc + " • " + check.Detail;
                entry.LastDelayMs = check.Connected ? check.DelayMs : -1;
                entry.LastStatus = check.Status;
                entry.LastError = check.Verified ? "" : check.Detail;
                entry.MarkTested();
                Ui(delegate
                {
                    AppendLog("[mtproto] " + line);
                    RefreshConnections();
                    SetStatus(check.Verified
                        ? L.T("تأیید شد — پروکسی واقعاً کار می‌کند", "verified - the proxy really works")
                        : L.T("تأیید نشد: ", "not verified: ") + check.Detail);
                });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>Measures the real resPQ delay to every Telegram DC through the selected proxy.</summary>
        private void RankTelegramDcs()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null || entry.Kind != ConnectionKind.Mtproto)
            {
                SetStatus(L.T("برای این کار یک اتصال MTProto را انتخاب کنید",
                              "select an MTProto entry for this"));
                return;
            }
            int timeout = _settings.ConnectionTestTimeoutMs;
            SetStatus(L.T("اندازه‌گیری تأخیر دیتاسنترهای تلگرام…", "measuring the Telegram data centres…"));

            var thread = new Thread(delegate ()
            {
                var delays = new Dictionary<int, int>();
                int bestDc = 0, bestDelay = int.MaxValue;

                // one connection per DC; run them at the same time so nothing is compared unfairly
                var done = new ManualResetEvent[MtprotoClient.DataCenters.Length];
                for (int i = 0; i < MtprotoClient.DataCenters.Length; i++)
                {
                    int dc = MtprotoClient.DataCenters[i];
                    var handle = new ManualResetEvent(false);
                    done[i] = handle;
                    var worker = new Thread(delegate ()
                    {
                        try
                        {
                            MtprotoCheck check = MtprotoClient.Check(entry.Host, entry.Port, entry.Secret, dc, timeout);
                            lock (delays)
                            {
                                delays[dc] = check.Connected ? check.DelayMs : -1;
                            }
                        }
                        catch { }
                        finally { handle.Set(); }
                    });
                    worker.IsBackground = true;
                    worker.Start();
                }

                foreach (var handle in done)
                {
                    handle.WaitOne(TimeSpan.FromMilliseconds(timeout + 4000));
                    handle.Close();
                }

                foreach (var pair in delays)
                {
                    if (pair.Value > 0 && pair.Value < bestDelay) { bestDelay = pair.Value; bestDc = pair.Key; }
                }

                var report = new System.Text.StringBuilder();
                report.AppendLine(L.T("تأخیر واقعی هر دیتاسنتر تلگرام از این پروکسی:", "real delay to each Telegram DC through this proxy:"));
                report.AppendLine();
                // the data centre list comes from the client, so a new one cannot be silently ignored
                foreach (int dc in MtprotoClient.DataCenters)
                {
                    int value;
                    if (!delays.TryGetValue(dc, out value) || value <= 0) continue;
                    report.AppendLine("DC" + dc + " → " + L.N(value) + " ms" + (dc == entry.Dc ? "   ← " + L.T("فعلی", "current") : ""));
                }
                if (bestDc > 0)
                {
                    report.AppendLine();
                    report.AppendLine(L.T("سریع‌ترین: DC", "fastest: DC") + bestDc + " (" + L.N(bestDelay) + " ms)");
                    if (bestDc != entry.Dc)
                        report.AppendLine(L.T("پیشنهاد: دیتاسنتر این اتصال را به DC", "suggestion: change this entry to DC") + bestDc + L.T(" تغییر دهید", ""));
                }
                else
                {
                    report.AppendLine(L.T("هیچ دیتاسنتری جواب نداد — پروکسی یا سکرت مشکل دارد.",
                                          "no data centre answered - the proxy or the secret is broken."));
                }

                string text = report.ToString();
                Ui(delegate
                {
                    AppendLog("[mtproto] " + text.Replace(Environment.NewLine, " | "));
                    SetStatus(L.T("رتبه‌بندی دیتاسنترها تمام شد", "the data centre ranking is ready"));
                    if (bestDc > 0 && bestDc != entry.Dc)
                    {
                        string where = entry.Dc > 0
                            ? L.T("دیتاسنتر این اتصال: DC", "this entry is on DC") + entry.Dc
                            : L.T("دیتاسنتر این اتصال روی خودکار است", "this entry's data centre is automatic");
                        string question = L.T("اندازه‌گیری از همین پروکسی: DC", "measured through this proxy: DC") +
                                          bestDc + " = " + L.N(bestDelay) + " ms" + Environment.NewLine +
                                          where + Environment.NewLine + Environment.NewLine +
                                          L.T("دیتاسنتر عوض شود؟ (فقط مسیر تلگرام این اتصال تغییر می‌کند و روی بازی اثری ندارد.)",
                                              "change it? (this only moves Telegram's route through this entry; the game never uses it.)");
                        DialogResult answer = MessageBox.Show(this,
                            text + Environment.NewLine + question,
                            L.T("رتبه‌بندی تلگرام", "Telegram ranking"), MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                        if (answer == DialogResult.Yes)
                        {
                            entry.Dc = bestDc;
                            SettingsStore.Save(_settings);
                            RefreshConnections();
                            SetStatus(L.T("دیتاسنتر ثبت شد: DC", "data centre saved: DC") + bestDc +
                                      " (" + L.N(bestDelay) + " ms)");
                        }
                    }
                    else
                    {
                        MessageBox.Show(this, text, L.T("رتبه‌بندی تلگرام", "Telegram ranking"),
                                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                    }
                });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>Copies a tg:// link for the selected proxy so it can be handed to Telegram.</summary>
        private void CopyTelegramLink()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null || entry.Kind != ConnectionKind.Mtproto)
            {
                SetStatus(L.T("برای این کار یک اتصال MTProto را انتخاب کنید", "select an MTProto entry for this"));
                return;
            }
            var secret = MtprotoSecret.Parse(entry.Secret);
            if (!secret.Ok)
            {
                SetStatus(L.T("سکرت خوانده نشد: ", "the secret cannot be read: ") + secret.Error);
                return;
            }
            string link = secret.ToLink(entry.Host, entry.Port);
            try
            {
                Clipboard.SetText(link);
                SetStatus(L.T("لینک کپی شد: ", "link copied: ") + link);
                AppendLog("[mtproto] " + link);
            }
            catch (Exception ex)
            {
                SetStatus(L.T("کپی نشد: ", "could not copy: ") + ex.Message);
            }
        }

        /// <summary>One more copy of the selected entry - handy when comparing two variants.</summary>
        private void DuplicateConnection()
        {
            ConnectionEntry entry = SelectedConnection();
            if (entry == null)
            {
                SetStatus(L.T("اول یک اتصال را انتخاب کنید", "select a connection first"));
                return;
            }
            ConnectionEntry copy = entry.Clone();
            copy.Id = ConnectionEntry.NewId();
            string name = entry.Name + " (2)";
            int number = 2;
            while (_settings.FindConnection(name) != null) name = entry.Name + " (" + (++number) + ")";
            copy.Name = name;
            copy.ForgetTest();
            _settings.Connections.Add(copy);
            SettingsStore.Save(_settings);
            RefreshConnections();
            SetStatus(L.T("کپی ساخته شد: ", "copied: ") + copy.Name);
        }

        /// <summary>Sorts the list by measured delay; entries that were never tested go last.</summary>
        private void SortConnectionsByDelay()
        {
            var sorted = new List<ConnectionEntry>(_settings.Connections);
            sorted.Sort(delegate (ConnectionEntry a, ConnectionEntry b)
            {
                int left = a.LastDelayMs > 0 ? a.LastDelayMs : int.MaxValue;
                int right = b.LastDelayMs > 0 ? b.LastDelayMs : int.MaxValue;
                if (left != right) return left.CompareTo(right);
                return string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase);
            });
            _settings.Connections = sorted;
            SettingsStore.Save(_settings);
            RefreshConnections();
            SetStatus(L.T("به ترتیب تأخیر مرتب شد", "sorted by delay"));
        }

        /// <summary>Saves every connection into one JSON file the user can keep or move to another PC.</summary>
        private void ExportConnections()
        {
            if (_settings.Connections.Count == 0)
            {
                SetStatus(L.T("چیزی برای ذخیره نیست", "there is nothing to save"));
                return;
            }
            using (var dialog = new SaveFileDialog())
            {
                dialog.Title = L.T("ذخیره اتصال‌ها", "Save connections");
                dialog.Filter = "JSON (*.json)|*.json|" + L.T("همه فایل‌ها", "all files") + " (*.*)|*.*";
                dialog.FileName = "serverhelp-connections.json";
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    File.WriteAllText(dialog.FileName, ConnectionParser.SerializeList(_settings.Connections));
                    SetStatus(L.T("ذخیره شد: ", "saved: ") + dialog.FileName);
                    AppendLog("[connections] saved to " + dialog.FileName);
                }
                catch (Exception ex)
                {
                    SetStatus(L.T("ذخیره نشد: ", "could not save: ") + ex.Message);
                }
            }
        }

        /// <summary>Merges a saved file (or a pasted subscription in a text file) back in.</summary>
        private void LoadConnectionsFromFile()
        {
            using (var dialog = new OpenFileDialog())
            {
                dialog.Title = L.T("خواندن اتصال‌ها از فایل", "Load connections from a file");
                dialog.Filter = L.T("JSON یا متن", "JSON or text") + " (*.json;*.txt;*.conf)|*.json;*.txt;*.conf|" +
                                L.T("همه فایل‌ها", "all files") + " (*.*)|*.*";
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                string text;
                try { text = File.ReadAllText(dialog.FileName); }
                catch (Exception ex)
                {
                    SetStatus(L.T("فایل خوانده نشد: ", "the file cannot be read: ") + ex.Message);
                    return;
                }

                List<ConnectionEntry> loaded = null;
                string head = text.TrimStart();
                if (head.StartsWith("{") || head.StartsWith("["))
                {
                    string error;
                    loaded = ConnectionParser.ParseListFile(text, out error);
                    if (loaded.Count == 0)
                    {
                        SetStatus(L.T("فایل خوانده نشد: ", "the file cannot be read: ") + error);
                        return;
                    }
                }
                else
                {
                    List<string> problems;
                    loaded = ConnectionParser.ParseBlob(text, out problems);
                    foreach (string problem in problems) AppendLog("[connections] skipped: " + problem);
                }

                int added = 0;
                foreach (ConnectionEntry entry in loaded)
                {
                    string name = entry.Name;
                    int number = 2;
                    while (_settings.FindConnection(name) != null) name = entry.Name + " " + (number++);
                    entry.Name = name;
                    entry.Id = ConnectionEntry.NewId();
                    _settings.Connections.Add(entry);
                    added++;
                }
                SettingsStore.Save(_settings);
                RefreshConnections();
                SetStatus(L.T("افزوده شد: ", "loaded: ") + L.N(added) + L.T(" اتصال", " connection(s)"));
            }
        }

        private void RefreshVersions()
        {
            string dir = VersionScanner.ResolveVersionsDir(_settings.GameDirOverride, _settings.VersionsDir);
            if (_versionList == null) return;
            _versionList.BeginUpdate();
            _versionCombo.BeginUpdate();
            try
            {
                _versionList.Items.Clear();
                _versionCombo.Items.Clear();
                _versions = VersionScanner.Scan(dir);
                foreach (McVersion version in _versions)
                {
                    var item = new ListViewItem(version.Id);
                    item.SubItems.Add(string.IsNullOrEmpty(version.Type) ? "—" : version.Type);
                    item.SubItems.Add(version.Detail);
                    item.SubItems.Add(version.Folder);
                    _versionList.Items.Add(item);
                    _versionCombo.Items.Add(version.Display);
                }
                if (_versionCombo.Items.Count > 0)
                {
                    int preferred = 0;
                    for (int i = 0; i < _versions.Count; i++)
                        if (_versions[i].Type == "release" && _versions[i].RequiredJavaMajor > 0) preferred = i;
                    int keep = _pendingVersionIndex;
                    _pendingVersionIndex = -1;
                    _versionCombo.SelectedIndex = keep >= 0 && keep < _versionCombo.Items.Count ? keep : preferred;
                }
            }
            finally
            {
                _versionList.EndUpdate();
                _versionCombo.EndUpdate();
            }
            SetStatus(_versions.Count > 0
                ? L.T("نسخه‌ها پیدا شد: ", "versions found: ") + L.N(_versions.Count)
                : L.T("هیچ نسخه‌ای پیدا نشد — پوشه را در تب «نسخه‌ها» مشخص کنید",
                      "no versions found — set the folder in the Versions tab"));
        }

        private void UseSelectedVersion()
        {
            if (_versionList.SelectedIndices.Count == 0) return;
            int index = _versionList.SelectedIndices[0];
            if (index >= 0 && index < _versions.Count)
            {
                _versionCombo.SelectedIndex = index;
                _tabs.SelectedIndex = 0;
            }
        }

        /// <summary>The version chosen in the combo box (the list just selects it).</summary>
        private McVersion SelectedVersion()
        {
            int index = _versionCombo.SelectedIndex;
            if (index < 0 || index >= _versions.Count) return null;
            return _versions[index];
        }

        /// <summary>
        /// Shows, before the user presses play, exactly what will be done to this version: the loader
        /// that was detected, the memory that fits this machine, the collector and the missing files.
        /// Building the launch command also downloads anything that is missing, so we do that here in
        /// the background: by the time "optimise and play" is pressed the game is ready to start, which
        /// is what keeps the whole thing inside a minute.
        /// </summary>
        private void UpdatePlanPreview()
        {
            McVersion version = SelectedVersion();
            var target = _planBox;
            if (target == null) return;
            if (version == null)
            {
                target.Text = L.T("یک نسخه انتخاب کنید تا برنامه بهینه‌سازی همین نسخه را نشان دهد.",
                                  "pick a version and this panel shows exactly what will be optimised.");
                return;
            }
            if (_planBuildingFor == version.Id) return;          // already being prepared
            _planBuildingFor = version.Id;
            target.Text = L.T("در حال محاسبه بهینه‌سازی…", "working out the optimisation…");
            SetStatus(L.T("بهینه‌سازی نسخه ", "optimising version ") + version.Id + " …");
            var thread = new Thread(delegate ()
            {
                try
                {
                    string dir = _gameDir;
                    if (string.IsNullOrEmpty(dir)) dir = VersionScanner.DetectGameDir(_settings.GameDirOverride);
                    string javaPath = ResolveJava(version);
                    var plan = LaunchBuilder.Build(version, javaPath, dir, _settings.Nickname, SelectedServer(),
                                                   _settings, _settings.QuickPlay, null, out string error);
                    string text = plan == null
                        ? L.T("بهینه‌سازی آماده نشد: ", "could not prepare the optimisation: ") + error
                        : plan.Profile.Summary();
                    Ui(delegate
                    {
                        if (_planBuildingFor == version.Id) _planBuildingFor = "";
                        if (_planBox != null && SelectedVersion() == version) _planBox.Text = text;
                        if (plan != null)
                            SetStatus(L.T("بهینه‌سازی آماده است — ", "optimisation ready — ") + version.Id +
                                      L.T(" با ", " with ") + plan.Profile.HeapMb + " MB");
                    });
                }
                catch (Exception ex)
                {
                    Log.Warn("plan preview: " + ex.Message);
                    Ui(delegate
                    {
                        if (_planBuildingFor == version.Id) _planBuildingFor = "";
                        if (_planBox != null && SelectedVersion() == version)
                            _planBox.Text = L.T("پیش‌نمایش بهینه‌سازی ممکن نشد: ", "the preview is unavailable: ") + ex.Message;
                    });
                }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void CheckServerAsync()
        {
            var profile = SelectedServer();
            SetStatus(L.T("در حال بررسی سرور…", "checking the server…"));
            var thread = new Thread(delegate ()
            {
                var results = new List<string>();
                int best = -1;
                foreach (string ip in NetUtil.ResolveSimple(profile.Host))
                {
                    var status = McPing.Status(ip, profile.Port, 5000, null);
                    if (status != null && status.Ok)
                    {
                        results.Add(ip + "  " + L.N(status.LatencyMs) + " ms  " + status.Motd);
                        if (best < 0 || status.LatencyMs < best) best = status.LatencyMs;
                    }
                }
                if (!string.IsNullOrEmpty(profile.DirectIp))
                {
                    var status = McPing.Status(profile.DirectIp, profile.Port, 5000, null);
                    if (status != null && status.Ok)
                    {
                        results.Add(profile.DirectIp + "  " + L.N(status.LatencyMs) + " ms  " + status.Motd);
                        if (best < 0 || status.LatencyMs < best) best = status.LatencyMs;
                    }
                }
                Ui(delegate
                {
                    string text = results.Count > 0
                        ? string.Join(" | ", results.ToArray())
                        : L.T("پاسخ نداد (فیلتر یا خاموش) — برنامه تونل را امتحان می‌کند", "no answer (filtered or down) — the tunnel will be tried");
                    _serverInfoLabel.Text = profile.Endpoint + Environment.NewLine + text;
                    _pingLabel.Text = best >= 0 ? L.T("پینگ مستقیم: ", "direct ping: ") + L.N(best) + " ms"
                                                : L.T("پینگ مستقیم: ندارد", "direct ping: none");
                    SetStatus(results.Count > 0 ? L.T("سرور پاسخ داد", "the server answered") : L.T("بدون پاسخ مستقیم", "no direct answer"));
                });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void ScanEndpointsAsync()
        {
            SetStatus(L.T("اسکن endpointهای WARP…", "scanning WARP endpoints…"));
            var thread = new Thread(delegate ()
            {
                var scan = EndpointScanner.Scan(Math.Min(_settings.ScanTimeoutMs, 2500), null,
                    delegate (string message) { Ui(delegate { SetStatus(message); }); });
                _lastScan = scan.Endpoints;
                var best = WarpEndpoints.PickBest(scan.Endpoints, 12);
                Ui(delegate
                {
                    _endpointList.BeginUpdate();
                    try
                    {
                        _endpointList.Items.Clear();
                        foreach (WarpEndpoint endpoint in best)
                        {
                            var item = new ListViewItem(endpoint.Address);
                            item.SubItems.Add(endpoint.IcmpRtt >= 0 ? L.N(endpoint.IcmpRtt) + " ms" : "—");
                            item.SubItems.Add(endpoint.TcpRtt >= 0 ? L.N(endpoint.TcpRtt) + " ms" : "—");
                            item.SubItems.Add(endpoint.Score.ToString());
                            item.SubItems.Add(endpoint.TunnelRtt >= 0 ? L.N(endpoint.TunnelRtt) + " ms" : "—");
                            item.SubItems.Add("—");
                            _endpointList.Items.Add(item);
                        }
                    }
                    finally { _endpointList.EndUpdate(); }
                    _tunnelInfoLabel.Text = L.T("بهترین آدرس‌ها انتخاب شد؛ هنگام اجرا، تونل روی سریع‌ترین آن‌ها ساخته می‌شود.",
                                                "Best addresses selected; the tunnel is built on the fastest ones on launch.")
                                            + "  (" + L.N(scan.Reachable) + "/" + L.N(scan.Probed) + ")";
                    SetStatus(L.T("اسکن تمام شد", "scan finished"));
                });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void MeasureEndpointDelays()
        {
            if (_endpointList == null || _endpointList.Items.Count == 0)
            {
                SetStatus(L.T("اول endpointها را اسکن کنید", "scan the endpoints first"));
                return;
            }
            SetStatus(L.T("اندازه‌گیری تأخیر…", "measuring delays…"));
            var targets = new List<WarpEndpoint>();
            for (int i = 0; i < _endpointList.Items.Count; i++)
            {
                if (i < _lastScan.Count) targets.Add(_lastScan[i]);
            }
            bool tunnelUp = _pipeline.TunnelRunning;
            string controller = "127.0.0.1:22346";
            var thread = new Thread(delegate ()
            {
                for (int i = 0; i < targets.Count; i++)
                {
                    WarpEndpoint endpoint = targets[i];
                    int delay = NetUtil.TcpPing(endpoint.Ip, endpoint.Port, 2500);
                    int tunnelDelay = -1;
                    string tag = "warp-" + (i + 1);
                    if (tunnelUp) tunnelDelay = ClashApi.Delay(controller, "", tag, "https://cp.cloudflare.com/generate_204", 3000);
                    int index = i;
                    Ui(delegate
                    {
                        if (index >= _endpointList.Items.Count) return;
                        var item = _endpointList.Items[index];
                        if (item.SubItems.Count > 4) item.SubItems[4].Text = delay > 0 ? L.N(delay) + " ms" : "—";
                        if (item.SubItems.Count > 5) item.SubItems[5].Text = tunnelDelay > 0 ? L.N(tunnelDelay) + " ms" : "—";
                        if (delay > 0) item.ForeColor = delay < 120 ? Color.FromArgb(24, 120, 50) : Color.FromArgb(180, 110, 0);
                    });
                }
                Ui(delegate { SetStatus(L.T("تأخیر همه آدرس‌ها اندازه‌گیری شد", "all endpoint delays measured")); });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        /// <summary>
        /// The list of system changes the launch path is about to make, in the user's language and built
        /// from the same switches the optimisation tab shows. Only what is really going to run is
        /// listed, so the confirmation never promises more than the app does.
        /// </summary>
        private string TuningSummary()
        {
            var lines = new List<string>();
            if (_settings.HighPerformancePowerPlan) lines.Add(L.T("طرح انرژی حداکثر کارایی", "high performance power plan"));
            if (_settings.TuneNetwork) lines.Add(L.T("کاهش throttle شبکه و پاک‌کردن کش DNS", "network throttling lowered, DNS cache flushed"));
            if (_settings.AddFirewallRules) lines.Add(L.T("دو قاعده فایروال (بازی و تونل)", "two firewall rules (the game and the tunnel)"));
            if (_settings.TrimMemory) lines.Add(L.T("آزادسازی حافظه برنامه‌های بی‌کار", "idle applications' memory released"));
            if (_settings.CloseBackgroundApps) lines.Add(L.T("بستن برنامه‌های سنگین پس‌زمینه", "heavy background apps closed"));
            if (_settings.TimerResolution) lines.Add(L.T("دقت تایمر سیستم روی ۱ میلی‌ثانیه", "system timer resolution set to 1 ms"));
            if (_settings.UseAikarFlags) lines.Add(L.T("پرچم‌های بهینه‌سازی JVM (فقط داخل بازی)", "JVM tuning flags (inside the game only)"));
            if (_settings.OpenGlPipeline) lines.Add(L.T("خط لوله OpenGL جاوا", "Java OpenGL pipeline"));
            if (_settings.SetJavaPriority) lines.Add(L.T("اولویت پردازش بازی", "game process priority raised"));
            if (_settings.UseHostsFile) lines.Add(L.T("تثبیت آدرس سرور در فایل hosts", "server address pinned in the hosts file"));
            if (lines.Count == 0)
                return L.T("موردی روشن نیست؛ فقط بازی اجرا می‌شود.", "nothing is switched on; only the game will start.");
            return "• " + string.Join(Environment.NewLine + "• ", lines.ToArray());
        }

        private void RunOptimizerNow()
        {
            if (_optimizerBusy)
            {
                SetStatus(L.T("بهینه‌سازی همین حالا در جریان است", "an optimisation is already running"));
                return;
            }
            if (_worker != null && _worker.IsAlive)
            {
                // The launch does its own tuning a moment from now; two of them at once would undo
                // each other's bookkeeping of what has to be put back afterwards.
                SetStatus(L.T("یک اجرا در جریان است؛ بهینه‌سازی همین حالا انجام نشد",
                              "a launch is running; nothing was tuned now"));
                return;
            }
            _optimizerBusy = true;
            SetStatus(L.T("بهینه‌سازی سیستم…", "tuning the system…"));
            var thread = new Thread(delegate ()
            {
                try
                {
                    _pipeline.Optimizer.TunnelExePath = Shell.FileExists(AppPaths.SingBoxExe) ? AppPaths.SingBoxExe : "";
                    _pipeline.Optimizer.JavaExePath = _javaPath;
                    _pipeline.Optimizer.Run(_settings, delegate (OptimizationStep step)
                    {
                        Ui(delegate { AddStepRow("★ " + step.Title, step.StateText, step.Detail, step.State); });
                    });
                    Ui(delegate
                    {
                        _optimizerBusy = false;
                        SetStatus(L.T("بهینه‌سازی انجام شد", "optimisation done"));
                    });
                }
                catch (Exception ex)
                {
                    // Before this, a failure left the status line saying "tuning…" for ever.
                    Log.Warn("optimise now failed: " + ex.Message);
                    Ui(delegate
                    {
                        _optimizerBusy = false;
                        SetStatus(L.T("بهینه‌سازی خطا داد: ", "optimisation failed: ") + ex.Message);
                    });
                }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void ToggleTunnel()
        {
            if (_pipeline.TunnelRunning)
            {
                _pipeline.Tunnel.Stop();
                _tunnelInfoLabel.Text = L.T("تونل خاموش شد", "tunnel stopped");
                SetStatus(L.T("تونل خاموش شد", "tunnel stopped"));
                return;
            }
            MessageBox.Show(
                L.T("برای ساخت تونل، نسخه‌ای را انتخاب کنید و دکمه «بهینه‌سازی و اجرای بازی» را بزنید؛" +
                    " تونل با همان تنظیمات و روی سریع‌ترین سرور ساخته می‌شود.",
                    "To build the tunnel, pick a version and press “Optimise and play”; the tunnel is created " +
                    "with the same settings on the fastest endpoint."),
                "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        private void UpdateServerInfo()
        {
            if (_serverInfoLabel == null) return;
            var profile = SelectedServer();
            _serverInfoLabel.Text = profile.Name + Environment.NewLine + profile.Endpoint +
                                    (string.IsNullOrEmpty(profile.DirectIp) ? "" : Environment.NewLine + L.T("IP جایگزین: ", "fallback IP: ") + profile.DirectIp);
        }

        // ------------------------------------------------------------------ pipeline

        private void StartPipeline()
        {
            if (_worker != null && _worker.IsAlive)
            {
                SetStatus(L.T("یک اجرا در جریان است", "a run is in progress"));
                return;
            }
            if (_optimizerBusy)
            {
                SetStatus(L.T("بهینه‌سازی در جریان است؛ چند لحظه بعد دوباره Play را بزنید",
                              "an optimisation is running; press Play again in a moment"));
                return;
            }
            if (_versions.Count == 0)
            {
                MessageBox.Show(L.T("نسخه‌ای پیدا نشد. در تب «نسخه‌ها» پوشه را مشخص کنید.", "No version found. Set the folder in the Versions tab."),
                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            int index = _versionCombo.SelectedIndex;
            if (index < 0 || index >= _versions.Count) { SetStatus(L.T("نسخه انتخاب نشده", "no version selected")); return; }
            McVersion version = _versions[index];
            var profile = SelectedServer();

            if (string.IsNullOrEmpty(_settings.Nickname)) _settings.Nickname = "Player";
            _gameDir = VersionScanner.DetectGameDir(_settings.GameDirOverride);
            if (string.IsNullOrEmpty(_gameDir))
            {
                MessageBox.Show(L.T("پوشه بازی پیدا نشد. آن را در تنظیمات انتخاب کنید.", "Game folder not found. Pick it in Settings."),
                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (!version.HasJson)
            {
                MessageBox.Show(L.T("این نسخه فایل json ندارد و قابل اجرا نیست.", "This version has no json file and cannot be launched."),
                    "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            // "Ask before optimising" is a promise, so the launch path really does stop and ask once,
            // with the plain list of changes it is about to make on this machine.
            if (_settings.OptimizeSystem && _settings.ConfirmTuning)
            {
                var answer = MessageBox.Show(this,
                    L.T("پیش از اجرا این تغییرات روی سیستم اعمال می‌شود (همه برگشت‌پذیر):",
                        "Before the game starts these changes are applied (all reversible):") +
                    Environment.NewLine + Environment.NewLine + TuningSummary() + Environment.NewLine + Environment.NewLine +
                    L.T("ادامه بدهم؟ (این پرسش را در تب «بهینه‌سازی» می‌توانید خاموش کنید)",
                        "Continue? (you can switch this question off in the Optimisation tab)"),
                    L.T("بهینه‌سازی سیستم", "System optimisation"), MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                if (answer != DialogResult.Yes)
                {
                    SetStatus(L.T("اجرا لغو شد؛ هیچ تغییری اعمال نشد", "launch cancelled; nothing was changed"));
                    return;
                }
            }

            _stepList.Items.Clear();
            _stepRows.Clear();
            _playButton.Enabled = false;
            _stopButton.Enabled = true;
            UpdateConnectionSummary();     // the line now says the run took its own copy of the list
            _runWatch = Stopwatch.StartNew();
            SetStatus(L.T("شروع شد…", "starting…"));

            // The Connections tab can be edited while a launch is in flight, so the run gets its own
            // copy of the list, taken here on this thread: from now on nothing the user changes can
            // move the ground under a launch that is already going.
            var runConnections = new List<ConnectionEntry>(_settings.Connections);

            _worker = new Thread(delegate ()
            {
                string javaPath = ResolveJava(version);
                _javaPath = javaPath;
                if (string.IsNullOrEmpty(javaPath))
                {
                    Ui(delegate
                    {
                        SetStatus(L.T("Java پیدا نشد", "no Java found"));
                        _playButton.Enabled = true;
                        _stopButton.Enabled = false;
                    });
                    MessageBox.Show(L.T("هیچ نسخه‌ای از Java پیدا نشد. آن را نصب کنید یا مسیرش را در تنظیمات بدهید.",
                                        "No Java runtime found. Install one or set its path in Settings."),
                        "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                _pipeline.Run(_settings, profile, version, _gameDir, javaPath, runConnections);
            });
            _worker.IsBackground = true;
            _worker.Start();
        }

        private string ResolveJava(McVersion version)
        {
            var installs = JavaLocator.Discover(_gameDir, _settings.JavaPathOverride);
            var best = JavaLocator.PickBest(installs, version.RequiredJavaMajor);
            if (best != null)
            {
                Log.Info("java selected: " + best.Path + " (major " + best.Major + ", required " +
                         version.RequiredJavaMajor + ", source " + best.Source + ")");
                if (version.RequiredJavaMajor > 0 && best.Major > 0 && best.Major < version.RequiredJavaMajor)
                {
                    int found = best.Major;
                    int needed = version.RequiredJavaMajor;
                    Ui(delegate
                    {
                        MessageBox.Show(L.T("نسخه Java پیدا‌شده (" + found + ") از نیاز این نسخه ماینکرفت (" + needed +
                                            ") کمتر است؛ ممکن است بازی اجرا نشود.",
                                            "The Java found (" + found + ") is older than this Minecraft version needs (" +
                                            needed + "); the game may not start."),
                            "Server Help", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    });
                }
            }
            return best == null ? "" : best.Path;
        }

        private void OnPipelineFinished(LaunchReport report)
        {
            _playButton.Enabled = true;
            _stopButton.Enabled = true;
            _runWatch.Stop();
            UpdateConnectionSummary();
            string mode = report.TunnelUp ? L.T("تونل WARP", "WARP tunnel")
                        : report.Strategy == "dns" ? L.T("اصلاح DNS", "DNS fix")
                        : L.T("اتصال مستقیم", "direct");
            SetStatus(L.T("اجرا شد • ", "started • ") + mode +
                      (report.TunnelPing > 0 ? L.T(" • پینگ بازی: ", " • game ping: ") + L.N(report.TunnelPing) + " ms" : ""));
            if (_tunnelInfoLabel != null)
            {
                _tunnelInfoLabel.Text = L.T("حالت: ", "mode: ") + mode +
                    (string.IsNullOrEmpty(report.ConnectionUsed) ? "" : "  •  " + L.T("اتصال: ", "connection: ") + report.ConnectionUsed) +
                    (report.EndpointUsed.Length > 0 ? "  •  " + report.EndpointUsed : "") +
                    (report.TunnelPing > 0 ? "  •  " + L.N(report.TunnelPing) + " ms" : "") +
                    (report.ProxyOnlyMode ? L.T("  •  بازی با پروکسی محلی (بدون TUN)", "  •  game uses the local proxy (no TUN)") : "") +
                    (report.LeakGuardArmed ? L.T("  •  kill-switch فعال", "  •  kill switch armed") : "") +
                    (string.IsNullOrEmpty(report.LeakGuardNote) ? "" : "  —  " + report.LeakGuardNote);
            }
            foreach (string line in report.Candidates) AppendLog("[route] " + line);
            foreach (string warning in report.Warnings) AppendLog("[warning] " + warning);

            if (_settings.MinimizeWhilePlaying && string.IsNullOrEmpty(report.Error))
                WindowState = FormWindowState.Minimized;
        }

        private void OnGameExited(int code)
        {
            AppendLog(L.T("بازی بسته شد (کد ", "game closed (code ") + code + ")");
            SetStatus(L.T("بازی بسته شد", "the game exited"));
            if (_pipeline.Report.LeakGuardTripped)
            {
                // the kill switch closed the game on purpose: say so, or it looks like a crash
                AppendLog(L.T("kill-switch: مسیر تونل قطع شد و بازی بسته شد",
                              "kill switch: the tunnel died and the game was closed"));
                MessageBox.Show(this,
                    L.T("مسیر تونل قطع شد و برای جلوگیری از لو رفتن IP، بازی بسته شد. آدرس سرور تا برنگشتن" +
                        " تونل مسدود می‌ماند و با «توقف و بازگردانی» همه‌چیز به حالت قبل برمی‌گردد.",
                        "The tunnel died, so the game was closed to keep your address from leaking. The server" +
                        " address stays blocked until the tunnel is back, and \"stop and restore\" puts" +
                        " everything back."),
                    L.T("kill-switch", "kill switch"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            if (_settings.AutoRestoreOnExit && !_settings.KeepTunnelAfterGame)
            {
                _pipeline.Shutdown(false);
                SetStatus(L.T("بازی بسته شد و تنظیمات بازگردانی شد", "the game exited and everything was restored"));
            }
        }

        private void StopEverything()
        {
            try
            {
                if (_pipeline.GameRunning) _pipeline.Game.Kill();
                _pipeline.Shutdown(false);
                SetStatus(L.T("متوقف شد و بازگردانی انجام شد", "stopped and restored"));
            }
            catch (Exception ex) { AppendLog("stop: " + ex.Message); }
        }

        private void AddStepRow(string title, string state, string detail, StepState stepState)
        {
            // remembered so that a rebuild of the window can put the run that is on screen back
            _stepRows.Add(new string[] { title, state, detail ?? "", ((int)stepState).ToString() });
            DrawStepRow(title, state, detail, stepState);
            AppendLog("[step] " + title + " — " + state + (string.IsNullOrEmpty(detail) ? "" : " (" + detail + ")"));
        }

        /// <summary>Puts one row into the launch table.</summary>
        private void DrawStepRow(string title, string state, string detail, StepState stepState)
        {
            if (_stepList == null) return;
            var item = new ListViewItem(title);
            item.SubItems.Add(state);
            item.SubItems.Add(detail ?? "");
            switch (stepState)
            {
                case StepState.Done: item.ForeColor = Color.FromArgb(24, 120, 50); break;
                case StepState.Warn: item.ForeColor = Color.FromArgb(180, 110, 0); break;
                case StepState.Fail: item.ForeColor = Color.FromArgb(180, 40, 40); break;
                case StepState.Skip: item.ForeColor = Color.FromArgb(110, 110, 110); break;
            }
            _stepList.Items.Add(item);
            _stepList.EnsureVisible(_stepList.Items.Count - 1);
        }

        private void SetStatus(string text)
        {
            if (_statusLabel != null) _statusLabel.Text = text;
            if (_runProgress != null && !string.IsNullOrEmpty(text))
            {
                _runProgress.Caption = text;
                _runProgress.Invalidate();
            }
            if (_header != null) UpdateHeaderPills();
            AppendLog(text);
        }

        private void AppendLog(string line)
        {
            if (_logBox == null || string.IsNullOrEmpty(line)) return;
            _logBox.AppendText(line + Environment.NewLine);
            if (_logBox.TextLength > 400000)
                _logBox.Text = _logBox.Text.Substring(_logBox.TextLength - 200000);
        }
    }
}

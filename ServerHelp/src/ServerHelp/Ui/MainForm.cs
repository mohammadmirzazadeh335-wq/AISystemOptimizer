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

        private TabControl _tabs;
        private ComboBox _versionCombo;
        private ComboBox _serverCombo;
        private TextBox _nicknameBox;
        private Button _playButton;
        private Button _stopButton;
        private Label _statusLabel;
        private Label _bannerLabel;
        private Label _timerLabel;
        private Label _pingLabel;
        private ListView _stepList;
        private ListView _serverList;
        private ListView _versionList;
        private ListView _endpointList;
        private TextBox _logBox;
        private TextBox _versionsDirBox;
        private TextBox _gameDirBox;
        private CheckBox _chkOptimize, _chkPower, _chkTrim, _chkClose, _chkPriority, _chkTuneNetwork, _chkFirewall, _chkTimer;
        private CheckBox _chkAikar, _chkQuickPlay, _chkHosts, _chkKeepTunnel, _chkAutoRestore, _chkMinimize;
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
                Ui(delegate { AddStepRow(step.Title, step.StateTextFa, step.Detail, step.State); });
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
            Text = L.T("Server Help — راهنمای سرور ماینکرفت", "Server Help — Minecraft server helper");
            BackColor = Color.FromArgb(245, 246, 248);

            while (Controls.Count > 0) Controls[0].Dispose();

            // Docking works out when the Fill control is added first, then the Top/Bottom ones.
            _tabs = new TabControl();
            _tabs.Dock = DockStyle.Fill;
            Controls.Add(_tabs);

            var header = new Panel();
            header.Dock = DockStyle.Top;
            header.Height = 74;
            header.BackColor = Color.FromArgb(24, 32, 44);
            Controls.Add(header);

            var title = new Label();
            title.Text = L.T("Server Help", "Server Help");
            title.ForeColor = Color.White;
            title.Font = UiKit.UiFont(17f, true);
            title.AutoSize = true;
            title.Location = new Point(20, 12);
            header.Controls.Add(title);

            _bannerLabel = new Label();
            _bannerLabel.Text = L.T("اتصال به سرور، تونل با کمترین پینگ، و بهینه‌سازی سیستم — در یک کلیک",
                                    "Connect, tunnel with the lowest ping, and tune the system — in one click");
            _bannerLabel.ForeColor = Color.FromArgb(190, 200, 215);
            _bannerLabel.Font = UiKit.UiFont(9.5f, false);
            _bannerLabel.AutoSize = true;
            _bannerLabel.Location = new Point(22, 44);
            header.Controls.Add(_bannerLabel);

            _tabs.TabPages.Add(BuildHomeTab());
            _tabs.TabPages.Add(BuildServersTab());
            _tabs.TabPages.Add(BuildConnectionsTab());
            _tabs.TabPages.Add(BuildNetworkTab());
            _tabs.TabPages.Add(BuildOptimizeTab());
            _tabs.TabPages.Add(BuildVersionsTab());
            _tabs.TabPages.Add(BuildSettingsTab());
            _tabs.TabPages.Add(BuildLogTab());

            var footer = new Panel();
            footer.Dock = DockStyle.Bottom;
            footer.Height = 30;
            footer.BackColor = Color.FromArgb(232, 234, 238);
            Controls.Add(footer);
            footer.BringToFront();

            _statusLabel = new Label();
            _statusLabel.Text = L.T("آماده", "ready");
            _statusLabel.AutoSize = true;
            _statusLabel.Location = new Point(10, 7);
            footer.Controls.Add(_statusLabel);

            _pingLabel = new Label();
            _pingLabel.AutoSize = true;
            _pingLabel.Location = new Point(420, 7);
            footer.Controls.Add(_pingLabel);

            _timerLabel = new Label();
            _timerLabel.AutoSize = true;
            _timerLabel.Location = new Point(700, 7);
            footer.Controls.Add(_timerLabel);

            ResumeLayout(true);
            RefreshVersions();
            RefreshServerList();
            RefreshConnections();
        }

        private TabPage BuildConnectionsTab()
        {
            var page = new TabPage(L.T("اتصالات", "Connections"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Top;
            buttons.Height = 82;
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
            buttons.Controls.Add(clean);
            card.Controls.Add(buttons);

            var options = new FlowLayoutPanel();
            options.Dock = DockStyle.Top;
            options.Height = 96;
            options.FlowDirection = FlowDirection.LeftToRight;

            var pinLabel = UiKit.Sub(L.T("مسیر ثابت بازی:", "Pinned game route:"));
            pinLabel.Width = 130;
            pinLabel.Height = 30;
            options.Controls.Add(pinLabel);

            _pinCombo = new ComboBox();
            _pinCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _pinCombo.Width = 300;
            _pinCombo.SelectedIndexChanged += delegate
            {
                if (_connectionsBusy) return;
                if (_pinCombo.SelectedIndex < 0) return;
                PinConnection(_pinCombo.SelectedIndex == 0 ? "" : _pinCombo.Items[_pinCombo.SelectedIndex].ToString());
            };
            options.Controls.Add(_pinCombo);

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
            _connectionSummary.Height = 34;
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
            _connectionList.Columns.Add(L.T("تأخیر", "Delay"), 80);
            _connectionList.Columns.Add(L.T("وضعیت", "Status"), 240);
            _connectionList.Columns.Add(L.T("فعال", "On"), 60);
            _connectionList.DoubleClick += delegate { EditConnection(SelectedConnection()); };
            card.Controls.Add(_connectionList);
            _connectionList.BringToFront();

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildHomeTab()
        {
            var page = new TabPage(L.T("خانه و اجرا", "Home & Play"));
            page.Padding = new Padding(12);

            var top = UiKit.Card();
            top.Dock = DockStyle.Top;
            top.Height = 214;

            var lblServer = UiKit.Sub(L.T("سرور:", "Server:"));
            lblServer.Location = new Point(12, 12);
            top.Controls.Add(lblServer);

            _serverCombo = new ComboBox();
            _serverCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _serverCombo.Location = new Point(12, 32);
            _serverCombo.Width = 300;
            _serverCombo.SelectedIndexChanged += delegate { if (_serverCombo.SelectedIndex >= 0) SelectServer(_serverCombo.SelectedIndex); };
            top.Controls.Add(_serverCombo);

            var lblVersion = UiKit.Sub(L.T("نسخه ماینکرفت:", "Minecraft version:"));
            lblVersion.Location = new Point(330, 12);
            top.Controls.Add(lblVersion);

            _versionCombo = new ComboBox();
            _versionCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _versionCombo.Location = new Point(330, 32);
            _versionCombo.Width = 280;
            top.Controls.Add(_versionCombo);

            var checkButton = new Button();
            checkButton.Text = L.T("بررسی سرور", "Check server");
            checkButton.Height = 30;
            checkButton.Width = 150;
            checkButton.Location = new Point(630, 30);
            checkButton.Click += delegate { CheckServerAsync(); };
            top.Controls.Add(checkButton);

            var lblNick = UiKit.Sub(L.T("نام بازیکن (آفلاین):", "Player name (offline):"));
            lblNick.Location = new Point(12, 72);
            top.Controls.Add(lblNick);

            _nicknameBox = new TextBox();
            _nicknameBox.Location = new Point(12, 92);
            _nicknameBox.Width = 300;
            _nicknameBox.Text = _settings.Nickname;
            _nicknameBox.TextChanged += delegate { _settings.Nickname = _nicknameBox.Text.Trim(); };
            top.Controls.Add(_nicknameBox);

            _playButton = new Button();
            _playButton.Text = L.T("بهینه‌سازی و اجرای بازی", "Optimise and play");
            _playButton.Font = UiKit.UiFont(11f, true);
            _playButton.Height = 46;
            _playButton.Width = 300;
            _playButton.Location = new Point(630, 84);
            _playButton.BackColor = Color.FromArgb(46, 160, 67);
            _playButton.ForeColor = Color.White;
            _playButton.FlatStyle = FlatStyle.Flat;
            _playButton.Click += delegate { StartPipeline(); };
            top.Controls.Add(_playButton);

            _stopButton = new Button();
            _stopButton.Text = L.T("توقف و بازگردانی", "Stop and restore");
            _stopButton.Height = 30;
            _stopButton.Width = 150;
            _stopButton.Location = new Point(12, 132);
            _stopButton.Enabled = false;
            _stopButton.Click += delegate { StopEverything(); };
            top.Controls.Add(_stopButton);

            _serverInfoLabel = new Label();
            _serverInfoLabel.AutoSize = false;
            _serverInfoLabel.Width = 920;
            _serverInfoLabel.Height = 42;
            _serverInfoLabel.Location = new Point(12, 168);
            _serverInfoLabel.Text = "—";
            top.Controls.Add(_serverInfoLabel);

            var steps = UiKit.Card();
            steps.Dock = DockStyle.Fill;

            _stepList = new ListView();
            _stepList.Dock = DockStyle.Fill;
            _stepList.View = View.Details;
            _stepList.FullRowSelect = true;
            _stepList.GridLines = true;
            _stepList.Columns.Add(L.T("مرحله", "Step"), 320);
            _stepList.Columns.Add(L.T("وضعیت", "State"), 90);
            _stepList.Columns.Add(L.T("جزئیات", "Detail"), 430);
            steps.Controls.Add(_stepList);

            page.Controls.Add(steps);
            page.Controls.Add(top);
            return page;
        }

        private TabPage BuildServersTab()
        {
            var page = new TabPage(L.T("سرورها", "Servers"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

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
            hint.Height = 34;
            card.Controls.Add(hint);

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildNetworkTab()
        {
            var page = new TabPage(L.T("شبکه و تونل", "Network & tunnel"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Top;
            buttons.Height = 44;

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

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildOptimizeTab()
        {
            var page = new TabPage(L.T("بهینه‌سازی", "Optimisation"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

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
                _pipeline.Shutdown(false);
                SetStatus(L.T("تنظیمات سیستم بازگردانی شد", "system settings restored"));
            };

            panel.Controls.Add(_chkOptimize);
            panel.Controls.Add(_chkPower);
            panel.Controls.Add(_chkTuneNetwork);
            panel.Controls.Add(_chkFirewall);
            panel.Controls.Add(_chkTrim);
            panel.Controls.Add(_chkClose);
            panel.Controls.Add(_chkPriority);
            panel.Controls.Add(_chkTimer);
            panel.Controls.Add(_chkAikar);
            panel.Controls.Add(_chkQuickPlay);
            panel.Controls.Add(_chkHosts);
            panel.Controls.Add(_chkKeepTunnel);
            panel.Controls.Add(_chkAutoRestore);
            panel.Controls.Add(_chkMinimize);
            panel.Controls.Add(modeLabel);
            panel.Controls.Add(_tunnelCombo);
            panel.Controls.Add(heapLabel);
            panel.Controls.Add(_heapBox);
            panel.Controls.Add(epLabel);
            panel.Controls.Add(_endpointBox);
            panel.Controls.Add(extraLabel);
            panel.Controls.Add(_extraJvmBox);
            panel.Controls.Add(runNow);
            panel.Controls.Add(restore);

            card.Controls.Add(panel);
            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildVersionsTab()
        {
            var page = new TabPage(L.T("نسخه‌ها", "Versions"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

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
            _versionsDirBox.TextChanged += delegate { _settings.VersionsDir = _versionsDirBox.Text.Trim(); };
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
            card.Controls.Add(_versionList);

            var bottom = UiLabel(L.T("نسخه‌ها از پوشه TLauncher/ماینکرفت خوانده می‌شوند. با دوبار کلیک، نسخه انتخاب می‌شود.",
                                     "Versions are read from the TLauncher/Minecraft folder. Double click a row to select it."));
            bottom.Dock = DockStyle.Bottom;
            bottom.Height = 30;
            card.Controls.Add(bottom);

            page.Controls.Add(card);
            return page;
        }

        private TabPage BuildSettingsTab()
        {
            var page = new TabPage(L.T("تنظیمات", "Settings"));
            page.Padding = new Padding(12);

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

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
                BuildUi();
                SetStatus(L.T("زبان تغییر کرد", "language changed"));
            };

            var gameDirLabel = UiKit.Sub(L.T("پوشه بازی (.minecraft)", "Game folder (.minecraft)"));
            _gameDirBox = new TextBox();
            _gameDirBox.Width = 520;
            _gameDirBox.Text = _settings.GameDirOverride;
            _gameDirBox.TextChanged += delegate { _settings.GameDirOverride = _gameDirBox.Text.Trim(); };

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

            var folderButton = new Button();
            folderButton.Text = L.T("بازکردن پوشه داده‌ها", "Open the data folder");
            folderButton.Width = 200;
            folderButton.Click += delegate { Process.Start("explorer.exe", AppPaths.Data); };

            var creditLabel = UiLabel(L.T("Server Help v1.0.0 — تونل: sing-box " + SingBoxRunner.PinnedVersion +
                                          " + Cloudflare WARP. هیچ داده‌ای از شما جایی ارسال نمی‌شود.",
                                          "Server Help v1.0.0 — tunnel: sing-box " + SingBoxRunner.PinnedVersion +
                                          " + Cloudflare WARP. Nothing about you leaves this machine."));
            creditLabel.Width = 640;
            creditLabel.Height = 40;

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

            var card = UiKit.Card();
            card.Dock = DockStyle.Fill;

            _logBox = new TextBox();
            _logBox.Multiline = true;
            _logBox.ScrollBars = ScrollBars.Both;
            _logBox.WordWrap = false;
            _logBox.Dock = DockStyle.Fill;
            _logBox.Font = new Font("Consolas", 9f);
            _logBox.ReadOnly = true;
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
                bool keep = _settings.KeepTunnelAfterGame;
                _pipeline.Shutdown(keep);
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
            _serverList.Items.Clear();
            if (_serverCombo != null)
            {
                int keep = _serverCombo.SelectedIndex;
                _serverCombo.Items.Clear();
                foreach (ServerProfile profile in _settings.Servers) _serverCombo.Items.Add(profile.Name);
                _serverCombo.SelectedIndex = Math.Max(0, Math.Min(keep, _serverCombo.Items.Count - 1));
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
            _connectionList.Items.Clear();
            foreach (ConnectionEntry entry in _settings.Connections)
            {
                var item = new ListViewItem(entry.Name);
                item.SubItems.Add(entry.Info.Title);
                item.SubItems.Add(entry.Target);
                item.SubItems.Add(entry.LastDelayMs > 0 ? entry.LastDelayMs + " ms" : "—");
                item.SubItems.Add(string.IsNullOrEmpty(entry.LastStatus) ? L.T("تست نشده", "not tested") : entry.StatusText);
                item.SubItems.Add(entry.Enabled ? L.T("بله", "yes") : L.T("خیر", "no"));
                if (!entry.Enabled) item.ForeColor = Color.FromArgb(140, 140, 140);
                else if (entry.LastDelayMs > 0) item.ForeColor = Color.FromArgb(24, 120, 50);
                else if (!string.IsNullOrEmpty(entry.LastError)) item.ForeColor = Color.FromArgb(180, 40, 70);
                _connectionList.Items.Add(item);
            }

            _connectionsBusy = true;
            try
            {
                    _pinCombo.Items.Clear();
                    _pinCombo.Items.Add(L.T("خودکار (سریع‌ترین)", "Automatic (fastest)"));
                    foreach (ConnectionEntry entry in _settings.Connections)
                    {
                        if (!entry.Enabled) continue;
                        if (!entry.UseForGame && !entry.Info.IsResolver) continue;
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
            finally { _connectionsBusy = false; }

            if (_connectionSummary != null)
            {
                int on = 0, working = 0;
                foreach (ConnectionEntry entry in _settings.Connections)
                {
                    if (entry.Enabled) on++;
                    if (entry.LastDelayMs > 0) working++;
                }
                _connectionSummary.Text = L.T("اتصال‌ها: ", "connections: ") + L.N(_settings.Connections.Count) +
                                          L.T(" • روشن: ", " • on: ") + L.N(on) +
                                          L.T(" • تست‌شده با تأخیر: ", " • measured: ") + L.N(working) +
                                          L.T("    |  مسیر انتخابی: ", "    |  chosen route: ") +
                                          (_settings.PinnedConnection.Length == 0
                                              ? L.T("خودکار (همه تست و سریع‌ترین انتخاب می‌شود)", "automatic (all are tested, the fastest wins)")
                                              : _settings.PinnedConnection);
            }
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
            _settings.Connections.Remove(entry);
            if (string.Equals(_settings.PinnedConnection, entry.Name, StringComparison.OrdinalIgnoreCase))
                _settings.PinnedConnection = "";
            SettingsStore.Save(_settings);
            RefreshConnections();
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
            SetStatus(L.T("تست اتصال‌ها…", "testing connections…"));

            var thread = new Thread(delegate ()
            {
                foreach (ConnectionEntry entry in targets)
                {
                    ConnectionEntry local = entry;
                    Ui(delegate { SetStatus(L.T("تست: ", "testing: ") + local.Name); });
                    ConnectionTestResult result = ConnectionTester.Test(local, host, port, timeout, false);
                    local.LastDelayMs = result.Ok ? result.DelayMs : -1;
                    local.LastStatus = result.Status;
                    local.LastError = result.Ok ? "" : result.Detail;
                    local.LastTestUtc = DateTime.Now.ToString("HH:mm:ss");
                    string line = local.Name + " [" + local.Info.Title + "] — " +
                                  (result.Ok ? L.T("کار کرد", "works") : L.T("کار نکرد", "failed")) +
                                  (result.DelayMs > 0 ? " • " + result.DelayMs + " ms" : "") +
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
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void RefreshVersions()
        {
            string dir = VersionScanner.ResolveVersionsDir(_settings.GameDirOverride, _settings.VersionsDir);
            if (_versionList == null) return;
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
                _versionCombo.SelectedIndex = preferred;
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
                        results.Add(ip + "  " + status.LatencyMs + " ms  " + status.Motd);
                        if (best < 0 || status.LatencyMs < best) best = status.LatencyMs;
                    }
                }
                if (!string.IsNullOrEmpty(profile.DirectIp))
                {
                    var status = McPing.Status(profile.DirectIp, profile.Port, 5000, null);
                    if (status != null && status.Ok)
                    {
                        results.Add(profile.DirectIp + "  " + status.LatencyMs + " ms  " + status.Motd);
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
                    _endpointList.Items.Clear();
                    foreach (WarpEndpoint endpoint in best)
                    {
                        var item = new ListViewItem(endpoint.Address);
                        item.SubItems.Add(endpoint.IcmpRtt >= 0 ? endpoint.IcmpRtt + " ms" : "—");
                        item.SubItems.Add(endpoint.TcpRtt >= 0 ? endpoint.TcpRtt + " ms" : "—");
                        item.SubItems.Add(endpoint.Score.ToString());
                        item.SubItems.Add(endpoint.TunnelRtt >= 0 ? endpoint.TunnelRtt + " ms" : "—");
                        item.SubItems.Add("—");
                        _endpointList.Items.Add(item);
                    }
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
                        if (item.SubItems.Count > 4) item.SubItems[4].Text = delay > 0 ? delay + " ms" : "—";
                        if (item.SubItems.Count > 5) item.SubItems[5].Text = tunnelDelay > 0 ? tunnelDelay + " ms" : "—";
                        if (delay > 0) item.ForeColor = delay < 120 ? Color.FromArgb(24, 120, 50) : Color.FromArgb(180, 110, 0);
                    });
                }
                Ui(delegate { SetStatus(L.T("تأخیر همه آدرس‌ها اندازه‌گیری شد", "all endpoint delays measured")); });
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void RunOptimizerNow()
        {
            SetStatus(L.T("بهینه‌سازی سیستم…", "tuning the system…"));
            var thread = new Thread(delegate ()
            {
                _pipeline.Optimizer.TunnelExePath = Shell.FileExists(AppPaths.SingBoxExe) ? AppPaths.SingBoxExe : "";
                _pipeline.Optimizer.JavaExePath = _javaPath;
                _pipeline.Optimizer.Run(_settings, delegate (OptimizationStep step)
                {
                    Ui(delegate { AddStepRow("★ " + step.Title, step.StateText, step.Detail, step.State); });
                });
                Ui(delegate { SetStatus(L.T("بهینه‌سازی انجام شد", "optimisation done")); });
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

            _stepList.Items.Clear();
            _playButton.Enabled = false;
            _stopButton.Enabled = true;
            _runWatch = Stopwatch.StartNew();
            SetStatus(L.T("شروع شد…", "starting…"));

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
                _pipeline.Run(_settings, profile, version, _gameDir, javaPath);
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
                    (report.LeakGuardArmed ? L.T("  •  kill-switch فعال", "  •  kill switch armed") : "");
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
            AppendLog("[step] " + title + " — " + state + (string.IsNullOrEmpty(detail) ? "" : " (" + detail + ")"));
        }

        private void SetStatus(string text)
        {
            if (_statusLabel != null) _statusLabel.Text = text;
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

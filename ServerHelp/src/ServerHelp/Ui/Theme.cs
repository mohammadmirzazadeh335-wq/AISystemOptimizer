using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Windows.Forms;
using ServerHelp.Core;

namespace ServerHelp.Ui
{
    /// <summary>
    /// One place for every colour and every custom control, so the whole app looks like one
    /// program instead of a pile of default Windows dialogs. Flat, rounded, a bit of a game
    /// launcher feel - without any third party library.
    /// </summary>
    public static class Theme
    {
        public static readonly Color Background = Color.FromArgb(0xF2, 0xF4, 0xF8);
        public static readonly Color Surface = Color.White;
        public static readonly Color SurfaceAlt = Color.FromArgb(0xF7, 0xF9, 0xFC);
        public static readonly Color Border = Color.FromArgb(0xD8, 0xDE, 0xE8);
        public static readonly Color Text = Color.FromArgb(0x1B, 0x22, 0x2E);
        public static readonly Color SubText = Color.FromArgb(0x6B, 0x74, 0x84);
        public static readonly Color Accent = Color.FromArgb(0x2E, 0xA0, 0x43);
        public static readonly Color AccentDark = Color.FromArgb(0x1F, 0x7A, 0x33);
        public static readonly Color AccentSoft = Color.FromArgb(0xE4, 0xF4, 0xE8);
        public static readonly Color Info = Color.FromArgb(0x1D, 0x6F, 0xC4);
        public static readonly Color InfoSoft = Color.FromArgb(0xE6, 0xF0, 0xFB);
        public static readonly Color Good = Color.FromArgb(0x1E, 0x8E, 0x4A);
        public static readonly Color Warn = Color.FromArgb(0xC8, 0x7A, 0x00);
        public static readonly Color Bad = Color.FromArgb(0xC0, 0x39, 0x4B);
        public static readonly Color HeaderTop = Color.FromArgb(0x1B, 0x3B, 0x63);
        public static readonly Color HeaderBottom = Color.FromArgb(0x2A, 0x6B, 0x4F);

        public static Font Font(float size, bool bold)
        {
            return UiKit.UiFont(size, bold);
        }

        /// <summary>A rounded rectangle path, used by every surface in the app.</summary>
        public static GraphicsPath Rounded(Rectangle bounds, int radius)
        {
            int diameter = Math.Max(2, radius * 2);
            if (diameter > bounds.Width) diameter = bounds.Width;
            if (diameter > bounds.Height) diameter = bounds.Height;
            var path = new GraphicsPath();
            path.AddArc(bounds.X, bounds.Y, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Y, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }

        public static void FillRounded(Graphics g, Rectangle bounds, int radius, Color color)
        {
            using (var path = Rounded(bounds, radius))
            using (var brush = new SolidBrush(color))
                g.FillPath(brush, path);
        }

        public static void DrawRounded(Graphics g, Rectangle bounds, int radius, Color color, float width)
        {
            using (var path = Rounded(bounds, radius))
            using (var pen = new Pen(color, width))
                g.DrawPath(pen, path);
        }

        // ------------------------------------------------------------------ theming pass

        /// <summary>
        /// Walks the form once and gives every stock control the same skin. Cheap, safe, and it
        /// means the older dialogs inherit the new look without being rewritten.
        /// </summary>
        public static void Apply(Control root)
        {
            if (root == null) return;
            ApplyOne(root);
            foreach (Control child in root.Controls) Apply(child);
        }

        private static void ApplyOne(Control control)
        {
            if (control == null) return;
            var font = control.Font;
            bool bold = font != null && font.Bold;

            if (control is SHButton || control is SHPanel || control is SHHeader ||
                control is SHGauge || control is SHPill || control is SHProgress) return;

            var button = control as Button;
            if (button != null)
            {
                StyleButton(button, false);
                return;
            }

            var list = control as ListView;
            if (list != null)
            {
                SHListView.Style(list);
                return;
            }

            var tabs = control as TabPage;
            if (tabs != null)
            {
                tabs.BackColor = Background;
                return;
            }

            if (control is TextBox || control is ComboBox || control is NumericUpDown)
            {
                control.BackColor = Color.White;
                control.ForeColor = Text;
                control.Font = Font(9.75f, false);
                var box = control as TextBox;
                if (box != null) box.BorderStyle = BorderStyle.FixedSingle;
                var combo = control as ComboBox;
                if (combo != null) combo.FlatStyle = FlatStyle.Flat;
                var numeric = control as NumericUpDown;
                if (numeric != null) numeric.BorderStyle = BorderStyle.FixedSingle;
                return;
            }

            if (control is CheckBox || control is RadioButton)
            {
                control.BackColor = Color.Transparent;
                control.ForeColor = Text;
                control.Font = Font(9.75f, false);
                return;
            }

            var label = control as Label;
            if (label != null)
            {
                if (label.ForeColor == Color.Empty || label.ForeColor == Color.Black) label.ForeColor = Text;
                return;
            }

            var flow = control as FlowLayoutPanel;
            if (flow != null)
            {
                // a flow of checkboxes and labels sits on a white card or on the grey page,
                // so it has to borrow the colour of whatever holds it
                Control holder = flow.Parent;
                Color parentColor = holder == null ? Background : holder.BackColor;
                flow.BackColor = parentColor == Color.Transparent ? Surface : parentColor;
                return;
            }

            var panel = control as Panel;
            if (panel != null)
            {
                if (panel.BackColor == Color.Empty || panel.BackColor == Color.White) panel.BackColor = Surface;
                else if (panel.BackColor == SystemColors.Control) panel.BackColor = Background;
                return;
            }

            var group = control as GroupBox;
            if (group != null)
            {
                group.ForeColor = Text;
                Color holder = group.Parent == null ? Background : group.Parent.BackColor;
                group.BackColor = holder == Color.Transparent ? Surface : holder;
                return;
            }

            var form = control as Form;
            if (form != null)
            {
                form.BackColor = Background;
                form.ForeColor = Text;
                if (form.Font == null || form.Font.Name != "Segoe UI") form.Font = Font(9.75f, false);
                return;
            }
        }

        public static void StyleButton(Button button, bool accent)
        {
            if (button == null) return;
            var chip = button as SHButton;
            if (chip != null)
            {
                if (accent) chip.Accent = true;
                return;
            }
            button.UseVisualStyleBackColor = false;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.BorderColor = accent ? Theme.AccentDark : Theme.Border;
            button.FlatAppearance.MouseOverBackColor = accent ? Color.FromArgb(0x37, 0xB2, 0x50) : Color.FromArgb(0xE9, 0xF3, 0xEC);
            button.FlatAppearance.MouseDownBackColor = accent ? Theme.AccentDark : Color.FromArgb(0xDD, 0xE6, 0xF0);
            button.BackColor = accent ? Theme.Accent : Theme.Surface;
            button.ForeColor = accent ? Color.White : Theme.Text;
            button.Font = Font(9.75f, button.Font != null && button.Font.Bold);
            button.Cursor = Cursors.Hand;
            button.Height = Math.Max(28, button.Height);
        }

        /// <summary>The one button that has to shout: keep it green whatever the theme does.</summary>
        public static void StylePrimary(Button button)
        {
            StyleButton(button, true);
            button.Height = Math.Max(42, button.Height);
            button.Font = Font(11.5f, true);
        }
    }
    /// <summary>Flat rounded button with hover and press states.</summary>
    public sealed class SHButton : Button
    {
        private bool _hover, _down;
        private bool _accent;

        public bool Accent
        {
            get { return _accent; }
            set { _accent = value; Invalidate(); }
        }

        public SHButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            BackColor = Color.Transparent;
            Font = Theme.Font(9.75f, false);
            Height = 30;
            Cursor = Cursors.Hand;
        }

        protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { _hover = false; _down = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { _down = true; Invalidate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { _down = false; Invalidate(); base.OnMouseUp(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
            Color fill, border, text;

            if (!Enabled)
            {
                fill = Color.FromArgb(0xEE, 0xF0, 0xF4);
                border = Theme.Border;
                text = Color.FromArgb(0x9A, 0xA2, 0xB0);
            }
            else if (_accent)
            {
                fill = _down ? Theme.AccentDark : (_hover ? Color.FromArgb(0x37, 0xB2, 0x50) : Theme.Accent);
                border = Theme.AccentDark;
                text = Color.White;
            }
            else
            {
                fill = _down ? Color.FromArgb(0xE2, 0xE7, 0xEF) : (_hover ? Color.FromArgb(0xF0, 0xF4, 0xFA) : Theme.Surface);
                border = _hover ? Theme.Accent : Theme.Border;
                text = Theme.Text;
            }

            var parentColor = Parent != null ? Parent.BackColor : Theme.Background;
            using (var back = new SolidBrush(parentColor == Color.Transparent ? Theme.Background : parentColor))
                g.FillRectangle(back, ClientRectangle);
            Theme.FillRounded(g, bounds, 6, fill);
            Theme.DrawRounded(g, bounds, 6, border, 1f);

            TextFormatFlags flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                    TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine;
            if (RightToLeft == RightToLeft.Yes) flags |= TextFormatFlags.RightToLeft;
            TextRenderer.DrawText(g, Text, Font, bounds, text, flags);
        }
    }

    /// <summary>Rounded card with a border, an optional accent stripe and an optional title.</summary>
    public sealed class SHPanel : Panel
    {
        private string _title = "";

        public string Title
        {
            get { return _title; }
            set
            {
                _title = value ?? "";
                if (_title.Length > 0) Padding = new Padding(12, 42, 12, 12);
                Invalidate();
            }
        }

        public Color StripeColor = Theme.Accent;
        public bool ShowStripe = true;
        public int Radius = 10;

        public SHPanel()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = Theme.Surface;
            Padding = new Padding(12);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (Parent != null)
            {
                Color parentColor = Parent.BackColor == Color.Transparent ? Theme.Background : Parent.BackColor;
                using (var back = new SolidBrush(parentColor)) g.FillRectangle(back, ClientRectangle);
            }

            var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
            Theme.FillRounded(g, bounds, Radius, BackColor);
            Theme.DrawRounded(g, bounds, Radius, Theme.Border, 1f);

            if (ShowStripe && _title.Length > 0)
            {
                using (var brush = new SolidBrush(StripeColor))
                    g.FillRectangle(brush, new Rectangle(1, 8, 4, 22));
            }

            if (_title.Length > 0)
            {
                TextFormatFlags flags = TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine |
                                        TextFormatFlags.EndEllipsis | TextFormatFlags.Left;
                if (RightToLeft == RightToLeft.Yes) flags |= TextFormatFlags.RightToLeft | TextFormatFlags.Right;
                using (var font = Theme.Font(11.5f, true))
                    TextRenderer.DrawText(g, _title, font, new Rectangle(14, 6, Width - 24, 28), Theme.Text, flags);
            }
        }
    }

    /// <summary>Gradient app header with a title, a subtitle and the live status pills.</summary>
    public sealed class SHHeader : Panel
    {
        public string Title = "Server Help";
        public string Subtitle = "";
        public string Right1 = "";
        public Color Right1Color = Theme.Good;
        public string Right2 = "";
        public Color Right2Color = Theme.Info;

        public SHHeader()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Height = 68;
            Dock = DockStyle.Top;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var bounds = ClientRectangle;
            using (var brush = new LinearGradientBrush(bounds, Theme.HeaderTop, Theme.HeaderBottom, 25f))
                g.FillRectangle(brush, bounds);

            // a soft wave so the header does not look like a flat rectangle
            using (var glow = new SolidBrush(Color.FromArgb(28, 255, 255, 255)))
                g.FillEllipse(glow, bounds.Width - 260, -90, 380, 220);
            using (var glow = new SolidBrush(Color.FromArgb(22, 255, 255, 255)))
                g.FillEllipse(glow, -80, 30, 240, 140);

            // logo dot
            using (var logo = new SolidBrush(Color.FromArgb(255, 255, 255)))
                g.FillEllipse(logo, 16, 18, 32, 32);
            using (var pen = new Pen(Theme.HeaderTop, 3.2f) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                g.DrawLine(pen, 24, 41, 30, 30);
                g.DrawLine(pen, 30, 30, 35, 39);
                g.DrawLine(pen, 35, 39, 44, 24);
            }

            using (var font = Theme.Font(15f, true))
                TextRenderer.DrawText(g, Title, font, new Rectangle(60, 12, 420, 26), Color.White,
                                      TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            if (Subtitle.Length > 0)
            {
                using (var font = Theme.Font(8.75f, false))
                    TextRenderer.DrawText(g, Subtitle, font, new Rectangle(60, 36, Math.Max(120, Width - 480), 20),
                                          Color.FromArgb(210, 255, 255, 255), TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            }

            DrawPill(g, Right1, Right1Color, 1);
            DrawPill(g, Right2, Right2Color, 2);
        }

        private void DrawPill(Graphics g, string text, Color color, int slot)
        {
            if (string.IsNullOrEmpty(text)) return;
            using (var font = Theme.Font(9f, true))
            {
                Size size = TextRenderer.MeasureText(g, text, font);
                int width = size.Width + 34;
                int x = Width - 16 - (slot == 1 ? width : width + (Measure(1) + 8));
                var bounds = new Rectangle(x, 19, width, 30);
                Theme.FillRounded(g, bounds, 15, Color.FromArgb(46, 255, 255, 255));
                using (var dot = new SolidBrush(color))
                    g.FillEllipse(dot, bounds.X + 12, bounds.Y + 11, 8, 8);
                using (var border = new Pen(Color.FromArgb(70, 255, 255, 255)))
                    Theme.DrawRounded(g, bounds, 15, Color.FromArgb(70, 255, 255, 255), 1f);
                TextRenderer.DrawText(g, text, font, new Rectangle(bounds.X + 26, bounds.Y, width - 30, bounds.Height),
                                      Color.White, TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            }
        }

        private int Measure(int slot)
        {
            string text = slot == 1 ? Right1 : Right2;
            if (string.IsNullOrEmpty(text)) return 0;
            using (var font = Theme.Font(9f, true))
                return TextRenderer.MeasureText(text, font).Width + 34;
        }
    }

    /// <summary>Ring gauge for the dashboard: one number, one caption, optional note.</summary>
    public sealed class SHGauge : Control
    {
        private float _value;
        public string Caption = "";
        public string Unit = "ms";
        public string Note = "";
        public Color RingColor = Theme.Accent;
        public bool Unknown;

        public float Value
        {
            get { return _value; }
            set { _value = value; Invalidate(); }
        }

        public SHGauge()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            Size = new Size(150, 150);
            BackColor = Color.Transparent;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (Parent != null && Visible)
            {
                Color parentColor = Parent.BackColor == Color.Transparent ? Theme.Background : Parent.BackColor;
                using (var back = new SolidBrush(parentColor)) g.FillRectangle(back, ClientRectangle);
            }

            int size = Math.Min(Width, Height) - 16;
            int left = (Width - size) / 2;
            int top = 4;
            var ring = new Rectangle(left, top, size, size);
            float thickness = Math.Max(8f, size * 0.11f);

            using (var track = new Pen(Color.FromArgb(0xE3, 0xE8, 0xF0), thickness))
            {
                track.StartCap = LineCap.Round;
                track.EndCap = LineCap.Round;
                g.DrawArc(track, ring, 135, 270);
            }

            float fraction = Unknown ? 0f : Math.Max(0f, Math.Min(1f, _value));
            if (!Unknown && fraction > 0.005f)
            {
                using (var pen = new Pen(RingColor, thickness))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    g.DrawArc(pen, ring, 135, 270f * fraction);
                }
            }

            string main = Unknown ? "—" : (_value * 100f).ToString("0");
            using (var font = Theme.Font(19f, true))
            using (var brush = new SolidBrush(Unknown ? Theme.SubText : Theme.Text))
            {
                Size size2 = TextRenderer.MeasureText(g, main, font);
                g.DrawString(main, font, brush, ring.Left + (ring.Width - size2.Width) / 2f, ring.Top + ring.Height * 0.30f);
            }
            using (var font = Theme.Font(8.5f, false))
                TextRenderer.DrawText(g, Unit, font, new Rectangle(ring.Left, ring.Top + (int)(ring.Height * 0.58f), ring.Width, 18),
                                      Theme.SubText, TextFormatFlags.HorizontalCenter);
            if (Caption.Length > 0)
            {
                using (var font = Theme.Font(9f, true))
                    TextRenderer.DrawText(g, Caption, font, new Rectangle(0, ring.Bottom + 2, Width, 20),
                                          Theme.Text, TextFormatFlags.HorizontalCenter);
            }
            if (Note.Length > 0)
            {
                using (var font = Theme.Font(8f, false))
                    TextRenderer.DrawText(g, Note, font, new Rectangle(0, ring.Bottom + 22, Width, 18),
                                          Theme.SubText, TextFormatFlags.HorizontalCenter | TextFormatFlags.EndEllipsis);
            }
        }
    }

    /// <summary>Small status chip: coloured dot plus text.</summary>
    public sealed class SHPill : Control
    {
        private string _text = "";
        public Color DotColor = Theme.Good;
        public bool Soft = true;

        public string Text2
        {
            get { return _text; }
            set { _text = value ?? ""; Invalidate(); }
        }

        public SHPill()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            Height = 26;
            BackColor = Color.Transparent;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (Parent != null)
            {
                Color parentColor = Parent.BackColor == Color.Transparent ? Theme.Background : Parent.BackColor;
                using (var back = new SolidBrush(parentColor)) g.FillRectangle(back, ClientRectangle);
            }
            var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
            Color fill = Soft ? Color.FromArgb(24, DotColor) : DotColor;
            Theme.FillRounded(g, bounds, Height / 2, fill);
            Theme.DrawRounded(g, bounds, Height / 2, Color.FromArgb(70, DotColor), 1f);
            using (var dot = new SolidBrush(DotColor))
                g.FillEllipse(dot, 9, Height / 2 - 4, 8, 8);
            using (var font = Theme.Font(8.75f, true))
                TextRenderer.DrawText(g, _text, font, new Rectangle(23, 0, Width - 28, Height), Theme.Text,
                                      TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }
    }

    /// <summary>Thin rounded progress bar (the one minute countdown and the step progress).</summary>
    public sealed class SHProgress : Control
    {
        private float _value;
        public Color BarColor = Theme.Accent;
        public string Caption = "";

        public float Value
        {
            get { return _value; }
            set { _value = value; Invalidate(); }
        }

        public SHProgress()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            Height = 34;
            BackColor = Color.Transparent;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (Parent != null)
            {
                Color parentColor = Parent.BackColor == Color.Transparent ? Theme.Background : Parent.BackColor;
                using (var back = new SolidBrush(parentColor)) g.FillRectangle(back, ClientRectangle);
            }
            int barTop = Caption.Length > 0 ? Height - 14 : 0;
            var track = new Rectangle(0, barTop, Width - 1, 11);
            Theme.FillRounded(g, track, 5, Color.FromArgb(0xE3, 0xE8, 0xF0));
            float fraction = Math.Max(0f, Math.Min(1f, _value));
            if (fraction > 0.004f)
            {
                var filled = new Rectangle(0, barTop, Math.Max(8, (int)((Width - 1) * fraction)), 11);
                using (var brush = new LinearGradientBrush(filled, BarColor, Color.FromArgb(
                           Math.Min(255, BarColor.R + 40), Math.Min(255, BarColor.G + 40), Math.Min(255, BarColor.B + 40)), 0f))
                    g.FillPath(brush, Theme.Rounded(filled, 5));
            }
            if (Caption.Length > 0)
            {
                using (var font = Theme.Font(9f, false))
                    TextRenderer.DrawText(g, Caption, font, new Rectangle(0, 0, Width, Height - 16), Theme.Text,
                                          TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
            }
        }
    }

    /// <summary>Owner drawn list view: taller rows, alternating background, soft selection.</summary>
    public static class SHListView
    {
        public static void Style(ListView list)
        {
            if (list == null || list.OwnerDraw) return;
            list.OwnerDraw = true;
            list.BorderStyle = BorderStyle.None;
            list.BackColor = Theme.Surface;
            list.ForeColor = Theme.Text;
            list.GridLines = false;
            list.Font = Theme.Font(9.75f, false);

            var spacer = new ImageList();
            spacer.ImageSize = new Size(1, 24);            // this is what makes the rows taller
            list.SmallImageList = spacer;

            list.DrawColumnHeader += delegate (object sender, DrawListViewColumnHeaderEventArgs e)
            {
                using (var back = new SolidBrush(Color.FromArgb(0xF4, 0xF6, 0xFA)))
                    e.Graphics.FillRectangle(back, e.Bounds);
                using (var line = new Pen(Theme.Border))
                    e.Graphics.DrawLine(line, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
                TextFormatFlags flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis;
                if (e.Header != null && list.RightToLeft == RightToLeft.Yes) flags |= TextFormatFlags.RightToLeft | TextFormatFlags.Right;
                using (var font = Theme.Font(9f, true))
                    TextRenderer.DrawText(e.Graphics, e.Header == null ? "" : e.Header.Text, font,
                                          new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - 10, e.Bounds.Height),
                                          Theme.SubText, flags);
            };

            list.DrawItem += delegate (object sender, DrawListViewItemEventArgs e)
            {
                if (e.Item == null) return;
                Color back = e.ItemIndex % 2 == 0 ? Theme.Surface : Theme.SurfaceAlt;
                if ((e.State & ListViewItemStates.Selected) != 0) back = Theme.AccentSoft;
                using (var brush = new SolidBrush(back))
                    e.Graphics.FillRectangle(brush, e.Bounds);
                if (e.Item.Focused && (e.State & ListViewItemStates.Selected) != 0)
                    using (var pen = new Pen(Theme.Accent))
                        e.Graphics.DrawRectangle(pen, e.Bounds.X, e.Bounds.Y, e.Bounds.Width - 1, e.Bounds.Height - 1);
            };

            list.DrawSubItem += delegate (object sender, DrawListViewSubItemEventArgs e)
            {
                if (e.Item == null) return;
                Color back = e.ItemIndex % 2 == 0 ? Theme.Surface : Theme.SurfaceAlt;
                if ((e.ItemState & ListViewItemStates.Selected) != 0) back = Theme.AccentSoft;
                using (var brush = new SolidBrush(back))
                    e.Graphics.FillRectangle(brush, e.Bounds);
                using (var line = new Pen(Color.FromArgb(0xEE, 0xF1, 0xF6)))
                    e.Graphics.DrawLine(line, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);

                Color text = e.Item.ForeColor == Color.Empty ? Theme.Text : e.Item.ForeColor;
                TextFormatFlags flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis |
                                        TextFormatFlags.NoPrefix;
                if (list.RightToLeft == RightToLeft.Yes) flags |= TextFormatFlags.RightToLeft | TextFormatFlags.Right;
                string value = e.SubItem == null ? "" : e.SubItem.Text;
                TextRenderer.DrawText(e.Graphics, value, e.Item.Font ?? list.Font,
                                      new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - 10, e.Bounds.Height), text, flags);
            };
        }
    }

    /// <summary>Owner drawn tab strip with an accent underline for the active tab.</summary>
    public sealed class SHTabs : TabControl
    {
        public SHTabs()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            DrawMode = TabDrawMode.OwnerDrawFixed;
            SizeMode = TabSizeMode.Fixed;
            ItemSize = new Size(150, 36);
            Padding = new Point(14, 6);
            Font = Theme.Font(10f, false);
            Appearance = TabAppearance.Normal;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var back = new SolidBrush(Theme.Surface))
                g.FillRectangle(back, ClientRectangle);

            for (int i = 0; i < TabCount; i++)
            {
                Rectangle bounds = GetTabRect(i);
                bool active = i == SelectedIndex;
                var item = new Rectangle(bounds.X + 3, bounds.Y + 4, bounds.Width - 6, bounds.Height - 6);
                if (active)
                {
                    Theme.FillRounded(g, item, 8, Theme.AccentSoft);
                    using (var pen = new Pen(Theme.Accent, 3f))
                        g.DrawLine(pen, item.Left + 10, item.Bottom - 2, item.Right - 10, item.Bottom - 2);
                }
                else if (i == _hoverIndex)
                {
                    Theme.FillRounded(g, item, 8, Color.FromArgb(0xF0, 0xF3, 0xF8));
                }

                Color text = active ? Theme.AccentDark : Theme.SubText;
                TextFormatFlags flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                        TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix;
                if (RightToLeft == RightToLeft.Yes) flags |= TextFormatFlags.RightToLeft;
                using (var font = Theme.Font(10f, active))
                    TextRenderer.DrawText(g, TabPages[i].Text, font, item, text, flags);
            }

            using (var line = new Pen(Theme.Border))
            {
                int y = TabCount > 0 ? GetTabRect(0).Bottom + 7 : 40;
                g.DrawLine(line, 0, y, Width, y);
            }
        }

        private int _hoverIndex = -1;

        protected override void OnMouseMove(MouseEventArgs e)
        {
            int index = -1;
            for (int i = 0; i < TabCount; i++)
                if (GetTabRect(i).Contains(e.Location)) { index = i; break; }
            if (index != _hoverIndex) { _hoverIndex = index; Invalidate(); }
            base.OnMouseMove(e);
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            _hoverIndex = -1;
            Invalidate();
            base.OnMouseLeave(e);
        }
    }
}

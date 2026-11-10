"""Dashboard: live operational picture built exclusively from database data."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.jalali import JalaliDate
from pars_erp.core.money import format_amount
from pars_erp.services.dashboard_service import DashboardOverview
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import SECURITY_EVENT_COLUMNS, format_cell
from pars_erp.ui.widgets.common import Badge, BarChart, InfoRow, KpiCard, apply_shadow


class DashboardPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate
        self._overview: DashboardOverview | None = None

        self.header = PageHeader("داشبورد", "وضعیت لحظه‌ای سیستم بر اساس اطلاعات واقعی پایگاه داده")
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        content.addWidget(self.banner)

        # --- KPI tiles -------------------------------------------------------
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(12)
        self.kpi_users = KpiCard("کاربران فعال", "—", "از تعداد کل کاربران", tone="primary")
        self.kpi_sessions = KpiCard("نشست‌های باز", "—", "ورودهای فعال در سیستم", tone="info")
        self.kpi_logins = KpiCard("ورودهای امروز", "—", "بر اساس تقویم شمسی", tone="success")
        self.kpi_failures = KpiCard("تلاش ناموفق ورود", "—", "۲۴ ساعت گذشته", tone="warning")
        self.kpi_events = KpiCard("رویدادهای امنیتی", "—", "امروز", tone="neutral")
        self.kpi_backup = KpiCard("آخرین پشتیبان", "—", "وضعیت پشتیبان‌گیری", tone="primary")
        self.kpi_users.clicked.connect(lambda: self._navigate("users"))
        self.kpi_events.clicked.connect(lambda: self._navigate("audit"))
        self.kpi_backup.clicked.connect(lambda: self._navigate("backup"))
        self.kpi_sessions.clicked.connect(lambda: self._navigate("audit"))
        for index, card in enumerate((self.kpi_users, self.kpi_sessions, self.kpi_logins,
                                      self.kpi_failures, self.kpi_events, self.kpi_backup)):
            kpi_grid.addWidget(card, index // 3, index % 3)
        content.addLayout(kpi_grid)

        # --- chart + recent events ------------------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(14)

        self.chart_card = CardPanel("تلاش‌های ناموفق ورود (۷ روز گذشته)",
                                    "هر ستون یک روز شمسی؛ فقط داده واقعی ثبت‌شده")
        self.chart = BarChart()
        self.chart.setMinimumHeight(150)
        self.chart_card.add(self.chart, 1)
        middle.addWidget(self.chart_card, 1)

        self.security_card = CardPanel("آخرین رویدادهای امنیتی", "برای مشاهده جزئیات به بخش رویدادها بروید")
        self.events_list = QListWidget()
        self.events_list.setObjectName("RecentEvents")
        self.events_list.setWordWrap(True)
        self.events_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.events_list.setMinimumHeight(150)
        self.events_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.security_card.add(self.events_list, 1)
        open_audit = QPushButton("مشاهده همه رویدادها")
        open_audit.setProperty("variant", "link")
        open_audit.clicked.connect(lambda: self._navigate("audit"))
        self.security_card.add(open_audit)
        middle.addWidget(self.security_card, 1)
        content.addLayout(middle)

        # --- system information ---------------------------------------------
        self.system_card = CardPanel("اطلاعات سیستم", "شناسنامه نصب و وضعیت پایگاه داده")
        info_grid = QGridLayout()
        info_grid.setSpacing(8)
        self.info_company = InfoRow("نام شرکت", "—")
        self.info_app = InfoRow("نرم‌افزار", "—")
        self.info_currency = InfoRow("واحد پول", "—")
        self.info_roles = InfoRow("نقش‌ها", "—")
        self.info_database = InfoRow("پایگاه داده", "—")
        self.info_size = InfoRow("حجم پایگاه داده", "—")
        self.info_schema = InfoRow("نسخه ساختار", "—")
        self.info_installation = InfoRow("شناسه نصب", "—")
        self.info_last_backup = InfoRow("آخرین پشتیبان", "—")
        for index, row in enumerate((self.info_company, self.info_app, self.info_currency,
                                     self.info_roles, self.info_database, self.info_size,
                                     self.info_schema, self.info_installation,
                                     self.info_last_backup)):
            info_grid.addWidget(row, index // 3, index % 3)
        self.system_card.add_layout(info_grid)
        content.addWidget(self.system_card)
        content.addStretch(1)

        scroll.setWidget(container)
        self.root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ logic
    def _navigate(self, key: str) -> None:
        if self._on_navigate:
            self._on_navigate(key)

    def refresh(self) -> None:
        overview = self.services.dashboard.overview(self.ctx)
        self._overview = overview
        fmt = self.formatter

        self.kpi_users.set_value(fmt.number(overview.users_active),
                                 f"از {fmt.number(overview.users_total)} کاربر "
                                 f"({fmt.number(overview.users_inactive)} غیرفعال)")
        self.kpi_sessions.set_value(fmt.number(overview.sessions_open),
                                    f"حساب‌های قفل‌شده: {fmt.number(overview.users_locked)}")
        self.kpi_logins.set_value(fmt.number(overview.logins_today),
                                  JalaliDate.today().format(long=True))
        failures_hint = (f"هفتهٔ گذشته: {fmt.number(overview.failed_logins_7d)}"
                         f" — امروز: {fmt.number(overview.warning_events_today)} هشدار")
        self.kpi_failures.set_value(fmt.number(overview.failed_logins_24h), failures_hint)
        self.kpi_events.set_value(fmt.number(overview.events_today),
                                  f"رویداد بحرانی: {fmt.number(overview.critical_events_today)}")
        self.kpi_backup.set_value(overview.last_backup_label,
                                  f"تعداد نسخه‌ها: {fmt.number(overview.backup_count)}"
                                  f" — حجم: {fmt.number(round(overview.backup_size_mb))} مگابایت")

        self.chart.set_data([point.label_fa for point in overview.failed_login_series],
                            [point.value for point in overview.failed_login_series])
        from pars_erp.ui.theme import palette_for
        snapshot = self.services.settings.snapshot()
        palette = palette_for(snapshot.theme)
        self.chart.set_theme(color=palette["chart"], soft=palette["border"], text=palette["muted"])
        self.chart.set_digits(snapshot.persian_digits)

        self.events_list.clear()
        if overview.recent_events:
            for event in overview.recent_events:
                item = QListWidgetItem(
                    f"{fmt.datetime(event.occurred_at)}  •  {event.event_title_fa}  "
                    f"—  {event.message_fa}")
                item.setToolTip(event.message_fa)
                self.events_list.addItem(item)
        else:
            item = QListWidgetItem("رویداد قابل نمایشی وجود ندارد (یا دسترسی به رویدادها ندارید).")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.events_list.addItem(item)

        self.info_company.set_value(overview.company_name or "تعریف نشده")
        self.info_app.set_value(f"{overview.app_name} — نسخه {overview.app_version}")
        self.info_currency.set_value(
            f"{overview.currency_code} — ۱ واحد = "
            f"{format_amount(1, overview.currency_code, persian_digits=False)}")
        self.info_roles.set_value(
            f"{fmt.number(overview.roles_total)} نقش "
            f"({fmt.number(overview.roles_custom)} سفارشی)")
        self.info_database.set_value(overview.backend)
        self.info_size.set_value(overview.database_size_label)
        self.info_schema.set_value(overview.schema_revision or "—")
        self.info_installation.set_value(overview.installation_id or "—")
        self.info_last_backup.set_value(
            f"{overview.last_backup_label}" if overview.last_backup_at else "بدون پشتیبان")

        if overview.backup_is_stale:
            self.banner.setText("⚠  پشتیبان‌گیری به‌روز نیست. برای جلوگیری از از دست رفتن اطلاعات، "
                                "از بخش پشتیبان‌گیری یک نسخه جدید بگیرید.")
            self.banner.setStyleSheet(
                "background-color: #fdf3e7; color: #b54708; border: 1px solid #f5d9b3;"
                " border-radius: 8px; padding: 10px;")
            self.banner.setVisible(True)
        elif overview.users_must_change_password:
            self.banner.setText(
                f"ℹ  {fmt.number(overview.users_must_change_password)} کاربر باید در ورود بعدی "
                "رمز عبور خود را تغییر دهد.")
            self.banner.setStyleSheet(
                "background-color: #e8f0ff; color: #175cd3; border: 1px solid #c7dcff;"
                " border-radius: 8px; padding: 10px;")
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)

"""دارایی‌های ثابت — register, edit, transfer, policy change, maintenance, disposal."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.assets import constants as A
from pars_erp.core.errors import AppError, ValidationError
from pars_erp.services.assets_service import (
    AssetInput,
    DisposalInput,
    MaintenanceInput,
)
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import AccountPicker, JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, confirm
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import EmployeePicker
from pars_erp.ui.pages.treasury.widgets import FundPicker
from pars_erp.ui.table_specs import ASSET_COLUMNS, ASSET_MOVEMENT_COLUMNS
from pars_erp.ui.widgets.common import InfoRow, SearchInput
from pars_erp.ui.widgets.table import DataTable


def _account_choices(services, ctx):
    try:
        return [(row.id, row.display) for row in services.accounts.list_accounts(
            ctx, level=C.LEVEL_SUBSIDIARY, active=None)]
    except AppError:
        return []


class AssetDialog(FormDialog):
    title_fa = "دارایی ثابت"
    width = 760

    def __init__(self, services, ctx, *, asset_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        self.asset_id = asset_id
        self.raw: dict = {}
        if asset_id is not None:
            try:
                self.raw = services.assets.asset_form_data(ctx, asset_id)
            except AppError:
                self.raw = {}
        super().__init__(services, ctx, parent=parent,
                         subtitle="کد خالی به‌صورت خودکار ساخته می‌شود؛ حساب‌ها از دسته "
                                  "پر می‌شوند و قابل تغییرند.")

    def _build(self) -> None:
        raw = self.raw
        self.category_combo = PickCombo()
        try:
            self.category_combo.load(self.services.assets.category_choices(self.ctx))
        except AppError:
            self.category_combo.load([])
        self.category_combo.set_value(raw.get("category_id"))
        self.code_edit = QLineEdit(str(raw.get("code") or ""))
        self.code_edit.setPlaceholderText("خودکار")
        self.add_pair(("دسته *", self.category_combo), ("کد دارایی", self.code_edit),
                      left_required=True)
        self.title_edit = QLineEdit(str(raw.get("title_fa") or ""))
        self.add_row("نام دارایی *", self.title_edit, required=True)
        self.serial_edit = QLineEdit(str(raw.get("serial_no") or ""))
        self.model_edit = QLineEdit(str(raw.get("model") or ""))
        self.add_pair(("شماره سریال", self.serial_edit), ("مدل", self.model_edit))
        self.manufacturer_edit = QLineEdit(str(raw.get("manufacturer") or ""))
        self.location_edit = QLineEdit(str(raw.get("location") or ""))
        self.add_pair(("سازنده", self.manufacturer_edit), ("محل نگهداری", self.location_edit))

        self.purchase_edit = JalaliDateEdit(raw.get("purchase_date"), allow_empty=True)
        self.service_edit = JalaliDateEdit(raw.get("in_service_date") or _dt.date.today())
        self.add_pair(("تاریخ خرید", self.purchase_edit), ("تاریخ بهره‌برداری *", self.service_edit),
                      right_required=True)

        self.custodian_picker = EmployeePicker(active_only=False)
        self.custodian_picker.attach(self.services, self.ctx)
        self.custodian_picker.set_value(raw.get("custodian_employee_id"))
        self.unit_combo = PickCombo()
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        self.unit_combo.set_value(raw.get("org_unit_id"))
        self.add_pair(("امانت‌دار", self.custodian_picker), ("واحد سازمانی", self.unit_combo))

        self.add_section("بهای تمام‌شده و استهلاک")
        self.price_edit = MoneyEdit()
        self.price_edit.set_amount(raw.get("purchase_price"))
        self.related_edit = MoneyEdit()
        self.related_edit.set_amount(raw.get("related_costs"))
        self.add_pair(("بهای خرید", self.price_edit), ("هزینه‌های مرتبط", self.related_edit))
        self.initial_edit = MoneyEdit()
        self.initial_edit.set_amount(raw.get("initial_value"))
        self.initial_edit.setPlaceholderText("خالی = بهای خرید + هزینه‌های مرتبط")
        self.salvage_edit = MoneyEdit()
        self.salvage_edit.set_amount(raw.get("salvage_value"))
        self.add_pair(("بهای تمام‌شده", self.initial_edit), ("ارزش اسقاط", self.salvage_edit))

        self.method_combo = fill_combo(QComboBox(), A.METHODS,
                                       current=raw.get("method") or A.METHOD_STRAIGHT_LINE,
                                       placeholder="")
        self.life_spin = QSpinBox()
        self.life_spin.setRange(1, 1200)
        self.life_spin.setSuffix(" ماه")
        if raw.get("useful_life_months"):
            self.life_spin.setValue(int(raw["useful_life_months"]))
        else:
            self.life_spin.setValue(60)
        self.add_pair(("روش استهلاک", self.method_combo), ("عمر مفید", self.life_spin))

        self.rate_edit = QLineEdit(
            f"{Decimal(raw['declining_rate']):f}" if raw.get("declining_rate") is not None else "")
        self.rate_edit.setPlaceholderText("فقط برای روش نزولی — درصد سالانه")
        self.units_edit = QLineEdit(
            f"{Decimal(raw['total_units']):f}" if raw.get("total_units") is not None else "")
        self.units_edit.setPlaceholderText("فقط برای روش کارکردی")
        self.add_pair(("نرخ نزولی (٪)", self.rate_edit), ("کل کارکرد قابل استهلاک", self.units_edit))

        self.status_combo = fill_combo(QComboBox(), A.ASSET_STATUSES,
                                       current=raw.get("status") or A.ASSET_IN_USE,
                                       placeholder="")
        self.add_row("وضعیت", self.status_combo)

        self.add_section("حساب‌ها (خالی = پیش‌فرض دسته)")
        choices = _account_choices(self.services, self.ctx)
        self.asset_account = AccountPicker()
        self.asset_account.load(choices, placeholder="— حساب دارایی —")
        if raw.get("asset_account_id"):
            self.asset_account.set_account(raw["asset_account_id"])
        self.accumulated_account = AccountPicker()
        self.accumulated_account.load(choices, placeholder="— استهلاک انباشته —")
        if raw.get("accumulated_account_id"):
            self.accumulated_account.set_account(raw["accumulated_account_id"])
        self.expense_account = AccountPicker()
        self.expense_account.load(choices, placeholder="— هزینهٔ استهلاک —")
        if raw.get("expense_account_id"):
            self.expense_account.set_account(raw["expense_account_id"])
        self.add_pair(("حساب دارایی", self.asset_account), ("استهلاک انباشته", self.accumulated_account))
        self.add_row("هزینهٔ استهلاک", self.expense_account)

        self.notes_edit = QLineEdit(str(raw.get("notes") or ""))
        self.add_row("یادداشت", self.notes_edit)

    def save(self):
        initial = self.initial_edit.amount if self.initial_edit.text().strip() else None
        rate = self.rate_edit.text().strip()
        units = self.units_edit.text().strip()
        data = AssetInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            category_id=self.category_combo.value(),
            serial_no=self.serial_edit.text().strip(),
            model=self.model_edit.text().strip(),
            manufacturer=self.manufacturer_edit.text().strip(),
            purchase_date=self.purchase_edit.date(),
            in_service_date=self.service_edit.date(),
            supplier_detail_id=self.raw.get("supplier_detail_id"),
            invoice_id=self.raw.get("invoice_id"),
            location=self.location_edit.text().strip(),
            custodian_employee_id=self.custodian_picker.value(),
            org_unit_id=self.unit_combo.value(),
            purchase_price=self.price_edit.amount,
            related_costs=self.related_edit.amount,
            initial_value=initial,
            salvage_value=self.salvage_edit.amount,
            useful_life_months=self.life_spin.value(),
            method=str(self.method_combo.currentData()),
            declining_rate=Decimal(rate) if rate else None,
            total_units=Decimal(units) if units else None,
            asset_account_id=self.asset_account.current_account_id(),
            accumulated_account_id=self.accumulated_account.current_account_id(),
            expense_account_id=self.expense_account.current_account_id(),
            status=str(self.status_combo.currentData()),
            depreciation_start_override=self.raw.get("depreciation_start_override"),
            notes=self.notes_edit.text().strip(),
            attachment_path=self.raw.get("attachment_path") or "",
        )
        if self.asset_id is None:
            return self.services.assets.register(self.ctx, data)
        return self.services.assets.update(self.ctx, self.asset_id, data)


class TransferDialog(FormDialog):
    title_fa = "انتقال / تغییر امانت‌دار"
    width = 560

    def __init__(self, services, ctx, asset, parent: QWidget | None = None) -> None:
        self.asset = asset
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"{asset.code} — {asset.title_fa}؛ هر تغییر در سابقه ثبت "
                                  "می‌شود.")

    def _build(self) -> None:
        self.custodian_picker = EmployeePicker(active_only=False)
        self.custodian_picker.attach(self.services, self.ctx)
        self.add_row("امانت‌دار جدید", self.custodian_picker)
        self.unit_combo = PickCombo()
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        self.add_row("واحد سازمانی جدید", self.unit_combo)
        self.location_edit = QLineEdit()
        self.add_row("محل جدید", self.location_edit)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_row("تاریخ انتقال", self.date_edit)
        self.note_edit = QLineEdit()
        self.add_row("توضیح", self.note_edit)

    def save(self):
        custodian = self.custodian_picker.value()
        unit = self.unit_combo.value()
        location = self.location_edit.text().strip()
        if custodian is None and unit is None and not location:
            raise ValidationError("حداقل یکی از مقصد امانت‌دار، واحد یا محل را انتخاب کنید.",
                                  field="target")
        return self.services.assets.transfer(
            self.ctx, self.asset.id, to_org_unit_id=unit, to_employee_id=custodian,
            location=location or None, movement_date=self.date_edit.date(),
            note=self.note_edit.text().strip())


class PolicyDialog(FormDialog):
    title_fa = "تغییر سیاست استهلاک"
    width = 560

    def __init__(self, services, ctx, asset, parent: QWidget | None = None) -> None:
        self.asset = asset
        super().__init__(services, ctx, parent=parent,
                         subtitle="تغییر سیاست فقط از تاریخ اجرا به بعد اثر دارد و "
                                  "استهلاک ثبت‌شدهٔ گذشته را بازنویسی نمی‌کند.")

    def _build(self) -> None:
        self.method_combo = fill_combo(QComboBox(), A.METHODS,
                                       current=self.asset.method, placeholder="")
        self.add_row("روش جدید", self.method_combo)
        self.life_spin = QSpinBox()
        self.life_spin.setRange(1, 1200)
        self.life_spin.setSuffix(" ماه")
        self.life_spin.setValue(int(self.asset.useful_life_months or 60))
        self.add_row("عمر مفید جدید", self.life_spin)
        self.rate_edit = QLineEdit()
        self.rate_edit.setPlaceholderText("درصد سالانه (روش نزولی)")
        self.add_row("نرخ نزولی", self.rate_edit)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_row("تاریخ اجرا", self.date_edit)
        self.note_edit = QLineEdit()
        self.add_row("دلیل تغییر *", self.note_edit, required=True)

    def save(self):
        rate = self.rate_edit.text().strip()
        return self.services.assets.change_depreciation_policy(
            self.ctx, self.asset.id, method=str(self.method_combo.currentData()),
            useful_life_months=self.life_spin.value(),
            declining_rate=Decimal(rate) if rate else None,
            effective_date=self.date_edit.date(), note=self.note_edit.text().strip())


class MaintenanceDialog(FormDialog):
    title_fa = "تعمیر و نگهداری"
    width = 620

    def __init__(self, services, ctx, asset, parent: QWidget | None = None) -> None:
        self.asset = asset
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"{asset.code} — هزینهٔ تعمیر در حساب هزینه ثبت می‌شود.")

    def _build(self) -> None:
        self.kind_combo = fill_combo(QComboBox(), A.MAINT_KINDS,
                                     current=A.MAINT_SERVICE, placeholder="")
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("نوع", self.kind_combo), ("تاریخ سرویس", self.date_edit))
        self.cost_edit = MoneyEdit()
        self.contractor_edit = QLineEdit()
        self.add_pair(("هزینه", self.cost_edit), ("پیمانکار", self.contractor_edit))
        self.consumables_edit = QLineEdit()
        self.next_edit = JalaliDateEdit(None, allow_empty=True)
        self.add_pair(("مصرفی/قطعات", self.consumables_edit), ("سرویس بعدی", self.next_edit))
        self.description_edit = QLineEdit()
        self.add_row("شرح", self.description_edit)

    def save(self):
        return self.services.assets.add_maintenance(self.ctx, MaintenanceInput(
            asset_id=self.asset.id,
            kind=str(self.kind_combo.currentData()),
            service_date=self.date_edit.date(),
            cost=self.cost_edit.amount,
            contractor=self.contractor_edit.text().strip(),
            consumables=self.consumables_edit.text().strip(),
            description=self.description_edit.text().strip(),
            next_service_date=self.next_edit.date(),
        ))


class DisposalDialog(FormDialog):
    title_fa = "فروش / کنارگذاری دارایی"
    width = 620

    def __init__(self, services, ctx, asset, parent: QWidget | None = None) -> None:
        self.asset = asset
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"{asset.code} — ارزش دفتری "
                                  f"{asset.book_value:,}؛ سند فروش و رسید هم‌زمان صادر می‌شود.")

    def _build(self) -> None:
        self.kind_combo = fill_combo(QComboBox(), A.DISPOSAL_KINDS,
                                     current=A.DISPOSAL_SALE, placeholder="")
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("نوع", self.kind_combo), ("تاریخ", self.date_edit))
        self.sale_edit = MoneyEdit()
        self.buyer_edit = QLineEdit()
        self.add_pair(("مبلغ فروش", self.sale_edit), ("خریدار", self.buyer_edit))
        self.fund_picker = FundPicker()
        self.fund_picker.attach(self.services, self.ctx)
        self.add_row("محل دریافت وجه (در صورت فروش)", self.fund_picker)
        self.reason_edit = QLineEdit()
        self.add_row("دلیل/توضیح *", self.reason_edit, required=True)

    def save(self):
        kind, fund_id = self.fund_picker.require() if self.sale_edit.amount > 0 else ("cash", None)
        return self.services.assets.dispose(self.ctx, DisposalInput(
            asset_id=self.asset.id,
            kind=str(self.kind_combo.currentData()),
            disposal_date=self.date_edit.date(),
            sale_amount=self.sale_edit.amount,
            buyer_name=self.buyer_edit.text().strip(),
            reason=self.reason_edit.text().strip(),
            cash_box_id=fund_id if (fund_id and kind == TC.FUND_CASH) else None,
            bank_account_id=fund_id if (fund_id and kind == TC.FUND_BANK) else None,
            method=TC.METHOD_CASH if fund_id and kind == TC.FUND_CASH else TC.METHOD_TRANSFER,
        ))


class AssetsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "دارایی‌های ثابت",
            "ثبت دارایی، انتقال و امانت‌داری، تغییر سیاست استهلاک، تعمیر و فروش")
        self.new_button = self.header.add_action("دارایی جدید", slot=self._new)
        self.edit_button = self.header.add_action("ویرایش", variant="secondary",
                                                  slot=self._edit)
        self.transfer_button = self.header.add_action("انتقال", variant="secondary",
                                                      slot=self._transfer)
        self.policy_button = self.header.add_action("سیاست استهلاک", variant="secondary",
                                                    slot=self._policy)
        self.maintenance_button = self.header.add_action("تعمیر", variant="secondary",
                                                         slot=self._maintenance)
        self.dispose_button = self.header.add_action("فروش/کنارگذاری", variant="secondary",
                                                     slot=self._dispose)
        self.history_button = self.header.add_action("سابقه", variant="secondary",
                                                     slot=self._history)
        self.root.addWidget(self.header)

        bar = CardPanel("جست‌وجو و فیلتر")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی کد، نام یا سریال دارایی…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.category_combo = PickCombo()
        self.category_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("دسته", self.category_combo), 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in A.ASSET_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_combo), 1)
        self.location_edit = SearchInput("محل…")
        self.location_edit.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(form_row("محل", self.location_edit), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)

        body = QHBoxLayout()
        table_card = CardPanel("دارایی‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        table_card.add_header_widget(self.summary)
        self.table = DataTable(ASSET_COLUMNS, formatter=formatter)
        self.table.on_selection_changed(self._show_detail)
        table_card.add(self.table, 1)
        body.addWidget(table_card, 3)

        detail_card = CardPanel("جزئیات دارایی")
        detail_card.setMaximumWidth(340)
        layout = QVBoxLayout()
        layout.setSpacing(4)
        self.detail: dict[str, InfoRow] = {}
        for key, label in (("code", "کد"), ("title", "نام"), ("category", "دسته"),
                           ("location", "محل"), ("custodian", "امانت‌دار"),
                           ("service", "بهره‌برداری"), ("method", "روش استهلاک"),
                           ("initial", "بهای تمام‌شده"), ("accumulated", "استهلاک انباشته"),
                           ("book", "ارزش دفتری"), ("monthly", "استهلاک ماهانه"),
                           ("status", "وضعیت")):
            info = InfoRow(label)
            self.detail[key] = info
            layout.addWidget(info)
        layout.addStretch(1)
        detail_card.add_layout(layout)
        body.addWidget(detail_card, 1)
        self.root.addLayout(body, 1)

        can_register = self.can("assets.register")
        self.new_button.setEnabled(can_register)
        self.edit_button.setEnabled(can_register)
        self.transfer_button.setEnabled(self.can("assets.transfer"))
        self.policy_button.setEnabled(can_register)
        self.maintenance_button.setEnabled(self.can("assets.maintenance"))
        self.dispose_button.setEnabled(self.can("assets.dispose"))
        self.history_button.setEnabled(self.can("assets.view"))
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.category_combo.load(self.services.assets.category_choices(self.ctx))
            self.rows = self.services.assets.list_assets(
                self.ctx, search=self.search_input.text().strip(),
                category_id=self.category_combo.value(),
                status=self.status_combo.currentData(),
                location=self.location_edit.text().strip())
        except AppError as error:
            show_error(self, "دارایی‌های ثابت", error)
            return
        self.set_rows(self.table, self.rows)
        value = sum((row.book_value for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} دارایی — ارزش دفتری "
                             f"{self.formatter.amount(value)}")
        self._show_detail()

    def _selected(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    def _show_detail(self) -> None:
        row = self._selected()
        for info in self.detail.values():
            info.setVisible(row is not None)
        if row is None:
            return
        self.detail["code"].set_value(row.code)
        self.detail["title"].set_value(row.title_fa)
        self.detail["category"].set_value(row.category or "—")
        self.detail["location"].set_value(row.location or "—")
        self.detail["custodian"].set_value(row.custodian_name or "—")
        self.detail["service"].set_value(self.formatter.date(row.in_service_date))
        self.detail["method"].set_value(row.method_fa)
        self.detail["initial"].set_value(self.formatter.amount(row.initial_value))
        self.detail["accumulated"].set_value(self.formatter.amount(row.accumulated))
        self.detail["book"].set_value(self.formatter.amount(row.book_value))
        self.detail["monthly"].set_value(self.formatter.amount(row.monthly_depreciation))
        self.detail["status"].set_value(row.status_fa)

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = AssetDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دارایی {dialog.saved.code} ثبت شد.")

    def _edit(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "ویرایش", "ابتدا یک دارایی را انتخاب کنید.")
            return
        dialog = AssetDialog(self.services, self.ctx, asset_id=asset.id, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دارایی {asset.code} به‌روزرسانی شد.")

    def _transfer(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "انتقال", "ابتدا یک دارایی را انتخاب کنید.")
            return
        dialog = TransferDialog(self.services, self.ctx, asset, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("انتقال ثبت شد.")

    def _policy(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "سیاست استهلاک", "ابتدا یک دارایی را انتخاب کنید.")
            return
        dialog = PolicyDialog(self.services, self.ctx, asset, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("سیاست استهلاک تغییر کرد.")

    def _maintenance(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "تعمیر", "ابتدا یک دارایی را انتخاب کنید.")
            return
        dialog = MaintenanceDialog(self.services, self.ctx, asset, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("تعمیر و نگهداری ثبت شد.")

    def _dispose(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "فروش/کنارگذاری", "ابتدا یک دارایی را انتخاب کنید.")
            return
        if not confirm(self, "فروش/کنارگذاری",
                       f"دارایی {asset.code} از فهرست جاری خارج شود؟ سند و رسید صادر می‌شود.",
                       danger=True):
            return
        dialog = DisposalDialog(self.services, self.ctx, asset, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دارایی {asset.code} واگذار شد.")

    def _history(self) -> None:
        asset = self._selected()
        if asset is None:
            show_info(self, "سابقه", "ابتدا یک دارایی را انتخاب کنید.")
            return
        try:
            history = self.services.assets.history(self.ctx, asset.id)
        except AppError as error:
            show_error(self, "سابقه", error)
            return
        show_rows(self, f"سابقهٔ دارایی {asset.code}", ASSET_MOVEMENT_COLUMNS, history,
                  formatter=self.formatter,
                  subtitle="انتقال، تغییر امانت‌دار، محل، وضعیت و سیاست استهلاک")

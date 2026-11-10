"""Command line entry point: ``pars-erp`` / ``python -m pars_erp``."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from pars_erp import APP_NAME_DEFAULT, APP_NAME_EN, __version__
from pars_erp.config.paths import AppPaths
from pars_erp.config.settings import load_config
from pars_erp.core.errors import AppError
from pars_erp.services.context import build_services, prepare_application


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pars-erp",
        description=f"{APP_NAME_DEFAULT} ({APP_NAME_EN}) — نرم‌افزار حسابداری و مدیریت کسب‌وکار")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME_DEFAULT} ({APP_NAME_EN}) {__version__}")
    parser.add_argument("--home", type=str, default=None,
                        help="پوشه داده برنامه (پیش‌فرض: %APPDATA%/ZarrinHormoz)")
    parser.add_argument("--database-url", type=str, default=None,
                        help="آدرس پایگاه داده (پیش‌فرض از config.json)")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="اجرای رابط گرافیکی (پیش‌فرض)")
    run.add_argument("--no-startup-backup", action="store_true",
                     help="پشتیبان‌گیری خودکار در شروع برنامه انجام نشود")

    sub.add_parser("migrate", help="اجرای مهاجرت‌های پایگاه داده")
    backup = sub.add_parser("backup", help="ایجاد پشتیبان از خط فرمان")
    backup.add_argument("--note", type=str, default=None)
    info = sub.add_parser("info", help="نمایش وضعیت نصب")
    info.add_argument("--check", action="store_true", help="اجرای بررسی‌های سلامت")
    recover = sub.add_parser("recover-admin", help="بازیابی رمز مدیر سیستم (کنترل‌شده)")
    recover.add_argument("--username", type=str, default=None)
    recover.add_argument("--phrase", type=str, default=None,
                         help="عبارت تأیید؛ در صورت عدم ارائه به‌صورت تعاملی پرسیده می‌شود")
    recover.add_argument("--list", action="store_true", help="فقط فهرست مدیران را نشان بده")
    return parser


def _resolve_paths(args) -> AppPaths:
    if args.home:
        paths = AppPaths(Path(args.home).expanduser().resolve())
    else:
        paths = AppPaths.default()
    return paths.ensure()


def _load_services(args):
    paths = _resolve_paths(args)
    config = load_config(paths)
    url = args.database_url or config.database_url
    from pars_erp.logging_setup import configure_logging
    configure_logging(paths.logs_dir, config)
    services = build_services(paths=paths, config=config,
                              db=__import__("pars_erp.db.session", fromlist=["Database"])
                              .Database(url))
    return services


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command or "run"

    if command == "run":
        from pars_erp.app import AppOptions, run_gui
        paths = _resolve_paths(args)
        if args.database_url:
            os.environ["PARSERP_DATABASE_URL"] = args.database_url
        options = AppOptions(paths=paths,
                             run_startup_backup=not getattr(args, "no_startup_backup", False))
        try:
            return run_gui(options)
        except AppError as exc:
            print(f"خطا: {exc}", file=sys.stderr)
            return 2

    services = _load_services(args)
    try:
        if command == "migrate":
            revision = services.db.migrate()
            print(f"پایگاه داده به نسخه ساختار «{revision}» به‌روزرسانی شد.")
            return 0

        if command == "backup":
            prepare_application(services, run_startup_backup=False)
            from pars_erp.maintenance import create_backup_cli
            name = create_backup_cli(services, args.note)
            print(f"پشتیبان ایجاد شد: {name}")
            print(f"مسیر: {services.paths.backups_dir}")
            return 0

        if command == "info":
            from pars_erp.maintenance import integrity_report, system_info
            prepare_application(services, run_startup_backup=False)
            info = system_info(services)
            labels = {
                "app_version": "نسخه برنامه", "backend": "موتور پایگاه داده",
                "database_url": "آدرس پایگاه داده", "home": "پوشه داده",
                "schema_revision": "نسخه ساختار", "users": "تعداد کاربران",
                "needs_setup": "نیازمند راه‌اندازی اولیه",
                "has_active_admin": "مدیر فعال دارد", "last_backup": "آخرین پشتیبان",
            }
            for key, label in labels.items():
                value = info.get(key)
                if isinstance(value, bool):
                    value = "بله" if value else "خیر"
                print(f"{label}: {value if value is not None else '—'}")
            if args.check:
                print("\nبررسی سلامت:")
                for title, ok, detail in integrity_report(services):
                    mark = "✓" if ok else "✗"
                    print(f"  {mark} {title} — {detail}")
            return 0

        if command == "recover-admin":
            prepare_application(services, run_startup_backup=False)
            from pars_erp.maintenance import RECOVERY_PHRASE, list_administrators, recover_admin_password
            admins = list_administrators(services)
            if not admins:
                print("هیچ حساب مدیری وجود ندارد. ابتدا راه‌اندازی اولیه را از رابط گرافیکی انجام دهید.",
                      file=sys.stderr)
                return 3
            if getattr(args, "list", False):
                print("حساب‌های مدیر:")
                for username, full_name, is_active, is_locked in admins:
                    state = "فعال" if is_active else "غیرفعال"
                    if is_locked:
                        state += " (قفل‌شده)"
                    print(f"  - {username} ({full_name}) — {state}")
                return 0
            username = args.username
            if not username:
                print("حساب‌های مدیر موجود:")
                for username_option, full_name, _active, _locked in admins:
                    print(f"  - {username_option} ({full_name})")
                username = input("نام کاربری مدیر: ").strip()
            print("این عملیات رمز عبور مدیر را بدون نیاز به رمز قبلی تغییر می‌دهد و "
                  "در گزارش رویدادهای امنیتی ثبت می‌شود.")
            phrase = args.phrase or input(f"برای ادامه عبارت «{RECOVERY_PHRASE}» را وارد کنید: ")
            if phrase.strip() != RECOVERY_PHRASE:
                print("عبارت تأیید نادرست است. عملیات لغو شد.", file=sys.stderr)
                return 4
            password = getpass.getpass("رمز عبور جدید: ")
            confirm = getpass.getpass("تکرار رمز عبور جدید: ")
            result = recover_admin_password(services, username=username, new_password=password,
                                            confirm_password=confirm, confirm_phrase=phrase)
            print(result.message_fa)
            return 0

        print(f"دستور ناشناخته: {command}", file=sys.stderr)
        return 2
    except AppError as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        return 2
    finally:
        services.dispose()

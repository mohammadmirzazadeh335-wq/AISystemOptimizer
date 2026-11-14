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
from pars_erp.core.errors import AppError, ConfigurationError
from pars_erp.db.session import Database, describe_connection_error
from pars_erp.services.context import build_services, prepare_application


#: Options that belong to the whole program. argparse only accepts them *before*
#: the sub-command; every user who types ``pars-erp info --home X`` deserves a
#: working command rather than an English "unrecognized arguments" message.
GLOBAL_OPTIONS_WITH_VALUE = ("--home", "--database-url")


class _Parser(argparse.ArgumentParser):
    """argparse with Persian messages instead of the English defaults."""

    def error(self, message: str) -> None:  # noqa: D401 - argparse hook
        print(f"خطا: دستور یا گزینه درست نیست ({message}).", file=sys.stderr)
        print("برای دیدن راهنما اجرا کنید: pars-erp --help", file=sys.stderr)
        raise SystemExit(2)


def _reorder_global_options(argv: list[str]) -> list[str]:
    """Move ``--home``/``--database-url`` in front of the sub-command."""
    head: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in GLOBAL_OPTIONS_WITH_VALUE and index + 1 < len(argv):
            head.extend([token, argv[index + 1]])
            index += 2
            continue
        for name in GLOBAL_OPTIONS_WITH_VALUE:
            if token.startswith(name + "="):
                head.append(token)
                break
        else:
            rest.append(token)
        index += 1
    return head + rest


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pars-erp",
        description=f"{APP_NAME_DEFAULT} ({APP_NAME_EN}) — نرم‌افزار حسابداری و مدیریت کسب‌وکار")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME_DEFAULT} ({APP_NAME_EN}) {__version__}")
    parser.add_argument("--home", type=str, default=None,
                        help="پوشه داده برنامه (پیش‌فرض: %%APPDATA%%\\ParsERP)")
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
    doctor = sub.add_parser("doctor", help="بررسی سلامت کامل نصب (پایگاه داده، ساختار، به‌روزرسانی، پشتیبان)")
    doctor.add_argument("--json", action="store_true", help="خروجی ماشین‌خوان")
    upd = sub.add_parser("update", help="بررسی، آماده‌سازی و بازگردانی به‌روزرسانی")
    upd.add_argument("action", choices=("status", "check", "stage", "rollback"))
    upd.add_argument("--package", type=str, default=None, help="فایل بستهٔ به‌روزرسانی")
    upd.add_argument("--version", type=str, default=None, help="نسخهٔ هدف (برای stage)")
    upd.add_argument("--confirm", type=str, default=None,
                     help="عبارت تأیید بازگردانی (برای rollback)")
    recover = sub.add_parser("recover-admin", help="بازیابی رمز مدیر سیستم (کنترل‌شده)")
    recover.add_argument("--username", type=str, default=None)
    recover.add_argument("--phrase", type=str, default=None,
                         help="عبارت تأیید؛ در صورت عدم ارائه به‌صورت تعاملی پرسیده می‌شود")
    recover.add_argument("--list", action="store_true", help="فقط فهرست مدیران را نشان بده")
    return parser


def _home_of(args) -> Path:
    try:
        return _resolve_paths(args).home
    except Exception:  # pragma: no cover - unwritable home
        return Path(args.home).expanduser() if getattr(args, "home", None) else AppPaths.default().home


def _error_id() -> str:
    """A short, quotable id so a user can report a failure without a traceback."""
    import secrets

    return secrets.token_hex(3).upper()


def _report_failure(exc: BaseException, *, context: str, home: Path | None = None) -> int:
    """Print one Persian sentence (never a traceback) and return an exit code."""
    import logging

    logger = logging.getLogger("pars_erp.cli")
    if not logging.getLogger().handlers and home is not None:
        # the configuration itself could not be read; still leave a log behind
        try:
            from pars_erp.config.settings import FileConfig
            from pars_erp.logging_setup import configure_logging

            configure_logging(Path(home) / "logs", FileConfig())
        except Exception:  # pragma: no cover - a read-only home
            pass
    error_id = _error_id()
    logger.error("cli failure [%s] during %s", error_id, context, exc_info=exc,
                 extra={"file_only": True})
    if isinstance(exc, ConfigurationError):
        message = str(exc)
        code = 2
    elif isinstance(exc, AppError):
        message = str(exc)
        code = 2
    else:
        message = describe_connection_error(exc)
        code = 3 if message != f"{type(exc).__name__}: {exc}" else 1
    print(f"خطا: {message}", file=sys.stderr)
    print(f"شناسهٔ خطا: {error_id} (جزئیات فنی در فایل لاگ ثبت شد)", file=sys.stderr)
    return code


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
    services = build_services(paths=paths, config=config, db=Database(url))
    return services


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(_reorder_global_options(raw))
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

    try:
        services = _load_services(args)
    except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
        return _report_failure(exc, context=f"آماده‌سازی سرویس‌ها ({command})",
                               home=_home_of(args))
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

        if command == "doctor":
            import json as _json

            from pars_erp.maintenance import integrity_report
            prepare_application(services, run_startup_backup=False)
            from pars_erp.services.update_service import HEALTH_TITLES_FA, UpdateError

            rows = list(integrity_report(services))
            try:
                health = services.updates.health_check(None, system=True)
                rows.extend((HEALTH_TITLES_FA.get(name, name), value, "")
                            for name, value in health.checks.items())
            except UpdateError as exc:  # pragma: no cover - defensive
                rows.append(("به‌روزرسانی", False, str(exc)))
            if args.json:
                print(_json.dumps(
                    [{"title": t, "ok": ok, "detail": d} for t, ok, d in rows],
                    ensure_ascii=False, indent=2))
            else:
                for title, ok, detail in rows:
                    print(f"{'✓' if ok else '✗'} {title}" + (f" — {detail}" if detail else ""))
            return 0 if all(ok for _t, ok, _d in rows) else 4

        if command == "update":
            prepare_application(services, run_startup_backup=False)
            from pars_erp.services.update_service import UpdateError

            try:
                if args.action == "status":
                    result = services.updates.check(None, system=True)
                    print(f"{result.status_fa} — {result.message_fa}")
                    if result.release is not None:
                        print(result.release.notes_text())
                    return 0
                if args.action == "check":
                    result = services.updates.check(None, system=True)
                    print(result.status)
                    return 0 if result.has_update else 0
                if args.action == "stage":
                    if not args.package:
                        print("برای آماده‌سازی، --package لازم است.", file=sys.stderr)
                        return 2
                    result = services.updates.check(None, system=True)
                    if result.release is None:
                        print(f"هیچ نسخهٔ تازه‌تری موجود نیست: {result.message_fa}",
                              file=sys.stderr)
                        return 3
                    release = result.release
                    if args.version and args.version != release.version:
                        print(f"نسخهٔ هدف {args.version} با مانیفست ({release.version}) "
                              f"هم‌خوان نیست.", file=sys.stderr)
                        return 2
                    staged = services.updates.stage(None, release, Path(args.package),
                                                    system=True)
                    print(staged.message_fa)
                    if staged.backup:
                        print(f"پشتیبان پیش از به‌روزرسانی: {staged.backup}")
                    return 0
                # rollback
                backup = services.updates.rollback(None, confirm_phrase=args.confirm or "",
                                                   system=True)
                print(f"پایگاه داده از «{backup.name}» بازگردانده شد.")
                return 0
            except UpdateError as exc:
                print(f"خطا: {exc}", file=sys.stderr)
                return 3
            except AppError as exc:
                print(f"خطا: {exc}", file=sys.stderr)
                return 2

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
        return _report_failure(exc, context=command, home=services.paths.home)
    except BaseException as exc:  # noqa: BLE001 - logged with an id, then reported
        return _report_failure(exc, context=command, home=services.paths.home)
    finally:
        services.dispose()
        from pars_erp.logging_setup import close_logging

        close_logging()

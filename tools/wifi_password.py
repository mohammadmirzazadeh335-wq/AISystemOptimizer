#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wifi_password.py — اسکنر وای‌فای + نمایش رمز ذخیره‌شده روی همین کامپیوتر
==========================================================================

یک فایل، بدون هیچ کتابخانه‌ی بیرونی. در ترمینال VS Code اجرا می‌شود:

    python tools/wifi_password.py

چه کاری می‌کند؟
  1) شبکه‌های وای‌فای اطراف را پیدا می‌کند و با شماره (1, 2, 3, ...) لیست می‌کند.
  2) شماره را از تو می‌گیرد.
  3) اگر آن شبکه قبلاً روی همین سیستم ذخیره شده باشد (یعنی خودت یک بار
     به آن وصل شده‌ای)، رمزش را از مخزن رمزِ خودِ سیستم‌عامل می‌خواند و چاپ می‌کند:
         pass: ********
  4) اگر شبکه ذخیره نشده باشد، صادقانه می‌گوید رمز قابل بازیابی نیست.

چه کاری نمی‌کند (به‌عمد)؟
  رمز شبکه‌ی دیگران را «نمی‌شکند». نه handshake می‌گیرد، نه دیکشنری
  (brute-force) اجرا می‌کند. رمز وای‌فای یک شبکه‌ی متعلق به دیگری، رمز
  حساب کسی است؛ شکستنش در همه‌جا غیرقانونی است. این اسکریپت فقط چیزی را
  برمی‌گرداند که *خودِ سیستم‌عاملِ خودت* برای تو ذخیره کرده است.

روش کار در هر سیستم‌عامل:
  • Windows : netsh wlan export profile  (خواندن <keyMaterial> از XML پروفایل)
              چرا XML؟ چون تگ‌های XML ترجمه نمی‌شوند و روی ویندوز فارسی/آلمانی/
              ... هم درست کار می‌کند. فایل موقت بلافاصله پاک می‌شود.
  • Linux   : nmcli --show-secrets  (NetworkManager)
  • macOS   : security find-generic-password  (Keychain؛ ممکن است اجازه بخواهد)

نصب پیش‌نیاز: فقط پایتون ۳ (ویندوز ۱۰/۱۱ معمولاً netsh دارد؛ لینوکس نیاز به
NetworkManager/nmcli دارد). هیچ pip install ای لازم نیست.
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# ───────────────────────────── تنظیمات کوچک ─────────────────────────────

TIMEOUT = 45  # ثانیه، برای هر دستور سیستم

BAR_STEPS = [(80, "▂▄▆█"), (60, "▂▄▆_"), (40, "▂▄__"), (20, "▂___"), (0, "____")]

# برچسب‌های «Key Content» در زبان‌های مختلف (فقط برای مسیر جایگزینِ ویندوز)
WINDOWS_KEY_LABELS = (
    "key content", "schlüsselinhalt", "contenido de la clave", "contenu de la clé",
    "contenuto della chiave", "содержимое ключа", "anahtar i̇çeriği", "anahtar içeriği",
    "محتویات کلید", "محتوای کلید", "محتوى المفتاح", "ključ", "inhoud van sleutel",
    "chave de segurança", "nyckel", "nøkkelinnhold", "nøgleindhold",
)


# ───────────────────────────── ابزارهای عمومی ─────────────────────────────

def decode_bytes(data: bytes) -> str:
    """خروجی دستورهای سیستم را با مناسب‌ترین کدگذاری به متن تبدیل می‌کند."""
    candidates = ["utf-8"]
    if platform.system() == "Windows":
        try:  # کدپیج OEM ویندوز (مثلاً 437 / 850 / 1256)
            import ctypes

            candidates.append("cp%d" % ctypes.windll.kernel32.GetOEMCP())
        except Exception:
            pass
        candidates += ["cp1256", "cp1252", "cp437"]
    else:
        import locale

        enc = locale.getpreferredencoding(False)
        if enc:
            candidates.append(enc)
        candidates.append("cp1256")

    for enc in candidates:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def run(cmd: list[str]) -> tuple[int, str]:
    """دستور را اجرا می‌کند و (کد خروج، خروجی) برمی‌گرداند. هیچ‌وقت استثنا نمی‌دهد."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except Exception as exc:  # pragma: no cover - موارد نادر سیستم‌عامل
        return 1, str(exc)

    out = decode_bytes(proc.stdout)
    err = decode_bytes(proc.stderr)
    if err.strip():
        out = (out + "\n" + err).strip()
    return proc.returncode, out


def signal_bar(signal: int) -> str:
    for threshold, bar in BAR_STEPS:
        if signal >= threshold:
            return bar
    return "____"


def emit(text: str = "") -> None:
    """چاپ امن (روی کنسول‌های قدیمی ویندوز هم کرش نکند)."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, "replace").decode(enc, "replace"))


# ───────────────────────────── اسکن شبکه‌ها ─────────────────────────────

def _scan_windows() -> tuple[list[dict], str]:
    code, out = run(["netsh", "wlan", "show", "networks", "mode=bssid"])
    if not re.search(r"(?mi)^\s*SSID\s+\d+\s*:", out):
        hint = out.strip().splitlines()[-1] if out.strip() else "خروجی خالی"
        return [], (
            "نتوانستم لیست شبکه‌ها را بخوانم.\n"
            "  • مطمئن شو Wi-Fi روشن است و «WLAN AutoConfig» در سرویس‌ها فعال است.\n"
            "  • در ویندوز ۱۱ ممکن است لازم باشد «Location permission» برای اپ‌های دسکتاپ روشن باشد.\n"
            f"  • پیام سیستم: {hint}"
        )

    networks: list[dict] = []
    current: dict | None = None
    auth_re = re.compile(r"\b(Open|WEP|WPA[0-9A-Za-z\-]*(?:-Enterprise|-Personal)?|OWE|Enhanced Open|802\.1X)\b", re.I)

    for raw_line in out.splitlines():
        line = raw_line.rstrip()
        header = re.match(r"^\s*SSID\s+\d+\s*:\s*(.*)$", line)
        if header:
            name = header.group(1).strip()
            current = None
            if name:  # شبکه‌ی مخفی (بدون نام) را رد می‌کنیم
                current = {"ssid": name, "signal": 0, "security": ""}
                networks.append(current)
            continue

        if current is None:
            continue

        percent = re.search(r":\s*(\d{1,3})\s*%", line)
        if percent:
            current["signal"] = max(current["signal"], min(100, int(percent.group(1))))

        if not current["security"]:
            found = auth_re.search(line.split(":", 1)[-1])
            if found:
                current["security"] = found.group(1)

    return _merge_same_ssid(networks), ""


def _scan_linux() -> tuple[list[dict], str]:
    if not shutil.which("nmcli"):
        return [], "nmcli پیدا نشد. روی لینوکس به NetworkManager نیاز است (sudo apt install network-manager)."

    code, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"])
    if code != 0:
        return [], f"nmcli خطا داد:\n{out.strip()}"

    networks: list[dict] = []
    for line in out.splitlines():
        parts = _nmcli_split(line)
        if len(parts) < 3:
            continue
        ssid = parts[0].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[1])
        except ValueError:
            signal = 0
        security = parts[2].strip() or "Open"
        networks.append({"ssid": ssid, "signal": signal, "security": security})

    return _merge_same_ssid(networks), ""


def _scan_macos() -> tuple[list[dict], str]:
    airport = ("/System/Library/PrivateFrameworks/Apple80211.framework/"
               "Versions/Current/Resources/airport")
    if not os.path.exists(airport):
        return [], ("ابزار airport در این نسخه از macOS حذف شده است.\n"
                    "  • از منوی Wi-Fi در نوار بالا یا «System Settings → Wi-Fi» لیست شبکه‌ها را ببین.")
    code, out = run([airport, "-s"])
    if code != 0:
        return [], f"airport خطا داد:\n{out.strip()}"

    networks: list[dict] = []
    for line in out.splitlines()[1:]:
        m = re.match(r"\s*(.+?)\s+([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+(-?\d+)\s+(\d+)\s+(\S+)(?:\s+(.*))?$",
                     line, re.I)
        if not m:
            continue
        ssid = m.group(1).strip()
        rssi = int(m.group(3))
        signal = max(0, min(100, 2 * (rssi + 100)))
        networks.append({"ssid": ssid, "signal": signal, "security": (m.group(6) or "").strip()})
    return _merge_same_ssid(networks), ""


def _merge_same_ssid(networks: list[dict]) -> list[dict]:
    """چند آنتن با یک نام را یکی می‌کند (قوی‌ترین سیگنال می‌ماند)."""
    merged: dict[str, dict] = {}
    for net in networks:
        key = net["ssid"].casefold()
        if key not in merged:
            merged[key] = dict(net)
        else:
            merged[key]["signal"] = max(merged[key]["signal"], net["signal"])
            if not merged[key]["security"]:
                merged[key]["security"] = net["security"]
    return sorted(merged.values(), key=lambda n: (-n["signal"], n["ssid"].casefold()))


def scan_networks() -> tuple[list[dict], str]:
    system = platform.system()
    if system == "Windows":
        return _scan_windows()
    if system == "Linux":
        return _scan_linux()
    if system == "Darwin":
        return _scan_macos()
    return [], f"سیستم‌عامل «{system}» پشتیبانی نمی‌شود."


def _nmcli_split(line: str) -> list[str]:
    """خط خروجی nmcli -t را با در نظر گرفتن \\: و \\\\ تقسیم می‌کند."""
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            buf.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


# ─────────────────── پروفایل‌های ذخیره‌شده روی این سیستم ───────────────────

def saved_profile_names() -> set[str]:
    """نام شبکه‌هایی که روی همین سیستم پروفایل ذخیره دارند."""
    system = platform.system()
    names: set[str] = set()

    if system == "Windows":
        code, out = run(["netsh", "wlan", "show", "profiles"])
        for line in out.splitlines():
            if ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    names.add(value.casefold())

    elif system == "Linux":
        if shutil.which("nmcli"):
            code, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
            for line in out.splitlines():
                parts = _nmcli_split(line)
                if len(parts) >= 2 and "wireless" in parts[1]:
                    names.add(parts[0].casefold())

    return names


# ───────────────────────── بازیابی رمز ذخیره‌شده ─────────────────────────

def saved_password(ssid: str) -> tuple[str | None, str]:
    """
    (رمز، توضیح) برمی‌گرداند.
    رمز فقط وقتی برمی‌گردد که این سیستم پروفایلِ ذخیره‌شده‌ی آن شبکه را داشته باشد.
    """
    system = platform.system()
    if system == "Windows":
        return _password_windows(ssid)
    if system == "Linux":
        return _password_linux(ssid)
    if system == "Darwin":
        return _password_macos(ssid)
    return None, f"سیستم‌عامل «{system}» پشتیبانی نمی‌شود."


def _password_windows(ssid: str) -> tuple[str | None, str]:
    tmp_dir = tempfile.mkdtemp(prefix="wifi_prof_")
    try:
        code, out = run(["netsh", "wlan", "export", "profile", f'name={ssid}',
                         "key=clear", f"folder={tmp_dir}"])
        files = glob.glob(os.path.join(tmp_dir, "*.xml"))
        if not files:
            # مسیر جایگزین: خواندن متن netsh و جست‌وجوی برچسب «Key Content» به چند زبان
            code, out = run(["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"])
            for line in out.splitlines():
                if ":" not in line:
                    continue
                label, value = line.split(":", 1)
                if any(w in label.strip().casefold() for w in WINDOWS_KEY_LABELS) and value.strip():
                    return value.strip(), "از پروفایل ذخیره‌شده‌ی ویندوز خوانده شد (روش متنی)."
            return None, ("این شبکه روی سیستم تو ذخیره نشده است (هرگز به آن وصل نشده‌ای)، "
                          "پس رمزی برای خواندن وجود ندارد.")

        key = None
        for path in files:
            try:
                tree = ET.parse(path)
            except ET.ParseError:
                continue
            for element in tree.iter():
                tag = element.tag.split("}")[-1].lower()
                if tag == "keymaterial" and element.text and element.text.strip():
                    key = element.text.strip()
                    break
                if tag in ("keycontent",) and element.text and element.text.strip():
                    key = element.text.strip()
                    break
            if key:
                break

        if key:
            return key, "از پروفایل ذخیره‌شده‌ی ویندوز خوانده شد."
        return None, ("پروفایل هست، اما ویندوز برای آن رمزی ذخیره نکرده است "
                      "(شبکه‌ی باز یا ورود ۸۰۲.۱X با نام کاربری سازمانی).")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # فایل حاوی رمز را پاک می‌کنیم


def _password_linux(ssid: str) -> tuple[str | None, str]:
    if not shutil.which("nmcli"):
        return None, "nmcli موجود نیست، پس نمی‌توان رمز ذخیره‌شده را خواند."

    code, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    target = None
    for line in out.splitlines():
        parts = _nmcli_split(line)
        if len(parts) >= 2 and parts[0].casefold() == ssid.casefold() and "wireless" in parts[1]:
            target = parts[0]
            break

    if target is None:
        return None, ("این شبکه روی سیستم تو ذخیره نشده است (هرگز به آن وصل نشده‌ای)، "
                      "پس رمزی برای خواندن وجود ندارد.")

    code, out = run(["nmcli", "--show-secrets", "-t", "-f",
                     "802-11-wireless-security.psk", "connection", "show", target])
    value = ""
    for line in out.splitlines():
        if "psk" in line.lower():
            value = _nmcli_split(line)[-1].strip()
            break

    if value:
        return value, "از پروفایل ذخیره‌شده‌ی NetworkManager خوانده شد."
    return None, ("پروفایل هست، اما رمزی در آن ذخیره نشده است "
                  "(شبکه‌ی باز یا ورود سازمانی/802.1X).")


def _password_macos(ssid: str) -> tuple[str | None, str]:
    code, out = run(["security", "find-generic-password", "-D", "AirPort network password",
                     "-a", ssid, "-w"])
    password = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if code == 0 and password:
        return password, "از Keychain مک خوانده شد."
    return None, ("در Keychain این مک رمزی برای این شبکه پیدا نشد "
                  "(یا ذخیره نشده، یا دسترسی رد شد).")


# ───────────────────────────── رابط کاربری ─────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║  WiFi Scanner + Saved Password Viewer                        ║
║  اسکن وای‌فای و نمایش رمز شبکه‌هایی که روی این سیستم ذخیره‌اند ║
╚══════════════════════════════════════════════════════════════╝
"""

NOTE = ("توجه: این ابزار رمز شبکه‌ی دیگران را نمی‌شکند. فقط رمزی را نشان می‌دهد که\n"
        "خودِ همین ویندوز/لینوکس برای تو ذخیره کرده است (شبکه‌هایی که قبلاً به آن‌ها\n"
        "وصل شده‌ای). برای رمز شبکه‌ای که مالک آن نیستی، از صاحبش بپرس.\n")


def print_network_table(networks: list[dict], saved: set[str]) -> None:
    width = max((len(n["ssid"]) for n in networks), default=10)
    width = min(max(width, 12), 34)
    emit("")
    emit(f"  {'#':<3} {'نام شبکه':<{width}}  {'سیگنال':<8} {'قدرت':>5}  {'امنیت':<16} وضعیت")
    emit("  " + "─" * (width + 46))
    for index, net in enumerate(networks, start=1):
        ssid = net["ssid"]
        shown = ssid if len(ssid) <= width else ssid[: width - 1] + "…"
        marker = "✓ رمز ذخیره‌شده" if ssid.casefold() in saved else "—"
        emit(f"  {index:<3} {shown:<{width}}  {signal_bar(net['signal']):<8} "
             f"{net['signal']:>4}%  {(net['security'] or '?'):<16} {marker}")
    emit("")


def interactive() -> None:
    emit(BANNER)
    emit(NOTE)

    networks: list[dict] = []
    while True:
        emit("در حال اسکن شبکه‌های وای‌فای ...")
        networks, error = scan_networks()
        if error:
            emit("\n[!] " + error)
            return
        if not networks:
            emit("\n[!] هیچ شبکه‌ای پیدا نشد. Wi-Fi روشن است؟ کمی نزدیک‌تر به مودم امتحان کن.")
            return

        saved = saved_profile_names()
        print_network_table(networks, saved)
        break

    while True:
        try:
            answer = input("شماره وای‌فای مورد نظر (r = اسکن مجدد، q = خروج): ").strip()
        except (EOFError, KeyboardInterrupt):
            emit("\nخداحافظ.")
            return

        if answer.lower() in ("q", "quit", "exit", "خروج"):
            emit("خداحافظ.")
            return

        if answer.lower() in ("r", "rescan", "اسکن"):
            interactive()
            return

        if not answer.isdigit() or not (1 <= int(answer) <= len(networks)):
            emit(f"[!] یک عدد بین 1 تا {len(networks)} وارد کن.")
            continue

        chosen = networks[int(answer) - 1]
        emit("")
        emit(f"انتخاب شد: {chosen['ssid']}   (سیگنال {chosen['signal']}%، "
             f"امنیت {chosen['security'] or 'نامشخص'})")
        emit("در حال بررسی مخزن رمزهای همین سیستم ...")

        password, note = saved_password(chosen["ssid"])
        if password:
            emit(f"pass: {password}")
            emit(f"      ({note})")
        else:
            emit("pass: ——")
            emit(f"      {note}")
            emit("      رمز یک شبکه‌ی WPA2 که روی این سیستم ذخیره نشده، بدون حمله‌ی")
            emit("      غیرقانونی به handshake قابل بازیابی نیست؛ این اسکریپت چنین کاری نمی‌کند.")
        emit("")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    args = [a.lower() for a in sys.argv[1:]]

    if "--help" in args or "-h" in args:
        emit(__doc__ or "")
        return 0

    if "--list" in args or "--list-only" in args:
        networks, error = scan_networks()
        if error:
            emit("[!] " + error)
            return 1
        print_network_table(networks, saved_profile_names())
        return 0

    if "--all" in args:
        names = sorted(saved_profile_names())
        if not names:
            emit("[!] هیچ پروفایل ذخیره‌شده‌ای پیدا نشد.")
            return 1
        for name in names:
            password, note = saved_password(name)
            emit(f"[{name}]")
            emit(f"pass: {password}" if password else f"pass: ——  ({note})")
        return 0

    interactive()
    return 0


if __name__ == "__main__":
    sys.exit(main())

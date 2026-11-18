#!/usr/bin/env python3
"""Focused tests for PHASE 6: page redesign system.

Covers: analyze (inventory + critique + proposal), preview (draft copy,
original untouched, content preserved), apply gated by confirm + snapshot
protection, rollback via snapshot restore, compare (declared screenshot
limitation).

Usage: python3 redesign_test.py
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("AIWC_TEST_BASE", "http://127.0.0.1:9400")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CREDS_FILE = os.path.join(REPO, "ai-wordpress-copilot", ".test-credentials")
API = BASE + "/wp-json/ai-copilot/v1"
TEST_API = BASE + "/wp-json/aiwc-test/v1"
WP_API = BASE + "/wp-json/wp/v2"

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS  " + name)
    else:
        FAIL += 1
        print("FAIL  " + name + ("  -> " + str(detail) if detail else ""))


def parse_json_loose(body):
    text = body.decode(errors="replace") if isinstance(body, bytes) else str(body)
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return json.loads(text[i:])
            except Exception:
                continue
    return {}


def req(path, method="GET", body=None, base=None):
    url = (base or API) + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = json.load(open(CREDS_FILE))
    token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
    r.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.getcode(), parse_json_loose(resp.read())
    except urllib.error.HTTPError as e:
        try:
            payload = parse_json_loose(e.read())
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def exec_tool(name, args):
    code, data = req("/exec-tool", "POST", {"name": name, "args": args}, base=TEST_API)
    return code == 200 and data.get("success") is True, data


def wait_ready(timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(BASE + "/wp-json/", timeout=20) as resp:
                if resp.getcode() == 200:
                    code, data = req("/creds?key=smoke", base=TEST_API)
                    if code == 200 and "user" in data:
                        with open(CREDS_FILE, "w") as fh:
                            json.dump({"user": data["user"], "pass": data["pass"]}, fh)
                        return True
        except Exception:
            pass
        time.sleep(3)
    return False


def main():
    print("== PHASE 6 redesign tests against " + BASE + " ==")
    if not wait_ready():
        check("wordpress boot + credentials", False, "site not reachable")
        return 1
    check("wordpress boot + credentials", True)

    # --- Setup: a page with real content (classic HTML, like an old page) ---
    req("/settings", "POST", {"preferred_builder": "gutenberg"})
    original_html = (
        "<h1>فروشگاه قدیمی ما</h1>"
        "<p>این فروشگاه از سال ۱۳۹۰ فعالیت می‌کند و محصولات باکیفیت ارائه می‌دهد.</p>"
        "<h2>محصولات ویژه</h2>"
        "<p>ما بهترین محصولات دیجیتال را با قیمت مناسب عرضه می‌کنیم و ارسال سریع داریم.</p>"
        "<img src='http://127.0.0.1:8899/status/200' alt='محصول' />"
        "<p><a href='http://127.0.0.1:8899/status/200'>مشاهده محصولات</a></p>"
    )
    code, page = req("/pages", "POST", {
        "title": "صفحه بازطراحی",
        "content": original_html,
        "status": "publish",
    }, base=WP_API)
    post_id = page.get("id", 0)
    check("setup: test page created", code in (200, 201) and post_id > 0, (code, page))

    # --- A. analyze ---
    ok, data = exec_tool("redesign_page", {"post_id": post_id, "action": "analyze"})
    analysis = data.get("data") or {}
    inv = analysis.get("inventory") or {}
    check("analyze: inventory extracted (headings/texts/images)",
          ok and len(inv.get("headings", [])) >= 2 and inv.get("texts") and inv.get("images"), inv.keys())
    check("analyze: critique present (evidence-based)",
          bool(analysis.get("critique")), analysis.get("critique"))
    proposal = analysis.get("proposal") or {}
    check("analyze: proposal has sections + preserved content",
          proposal.get("sections") and proposal.get("preserved", {}).get("headings"), list(proposal.keys()))
    check("analyze: nothing removed without permission",
          proposal.get("removed") == [], proposal.get("removed"))
    check("analyze: preserved includes original heading",
          any("فروشگاه قدیمی ما" in h for h in proposal.get("preserved", {}).get("headings", [])),
          proposal.get("preserved", {}).get("headings"))

    # --- B. preview (original untouched) ---
    ok, data = exec_tool("redesign_page", {"post_id": post_id, "action": "preview", "proposal": proposal})
    preview = data.get("data") or {}
    preview_id = preview.get("preview_id", 0)
    check("preview: draft preview built", ok and preview_id > 0, preview)
    checks = preview.get("checks") or {}
    check("preview: checks ok (structure + content preserved)", checks.get("ok") is True, checks)
    code, orig = req("/pages/%d?context=edit" % post_id, "GET", None, base=WP_API)
    orig_raw = orig.get("content", {}).get("raw", "")
    check("preview: original page untouched", original_html.strip() in orig_raw or "فروشگاه قدیمی ما" in orig_raw, orig_raw[:120])
    code, prev = req("/pages/%d?context=edit" % preview_id, "GET", None, base=WP_API)
    check("preview: preview is draft", prev.get("status") == "draft", prev.get("status"))
    prev_raw = prev.get("content", {}).get("raw", "")
    check("preview: original heading preserved in preview", "فروشگاه قدیمی ما" in prev_raw or "فروشگاه قدیمی" in prev_raw, prev_raw[:120])

    # --- C. apply without confirm → refused ---
    ok, data = exec_tool("redesign_page", {"post_id": post_id, "action": "apply", "preview_id": preview_id})
    err = json.dumps(data, ensure_ascii=False)
    check("apply without confirm → refused", not ok and ("confirmation" in err or "تأیید" in err), err[:200])
    code, orig = req("/pages/%d?context=edit" % post_id, "GET", None, base=WP_API)
    check("apply refused → original still untouched", "فروشگاه قدیمی ما" in (orig.get("content", {}).get("raw", "")), "")

    # --- D. apply with confirm → snapshot-protected apply ---
    ok, data = exec_tool("redesign_page", {"post_id": post_id, "action": "apply", "preview_id": preview_id, "confirm": True})
    applied = data.get("data") or {}
    check("apply with confirm → applied", ok and applied.get("applied") is True, applied)
    check("apply created rollback snapshot", applied.get("snapshot_id", 0) > 0, applied)
    code, after = req("/pages/%d?context=edit" % post_id, "GET", None, base=WP_API)
    after_raw = after.get("content", {}).get("raw", "")
    check("applied page has redesigned content", after_raw != orig_raw and len(after_raw) > 50, after_raw[:100])

    # --- E. rollback via snapshot restore ---
    code, data = req("/snapshots/%d/restore" % applied.get("snapshot_id", 0), "POST", {})
    check("snapshot restore (rollback) works", code == 200, data)
    code, restored = req("/pages/%d?context=edit" % post_id, "GET", None, base=WP_API)
    restored_raw = restored.get("content", {}).get("raw", "")
    check("rollback restored the original content", "فروشگاه قدیمی ما" in restored_raw and original_html.strip() in restored_raw, restored_raw[:120])

    # --- F. compare (declared screenshot limitation) ---
    ok, data = exec_tool("redesign_page", {"post_id": post_id, "action": "compare"})
    comp = data.get("data") or {}
    shots = comp.get("screenshots") or {}
    check("compare works (structural)", ok and "now" in comp and "history" in comp, comp.keys())
    check("screenshot limitation explicitly declared", shots.get("available") is False and "browser" in shots.get("reason", ""), shots)

    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PHASE 10 UI tests: Website Builder section endpoints (design system,
components, designed pages), Reports summary, extended AI settings fields,
tool permission toggles, and static JS/UI wiring checks.

Browser automation is not available in this environment (php-wasm sandbox);
UI behavior is verified at the REST layer the UI calls plus static checks of
the bundled JS. This limitation is declared in the final report.

Usage: python3 ui_test.py
"""
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("AIWC_TEST_BASE", "http://127.0.0.1:9400")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CREDS_FILE = os.path.join(REPO, "ai-wordpress-copilot", ".test-credentials")
API = BASE + "/wp-json/ai-copilot/v1"
TEST_API = BASE + "/wp-json/aiwc-test/v1"

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
    text = body.decode(errors="replace") if isinstance(body, bytes) else str(text)
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


def main():
    print("== PHASE 10 UI tests against " + BASE + " ==")

    # ---------- A. Website Builder endpoints ----------
    code, data = req("/builder/status")
    check("GET /builder/status", code == 200 and ("gutenberg" in json.dumps(data) or "elementor" in json.dumps(data)), data)

    code, data = req("/builder/design-system")
    check("GET /builder/design-system", code == 200 and isinstance(data.get("system"), dict), data)
    old_primary = ((data.get("system") or {}).get("colors") or {}).get("primary", "#000")

    code, data = req("/builder/design-system", "POST", {"colors": {"primary": "#123456"}, "radius": 10})
    sys_after = data.get("system") or {}
    check("POST /builder/design-system updates tokens",
          code == 200 and ((sys_after.get("colors") or {}).get("primary") == "#123456"), sys_after.get("colors"))
    code, data = req("/builder/design-system", "POST", {"colors": {"primary": old_primary}})
    check("design system restore", code == 200, data.get("error"))

    code, data = req("/builder/components", "POST", {"action": "save", "name": "ui-test-comp", "spec": {"type": "hero", "elements": []}})
    check("POST /builder/components save", code == 200 and data.get("saved") is True, data)
    code, data = req("/builder/components")
    names = [c.get("name") if isinstance(c, dict) else c for c in (data.get("items") or [])]
    check("component listed", "ui-test-comp" in names, names[:8])
    code, data = req("/builder/components", "POST", {"action": "delete", "name": "ui-test-comp"})
    check("POST /builder/components delete", code == 200 and data.get("deleted") is True, data)

    # Designed pages: build one page then it must appear in /builder/pages.
    ok, data = exec_tool("build_page", {
        "title": "UI Test Landing",
        "sections": [
            {"type": "hero", "content": {"heading": "UI Test", "subheading": "builder pages", "cta_text": "Go", "cta_url": "#"}},
            {"type": "features", "content": {"heading": "F", "items": [{"title": "A", "text": "a"}]}},
        ],
        "builder": "gutenberg",
    })
    built = data.get("data") or {}
    check("build_page via exec-tool", ok and built.get("post_id", 0) > 0, data.get("error"))
    code, data = req("/builder/pages")
    titles = [p.get("title") for p in (data.get("items") or [])]
    check("designed page listed in /builder/pages", "UI Test Landing" in titles, titles[:8])
    item = next((p for p in (data.get("items") or []) if p.get("title") == "UI Test Landing"), {})
    check("designed page entry has builder + links", item.get("builder") == "gutenberg" and bool(item.get("url")) and bool(item.get("edit_url")), item)

    # ---------- B. Reports ----------
    code, data = req("/reports/summary")
    need = ["operations", "by_tool", "tokens", "seo", "jobs", "recent_changes", "recent_snapshots"]
    check("GET /reports/summary has all sections", code == 200 and all(k in data for k in need), sorted(data.keys()))
    ops = data.get("operations") or {}
    check("operations counters present", all(k in ops for k in ("total", "success", "failed")) and ops["total"] > 0, ops)
    check("token usage aggregated", isinstance((data.get("tokens") or {}).get("total"), int), data.get("tokens"))
    check("recent changes populated", len(data.get("recent_changes") or []) > 0, len(data.get("recent_changes") or []))

    # ---------- C. Extended settings ----------
    code, data = req("/settings", "POST", {
        "max_retries": 3, "streaming": 0, "stream_timeout": 90,
        "system_prompt": "ui-test prompt", "temperature": 0.5,
    })
    check("POST /settings accepts new fields", code == 200, data)
    code, data = req("/settings")
    check("settings round-trip", data.get("max_retries") == 3 and data.get("streaming") in (0, False)
          and data.get("stream_timeout") == 90 and data.get("system_prompt") == "ui-test prompt"
          and float(data.get("temperature", 0)) == 0.5, {k: data.get(k) for k in ("max_retries", "streaming", "stream_timeout", "system_prompt", "temperature")})
    req("/settings", "POST", {"max_retries": 2, "streaming": 1, "stream_timeout": 120, "system_prompt": ""})

    # ---------- D. Tool permissions toggles ----------
    code, data = req("/tools")
    names = [t.get("name") for t in (data.get("items") or [])]
    target = "site_overview" if "site_overview" in names else (names[0] if names else "")
    code, res = req("/tools/" + target, "POST", {"enabled": False})
    check("tool toggle off", code == 200 and res.get("enabled") is False, res)
    code, data = req("/tools")
    state = next((t.get("enabled") for t in (data.get("items") or []) if t.get("name") == target), None)
    check("tool listed disabled", state is False, state)
    code, res = req("/tools/" + target, "POST", {"enabled": True})
    check("tool toggle back on", code == 200 and res.get("enabled") is True, res)

    # ---------- E. Static UI wiring (no browser runtime available) ----------
    app = open(os.path.join(REPO, "ai-wordpress-copilot", "assets", "js", "app.js")).read()
    chat = open(os.path.join(REPO, "ai-wordpress-copilot", "assets", "js", "chat.js")).read()
    admin = open(os.path.join(REPO, "ai-wordpress-copilot", "includes", "Admin", "class-admin.php")).read()
    check("app.js renders builder route", "function renderBuilder" in app and "builder: renderBuilder" in app, "")
    check("app.js renders reports route", "function renderReports" in app and "reports: renderReports" in app, "")
    check("settings UI exposes retry/streaming/system prompt", all(k in app for k in ("s-retries", "s-streaming", "s-system-prompt")), "")
    check("settings UI has tool permission toggles", "data-tool-toggle" in app, "")
    check("chat UI has stop/rollback/usage/plan", all(k in chat for k in ("aiwc-stop", "data-rollback", "updateUsage", "renderPlanCard")), "")
    check("admin menu registers new pages", "aiwc-builder" in admin and "aiwc-reports" in admin, "")

    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

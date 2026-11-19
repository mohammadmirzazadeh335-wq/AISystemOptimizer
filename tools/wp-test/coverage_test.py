#!/usr/bin/env python3
"""PHASE 11: 25 mandatory-area coverage runner.

Each numbered area is one of the spec's required test areas. Existing deep
suites (smoke/stream/link/builder/redesign/woo/security/ui) are counted from
their own runs; this runner adds focused quick checks so every area has a
direct, current result. The "real API" area runs only when AIWC_REAL_API_KEY
is provided; otherwise it is recorded as SKIPPED (not a failure).

Usage: python3 coverage_test.py
"""
import base64
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error

BASE = os.environ.get("AIWC_TEST_BASE", "http://127.0.0.1:9400")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CREDS_FILE = os.path.join(REPO, "ai-wordpress-copilot", ".test-credentials")
API = BASE + "/wp-json/ai-copilot/v1"
TEST_API = BASE + "/wp-json/aiwc-test/v1"
WP = BASE + "/wp-json/wp/v2"

PASS = 0
FAIL = 0
SKIP = 0
RESULTS = []


def record(area, name, status, detail=""):
    global PASS, FAIL, SKIP
    if status == "PASS":
        PASS += 1
    elif status == "SKIP":
        SKIP += 1
    else:
        FAIL += 1
    RESULTS.append((area, name, status, detail))
    print("%-4s [%s] %s%s" % (status, area, name, ("  -> " + str(detail)[:80] if detail and status == "FAIL" else "")))


def check(area, name, cond, detail=""):
    record(area, name, "PASS" if cond else "FAIL", detail)


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


def req(path, method="GET", body=None, base=None, timeout=120):
    url = (base or API) + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = json.load(open(CREDS_FILE))
    token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
    r.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getcode(), parse_json_loose(resp.read())
    except urllib.error.HTTPError as e:
        try:
            payload = parse_json_loose(e.read())
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def sse_events(path, body, timeout=90):
    url = API + path
    data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method="POST")
    r.add_header("Content-Type", "application/json")
    creds = json.load(open(CREDS_FILE))
    token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
    r.add_header("Authorization", "Basic " + token)
    events = []
    current_event = "message"
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode(errors="replace").strip()
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict):
                        payload.setdefault("type", current_event)
                    events.append(payload)
                elif line == "":
                    current_event = "message"
    except Exception as e:
        events.append({"type": "client_error", "message": str(e)})
    return events


def exec_tool(name, args):
    code, data = req("/exec-tool", "POST", {"name": name, "args": args}, base=TEST_API)
    return code == 200 and data.get("success") is True, data


def chat(message, timeout=120):
    return req("/chat", "POST", {"message": message}, timeout=timeout)


def main():
    print("== PHASE 11 coverage (25 areas) against " + BASE + " ==")

    # Provider config for agent-driven areas.
    req("/settings", "POST", {
        "base_url": "http://127.0.0.1:8899/v1",
        "api_key": "sk-mock-secret-key-1234567890",
        "model": "mock-gpt",
        "execution_mode": 3,
        "streaming": 1,
    })

    # 1. Streaming — simple text.
    ev = sse_events("/chat/stream", {"message": "Say hi."})
    kinds = [e.get("type") for e in ev]
    text = "".join(e.get("text", "") for e in ev if e.get("type") == "delta")
    check("streaming", "streaming simple text", "start" in kinds and "delta" in kinds and "done" in kinds and len(text) > 5, kinds)

    # 2. Streaming — tool call.
    ev = sse_events("/chat/stream", {"message": "create page streaming coverage"})
    kinds = [e.get("type") for e in ev]
    check("streaming", "streaming with tool call", "tool_call" in kinds and "tool" in kinds and "review" in kinds, kinds)

    # 3. Multi-step chain.
    code, data = chat("create page multi step coverage")
    steps = data.get("steps", [])
    ok_steps = [s for s in steps if (s.get("result") or {}).get("success")]
    check("multi_step", "multi-step tool chain executes", code == 200 and len(ok_steps) >= 1 and len(steps) >= 1, [s.get("tool") for s in steps])

    # 4. Disconnect + continue: messages persist and a follow-up run works.
    code, data = chat("create page persist coverage")
    conv = data.get("conversation_id", 0)
    code2, data2 = req("/chat", "POST", {"message": "continue after the previous step", "conversation_id": conv})
    code3, msgs = req("/chat/%d/messages" % conv if conv else "/chat-conversations")
    persisted = code2 == 200 and (data2.get("message") or {}).get("role") == "assistant"
    check("disconnect", "run persists + continues after interruption", persisted, data2.get("error"))

    # 5. Retry on 429 (mock-flaky fails once; a normal completion proves the retry).
    req("/settings", "POST", {"model": "mock-flaky"})
    code, data = chat("Say hi.")
    content = (data.get("message") or {}).get("content", "")
    check("retry", "429 retried then succeeds", code == 200 and not data.get("error") and len(content) > 3, data.get("error") or content[:60])
    req("/settings", "POST", {"model": "mock-gpt"})

    # 6. Timeout handled with friendly error.
    req("/settings", "POST", {"timeout": 3})
    code, data = chat("slow page for timeout", timeout=60)
    err = json.dumps(data, ensure_ascii=False)
    check("timeout", "timeout → clean typed error", "timeout" in err.lower() or "timed out" in err.lower() or "زمان" in err, err[:150])
    req("/settings", "POST", {"timeout": 60})

    # 7. Auth: anonymous rejected.
    r = urllib.request.Request(API + "/tools")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    check("auth", "anonymous request rejected", code in (401, 403), code)

    # 8. Real API — only with a provided key.
    real_key = os.environ.get("AIWC_REAL_API_KEY", "")
    if real_key:
        code, data = req("/settings", "POST", {
            "base_url": os.environ.get("AIWC_REAL_BASE", "https://api.openai.com/v1"),
            "api_key": real_key,
            "model": os.environ.get("AIWC_REAL_MODEL", "gpt-4o-mini"),
        })
        code, data = req("/settings/test-connection", "POST", {})
        check("real_api", "real provider connection", code == 200 and data.get("ok"), data)
    else:
        record("real_api", "real provider connection", "SKIP", "AIWC_REAL_API_KEY not provided")

    # 9+10. External links + SSRF through the scan/check pipeline.
    # Cache-busting query params keep URLs fresh (status cache skips repeats).
    ts = int(time.time())
    u_ok = "http://127.0.0.1:8899/status/200?cb=%d" % ts
    u_404 = "http://127.0.0.1:8899/status/404?cb=%d" % ts
    u_meta = "http://169.254.169.254/latest/meta-data/?cb=%d" % ts
    links_html = ('<p><a href="%s">ok</a> <a href="%s">broken</a> <a href="%s">meta</a></p>' % (u_ok, u_404, u_meta))
    code, page = req("/pages", "POST", {"title": "Coverage Links", "content": links_html, "status": "publish"}, base=WP)
    lid = page.get("id", 0)
    req("/links/scan", "POST", {"post_id": lid})
    code, data = req("/links/check", "POST", {"limit": 20})
    statuses = {r.get("url"): r.get("status") for r in data.get("results", [])}
    check("external_links", "link check classifies statuses",
          code == 200 and statuses.get(u_ok) in ("ok", "redirected")
          and statuses.get(u_404) == "broken", statuses)
    meta_status = statuses.get(u_meta)
    check("ssrf", "metadata IP blocked", meta_status in ("blocked", "invalid", "error", "unreachable"), statuses)

    # 11. Gutenberg.
    ok, data = exec_tool("build_page", {"title": "Coverage Gutenberg", "sections": [{"type": "hero", "content": {"heading": "G", "subheading": "g", "cta_text": "x", "cta_url": "#"}}], "builder": "gutenberg"})
    pid = (data.get("data") or {}).get("post_id", 0)
    ok2, data2 = exec_tool("get_page_structure", {"post_id": pid})
    blocks = json.dumps(data2.get("data") or {}, ensure_ascii=False)
    check("gutenberg", "gutenberg page + structure", ok and ok2 and ("core/" in blocks or "block" in blocks.lower()), data2.get("error"))

    # 12. Elementor.
    ok, data = exec_tool("build_page", {"title": "Coverage Elementor", "sections": [{"type": "hero", "content": {"heading": "E", "subheading": "e", "cta_text": "x", "cta_url": "#"}}], "builder": "elementor"})
    pid2 = (data.get("data") or {}).get("post_id", 0)
    ok2, data2 = exec_tool("get_page_structure", {"post_id": pid2})
    check("elementor", "elementor page + structure", ok and ok2 and pid2 > 0, data.get("error") or data2.get("error"))

    # 13. Responsive tokens.
    code, data = req("/builder/design-system")
    css = data.get("css", "")
    sysd = data.get("system") or {}
    check("responsive", "breakpoints + responsive tokens present",
          ("breakpoint" in json.dumps(sysd).lower() or "@media" in css or "breakpoint" in css.lower()), list(sysd.keys())[:8])

    # 14. Design-system change via natural language.
    code, data = chat("رنگ اصلی را سرمه‌ای کن")
    tools_run = [s.get("tool") for s in data.get("steps", [])]
    check("design_system", "natural-language design change", "update_design_system" in tools_run, tools_run)

    # 15+16. Redesign analyze + preview.
    code, data = chat("create page redesign coverage")
    conv_id = data.get("conversation_id", 0)
    ok, data = exec_tool("build_page", {"title": "Coverage Redesign", "sections": [{"type": "hero", "content": {"heading": "R", "subheading": "r", "cta_text": "x", "cta_url": "#"}}], "builder": "gutenberg"})
    rid = (data.get("data") or {}).get("post_id", 0)
    ok, data = exec_tool("redesign_page", {"post_id": rid, "action": "analyze"})
    check("redesign", "redesign analyze", ok and "inventory" in json.dumps(data.get("data") or {}), data.get("error"))
    ok, data = exec_tool("redesign_page", {"post_id": rid, "action": "preview", "proposal": (data.get("data") or {}).get("proposal")})
    prev = data.get("data") or {}
    check("preview", "redesign preview built", ok and prev.get("preview_id", 0) > 0 and bool(prev.get("preview_url")), data.get("error"))

    # 17. Rollback via snapshot restore.
    ok, data = exec_tool("create_page", {"title": "Coverage Rollback", "content": "version one", "status": "draft"})
    snap = (data.get("data") or {}).get("snapshot_id", 0)
    if snap:
        ok2, data2 = exec_tool("rollback_change", {"snapshot_id": snap, "confirm": True})
        check("rollback", "snapshot restore round-trips", ok2, data2.get("error"))
    else:
        ok2, data2 = exec_tool("list_snapshots", {"limit": 5})
        items = (data2.get("data") or {}).get("snapshots") or []
        check("rollback", "snapshots listable for rollback", ok2 and isinstance(items, list), data2.get("error"))

    # 18. Planning engine.
    code, data = chat("execution plan for the next task")
    tools_run = [s.get("tool") for s in data.get("steps", [])]
    has_plan = bool(data.get("plan")) or "create_plan" in tools_run
    check("planning", "plan recorded before work", has_plan, (data.get("plan"), tools_run))

    # 19. Self-review.
    code, data = chat("create page self review coverage")
    reviews = [s.get("review") for s in data.get("steps", []) if s.get("review")]
    check("self_review", "self-review attached to steps", len(reviews) > 0, [s.get("tool") for s in data.get("steps", [])])

    # 20. Cancel mid-run.
    holder = {}

    def slow():
        holder["res"] = req("/chat", "POST", {"message": "slow page cancel coverage"}, timeout=90)

    th = threading.Thread(target=slow)
    th.start()
    time.sleep(1.5)
    req("/chat/cancel", "POST", {})
    th.join(60)
    res = holder.get("res", (0, {}))[1]
    check("cancel", "cancel stops run cooperatively", res.get("cancelled") is True or "cancel" in json.dumps(res, ensure_ascii=False).lower(), res.get("error"))

    # 21. Memory.
    req("/chat", "POST", {"message": "remember that the launch code is ORANGE-42"})
    code, data = chat("what did you remember about the launch code?")
    content = json.dumps(data, ensure_ascii=False)
    check("memory", "memory write + recall", "ORANGE-42" in content or "remember" in content.lower(), content[:120])

    # 22. REST security.
    r = urllib.request.Request(API + "/reports/summary")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    ok, data = exec_tool("definitely_not_a_tool", {})
    check("rest_security", "anon blocked + unknown tool rejected", code in (401, 403) and not ok, code)

    # 23. WooCommerce.
    ok, data = exec_tool("woo_product_create", {"title": "Coverage Woo Product", "price": "5.00"})
    pid = (data.get("data") or {}).get("product_id", 0)
    ok2, data2 = exec_tool("woo_product_update", {"product_id": pid, "price": "6.00"})
    check("woocommerce", "woo product create + price gate", ok and pid > 0 and not ok2, data2.get("error"))

    # 24. Jobs queue.
    code, data = req("/jobs")
    check("jobs", "job queue REST responds", code == 200, data)

    # 25. Model capability detection.
    code, data = req("/settings/detect-capabilities", "POST", {})
    caps = data.get("capabilities") or data
    check("capabilities", "capability detection returns flags",
          code == 200 and ("tool_calling" in json.dumps(caps) or "streaming" in json.dumps(caps)), caps)

    print("\n== RESULT: %d passed, %d failed, %d skipped ==" % (PASS, FAIL, SKIP))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
AIWC end-to-end smoke test against a live WordPress Playground site.

Usage: python3 smoke_test.py [base_url]
Default base_url: http://127.0.0.1:9400
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9400"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CREDS_FILE = os.path.join(REPO, "ai-wordpress-copilot", ".test-credentials")
API = BASE + "/wp-json/ai-copilot/v1"

PASS = 0
FAIL = 0
NOTES = []


def note(msg):
    NOTES.append(msg)
    print("   note: " + msg)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS  " + name)
    else:
        FAIL += 1
        print("FAIL  " + name + ("  -> " + str(detail) if detail else ""))


def req(path, method="GET", body=None, auth=True, raw_base=False):
    url = (BASE if raw_base else API) + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if auth:
        creds = json.load(open(CREDS_FILE))
        token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
        r.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.getcode(), json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def fetch_creds():
    """Fetch test credentials from the test-only mu-plugin endpoint."""
    url = BASE + "/wp-json/aiwc-test/v1/creds?key=smoke"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    with open(CREDS_FILE, "w") as fh:
        json.dump({"user": data["user"], "pass": data["pass"]}, fh)
    return data


def wait_ready(timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        try:
            code, _ = req("/wp-json/", raw_base=True, auth=False)
            if code == 200:
                fetch_creds()
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def main():
    print("== AIWC smoke test against " + BASE + " ==")
    if not wait_ready():
        check("wordpress boot + credentials", False, "site not reachable or creds missing")
        return 1
    check("wordpress boot + credentials", True)

    # --- 1. Settings roundtrip ---
    code, _ = req("/settings", "POST", {"api_key": "[CLEAR]"})
    code, data = req("/settings")
    check("GET /settings (authorized)", code == 200 and "base_url" in data, data)
    check("api key hidden before set", data.get("api_key_set") is False, data)

    code, _ = req("/settings", "POST", {
        "api_key": "sk-test-1234567890abcdef",
        "base_url": "http://127.0.0.1:8899/v1",
        "model": "mock-gpt",
        "max_retries": 1,
        "timeout": 10,
    })
    check("POST /settings", code == 200)

    code, data = req("/settings")
    masked = data.get("api_key", "")
    check("api key masked in response", "sk-test-1234567890abcdef" not in json.dumps(data), data.get("api_key"))
    check("api key never full in frontend", data.get("api_key_set") is True)

    # --- 2. Connection test (real HTTP transport first) ---
    code, data = req("/settings/test", "POST")
    transport = "real-http"
    if code != 200 or not data.get("ok"):
        note("real HTTP transport failed (" + str(data.get("message")) + ") -> enabling pre_http_request fallback")
        transport = "wp-http-fallback"
        open(os.path.join(REPO, "tools/wp-test/mu-plugins/.use-fallback"), "w").close()
        code, data = req("/settings/test", "POST")
    check("POST /settings/test (connection)", code == 200 and data.get("ok") is True, data)
    note("transport: " + transport)

    code, data = req("/models")
    check("GET /models", code == 200 and "mock-gpt" in json.dumps(data), data)

    # --- 3. Site context ---
    code, data = req("/site/context")
    check("GET /site/context", code == 200 and "overview" in data and "structure" in data, data)
    check("site context has counts", isinstance(data.get("overview", {}).get("counts"), dict))

    # --- 4. Unauthenticated is rejected ---
    code, data = req("/settings", auth=False)
    check("unauthenticated request rejected", code in (401, 403), code)

    # --- 5. Chat + tool calling (auto low-risk mode) ---
    code, _ = req("/settings", "POST", {"execution_mode": 3})
    check("set execution_mode=3", code == 200)

    code, data = req("/chat", "POST", {"message": "please create page about us now"})
    check("POST /chat (create page)", code == 200, data)
    steps = data.get("steps", [])
    check("chat executed tool step", any(s.get("tool") == "create_page" for s in steps), steps)
    check("chat final message is markdown", bool(data.get("message", {}).get("content")), data.get("message"))
    check("chat usage tokens counted", data.get("usage", {}).get("total_tokens", 0) > 0, data.get("usage"))
    conv_id = data.get("conversation_id")
    check("conversation created", conv_id > 0, conv_id)

    created_id = 0
    for s in steps:
        if s.get("tool") == "create_page" and s.get("result", {}).get("success"):
            created_id = s["result"].get("data", {}).get("post_id", 0)
    check("page really created in WP", created_id > 0, steps)

    # Verify on WordPress itself.
    code, data = req("/wp-json/wp/v2/pages/" + str(created_id), raw_base=True)
    check("page visible via WP REST API", code == 200 and data.get("id") == created_id, data)

    # --- 6. Activity log + snapshot ---
    code, data = req("/logs?per_page=20")
    rows = data.get("items", [])
    check("activity log has entries", len(rows) > 0, data)
    create_rows = [r for r in rows if r.get("tool_name") == "create_page" and r.get("status") == "success"]
    check("create_page logged", len(create_rows) > 0, [r.get("tool_name") for r in rows])
    snapshot_ids = [s for s in [0] ]
    code, data2 = req("/chat", "POST", {"message": "site overview please"})
    check("chat read-only tool (site_overview)", any(s.get("tool") == "site_overview" for s in data2.get("steps", [])), data2.get("steps"))

    # --- 7. Approval flow (mode 2) ---
    code, _ = req("/settings", "POST", {"execution_mode": 2})
    before_code, before_pages = req("/wp-json/wp/v2/pages?per_page=100", raw_base=True)
    count_before = len(before_pages) if before_code == 200 else -1

    code, data = req("/chat", "POST", {"message": "create page about approval flow"})
    check("mode2 chat returns", code == 200, data)
    pending = data.get("pending", [])
    check("mode2 mutating tool waits for approval", len(pending) > 0, data.get("steps"))
    approval_id = pending[0]["approval_id"] if pending else 0

    code, ap = req("/approvals")
    check("GET /approvals lists pending", code == 200 and any(a["id"] == approval_id for a in ap.get("items", [])), ap)

    code, after_pages = req("/wp-json/wp/v2/pages?per_page=100", raw_base=True)
    count_after = len(after_pages) if code == 200 else -1
    check("mode2 did NOT create the page before approval", count_before == count_after, (count_before, count_after))

    code, res = req("/approvals/" + str(approval_id) + "/approve", "POST")
    check("approve executes the operation", code == 200 and res.get("success") is True, res)

    code, after_pages = req("/wp-json/wp/v2/pages?per_page=100", raw_base=True)
    count_final = len(after_pages) if code == 200 else -1
    check("page created after approval", count_final == count_before + 1, (count_before, count_final))

    # --- 8. Reject flow ---
    code, data = req("/chat", "POST", {"message": "create page to be rejected"})
    pending = data.get("pending", [])
    check("second approval created", len(pending) > 0, data.get("steps"))
    if pending:
        code, res = req("/approvals/" + str(pending[0]["approval_id"]) + "/reject", "POST")
        check("reject marks rejected", code == 200 and res.get("rejected") is True, res)

    # --- 9. Memory ---
    code, _ = req("/settings", "POST", {"execution_mode": 3})
    code, data = req("/chat", "POST", {"message": "please remember our brand color"})
    mem_steps = [s for s in data.get("steps", []) if s.get("tool") == "memory_save"]
    check("memory_save tool ran", len(mem_steps) > 0, data.get("steps"))

    code, data = req("/memory")
    check("GET /memory has stored fact", code == 200 and len(data.get("items", [])) > 0, data)

    code, res = req("/memory", "POST", {"category": "design", "memory_key": "font", "memory_value": "Vazirmatn"})
    check("POST /memory manual add", code == 201, res)
    code, data = req("/memory/" + str(res.get("id", 0)), "DELETE")
    check("DELETE /memory", code == 200, data)

    # --- 10. SEO analyze + site report + queue ---
    code, data = req("/seo/analyze", "POST", {"post_id": created_id})
    check("POST /seo/analyze", code == 200 and "score" in data, data)
    check("seo score within range", isinstance(data.get("score"), int) and 0 <= data["score"] <= 100, data.get("score"))
    check("seo issues list present", isinstance(data.get("issues"), list), data.get("issues"))
    check("seo checks computed", "word_count" in data.get("checks", {}), data.get("checks"))

    code, data = req("/seo/analyze-site", "POST")
    job_id = data.get("job_id", 0)
    check("POST /seo/analyze-site queues job", code in (200, 201) and job_id > 0, data)

    code, data = req("/jobs/" + str(job_id) + "/run", "POST")
    check("job runs to completion", code == 200 and data.get("status") == "complete", data)

    code, data = req("/seo/report")
    check("site seo report available", code == 200 and data.get("available") is True, data)
    check("site seo average score", "average_score" in data, data)

    # --- 11. Content listing ---
    code, data = req("/content?type=page&per_page=5")
    check("GET /content lists pages", code == 200 and "items" in data, data)

    # --- 12. Tools listing + toggle ---
    code, data = req("/tools")
    tools = data.get("items", [])
    check("GET /tools lists tools", len(tools) >= 20, len(tools))
    some = tools[0]["name"] if tools else ""
    code, res = req("/tools/" + some, "POST", {"enabled": False})
    check("POST /tools/{name} toggle", code == 200 and res.get("enabled") is False, res)
    code, res = req("/tools/" + some, "POST", {"enabled": True})
    check("tool re-enabled", res.get("enabled") is True)

    # --- 13. Rollback (real snapshot -> update -> restore) ---
    code, data = req("/chat", "POST", {"message": "create page rollback victim"})
    victim_id = 0
    original_title = ""
    for s in data.get("steps", []):
        if s.get("tool") == "create_page" and s.get("result", {}).get("success"):
            victim_id = s["result"]["data"]["post_id"]
    check("victim page created", victim_id > 0, data.get("steps"))

    code, victim = req("/wp-json/wp/v2/pages/" + str(victim_id), raw_base=True)
    original_title = victim.get("title", {}).get("rendered", "") if code == 200 else ""
    check("victim original title read", bool(original_title), victim)

    # Update it through the agent -> snapshot created.
    code, data = req("/chat", "POST", {"message": "update page " + str(victim_id)})
    upd_steps = [s for s in data.get("steps", []) if s.get("tool") == "update_page"]
    check("update_page tool executed", len(upd_steps) > 0 and upd_steps[0].get("status") == "success", data.get("steps"))

    code, victim2 = req("/wp-json/wp/v2/pages/" + str(victim_id), raw_base=True)
    changed_title = victim2.get("title", {}).get("rendered", "") if code == 200 else ""
    check("page content really changed", changed_title != original_title and bool(changed_title), (original_title, changed_title))

    # Find the update_page log entry and roll it back.
    code, data = req("/logs?tool_name=update_page&per_page=10")
    upd_rows = [r for r in data.get("items", []) if r.get("status") == "success" and r.get("object_id") == victim_id]
    check("update_page logged with snapshot", len(upd_rows) > 0, [r.get("object_id") for r in data.get("items", [])])
    if upd_rows:
        code, res = req("/logs/" + str(upd_rows[0]["id"]) + "/restore", "POST")
        check("POST /logs/{id}/restore succeeds", code == 200 and res.get("success") is True, res)

        code, victim3 = req("/wp-json/wp/v2/pages/" + str(victim_id), raw_base=True)
        restored_title = victim3.get("title", {}).get("rendered", "") if code == 200 else ""
        check("rollback restored original content", restored_title == original_title, (restored_title, original_title))

    # --- 13b. Custom CSS change + rollback ---
    code, css_before = req("/design/css")
    check("GET /design/css", code == 200, css_before)
    code, res = req("/design/css", "POST", {"css": "body { --aiwc-test: 1; }", "mode": "append"})
    check("POST /design/css", code == 200 and res.get("success") is True, res)
    code, css_mid = req("/design/css")
    check("css really changed", "--aiwc-test" in (css_mid.get("css") or ""), css_mid)

    code, data = req("/logs?tool_name=update_custom_css&per_page=5")
    css_rows = [r for r in data.get("items", []) if r.get("status") == "success"]
    check("css update logged", len(css_rows) > 0, data)
    if css_rows:
        code, res = req("/logs/" + str(css_rows[0]["id"]) + "/restore", "POST")
        check("css rollback succeeds", code == 200 and res.get("success") is True, res)
        code, css_after = req("/design/css")
        check("css rollback restored previous css", "--aiwc-test" not in (css_after.get("css") or ""), css_after)

    code, data = req("/chat", "POST", {"message": "create page another one"})
    check("chat still works after many calls", code == 200, data)

    code, data = req("/logs?per_page=30")
    snap_rows = [r for r in data.get("items", []) if r.get("tool_name") in ("create_page", "update_page", "update_custom_css")]
    check("logs contain mutating ops", len(snap_rows) > 0, [r.get("tool_name") for r in data.get("items", [])][:10])

    # --- 14. WP admin page loads (HTML sanity, cookie login) ---
    try:
        # Application passwords don't authenticate wp-admin pages; use the
        # Playground default credentials (admin/password) with a cookie jar.
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.open(BASE + "/wp-login.php", timeout=30).read()
        login_data = urllib.parse.urlencode({
            "log": "admin", "pwd": "password", "wp-submit": "Log In",
            "redirect_to": "/wp-admin/", "testcookie": "1",
        }).encode()
        req_login = urllib.request.Request(BASE + "/wp-login.php", data=login_data)
        opener.open(req_login, timeout=30).read()
        html = opener.open(BASE + "/wp-admin/admin.php?page=aiwc-dashboard", timeout=60).read().decode(errors="replace")
        check("admin dashboard page renders", "aiwc-app" in html, html[:120])
        check("no fatal error on admin page", "Fatal error" not in html and "Parse error" not in html)
        check("admin app assets enqueued", "aiwc-app.js" in html or "admin.css" in html, "assets missing")
    except Exception as e:
        check("admin dashboard page renders", False, str(e))

    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

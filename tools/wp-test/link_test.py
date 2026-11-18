#!/usr/bin/env python3
"""Focused tests for PHASE 4: SSRF protection + external link checker.

Covers: Url_Guard scheme/IP/userinfo/resolution blocking (localhost, private
ranges, cloud metadata), allowlist + trust_dns filters, link extraction with
anchors and source page, scan/check/report flow, broken/redirected/timeout/
blocked statuses, redirect-to-metadata SSRF defense, caching, cancel, resume,
and SEO analyzer integration.

Usage: python3 link_test.py
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


def guard(url, trust_dns=None, allow=None):
    qs = "?url=" + urllib.parse.quote(url, safe="")
    if trust_dns is not None:
        qs += "&trust_dns=" + ("1" if trust_dns else "0")
    if allow is not None:
        qs += "&allow=" + urllib.parse.quote(",".join(allow), safe=",")
    code, data = req("/url-guard" + qs, base=TEST_API)
    return code == 200 and data.get("ok") is True, data.get("code", "")


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
    import urllib.parse  # noqa: F401  (used in guard())

    print("== PHASE 4 SSRF/link-checker tests against " + BASE + " ==")
    if not wait_ready():
        check("wordpress boot + credentials", False, "site not reachable")
        return 1
    check("wordpress boot + credentials", True)

    # --- A. SSRF guard: schemes ---
    ok, code = guard("file:///etc/passwd", trust_dns=False)
    check("block file:// scheme", not ok and code == "aiwc_url_scheme_blocked", code)
    ok, code = guard("ftp://example.com/x", trust_dns=False)
    check("block ftp:// scheme", not ok and code == "aiwc_url_scheme_blocked", code)
    ok, code = guard("gopher://example.com/", trust_dns=False)
    check("block gopher:// scheme", not ok and code == "aiwc_url_scheme_blocked", code)
    ok, code = guard("dict://127.0.0.1:8899/", trust_dns=False)
    check("block dict:// scheme", not ok, code)

    # --- B. SSRF guard: IP literals + userinfo ---
    ok, code = guard("http://127.0.0.1/", trust_dns=False)
    check("block loopback 127.0.0.1", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://169.254.169.254/latest/meta-data/", trust_dns=False)
    check("block cloud metadata 169.254.169.254", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://10.0.0.5/", trust_dns=False)
    check("block RFC1918 10.x", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://172.16.0.1/", trust_dns=False)
    check("block RFC1918 172.16.x", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://192.168.1.1/", trust_dns=False)
    check("block RFC1918 192.168.x", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://[::1]/", trust_dns=False)
    check("block IPv6 loopback [::1]", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("http://0.0.0.0/", trust_dns=False)
    check("block 0.0.0.0", not ok, code)
    ok, code = guard("http://user:pass@example.com/", trust_dns=False)
    check("block userinfo credentials", not ok and code == "aiwc_url_userinfo_blocked", code)
    ok, code = guard("http://100.64.0.1/", trust_dns=False)
    check("block CGNAT 100.64.x", not ok, code)

    # --- C. SSRF guard: hostname resolution + allowlist + trust_dns ---
    ok, code = guard("https://example.com/page", trust_dns=False)
    check("strict mode blocks proxy-resolved host", not ok and code == "aiwc_url_private_ip", code)
    ok, code = guard("https://example.com/page", trust_dns=True)
    check("trust_dns allows hostname", ok, code)
    ok, code = guard("http://127.0.0.1:8899/status/200", trust_dns=False, allow=["127.0.0.1"])
    check("allowlist unblocks specific host", ok, code)

    # --- D. Link checker: build a page with external links ---
    links_html = """
    <p>لینک‌های تستی:</p>
    <ul>
      <li><a href="http://127.0.0.1:8899/status/200">سالم</a></li>
      <li><a href="http://127.0.0.1:8899/status/404">خراب</a></li>
      <li><a href="http://127.0.0.1:8899/status/301">ریدایرکت</a></li>
      <li><a href="http://127.0.0.1:8899/status/302-evil">ریدایرکت شیطانی</a></li>
      <li><a href="http://127.0.0.1:8899/status/timeout">کند</a></li>
      <li><a href="http://127.0.0.1:8899/status/200">تکراری</a></li>
    </ul>
    """
    code, page = req("/pages", "POST", {
        "title": "صفحه تست لینک‌ها",
        "content": links_html,
        "status": "publish",
    }, base=WP_API)
    post_id = page.get("id", 0)
    check("create page with external links", code in (200, 201) and post_id > 0, (code, page))

    code, data = req("/links/scan", "POST", {"post_id": post_id})
    check(
        "links/scan extracts links (deduped per source)",
        code == 200 and data.get("new", 0) >= 5 and data.get("total", 0) >= 5,
        data,
    )

    # --- E. Check batch (includes an 8s timeout case) ---
    code, data = req("/links/check", "POST", {"limit": 20})
    statuses = {r["url"]: r["status"] for r in data.get("results", [])}
    check("links/check runs a batch", code == 200 and data.get("checked", 0) >= 5, data)
    check("healthy link → ok", statuses.get("http://127.0.0.1:8899/status/200") in ("ok", "redirected"), statuses)
    check("404 link → broken", statuses.get("http://127.0.0.1:8899/status/404") == "broken", statuses)
    check(
        "301 link → redirected with final URL",
        statuses.get("http://127.0.0.1:8899/status/301") == "redirected",
        statuses,
    )
    check(
        "redirect-to-metadata → blocked (SSRF defense)",
        statuses.get("http://127.0.0.1:8899/status/302-evil") == "blocked",
        statuses,
    )
    check("slow link → timeout", statuses.get("http://127.0.0.1:8899/status/timeout") == "timeout", statuses)

    # --- F. Report with suggestions ---
    code, data = req("/links/report")
    groups = data.get("groups", {})
    broken_items = groups.get("broken", [])
    check("report groups broken links", code == 200 and any("status/404" in i["url"] for i in broken_items), data.get("counts"))
    check(
        "report carries fix suggestions + source page",
        any(i.get("suggestion") for i in broken_items) and any(i.get("source_post_id") == post_id for i in broken_items),
        broken_items[:1],
    )
    check("report has redirected group", any("status/301" in i["url"] for i in groups.get("redirected", [])), groups.keys())
    check("report has blocked group with SSRF suggestion", any("302-evil" in i["url"] and "SSRF" in i.get("suggestion", "") for i in groups.get("blocked", [])), groups.get("blocked", []))
    check("anchors extracted", any("خراب" in i.get("anchor", "") for i in broken_items), broken_items[:2])

    # --- G. Caching: fresh results are not re-checked ---
    code, data = req("/links/check", "POST", {"limit": 20})
    check("cached links skipped on re-check", code == 200 and data.get("checked", 0) == 0, data)

    # --- H. Cancel + resume ---
    # Enqueue one more link first so the next batch has work to abort.
    code, page2 = req("/pages", "POST", {
        "title": "صفحه تست لینک ۲",
        "content": '<a href="http://127.0.0.1:8899/status/500">خطای سرور</a>',
        "status": "publish",
    }, base=WP_API)
    req("/links/scan", "POST", {"post_id": page2.get("id", 0)})
    code, _ = req("/links/cancel", "POST", {})
    code2, data = req("/links/check", "POST", {"limit": 5})
    check("links/cancel aborts a batch (flag consumed)", code == 200 and code2 == 200 and data.get("cancelled") is True, data)

    # Resume: the aborted item is still pending; the next batch completes it.
    code, data = req("/links/check", "POST", {"limit": 5})
    check("resume: aborted link checked on next batch", code == 200 and data.get("checked", 0) == 1 and data.get("remaining", 0) == 0, data)

    # --- I. SEO analyzer integration ---
    code, data = req("/seo/analyze", "POST", {"post_id": post_id})
    analysis = data.get("analysis", data)
    links_check = (analysis.get("checks") or {}).get("links") or {}
    ext_status = links_check.get("external_status") or {}
    check(
        "SEO analyzer reports external link statuses",
        code == 200 and ext_status and ext_status.get("http://127.0.0.1:8899/status/404") == "broken",
        links_check,
    )
    issues = analysis.get("issues") or []
    check(
        "SEO analyzer flags broken external links",
        any(i.get("code") == "broken_external_links" for i in issues),
        [i.get("code") for i in issues],
    )

    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

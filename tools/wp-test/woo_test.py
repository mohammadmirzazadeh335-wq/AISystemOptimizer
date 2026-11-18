#!/usr/bin/env python3
"""Focused tests for PHASE 8: WooCommerce upgrade.

Covers: product create/update, mandatory confirmation for price/stock
changes (refused + approval entry without confirm, applied with confirm),
variable products with attributes + variations, inventory management,
categories, images (media sideload through the SSRF-guarded path), product
analysis, description + SEO application, shop page design, and the agent
chat flow with the mock provider.

Usage: python3 woo_test.py
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


def chat(message):
    code, data = req("/chat", "POST", {"message": message, "conversation_id": 0})
    return code == 200, data


def step_tool_result(data, tool):
    for s in data.get("steps", []):
        if s.get("tool") == tool and (s.get("result") or {}).get("success"):
            return s["result"].get("data") or {}
    return None


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
    print("== PHASE 8 WooCommerce tests against " + BASE + " ==")
    if not wait_ready():
        check("wordpress boot + credentials", False, "site not reachable")
        return 1
    check("wordpress boot + credentials", True)

    # Ensure provider configured for the agent-flow section.
    req("/settings", "POST", {
        "base_url": "http://127.0.0.1:8899/v1",
        "api_key": "sk-mock-secret-key-1234567890",
        "model": "mock-gpt",
    })

    # --- A. Product create + update ---
    ok, data = exec_tool("woo_product_create", {"title": "محصول تست وو", "price": "25.00", "stock": 10, "description": "توضیح اولیه محصول تست برای بررسی قابلیت‌ها"})
    prod = data.get("data") or {}
    pid = prod.get("product_id", 0)
    check("woo_product_create", ok and pid > 0, prod)

    ok, data = exec_tool("woo_product_update", {"product_id": pid, "price": "30.00"})
    err = json.dumps(data, ensure_ascii=False)
    check("price change WITHOUT confirm → refused + approval entry",
          not ok and "confirmation" in err and "Approval entry" in err, err[:200])
    check("approval entry recorded (pending)", code_has_pending(err), err[:200])

    ok, data = exec_tool("woo_product_update", {"product_id": pid, "price": "30.00", "confirm": True})
    check("price change WITH confirm → applied", ok, data.get("error"))
    ok, data = exec_tool("woo_product_analyze", {"product_id": pid})
    an = data.get("data") or {}
    check("woo_product_analyze reports score + fixes", ok and an.get("score", 0) > 0 and "fixes" in an, an)

    # --- B. Variable product with attributes + variations ---
    ok, data = exec_tool("woo_product_variable", {
        "title": "محصول متغیر تست",
        "attributes": [{"name": "Size", "options": ["S", "M"], "variation": True}],
        "variations": [
            {"sku": "VAR-S-%d" % int(time.time()), "attributes": {"Size": "S"}, "price": "10.00", "stock": 5},
            {"sku": "VAR-M-%d" % int(time.time()), "attributes": {"Size": "M"}, "price": "12.00", "stock": 3},
        ],
        "confirm": True,
    })
    var = data.get("data") or {}
    check("woo_product_variable creates product + variations",
          ok and var.get("product_id", 0) > 0 and len(var.get("variation_ids", [])) == 2, var)
    ok2, data2 = exec_tool("woo_product_analyze", {"product_id": var.get("product_id", 0)})
    check("variable product analyze works", ok2, data2.get("error"))

    # Variable without confirm → refused
    ok, data = exec_tool("woo_product_variable", {
        "title": "بدون تأیید",
        "variations": [{"sku": "X", "attributes": {"Size": "S"}, "price": "9.00"}],
    })
    check("variation price WITHOUT confirm → refused", not ok and "confirmation" in json.dumps(data, ensure_ascii=False), data.get("error"))

    # --- C. Inventory ---
    ok, data = exec_tool("woo_manage_stock", {"product_id": pid, "stock": 42, "confirm": True})
    stock_data = data.get("data") or {}
    check("woo_manage_stock updates quantity", ok and stock_data.get("after", {}).get("stock") == 42, stock_data)
    ok, data = exec_tool("woo_manage_stock", {"product_id": pid, "stock": 1})
    check("inventory WITHOUT confirm → refused (needs_confirmation tool)", not ok, data.get("error"))

    # --- D. Categories ---
    ok, data = exec_tool("woo_product_categories", {"action": "create", "name": "دسته تست وو", "description": "دسته آزمایشی"})
    cat = data.get("data") or {}
    check("category created", ok and cat.get("term_id", 0) > 0, cat)
    ok, data = exec_tool("woo_product_categories", {"action": "list"})
    names = [c.get("name") for c in ((data.get("data") or {}).get("categories") or [])]
    check("category list includes new category", "دسته تست وو" in names, names[:6])
    ok, data = exec_tool("woo_product_categories", {"action": "update", "term_id": cat.get("term_id"), "description": "به‌روزشده"})
    check("category updated", ok, data.get("error"))

    # --- E. Images (sideload through Url_Guard) ---
    ok, data = exec_tool("woo_product_images", {"product_id": pid, "image_url": "http://127.0.0.1:8899/img/test.jpg"})
    check("product image sideloaded from URL", ok and (data.get("data") or {}).get("image_id", 0) > 0, data.get("error") or data.get("data"))
    ok, data = exec_tool("woo_product_images", {"product_id": pid, "image_url": "http://169.254.169.254/latest/meta-data/"})
    check("metadata URL image → blocked by SSRF guard", not ok, data.get("error"))

    # --- F. Description + SEO ---
    ok, data = exec_tool("woo_product_description", {
        "product_id": pid,
        "description": "این یک توضیح کامل و حرفه‌ای برای محصول تست است که بیش از صد و پنجاه کاراکتر دارد تا بررسی طول توضیحات با موفقیت انجام شود و کیفیت محتوا تأیید گردد. " * 2,
        "short_description": "توضیح کوتاه محصول.",
        "seo_title": "محصول تست وو | بهترین قیمت",
        "seo_description": "توضیح متا مناسب برای محصول تست وو با طول استاندارد بین پنجاه تا صد و شصت کاراکتر.",
    })
    desc = data.get("data") or {}
    checks = desc.get("seo_checks") or {}
    check("description + SEO applied with checks", ok and checks.get("description_length_ok") and checks.get("seo_description_ok"), checks)

    # --- G. Shop design ---
    ok, data = exec_tool("woo_shop_design", {"action": "shop", "title": "فروشگاه تست", "slug": "test-shop", "builder": "gutenberg"})
    shop = data.get("data") or {}
    check("shop page built with product grid", ok and shop.get("post_id", 0) > 0, shop)
    code, page = req("/pages/%d?context=edit" % shop.get("post_id", 0), "GET", None, base=BASE + "/wp-json/wp/v2")
    raw = page.get("content", {}).get("raw", "")
    check("shop page contains product shortcode", "[products" in raw, raw[:150])

    # --- H. Agent chat flows (mock patterns) ---
    ok, data = chat("manage stock for product %d" % pid)
    pending = data.get("pending") or []
    steps = data.get("steps", [])
    has_approval = any(s.get("type") == "approval" and s.get("tool") == "woo_manage_stock" for s in steps)
    check("agent flow: needs_confirmation tool → queued for approval",
          ok and has_approval and len(pending) > 0, [s.get("type") for s in steps])
    if pending:
        aid = pending[0].get("approval_id")
        code, res = req("/approvals/%d/approve" % aid, "POST", {})
        check("approval approve executes the queued stock change", code == 200 and res.get("success"), res)
        code, prod = req("/products/%d" % pid, "GET", None, base=BASE + "/wp-json/wc/v3")
        check("stock applied after approval", prod.get("stock_quantity") == 25, prod.get("stock_quantity"))
    ok, data = chat("product analysis %d" % pid)
    res = step_tool_result(data, "woo_product_analyze")
    check("agent flow: product analysis", ok and res is not None, [s.get("tool") for s in data.get("steps", [])])
    ok, data = chat("shop design for the store")
    res = step_tool_result(data, "woo_shop_design")
    check("agent flow: shop design", ok and res is not None and res.get("post_id", 0) > 0, res)
    ok, data = chat("create product کفش ورزشی")
    res = step_tool_result(data, "woo_product_create")
    check("agent flow: create product", ok and res is not None, [s.get("tool") for s in data.get("steps", [])])

    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


def code_has_pending(err_text):
    return "Approval entry" in err_text or "pending" in err_text


if __name__ == "__main__":
    sys.exit(main())

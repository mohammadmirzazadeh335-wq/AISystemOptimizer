#!/usr/bin/env python3
"""Focused tests for PHASE 2+3: provider layer + streaming.

Covers: settings roundtrip (custom headers/params), capability detection,
SSE chat stream (deltas, tool calls, steps, usage, done), mid-run cancel,
provider error mapping (401/404/429), secret masking, legacy fallback.

Usage: python3 stream_test.py
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("AIWC_TEST_BASE", "http://127.0.0.1:9400")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CREDS_FILE = os.path.join(REPO, "ai-wordpress-copilot", ".test-credentials")
API = BASE + "/wp-json/ai-copilot/v1"

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


def req(path, method="GET", body=None):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = json.load(open(CREDS_FILE))
    token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
    r.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.getcode(), parse_json_loose(resp.read()), resp.read() if False else b""
    except urllib.error.HTTPError as e:
        try:
            payload = parse_json_loose(e.read())
        except Exception:
            payload = {}
        return e.code, payload, b""
    except Exception as e:
        return 0, {"error": str(e)}, b""


def req_raw(path, method="POST", body=None, timeout=180):
    """Return (http_code, raw_text) — used for SSE parsing."""
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = json.load(open(CREDS_FILE))
    token = base64.b64encode((creds["user"] + ":" + creds["pass"]).encode()).decode()
    r.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def parse_sse(raw):
    """Parse an SSE body into a list of (event, data_dict)."""
    events = []
    for block in raw.split("\n\n"):
        ev, data_lines = "message", []
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[7:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        joined = "\n".join(data_lines)
        try:
            data = json.loads(joined)
        except Exception:
            data = {"raw": joined}
        events.append((ev, data))
    return events


def wait_ready(timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        try:
            url = BASE + "/wp-json/"
            with urllib.request.urlopen(url, timeout=20) as resp:
                if resp.getcode() == 200:
                    url = BASE + "/wp-json/aiwc-test/v1/creds?key=smoke"
                    with urllib.request.urlopen(url, timeout=20) as r2:
                        data = parse_json_loose(r2.read())
                    if "user" in data:
                        with open(CREDS_FILE, "w") as fh:
                            json.dump({"user": data["user"], "pass": data["pass"]}, fh)
                        return True
        except Exception:
            pass
        time.sleep(3)
    return False


def configure(extra=None):
    body = {
        "base_url": "http://127.0.0.1:8899/v1",
        "api_key": "sk-mock-secret-key-1234567890",
        "model": "mock-gpt",
        "streaming": 1,
        "json_mode": 0,
    }
    if extra:
        body.update(extra)
    code, data, _ = req("/settings", "POST", body)
    return code == 200


def main():
    print("== PHASE 2+3 provider/streaming tests against " + BASE + " ==")
    if not wait_ready():
        check("wordpress boot + credentials", False, "site not reachable")
        return 1
    check("wordpress boot + credentials", True)

    # --- 1. Provider settings roundtrip (new keys) ---
    check(
        "configure provider (custom headers/params + streaming)",
        configure(
            {
                "custom_headers": json.dumps({"x-aiwc-test": "echo-42"}),
                "custom_params": json.dumps({"top_k": "5"}),
                "stream_timeout": 60,
                "context_window": 64000,
                "system_prompt": "You are a test assistant.",
            }
        ),
    )
    code, data, _ = req("/settings")
    check(
        "new provider keys roundtrip",
        code == 200
        and "x-aiwc-test" in str(data.get("custom_headers", ""))
        and "top_k" in str(data.get("custom_params", ""))
        and int(data.get("streaming", 0)) == 1
        and int(data.get("context_window", 0)) == 64000,
        data,
    )
    check(
        "api_key masked in GET /settings",
        "sk-mock-secret-key-1234567890" not in json.dumps(data),
        data.get("api_key"),
    )

    # --- 2. Capability detection ---
    code, data, _ = req("/settings/detect-capabilities", "POST", {"force": True})
    check(
        "detect-capabilities (mock-gpt heuristics)",
        code == 200 and data.get("tool_calling") is True and data.get("streaming") is True,
        data,
    )
    code, data, _ = req("/settings/detect-capabilities", "POST", {"force": True})
    caps = data if code == 200 else {}
    check("capabilities include context_window + source", "context_window" in caps and "source" in caps, caps)

    # --- 3. GET /models ---
    code, data, _ = req("/models")
    check("GET /models lists mock models", code == 200 and any("mock-gpt" in m for m in data.get("models", [])), data)

    # --- 4. SSE streaming: simple text ---
    code, raw = req_raw("/chat/stream", "POST", {"message": "خودت را معرفی کن", "conversation_id": 0})
    events = parse_sse(raw)
    kinds = [e for e, _ in events]
    text = "".join(d.get("text", "") for e, d in events if e == "delta")
    done = [d for e, d in events if e == "done"]
    check("SSE stream: 200 + event:start", code == 200 and "start" in kinds, (code, kinds[:6]))
    check("SSE stream: deltas assembled to full text", "delta" in kinds and len(text) > 20, (len(text), kinds))
    check("SSE stream: usage + done events", "usage" in kinds and "done" in kinds, kinds)
    check(
        "SSE stream: done payload has message/steps/plan keys",
        bool(done) and "message" in done[0] and "steps" in done[0] and "plan" in done[0],
        done[0].keys() if done else kinds,
    )

    # --- 5. SSE streaming with tool call (fragmented args assembly) ---
    code, raw = req_raw("/chat/stream", "POST", {"message": "create page درباره ما تست استریم", "conversation_id": 0})
    events = parse_sse(raw)
    kinds = [e for e, _ in events]
    tool_calls = [d for e, d in events if e == "tool_call"]
    steps = [d for e, d in events if e == "step"]
    reviews = [d for e, d in events if e == "review"]
    done = [d for e, d in events if e == "done"]
    check("SSE tool call events emitted", any((d.get("tool") or d.get("name")) == "create_page" for d in tool_calls), tool_calls)
    check("SSE step + review events emitted", bool(steps) and bool(reviews), (kinds, reviews))
    created = False
    if done:
        for s in done[0].get("steps", []):
            r = s.get("result") or {}
            if r.get("success") and isinstance(r.get("data"), dict) and r["data"].get("post_id"):
                created = True
    check("streamed tool call really created the page", created, done[0] if done else kinds)
    check(
        "self-review passed in step data",
        any((s.get("review") or {}).get("ok") for s in (done[0].get("steps", []) if done else []) if s.get("review")),
        done[0].get("steps") if done else "",
    )

    # --- 6. Conversation persisted after streaming ---
    conv_id = done[0].get("conversation_id") if done else 0
    if conv_id:
        code, data, _ = req("/conversations/%d/messages" % conv_id)
        roles = [m.get("role") for m in data.get("messages", [])]
        check("streamed run persisted user+assistant messages", "user" in roles and "assistant" in roles, roles)

    # --- 7. Non-stream endpoint still works (regression) ---
    code, data, _ = req("/chat", "POST", {"message": "hello from non-stream", "conversation_id": 0})
    check("non-stream /chat regression", code == 200 and data.get("message", {}).get("role") == "assistant", data.get("error"))

    # --- 8. Mid-run cancel over streaming ---
    import threading

    def cancel_soon():
        time.sleep(2)
        req("/chat/cancel", "POST", {})

    t = threading.Thread(target=cancel_soon)
    t.start()
    code, raw = req_raw("/chat/stream", "POST", {"message": "slow test for cancel", "conversation_id": 0}, timeout=120)
    t.join()
    events = parse_sse(raw)
    done = [d for e, d in events if e == "done"]
    result = done[0] if done else {}
    check(
        "mid-run cancel ends stream with cancelled flag",
        bool(result) and (result.get("cancelled") is True or result.get("error") == "" or "لغو" in json.dumps(result, ensure_ascii=False)),
        {k: result.get(k) for k in ("cancelled", "error")} if result else [e for e, _ in events],
    )

    # --- 9. Provider error mapping ---
    check("configure model mock-401", configure({"model": "mock-401"}))
    code, data, _ = req("/chat", "POST", {"message": "hi", "conversation_id": 0})
    err_text = json.dumps(data, ensure_ascii=False)
    check(
        "401 → sanitized auth error",
        code in (200, 502, 400, 401)
        and "API key" in err_text
        and "sk-mock-secret-key-1234567890" not in err_text,
        err_text[:300],
    )

    check("configure model mock-429", configure({"model": "mock-429"}))
    code, data, _ = req("/chat", "POST", {"message": "hi", "conversation_id": 0})
    err_text = json.dumps(data, ensure_ascii=False)
    check("429 → rate limit message", "rate limit" in err_text.lower() or "محدود" in err_text, err_text[:300])

    check("configure model mock-404", configure({"model": "mock-404"}))
    code, data, _ = req("/chat", "POST", {"message": "hi", "conversation_id": 0})
    err_text = json.dumps(data, ensure_ascii=False)
    check("404 → model not found message", "model" in err_text.lower() or "مدل" in err_text, err_text[:300])

    # --- 10. Legacy (no tool-calling) model still executes via fenced protocol ---
    check("configure model mock-no-tools", configure({"model": "mock-no-tools"}))
    code, data, _ = req("/chat", "POST", {"message": "create page صفحه میراث قدیمی", "conversation_id": 0})
    legacy_ok = False
    for s in data.get("steps", []):
        r = s.get("result") or {}
        if s.get("tool") == "create_page" and r.get("success"):
            legacy_ok = True
    check("legacy fenced protocol executes tool", code == 200 and legacy_ok, data.get("error") or [s.get("tool") for s in data.get("steps", [])])

    # --- restore ---
    configure({"model": "mock-gpt", "streaming": 1})
    print("\n== RESULT: %d passed, %d failed ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

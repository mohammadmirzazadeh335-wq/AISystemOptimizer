# Phase 4 plan — Agent Mode with validated tools (v0.4.0)

**Goal:** an agent that can only act through registered tools with a JSON schema, a risk
level and a confirmation gate, and that tells the truth when a capability is unavailable.

**Non-goals for this phase:** autonomous background execution, unrestricted shell, any
tool that silently reaches the network, any "image generation" without a real provider.

## Scope

| Area | What ships | Honesty rule |
| --- | --- | --- |
| Tool registry | `ToolSpec` (id, JSON schema, risk, availability, handler), argument validation, deterministic ordering | A tool that cannot run is listed as unavailable with the exact reason |
| Permission gate | `read` runs automatically; `write`/`execute`/`network` require approval when `agent.require_confirmation` is on | A denied call is recorded as denied, never executed |
| Local tools | `list_files`, `read_file`, `write_file`, `delete_file`, `run_file`, `remember`, `recall`, `save_output` | File access is confined to the opened project; `run_file` uses the real toolchain |
| Network tools | `web_search` (SearxNG-compatible JSON endpoint), `github_list_issues`, `github_comment` | Unavailable without endpoint/token; never faked, never allowed by default (`agent.allow_network`) |
| Image tool | `generate_image` | Registered but **always unavailable**: no image provider is configured and OpenRouter text models cannot produce images |
| Agent loop | model → tool calls → validation → approval → execution → tool result → repeat, with step limit, cancel and per-step events | No model/key → error, not a fabricated plan |
| Agent UI | task input, live step list, tool cards with risk badges, approve/deny, stop, final answer | Every control reaches real code |
| Task centre | recent agent runs with status and duration | Records come from real runs |

## Acceptance gate (same rules as phases 2–3)

1. New behaviour is covered by tests that execute real code; provider calls are the only
   mocked part (`httpx.MockTransport`) because `openrouter.ai` is unreachable here.
2. Screenshots of the Agent page and the approval dialog, fa RTL + en LTR, both themes,
   reviewed at 1.0×, 1.25× and 1.5×.
3. No display-only control: every visible button has a receiver and an effect.
4. A full-suite run after the last change; the numbers in the report come from that run.
5. fa + en documentation and the seven-part report.
6. `ruff` clean; no new third-party dependency.

## Risks to handle explicitly

- **Path escape** through tool arguments (traversal, absolute paths, drive letters,
  symlinks) — reuse `ProjectService` guards and test them through the agent path.
- **Secret leakage** — tool arguments and outputs are logged without secrets; the GitHub
  token and search key are read from the encrypted store, never from arguments.
- **Runaway loops** — `agent.max_steps` (1–50) and a hard per-tool timeout.
- **Cancellation** — a cancel event stops the stream, the tool in flight and the loop.
- **Honest unavailability** — network tools are off by default; enabling requires the
  setting *and* the endpoint/token, and both reasons are shown when missing.

# Phase 4 report — Agent Mode with validated tools (v0.4.0)

Agent Mode turns the model into an operator that may only act through **registered tools**
with a JSON schema, a risk level and an availability check. Every write, delete, execution
or network call is gated behind an explicit approval; a denied call is recorded as denied
and is never executed. When a tool cannot run, the page and the settings screen say exactly
what is missing (no API key, no project folder, network off, no endpoint, no token, no image
provider). Nothing is simulated.

Every number below comes from commands executed **after the last code change**.

---

## 1. Test results

### 1.1 Whole suite (final run, after the last change)

```
$ cd myai_studio && ./scripts/run_tests.sh -q
432 passed, 1 skipped in 194.28s (0:03:14)
```

| Layer | Result | Collected |
| --- | --- | --- |
| `tests/unit` + `tests/integration` | **250 passed, 1 skipped** (6.67 s) | 251 |
| `tests/ui` | **182 passed** (189.90 s) | 182 |
| **total** | **432 passed, 1 skipped** | **433** |

The one skip is the opt-in live OpenRouter test (`tests/unit/test_openrouter.py:360`):
it needs `MYAI_LIVE_API_KEY` and `openrouter.ai`, neither of which exists in this
environment. It is **not** counted as a pass.

Baseline before Phase 4: 319 passed, 1 skipped. Phase 4 adds **115 tests**:

| New file | Tests | What it proves |
| --- | --- | --- |
| `tests/unit/test_agent_tools.py` | 43 | every tool handler against real files; path escape, invalid arguments, missing gates, real `python` execution, HTTP via `MockTransport` |
| `tests/unit/test_agent.py` | 30 | the loop: tool schemas sent to the provider, approval, denial, unknown tool, step limit, cancel, provider errors, history |
| `tests/unit/test_openrouter_tools.py` | 7 | tool-call decoding from streamed SSE frames, malformed arguments, capability flags |
| `tests/ui/test_agent_page.py` | 33 | the real window: tool card contents, run, approve/deny dialog, cancel, limit, fa/en + RTL, settings page, small-window layout |

Two Phase-2 tests were **updated, not deleted**: the route matrix now expects the real
Agent page instead of a placeholder, and the placeholder key list no longer contains
`placeholder.agent_*`.

### 1.2 What the tests actually execute

- Real files in a temporary project are read, written, listed, deleted and executed with
  the `python` that runs the suite; results are compared with the file system afterwards.
- `write_file`, `delete_file`, `run_file`, `web_search`, `github_*` go through the same
  confirmation gate as the UI; a denial asserts the file/endpoint was untouched.
- Provider traffic is the only mocked part (`httpx.MockTransport`); no test claims a live
  model call.

### 1.3 Lint

```
$ ../.venv/bin/ruff check myai tests scripts
All checks passed!
```

No new third-party dependency was added in this phase.

---

## 2. Commands used

```bash
cd myai_studio
./scripts/run_tests.sh -q                                   # 432 passed, 1 skipped
../.venv/bin/ruff check myai tests scripts                  # clean
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=../tools/headless_libs \
  ../.venv/bin/python scripts/capture_ui.py --out artifacts/ui   # EXIT=0, 55 PNGs
```

Headless libraries were rebuilt for this container with
`PYTHON=../.venv/bin/python bash scripts/make_headless_libs.sh` (the previous stubs had
been lost with the sandbox; the script is the repository's own, unchanged).

Screenshots produced by the last capture run (`artifacts/logs/capture_p4_master.log`, EXIT=0):

- `p4_agent_idle_{midnight,dawn}_{fa,en}.png` — page before any run (fa RTL / en LTR).
- `p4_agent_run_{midnight,dawn}_{fa,en}.png` — a completed run, real tool output.
- `p4_agent_approve_dawn_en.png` — the real approval dialog over the page.
- `p4_agent_scale_1_25_en.png`, `p4_agent_scale_1_5_en.png` — DPI stress at 1.25× / 1.5×.
- `10b_settings_agent_fa.png` — Settings → Agent & tools.

All of them were opened and reviewed. The capture workspace uses a placeholder key and a
**deterministic local client** so a run can be photographed without the network; neither
the report nor the screenshots claim a live model call.

---

## 3. What is complete

| Area | State | Proof |
| --- | --- | --- |
| Tool registry: 12 tools, JSON schema, risk, availability reason | **Works** | `myai/services/tools.py`, `test_agent_tools.py` |
| Argument validation (types, bounds, unknown keys, path confinement) | **Works** | `test_agent_tools.py` path-escape tests |
| Approval gate: `write`/`execute`/`network` ask first; denial never executes | **Works** | service-level `ToolDenied` + UI tests |
| Exact unavailability text (no key / no project / network off / no endpoint / no token / no image provider), translated fa/en | **Works** | `REASON_TEXT`, `agent.reason_*` keys, both locales |
| Bounded loop: `agent.max_steps` 1–50 (default 12), cancel, per-step events | **Works** | `test_agent.py` limit/cancel tests |
| Tool results and failures returned to the model **verbatim** | **Works** | `_tool_message`, loop tests |
| Real local execution through the Phase-3 toolchain detection | **Works** | `run_file` tests with real `python` |
| Web search (SearxNG-compatible JSON endpoint), GitHub issues/comment (REST) | **Works when configured**; otherwise listed as unavailable with the reason | `MockTransport` tests; settings page fields |
| Image generation | **Always unavailable** — no provider exists; the tool says so instead of pretending | `test_agent_tools.py::test_generate_image_is_unavailable` |
| Agent UI: task input, live timeline, tool run details, final answer, stop | **Works** | `test_agent_page.py`, screenshots |
| Recent runs with status/duration; reopen an earlier run | **Works** | history tests |
| Settings → Agent: confirmation, network, max steps, search endpoint, GitHub token (encrypted), live tool availability | **Works** | `10b_settings_agent_fa.png`, UI tests |
| Layout at 1.0× / 1.25× / 1.5×, small windows, fa/en, both themes | **Works** | 12 Phase-4 screenshots + layout tests |

### The twelve tools

| Tool | Risk | Needs | Available in this environment |
| --- | --- | --- | --- |
| `list_files`, `read_file` | read | project | yes (project open) |
| `write_file`, `delete_file` | write | project + approval | yes (approval) |
| `run_file` | execute | project + toolchain + approval | yes (`python`) |
| `remember`, `recall` | write / read | — | yes |
| `save_output` | write | — | yes |
| `web_search` | network | network on + SearxNG endpoint + approval | no endpoint here |
| `github_list_issues`, `github_comment` | network | network on + GitHub token + approval | no token here |
| `generate_image` | network | an image provider | **never** — none configured |

### UI defects found by reviewing the screenshots and fixed in this phase

| Defect | Fix |
| --- | --- |
| Twelve tool rows were compressed to 13 px and the card rendered blank | card is a single-line-per-tool scroll area (44 px rows, visible 10 px track); the status and reason sit in an elided second line with the full text in a tooltip |
| The English/fa reason text was clipped mid-word in the row | row meta uses `ElidedLabel`; the *full* reason stays in the tooltip and in Settings → Agent |
| Task-card badges were cut in half in a narrow pane | badges moved into a `FlowLayout` that wraps under the title |
| The run hint ran underneath the “Run agent” button | hint takes ignored width, wraps inside its own column |
| A 1120×720 window squeezed both panes into overlapping cards | the splitter stacks vertically and the workspace scrolls; tool rows keep their height (two tests) |
| Inspector cards collapsed to a strip on a short window | inspector body layout pins its minimum and scrolls |
| The sidebar's empty state painted over the LIBRARY rows on a short window | navigation column scrolls; the decorative circle yields first (test) |

---

## 4. What is incomplete

- **No live OpenRouter run.** The environment has no key and `openrouter.ai` is unreachable
  (TCP connects, TLS handshake is dropped). Tool schemas, tool-call decoding and the loop are
  covered with `httpx.MockTransport`; this is labelled as mocked everywhere.
- **`generate_image` is registered but permanently unavailable.** There is no image service
  and OpenRouter text models cannot return images; Phase 5 may add one only with a real API.
- **Web search requires a SearxNG-compatible endpoint**; no public endpoint is bundled.
- **GitHub tools require a personal access token** saved through Settings → Agent; the token
  is stored in the encrypted store and never in backups or logs.
- **One tool call runs at a time.** Parallel tool calls from the model are executed
  sequentially (order preserved); the loop is single-threaded per run.
- **No “allow for this session” shortcut.** Every sensitive call asks again, by design; a
  session-wide switch would weaken the gate and is not implemented.
- **Streaming inside a step is limited.** Tokens of intermediate assistant messages are not
  shown live; the step appears when the model finishes that turn (the final answer is
  rendered in full). Chat streaming itself is unchanged from Phase 3.

---

## 5. Real OpenRouter result

**Not live-tested.** No `MYAI_LIVE_API_KEY` is set, and `https://openrouter.ai/api/v1/models`
cannot be reached from this sandbox (TLS handshake dropped). Consequently:

- the model catalogue in the screenshots comes from a cache entry built with
  `parse_model()` for a synthetic tool-capable model (`Capture Tool Model`);
- the agent reply in the run screenshots comes from a deterministic local client;
- the live test in `tests/unit/test_openrouter.py` is **skipped**, and the skip is reported
  as a skip, not a pass.

Everything else — request shape, streaming SSE parsing, tool-call frames, error mapping —
is exercised against a mocked transport.

---

## 6. Changed files

New:

```
myai/services/tools.py              tool registry, 12 handlers, reasons, validation
myai/services/agent.py              the bounded agent loop, approvals, history, cancel
myai/ui/views/agent_page.py         Agent Mode page (tools card, task, timeline, runs)
tests/unit/test_agent_tools.py      43 tests
tests/unit/test_agent.py            30 tests
tests/unit/test_openrouter_tools.py 7 tests
tests/ui/test_agent_page.py         33 tests
docs/PHASE4_PLAN.md                 scope and acceptance gate for this phase
docs/PHASE4_REPORT.md               this report
docs/PHASE4_REPORT_FA.md            Persian report
docs/AGENT_MODE.md                  user guide (en)
docs/AGENT_MODE_FA.md               user guide (fa)
```

Modified:

```
myai/version.py                 0.4.0, PHASE = 4
myai/context.py                 builds ToolRegistry + AgentService
myai/core/events.py             AGENT_* events for the activity feed
myai/services/openrouter.py     tool-call support in the streaming path
myai/services/settings.py       agent.* defaults and validation (max_steps 1–50)
myai/i18n/locales/{en,fa}.json  812 keys each, parity enforced by a test
myai/ui/main_window.py          agent route, page refresh, Chat/Agent switch
myai/ui/views/settings_dialog.py  real Settings → Agent page
myai/ui/views/placeholder.py    agent is no longer a placeholder
myai/ui/views/sidebar.py        scrollable navigation column, readable empty state
myai/ui/views/inspector.py      cards keep their height and scroll on short windows
myai/ui/widgets/foundation.py   EmptyState exposes its icon circle
tests/unit/test_i18n.py         locale parity + agent keys
tests/ui/test_phase2_pages.py   route matrix now expects the real page
scripts/capture_ui.py           Phase-4 capture matrix (deterministic client)
artifacts/ui/*.png              55 screenshots, 12 of them Phase 4
```

`myai/ui/views/code_page.py` is **untouched** in this phase.

---

## 7. Remaining issues and limits

1. **Tools card is scrollable by design.** Twelve rows do not fit the card at 100 % scale,
   so the list scrolls with an always-visible 10 px track; the header shows “N of 12 ready”.
   At 1.5× the card keeps its minimum height and the page scrolls (see
   `p4_agent_scale_1_5_en.png`).
2. **Approval dialog is deliberately modal** and cannot be disabled per tool from the
   dialog; the global switch lives in Settings → Agent.
3. **The activity feed shows agent events** (`Agent run: ok · 1 tool call`) but cannot
   cancel a run from there.
4. **Run history is in memory for the session**, not yet persisted to SQLite; reopening the
   app starts with an empty “Recent runs” list. Persisting runs is a Phase-5 task centre item.
5. **Long tool outputs are truncated** for display (the model still receives the trimmed
   text marked as truncated); see `MAX_READ_CHARS` / `MAX_TOOL_OUTPUT` in `tools.py`.
6. **Network tools fail loudly** if the endpoint/token is wrong; failures are fed back to
   the model verbatim and shown in the step, not retried silently.
7. **No EXE was produced** in this phase. Packaging still requires a Windows host running
   `scripts/build_windows.ps1`; no placeholder binary is shipped.

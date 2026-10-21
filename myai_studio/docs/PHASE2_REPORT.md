# Phase 2 Report — AI core

**Version:** 0.2.0 · **Date:** 2026-10-21 · **Status:** implemented and tested; OpenRouter live calls **not** possible in this environment
**Project path:** `/home/user/AISystemOptimizer/myai_studio`
**Test command:** `cd myai_studio && ./scripts/run_tests.sh -q`

---

## 1. Verification summary (measured, final run)

| Item | Result |
| --- | --- |
| Test suite collected | **265** (unit 129 · ui 122 · integration 14) |
| Passed / failed / skipped | **264 passed · 0 failed · 1 skipped** in 79.3 s |
| Lint (`ruff check myai tests scripts`) | All checks passed |
| Screenshots produced | **35** PNG files (code for all of them is `scripts/capture_ui.py`) |
| Live OpenRouter request | **not performed** — the sandbox cannot reach `openrouter.ai` (see §5) |

### 1.1 Final measured run

```
$ cd myai_studio && ./scripts/run_tests.sh -q
264 passed, 1 skipped in 81.31s
SKIPPED [1] tests/unit/test_openrouter.py:360: live API test: set MYAI_LIVE_API_KEY
                to run against openrouter.ai

$ ./scripts/run_tests.sh tests/unit -q          -> 128 passed, 1 skipped in  1.69 s
$ ./scripts/run_tests.sh tests/integration -q   ->  14 passed            in  0.43 s
$ ./scripts/run_tests.sh tests/ui -q            -> 122 passed            in 78.33 s
$ ../.venv/bin/ruff check myai tests scripts    -> All checks passed!
```

The single skip is the opt-in live OpenRouter test; it needs `MYAI_LIVE_API_KEY`
**and** outbound network access to `openrouter.ai`, neither of which this sandbox has.

This run was the *last* run, executed after the final code change — the previous
suite needed >40 minutes because closed windows were never destroyed and every new
theme application re-polished the whole widget backlog. That leak is fixed
(`tests/conftest.py` flushes `DeferredDelete`; `ThemeManager` skips identical
styles), and the same suite now takes 79 s.

## 2. What was built

### 2.1 OpenRouter connection (`myai/services/openrouter.py`, `myai/ui/views/api_page.py`)

- Key management: enter, replace, delete; masked display (`sk-or-v1…abcd`) is the only
  form ever rendered. Storage goes through `SecretStore` — Windows DPAPI, Fernet vault
  elsewhere. Backups, logs and exports are proven key-free by tests.
- "Test connection" performs one authenticated `GET /models` and reports the measured
  latency and catalogue size. A failed test shows the mapped error, not a success.
- Dynamic model catalogue from the API; capabilities (`tools`, `vision`, context length,
  pricing) are shown **only** when the provider reports them — `parse_model` defaults to
  `False`/`0` rather than guessing.
- Model chooser in the main header and on the API page; the default is persisted and
  cached (`ai.openrouter_cache`) so a restart still shows the list offline.
- Streaming with SSE parsing, cancellation via `threading.Event`, first-token and total
  latency, token usage, per-message stats.
- Typed errors: 401/403 → auth, 402 → credit, 429 → rate limit, 404 → model, 5xx →
  provider, timeouts and connection failures → network. Each maps to a translated message
  in fa/en.

### 2.2 Memory (`myai/services/memory.py`, `myai/ui/views/memory_page.py`)

- Two independent scopes: `global` and `conversation`; the UI cannot create a conversation
  memory without a conversation.
- View / add / edit / delete / pin; per-scope clear behind a confirmation dialog.
- Conversation summarising extracts *candidate* facts from the user's own messages and
  shows them for editing; nothing is stored until "Save these memories" is pressed, and
  history is never modified (`summarize_conversation` only reads).
- Storage size (characters) and estimated context usage (≈4 chars/token) are displayed as
  separate numbers, with the estimate labelled everywhere it appears.
- Warning when the context window is nearly full (`ai.context_warn_ratio`, default 0.8).

### 2.3 Personality and profile (`myai/services/persona.py`, `myai/ui/views/persona_page.py`)

- A Markdown profile file the user owns (`profile.md` in the workspace), editable in-app,
  importable from disk, reloadable; the shipped template is detected and never injected.
- A separate assistant persona box with enable toggle, tone, detail level and answer
  language. Both are stored outside memory and are proven separate by tests.
- Prompt assembly order: system instruction → persona → profile → memory → history.

### 2.4 Output Studio (`myai/services/outputs.py`, `myai/ui/views/output_page.py`)

- Kinds: code, text, prompt, Markdown, JSON; language guessed from the extension.
- Code/text editor, Markdown rendered preview, JSON preview with validation ("Invalid JSON:
  Expecting property name … line 1, column 2") and a formatter.
- Every save keeps the previous content as a revision; the history lists them, the diff tab
  shows a real unified diff with added/removed counts, restore writes the old content back
  while preserving the replaced text as a new revision.
- Export to a real file; import from disk; delete with confirmation.

### 2.5 UI integration

- New sidebar group "AI tools": Connection & models, Memory, Personality, Output Studio.
- Header model chooser wired to the catalogue; context ring driven by the real estimate.
- Inspector shows injected memory entries, storage size and context breakdown, with a
  "Connect a model" action instead of a phase-locked placeholder.
- Assistant replies can be sent to Output Studio from the message menu; failed replies can
  be retried without duplicating the user turn.

## 3. Threading and responsiveness

`ChatService.send` runs in a worker thread (`myai-chat`). Deltas, status and completion are
delivered through a `QObject` bridge with queued signals, so widgets are only ever touched
on the GUI thread. A test runs a 10 ms timer during a slow stream and asserts the event loop
kept firing (the UI was not blocked). Cancellation sets an event that the client checks
between chunks.

## 4. Test coverage added in Phase 2

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/test_openrouter.py` | 19 (+1 opt-in live) | catalogue parsing, caching, capability honesty, every HTTP status, timeouts, network failure, streaming, first-token timing, cancel, in-stream errors, no key in logs |
| `tests/unit/test_chat_service.py` | 13 | streaming + persistence, stats, cancel, memory/persona injection, isolation, error rows, context report, usage fallback, no key leakage |
| `tests/unit/test_memory.py` | 9 | scopes, isolation, CRUD, validation, cascade, summary consent, context report |
| `tests/unit/test_persona_outputs.py` | 13 | profile file lifecycle, template detection, persona validation, separation, output revisions/diff/restore/export/import, JSON helpers |
| `tests/ui/test_phase2_pages.py` | 42 | routing, key UX, catalogue rendering, model selection, memory/persona/studio pages, streaming bubbles, responsiveness, network errors, cancel, RTL, wrapping, DPI, no-Persian-text-in-English, dead-button scan, header metrics at 1.5× |
| `tests/unit/test_i18n.py` (+4) | plural forms, translated Phase 2 copy |
| `tests/unit/test_settings_secrets.py` (+2) | Phase 2 settings round-trip and validation |
| `tests/integration/test_end_to_end.py` (7 total, +4 in Phase 2) | restart survival of memory/persona/outputs, isolation after restart, disk round-trip, key never in backups |

Mocked tests use `httpx.MockTransport`; they prove the client logic, **not** connectivity.
The live test is skipped unless `MYAI_LIVE_API_KEY` is set and the network reachable.

## 5. OpenRouter live test result

Not performed. Outbound HTTPS to `openrouter.ai` is blocked from this sandbox (the same
restriction is documented in the Phase 1 report), and no real API key exists in this
environment. The exact probe at report time:

```
$ curl -sS -m 15 https://openrouter.ai/api/v1/models
curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to openrouter.ai:443
```

TCP connects to 104.18.3.115:443, but the TLS handshake is dropped by the sandbox
network policy, so no HTTP request can complete; `MYAI_LIVE_API_KEY` is also unset.
Therefore:

- request building, SSE parsing, error mapping, cancellation and timing are covered by
  mocked transport tests, and
- **no claim is made** that a real reply was received in this environment.

To run the live check where the network is available:

```bash
export MYAI_LIVE_API_KEY=sk-or-v1-...      # PowerShell: $env:MYAI_LIVE_API_KEY="..."
python -m pytest tests/unit/test_openrouter.py -k live -v
```

## 6. Bugs found and fixed during Phase 2 verification

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | Persian pages kept English labels after a language switch | only `retranslate()` ran on pre-built widgets | pages rebuild their body on language/theme change |
| 2 | Toasts covered page headers | fixed 146 px bottom margin | margin switches to 30 px on full pages |
| 3 | Persian text in the profile editor showed broken ZWNJ shapes | forced LTR mono font | UI font for prose + per-paragraph auto direction |
| 4 | "1 entries", "1 revisions" | no plural forms | `tn()` plural helper + `*.one`/`*.many` keys |
| 5 | Studio editor squeezed to ~20 px at 1440 px with the inspector open | three-column split | rail + (editor above preview) split |
| 6 | Studio page clipped at 1.5× font scale | fixed splitter budgets, clipped actions | rail hides below 560 px, wrapping action row |
| 7 | Header controls overlapped at 1120 px | expanding title kept its width | title policy `Ignored`, secondary chrome collapses |
| 8 | RTL action row put the primary button on the left | FlowLayout ignored direction | RTL-aware wrapping + direction-change hook |
| 9 | `RuntimeError: C++ object already deleted` after a stream | queued deletion of a re-rendered card | guarded drop + reset on re-render |
| 10 | `input_tokens` always 0 when a provider omits usage | empty join in the fallback | fallback to the prompt estimate |
| 11 | Retry duplicated the user turn | send appends the turn again | retry removes the failed pair first |
| 12 | First-token label showed 0 ms | placeholder value | measured with `time.monotonic()` |
| 13 | English page showed a Persian button and a Persian assistant name | text set once at construction / transliterated name | relabel on rebuild, `chat.assistant` = "دستیار", regression test walks every page |
| 14 | "Send persona with requests" drew the first letter on the icon | text rect started at the padding, under the glyph | icon/text rects computed once and never overlapping (unit test) |
| 15 | Placeholder card rows cut wrapped feature text in half | fixed 38 px row height | height derived from `heightForWidth`, applied after layout settles |
| 16 | Duplicate page headline (window header + page header) | both printed the title | page prints subtitle only; header keeps the title |
| 17 | Chat/Agent labels ran together at 1.5× font scale | segment width frozen at construction | widths recomputed on every theme/font change |
| 18 | Action buttons looked like form widgets at 1.5× (55 px save button) | `QPushButton[size="sm"]` selector swallowed Qt's own `size` property | selector renamed to `buttonsize`; height refits on scale change |
| 19 | Stale "Phase 1"/"Phase 2" copy in chat notice and local-mode subtitle | hard-coded strings from Phase 1 | rewritten to describe the real state ("connect a key to get replies") |
| 20 | Suite slowed to >40 min and appeared to hang | deleted windows kept alive by `deleteLater` + `setStyle` re-polish | flush `DeferredDelete` between tests, style once per process, skip identical stylesheets |

## 6b. Screenshot review (all pages, both languages)

35 PNGs in `artifacts/ui/`, regenerated from the final code by
`python scripts/capture_ui.py --out artifacts/ui`:

| Set | Files |
| --- | --- |
| Phase 2 pages | `p2_{api,memory,persona,studio}_{midnight,dawn}_{fa,en}.png` (16) |
| DPI / min-window stress | `p2_scale_{1_25,1_5}_{api,studio}_en.png` (4) |
| Phase 1 matrix | `01…10` welcome, conversation (dark/aurora/dawn), collapsed sidebar, route placeholder, 1280×720, 1920×1080, confirm dialog, settings ×2 (15) |

Every file was opened and checked for: RTL/LTR correctness, overlap, clipping,
bar height and button height, and consistency across the four Phase 2 pages.

## 7. Known limitations

- **No live OpenRouter verification here** (network blocked, no key).
- Conversation summarising is deterministic local extraction; it does not call a model to
  paraphrase. The user reviews every candidate before it is stored.
- Context usage is an estimate until the provider returns usage numbers; the UI always
  marks the estimate.
- Token counting uses a characters/4 heuristic, not a tokenizer.
- Only text chat is implemented; images/tools/agents remain Phase 3–4.
- The sandbox runs Qt on the offscreen platform; visual checks are PNG renders, not a real
  compositor, and Windows-specific DPAPI behaviour is covered by the fallback path here.

## 7b. Dependencies added in Phase 2

Phase 2 introduced no new runtime package: streaming uses `httpx` (already required
for the health checks) and storage uses the existing SQLAlchemy 2.0 models. The
client is written against `httpx.MockTransport` in tests, which ships with httpx.

To reproduce the environment from scratch:

```bash
cd myai_studio
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # PySide6, SQLAlchemy, httpx, cryptography, keyring
.venv/bin/pip install -r requirements-dev.txt    # pytest, pytest-qt, ruff, pyinstaller
```

On Windows use `.venv\Scripts\pip`. Pinned versions live in those two files
(`requirements.txt`: PySide6 6.8.x, SQLAlchemy 2.0.38, httpx 0.28.1; dev adds
pytest 8.3.5, pytest-qt, ruff 0.9.10, pyinstaller).

Linux/macOS additionally need the headless stub libraries for the offscreen Qt
platform used by this sandbox; they are generated by a committed script:

```bash
bash scripts/make_headless_libs.sh     # writes ../tools/headless_libs
```

`scripts/run_tests.sh` finds them automatically and sets `QT_QPA_PLATFORM=offscreen`.

## 8. Files created / changed

New: `myai/services/{openrouter,chat,memory,persona,outputs}.py`,
`myai/ui/views/{page_base,api_page,memory_page,persona_page,output_page}.py`,
`tests/unit/{test_openrouter,test_chat_service,test_memory,test_persona_outputs}.py`,
`tests/ui/test_phase2_pages.py`, `scripts/make_headless_libs.sh`,
`docs/PHASE2_REPORT.md`, `docs/PHASE2_REPORT_FA.md`.

Changed: `myai/{context,version}.py`, `myai/core/events.py`, `myai/data/{models,db,repositories}.py`,
`myai/services/{conversations,settings}.py`, `myai/security/secrets.py`,
`myai/i18n/{__init__.py,locales/*.json}`, `myai/ui/theme/icons.py`,
`myai/ui/main_window.py`, `myai/ui/views/{chat_view,header,inspector,sidebar}.py`,
`myai/ui/widgets/{feedback,fields}.py`, `tests/*`, `scripts/{run_tests,capture_ui}.sh|py`,
`README.md`, `docs/ROADMAP.md`, `artifacts/ui/*`.

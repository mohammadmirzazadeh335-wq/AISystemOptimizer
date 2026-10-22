# Roadmap

Five phases. Each phase ships something runnable, tested and documented before the
next one starts. Status reflects **actual** progress, not intentions.

| Phase | Theme | Status | What ships |
| --- | --- | --- | --- |
| 1 | Foundation | **Complete (v0.1.0)** | shell, design system, i18n/RTL, persistence, settings, secrets, backups, tests, screenshots, packaging scripts |
| 2 | AI core | **Complete (v0.2.0)** | OpenRouter client (streaming, cancel, retry, timeouts), model catalogue, chat with real replies, token/latency stats, personality files, memory (global + per conversation), prompt library foundation |
| 3 | Code Studio | **Complete (v0.3.0)** | real folder tree, editor with syntax highlighting + line numbers, autosave and `Ctrl+S`, real execution with detected toolchains, verbatim compiler diagnostics, stdout/stderr/exit code, cancel + wall-clock limit, missing toolchains named (no interactive debugger yet — see report §4) |
| 4 | Agent & tools | **Complete (v0.4.0)** | 12 validated tools with JSON schemas and risk levels, approval gate for write/execute/network, real file/project tools, real execution through the Phase-3 toolchain detection, web search (SearxNG endpoint) and GitHub tools gated by settings, session run history, Settings → Agent page. Image generation is registered but **unavailable** — no provider exists (see report §4) |
| 5 | Ecosystem & polish | **Complete (v0.5.0)** | prompt library (SQLite, six built-ins, CRUD, search, tags, send-to-composer), task centre (every finished agent/program run persisted with steps), performance monitor measured from the process and the workspace, Image/Video Studio + web research pages with honest labels (no provider ⇒ unavailable; libraries and page reading are real), plugin loader for prompt packs (manifest, permissions, disabled by default, code plugins rejected), accessibility pass (36 assertions), placeholder pages deleted. **No EXE was produced in this environment** — the Windows script is unverified (report §4) |

## Acceptance criteria per phase

**Phase 2** — a real request to OpenRouter streams tokens into the UI; cancel stops
the stream within 250 ms; a bad key produces a translated error and no traceback in
the UI; usage stats are stored per message; memory survives restart; no key ever
appears in logs, exports or backups. Because this sandbox cannot reach
`openrouter.ai`, live calls will be labelled **not live-tested** with the exact
error and a mocked-transport test proving the client logic.

**Phase 3** — open a folder, edit a file, run it, see real stdout/stderr, see real
compiler errors, edit and re-run. Toolchains that are missing are reported as
unavailable rather than faked. Every language claim needs a test that compiles and
runs a real file on this machine.

**Phase 4 (met)** — every agent action goes through a registered tool with a schema, a
permission level and a confirmation gate for sensitive operations; a denied call never
executes; tool results and errors are fed back verbatim; the loop is bounded; web search
and image generation are labelled unavailable when no working service is configured.

**Phase 5 (met, with two honest gaps)** — plugins load from a validated manifest with
permissions and start disabled; every metric on the performance page is sampled from the
real process or workspace; media and web-search surfaces state unavailability instead of
faking output; every page and control is keyboard reachable and named. Gaps, both stated
in the report: no `.exe`/installer was built because this host is Linux (the PowerShell
build script remains unvalidated), and no live provider call was possible.

## After Phase 5 (same version line)

The five phases above are closed. A later hardening pass adds, without moving
any tag:

* Windows 11 rules in `core/platform.py` (reserved names, long paths, hidden
  child consoles, tolerant decoding, frozen-build interpreter) plus
  `scripts/windows11_smoke.ps1` for a one-command verification on a real machine;
* real file attachments (copy → extract → send → persist, schema v4);
* `search_files`, `make_folder` and `create_project` agent tools;
* a command palette on `Ctrl+Shift+P`, with a selection that stays visible
  regardless of window focus;
* real controls on Settings → AI (temperature) and Settings → Memory (enable
  toggle, live count, navigation), replacing the last phase-placeholder pages.

Details and honest limits: [`POST_PHASE5_UPGRADE.md`](POST_PHASE5_UPGRADE.md).

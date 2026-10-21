# Roadmap

Five phases. Each phase ships something runnable, tested and documented before the
next one starts. Status reflects **actual** progress, not intentions.

| Phase | Theme | Status | What ships |
| --- | --- | --- | --- |
| 1 | Foundation | **Complete (v0.1.0)** | shell, design system, i18n/RTL, persistence, settings, secrets, backups, tests, screenshots, packaging scripts |
| 2 | AI core | **Complete (v0.2.0)** | OpenRouter client (streaming, cancel, retry, timeouts), model catalogue, chat with real replies, token/latency stats, personality files, memory (global + per conversation), prompt library foundation |
| 3 | Code Studio | **Complete (v0.3.0)** | real folder tree, editor with syntax highlighting + line numbers, autosave and `Ctrl+S`, real execution with detected toolchains, verbatim compiler diagnostics, stdout/stderr/exit code, cancel + wall-clock limit, missing toolchains named (no interactive debugger yet — see report §4) |
| 4 | Agent & tools | Next | validated tool registry, approval workflow, file/project tools, web search, image studio, GitHub integration, task center |
| 5 | Ecosystem & polish | Planned | plugin architecture, performance monitor, video studio (only if a real service exists), accessibility pass, final report, installer |

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

**Phase 4** — every agent action goes through a registered tool with a schema, a
permission level and a confirmation gate for sensitive operations. Web search and
image generation are labelled unavailable if no working service is reachable.

**Phase 5** — plugin loading with permission manifests, performance metrics measured
from the real process, an honest capability table, Persian user guide, and a real
`.exe`/installer only if the build script succeeds.

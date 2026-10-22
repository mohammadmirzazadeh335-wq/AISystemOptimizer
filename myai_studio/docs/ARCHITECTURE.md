# Architecture

## 1. Goals

1. The UI never blocks on I/O.
2. Core logic has no Qt dependency and is trivially unit-testable.
3. Every capability is replaceable without rewriting the shell (providers, tools,
   storage, themes, languages).
4. Failures are visible, logged and recoverable — never swallowed.
5. The product stays maintainable across five phases.

## 2. Layers

```
┌────────────────────────────────────────────────────────────┐
│ ui/                     PySide6 widgets, views, theme      │
│   bridge.QtBridge  ── converts core events to Qt signals   │
├────────────────────────────────────────────────────────────┤
│ services/               use-cases (no Qt imports)          │
│   settings · conversations · activity · backup             │
│   openrouter · chat · memory · persona · outputs           │
│   toolchains · runner · projects                           │
├────────────────────────────────────────────────────────────┤
│ data/ security/ core/   persistence, crypto, infra          │
│   repositories · secret store · events · logging · errors   │
└────────────────────────────────────────────────────────────┘
```

Dependency direction is strictly downward. `myai.core`, `myai.data`, `myai.services`
and `myai.security` import **no** PySide6 modules; this is verified by
`tests/integration/test_layering.py`.

## 3. Composition root

`myai/context.py::build_context()` constructs the entire object graph once:

```
AppPaths → Database → Repositories → Services → AppContext
```

The desktop app and the test-suite use the same function, so tests exercise real
repositories and real SQLite files rather than mocks.

## 4. Eventing and threading

- `SignalBus` (pure Python) publishes domain events (`conversation.created`,
  `message.created`, `activity`, `toast`, …). Subscriber failures are isolated.
- `ui/bridge.py` subscribes to the bus and re-emits **Qt signals**. When a service
  runs on a worker thread (network, compiler, agent — phases 2–4), Qt's queued
  connection delivers the signal on the GUI thread. Widgets are never touched from
  worker threads.
- Long operations are cancellable and report progress through the same bus.

### 4.1 Code Studio execution

```
CodePage ──plan_for()──> Runner ──> ToolchainRegistry (cached detection)
   │                        │
   │  thread: myai-code-run │  subprocess per step, stdout/stderr streamed
   │  cancel_event          │  new session → killpg on timeout/cancel
   └── _RunBridge(Signal) ──┘  queued signals → GUI thread → output panel
```

- `services/toolchains.py` owns what can run: 10 toolchain specs, cached `--version`
  detection with a 6 s probe, `RunPlan`/`RunStep`, and `ToolchainUnavailable` carrying
  the exact missing executable. Compile artifacts go to `<project>/.myai-build`.
- `services/runner.py` executes a plan without a shell, streams each line, enforces the
  wall-clock limit, kills the whole process group, and never exposes the app's API key
  to the child environment.
- `services/projects.py` confines every path to the opened folder (traversal, drive
  letters and symlink escapes are rejected), caps file size, and flags binary files.
- The page only touches widgets on the GUI thread: the worker emits Qt signals through
  a small bridge object, so the interface stays responsive during a 20 s program.

## 5. Data model (schema v4)

| Table | Purpose | Notes |
| --- | --- | --- |
| `conversations` | title, folder, project, model, mode, pin, counts, preview | indexed on `updated_at`, `folder_id`, `project_id` |
| `messages` | role, content, model, status, token counts, JSON meta | cascade delete, ordered by `created_at` + `rowid` |
| `folders` | user folders for conversations | conversations are moved out, never deleted |
| `projects` | project metadata (Code Studio keeps its folder list in settings) | — |
| `settings` | validated key/value JSON registry | secrets never stored here |
| `prompts` | prompt library: title, body, category, tags JSON, source (`builtin` / `user` / `plugin:<id>`), uses | indexed on `category`, `updated_at`, `source` (Phase 5) |
| `task_runs` | one row per finished agent or program run: kind, title, status, detail, model, project, tool count, duration, steps JSON | indexed on `created_at`, `kind` (Phase 5) |
| `attachments` | one row per attached file: name, stored copy, size, kind, mime, extracted characters, truncation and a note | cascade delete with the message, indexed on `message_id` (post-Phase-5) |
| `schema_info` | schema version for migrations | `MIGRATIONS` map in `data/db.py` |

SQLite runs in WAL mode with `foreign_keys=ON` and a busy timeout. Each operation uses
a short-lived session; repositories return detached, fully loaded entities.

## 6. Settings

`services/settings.py` owns typed defaults and validation. Any write:

1. is coerced/validated (ranges, enums, https-only provider URL),
2. persisted in `settings` and applied in memory,
3. triggers side effects (language runtime),
4. published on the bus so views react (theme, layout, scale).

Adding a setting = one entry in `DEFAULTS` (+ a validator if it needs one). No widget
reads configuration files directly.

## 7. Secrets

`security/secrets.py` stores API keys in a single encrypted envelope:

- **Windows:** DPAPI `CryptProtectData`, scoped to the current user account.
- **Other OS:** Fernet with a 0600 key file.
- Atomic writes, `0600` permissions, no secrets in logs/exports/backups,
  name validation to prevent path/format injection.
- **Shape check before use** (`openrouter.api_key_problem`): prefix `sk-or-`,
  printable characters, no whitespace or control characters. A key with `\r\n`
  can therefore never be spliced into the `Authorization` header, and the error
  shown to the user never echoes the value.
- **Redaction at the handler** (`core/redaction.py` + `RedactFilter`): every
  handler (JSON file, console, inspector ring buffer) masks OpenRouter, GitHub
  and `Bearer` tokens, so a mistaken `logger.info("…%s", key)` cannot leak.
- **Proven absent** from the SQLite file, the settings export and the backup
  archive by tests; the store keeps only an encrypted envelope on disk.

## 8. UI construction

- **Design tokens** (`ui/theme/tokens.py`) are plain data — unit-tested without Qt.
- **ThemeManager** generates the application stylesheet from tokens, sets the Qt
  palette and layout direction, and normalises fonts. Switching a theme is one call.
- **Custom painting** goes through `widgets/painting.py::paint_event`, which creates
  the painter, enables antialiasing, logs exceptions and always ends the painter —
  an exception inside `paintEvent` can otherwise crash the process.
- **Runtime theme access** (`ui/theme/runtime.py`) lets small widgets read tokens and
  subscribe to `runtime.signals.changed`.
- **Icons** are SVG paths recoloured per theme and cached by `(name, colour, size)`.

## 9. Error handling

- Expected failures raise `AppError` subclasses carrying a translation key, safe
  details and an optional hint.
- The UI maps them to toasts/dialogs; stack traces go to `logs/myai_studio.jsonl`.
- `sys.excepthook` is installed so an unexpected error shows a diagnostic dialog
  instead of silently killing the window.

## 10. Extension points (used by later phases)

| Extension | Contract |
| --- | --- |
| AI provider | implement the Phase 2 `ChatProvider` protocol (`stream`, `models`, `cancel`) |
| Tool | add a `ToolSpec` to `services/tools.py`: id, JSON schema, risk level, availability check, handler `(ctx, args)`; the registry exposes it to the model and the UI automatically |
| Plugin | `plugin.json` declaring permissions and tools, loaded disabled by default |
| Theme | add a palette dict + accent entry; tokens flow everywhere automatically |
| Language | add `i18n/locales/<code>.json`; RTL is automatic for `fa/ar/he/ur` |
| Migration | append SQL to `MIGRATIONS[version]` and bump `LATEST_SCHEMA` |
| View | add a page to `QStackedWidget` and a route in the sidebar |

## 11. Agent Mode (Phase 4)

```
AgentService.run(task)
  → ChatService.stream_chat(messages, tools=registry.schemas())
  → tool_calls?
      → validate JSON + spec → availability gate → approval (write/execute/network)
      → ToolRegistry.execute(...) on the worker thread
      → ToolResult (stdout/stderr/HTTP body) appended verbatim as a tool message
  → repeat until a final answer, cancel, or agent.max_steps
```

- The loop runs on a worker thread; the page receives `step`, `delta`, `approval` and
  `finished` through queued Qt signals, so the window never blocks on a tool call.
- Approval is a blocking callback **inside** the worker; the UI shows a modal
  `ConfirmDialog` and resolves the request. Cancelling resolves it as denied.
- Unavailable tools never reach the model as runnable: `ToolSpec.reason_key(ctx)` returns
  a translation key plus parameters, rendered in the page and in Settings → Agent.
- `generate_image` is registered with a reason that can never clear — no provider exists.

## 12. Packaging

`packaging/launcher.py` is the frozen entry point (PyInstaller onedir). The build
script runs tests, packages, smoke-tests the real executable, and only then allows
the installer step (Inno Setup). No binary is committed to the repository.

## 13. Phase 5 services

```
AppContext
├── prompts     PromptService(db, bus)                 prompts table, seed-once built-ins
├── tasks       TaskService(db, bus)                   task_runs table
├── performance PerformanceService(paths)              process + /proc + disk_usage + os.walk
├── media       MediaService(paths)                    outputs/images, outputs/videos
├── web         WebService(transport=None)             httpx + HTMLParser extraction
└── plugins     PluginService(paths, settings, prompts) plugin.json discovery, prompt packs
```

- **No service fabricates data.** `WebService.search_available` is `False` because no
  provider is configured; `MediaService.image_provider()`/`video_provider()` return
  `None`; the pages print those facts.
- **Recorder seam.** `AgentService.set_recorder(fn)` is called once in
  `build_context()` with `TaskService.record_agent_run`. Persistence failures are logged
  and never surface as run failures.
- **Performance sampling** is synchronous and cheap (one `os.walk` with a file cap);
  the page owns the 2 s `QTimer` and stops it while hidden.
- **Plugin format.** A folder under `<workspace>/plugins` containing `plugin.json`:
  `id` (must equal the folder name), `name`, `version` (`x.y.z`), `kind` (`prompt_pack`
  is the only executable-free kind), `permissions` (subset of `prompts.write`,
  `library.read`) and `prompts[]` (title, body, category, tags). Nothing is imported or
  executed; code kinds are rejected at load with a translation key.
- **Enable/disable.** Enabling copies prompts into `prompts` with source
  `plugin:<id>`; disabling removes only the copies whose body/category still match the
  manifest, so user edits survive.
- **Schema upgrades.** `create_all` adds the new tables to existing databases, and
  `MIGRATIONS[3]` adds the five indexes; version 3 is written to `schema_info` after the
  migration runs.

## 14. Accessibility contract

- Every page sets an `accessibleName`; shared fields (`SearchField`, `SelectField`)
  derive theirs from the placeholder.
- Interactive controls are tab stops with visible focus rings; modal dialogs trap focus
  and close on Escape.
- `tests/ui/test_accessibility.py` enforces names and Tab/Shift-Tab containment, so a
  new page without labels fails the suite.

## 15. Platform rules (`myai/core/platform.py`)

Everything that differs between Windows 11 and POSIX lives in one module so the
rest of the code stays portable and the Windows **rules** can be tested from
Linux:

| Function | Contract |
| --- | --- |
| `creation_flags()` | `CREATE_NO_WINDOW` on Windows, `0` elsewhere — every child process uses it |
| `decode_output(bytes)` | Never raises. UTF-8/BOM → preferred encoding → cp1252 → cp850 → Latin-1 |
| `filename_problem(name)` | Rejects reserved device names, `<>:"|?*`, trailing dots/spaces and >120 characters on **every** OS, so a project copied to Windows behaves the same |
| `path_problem(parts)` | The same per component, plus the 259-character limit |
| `IS_FROZEN` | A PyInstaller build must take its Python interpreter from PATH, never `sys.executable` |

`tests/unit/test_windows_platform.py` pins all of it; `scripts/check_portability.py`
prints the same checks as a PASS/FAIL table on any machine.

## 16. Attachments (`myai/services/attachments.py`)

```
Composer chip (name + original path)
  → ChatService.prepare_attachments   (worker thread, never the GUI thread)
      → AttachmentService.ingest      validate → copy to <home>/attachments/<hash>_<name>
                                      → extract text (UTF-8/UTF-16/cp1256, docx/xlsx/pptx, image headers)
  → ChatService.build_messages(attachments=…)
      → one fenced block appended to that user turn, capped at 120k characters
  → attachments table row per file, linked to the stored message
```

* The stored message keeps the plain text and the chip metadata, so the bubble
  stays readable and later turns only see `[Attached files: …]`.
* Files without extractable text (PDF, images) are recorded with real metadata
  and an explicit note; nothing pretends the model saw pixels.
* Budgets: 25 MB per file, 8 files per message (composer), 60k characters per file, 120k per message (service).

## 17. Command palette (`myai/ui/widgets/palette.py`)

`Ctrl+Shift+P` opens a modal list built from `MainWindow._palette_actions()`.
Every action calls the same public method the sidebar or menu uses; the palette
owns no state beyond the filter and the selected index. Rows are buttons, but the
highlight is a `selected` dynamic property rather than Qt `:focus`, so it is
visible before the window is activated and does not depend on where the keyboard
focus sits. The search box keeps the focus, ↑/↓ move `_index` with clamping and
scroll the row into view, and Enter runs the selected action (or the first one
when nothing is selected). The list is rebuilt on every keystroke; an empty
result shows the translated empty state instead of an empty box.

## 18. Agent tool suite (`myai/services/tools.py`)

A tool exists only if it has a JSON schema, a risk level, an availability rule
and a real handler. `ToolRegistry` produces both the model-facing descriptions
and the approvals; nothing in the UI invents a capability.

| Group | Tools |
| --- | --- |
| Explore | `list_files`, `read_file`, `read_lines`, `search_files`, `find_files`, `project_map`, `scan_todos`, `diff_files` |
| Edit | `write_file`, `apply_patch`, `make_folder`, `create_project`, `delete_file` |
| Run | `run_file` |
| Remember | `remember`, `recall`, `save_output` |
| Network | `web_search`, `fetch_url`, `github_list_issues`, `github_comment`, `generate_image` (always unavailable) |

`apply_patch` is deliberately all-or-nothing: `services/patches.py` parses the
`@@` hunks, matches exact context (line numbers may drift), and raises before
the caller writes anything. A half-applied file is impossible by construction.
`fetch_url` reuses `WebService.fetch`, so the same URL validation, size cap and
HTML-to-text pass apply on the page and in the agent.

Availability is computed, never stored: a tool with no project, no network
permission, no endpoint, no token or no image provider reports the exact reason
in English (prompt) and in the UI language (`agent.reason_*` keys).

## 19. Windows static gate (`scripts/check_windows_static.py`)

A small AST scanner with one rule per Windows hazard: POSIX-only module at
import time, `subprocess` without `creationflags`, `shell=True`, text I/O
without `encoding`, unguarded `os.fork`/`killpg`/`SIGKILL`, `sys.executable`
used to launch a child, hard-coded POSIX paths. `tests/unit/test_windows_static.py`
feeds each rule a violating snippet and asserts the real `myai/` tree is clean,
so the gate cannot silently turn green.

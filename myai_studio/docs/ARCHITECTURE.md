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

## 5. Data model (schema v1)

| Table | Purpose | Notes |
| --- | --- | --- |
| `conversations` | title, folder, project, model, mode, pin, counts, preview | indexed on `updated_at`, `folder_id`, `project_id` |
| `messages` | role, content, model, status, token counts, JSON meta | cascade delete, ordered by `created_at` + `rowid` |
| `folders` | user folders for conversations | conversations are moved out, never deleted |
| `projects` | project metadata (used from Phase 3) | — |
| `settings` | validated key/value JSON registry | secrets never stored here |
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
| Tool | subclass `agent.tools.Tool` with name, schema, permission level, `run(ctx, args)` |
| Plugin | `plugin.json` declaring permissions and tools, loaded disabled by default |
| Theme | add a palette dict + accent entry; tokens flow everywhere automatically |
| Language | add `i18n/locales/<code>.json`; RTL is automatic for `fa/ar/he/ur` |
| Migration | append SQL to `MIGRATIONS[version]` and bump `LATEST_SCHEMA` |
| View | add a page to `QStackedWidget` and a route in the sidebar |

## 11. Packaging

`packaging/launcher.py` is the frozen entry point (PyInstaller onedir). The build
script runs tests, packages, smoke-tests the real executable, and only then allows
the installer step (Inno Setup). No binary is committed to the repository.

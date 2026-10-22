# Phase 5 report — Ecosystem (v0.5.0)

Phase 5 turned the last five "coming in phase 5" screens into working surfaces and
removed the placeholder entirely: **every route in the sidebar is now a real page**
that reads or writes real data.

> **After this report:** a later hardening pass (Windows 11 rules, real file
> attachments, three file tools, command palette) is documented in
> [`POST_PHASE5_UPGRADE.md`](POST_PHASE5_UPGRADE.md). No phase was renumbered and
> no tag moved.

| Feature | What is real | What is not |
| --- | --- | --- |
| Prompt library | SQLite table, six built-in prompts, create/edit/duplicate/delete, search, categories, tags, use counter, "Use" pushes the body into the composer | No variable substitution engine |
| Task centre | Every finished agent run and every Code Studio program run is persisted with status, model, project, tool count, duration and steps | Only completed runs are recorded (no live queue) |
| Performance monitor | CPU/memory/threads from the running process, RAM and disk from the OS, workspace/database/log sizes from the real files, 2 s sampler | No GPU, no network latency |
| Image Studio | Honest "unavailable" state with the exact reason; a real library of files in `outputs/images` (preview, open, delete) | **No generation** — no image provider exists |
| Video Studio | Same honesty; library for `outputs/videos` | **No generation** — no video provider exists |
| Web research | Direct page reading over HTTP with HTML→text extraction, copy and "save to library" | **No web search** — no search provider is configured |
| Plugins | `plugin.json` manifest discovery, validation with specific errors, permissions, prompt packs start disabled, edited copies survive a disable | **Code plugins are rejected**, never executed |
| Accessibility | Every page, control and dialog has a name; Tab/Shift-Tab never leave the window; Escape closes modals | No screen-reader-driven end-to-end test |

Every number below comes from commands executed **after the last code change**.

---

## 1. Test results

### 1.1 Whole suite (final run, after the last change)

```
$ cd myai_studio && QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=../tools/headless_libs \
    ../.venv/bin/python -m pytest -q
531 passed, 1 skipped in 338.01s (0:05:38)
```

| Layer | Result | Collected |
| --- | --- | --- |
| `tests/unit` | **258 passed, 1 skipped** | 259 |
| `tests/integration` | **14 passed** | 14 |
| `tests/ui` | **259 passed** | 259 |
| **total** | **531 passed, 1 skipped** | **532** |

The single skip is the opt-in live OpenRouter test
(`tests/unit/test_openrouter.py:360`): it needs `MYAI_LIVE_API_KEY` and a working
TLS connection to `openrouter.ai`, neither of which exists in this environment. It
is **not** counted as a pass.

Baseline before Phase 5: **432 passed, 1 skipped**. Phase 5 adds **99 tests**:

| New or extended file | Tests | What it proves |
| --- | --- | --- |
| `tests/unit/test_phase5_services.py` | 22 | prompt seeding/validation/usage, task recording *and* the real agent→task row path, performance maths with injected clocks, plugin enable/disable with edited-copy survival, every manifest error key, media listing/deletion bounds, real HTML extraction over `httpx.MockTransport`, private-address blocking |
| `tests/ui/test_phase5_pages.py` | 25 | all seven routes open, prompt create/use/delete, task filtering/expand/clear, sampler output, auto-refresh timer, honest media labels, real file deletion, web fetch success/save, plugin import and rejection |
| `tests/ui/test_accessibility.py` | 36 | a name for every page/control, Tab and Shift-Tab never escape the window, sidebar tab stops, Escape dismisses a modal |
| `tests/ui/test_ui_matrix.py` (rewritten) | +16 | the matrix now walks all 13 real routes in both languages instead of the old five placeholders |

### 1.2 Commands used

```bash
# environment (rebuilt from scratch in this sandbox)
python3 -m venv .venv
.venv/bin/python -m pip install -r myai_studio/requirements-dev.txt

# headless Qt (system has no libGL)
cd myai_studio && PYTHON=../.venv/bin/python bash scripts/make_headless_libs.sh

# tests
cd myai_studio && QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=../tools/headless_libs \
    ../.venv/bin/python -m pytest -q

# lint
cd myai_studio && ../.venv/bin/ruff check myai tests scripts

# screenshots
cd myai_studio && QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=../tools/headless_libs \
    ../.venv/bin/python scripts/capture_ui.py --out artifacts/ui
```

Logs: `artifacts/logs/full_suite_p5_final.log`, `artifacts/logs/capture_p5_master.log`
(both `EXIT=0`).

---

## 2. What was built

### 2.1 Prompt library — `myai/services/prompts.py`, `myai/ui/views/prompts_page.py`

* Schema **v3** adds `prompts` (title, body, category, tags JSON, source, uses,
  timestamps) and `task_runs`; `MIGRATIONS[3]` adds the five indexes.
* Six built-ins are seeded **only when the table is empty**, so a user who deletes
  one does not get it back on the next launch.
* Source values are `builtin`, `user` and `plugin:<id>`; the card shows a badge for
  each and the plugin id.
* Validation returns translatable keys (`prompts.title_required`,
  `prompts.body_too_long`, …), so the editor shows a localised message instead of
  an English exception.
* "Use" increments `uses` and hands the body to the composer through
  `MainWindow._use_prompt`, which also returns to the chat.

### 2.2 Task centre — `myai/services/tasks.py`, `myai/ui/views/tasks_page.py`

* `AgentService` gained a recorder hook; `AppContext` wires it to
  `TaskService.record_agent_run`. A failing sink is logged and never breaks a run
  (covered by a test that installs a recorder that raises).
* Real Code Studio runs are recorded with their project and duration.
* The page filters by kind, searches title/detail, expands the recorded steps,
  deletes one record or clears history — each behind a confirmation.

### 2.3 Performance monitor — `myai/services/performance.py`,
`myai/ui/views/performance_page.py`

* CPU is `Δprocess_time / Δwall` between samples (share of one core);
  memory is `/proc/self/status` on Linux, `GetProcessMemoryInfo` on Windows and
  `resource` elsewhere; system RAM from `/proc/meminfo` or `GlobalMemoryStatusEx`;
  disk from `shutil.disk_usage`.
* When a platform cannot report a value the tile says **n/a** and the page explains
  which metric is missing. A synthetic-clock unit test proves the arithmetic.
* Workspace size walks real files with a 20 000-file cap and says so when truncated.
* A 2 s timer refreshes only while the page is visible; a switch turns it off.

### 2.4 Image Studio and Video Studio — `myai/services/media.py`,
`myai/ui/views/media_page.py`

* Both pages open with a **status card**: `Unavailable` badge, `No provider`
  badge, a disabled Generate button whose tooltip explains why, and the exact
  sentence (`IMAGE_PROVIDER_NOTE` / `VIDEO_PROVIDER_NOTE`).
* The library lists real files from `outputs/images` / `outputs/videos` with size,
  date, thumbnail (images) and open/delete actions. Deletion refuses paths outside
  `outputs/`.

### 2.5 Web research — `myai/services/web.py`, `myai/ui/views/web_page.py`

* Search is **disabled and labelled**: `WebService.search_available` is `False`
  because no search provider exists; the page prints that instead of faking a
  result list.
* Reading a page is real: one `httpx` request with a 20 s timeout, 2 MB cap,
  redirects followed, title and block text extracted by a small `HTMLParser`
  subclass (`script`, `style`, `nav`, `form` … dropped).
* `validate_url` refuses non-HTTP schemes, missing hosts and private/loopback
  addresses (literal check plus `getaddrinfo`); the tests cover `localhost`,
  `127.0.0.1`, `192.168.1.5` and `file://`.
* The result can be copied or saved as a Markdown output with its source URL.

### 2.6 Plugins — `myai/services/plugins.py`, `myai/ui/views/plugins_page.py`

* A plugin is a folder in `<workspace>/plugins` with `plugin.json`.
* Validation covers: missing manifest, invalid JSON, bad id, id ≠ folder name, bad
  version, unknown permission, unknown kind, code kinds (rejected by design), no
  usable prompts. Each failure maps to a translation key and is displayed.
* Permissions are an allow-list (`prompts.write`, `library.read`); anything else
  rejects the manifest.
* Every plugin starts **disabled**; enabling imports its prompts with source
  `plugin:<id>`; disabling deletes the copies the user has not edited and reports
  how many edited copies were kept.
* "Create example" writes a working two-prompt pack so the format is discoverable.
* Nothing is executed: there is no import of plugin code anywhere.

### 2.7 Accessibility

* Every page exposes `accessibleName()`; every focusable control has a name from
  its text, accessible name or tooltip.
* Tab and Shift-Tab are simulated for 40/20 presses on five routes and never leave
  the window; sidebar entries are tab stops; Escape closes a modal dialog.
* Shared widgets (`SearchField`, `SelectField`) now derive their accessible name
  from their placeholder, so the whole app improved, not only the new pages.

### 2.8 Cleanup that Phase 4 left open

| Item | Fix |
| --- | --- |
| Header pill showed **Chat** on the agent page | `_show_ai_page` sets `agent` for the agent route; all Phase-4 agent shots were recaptured |
| Prompt bodies rendered `{{diff}}` | Built-ins and the example pack use single-brace placeholders |
| Plugin disable confirmation was inverted (`exec() != 0`) | Compares against `QDialogCode.Accepted`; the UI test proves disable now removes rows |
| `1 files`, `1 tool calls` | Plural keys (`images.count.one/many`, `plugins.*_count.*`) and a wording change for tool counts |
| `0s` for sub-second runs | Shows milliseconds below one second |
| Prompt editor had no RTL/LTR handling | `auto_direction()` on the body editor |
| Placeholder pages | Module deleted; matrix test now covers 13 real routes |

---

## 3. Screenshots

`scripts/capture_ui.py` now seeds real Phase-5 data (task rows, the example plugin
with two imported prompts, one image and one video file) and captures the seven
library pages in **fa/midnight, fa/dawn, en/midnight, en/dawn**, plus the prompt
editor dialog.

* `artifacts/ui/` — **84 PNGs**, of which **29** are Phase-5 (`p5_*.png`).
* Reviewed: prompts (fa/en, both themes), tasks, performance, images, video, web,
  plugins, prompt editor. Persian pages are right-to-left; English pages are
  left-to-right; no clipped badges, no overlapping cards, the dialog composites
  over a dimmed backdrop.

---

## 4. What is incomplete

1. **Live OpenRouter call** — not executed: `openrouter.ai` is unreachable from
   this sandbox (TLS handshake fails) and no key is configured. All provider tests
   use scripted clients and are labelled as such.
2. **Windows EXE and installer** — not built here. `scripts/build_windows.ps1`
   (PyInstaller onedir + optional Inno Setup), `packaging/launcher.py` and
   `packaging/myai_studio.iss` exist and agree on their paths, but this sandbox has
   no PowerShell and is not Windows, so **no EXE is delivered**. A packaging attempt
   was made on Linux as a configuration check and failed for an environment reason,
   not a project one: `PyInstaller.exceptions.PythonLibraryNotFoundError: Python
   library not found: libpython3.11.so` (the host Python is built without
   `--enable-shared`). The Windows script therefore remains **unverified**; it must
   be run on Windows 11 before any `.exe` is claimed.
3. **Web search** — no provider, therefore disabled. Reading a pasted URL works.
4. **Image and video generation** — no provider, therefore unavailable; only the
   library is real.
5. **Backup restore** — backups are created (database + settings, which now include
   prompts and task history) but automatic *restore* is still not implemented; a
   user restores by replacing `workspace.db` from the zip.
6. **Plugins that execute code** — rejected by design; only prompt packs load.
7. **Prompt variables** — placeholders are stored and shown but not substituted at
   send time.

---

## 5. Changed files

New:

| File | Lines |
| --- | --- |
| `myai/services/prompts.py` | 314 |
| `myai/services/tasks.py` | 191 |
| `myai/services/performance.py` | 292 |
| `myai/services/plugins.py` | 347 |
| `myai/services/media.py` | 117 |
| `myai/services/web.py` | 229 |
| `myai/ui/views/prompts_page.py` | 390 |
| `myai/ui/views/tasks_page.py` | 273 |
| `myai/ui/views/performance_page.py` | 296 |
| `myai/ui/views/plugins_page.py` | 204 |
| `myai/ui/views/media_page.py` | 243 |
| `myai/ui/views/web_page.py` | 219 |
| `tests/unit/test_phase5_services.py` | 430 |
| `tests/ui/test_phase5_pages.py` | 430 |
| `tests/ui/test_accessibility.py` | 148 |

Modified: `myai/version.py`, `myai/context.py`, `myai/core/events.py`,
`myai/data/models.py`, `myai/data/db.py`, `myai/services/agent.py`,
`myai/services/settings.py`, `myai/ui/main_window.py`, `myai/ui/views/sidebar.py`,
`myai/ui/views/{agent,api,code,memory,output,persona}_page.py`,
`myai/ui/widgets/fields.py`, `myai/i18n/locales/{en,fa}.json` (812 → 1006 keys),
`scripts/capture_ui.py`, four existing test files.

Deleted: `myai/ui/views/placeholder.py`.

---

## 6. Remaining issues and limits

* The activity feed in the sidebar still prints English tool text inside the
  Persian UI (`Agent run: ok · 1 tool calls`); it is a Phase-4 surface and was not
  translated in this phase.
* CPU percentage on the first sample after launch can read high because the window
  is still building; later samples settle.
* A plugin folder is not part of a backup (only `workspace.db` and settings are).
* Task history grows without a retention policy; "Clear" is manual.
* The performance page shows the process, not the whole machine; system CPU/RAM
  per core is not read.

---

## 7. Verification checklist

| Requirement | Evidence |
| --- | --- |
| Real tests per feature | 99 new tests; 531 total pass |
| No display-only page | Seven routes exercised through their handlers; placeholder deleted |
| Honest labels | Image/video/web-search states assert `Unavailable` in tests and appear in screenshots |
| Disabled by default plugins | `test_plugin_example_is_written_disabled_and_can_be_enabled` |
| Data survives restart | Stored in SQLite (schema v3); the app-level persistence tests cover reopen |
| Keyboard access | 36 accessibility assertions |
| Lint | `ruff check myai tests scripts` → clean |
| Screenshots | 84 PNGs, 29 from Phase 5, fa+en × both themes |
| No live claims | Live provider test skipped and reported as such |
| Packaging honesty | PyInstaller attempt failed with `PythonLibraryNotFoundError` (host Python lacks a shared libpython); no EXE is claimed |

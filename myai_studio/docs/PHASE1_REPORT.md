# Phase 1 Report — Foundation (final)

**Version:** 0.1.0 · **Date:** 2026-10-20 · **Status:** ✅ Complete — acceptance criteria verified
**Project path:** `/home/user/AISystemOptimizer/myai_studio`
**Test command:** `cd myai_studio && ./scripts/run_tests.sh -q`

---

## 1. Verification summary (measured, this run)

| Item | Result |
| --- | --- |
| Full suite | **148 tests collected → 148 passed, 0 failed, 0 skipped** |
| Lint (`ruff check myai tests scripts`) | **All checks passed** |
| Compile check (all 60 modules) | passes (`py_compile`) |
| Clean-install run (fresh venv, `pip install -r requirements.txt`) | exit code 0, screenshot written, 184 KB PNG |
| Headless smoke run | `window_shown version=0.1.0` → `app_shutdown`, exit 0 |
| Screenshots produced | **15** (real renders, see §5) |
| Live OpenRouter API test | **not performed** — network blocked (Phase 2) |

---

## 2. Capabilities really implemented

### Application shell
- Three-column responsive layout (sidebar · header+thread+composer · inspector), RTL-aware.
- Collapsible sidebar rail (88 px) with icon buttons, persisted state.
- Inspector panel with model, context, session, health, activity, files and memory cards,
  rebuilt on conversation switch, theme change and language change.
- Command-palette style favourites, keyboard shortcuts: `Ctrl+N`, `Ctrl+K`, `Ctrl+Shift+C`,
  `Ctrl+,`, `Esc`.
- Window geometry, inspector visibility and sidebar state persist across restarts.
- Single-instance lock per workspace (`QLockFile`), `--allow-multi` to bypass.

### Design system
- Design tokens for 3 themes (midnight, dawn, aurora) × 5 accents, all as data.
- Generated Qt stylesheet; no hard-coded colours in widgets.
- ~80 hand-drawn vector icons, one visual family, no emoji.
- Custom painted navigation, toggles, send button, meters, previews, cards.
- Light/dark/system themes switch live without restart; verified by pixel sampling in tests.

### Internationalisation
- Persian (default, RTL) and English (LTR); 381 catalogue keys per language, key-parity enforced by tests.
- Instant switch across every surface, including the inspector header, activity feed,
  composer hints and error messages.
- Jalali dates, Persian digits in badges, Vazirmatn + Inter bundled (SIL OFL).
- A test asserts that no raw translation key can ever be rendered.

### Data and services
- SQLite (WAL, foreign keys, schema version 1, migration hook), repositories for
  conversations, messages, folders, projects, settings.
- Conversation CRUD, pinning, folders, search, cascade delete, Markdown export.
- Message ordering guaranteed by microsecond timestamps + `rowid` tiebreaker.
- Settings registry with validation, live side-effects and atomic persistence.
- Encrypted secret store: DPAPI on Windows, Fernet + `0600` key elsewhere; never in
  backups, logs or exports.
- JSONL structured logging with rotation + in-app activity feed.
- Zip backups (database + non-sensitive settings + manifest), retention policy.

### Quality gates
- 148 tests: unit (65), UI on real widgets (73), integration (10).
- Crash-proof painting: every custom `paintEvent` runs through a guard that always ends
  the painter (an exception inside paint used to segfault the process).
- Architecture tests: core/services/security/data must not import Qt.

### Packaging & operations
- `scripts/build_windows.ps1`: installs requirements, **runs the tests**, packages with
  PyInstaller, **smoke-tests the produced .exe**, optional Inno Setup installer.
- `run_windows.bat` / `run_windows.ps1`: one-click launcher that provisions `.venv` on
  first use.
- App icons generated from the vector mark (10 PNG sizes + multi-resolution `.ico`).
- Persian user guide, install guide, architecture and testing docs.

---

## 3. Bugs found by testing in this phase (and fixed)

Each of these was reproduced, fixed, and covered by a regression test.

| # | Defect | How it was found | Fix |
| --- | --- | --- | --- |
| 1 | Exception inside `paintEvent` → **process segfault** | theme-switch test crashed pytest | `widgets/painting.py` guard + 30 paint methods migrated |
| 2 | `self.done` widget on a `QDialog` shadowed Qt's virtual method → crash in `reject()` | settings-dialog teardown | renamed to `close_button` |
| 3 | `QPen(...)` parenthesis bug in ToggleSwitch → paint exception | crash on settings page | corrected expression |
| 4 | Fernet tokens decoded as base64 twice → `SecretBackendError` | secret reload test | decode only for DPAPI |
| 5 | Backup filenames collided within one second | retention test kept 1 of 3 | microsecond stamp + uniqueness loop |
| 6 | Messages in the same second sorted randomly | ordering test | microsecond timestamps + `rowid` |
| 7 | Window size rejected at large font scale | close-event test | independent width/height bounds + clamp |
| 8 | `--lang` / `--theme` silently ignored | CLI subprocess test | overrides applied **after** `boot()` |
| 9 | Second instance hung on a modal dialog | lock test timed out | log + stderr message, exit immediately |
| 10 | Backdrop fade crashed on dialog close | settings test | replaced effect+animation with a value-animated overlay |
| 11 | 96 missing translation keys rendered as raw keys | screenshot review | catalogue completed + parity tests |
| 12 | Missing icons drew in magenta fallback | screenshot review | short name → palette token aliases |
| 13 | Activity feed stayed in the old language | screenshot review | events store translation keys |
| 14 | Inspector cards overflowed a 360 px panel as 640 px zombies | layout matrix test | detach from parent before `deleteLater()` |
| 15 | Inspector header not retranslated | English screenshot | `Inspector.retranslate()` |
| 16 | Trust chips clipped English labels | English screenshot | chip width recomputed from text |
| 17 | Model chip text drawn under the sparkles icon and elided to "Mo…" | screenshot review | glyph-aware text span, no icon on compact chip |
| 18 | Collapsed sidebar clipped icons into slices | screenshot review | rail widened to 88 px, sizes fixed |
| 19 | Theme preview captions invisible on light cards | settings screenshot | caption uses the preview palette |
| 20 | `SelectField` ignored RTL when laying out text | RTL screenshot | RTL-aware text span |

---

## 4. UI states verified

| Dimension | Values exercised |
| --- | --- |
| Language | Persian (RTL), English (LTR) |
| Theme | midnight (dark), dawn (light), aurora (dark) |
| Accent | azure, violet, teal, amber, rose (accent test) |
| Sidebar | expanded, collapsed |
| Window size | 1280×720, 1366×768, 1440×900, 1920×1080, 2560×1440, 3840×2160 |
| Font scale / DPI | 1.0 and 1.25 (emulated HiDPI), geometry asserted at 1366×768 |
| Screens | welcome, conversation thread, collapsed rail, 7 phase-locked routes, settings (9 categories), confirm dialog |
| Dialogs | confirm (destructive), settings — appearance, language, data, shortcuts, about |
| Interactions | typing, Enter/Shift+Enter, send, conversation switch, rename, pin, folder, delete, export, theme switch, language switch, accent switch, inspector toggle, toast lifecycle |

Automated coverage of this matrix lives in `tests/ui/test_ui_matrix.py` (26 parametrised
cases) and `tests/ui/test_main_window.py` (28 cases).

---

## 5. Screenshots (real application renders, `artifacts/ui/`)

| File | Shows |
| --- | --- |
| `01_welcome_midnight_fa.png` | dark theme, Persian RTL, welcome |
| `01_welcome_midnight_en.png` | dark theme, English LTR |
| `01_welcome_dawn_fa.png` / `_en.png` | light theme, both directions |
| `02_conversation_dark_fa.png` | message thread, phase notice, activity feed |
| `03_sidebar_collapsed_fa.png` | collapsed icon rail |
| `04_conversation_dawn_fa.png` | light theme conversation |
| `04_conversation_aurora_fa.png` | third theme |
| `05_conversation_dark_en.png` | English conversation |
| `06_route_code_en.png` | phase-locked route with explicit badge |
| `07_size_1280x720_en.png`, `07_size_1920x1080_en.png` | responsive layouts |
| `08_confirm_dialog_fa.png` | destructive confirmation |
| `09_settings_appearance_fa.png` | theme + accent pickers |
| `10_settings_language_fa.png` | language selection |

Regenerate: `python scripts/capture_ui.py --out artifacts/ui`

---

## 6. Environment limitations (stated honestly)

| Limitation | Effect | Mitigation |
| --- | --- | --- |
| Linux container, no display server | Qt runs with `QT_QPA_PLATFORM=offscreen` and shim libs (`tools/headless_libs`) | Widgets are still real; rendering is real; tests assert geometry and pixels |
| No Windows host | DPAPI path, real `.exe`, installer, physical HiDPI not executed | Code paths implemented; `build_windows.ps1` performs the packaging + smoke test on Windows |
| `openrouter.ai` unreachable | no live API call possible | Phase 2 network tests will be labelled "not live-tested" |
| Java/.NET/Go/Rust toolchains absent | compiler matrix incomplete in Phase 3 | will be detected at runtime and reported as unavailable |
| PyInstaller not installable here (no build host) | no binary produced | script exists; no fake `.exe` is committed |

---

## 7. Known gaps at the end of Phase 1

- No AI replies, no model catalogue, no memory — Phase 2.
- No Code Studio, no compilation — Phase 3.
- No agent tools, web search, media, GitHub — Phases 4–5.
- DPAPI secret backend untested on real Windows.
- Physical HiDPI rendering (200 % scaling) unverified.

---

## 8. Reproduce this result

```bash
cd /home/user/AISystemOptimizer/myai_studio
./scripts/run_tests.sh -q              # 148 passed
../.venv/bin/python -m ruff check myai tests scripts   # clean

# real UI render (15 screenshots)
LD_LIBRARY_PATH=../tools/headless_libs QT_QPA_PLATFORM=offscreen \
  ../.venv/bin/python scripts/capture_ui.py --out artifacts/ui

# application smoke run
LD_LIBRARY_PATH=../tools/headless_libs QT_QPA_PLATFORM=offscreen \
  ../.venv/bin/python -m myai --home /tmp/ws --smoke --allow-multi
```

On Windows, without any shim:

```powershell
.\run_windows.ps1
.venv\Scripts\python -m pytest -q
```

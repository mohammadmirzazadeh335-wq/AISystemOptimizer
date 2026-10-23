# Final debug report — MyAI Studio Ultimate 0.7.3

This round was a whole-application debug pass, followed by a real Windows build
published on GitHub. Everything below was executed or observed; nothing is
projected from intent.

## 1. How the pass was run

| Layer | What was actually run |
| --- | --- |
| Full local suite | `pytest -q` on the Linux development host: **831 passed, 1 skipped in 554 s** (the skip is the live OpenRouter test, which needs a key and an internet route this sandbox does not have) |
| Static gates | `ruff check myai tests scripts` → clean; `scripts/check_windows_static.py` → "No platform hazard found"; `scripts/check_portability.py` → **17/17** |
| Visual pass | 14 fresh frames of the three new surfaces at midnight/dawn × fa/en, plus a 1.5× Persian frame; the sidebar, Usage, search and history were read and corrected from those frames |
| Layout stress | `QScrollArea.horizontalScrollBar().maximum()` = 0 at 1.5×1440×900 (viewport 490 px), 1.5×1120×720 (363 px), 1.25×1120×720 (370 px), 1.0×1440×900 (792 px) |
| Windows build | GitHub Actions runs on `windows-latest`: PyInstaller build, packaged smoke run, zip published as a release asset |
| Windows tests | run `39931204558`: the **"Run the test suite" step finished successfully** (12 min 28 s, pytest exit code 0). The job was still marked red because the extra annotation-report step of mine crashed; that step is diagnostics-only now (`39931204558` → step 5 success, step 6 failure) |

## 2. Defects found in this pass and what changed

| Symptom | Root cause | Fix | Proof |
| --- | --- | --- | --- |
| Three history rows all read "Save · just now" | relative wording has a one-minute floor, and the capture wrote three versions inside one second | rows carry `hh:mm:ss` when the version is younger than ten minutes; the dialog reuses one label helper for list and diff headers | frames `r3_history_*` show 09:03:20 / 09:03:19 / 09:03:18 |
| Diff column header showed a raw snapshot id (`1792747318912-save`) | the dialog passed `snapshot.id` as the column name | both headers use human labels ("current" / "Save · 09:03:18") | `r3_history_*` |
| A restored file could be recorded as a plain "save" | `restore` wrote through a project service that may have no history attached | restore tags its own snapshot; `record` de-duplicates so nothing doubles | `test_restore_writes_the_file_and_records_itself` |
| Persian search rows showed a Latin "line 7" badge | the badge text was assembled inside the service | the widget formats `search.line` from `hit.extra["line"]` | `r3_search_midnight_fa` shows "خط ۷" |
| "Save key" stayed clickable with an empty box, then only complained | the button state ignored the input | disabled until a key is typed, re-synced on clear | `test_api_key_save_and_delete` + scripted probe (False → True → False) |
| At the navigation fold the column ended on a half row and a lone chevron | the scroll affordance was a bare glyph over a fade | the chevron now sits in a rounded pill that appears only while content remains | `r3_usage_*`, `r3_code_*` |
| The big cost figure sat on the left in Persian | a plain `QLabel` does not mirror a currency string | alignment follows `is_rtl()` | `r3_usage_midnight_fa_scale1_5` |
| The shipped `RUNNING.txt` and three documents pointed at `%USERPROFILE%\.myai_studio` | the text was written from memory, not from `paths.py` | `%APPDATA%\MyAIStudio`; projects default to `Documents\MyAI Studio Projects` | `myai/core/paths.py::_default_home` |
| Windows test job went red with no readable reason | the JUnit parser crashed on an incomplete report, and runner logs are not reachable from this sandbox | the report step cannot raise, falls back to `pytest.log`'s `FAILED` lines, and writes the list to `ci-failures.txt` (pushed to the `ci-reports` branch when possible) | `scripts/ci_report_failures.py` + a fabricated report test |

## 3. The Windows artefact

- Workflow: `.github/workflows/windows-build.yml` — a tests job (full suite, annotations) and a build job (PyInstaller 6.12 onedir, icon, locales, assets, packaged `--smoke --allow-multi`, zip, release).
- Release: [`v0.7.3`](https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer/releases/tag/v0.7.3), asset `MyAIStudio-v0.7.3-windows-x64.zip` (≈59 MB).
- Direct download: <https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer/releases/download/v0.7.3/MyAIStudio-v0.7.3-windows-x64.zip>
- Data folder on Windows: `%APPDATA%\MyAIStudio`; projects: `Documents\MyAI Studio Projects`.

## 4. What this round did NOT verify

- **No human click-through on a real Windows desktop.** The executable was smoke-started on the runner (build job success) and the GUI was driven here only under Qt's `offscreen` platform.
- **The live model path was not exercised**: no OpenRouter key, and `openrouter.ai` is unreachable from this sandbox; the one test that needs a key is skipped by design.
- **The artefact is not code-signed**, so SmartScreen warns on first launch.
- **The zip was not downloaded back into this sandbox** — `objects.githubusercontent.com` is blocked here. The evidence for it is the CI smoke run, the artifact upload step and the release asset (62,275,774 bytes).
- The **Windows test job's** result for this exact tag is stated in the release notes and in the hand-over message; it is not inferred from the Linux run.

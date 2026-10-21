# Phase 3 report — Code Studio (v0.3.0)

Phase 3 turns the Code Studio placeholder into a working file/run surface: open a real
folder, edit a real file, run it with the toolchain that is really installed, read the
command's own stdout/stderr and exit code, and see the compiler's own error text when a
build fails. When a toolchain is absent the page names the missing executable; it never
fakes a run.

This report follows the seven required sections. Every number below comes from a command
that was actually run on this machine, after the final code change.

---

## 1. Test results

### 1.1 Full suite (final run, after the last change)

```
$ cd myai_studio && ./scripts/run_tests.sh -q
319 passed, 1 skipped in 122.23s (0:02:02)
```

| Layer | Result | Time |
| --- | --- | --- |
| `tests/unit` | **156 passed, 1 skipped** | 3.92 s |
| `tests/integration` | **14 passed** | 0.60 s |
| `tests/ui` | **149 passed** | 113.85 s |

The single skip is the opt-in live OpenRouter test
(`tests/unit/test_openrouter.py:360`), which needs `MYAI_LIVE_API_KEY` and a reachable
`openrouter.ai` — neither exists in this sandbox. It is **not** counted as a pass.

Baseline before Phase 3: 264 passed, 1 skipped in 81.31 s. Phase 3 adds **57 tests**
(28 service + 29 page). The placeholder matrix lost its two `code` cases because that
route is a real page now, so the net change is **+55** (264 → 319). Two Phase-2 tests
were updated rather than removed: the route test now asserts the real page, and the i18n
placeholder list no longer expects `placeholder.code_*` keys.

### 1.2 Phase-3 suites on their own

```
$ ./scripts/run_tests.sh tests/unit/test_code_services.py -q
28 passed in 2.19s

$ ./scripts/run_tests.sh tests/ui/test_code_studio.py -q
29 passed in 26.48s
```

`tests/unit/test_code_services.py` exercises the services without Qt:
toolchain detection, plan construction, real `python` execution, real `gcc`
compile + run, real `node` execution, compiler errors surfaced verbatim, timeout
kill, cross-thread cancel, API keys stripped from the child environment, and the
`ProjectService` guards (path traversal including `C:\...`, symlink escape, binary
files, size limits, recent-project bookkeeping).

`tests/ui/test_code_studio.py` drives the real window on the offscreen platform:
routing, real folder listing, open/save round trips, dirty-state semantics, autosave,
file switch (which saves first), run/stop/non-blocking, compile errors, missing
toolchain, new/rename/delete through the real dialogs (monkeypatched only at the
`QInputDialog.getText` boundary), and language/theme/font-scale rebuilds that keep the
open file and unsaved text.

`ruff check myai tests scripts` → **All checks passed!**

### 1.3 Commands used

```bash
cd myai_studio
./scripts/run_tests.sh -q                      # everything
./scripts/run_tests.sh tests/unit -q
./scripts/run_tests.sh tests/ui -q
../.venv/bin/ruff check myai tests scripts
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=../tools/headless_libs \
  ../.venv/bin/python scripts/capture_ui.py --out artifacts/ui
```

---

## 2. What is done (verified by execution)

| Capability | State | Evidence |
| --- | --- | --- |
| Code Studio is a real route (`code` in `AI_ROUTES`, sidebar, `Ctrl+Shift+C`, window title) | **Works** | `test_code_page_is_a_real_route`, `06_code_studio_run_en.png` |
| Open a real folder (native picker) and list its real tree | **Works** | `test_opening_a_folder_lists_real_files` |
| Create a project under the workspace, recent-projects memory, last project restored on start | **Works** | `ProjectService` + page tests, restart via settings |
| Open a file, edit, save to the same path (`Ctrl+S`), autosave 2.5 s after typing stops | **Works** | `test_edit_and_save_writes_the_real_file`, `test_autosave_writes_after_the_timer` |
| Dirty indicator is content-based (a syntax re-highlight is not an edit) | **Works** | `test_reverting_the_text_clears_the_dirty_flag` |
| Switching files saves the pending edit first | **Works** | `test_switching_files_saves_the_pending_edit` |
| Syntax highlighting (10 language families) and line numbers | **Works** | visible in every `p3_*` screenshot |
| Run with the toolchain detected on this machine | **Works** | `test_run_a_python_file_for_real`, `test_c_compiles_and_runs` |
| Real stdout, stderr, exit code and duration in the output panel | **Works** | `$ /usr/bin/python3.11 -u hello.py` → `Hello, world!` / `Exit 0 · 33 ms` |
| Compiler errors shown verbatim, with the compiler's own file:line | **Works** | `broken.c:5:5: error: 'retrun' undeclared …` in `p3_code_compile_error_dawn_en.png` |
| Non-zero exit is reported, not hidden | **Works** | `test_non_zero_exit_is_reported` (exit 3, red badge) |
| Missing toolchain reported with the exact executable | **Works** | `javac and java not found on PATH (Java needs javac to compile and java to run)` |
| Stop a running program (process group kill) | **Works** | `test_stop_kills_a_long_run`, cancelled in ~3 s |
| GUI never blocks during a run | **Works** | `run_current()` returns in < 0.5 s while a 20 s script runs (`test_run_does_not_block_the_ui`) |
| Wall-clock limit (default 10 s, 1–120 s) | **Works** | `test_timeout_kills_a_long_run` (services) |
| Upload/sandbox safety: files never leave the folder, symlinks and traversal rejected | **Works** | `ProjectService` guard tests |
| API keys never reach the child process | **Works** | `test_child_env_has_no_api_key` |
| New file / rename / delete through the page, with real dialogs | **Works** | `test_new_file_through_the_dialog`, `test_rename_and_delete_update_disk_and_tree` |
| Toolchain inspector: what is ready, what is not, and why | **Works** | `p3_code_unavailable_midnight_fa.png` (details expanded) |
| Persian RTL + English LTR, three themes, 1.25×/1.5× DPI | **Works** | 8 new screenshots, all reviewed |

### 2.1 Toolchains on this machine

| Toolchain | Detected | Version / reason |
| --- | --- | --- |
| Python | yes | 3.11.2 (runs with the application's own interpreter) |
| Node.js | yes | v22.22.3 |
| C | yes | gcc 12.2.0 |
| C++ | yes | g++ 12.2.0 |
| Bash | yes | 5.2.15 |
| Java | **no** | `javac and java not found on PATH` |
| .NET | **no** | `dotnet was not found on PATH` |
| Go | **no** | `go was not found on PATH` |
| Rust | **no** | `rustc was not found on PATH` |
| PowerShell | **no** | `pwsh was not found on PATH` |

The five unavailable toolchains are exercised through their honest failure path
(`p3_code_unavailable_midnight_fa.png`); they are **not** claimed as tested runners.

---

## 3. Also fixed in this phase (found during the screenshot review)

- **FlowLayout did not reparent its children.** `FlowLayout.addWidget()` built a
  `QWidgetItem` by hand, so buttons added to it kept no parent and were never painted.
  The Output Studio action row (Save / Format JSON / Export / Delete) had been invisible
  since Phase 2. `addWidget()` now goes through `QLayout::addWidget`; every regenerated
  Phase-2 screenshot shows the buttons, and the new `p2_scale_1_5_studio_en.png` proves
  the row wraps instead of clipping at 1.5×.
- **Dangling layout items crashed the process.** When a page rebuild deleted the widgets
  of a FlowLayout, Qt deleted their `QWidgetItem`s while the Python list still held the
  wrappers; the next layout pass segfaulted. `FlowLayout` now prunes dead items
  (`shiboken6.isValid`), forgets them before deletion (`detach_items`), and
  `PageShell` detaches a container's layout before deleting it.
- **The header action row could not live beside the explanation.** With five actions it
  wrapped into a vertical column and pushed the workspace down. `PageShell` gained
  `actions_below=True`, which Code Studio uses: one wrapped row under the subtitle, in
  both directions and at every scale.
- **`python_executable()` kept the launch spelling** (`…/myai_studio/../.venv/bin/python`),
  which appeared verbatim in the command line. It now returns the real path.
- **Scroll-based pages hid their right edge at 1.5×.** At 1.5× font scale on a
  1120×720 window the card column of the API/Memory/Persona/Output pages is 824 px wide
  in a 698 px viewport, and the horizontal bar was suppressed, making part of the
  content unreachable. `PageShell` now uses `ScrollBarAsNeeded`: nothing is hidden at
  any scale, and no bar appears when the content fits.
- **The settings' Autosave toggle did nothing.** `ui.editor_autosave` now really controls
  Code Studio's autosave, and its label/hint say exactly what it does.

---

## 4. What is not done

| Gap | Why / what it means |
| --- | --- |
| **No interactive debugger** | There are no breakpoints, watches or single-stepping. The "debug loop" implemented here is the real one a compiler gives you: run → read the compiler's own diagnostics → fix → run again. No debugger is simulated. |
| Java / .NET / Go / Rust / PowerShell runs are unverified | Those toolchains are absent on this machine; only the unavailable path is proven. Installing them needs a real Windows toolchain set and is out of scope for this build host. |
| No test runner inside the page | Running `pytest` from the UI is not implemented; only the current file runs. |
| No per-file timeout control in the UI | `code.timeout_seconds` is validated and used (1–120 s, default 10) but has no settings row yet. |
| No multi-root workspace | One folder at a time; sub-folders are navigable, other disks are not mounted. |
| No source-control integration inside Code Studio | Diff/restore exists in Output Studio only. |
| Live OpenRouter calls still untested here | Unchanged from Phase 2: `openrouter.ai` is unreachable from this sandbox (`curl: (35) SSL_ERROR_SYSCALL`) and no key is present. Phase 3 did not retest it live and does not claim to have. |

---

## 5. Real execution evidence (verbatim)

```
$ cd myai_studio && ./scripts/run_tests.sh tests/unit/test_code_services.py -q
28 passed in 2.19s

$ ./scripts/run_tests.sh tests/ui/test_code_studio.py -q
29 passed in 26.48s

$ ./scripts/run_tests.sh -q
319 passed, 1 skipped in 122.23s (0:02:02)
```

Run of `hello.py` through the page (screenshot `p3_code_dawn_en.png`):

```
$ /usr/bin/python3.11 -u hello.py
Hello, world!
Hello, code studio!
Exit 0 · 34 ms
```

Compile failure of `broken.c` (screenshot `p3_code_compile_error_dawn_en.png`):

```
$ /usr/bin/gcc -O0 -g -Wall -Wextra -o …/.myai-build/broken broken.c
broken.c: In function 'main':
broken.c:5:5: error: 'retrun' undeclared (first use in this function)
    5 |     retrun 0;
      |     ^~~~~~
broken.c:5:5: note: each undeclared identifier is reported only once for each function it appears in
broken.c:5:11: error: expected ';' before numeric constant
Exit 1 · 33 ms
```

Missing toolchain (screenshot `p3_code_unavailable_midnight_fa.png`):

```
این فایل روی این دستگاه اجرا نمی‌شود:
javac and java not found on PATH (Java needs javac to compile and java to run)
```

---

## 6. Changed files

New:

```
myai/services/toolchains.py        detection, versions, RunPlan, ToolchainUnavailable
myai/services/runner.py            worker-safe execution, output capture, timeouts, cancel
myai/services/projects.py          folder tree, read/write, create/rename/delete, guards
myai/ui/views/code_page.py         the whole Code Studio surface
tests/unit/test_code_services.py   28 service tests
tests/ui/test_code_studio.py       29 page tests
docs/PHASE3_PLAN.md                the plan this phase was built against
docs/PHASE3_REPORT.md              this report
docs/PHASE3_REPORT_FA.md           گزارش فارسی
```

Modified:

```
myai/ui/main_window.py             route registration, PAGE_TITLES, page wiring
myai/ui/views/page_base.py         scroll/stretch/actions_below, safe widget disposal
myai/ui/views/placeholder.py       "code" removed from phase-locked routes
myai/ui/widgets/fields.py          FlowLayout: real parenting, dead-item pruning, detach
myai/services/settings.py          code.* defaults and validation
myai/i18n/locales/en.json          +51 keys, autosave wording
myai/i18n/locales/fa.json          +51 keys, autosave wording
myai/version.py                    0.3.0, PHASE 3
scripts/capture_ui.py              demo project, run/wait steps, 8 Phase-3 screenshots
tests/unit/test_i18n.py            placeholder list follows the new route set
tests/ui/test_main_window.py       code route now asserts the real page
artifacts/ui/*.png                 regenerated (43 images; 8 new p3_* + 06_code_studio_run_en)
README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/TESTING.md
```

No new third-party dependency was added; `requirements.txt` is unchanged.

---

## 7. Remaining issues and limits

1. **No debugger.** If the acceptance criterion "debug" means step-through debugging,
   this phase does not meet it. What exists is compile → read errors → fix → re-run.
2. **Five toolchains cannot be verified on this machine** (java, dotnet, go, rust,
   pwsh). Their detection and refusal messages are real; their successful runs are not.
3. **Timeout and autosave are settings, not page controls.** Autosave has a real
   toggle in Settings; the timeout does not have a UI row yet.
4. **The page is a single-folder workspace**, not a multi-root IDE; no test runner and
   no VCS panel.
5. **At 1.5× font scale on a 1120×720 window** the scroll-based Phase-2 pages need a
   horizontal scrollbar (the card column is wider than the centre pane). Everything is
   reachable and nothing overlaps, but the bar is real and visible; Code Studio itself
   uses splitters and does not need it.
6. **`openrouter.ai` remains unreachable from this sandbox**, so the live-API limitation
   from Phase 2 carries over unchanged. Nothing in this phase was reported as
   live-tested that was not live-tested.
7. **A pre-existing defect was found by this phase** (FlowLayout children were never
   parented). It is fixed and re-verified in the regenerated Phase-2 screenshots, but it
   is a reminder that the Phase-2 review missed an invisible action row; the screenshot
   review for Phase 3 therefore checked every action row at 1.0×, 1.25× and 1.5×.

# LAB round — final report

Round: five capabilities added after `v0.5.0-post-phase5-r2`. Nothing was
compiled into an `.exe` (the user asked to keep packaging for the very end).
Everything below was measured on this host: Debian Linux, Python 3.11.2,
PySide6 6.8.3, headless Qt (`QT_QPA_PLATFORM=offscreen`).

---

## 1. Test results

```
python -m pytest -q
803 passed, 1 skipped in 509.58s (0:08:29)
```

The one skip is the opt-in live OpenRouter test (`MYAI_LIVE_API_KEY` is not set
here and `openrouter.ai` is unreachable from this sandbox), exactly as in the
two previous rounds. Nothing else is skipped, xfailed or silently ignored.

| Suite | Tests | What it proves |
| --- | --- | --- |
| `tests/unit/test_colorlab.py` | 29 | colour parsing, HSV round-trip, WCAG maths, accent ramp generation |
| `tests/unit/test_review.py` | 15 | diff rows and stats, unified-diff parsing, dry run, rejection paths |
| `tests/unit/test_atlas_and_context.py` | 16 | import resolution, layout determinism, prompt segments, window maths, chart contracts |
| `tests/unit/test_doctor.py` | 14 | every check against a real database, injected failure, score and verdict |
| `tests/ui/test_lab_pages.py` | 27 | the five pages inside the real window, including a real patch written to a real file |
| **new in this round** | **103** | |

Static gates, unchanged and green:

```
scripts/check_windows_static.py      0 findings
scripts/check_portability.py         17/17 checks passed
ruff check myai tests scripts        All checks passed!
```

The three regression defects found by the screenshot review are covered by
tests that would have failed before the fix (see §6).

## 2. What was built

### 2.1 Review (`review`) — diff two files, apply a patch only after a dry run

`myai/services/review.py`, `myai/ui/widgets/diff_view.py`,
`myai/ui/views/review_page.py`.

A real `difflib` diff of any two files of the open project, with `+ / − / ~`
counts, a percent-identical figure, a two-pane painter with line numbers and
character-level highlights inside a changed line. *Swap* exchanges the sides
(additions become removals and vice versa), *Save diff* writes a unified diff
into Output Studio. *Apply patch* parses real `@@` hunks, verifies the declared
line counts and that every context/removal line exists at that position, and
reports `n hunk(s) match — nothing has been written yet.` The Apply button stays
disabled until that dry run succeeds, and the write itself asks for
confirmation. A patch that does not apply is rejected with the exact reason and
the file is byte-identical afterwards — both outcomes are asserted.

### 2.2 Project Atlas (`atlas`) — the import graph of the open folder

`myai/services/atlas.py`, `myai/ui/widgets/graph_canvas.py`,
`myai/ui/views/atlas_page.py`.

Walks only the folder open in Code Studio, counts files / lines / resolved
imports / unlinked files, and paints the graph: node radius from the square root
of the file size, colour from the language, a halo for files other modules
import. Python (including `from . import x` and `from .mod import y`), plus the
C, C++, C#, Java, Kotlin, JS, TS, Go and Rust forms the scanner understands.
Clicking a node opens that file in Code Studio. The layout is deterministic
(root bay, folder clusters, ring for three or more folders), so two screenshots
are comparable. The painter stops drawing past the row cap and says so.

### 2.3 Context Map (`context`) — what the next request really contains

`myai/services/chat.py` (`PromptSegment`, `ContextMap`, `context_map`),
`myai/ui/widgets/charts.py`, `myai/ui/views/context_page.py`.

The page asks the chat service for the same blocks that the sender builds and
measures **those** tokens, not an estimate of its own. Donut against the model
window, a 100 % stacked bar of System / Conversation / Memory / Personality /
Attachments, the five largest contributors with their first line, and a written
advice line when the window starts filling.

### 2.4 Appearance (`appearance`) — accent lab with a WCAG audit

`myai/ui/theme/colorlab.py`, `myai/ui/views/appearance_page.py`.

Six accents (five built-in + custom), custom edited by hue/saturation/brightness
sliders or a hex field. The preview is real widgets (bubble, code line, primary
and secondary button, badge) restyled with the candidate colour. The audit
computes WCAG 2.1 ratios from the same tokens the renderer uses, for the seven
pairs that matter, and badges each AAA / AA / LARGE. Nothing is written until
*Apply*; *Reset* returns to Azure.

### 2.5 Diagnostics (`doctor`) — fourteen measured checks and a score

`myai/services/doctor.py`, `myai/ui/views/doctor_page.py`.

Database integrity, schema version, free disk, backups, log size, attachments,
secret store, API-key shape, Windows name rules, workspace writability, settings,
translation-catalogue parity, database rows and toolchains — each row prints the
measured fact and the fix for a failure. Weighted score with three verdicts and a
plain-text report on the clipboard.

### 2.6 Supporting work

- A new **LAB** group in the sidebar: five routes as 30 px two-column tiles
  (five full-width rows pushed the AI section below the fold at 1440×900), an
  icon-only 40 px rail when the sidebar is collapsed, and a chevron band that
  appears only when something is hidden.
- Navigation, command palette (`Ctrl+Shift+P`), `PAGE_TITLES` and the
  `AI_ROUTES` hook wired for all five routes.
- 45 screenshots: `artifacts/ui/p6_*` (5 pages × 2 themes × 2 languages) and
  `artifacts/ui/lab_*` (the same four combinations plus the collapsed rail),
  all captured by `scripts/capture_ui.py` against a real demo project.
- `docs/LAB_PAGES.md` and `docs/LAB_PAGES_FA.md` (this round's user-facing docs),
  README table rows and project-structure updates.

## 3. Screenshots

| File pattern | Count | Content |
| --- | --- | --- |
| `artifacts/ui/p6_review_{midnight,dawn}_{en,fa}.png` | 4 | diff of `README.md` vs `main.py` in the demo project |
| `artifacts/ui/p6_atlas_*` | 4 | import graph with 7 files, 5 resolved imports |
| `artifacts/ui/p6_context_*` | 4 | measured request: donut, segments, largest contributors |
| `artifacts/ui/p6_appearance_*` | 4 | accent lab and the contrast audit |
| `artifacts/ui/p6_doctor_*` | 4 | 14 checks, score 86/100, verdict *Needs attention* |
| `artifacts/ui/lab_*` | 25 | the same pages from the review harness, including the collapsed rail |

Both directions were checked: English LTR at 1440×900 and Persian RTL at the
same size, in the dark and the light theme.

## 4. What is not complete

Stated plainly, in the same spirit as the earlier reports:

1. **No `.exe` was produced.** Packaging is deferred to the end, per the
   standing instruction. The Windows runtime has still never been executed —
   only the static gate (17/17) and the pure-function tests prove the rules.
2. **Review is text-only.** A binary file shows a clear message instead of a
   diff; images and PDFs have no diff representation. Diffs above 4 000 rows are
   truncated for painting (the counts still describe the whole file).
3. **Atlas understands nine languages.** Imports in, for example, Ruby, PHP or
   Swift are not parsed, so those files appear as unlinked nodes rather than as
   nodes with edges. Dynamic imports (`importlib`, `require(variable)`) are
   deliberately not guessed.
4. **Context Map measures the local builder, not the provider's tokeniser.** The
   numbers are a character-based estimate computed from the exact blocks that
   will be sent; an exact figure would require the provider's tokeniser, which
   this build cannot call.
5. **The contrast audit covers seven pairs.** It does not crawl every widget; a
   page with a hard-coded colour outside the token set would not be measured.
6. **Diagnostics never fixes anything by itself.** Every failing row names the
   fix and where to find it; there is no "repair" button, because a half-broken
   database is a bad place for automation to improvise.
7. **The live OpenRouter path is still untested here.** Network to
   `openrouter.ai` is blocked in this sandbox and the user reserved the real key
   test. Mocked transports are labelled as mocked everywhere.

## 5. Files changed

New:

```
myai/services/review.py            diff, stats, unified-diff parse, dry run, apply
myai/services/atlas.py             project walk, import resolution, layout
myai/services/doctor.py            14 health checks, weighted score
myai/ui/theme/colorlab.py          colour maths, accent ramps, WCAG audit
myai/ui/widgets/charts.py          DonutChart, GaugeScore, SegmentBar
myai/ui/widgets/diff_view.py       two-pane diff painter
myai/ui/widgets/graph_canvas.py    graph painter with hit testing
myai/ui/views/review_page.py
myai/ui/views/atlas_page.py
myai/ui/views/context_page.py
myai/ui/views/appearance_page.py
myai/ui/views/doctor_page.py
tests/unit/test_colorlab.py        29 tests
tests/unit/test_review.py          15 tests
tests/unit/test_atlas_and_context.py  16 tests
tests/unit/test_doctor.py          14 tests
tests/ui/test_lab_pages.py         27 tests
docs/LAB_PAGES.md, docs/LAB_PAGES_FA.md
45 screenshots under artifacts/ui/
```

Modified:

```
myai/ui/views/sidebar.py           LAB group, LabTile, _ScrollFade, collapsed rail
myai/ui/widgets/buttons.py         NavButton 38 → 36 px
myai/ui/main_window.py             five routes, page titles, cross-page navigation
myai/ui/theme/manager.py           slider QSS (including the hue gradient)
myai/ui/theme/tokens.py            light-theme success/warning/danger darkened to pass AA
myai/services/chat.py              PromptSegment / ContextMap / context_map
myai/services/settings.py          accent keys
myai/core/redaction.py             find_secrets(text)
myai/i18n/locales/{en,fa}.json     1273 keys each, parity true
scripts/capture_ui.py              the p6_* capture block
README.md                          verification rows, test figures, structure
```

## 6. Defects found by the visual review and fixed in this round

Every one of these was seen in a rendered screenshot, reproduced, fixed, and
re-checked against a new screenshot.

| # | Defect | Cause | Fix |
| --- | --- | --- | --- |
| 1 | Diff text was black in the light theme | `theme.alpha()` returns a CSS `rgba()` string; `QColor` parses that as invalid and paints black | `_tint()` builds a `QColor` and uses `setAlphaF` |
| 2 | Diff lines re-ordered in a Persian UI | the painter inherited the application's RTL direction | `painter.setLayoutDirection(LeftToRight)` in the diff painter, the charts and the graph |
| 3 | The diff strip below the last row was card-white | `DiffView` had a `Fixed` vertical size policy | `Expanding`, so the empty strip is painted in `code_bg` |
| 4 | Persian placeholder of the patch box showed the RTL sample wrapped into nonsense | a multi-line ASCII sample inside an RTL placeholder | the hint is now one translated line; the editor's text direction is pinned to LTR |
| 5 | Gauge arc was clipped; `/ 100` was outside the widget | the radius came from the width, but a 270° arc needs `R · 1.71` of height | radius derived from the height, caption repositioned inside the arc |
| 6 | Gauge track invisible on the light theme | `surface_3` is nearly white on the light card | track uses `border_strong` |
| 7 | Donut painted a full multicolour ring next to `0%` | the ring used the composition, not the share of the window | `set_data(..., fill=ratio)` plus a minimum arc so 0.1 % still shows |
| 8 | Colour swatches had borders around the chip and the caption | an unscoped `QFrame { … }` stylesheet on the parent | selectors scoped to `QFrame#Swatch` / `QFrame#SwatchChip` |
| 9 | Swatch caption clipped at the card edge | 64 px tall frame, 28 px chip | 76 px frame, 30 px chip, caption given its own line |
| 10 | Repeated `resizeEvent` in the sidebar (the second one silently won) | two methods with the same name from two edits | one method that does both jobs |
| 11 | Collapsed sidebar crashed on the new LAB tiles | `LabTile` had no `set_collapsed` | implemented, plus a one-column icon layout for the rail |
| 12 | Light theme failed its own contrast audit (success 3.47, warning 3.64, danger 4.48) | tokens chosen by eye | darkened to 4.89 / 4.86 / 4.63 — the audit now passes AA on white |

Also fixed: the sidebar overflow at 1440×900, the dead appearance sliders (they
read 0 because `refresh()` never wrote the candidate back), the rainbow-less hue
slider, the atlas's missing `from . import x` edges, the sparse top-heavy atlas
layout, the doctor's duplicated verdict and its raw timestamp, and two locale
keys that were used in code but never added.

## 7. Verification checklist

| Item | Status | Evidence |
| --- | --- | --- |
| Five capabilities exist and are reachable | **Yes** | 5 routes in `PAGE_TITLES`, sidebar LAB group, command palette |
| Each capability is backed by a service with unit tests | **Yes** | 74 unit tests across four files |
| Each capability is exercised through the real window | **Yes** | `tests/ui/test_lab_pages.py` (27) |
| Bilingual fa + en, key parity | **Yes** | 1273 keys each, `doctor` check *locales* reports `en = fa` |
| RTL and LTR reviewed in both themes | **Yes** | 45 screenshots, read one by one |
| No display-only page or dead button | **Yes** | every control on the five pages writes, navigates or measures (tests assert it) |
| Full suite green | **Yes** | 803 passed, 1 skipped |
| Static Windows gate | **Yes** | 0 findings, 17/17 portability checks |
| Lint | **Yes** | `ruff check` clean at line length 120 |
| Docs updated (fa + en) | **Yes** | `docs/LAB_PAGES.md`, `docs/LAB_PAGES_FA.md`, README |
| Packaging | **Not done — deferred to the very end, as instructed** | — |
| Debugging stage | **Not started — waiting for the user's instructions** | — |

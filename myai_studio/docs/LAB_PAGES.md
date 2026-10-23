# LAB pages: five capabilities added after Phase 5

`v0.5.0-post-phase5-r2` closed the Windows-readiness round. This document
describes the five capabilities added in the round that followed, all of them
reachable from the new **LAB** group in the sidebar and each one backed by a
service with its own unit tests and a page driven by the real window.

Nothing here is a mock-up: every number on these pages is produced by reading
the project folder, the database, the secret store or the theme tokens that the
renderer itself uses. Where something is a limit or a guess, the page says so.

---

## 1. Review — diff two files and apply a patch only after a dry run

**Route** `review` · **Service** `myai/services/review.py` · **Page**
`myai/ui/views/review_page.py`

The page lists the text files of the project that is open in Code Studio, and
compares any two of them.

| What it shows | Where the number comes from |
| --- | --- |
| `+n added`, `−n removed`, `~n changed` | a real line diff (`difflib.SequenceMatcher`) over the two files |
| `n% identical` | matching rows ÷ total rows |
| The two-pane view with line numbers | the same rows, painted left-to-right even in a Persian UI |
| Similar-span highlight inside a changed line | character-level opcodes, not a coloured block |

- **Swap** exchanges the two sides; additions and removals swap with them.
- **Save diff** writes a unified diff into Output Studio, so it can be copied or
  attached to a message.
- **Apply a patch** never writes on the first click. *Preview* parses the
  unified diff, checks that every hunk's line counts match its body and that
  every context/removal line exists at the declared position, and reports
  `n hunk(s) match — nothing has been written yet.` Only then does **Apply**
  enable, and applying asks for confirmation with the file name and hunk count.
  A patch whose context does not exist is rejected with the exact reason and
  the file is left untouched — both paths are covered by tests.
- Above 4 000 rows the painter stops drawing and says so; the counts still
  describe the whole file.
- A binary file, a missing project and a project with fewer than two files each
  get their own empty state with a button that leads somewhere useful.

## 2. Project Atlas — the import graph of the open folder

**Route** `atlas` · **Service** `myai/services/atlas.py` · **Page**
`myai/ui/views/atlas_page.py` · **Widget** `myai/ui/widgets/graph_canvas.py`

The atlas walks the folder open in Code Studio (and nothing outside it), counts
files, lines, resolved imports and unlinked files, and draws the graph.

- Each **node is a file**; its radius grows with the square root of the file
  size, its colour is the language, and a halo marks files that others import.
- Each **line is a resolved import**: Python (`import x`, `from a.b import c`,
  `from . import util`, `from .mod import y`), plus the C/C++/C#/Java/Kotlin/JS/
  TS/Go/Rust forms the scanner understands. An import that points outside the
  folder is not invented as a node.
- **Clicking a node opens that file in Code Studio** and switches route; the
  signal is `AtlasCanvas.node_activated(str)`.
- *Most depended-on files* lists the files the rest of the project imports,
  which is usually the best place to start reading.
- The layout is deterministic: the root files sit in a bay, folders become
  clusters, and three or more folders are placed on a ring. The same project
  always draws the same picture, so two screenshots can be compared.
- The dot grid, the edges and the hub list are painted, not composed of dozens
  of child widgets, so a 400-file project does not freeze the UI.

## 3. Context Map — what the next request will actually contain

**Route** `context` · **Service** `myai/services/chat.py` (`PromptSegment`,
`ContextMap`, `context_map`) · **Page** `myai/ui/views/context_page.py`

The page does not estimate tokens from a heuristic of its own: it asks the chat
service for the same blocks the sender builds, and measures **those**.

- A donut shows used tokens against the model's window; the caption is
  `77 tokens of 128,000`.
- *Where the tokens go* is a 100 % stacked bar with the exact numbers and
  shares of System, Conversation, Memory, Personality and Attachments.
- *Largest contributors* lists the five biggest segments with their first line,
  so an oversized persona or a giant attachment is visible immediately.
- When the window starts filling, the page says so in words (and suggests
  starting a new chat or shortening memory), instead of only drawing a fuller
  ring.
- Two shortcuts lead to the two things that usually cause the growth: the
  memory settings and the chat itself.

## 4. Appearance — pick an accent, see it, then read its contrast

**Route** `appearance` · **Theme** `myai/ui/theme/colorlab.py`, `tokens.py` ·
**Page** `myai/ui/views/appearance_page.py`

- Six entries: Azure, Violet, Teal, Amber, Rose and **Custom**.
- Custom is edited with three real sliders (hue, saturation, brightness) or a
  hex field; the sliders are synchronised with the candidate, so they never sit
  at zero while a colour is selected.
- The preview uses **real widgets** — a chat bubble, a code line, a primary and
  a secondary button, a badge — restyled with the candidate colour, not an
  image of a widget.
- The **contrast audit** computes WCAG 2.1 ratios from the same tokens the
  renderer uses, for the seven pairs that matter (body, muted, accent text,
  button label on accent, success, warning, danger) and badges each one
  AAA / AA / LARGE with its ratio.
- *Apply* writes `ui.accent` (and `ui.accent_custom` for a custom colour) and
  restyles the whole app immediately; *Reset* returns to Azure. Nothing is
  written until Apply is pressed — the status line says *Preview only*.
- The audit is also a regression test: the light theme's success, warning and
  danger tokens were darkened in this round because the audit reported them
  below AA on white.

## 5. Diagnostics — fourteen measured checks and a score

**Route** `doctor` · **Service** `myai/services/doctor.py` · **Page**
`myai/ui/views/doctor_page.py`

| Group | Checks |
| --- | --- |
| Storage & data | database integrity (`PRAGMA integrity_check`), schema version, free disk space, backups, log size, attachments |
| Security | secret store opens, API key shape (never the key itself), Windows name rules |
| Interface & language | workspace writable, settings readable, translation catalogues (key parity), database rows |
| Runtime | Python and the toolchains this build can find |

- Every row prints the **measured fact** (bytes, versions, counts, milliseconds)
  and, when something is wrong, the fix next to it.
- The verdict is one of *Healthy*, *Needs attention* or *Needs care*, and the
  gauge is the weighted score. Failures always dominate warnings.
- **Copy report** puts a plain-text report on the clipboard, and the timestamp
  of the measurement is printed once, in UTC, at the top right.

---

## The LAB group in the sidebar

Five more destinations would have pushed the AI section below the fold at
1440×900, so the LAB entries are 30 px tiles in a two-column grid instead of
full-width 38 px rows. When the sidebar is collapsed to its rail, the tiles
become one column of icon-only 40 px buttons with tooltips — the same width
rule as every other navigation button. A chevron band at the bottom of the
scroll area appears only when content is hidden and scrolls one page per click.

## Tests

| File | Tests | What it proves |
| --- | --- | --- |
| `tests/unit/test_colorlab.py` | 29 | colour parsing, HSV round-trips, WCAG maths, accent token generation |
| `tests/unit/test_review.py` | 15 | diff rows, stats, unified-diff parse, dry run, rejection paths |
| `tests/unit/test_atlas_and_context.py` | 16 | import resolution, layout determinism, prompt segments, window maths, chart contracts |
| `tests/unit/test_doctor.py` | 14 | every check against a real database, failure injection, score |
| `tests/ui/test_lab_pages.py` | 27 | the five pages in the real window: routes, diff swap, patch apply, node activation, donut, accent apply, doctor score, collapsed rail |

All of them run headless (`QT_QPA_PLATFORM=offscreen`); the screenshots in
`artifacts/ui/p6_*` and `artifacts/ui/lab_*` are produced by the same code path
against a real demo project.

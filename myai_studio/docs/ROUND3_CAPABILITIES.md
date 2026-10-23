# Round 3 — three practical capabilities

After the LAB round (`v0.6.0-lab`) the next question was not "what else can the
model do" but "what does someone need every day". This round adds three
everyday features, each backed by its own service, its own page or overlay, its
own bilingual strings and its own tests:

| Capability | Service | Surface | Shortcut |
| --- | --- | --- | --- |
| Global search | `myai/services/search.py` | overlay `myai/ui/widgets/global_search.py` | **Ctrl+Shift+F** |
| Usage & cost | `myai/services/usage.py` | page `myai/ui/views/usage_page.py`, route `usage` | sidebar → Usage |
| File history | `myai/services/history.py` | dialog `myai/ui/widgets/history_panel.py`, Code Studio → **History** | — |

Nothing on these surfaces is a mock-up. Every number comes from a row the app
already stored, a file that is really on disk, or a price that is really in the
cached catalogue — and where that is not true the surface says so.

---

## 1. Global search — one field over every local source

Typing at least two characters searches conversations, messages, prompts,
memory entries, saved outputs, tasks and the files of the project that Code
Studio has open. Results are grouped per source, five per source in the
overlay, and a broken source is isolated instead of taking the dialog down.

- **Open a hit:** a conversation or message opens the chat, a file opens in Code
  Studio at that file, a prompt or task opens its page **already filtered** by
  the query you typed, and memory/output hits open their pages.
- **Keyboard:** ↑/↓ move the selection, Enter opens, Esc closes, and the footer
  shows those keys in the current language.
- **Limits that are real:** binary and attachment files are not indexed (they
  have no text to search), and file hits only exist when a project is open —
  the source is skipped rather than silently returning nothing.

## 2. Usage & cost — what the last 7/30/90 days actually consumed

The token counts are the ones the provider reported on each assistant reply
(`messages.input_tokens` / `output_tokens`), grouped by UTC day. The prices are
the per-million prices of the cached OpenRouter catalogue
(`ai.openrouter_cache`).

- **Hero:** estimated cost for the range, replies, tokens, distinct models, and
  the optional monthly budget bar (accent below 80 %, warning from 80 %, red
  once exceeded).
- **Daily cost chart:** one bar per day with a hover tooltip; a day with no
  spend draws a hairline instead of a fake stub.
- **By model:** up to eight models with replies, tokens and estimated cost. A
  model with no cached price is **counted in the tokens and marked unpriced** —
  the page never invents a price to make a chart look complete, and the note in
  the hero states how many tokens were excluded from the cost.
- **Budget:** stored in `usage.monthly_budget` (0 means "no limit"), editable
  from the page; the chosen range is stored in `usage.range_days` and survives
  a restart.

## 3. File history — restore a version, and the restore is itself a version

Every write that goes through `ProjectService` records a snapshot **after** the
file was written, so the history contains states that really existed on disk,
not a reconstruction of keystrokes:

| Writer | Reason stored |
| --- | --- |
| Code Studio **Save** / autosave | `save` |
| new file | `create` |
| Review page **Apply patch** | `patch` |
| **Restore** from this dialog | `restore` |

- Snapshots live under `<app home>/history/<project hash>/<file hash>/` as
  `<epoch-ms>-<reason>.snap`; the hash keeps user paths out of file names and
  stops two projects with the same relative file from sharing a history.
- Order is the file name, so a stamp is always strictly newer than every stored
  version — even if the wall clock steps backwards, the version that was just
  written can never be the one pruned.
- The newest 40 versions per file are kept and a snapshot larger than 1 MB is
  skipped. Writing text identical to the newest version is a no-op.
- The dialog shows the selected version diffed **against what is open now**, so
  a restore is a decision made with the change in front of you. Restoring
  writes the file, records a `restore` version and updates the editor.
- **Delete history** clears only the stored snapshots; the file itself is not
  touched.

## 4. What the screenshot audit changed

The three surfaces were captured in both languages, both the dark and light
theme, and at 1.25×/1.5× font scale. The review found real layout defects that
were fixed rather than documented away:

- the usage hero stacked cost above the counters, because side by side it was
  wider than a 1.5× window leaves beside the sidebar and inspector;
- the model table became a row list for the same reason, and the budget editor
  wraps instead of forcing a horizontal scrollbar;
- navigation labels sat far from their icons at 1.5× (the text rectangle
  arithmetic was replaced with a leading-gap calculation);
- disabled danger buttons kept their red fill — a missing
  `QPushButton[variant="danger"]:disabled` rule;
- the budget line showed "$2.54 of $4.00" in a bidirectional sentence that read
  badly in Persian, so the bar now shows the percentage and the amounts moved
  to its tooltip;
- Code Studio's toolbar gained dividers between project actions, file actions
  and History.

## 5. Tests

| Suite | Tests | What it proves |
| --- | --- | --- |
| `tests/unit/test_lab_round2.py` | 15 | snapshot dedupe/prune/restore order, no path leak, USD-per-million maths, unpriced handling, 7/30/90 windows, budget round-trip, all seven search sources, snippet shape, per-source cap, broken source isolation |
| `tests/ui/test_round3_pages.py` | 9 | real numbers on the usage page, range persistence, empty state, budget round-trip and validation, search grouping and open-in-page, save→version→restore through the real window, sidebar/palette/shortcut wiring |
| existing suites | — | the scale test now also covers the `usage` page at 1.25×/1.5× |

## 6. Honest limits

- Costs are **estimates** from the cached catalogue; the app never talks to a
  billing API. A model whose price is not cached is reported as unpriced.
- Live OpenRouter completions were not exercised here: no API key is configured
  in this environment and `openrouter.ai` is unreachable from the sandbox. The
  token accounting is tested with rows written through the same service the
  chat path uses, not with a live provider response.
- Search indexes text the app stores plus the text files of the open project;
  attachments and binaries are out of scope.
- History snapshots are plain UTF-8 files under the application home. They are
  excluded from project backups (`paths.history_dir` lives outside the project)
  and are removed when the user clears them.

## 7. Windows build and download

A Linux host cannot produce a Windows executable (PyInstaller does not
cross-compile), so the binary is built on GitHub's `windows-latest` runner by
`.github/workflows/windows-build.yml`:

| Step | What runs |
| --- | --- |
| tests job | Python 3.11, `pip install -r requirements-dev.txt`, full `pytest -q` with `QT_QPA_PLATFORM=offscreen`; failures are printed as check annotations |
| build job | `scripts/build_windows.ps1 -SkipTests` → PyInstaller 6.12 onedir, icon, bundled locales + assets, then the packaged `MyAIStudio.exe --smoke --allow-multi` must exit 0 |
| package | `RUNNING.txt` added, `dist/MyAIStudio` zipped, uploaded as an artifact, and attached to the release for tag pushes |

**Download (Windows x64):**
[`MyAIStudio-v0.7.3-windows-x64.zip`](https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer/releases/download/v0.7.3/MyAIStudio-v0.7.3-windows-x64.zip)

Extract the zip and run `MyAIStudio.exe`; the `_internal` folder must stay next
to it. Data lives in `%APPDATA%\MyAIStudio` unless `MYAI_STUDIO_HOME` is set.

To rebuild locally on a Windows machine:

```powershell
cd myai_studio
powershell -ExecutionPolicy Bypass -File scriptsuild_windows.ps1            # tests + exe + smoke
powershell -ExecutionPolicy Bypass -File scriptsuild_windows.ps1 -Installer # adds the Inno Setup installer
```

Honest limits of this artefact: it is **not code-signed**, so SmartScreen asks
for confirmation on first launch; it was smoke-started on the runner (exit 0)
but not clicked through by a human on a physical desktop; and it contains no
OpenRouter key, so live completions still need the user's own key.

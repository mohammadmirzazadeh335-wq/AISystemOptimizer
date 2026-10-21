# Phase 3 plan — Code Studio (real edit / compile / run / debug loop)

> **Status: delivered in v0.3.0.** Results, evidence and the honest list of gaps are in
> [`PHASE3_REPORT.md`](PHASE3_REPORT.md) / [`PHASE3_REPORT_FA.md`](PHASE3_REPORT_FA.md).

**Goal:** open a real folder, edit real files, run them with the real toolchains on this
machine, and see real stdout, stderr, exit codes and compiler errors. Anything the
machine cannot do is reported as *unavailable* with the exact reason — never faked.

**Acceptance gate (same rules as Phase 2):**

1. Every claimed language is proven by a test that compiles/runs a real file here.
2. Missing toolchains (Java, .NET, Go, Rust here) are shown as unavailable with the
   command that is missing; no pretend "Run" button.
3. Opening a project cannot read or write outside its root (`..`, absolute paths and
   symlink escapes are rejected and covered by tests).
4. Long or runaway programs are stopped by a wall-clock limit and can be cancelled from
   the UI; the process group is killed, not just the parent.
5. The UI never blocks while a program runs (worker thread + queued Qt signals).
6. Screenshots of the Code Studio in fa/en, dark/light and at 1.25×/1.5× are reviewed.
7. Full suite re-run after the last change; fa + en docs updated.

## Scope of this phase

| Area | What ships |
| --- | --- |
| Projects | open folder, create project, recent projects, file tree, create/rename/delete file, read/save with size and binary guards |
| Editor | plain-text editor with line numbers, per-language highlighting (Python, C/C++, JS/TS, JSON, Markdown, shell), unsaved marker, Ctrl+S, optional autosave |
| Toolchains | real detection and version of Python, C, C++, Node, Java, .NET, Go, Rust, Bash, PowerShell |
| Runner | per-language run plan (interpret or compile+run), streaming stdout/stderr, exit code, duration, timeout, cancel, output cap |
| Test panel | "Run" executes the current file; output panel shows the exact command, stdout, stderr and exit status; compile errors surface verbatim |
| Inspect | toolchain summary card, project path, file metadata, and honest unavailable rows |

## Out of scope (later phases or explicitly not promised)

- No language server / autocomplete engine; highlighting is syntax-only.
- No integrated debugger (breakpoints/step) — "debug loop" means edit → compile → read
  the real error → fix → re-run, which is what the acceptance gate asks for.
- No package installation from inside the app.

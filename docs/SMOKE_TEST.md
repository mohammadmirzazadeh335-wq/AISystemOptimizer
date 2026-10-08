# First-run smoke test

A 10-minute, copy-pasteable checklist. Each step lists the **expected** result so you can tell
pass from fail without judgement calls.

> **Most of this file is now automated.** Before working through it by hand, run:
>
> ```powershell
> dotnet build -c Release
> powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1 -MeasureOptimizer
> dotnet run --project tools\AISystemOptimizer.SmokeTests -c Release -- --monitor-seconds 300
> ```
>
> The first command builds the machine script's compiled counterpart; the second checks the machine,
> the delivered files and the security posture and returns the number of failures; the third drives the
> application's own code and prints PASS / FAIL / NOT VERIFIED per check. Whatever they cannot judge
> (the window, the theme, keyboard navigation, a real game, a real optimisation) is what remains below,
> and the report in [`../WINDOWS_VALIDATION.md`](../WINDOWS_VALIDATION.md) lists those items explicitly.

**PHASE 62** adds a second checklist, and it is the one that matters for the new feature:
[`GAME_APP_OPTIMIZER_SMOKE_TEST.md`](GAME_APP_OPTIMIZER_SMOKE_TEST.md) — 20 checks covering the
application picker, inspection without execution, the live status, a reversible change and its
restoration, cancellation, crash recovery, executable replacement, duplicate instances, foreground and
critical-process protection, Game Mode, the benchmark, the AI vocabulary, and the weight of the page.
**None of those checks has been run**, so the Game & App Optimizer is `NOT VERIFIED` on Windows.

Run the application as a **standard user first** (that is the intended default), then repeat
steps 6–8 elevated.

---

## 0. Sanity

```powershell
.\scripts\build.ps1 -Configuration Release
.\scripts\run-tests.ps1
```

- [ ] Build: `0 Warning(s), 0 Error(s)`
- [ ] Tests: `Failed: 0, Passed: 492`

---

## 1. Start-up (standard user)

Launch the executable.

- [ ] **No UAC prompt appears.**
- [ ] The window opens within ~2 seconds.
- [ ] The busy overlay shows "Analysing the system…" and disappears on its own.
- [ ] The status bar reads `Scan complete - N processes, RAM x %, health score n/100.`
- [ ] The navigation pane shows your user name, machine summary and "Standard user (some
      optimisations will ask for elevation)".

## 1b. Behaviour that the audit found broken and that must be re-checked here

These are the fixes that cannot be proven anywhere except on a real Windows machine. Each one is a
regression risk, so check them explicitly.

### Cancellation

- [ ] Start `Analyze System` and immediately press **Stop**. The operation ends with
      `Operation cancelled.` in the status bar and the application stays responsive.
- [ ] Start `Smart Optimize`, press **Stop** on the plan screen. No action is applied and the plan is
      left reviewable. Nothing is left half-changed.
- [ ] Press **Stop** when nothing is running. Nothing happens, and no error appears.

### Graceful close

- [ ] Open Notepad and type something without saving. Open a browser so Notepad is not the foreground.
- [ ] Run an optimisation that proposes closing a background application, and confirm it.
- [ ] A program that was closed should have exited **through its own shutdown path** — it should not
      be reported as crashed or leave a "recovered after unexpected shutdown" prompt on the next
      start. The log contains `closed cleanly and saved its state` or
      `did not close within the grace period`.

### Process identity

- [ ] The log contains an `Anchored process identities for N action(s)` line after planning.
- [ ] In the plan preview, every close/priority action shows a PID.
- [ ] Open and close an application repeatedly between planning and confirming. Confirming must never
      close a different program, and the report should say `The pid was reassigned` if it caught one.

### Active-window protection

- [ ] Make Chrome the foreground window, run an optimisation, and confirm that Chrome is **never** in
      the proposed close list — including when several `chrome.exe` processes are running.
- [ ] Switch to an application *after* building the plan but *before* pressing Optimize. It must be
      skipped, and the log should record that it became the active window.

### Service dependencies

- [ ] In **Services**, try to stop a service that other services depend on. It must be refused with an
      explanation naming the dependents.
- [ ] Stop a service that nothing depends on, then restart it. Both should succeed.

### Honest cache reporting

- [ ] Run **Smart RAM clean**. The result must quote real counts of files removed and files skipped,
      not a bare "success".

## 2. Dashboard correctness

- [ ] RAM card percentage matches Task Manager within ~2 points.
- [ ] CPU card percentage matches Task Manager within ~5 points (different sampling windows).
- [ ] Disk card shows activity and free space for the system drive.
- [ ] GPU shows a percentage **or** `N/A` — never a fabricated number.
- [ ] Component scores (Memory, CPU, Disk, Start-up, Background apps) are all inside 0–100.
- [ ] The "Memory target" card states either that the target is reachable, or that it is *not*
      reachable and why ("… Safe optimization limit reached.").

## 3. Live charts

- [ ] Leave the window open for a minute while opening a browser.
- [ ] The memory/CPU/disk sparklines move and the values refresh about every 2 seconds.

## 4. Processes page

- [ ] Sorting by RAM puts the biggest consumer first.
- [ ] Filtering the category to `Background` removes processes with visible windows.
- [ ] Click any running app you have on screen (e.g. Chrome):
  - [ ] The note says **IN USE** and explains that it will never be closed automatically.
  - [ ] The "Close process" button is disabled with a tooltip explaining why.
- [ ] Click a Windows component (e.g. `lsass.exe` or `dwm.exe`):
  - [ ] The note says **PROTECTED (critical)**.

## 5. Smart Optimize → preview → apply

- [ ] Press **Smart Optimize** (or **Optimize** after reviewing).
- [ ] A dialog titled *Confirm optimisation* appears listing "Will close:", "Will disable at
      start-up:", estimated recovery and overall risk.
- [ ] Press **No**. Nothing changes; the status bar says the plan was cancelled.
- [ ] Press **Smart Optimize** again, press **Yes**.
- [ ] A report appears with Before → After RAM/CPU/process counts and a list of actions.
- [ ] If nothing changed, the report contains "No significant optimisation was possible" —
      that is a **pass**, not a failure.

## 6. Start-up page

- [ ] Entries are listed with source, impact, risk and recommendation.
- [ ] Windows-owned entries show "Windows component - keep enabled" and cannot be disabled.
- [ ] Pick a non-Windows entry and disable it → confirmation dialog → it shows as disabled.
- [ ] Re-enable it again → it returns exactly as before.

## 7. Service page (elevated for changes)

- [ ] Attempting **Disable** on a critical service (e.g. `RpcSs`) is refused with an explanation.
- [ ] Disabling a third-party service asks for confirmation and needs elevation; without elevation
      the app reports that Windows refused instead of appearing to succeed.

## 8. Game Mode

- [ ] Start a game (or any process whose path contains `\Games\`).
- [ ] Open **Game Mode** → **Detect game**: the game is listed.
- [ ] **Prepare game plan** → the Optimization page shows a plan; verify that
      Windows Defender, the firewall and driver processes are **not** in the list.
- [ ] Apply, then check Task Manager: the game's priority should be `Above normal`, not `High`.

## 9. Honest-reporting checks

- [ ] With 8 GB RAM and a normal desktop session, the memory target card never promises a RAM
      figure the safe actions cannot deliver.
- [ ] **Smart RAM clean** either reports the bytes it removed from caches, or states that the
      caches were already empty — and in both cases explains that this frees storage, not RAM.

## 10. Robustness

- [ ] Turn off Wi-Fi/Ethernet: the application keeps working; AI status shows "not reachable";
      scanning and optimisation still function.
- [ ] Sleep the machine, wake it: charts resume, no crash, scan still works.
- [ ] Restart: settings, whitelist and history persist; disabled start-up entries stay disabled.
- [ ] Close and reopen the app while an optimisation plan is displayed: the app returns to the
      dashboard cleanly (no half-applied state).
- [ ] Launch a second copy: a message says an instance is already running and it exits.

## 11. Logs and reports

- [ ] `%LOCALAPPDATA%\AISystemOptimizer\Logs\` contains today's log with timestamped entries for
      every action, including reason and risk.
- [ ] `…\Reports\` receives the report when you press *Save & open*.
- [ ] **History** shows the session with before/after metrics.

---

## Failure handling

If something goes wrong, note the step, then:

```powershell
notepad "$env:LOCALAPPDATA\AISystemOptimizer\Logs\$(Get-Date -Format yyyy-MM-dd).log"
```

**About & Guarantees → Run diagnostics** produces a copyable summary (runtime, hardware, counter
availability, last counter error) that is enough to diagnose most issues without a round trip.

The application is designed so that a failure is **always** non-destructive: each action is
validated immediately before it runs, actions run one at a time, and a failed action is logged and
reported rather than retried blindly.

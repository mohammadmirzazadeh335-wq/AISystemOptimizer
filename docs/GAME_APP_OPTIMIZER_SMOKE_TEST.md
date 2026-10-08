# Game & App Optimizer — Windows 11 smoke test

**Status of this document: NOT RUN. No check below has been executed.**

Nothing in this phase has been validated on Windows. This repository contains no Windows host: the
code was written and unit-tested on Linux, so every runtime behaviour below is `NOT VERIFIED` until
somebody runs this file on a Windows 11 x64 machine and fills in the last column.

Allowed results, and only these: **PASS**, **FAIL**, **NOT VERIFIED**.
`PASS` means the check was run and behaved as described. A check whose result cannot be determined is
`NOT VERIFIED` — an unreadable check never becomes a pass.

---

## 0. Before you start

| Requirement | Detail |
|---|---|
| Machine | Windows 11 x64 (Windows 10 will work for most checks; the title bar, Mica and WebView2 are 11-specific) |
| Rights | A standard user account first, then one pass as administrator |
| Build | `AIOptimizer.exe` from `dotnet publish … -p:PortableName=AIOptimizer` or the installer |
| Time | ~45 minutes, plus 30 minutes for the stability check (step 20) |
| Record | Task Manager open on the Performance tab; a second window with this file to write into |

Fill in before starting:

- Windows build: `winver` → ______________________
- Total RAM: ______________________
- CPU: ______________________
- GPU(s): ______________________
- Running as: standard user / administrator (circle one)

---

## The 20 checks

### 1. A harmless built-in executable: Notepad

Open **🎮 Game & App Optimizer** → **+ Add Game / App** → `C:\Windows\System32\notepad.exe`.

- Expected: the file picker opens filtered to `*.exe`; the file is added as a profile; **Notepad does
  not open**. The card shows the path, publisher (Microsoft Windows), architecture (x64), file size
  and a SHA-256 beginning with a hex string. The signature line says **valid**.
- Why it matters: inspection must never execute the target.

Result: __________ Notes: ______________________

### 2. A harmless test executable you built yourself

Copy any small `.exe` you trust (for example a build of a console "hello world") to
`C:\Temp\AIOptimizerTest\hello.exe` and add it.

- Expected: added successfully; publisher shows *not recorded*; the signature line says **unsigned**
  and the notes explain that unsigned is not evidence of harm. No launch of the file.
- Why it matters: the app must not assume every `.exe` is a game or that a missing signature is
  malicious.

Result: __________ Notes: ______________________

### 3. A real installed application

Add a real installed application (for example `C:\Program Files\…\<app>.exe`).

- Expected: the product name, publisher and file version match what Windows shows in the file's
  Properties → Details. The signature state matches what **Properties → Digital Signatures** shows.
- Why it matters: the metadata must be read, not guessed.

Result: __________ Notes: ______________________

### 4. Metadata completeness

On the card for the application from step 3, check every field the specification requires: full
path, file name, product name, publisher, file version, product version, size, last modified,
architecture, signature status, SHA-256, installation directory, parent directory, existence,
running state, PID(s), process creation time.

- Expected: every one is present, or explicitly shown as `N/A`/`unknown` — never blank and never
  invented.
- Cross-check the SHA-256 against `certutil -hashfile "<path>" SHA256` in a command prompt: it must
  match exactly.

Result: __________ Notes: ______________________

### 5. Starting the application from the page

Press **Launch** on the Notepad card.

- Expected: Notepad starts. The card's status changes to `● Running · PID <n>` within a few seconds
  without touching Refresh.
- Why it matters: the status must be live, not a stale snapshot.

Result: __________ Notes: ______________________

### 6. Detecting the application and its identity

With the application running, look at the card and then close it and watch again.

- Expected: while it runs, exactly the real PID(s) are shown. After closing, the status returns to
  `Not Running`.
- Now start the same application twice (two instances) and check the card.
- Expected: both instances are listed, each with its own PID.

Result: __________ Notes: ______________________

### 7. PID plus creation time

For the running application, compare the creation time shown on the card with Task Manager →
Details → right-click **Start time** column (enable it in *Select columns*).

- Expected: they agree to within about a second.
- Why it matters: PID reuse is the reason a pid alone is not an identity, and the creation time is
  what makes it one.

Result: __________ Notes: ______________________

### 8. Change one reversible setting and verify it

Add a profile for a real application, set the profile mode to **Balanced**, and press
**Optimize**. Confirm the dialog.

- Expected: the dialog lists every change before it happens, in plain words, and says that
  everything reversible is restored afterwards.
- After confirming, verify at least one change externally:
  - priority: Task Manager → Details → **Base priority** column, or Process Explorer;
  - power mode: Settings → System → Power, or `powercfg /getactivescheme` in a command prompt.
- Expected: the change is real and externally visible, and the change is recorded in the page's
  "What this page has done" log with its original value.

Result: __________ Notes: ______________________

### 9. Exit the application and verify restoration

Close the optimised application (or press **End session and restore**).

- Expected: the original priority and the original power scheme are back, verified by the same
  external tools as step 8. The log lists each restored item.
- If anything could not be restored, the log names it exactly and the page does **not** say
  "everything restored".
- Why it matters: this is the mandate of the whole feature.

Result: __________ Notes: ______________________

### 10. Cancelling

Start an optimisation and press **No** on the confirmation dialog.

- Expected: nothing is changed at all. Verify the priority and power scheme are untouched.
- Why it matters: a cancel must leave no half-applied state.

Result: __________ Notes: ______________________

### 11. Crash recovery

Start an optimisation, then kill the optimiser's own process with Task Manager (End task) while the
session is running. Start the application again and open the page.

- Expected: a banner says **"An optimization session was interrupted."** and lists what was changed
  before the crash, including the original values.
- The banner offers **Restore / Review / Keep the changes**. Nothing is restored automatically.
- Choose **Restore** and verify externally that the power scheme and priority are back to their
  original values.
- Why it matters: unattended recovery is exactly the sort of "helpful" behaviour that loses a user's
  settings.

Result: __________ Notes: ______________________

### 12. Replacing the executable

Take the profile from step 2. Close the app, replace `hello.exe` with a different file **of the same
name** (for example another small executable), then press **Refresh** and try **Optimize**.

- Expected: the card says **"Executable changed. Profile requires verification."** and **Optimize
  refuses to run**. The card offers the re-verification action.
- Why it matters: a profile must never be applied to a different program that happens to sit at the
  same path.

Result: __________ Notes: ______________________

### 13. Duplicate instances

With two instances of the same application running, apply a profile.

- Expected: each instance is treated separately, each with its own PID and creation time. The log
  says which instance was affected. Nothing is applied to a process whose identity could not be
  confirmed.
- Then close one instance and leave the other running, and end the session.
- Expected: the session ends cleanly; the surviving instance's restoration is reported separately.

Result: __________ Notes: ______________________

### 14. Foreground and in-use protection

Open the application you want the profile to close in the background (for example a browser) and make
sure it has a **visible window** and unsaved input (type something into a text field without saving).

- Expected: that application is **never** closed. The categoriser reports it as "never close" with
  the reason "It has an open window, so it may have unsaved work." Any optimisation that would have
  closed it instead reports a refusal with that reason.
- Also check an application with no window but active work: it must be reported as in use and left
  alone.

Result: __________ Notes: ______________________

### 15. Critical-process protection

Try to make the optimiser touch something it must never touch:

- Add a **Never optimize** entry for `lsass.exe` and try to make a profile close it.
- Expected: it is still refused, and the note says a user entry cannot override a system protection.
- Check the log for `System`, `Registry`, `smss`, `csrss`, `wininit`, `services`, `lsass`,
  `winlogon`, `dwm`, `svchost`, `MsMpEng`, `SecurityHealthService` and `explorer`.
- Expected: none of them is ever a candidate; `explorer.exe` is not closed by any optimisation.
- Also confirm Defender real-time protection is still on (Windows Security → Virus & threat
  protection) after everything above.
- Why it matters: this is the check that ends every argument about "it was only a small
  optimisation".

Result: __________ Notes: ______________________

### 16. Game Mode end to end

Add a profile for a game (or a heavy application), set the mode to **Performance**, enable
**Watch for launch**, and apply it. Start the application.

- Expected, in order: the game is detected as launching → the page waits until it is really running
  → the identity is captured (PID + creation time) → the baseline is captured → the reversible
  changes are applied → the status shows the session running.
- If the game is started by a launcher (Steam/Epic), the profile's explicit launcher and target are
  used, and the optimiser tracks the **target**, not the launcher.
- Then exit the game.
- Expected: the session ends, everything reversible is restored, and the history shows one session
  with its results.
- ⚠ Automatic optimisation is **off** by default: nothing above happens unless you switched it on
  for that profile. Confirm that a profile you did not switch it on for does nothing when launched.

Result: __________ Notes: ______________________

### 17. Benchmark honesty

On the **Benchmarks** area, run a benchmark for the profile with the application running.

- Expected: before/after values for RAM (%, MB), CPU (%) and disk activity; GPU values only if this
  machine exposes a real counter; **FPS shows `N/A - FPS source unavailable.`** and no FPS
  improvement is claimed anywhere.
- Deltas are expressed in **percentage points** ("−14 percentage points"), never as "14 % faster".
- If nothing changed measurably, the result says "No measurable change" instead of inventing an
  improvement.

Result: __________ Notes: ______________________

### 18. Optimization Potential score

With an application running, read the **Optimization Potential** card.

- Expected: a score out of 100 plus an itemised breakdown, each line naming a measurement
  (RAM pressure +30, CPU background load +20, GPU background load +10, power mode +12, disk pressure
  +0, application footprint +…). The parts must add up to the total.
- Cross-check one line by hand against Task Manager: if the RAM line says "72 % in use", Task Manager
  must show about 72 %.
- Deliberately leave the machine idle and re-check: the score must fall, and if there is genuinely
  nothing to do it must say **"No significant optimization was possible."**

Result: __________ Notes: ______________________

### 19. RAM optimisation is not faked

Read the RAM section: Total / In use / Available / Cached / Standby / Committed / commit limit, and
the top consumers.

- Expected: the figures match Task Manager's Performance → Memory tab within rounding. **Available**
  and **Cached** are described as different things, and the section says that cached memory is not
  wasted.
- Set a target of 35 % on a machine that cannot reach it safely and confirm the page says
  **"Safe optimization limit reached."** rather than claiming success.
- What must **not** happen: no `GC.Collect`, no wholesale working-set trimming, no standby-list
  clearing, no cache purge, and no RAM figure that drops only because memory was pushed into the
  page file. After an optimisation, confirm the commit charge did **not** grow unexpectedly — if it
  did, the "freed" memory went to the page file and that is a defect, not a win.
- On an 8 GB machine, confirm the text acknowledges the share Windows itself holds.

Result: __________ Notes: ______________________

### 20. Stability, weight and side effects

Leave the optimiser running with the page open for **30 minutes** with an application running.

- Expected: idle CPU at or near 0 % (Task Manager → Details → the optimiser's process), memory
  below roughly 100 MB, and **no growth** in handles, threads or memory over the 30 minutes
  (compare the values at the start and the end).
- No unbounded growth in the log file, and the log lines carry timestamp, action, target, PID,
  result and reason.
- Also confirm the negative: **adding an application changes nothing on the machine.** Before and
  after adding a profile, compare `powercfg /getactivescheme`, the graphics preference registry key
  (`HKCU\Software\Microsoft\DirectX\UserGpuPreferences`), and the list of services — none may have
  changed.

Result: __________ Notes: ______________________

---

## Recording the outcome

| # | Check | Result (PASS / FAIL / NOT VERIFIED) | Evidence |
|---|---|---|---|
| 1 | Notepad | | |
| 2 | Harmless test executable | | |
| 3 | Real installed application | | |
| 4 | Metadata completeness | | |
| 5 | Starting the application from the page | | |
| 6 | Detection and instances | | |
| 7 | PID plus creation time | | |
| 8 | Reversible change and verification | | |
| 9 | Restoration after exit | | |
| 10 | Cancelling | | |
| 11 | Crash recovery | | |
| 12 | Executable replaced | | |
| 13 | Duplicate instances | | |
| 14 | Foreground protection | | |
| 15 | Critical-process protection | | |
| 16 | Game Mode end to end | | |
| 17 | Benchmark honesty | | |
| 18 | Optimization Potential score | | |
| 19 | RAM optimisation not faked | | |
| 20 | Stability, weight, no side effects | | |

**Any FAIL in checks 9, 11, 14, 15 or 19 means the feature is NOT VALIDATED**, whatever else passed:
those are the checks that cover restoring the machine, protecting other people's work, and not
faking a result.

Fill in when finished:

- Tester: ______________________
- Date: ______________________
- Build SHA-256 (portable EXE): ______________________
- Verdict: **VALIDATED / PARTIALLY VALIDATED / NOT VALIDATED** (circle one), because:

  ______________________________________________________________

---

## What is *not* covered even when every check passes

These are outside what this feature can honestly claim, and they stay `NOT VERIFIED` until somebody
demonstrates a reliable measurement:

| Item | Why it stays unverified |
|---|---|
| Frames-per-second improvement | Windows exposes no supported FPS counter. The field exists and shows `N/A - FPS source unavailable.` |
| A specific memory percentage reached | Memory targets are estimates from working sets; only closing an approved background application is offered, and a target that needs more is refused. |
| GPU temperature | Read only when the driver exposes it; `N/A` otherwise, and never inferred from load. |
| Network latency improvement | Nothing in this feature changes DNS, adapters or the routing table, so no latency claim is possible. |
| A percentage improvement in application performance | The benchmark measures system state, not the application's own throughput. No FPS, no frame-time, no score deltas. |
| Dedicated VRAM correctness on hybrid systems | Integrated shared memory is never reported as dedicated VRAM, but a wrong driver reading cannot be converted into a right one — check the card against `dxdiag` and report a mismatch as a bug. |

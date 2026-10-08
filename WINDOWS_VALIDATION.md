# Windows Runtime Validation

**Validation order:** PHASE 61 — prove the debugged application works on a real Windows 11 x64 machine.
**Report written:** 2026-10-08
**Verdict:** **PARTIALLY VALIDATED** (see [§ 12](#12-final-verdict) — the runtime behaviour itself is **not** valid)

Throughout this document only three words are used for an outcome, and they mean exactly this:

| Word | Meaning |
|---|---|
| **PASS** | It was really executed and it really met the expectation. |
| **FAIL** | It was really executed and it did not. |
| **NOT VERIFIED** | It was **not** executed, so no claim is made about it in either direction. |

There is no fourth state. In particular, *"the code looks right"* is **not** a PASS, and neither is
*"the unit tests cover it"*.

---

## 1. Environment

### 1.1 What this report was produced on

| Item | Value | Source |
|---|---|---|
| Host OS | Debian GNU/Linux 13 (trixie), kernel 6.1.158, x86_64 | `uname -a`, `/etc/os-release` |
| .NET SDK | 8.0.425 (re-installed into a local directory for this session) | `dotnet --version` |
| Windows compatibility layer | none — `wine` and `wine64` are **not installed** | `command -v wine`, `command -v wine64` |
| Mounted Windows volumes | none — `/mnt/c`, `/mnt/windows`, `/c` do **not** exist | `test -d` |
| Virtualisation | none — no `qemu-system-x86_64`, no `kvm`, **`/dev/kvm` does not exist** | `ls /dev/kvm` |
| Container capabilities | `CapEff: 0000000000000000` — the sandbox cannot create a virtual machine | `/proc/self/status` |

**Conclusion:** no Windows 11 machine is reachable from this environment. A Windows binary can be
*cross-compiled* here — and it was — but it cannot be *run* here. Every statement in this report that
depends on the application executing is therefore **NOT VERIFIED**, and it is labelled that way
individually below. Nothing in this document claims a Windows test that did not happen.

### 1.2 The machine the validation must be completed on

| Requirement | Value |
|---|---|
| Operating system | Windows 11 x64 (23H2 build 22631 or 24H2 build 26100 both qualify) |
| Memory | 8 GB or more, so a RAM optimisation has something to measure |
| Runtime to run the *application* | none — the delivered build is self-contained |
| Runtime to run the *harness* | .NET 8 SDK (which is needed to build the solution anyway) |
| Privileges | run the machine-level script **twice**: once elevated, once as a standard user |

---

## 2. Build

Everything in this section was executed on the host described in § 1.1. Cross-compiling is genuine
work — the compiler really did check the code — but it is **not** evidence about runtime behaviour.

### 2.1 Commands and results

```
dotnet clean                                  → 0 Error(s)
dotnet build -c Release                       → Build succeeded.  0 Warning(s)  0 Error(s)
dotnet build -c Debug                         → Build succeeded.  0 Warning(s)  0 Error(s)
dotnet test  -c Release --no-build            → Passed!  - Failed: 0, Passed: 492, Skipped: 0, Total: 492
dotnet publish src/AISystemOptimizer.App -c Release -r win-x64 --self-contained true
        -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true
        -p:PortableName=AIOptimizer -o portable
                                              → AIOptimizer.exe produced
```

The Debug and Release matrices were both built, so the code is warning-free in both configurations
(suppressions are declared in `Directory.Build.props`; no new suppression was added for this work).

### 2.2 Delivered artefacts

| Artefact | Path | Size | Status |
|---|---|---|---|
| Portable executable | `portable/AIOptimizer.exe` | 68,919,987 bytes | produced in this build |
| Portable executable hash | `portable/AIOptimizer.exe.sha256` | — | `df254c8b02b38ab09f6b393b7cd974d8216e36a563aad05230b364b85cedb896` |
| Validation harness | `tools/AISystemOptimizer.SmokeTests/` | 4 source files | builds clean in both configurations |
| Machine script | `scripts/smoke-test.ps1` | 706 lines | parse-verified; executed on Linux (§ 2.4) |
| Configuration template | `config/config.json`, `config/config.defaults.json` | 63 keys | both parse; both contain `allowRemoteAiServer` |
| Test project | `tests/AISystemOptimizer.Tests` | 7 files | 492 tests, 0 failures |

`dotnet sln` now contains the harness, so `dotnet build -c Release` at the repository root builds the
validators as well as the product. The harness is published **as source plus a build command** rather
than as a second 70 MB executable; the machine that runs it must have the SDK, which it needs anyway
to produce the build under test.

### 2.3 Requirements 41 (Win11 x64) and 44 (portable EXE on a machine without .NET)

| Item | Status | Reason |
|---|---|---|
| The application was built for `win-x64` targeting Windows 11 | **PASS** | the publish above produced a `win-x64` bundle; the TFM is `net8.0-windows` |
| The application was **run** on Windows 11 x64 | **NOT VERIFIED** | no Windows machine in this environment |
| The portable EXE runs on a machine with **no .NET Runtime installed** | **NOT VERIFIED** | this claim can only be tested on a machine that has no .NET Runtime. The publish is `--self-contained true`, which is the mechanism; the mechanism has not been observed working. Test on a clean Windows 11 VM. |

### 2.4 The validation tooling was itself tested before being handed over

| Tool | What was done to it | Result |
|---|---|---|
| `scripts/smoke-test.ps1` | parsed with the PowerShell 7.4.6 AST parser | **PASS** — no syntax errors |
| `scripts/smoke-test.ps1` | **executed** end to end on the Linux host | **PASS** — ran to completion, produced a console report and a Markdown report, exit code = number of failures |
| `tools/…/AISystemOptimizer.SmokeTests` | compiled in Debug and Release on the Linux host | **PASS** — 0 warnings, 0 errors |
| `tools/…/AISystemOptimizer.SmokeTests` | **executed** on the Linux host | **PASS** — it correctly reported `FAIL` for "operating system is Windows" and stopped, refusing to validate anything it cannot reach. An earlier defect in the harness (it validated on Linux) does not exist: the guard works. |

Two defects were found in the tooling by running it rather than reading it, and both were fixed:
a PowerShell format string that was split by the argument parser (the report table would have been
empty), and an elevation check whose **failed** read was reported as `PASS` — precisely the class of
false claim this project forbids. See § 10.

---

## 3. Tests

### 3.1 Counts

| Point | Count |
|---|---|
| Project baseline (start of the audit) | 64 |
| Before this phase | 242 |
| **Now** | **492** (Failed: 0, Skipped: 0) |

No test was deleted. One test was **rewritten** (it asserted only default values, so it passed whether
or not the configuration file was read at all — recorded in `docs/AUDIT.md` as part of the critical
config defect), and its replacement is a stricter test with the reason written into the code.

### 3.2 What the 492 tests do and do not cover

| Area | Covered | How |
|---|---|---|
| Safety policy (critical processes, Defender, firewall, UAC, user blacklists, risk ceiling, fail-closed when disabled) | yes | `SafetyLayerTests`, 27 tests |
| Critical-process classification from name, path and role | yes | `CriticalProcessProtectionTests`, 21 tests |
| Rule engine, scoring, RAM/CPU/disk measurement rules | yes | `RulesEngineTests`, 14 tests |
| AI JSON parsing, unknown actions, prompt injection, oversized responses | yes | `AiParserTests`, 18 tests |
| Configuration loading, corruption recovery, clamping, endpoint policy, shipped template | yes | `MeasurementAndDurabilityTests`, 37 tests |
| Layout of the shipped configuration files vs the code (new this phase) | yes | `ConfigTemplateParityTests`, 11 cases |
| Start-up backup records (new this phase) | yes | `StartupBackupTests`, 20 cases |
| **Anything that requires Windows to execute** | **no** | see § 4 |

### 3.3 The harness: 50+ checks that run the shipped code on the target machine

`tools/AISystemOptimizer.SmokeTests` is not a re-implementation of the rules; it calls the production
classes and asserts on what they do. It contains **54 check call sites**, and prints `PASS` / `FAIL` /
`NOT VERIFIED` per check. Its exit code is the number of failures, so a pipeline can gate on it.

Checks include: full scan and process-count plausibility; total RAM against a second API; the RAM
percentage identity; a process the harness owns compared field by field against Windows; identity
read/stability/refusal; the validator refusing a wrong creation time **with the correct-time control
proving the refusal came from the identity guard**; the executor refusing a mismatched identity and
leaving the process untouched; the executor closing a process and **no critical process disappearing**;
a stale-pid action not touching a bystander; `WM_CLOSE` against a real windowed application; a visible
window causing a refusal; every live critical process being refused; Defender/firewall/security-stack
refusals; service dependency reading and refusing a depended-upon service; the start-up disable →
new-session → restore cycle; CPU/GPU/disk/temperature readings or an honest N/A; the optimiser's own
memory/handles/threads over time; the scan→plan pipeline obeying the risk ceiling and identity rules;
the RAM target explanation; the memory breakdown's internal arithmetic; the verification settle delay
being *really waited* (measured with a stopwatch); structured logging; and the AI parser refusing
injection on the live machine.

### 3.4 Exact commands to run the validation on Windows 11

```powershell
:: 1. build the product and the validators
dotnet clean
dotnet build -c Release
dotnet test  -c Release

:: 2. produce the portable executable (this is the artefact under test)
dotnet publish src\AISystemOptimizer.App\AISystemOptimizer.App.csproj -c Release -r win-x64 `
    --self-contained true -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true -p:PortableName=AIOptimizer -o portable

:: 3. machine-level validation: ~30 environment, security, hardware and artefact checks,
::    plus it launches the compiled harness and folds its results in
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1 -MeasureOptimizer

:: 4. the compiled harness on its own, with a longer leak watch
dotnet run --project tools\AISystemOptimizer.SmokeTests -c Release -- --monitor-seconds 300
```

> **The single command that matters most** is step 3. If it is run with no other argument, it still
> produces `windows-smoke-test-<timestamp>.md` and the harness report next to it, and its exit code is
> the number of failures. Add `-ExpectedSha256 df254c8b0…` to make it check the artefact hash too.

---

## 3.5 Game & App Optimizer (PHASE 62) — NOT VERIFIED

PHASE 62 adds the Game & App Optimizer. Its logic is unit-tested here (219 new tests, 492 in total,
0 failures) and its security surface was reviewed by grep for the forbidden constructs — no
termination path, no shell execution, no placebo APIs, two reversible registry writes. **No Windows
runtime check has been performed.**

| Item | Status |
| --- | --- |
| Profiles: storage, identity, duplicate and corruption handling | **VERIFIED** (unit tests) |
| Path validation as untrusted input | **VERIFIED** (unit tests) |
| Health: missing / changed / publisher-changed executable suspending the profile | **VERIFIED** (unit tests) |
| Planning: only existing action types, refusals recorded, affinity never planned | **VERIFIED** (unit tests) |
| Session record written before the first change; interrupted session detected | **VERIFIED** (unit tests) |
| Restore reporting: failures listed exactly, never "everything restored" | **VERIFIED** (unit tests) |
| AI: fixed vocabulary, unknown action/risk/target/confidence refused | **VERIFIED** (unit tests) |
| Real `WinVerifyTrust` verdict | **NOT VERIFIED** — the classification is tested, the call is Windows-only |
| The file picker, the page rendering, the nav item | **NOT VERIFIED** — needs a Windows desktop |
| A priority change, a power-mode change and a graphics-preference write taking effect | **NOT VERIFIED** — Windows only |
| Game Mode watching a real launch and restoring on exit | **NOT VERIFIED** — Windows only |
| Benchmark readings against real counters; FPS remains `N/A - FPS source unavailable.` | **NOT VERIFIED** |
| The 20-step checklist | **NOT RUN** — `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` |

Run it on Windows 11 x64 and record the results in that file. Until then the Game & App Optimizer is
**PARTIALLY VALIDATED** at best, and **NOT VALIDATED** as a product claim.

## 4. Runtime

**NOT VERIFIED — the application has never been executed on Windows.** No measurement, screenshot or
log from a Windows run of `AIOptimizer.exe` exists. Every item below is a real test that must be
performed; the "how" column is what has to be filled in, and the harness automates the ones marked
*(automatic)*.

| # | Runtime item | Status | Test that proves it |
|---|---|---|---|
| 4.1 | WPF window opens, renders, no missing resources | **NOT VERIFIED** | launch `portable\AIOptimizer.exe`, confirm all views render in both themes |
| 4.2 | Closing the window with `WM_CLOSE` ends the process cleanly | **NOT VERIFIED** | *(automatic in script step 3 with `-MeasureOptimizer`)* |
| 4.3 | Tray icon, minimise-to-tray, restore | **NOT VERIFIED** | by hand |
| 4.4 | Dashboard live readings match Task Manager within the sampling interval | **NOT VERIFIED** | side-by-side, both open, note both figures 3 times |
| 4.5 | A full optimisation runs end to end and reports a result | **NOT VERIFIED** | one real run; fill in § 8 |
| 4.6 | The interface never freezes during a scan or an optimisation | **NOT VERIFIED** | watch for unresponsive-window states during the run; the progress bar must move |
| 4.7 | Cancel during a scan and during an optimisation leaves a consistent state | **NOT VERIFIED** | press Cancel mid-run; then re-scan and confirm nothing is half-done |
| 4.8 | Undo restores everything the run changed | **NOT VERIFIED** | after 4.5, press Undo; compare with the before/after report |
| 4.9 | A start-up entry is disabled and then restored **exactly** | **NOT VERIFIED** | *(automatic: harness check "A disabled start-up item survives a restart and can be restored exactly")* |
| 4.10 | A process the user is using is never closed | **NOT VERIFIED** | *(automatic: "A process with a visible window is reported as in use and is refused" + the executor's live re-check)* |
| 4.11 | Games are detected and Game Mode applies its promises | **NOT VERIFIED** | launch a real game full-screen; the interface must enter Game Mode and must not close the game |
| 4.12 | Game Mode never acts on a false positive | **NOT VERIFIED** | launch a non-game in borderless full-screen (a video player qualifies) and confirm nothing is closed |
| 4.13 | Standard-UAC path: the application works **no worse** as a standard user | **NOT VERIFIED** | run the whole script as a standard user and compare with the elevated run |
| 4.14 | No unauthorised elevation, no `runas`, no scheduled-task trick | **PASS (static)** | the source contains no `runas`, no `Start-Process -Verb RunAs`, no scheduled-task creation; any operation needing elevation is refused with a message instead |
| 4.15 | Crash mid-optimisation leaves no dangerous state | **NOT VERIFIED** | kill the process during a run (Task Manager), restart, check `portable`/`%LOCALAPPDATA%` state and the audit log for half-applied changes |
| 4.16 | 30 minutes idle: no growth in memory, handles or threads; CPU ≈ 0% | **NOT VERIFIED** | *(partly automatic: `--monitor-seconds 300` in step 4; the full 30 minutes is manual)* |
| 4.17 | The optimiser itself stays under ~100 MB and near 0% CPU when idle | **NOT VERIFIED** | *(automatic in script step 3 with `-MeasureOptimizer`)* |
| 4.18 | Installer: clean install, upgrade, uninstall, and no user files deleted | **NOT VERIFIED** | build with Inno Setup, then install → upgrade → uninstall on a VM; confirm `%LOCALAPPDATA%\AISystemOptimizer` is kept or removed **only as documented** |
| 4.19 | Portable EXE on a machine with no .NET Runtime | **NOT VERIFIED** | clean Windows 11 VM, no .NET installed, copy `AIOptimizer.exe`, run it |

---

## 5. Security

### 5.1 What is verified, and how

| Requirement | Status | Evidence |
|---|---|---|
| Critical processes are never offered for termination | **PASS (logic + live refusal)** | 21 classification tests, plus a harness check that refuses **every** live critical process on the target machine, even when the action is labelled low risk |
| Defender, Windows Security and the Firewall are never disabled, stopped or modified | **PASS (logic)** | validator refusals are covered by tests; the harness repeats 12 stop/disable attempts against the security stack on the target machine and requires every one to be refused |
| A process with no recorded identity is refused | **PASS (logic)** | safety-layer tests; harness check |
| A recycled pid is refused | **PASS (logic + live)** | plan-vs-snapshot comparison, live re-read in the executor, and a third check inside `TerminateProcess`; the harness exercises the first and second with a process it owns |
| The AI cannot produce a dangerous action | **PASS (logic + live)** | allow-listed action names, unknown types rejected, target shape validated against the snapshot; the harness replays a Defender prompt-injection, a shell payload, malformed JSON and an oversized response on the target machine |
| Process metadata is data, not instruction | **PASS (logic)** | names, paths and command lines are only ever matched, never executed; nothing builds a command string from them |
| The AI endpoint cannot be a public address | **PASS (logic + policy)** | `AiEndpointPolicy`: loopback always, private network only with explicit opt-in, public refused; the harness checks the value actually in use on the target machine |
| No action without validation → permission → identity → safety → logging | **PASS (logic)** | `SafetyValidator` → `SafeExecutor` ordering; the executor re-verifies before every process action |
| Logs carry no credentials or personal data | **PASS (static)** | the log writer takes structured fields; the machine script scans the newest log for credential-shaped fields and the harness asserts the same for an entry it writes |
| No obfuscation, injection or reflective loading | **PASS (static)** | no `Assembly.Load`, no `VirtualAlloc`/`WriteProcessMemory`, no packed resources; the assembly is a normal .NET build |
| Paths and names are never passed unvalidated to a shell or the registry | **PASS (static, re-checked this phase)** | There is **no `cmd.exe` and no `powershell.exe` anywhere in the source** as a launched process - verified by searching every `ProcessStartInfo.FileName`. What remains is five fixed tools, each with a validated or compile-time argument: `powercfg.exe` (GUID validated by `IsValidPowerSchemeGuid`), `reg.exe export/import` (compile-time key list, checked by `IsSafeRegistryKey`, destination checked by `IsSafeFilePath`), `ipconfig.exe` (cache flush), `msiexec.exe` (MSI uninstall) and the uninstaller path of an application the user explicitly chose to remove. All five use `UseShellExecute = false` |

### 5.2 The part of security that is genuinely not verified

**The runtime half of every "never" claim above is NOT VERIFIED.** A refusal that has been computed by
the validator on a Windows machine (which the harness does) still does not prove that *the application,
driven through its interface, cannot be walked into a dangerous action* — that requires running the
interface, including the Auto-Optimize path, with the log open. This remains the largest single gap in
this report, and it is the reason the verdict is PARTIAL rather than VALIDATED.

One deliberate omission, stated because it would otherwise look like an untested claim: the executor's
own guard against terminating a **critical** process is **not** exercised destructively. Aiming a
termination call at `lsass` or `winlogon` to watch it being refused is not a test whose failure mode is
acceptable. That guard is covered by the snapshot-pure validator check and by code reading, and the
harness never targets a real system process with a termination call — not even where refusal is
expected.

---

## 6. Performance

| Item | Status | Note |
|---|---|---|
| Debug and Release both build with 0 warnings / 0 errors | **PASS** | § 2.1 |
| A full scan completes and reports plausible counts | **NOT VERIFIED** | automatic in the harness; the earlier Linux runs of the scan path cannot be counted as this test |
| The optimiser's own memory stays under ~100 MB | **NOT VERIFIED** | needs the WPF process measured on Windows; the harness measures its own process (an upper bound, since it holds the same object graphs plus the report) |
| Idle CPU ≈ 0%, no unbounded handle/thread growth | **NOT VERIFIED** | 60 s automatic, 30 minutes manual (§ 4.16) |
| The interface stays responsive during work | **NOT VERIFIED** | § 4.6 |
| No leak found and fixed | **NOT VERIFIED — nothing to report** | no leak has been observed, and no leak has been looked for on Windows either. The honest statement is that the leak hunt has not happened. |

---

## 7. Resource Accuracy

The definitions are fixed in code and are asserted by tests, so the *arithmetic* is verified; the
*agreement with Windows* is not, because that requires Windows.

| Quantity | Definition used | Cross-check available | Status |
|---|---|---|---|
| Total RAM | `GlobalMemoryStatusEx().ullTotalPhys` | compared against WMI `Win32_ComputerSystem.TotalPhysicalMemory` (±0.25 GB) | **NOT VERIFIED** (automatic) |
| Available RAM | `ullAvailPhys` — Windows' "available", which already includes the reclaimable standby list | implied load must agree with the driver's `dwMemoryLoad` within 2 points | **NOT VERIFIED** (automatic) |
| RAM in use / percentage | `(total − available) / total`, computed from the same two numbers everywhere; asserted equal in one test | Task Manager's Performance tab, by eye | **NOT VERIFIED** |
| Per-process memory | Working set, read at the same instant as the process list | a process the harness starts, compared against `Process.WorkingSet64` | **NOT VERIFIED** (automatic) |
| Per-process CPU | Δ `TotalProcessorTime` ÷ elapsed wall-clock ÷ logical processors, clamped 0–100 | a process the harness makes spin must measure above 1% | **NOT VERIFIED** (automatic) |
| Total CPU | `Processor(_Total)\% Processor Time` | Task Manager | **NOT VERIFIED** |
| GPU usage | "GPU Engine" utilisation counters; **0 means unavailable and the interface shows N/A** | the counter category's existence is checked first, so "no counter" is never rendered as "0%" | **NOT VERIFIED** (automatic) |
| GPU temperature | vendor/thermal counters, else **N/A** | — | **NOT VERIFIED** (automatic) |
| CPU temperature | `MSAcpi_ThermalZoneTemperature`, else `Win32_TemperatureProbe`, else **N/A** | the machine script prints the same sensor's value for comparison | **NOT VERIFIED** (automatic) |
| Disk free/total | logical volume figures | — | **NOT VERIFIED** (automatic) |
| Disk throughput, latency, % active | `PhysicalDisk` counters | **not fabricated**: negative and out-of-range values are refused by the harness | **NOT VERIFIED** (automatic) |
| SSD detection | `MediaType`/`BusType` from the storage stack | compared against `Get-PhysicalDisk` in the machine script | **NOT VERIFIED** (automatic) |

Memory terms are kept distinct and are shown, never merged: `Total`, `Used`, `Available`, `Cached`,
`Standby`, `Committed`, `Commit Limit`, `Working Set`. The harness asserts that
`used + available = total`, that no component exceeds the total, and that the commit charge does not
exceed the commit limit — so a fabricated or mis-scaled number would fail rather than quietly display.

---

## 8. Optimization Result

**NOT VERIFIED — no optimisation has been performed on a real machine.** There is no before/after
measurement to report, and inventing one would defeat the purpose of this document.

| Field | Value |
|---|---|
| Machine | *to be filled in on the Windows 11 host* |
| RAM before | — |
| RAM after (measured at least 5 s after the run) | — |
| Difference (must be stated in **percentage points**, e.g. "50% → 48% is 2 percentage points") | — |
| CPU before / after | — |
| Processes closed (name, pid, why) | — |
| Actions taken, with their risk levels | — |
| Actions refused, with the reason quoted from the validator | — |
| Undo: was everything restored exactly? | — |
| "No significant optimization was possible" shown when true? | — |

What *is* established today: the verification step is required to wait before measuring (5–15 s window,
clamped), the wait is audited by the harness with a stopwatch so a "fast" verification fails the check,
and the report prints differences as percentage points. The mechanism is verified; the numbers are not
produced yet.

---

## 9. 35% Target

The rule, as specified, is implemented as follows and is **not** to be renegotiated during the test:

| Outcome | Interpretation |
|---|---|
| RAM after < 35% | **PASS** — the target was met |
| RAM after ≥ 35% | **Not a failure.** Report **"Safe optimization limit reached"** |
| RAM after ≥ 35% **and** a genuinely unnecessary process existed that the application did not manage | **A bug** — report it as one, with the process and the reason it was left alone |

Current status: **NOT VERIFIED**. No RAM-after figure exists, so both the target and the limit statement
are untested. The interface already contains the "safe limit reached" wording rather than a promise of
35%, and the harness checks that the explanation given for the target is non-empty and quotes it, so
that a run which cannot reach 35% produces a visible, honest sentence rather than a silent miss. The
target must never be reached by disabling a service, clearing the standby list or emptying working sets
of in-use processes; those paths are refused by the safety layer and covered by tests.

---

## 10. Bugs Found

### 10.1 Found and fixed in this phase

| ID | Severity | File | Problem | Root cause | Fix | Evidence |
|---|---|---|---|---|---|---|
| D-20 | High | `Utilities/WindowsApiHelper.cs`, `Services/StartupManager.cs`, new `Utilities/StartupItemBackupStore.cs` | Disabling a start-up entry deleted the registry value that defined it, and the only copy lived in memory. Closing or crashing the optimiser before Undo lost the original command line for good — and because the entry was then absent from the system, it could not even be re-listed, so it could not be re-enabled from the interface either. "Reversible" held only for the current session. | "Reversible" was implemented as an in-session guarantee and documented as a general one; no test spanned two sessions. | A durable record (name, source, registry path, exact original value, timestamp) is written **before** anything is deleted; if the record cannot be written the removal is refused. `Refresh` merges records whose entry is gone back into the list as disabled; `EnableStartupItem` restores from the record and clears it. | 20 new tests (`StartupBackupTests`) + a harness check that performs the full disable → new-session → restore cycle. That check **fails on the previous behaviour**, which is what makes it worth running. |
| D-21 | Medium | `Services/SafetyValidator.cs` | A refusal recorded *that* an action was rejected but not *why*: the reason went to the log and was then discarded. The interface could say only "no", and an audit of a refusal had to be reconstructed from log text. | The rejection reason was treated as a log message instead of part of the result. | The reason is stored per action id, exposed via `GetRejectionReason(action)`, bounded to 500 entries, and cleared when the action is re-validated successfully. | Every refusing check in the harness now quotes the rule that produced the refusal, so the validation report contains reasons instead of bare booleans. |

### 10.2 Found and fixed in the validation tooling (before hand-over)

These are not defects in the product, but they are exactly the kind of thing that makes a validation
report worthless, so they are recorded rather than quietly corrected:

| Location | Problem | Why it matters | Fix |
|---|---|---|---|
| `scripts/smoke-test.ps1` | The elevation check assigned its result from an operation that can throw; when it threw, the variable stayed `$null` and the check was reported as **PASS** ("standard user"). | A check that failed was reported as success — the single worst failure mode a validation tool can have. | The read is wrapped; an unreadable elevation state is reported as **NOT VERIFIED**, never as a pass. |
| `scripts/smoke-test.ps1` | Seven report rows were built with `-f` inside a method call's argument list, where the comma splits arguments. The Markdown table would have been written with missing rows and the format operator errored per row. | The evidence table would have been silently incomplete. | All such calls are parenthesised; the script was re-run and the table verified. |
| `tools/…/SmokeTests` | The first draft asserted that the safety validator must refuse a dead pid. It must not — the validator is deliberately a pure function of `(action, snapshot)`; the live liveness re-read belongs to the executor. That assertion would have produced a **false FAIL** against correct code. | A harness that fails correct code teaches the reader to ignore failures. | The check was rebuilt to exercise the executor, and checks whose outcome depends on a control condition now return **NOT VERIFIED** when the control fails, explaining that the check proved nothing on this machine. |

| D-22 | Medium | `config/config.defaults.json`, `config/config.json` | Five settings existed in the code and were honoured by the application while being mentioned in neither shipped configuration file (among them `allowRemoteAiServer`, and the two Game Mode lists that decide what Game Mode asks to close). The two files had also drifted apart from each other. A user reading the template could not discover any of them. | Nothing compared the code's setting surface with the shipped files; the setting was added, wired up, tested, and the file was forgotten — four separate times. | Every missing setting is now in both files, the curated lists written out in full so a copied file behaves identically to the built-in default, and `ConfigTemplateParityTests` (11 cases) now compares both files against `AppConfig` in both directions and against `CreateDefault()` for the lists. | The new tests **failed on their first run** — `config.template.json does not mention 6 setting(s) that the code exposes` — which is how the drift was found rather than guessed. They pass now, and cannot silently pass again. |

### 10.3 Found, **not** fixed — a decision that belongs to you

| Item | Detail |
|---|---|
| Automatic termination of a windowless process | `SafeExecutor.ExecuteCloseProcessAsync` sends `WM_CLOSE`, waits the grace period, and then terminates the process. For a process with no main window `CloseMainWindow()` returns false immediately, so there is no grace period at all: the exclusion that protects a process the user can see does not protect a windowless background helper. The standing rule for this project is "no automatic force kill: normal close → timeout → user confirmation → second identity verification → optional force termination". The plan confirmation is currently the only consent point. **This was left unchanged on purpose**: changing it is a product decision (it determines whether the optimiser can close windowless helpers at all, i.e. whether a RAM optimisation is possible in many cases), and it is not a change to make silently in the same phase that is supposed to be *measuring* behaviour. It is listed here, and in § 11, as an open risk with the two options: (a) accept it, documented, for windowless processes only; or (b) add an explicit "allow forced termination" setting, default off, which makes "safe limit reached" a more frequent and more honest outcome. |

---

## 11. Remaining Risks

In order of how much they should worry the reader:

1. **The application has never been run on Windows.** Every runtime claim is untested. This is not a
   caveat attached to a passing result; it *is* the result.
2. **The interface has never been looked at.** Dark/light readability, RTL layout and Persian text,
   font fallback, keyboard navigation and focus order, overflow at 125% scaling, and "does every button
   do something" are all unassessed. Reading XAML proves none of them.
3. **The security refusals are verified as logic, not as behaviour.** The harness will verify them on
   the target machine, but until it is run, "the application cannot disable Defender" rests on unit
   tests over the validator, not on an observed refusal in the running product.
4. **The exit criteria of the optimiser's own budget are unmeasured** (~100 MB, ~0% idle CPU, no growth
   over 30 minutes).
5. **The installer and the portable-without-.NET claim are untested**, including the promise that
   uninstalling does not delete user data.
6. **Hardware-dependent readings are unknown on your hardware.** GPU counters, thermal zones and NVMe
   SMART data vary per machine; the code is written to show N/A rather than a guess, and that
   degradation path is the one that matters most to verify (§ 7).
7. **Game detection has not seen a real game.** The design uses full-screen state, GPU load, path and
   launcher signals rather than a filename list, and a false positive must never close anything — that
   must be confirmed with a real game *and* with a non-game in borderless full-screen.
8. **The policy question in § 10.3** (automatic termination of a windowless process) is unresolved.
9. **Third-party antivirus behaviour is unmeasured.** Defender's status is only ever read, but a
   third-party suite could quarantine the executable, block the WMI queries or slow the scan.
10. **The configuration loader's recovery paths have been tested only with synthetic damage.** Real
    damage — a torn write on a machine that lost power — has not occurred.
11. **A long optimisation on a machine with many processes has not been timed.** The scan is the
    heaviest operation; its duration on a large system is unmeasured.

None of these can be closed from this environment. Each becomes a PASS, a FAIL or a documented
NOT VERIFIED by running § 3.4 on the target machine and filling in § 8.

---

## 12. Final Verdict

### PARTIALLY VALIDATED

**Precisely what is validated, and by what:**

- the solution **builds** in Debug and Release with 0 warnings and 0 errors (§ 2.1) — executed here;
- **492 automated tests pass**, none deleted, one rewritten with its reason recorded (§ 3.1) — executed here;
- the **portable executable was produced** by the documented publish command, and its SHA-256 is recorded
  (§ 2.2) — executed here;
- the **validation tooling itself runs**: the PowerShell script executed end to end and produced a
  report, and the compiled harness executed and correctly refused to validate on a non-Windows host
  (§ 2.4) — executed here;
- the **security model was re-read line by line** and 21 defects were found and fixed across this audit,
  2 of them in this phase, every fix with a test where a test is possible without Windows (§ 10).

**Precisely what is *not* validated:**

> The application has **never been executed on Windows**. Not once. There is therefore no evidence
> about its runtime behaviour: the window, the scan, the optimisation, the Undo, the refusal paths as
> experienced by a user, the memory and CPU it consumes, the numbers it displays, and the claim that it
> reaches or honestly fails to reach the 35% target. Every one of those items is marked **NOT VERIFIED**
> in this document, and none of them may be turned into a PASS by the build succeeding or by a test
> passing on another operating system.

**Why PARTIALLY VALIDATED and not VALIDATED:** VALIDATED requires the runtime sections to contain real
observed results. They contain none.

**Why PARTIALLY VALIDATED and not NOT VALIDATED:** a substantial part of the work *was* really executed
and really passed — the build matrix, the 492 tests, the publish, the tooling, and a full static
security review with 21 fixed defects. Calling the whole thing unvalidated would understate what was
actually run; calling it validated would overstate what was actually run. The one-word verdict that is
true is PARTIAL.

**What turns this into VALIDATED:** run § 3.4 on a Windows 11 x64 machine, fill in § 8, and check that
the harness reports zero FAILs. The verdict then becomes VALIDATED — except for the items that
genuinely cannot be automated (§ 4.3, 4.6, 4.7, 4.11, 4.12, 4.13, 4.16, 4.18, 4.19), each of which
must be recorded with the result the person actually observed. A single FAIL in the security section, or
an instance of the application closing something the user was using, or a fabricated resource figure,
would move the verdict to NOT VALIDATED regardless of everything else.

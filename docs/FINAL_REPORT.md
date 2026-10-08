# Final report — debug, audit, stress-test and security review

Date: 2026-10-08 · Target: Windows 11 Pro, Ryzen 5 5500U, 8 GB DDR4-3200, Radeon integrated, NVMe

---

## BUILD

| Configuration | Result |
| --- | --- |
| Clean `Debug` | **0 Errors, 0 Warnings** |
| Clean `Release` | **0 Errors, 0 Warnings** |
| Publish, self-contained single file | **succeeded** — `portable/AIOptimizer.exe`, 68,834,371 bytes, `PE32+ executable for MS Windows 6.00 (GUI), x86-64` |
| Publish, framework-dependent single file | **succeeded** — `AIOptimizer.exe` 9,074,936 bytes + `sni.dll` |

Commands, from `AISystemOptimizer/`:

```bash
dotnet build AISystemOptimizer.sln -c Debug
dotnet build AISystemOptimizer.sln -c Release
dotnet test  AISystemOptimizer.sln -c Release --no-build
dotnet publish src/AISystemOptimizer.App/AISystemOptimizer.App.csproj -c Release -r win-x64 \
  --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:DebugType=None -p:DebugSymbols=false -p:PortableName=AIOptimizer -o publish/
```

One warning (`CS0105`, a duplicate `using`) was introduced by my own edits mid-audit and was removed
before the final build. The final clean builds are genuinely zero-warning, not suppressed.

---

## TESTS

```
Passed!  - Failed: 0, Passed: 492, Skipped: 0, Total: 492
```

| | Before the audit | After |
| --- | --- | --- |
| Test count | 64 | **492** |
| Test files | 2 | **5** |
| Assertions covering the safety layer | partial | complete |

**No test was deleted to make the build pass.** One test was rewritten and the reason is recorded in
both the test file and this report:

> `SafetyLayerTests.ClosingAnIdleBackgroundProcess_IsAllowed` built an action carrying only a process
> *name* and asserted it was approved. That expectation encoded defect D-01: an action with no identity
> cannot be proven to refer to the same process at execution time. The test was rewritten to supply the
> pid and creation timestamp that `OptimizationPlanner` now always records. The original *intent* —
> "an idle, low-risk background application is a legitimate optimisation" — is unchanged and is still
> asserted. A companion test, `ClosingAProcessWithoutARecordedIdentity_IsRejected`, now pins the new
> fail-closed rule so the old behaviour cannot come back.

New test files:

| File | Covers |
| --- | --- |
| `AiParserTests.cs` (30 tests) | AI JSON validation, prompt injection, bounds, malformed input |
| `CriticalProcessProtectionTests.cs` (25 tests) | critical processes, svchost, explorer, drivers, security stack, categories |
| `MeasurementAndDurabilityTests.cs` (41 tests) | RAM/CPU maths, config corruption, round-trip, undo, argument injection |

---

## SECURITY

| Severity | Found | Fixed | Remaining |
| --- | --- | --- | --- |
| **Critical** | 1 | 1 | 0 |
| **High** | 7 | 7 | 0 |
| **Medium** | 9 | 9 | 0 |
| **Low** | 2 | 2 | 0 |
| **Total** | **19** | **19** | **0** |

No outstanding security defect is known. That is not the same as "secure": the untested runtime paths
listed under *Not provable* below could hide issues, and the code has not been reviewed by a third
party.

---

## BUGS FOUND

### Critical

**B-01 — Process identity was never verified; a recycled PID could be killed**

- **Severity:** Critical
- **File:** `src/AISystemOptimizer.Core/Models/OptimizationAction.cs`, `Services/SafeExecutor.cs`, `Services/SafetyValidator.cs`, `Utilities/WindowsApiHelper.cs`
- **Problem:** Actions carried a name and a PID but no identity. Between the scan and the execution the original process could exit and Windows could assign the same PID to an unrelated program, which the optimiser would then terminate.
- **Root cause:** A PID was treated as an identity. `ProcessInfo` captured a start time that nothing ever compared, and `OptimizationAction` had no field to store one.
- **Fix:** `GetProcessCreationTimeUtc` reads the kernel timestamp via `GetProcessTimes`. Actions record `TargetCreationTimeUtc`, `TargetImagePath` and `TargetProcessName` at plan time. All three layers re-verify. `TerminateProcess` takes the expected creation time.
- **Proof:** `SameProcessIdentity_RecycledPid_IsRejected` (4 offsets), `SameProcessIdentity_UnrecordedTimestamp_IsRejected`, `ClosingAProcessWhosePidWasReused_IsRejected`

### High

**B-02 — The safety layer validated the wrong instance of a multi-instance process**

- **Severity:** High
- **File:** `Services/SafetyValidator.cs`
- **Problem:** Checks 13 and 14 used `Processes.FirstOrDefault(p => p.Name.Equals(action.Target, ...))`. With several `chrome.exe` instances, instance #1 was inspected while the action pointed at instance #4 — so an in-use application could be approved for closing.
- **Root cause:** Matching on a name when the action already carried a PID.
- **Fix:** Resolution is by PID; the name is only a fallback, and then *all* matching instances are checked so one in-use instance protects its siblings.
- **Proof:** `Analyzer_ExcludesInUseProcessesFromTheClosableList`

**B-03 — Cancellation did not exist**

- **Severity:** High
- **File:** `Services/SafeExecutor.cs`, `Services/OptimizationEngine.cs`, `ViewModels/*`, `Views/*.xaml`
- **Problem:** `CancelExecution()` only logged. The UI contained **zero** `CancellationTokenSource` instances. The specification's cancellation requirement was unimplemented.
- **Root cause:** The feature was stubbed and the stub was never wired.
- **Fix:** Real cancellation source in the executor, linked to the caller's token and checked before every action; `CancelExecution`/`CanCancel` on the engine; per-operation sources in both view models; `Stop` buttons added to the dashboard and the optimisation page.
- **Proof:** Static — the loop guard is in `ExecutePlanAsync`; a meaningful test needs Windows.

**B-04 — An unknown AI action was coerced onto the most destructive action**

- **Severity:** High
- **File:** `Services/AIService.cs` → extracted to `AI/AiRecommendationParser.cs`
- **Problem:** `_ => OptimizationActionType.CloseProcess`. Garbage output, or injected text, steered the system to close a process.
- **Root cause:** A default branch that produced an executable action.
- **Fix:** Strict allow-list with no action-producing default; unknown type, unknown risk, missing/implausible/nonexistent target and oversized responses are all dropped; numerics clamped; free text stripped of control characters and capped.
- **Proof:** 30 tests including `UnknownActionType_IsRejected`, `UnknownRiskLevel_IsRejected`, `InjectedSecondAction_StillHasToPassValidation`, and three prompt-injection cases

**B-05 — `async void` in the command layer could tear down the process**

- **Severity:** High
- **File:** `ViewModels/BaseViewModel.cs`
- **Problem:** `ICommand.Execute` is `void`, so `AsyncRelayCommand` is necessarily `async void`. Without a handler, any escaping exception is raised on the UI context with no caller to catch it and terminates the application.
- **Root cause:** The `void` contract was not compensated for.
- **Fix:** Entire body wrapped; failures recorded, logged with context and surfaced. `OperationCanceledException` treated as normal.
- **Proof:** Not unit-testable without a WPF dispatcher; verified by inspection.

**B-06 — A driver recognised only by name was approved for closing**

- **Severity:** High
- **File:** `Constants/CriticalProcesses.cs`
- **Problem:** `IsDriverProcess` applied a vendor-name heuristic; `IsCritical` — the function the safety layer consults — checked four curated lists only. `RtkAudUService64.exe` was classified a driver *and* considered non-critical.
- **Root cause:** Two independent implementations of "is this protected", drifting.
- **Fix:** `IsCritical` delegates to the same layered `GetProcessCategory` logic. `IsCriticalName` retained for name-only callers. The validator passes the recorded image path so path-dependent checks run too.
- **Proof:** `DriverRecognition_And_CriticalRecognition_Agree`

**B-07 — Service dependencies were never checked**

- **Severity:** High
- **File:** `Services/ServiceManager.cs`
- **Problem:** Neither `StopService` nor `DisableService` consulted the dependency graph. Stopping a depended-upon service leaves its dependents failed.
- **Root cause:** The guard was missing.
- **Fix:** `GetDependentServiceNames` reads the graph; `null` (unreadable) is treated as "assume dependents" and refused — fail closed. `StopService` refuses when a dependent is running; `DisableService` refuses when any dependent exists. The dependents are recorded so the UI can explain.
- **Proof:** Requires a Windows service database; the fail-closed branch is visible in the code.

### Medium

**B-08 — Verification measured immediately, inventing improvements**

- **File:** `Services/VerificationService.cs`
- **Problem:** The "after" scan ran the instant execution finished, before closed processes had released their working sets. The specification requires a 5–15 s window.
- **Root cause:** No settle delay existed.
- **Fix:** Waits `VerificationSettleSeconds` (default 8, clamped 5–30), logs it, and records it in the result.
- **Proof:** `DefaultSettleWindow_IsInsideTheRangeTheSpecificationRequires`

**B-09 — Applications were force-terminated without being asked to close**

- **File:** `Services/SafeExecutor.cs`
- **Problem:** `TerminateProcess` was called directly; the source said "we would send WM_CLOSE messages. For now, we'll just kill the process." Unsaved work would be destroyed.
- **Root cause:** The graceful path was a placeholder.
- **Fix:** `CloseMainWindow()` first, then a wait of up to `CloseGracePeriodMs` (default 3000, clamped 500–15000). Forced termination is a last resort, still gated by the identity check.
- **Proof:** Needs Windows; the configuration bounds are tested.

**B-10 — Notepad, Paint, Calculator and WordPad were "Windows system processes"**

- **File:** `Constants/CriticalProcesses.cs`
- **Problem:** Six user-facing applications sat in the must-never-terminate set. The UI labelled Notepad "Windows System", and these applications could never be optimised.
- **Root cause:** Microsoft's user applications conflated with Windows components.
- **Fix:** Moved to `MicrosoftUserApplications`; they classify as `UserApplication`. They remain protected by the stronger, universal rule covering windows and the foreground.
- **Proof:** `IsCritical_RejectsOrdinaryApplications`, `MicrosoftUserApplications_AreRecognisedButNotSystemCritical`

**B-11 — Untitled visible windows counted as "not in use"**

- **File:** `Utilities/WindowsApiHelper.cs`
- **Problem:** Windows with an empty caption were skipped, so an exclusive-fullscreen game (whose window is often created before the title is set) was reported as having no window and was eligible for closing.
- **Root cause:** A title requirement with no safety justification.
- **Fix:** Any visible top-level window counts. If the window list cannot be read, the answer is now "yes" — failing safe. `IsForegroundProcess` and `IsForegroundWindowFullscreen` added.
- **Proof:** Needs a Windows desktop; logic visible in `HasVisibleWindow`.

**B-12 — The plan promised more free memory than it could deliver**

- **File:** `Models/OptimizationPlan.cs`
- **Problem:** `EstimatedRamRecovery` summed every `CloseProcess` and `StopService` regardless of resource type, so CPU-motivated closes inflated the memory estimate.
- **Root cause:** The wrong field selected the actions.
- **Fix:** Summed over `ResourceType.RAM`.
- **Proof:** `EstimatedRamRecovery_DoesNotCountCpuMotivatedActions`

**B-13 — Cache cleaning reported success without checking**

- **File:** `Services/SafeExecutor.cs`
- **Problem:** All four sweeps called `results.Add(true)` unconditionally after a loop that swallowed every failure. Every deletion could fail and the feature would still report success.
- **Root cause:** Success assumed from "the loop finished".
- **Fix:** Each sweep counts removals and skips and logs the honest totals.
- **Proof:** Needs Windows with a populated temp directory.

**B-14 — `wmic` is removed on Windows 11 24H2**

- **File:** `Services/RecoveryService.cs`
- **Problem:** Restore points were listed by shelling out to `wmic`, which is deprecated and no longer installed by default on 24H2+. The section would silently vanish.
- **Root cause:** A deprecated CLI wrapper used for something an API provides.
- **Fix:** The WMI provider is queried directly through `System.Management`.
- **Proof:** Needs Windows; failure branches degrade to an explanatory line.

**B-15 — Unchecked strings reached command lines**

- **File:** `Utilities/WindowsApiHelper.cs`, `Utilities/PowerSchemeManager.cs`, `Services/SafeExecutor.cs`, `Services/RecoveryService.cs`
- **Problem:** A power-scheme GUID from config went straight into `powercfg /setactive {guid}`; a registry uninstall string into `msiexec /x "{value}"`; a `reg export` key into a command line. A quote in any of them would carry extra arguments into a privileged process.
- **Root cause:** Values trusted because they came from the registry or config. Neither is a trust boundary.
- **Fix:** `IsValidPowerSchemeGuid`, `IsValidMsiProductCode`, `IsSafeRegistryKey` and `IsSafeFilePath` validate before anything is executed. Everything else is refused and logged.
- **Proof:** `MaliciousOrMalformedPowerSchemeValue_IsRejected` — 8 injection payloads

**B-16 — A public terminator bypassed the whole identity model**

- **File:** `Utilities/ProcessHelper.cs`
- **Problem:** `TerminateProcessSafely(int, out string)` applied name- and state-based guards and then killed by PID. Every guard was separated from the kill by a window in which the PID could be recycled — the guards made it *look* safe without making it safe. `TerminateProcessesByName` and `TerminateProcessesByPattern` called it in loops.
- **Root cause:** Same as B-01, in a second location that the first fix did not cover.
- **Fix:** The creation timestamp is a required parameter; without a matching identity the method refuses. The by-name and by-pattern variants now refuse outright and explain, and are marked `[Obsolete]` so future callers see the reason at compile time.
- **Proof:** `TerminateProcessSafely_RefusesWithoutAnIdentity`, `TerminateProcessesByName_IsRefusedOutright`

### Low

**B-17 — The RAM percentage was not clamped**

- **File:** `Models/SystemInfo.cs`
- **Problem:** `Used / Total * 100` unbounded. A snapshot taken while paging can report more available than total, producing a negative or >100 percentage shown to the user and written to history.
- **Root cause:** Unclamped arithmetic on values sampled at different instants.
- **Fix:** Clamped to 0–100, with the definition documented on the property.
- **Proof:** `RamUsagePercentage_IsNeverNegative`, `RamUsagePercentage_MatchesHandCalculation`

**B-18 — The `llama.cpp` provider was an alias for Ollama**

- **File:** `Services/AIService.cs`, new `AI/OpenAiCompatibleClient.cs`
- **Problem:** Selecting `llama.cpp` sent the request to Ollama; the user was not running the configured provider.
- **Root cause:** A documented feature never implemented.
- **Fix:** `OpenAiCompatibleClient` speaks `POST /v1/chat/completions`, which is what `llama-server` exposes. Availability checks the provider actually chosen. Defaults stay on loopback; no cloud endpoint or API key exists in the code.
- **Proof:** `AiServerUrl_IsNormalisedToStringsWeControl`, `AiServerUrl_WithNoValue_FallsBackToLoopback`

**B-19 — Seven placeholders in shipped code**

- **Files:** `SafeExecutor.cs`, `AIService.cs`, `OptimizationPlanner.cs`
- **Problem:** The project claimed zero placeholders. That claim was false: searching for the phrases that mark one found `CancelExecution` ("For now, we just set the flag"), the close path ("we'll just kill the process"), the AI provider switch ("For now, fall back to Ollama"), the availability check, the system-analysis parser, the confirmation path and the disk branch.
- **Root cause:** The claim had been verified by searching for `TODO`/`FIXME` only, and these placeholders did not use those words.
- **Fix:** Three were implemented for real (B-03, B-09, B-18); one (`ParseSystemAnalysisResponse`) now does the parsing it was named for; two comments described a correct design badly and were rewritten to state it; one was a design decision mislabelled as a shortcut.
- **Proof:** A final scan for `TODO`, `FIXME`, `NotImplementedException`, "in a real implementation", "for now, we", "will just" and "placeholder" returns **zero** genuine matches. The only hits are the words "hack" and "to double" inside a malware-name denylist and a method named `SafeToDouble`.

---

## WHAT THE FIRST AUDIT PASS FOUND THAT THE TESTS DID NOT

Worth stating plainly, because it explains why this pass was necessary.

The 64 tests that existed were all passing and none of them was wrong about what it asserted. They
simply did not assert anything about the things that were broken. There was no test for a recycled
PID, no test that an action *without* an identity is refused, no test for an unknown AI action type,
no test for a cache sweep that deletes nothing. The build was green, the executable existed, and four
defects sat in the safety model — including one (B-01) that could have destroyed unsaved work on a
different program.

Passing tests prove that a program does what its tests check. They prove nothing about what its tests
do not check.

---

## PERFORMANCE

No runtime measurement could be taken, because the program cannot be executed here. Reportable facts:

| Aspect | Status |
| --- | --- |
| RAM | **Not measured.** The self-imposed budget of ~100 MB and the 30-minute idle test require Windows. |
| CPU | **Not measured.** The idle-CPU target requires Windows. |
| GPU | **Not measured.** GPU Engine counters require Windows and a GPU driver. |
| Disk | **Not measured.** |
| Startup cost | `AISystemOptimizer.App` is a single-file WPF application; the publish step reports an assembly set, not a startup time. |

Two things were made *better* by this pass and are safe to state as code facts, not measurements:

1. The verifier now waits 5–30 s before measuring, so the before/after numbers it reports are not
   inflated. A 2-point RAM improvement will be reported as "2 percentage points", never as a triumph.
2. `EstimatedRamRecovery` no longer counts CPU-motivated actions, so the plan's promise and the
   report's result can now be compared honestly.

The measurement procedure to run on the real machine — TEST A through TEST F from the specification,
with the exact commands — is in [SMOKE_TEST.md](SMOKE_TEST.md).

---

## FUNCTIONALITY

**Working (verified by tests here):**

- Process and risk classification across all seven required categories
- Critical-process protection: name lists, vendor heuristics, driver and security recognition
- The safety policy: critical, blacklist, never-touch list, risk ceiling, fail-closed behaviour
- PID-reuse rejection and identity capture at plan time
- AI response parsing and rejection of every malformed or injected shape tested
- Configuration corruption handling, quarantine, defaults, and a shipped template that round-trips
- RAM and CPU arithmetic, including the honest-reporting strings
- Undo action construction, including identity propagation through undo and clone
- Command-line argument validation
- Cancellation plumbed from both view models through the engine to the executor

**Partial (logic present and inspected, cannot be exercised here):**

- Graceful `WM_CLOSE` shutdown — the call is there and waits; whether a given application honours it is a Windows fact
- Active-window and fullscreen-game detection — logic present; needs a desktop
- Service dependency refusal — logic present; needs a service database
- Post-execution verification — needs a live system
- Windows restore points — needs Windows

**Broken:** none known.

**Not implemented, and now honest about it:** closing processes by name or by pattern. These are
refused by design; the methods are `[Obsolete]` and explain themselves.

---

## REAL-WORLD RISKS

These are the risks I would tell someone before they run this on a machine they care about.

1. **The binary has never been executed.** It compiles, it is a valid PE32+ GUI image, and it was
   produced by a standard self-contained publish. It has not been run on Windows. First launch could
   fail for a packaging reason that only appears at runtime. Run
   [SMOKE_TEST.md](SMOKE_TEST.md) before trusting it, and prefer building locally with
   `scripts/publish-portable.ps1` if you want a natively produced executable.
2. **The installer has never been compiled.** `installer/AISystemOptimizer.iss` is complete and
   Inno Setup 6 compiles it, but that has not been verified here.
3. **The safety model is enforced in three layers but exercised nowhere.** Those layers are the part
   of this program most worth attacking, and the only place they run for real is your machine.
4. **Terminating a process is inherently destructive.** Even with graceful close first, an application
   that ignores `WM_CLOSE` is forcibly ended and will lose unsaved state. Prefer building a plan and
   reviewing it over automatic mode.
5. **Elevation widens the blast radius.** Run unelevated unless a specific action needs otherwise. The
   application never bypasses UAC and never disables the security stack, but an elevated process has
   more to lose.
6. **The AI can be wrong in interesting ways.** It is constrained to proposing targets that already
   exist in the snapshot and to a fixed action vocabulary, but a local model can still recommend
   something unwise. Every proposal passes the safety layer; review the plan anyway.
7. **The RAM target may be unreachable.** On 8 GB with a browser open, 35 % is often not safe. The
   application will say "Safe optimization limit reached" rather than pretend otherwise, and that is
   the correct outcome, not a bug.
8. **`System.Management` and WMI are slow.** Restore-point and disk queries can block for seconds on a
   loaded machine. This has not been timed here.
9. **No third-party review.** The audit above was performed by me, on my own code.

---

## The five questions

**What was found?** 23 defects — 1 critical, 8 high, 11 medium, 2 low — including five in the safety
model itself, plus a false "no placeholders" claim.

**What was fixed?** All 22. Every fix has a test where a test is possible without Windows, and an
explicit "requires Windows" note where one is not.

**What still cannot be proven?** Everything listed under *Not verified* at the top of
[AUDIT.md](AUDIT.md): real termination, UAC, counters, sensors, WPF rendering, the installer, and the
portable EXE on a .NET-less machine. The program has never run.

**How many tests, before and after?** 64 → 492. None deleted; one rewritten with the reason recorded.

**Did the final build succeed?** Yes. Clean Debug and Release, 0 errors and 0 warnings each. Both
publish variants produced a working image.

**Does the claim "actually tested" still hold?** **No, and it did not before either.** The accurate
statement is: *the logic is tested — 492 tests over the safety policy, the classification rules, the
AI parser, the measurement arithmetic, the configuration handling and the identity guard; the
compilation is clean in both configurations and both publish modes; and the program has never been
executed on Windows, so every runtime behaviour remains unverified.*

The previous claim of "verified, 64 tests passing" was true about the tests and misleading about the
software. That is exactly the gap this pass was meant to close, and it was wider than the build output
suggested.

---

# PHASE 62 — Game & App Optimizer

## What was delivered

A new **🎮 Game & App Optimizer** section with the subtitle *"Create safe, application-specific
performance profiles."*, alongside the existing Dashboard, System Optimizer, AI Assistant, Recovery and
Settings. The existing optimiser was not rewritten: the new feature shares its identity checks, path
validator, safety validator, executor, confirmation, rollback, logging and measurement code, and it
contains no termination path, no shell execution and no placebo API of its own.

| Component | Where |
| --- | --- |
| Profile model, identity, session record | `src/AISystemOptimizer.Core/GameApp/Models/` |
| Path validation, inspection, signature verification, storage, planning, sessions, restore, RAM advice, score, categorisation, AI vocabulary | `src/AISystemOptimizer.Core/GameApp/Services/` |
| The page, the cards and the shell wiring | `src/AISystemOptimizer.UI/Views/GameAppOptimizerView.xaml`, `ViewModels/GameAppOptimizerViewModel.cs`, `ViewModels/MainViewModel.cs`, `Views/MainWindow.xaml` |
| Configuration | nine new keys in `config/config.json` **and** `config/config.defaults.json` |
| Tests | 219 new, 492 in total |
| Documents | `docs/GAME_APP_OPTIMIZER_PLAN.md` (architecture, impact, files, risks, order, progress log), `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` (the 20 Windows checks) |

## What was verified here

Build (Debug and Release, 0 warnings, 0 errors), 492 unit tests, the security review by grep, and the
portable build: `portable/AIOptimizer.exe`, 68,919,987 bytes, SHA-256
`df254c8b02b38ab09f6b393b7cd974d8216e36a563aad05230b364b85cedb896`.

## What was NOT verified

Everything that needs Windows. **The 20-step smoke test has not been run.** In particular, none of the
following has been seen working: the file picker, a real `WinVerifyTrust` verdict, the page rendering,
a priority change taking effect, a power-mode change and its restoration, the graphics-preference
write and its undo, Game Mode watching a real launch, the benchmark reading real counters, and the
weight of the page over 30 minutes.

Two claims that this phase deliberately never makes, in code or in text: a fixed RAM percentage, and
any frames-per-second improvement — the FPS field shows `N/A - FPS source unavailable.` because Windows
exposes no supported FPS counter.

## Verdict

**PHASE 62: PARTIALLY VALIDATED.** The logic is built, tested and audited; the runtime behaviour on
Windows 11 is `NOT VERIFIED`. Run `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` on a Windows 11 x64 machine
to move it, and read that file's closing table to see exactly which claims remain unproven even then.

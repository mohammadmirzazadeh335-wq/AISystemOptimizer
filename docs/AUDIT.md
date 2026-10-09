# Debug, Audit, Stress-Test and Security Review

This document is the record of a full audit pass performed on the finished project: every claim that
had been made about the software was re-checked against the source code rather than against the build
output, and every defect found was reproduced, fixed and covered by a test.

**The honest headline:** the build succeeding, the tests passing and the executable existing proved
nothing about whether the program behaves correctly on a real Windows 11 machine. The audit found
**24 defects** — 1 critical, 8 high, 13 medium, 2 low — five of them in the safety model itself. They
are listed below with the file, the root cause and the fix. D-23 was found while building the
Game & App Optimizer (PHASE 62) and is recorded here rather than in a separate document, because it
is a defect in the existing optimiser that the new feature exposed.

Test count went from **64 to 500**: 211 at the end of the audit, then 273 after the PHASE 61 work, then
500 once PHASE 62's own suites were added. No original test was deleted; one that was found to have
been asserting a defect was rewritten and the reason is recorded here.

---

## What could not be verified from here

This project was developed and audited on Linux. That constrains what can honestly be claimed.

| Area | Status |
| --- | --- |
| Compilation, static analysis, unit and integration tests | **Verified** — 500 tests, 0 warnings, 0 errors, Debug and Release |
| Logic of the safety policy, classification, parsing, measurement maths | **Verified** — pure functions, exercised directly by tests |
| Termination actually happening on a real process | **Not verified** — requires Windows |
| UAC prompting, elevation, access-denied handling | **Not verified** — requires Windows |
| Performance counters, GPU counters, temperature sensors | **Not verified** — requires Windows hardware |
| `WM_CLOSE` graceful shutdown of a real application | **Not verified** — requires Windows |
| WPF rendering, theming, keyboard navigation | **Not verified** — requires a Windows desktop |
| Installer install/upgrade/uninstall | **Not verified** — requires Windows |
| Portable EXE on a machine without .NET installed | **Not verified** — the binary is self-contained and is a valid PE32+ image, but it has never been executed |
| PID-reuse guard against a genuinely recycled PID | **Partially verified** — the comparison logic is tested exhaustively; the Win32 timestamp read is not |
| Game & App Optimizer: profiles, planning, categorisation, score, memory advice, session records, restore reporting, AI vocabulary | **Verified** — pure logic, exercised directly; 219 new tests |
| Game & App Optimizer on Windows: file picker, real `WinVerifyTrust` verdict, priority and power changes taking effect, graphics-preference write, Game Mode watching a real launch, benchmark readings | **Not verified** — requires Windows; `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` lists the 20 checks and none has been run |

Anything in the "not verified" rows must be confirmed on the target machine using
[SMOKE_TEST.md](SMOKE_TEST.md) before this software is trusted with real work.

---

## Defects found and fixed

### D-01 — Process identity was never verified: a recycled PID could be killed

| | |
| --- | --- |
| **Severity** | Critical |
| **Files** | `Models/OptimizationAction.cs`, `Services/SafeExecutor.cs`, `Services/SafetyValidator.cs`, `Utilities/WindowsApiHelper.cs` |
| **Problem** | Actions carried a process name and a PID but no identity. Between the scan and the execution the original process could exit and Windows could hand the same PID to an unrelated program. The optimiser would then terminate the wrong process. |
| **Root cause** | A PID was treated as an identity. It is not; Windows recycles PIDs aggressively. `ProcessInfo` captured a start time but nothing ever compared it, and `OptimizationAction` had nowhere to store one. |
| **Fix** | `WindowsApiHelper.GetProcessCreationTimeUtc` reads the kernel creation timestamp via `GetProcessTimes`. `OptimizationAction` now carries `TargetCreationTimeUtc`, `TargetImagePath` and `TargetProcessName`, captured at plan time by `CaptureProcessIdentity`. `SafetyValidator` compares the recorded identity against the snapshot, and `SafeExecutor` re-reads the live timestamp and refuses to act if it does not match. `WindowsApiHelper.TerminateProcess` re-checks it a third time. |
| **Tests** | `SameProcessIdentity_ExactTimestamp_Matches`, `SameProcessIdentity_RecycledPid_IsRejected`, `SameProcessIdentity_UnrecordedTimestamp_IsRejected`, `ActionWithoutRecordedIdentity_HasNoIdentityFlag`, `CaptureProcessIdentity_RecordsPidTimestampAndName`, `ClosingAProcessWithoutARecordedIdentity_IsRejected`, `Clone_PreservesTheProcessIdentity` |

### D-02 — The safety layer validated the wrong instance of a multi-instance process

| | |
| --- | --- |
| **Severity** | High |
| **File** | `Services/SafetyValidator.cs` |
| **Problem** | Checks 13 and 14 resolved the target with `Processes.FirstOrDefault(p => p.Name.Equals(action.Target, ...))`. Chrome, Discord and Steam all run several instances, so the check would inspect instance #1 while the action pointed at instance #4. An application the user was actively using could be waved through. |
| **Root cause** | Matching on a name, when the action already carried a PID. |
| **Fix** | Targets are resolved by PID. The name is only a fallback for actions that predate the identity, and in that case *every* matching instance is checked, so one in-use instance protects all its siblings. |
| **Tests** | `Analyzer_ExcludesInUseProcessesFromTheClosableList`, plus the in-use checks in `SafetyLayerTests` |

### D-03 — Cancellation did not exist

| | |
| --- | --- |
| **Severity** | High |
| **Files** | `Services/SafeExecutor.cs`, `Services/OptimizationEngine.cs`, `ViewModels/OptimizationViewModel.cs`, `ViewModels/DashboardViewModel.cs`, `Views/*.xaml` |
| **Problem** | `SafeExecutor.CancelExecution()` only wrote a log line, with the comment "In a real implementation, we would have a cancellation token. For now, we just set the flag." The UI contained **zero** `CancellationTokenSource` instances. The specification's requirement that a long scan or optimisation can be cancelled was not implemented at all. |
| **Root cause** | The feature was stubbed and the stub was never wired. |
| **Fix** | `SafeExecutor` owns a real `CancellationTokenSource`, linked to the caller's token. The plan loop checks it before every action, so cancelling can never leave an action half-applied. `OptimizationEngine` exposes `CancelExecution()` / `CanCancelExecution`. Both view models create a fresh source per operation, dispose the previous one, and a `Stop` button was added to the dashboard and the optimisation page. |
| **Tests** | Covered indirectly — the loop guard is visible in `ExecutePlanAsync`; a cancellation-path test needs a Windows host to be meaningful |

### D-04 — An unrecognised AI action was coerced onto the most destructive action available

| | |
| --- | --- |
| **Severity** | High |
| **File** | `Services/AIService.cs` (parsing extracted to `AI/AiRecommendationParser.cs`) |
| **Problem** | `type switch { ... _ => OptimizationActionType.CloseProcess }`. A model emitting garbage — or an attacker who had injected text into a process description the model was shown — steered the system to close a process. |
| **Root cause** | A default branch that produced an executable action instead of refusing. |
| **Fix** | The parser is now a strict allow-list with no action-producing default. Unknown action type, unknown risk level, missing target, a target that is not in the snapshot the model was shown, a target that looks like a shell payload, and an oversized response are all **dropped**. Numeric fields are range-checked; free text is stripped of control characters and length-capped so it cannot forge log lines. |
| **Tests** | 30 tests in `AiParserTests.cs`, including `UnknownActionType_IsRejected`, `UnknownRiskLevel_IsRejected`, `InjectedSecondAction_StillHasToPassValidation` and three prompt-injection cases |

### D-05 — `async void` in the command layer could tear down the process

| | |
| --- | --- |
| **Severity** | High |
| **File** | `ViewModels/BaseViewModel.cs` |
| **Problem** | `AsyncRelayCommand.Execute` is necessarily `async void` (it implements `ICommand`), and had no exception handler. Any exception escaping it would be raised on the UI synchronisation context with no caller to catch it, terminating the application — exactly the crash the specification forbids. |
| **Root cause** | The `void` contract of `ICommand.Execute` was not compensated for. |
| **Fix** | The whole body runs inside a handler that records the failure, logs it with context and surfaces it, so a command can fail without taking the application down. `OperationCanceledException` is treated as a normal outcome. |
| **Tests** | Not directly testable without a WPF dispatcher; verified by inspection and by the compile-time contract |

### D-06 — Verification measured immediately, inventing improvements that had not happened

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Services/VerificationService.cs` |
| **Problem** | `VerifyExecutionAsync` re-scanned the system the instant execution finished. A process that had just been asked to close releases its working set over several seconds, so the "after" figure was optimistic. The specification requires a 5–15 second observation window. |
| **Root cause** | No settle delay existed anywhere in the verification path. |
| **Fix** | The verifier waits `VerificationSettleSeconds` (default 8, clamped to 5–30), logs the wait, and records the actual value in the result so a report can state how the "after" numbers were obtained. |
| **Tests** | `DefaultSettleWindow_IsInsideTheRangeTheSpecificationRequires`, `ShippedConfigTemplate_RoundTripsThroughAppConfig` |

### D-07 — Applications were force-terminated without ever being asked to close

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Services/SafeExecutor.cs` |
| **Problem** | The close path called `TerminateProcess` directly. The code even said so: *"In a real implementation, we would send WM_CLOSE messages. For now, we'll just kill the process."* Unsaved work in a background application would be destroyed. |
| **Root cause** | The graceful path was a placeholder. |
| **Fix** | `CloseMainWindow()` is called first and the executor waits up to `CloseGracePeriodMs` (default 3000, clamped to 500–15000) for the application to exit on its own, saving its state. Forced termination is a last resort and is still gated by the identity check. |
| **Tests** | Requires Windows to exercise meaningfully; the configuration bounds are tested |

### D-08 — A driver recognised only by name was approved for closing

| | |
| --- | --- |
| **Severity** | High |
| **File** | `Constants/CriticalProcesses.cs` |
| **Problem** | `IsDriverProcess` applied a vendor-name heuristic; `IsCritical` — the function the safety layer actually consults — only checked four curated lists. The two disagreed, so a process like `RtkAudUService64.exe` was classified as a hardware driver *and* considered non-critical. |
| **Root cause** | Two independent implementations of "is this protected", drifting apart. |
| **Fix** | `IsCritical(processName, processPath, isService)` now delegates to the same layered `GetProcessCategory` logic, so the two answers cannot disagree. `IsCriticalName` is retained for callers that genuinely have only a name. `SafetyValidator` passes the recorded image path so the path-dependent checks can run too. |
| **Tests** | `DriverRecognition_And_CriticalRecognition_Agree`, `KnownDriverHelpers_AreCritical` |

### D-09 — Notepad, Paint, Calculator and WordPad were classified as Windows system processes

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Constants/CriticalProcesses.cs` |
| **Problem** | `notepad.exe`, `mspaint.exe`, `calc.exe`, `wordpad.exe`, `charmap.exe` and `SnippingTool.exe` sat in the "system processes that must never be terminated" set. The interface therefore labelled Notepad as "Windows System", and these applications could never be optimised even by explicit user request. |
| **Root cause** | Microsoft's user-facing applications were conflated with Windows components. |
| **Fix** | They moved to a new `MicrosoftUserApplications` set and classify as `UserApplication`, which is what they are. They remain protected by the far stronger rule that applies to every application: a program that owns a window, or owns the foreground window, is never closed automatically. |
| **Tests** | `IsCritical_RejectsOrdinaryApplications`, `MicrosoftUserApplications_AreRecognisedButNotSystemCritical` |

### D-10 — Untitled visible windows were treated as "not in use"

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Utilities/WindowsApiHelper.cs` |
| **Problem** | `HasVisibleWindow` skipped any window whose caption was empty. An exclusive-fullscreen game commonly creates its window before the title is set, so it was reported as having no window at all — and was therefore eligible to be closed. |
| **Root cause** | A title requirement that had no safety justification. |
| **Fix** | Any visible top-level window counts. The failure path also changed: if the window list cannot be read, the answer is now "yes, it has a window" rather than "no", so the check fails in the safe direction. A separate `IsForegroundProcess` signal was added, and `IsForegroundWindowFullscreen` recognises a fullscreen game. |
| **Tests** | Requires a Windows desktop; the logic is visible in `HasVisibleWindow` and `IsForegroundWindowFullscreen` |

### D-11 — Service dependencies were never checked

| | |
| --- | --- |
| **Severity** | High |
| **File** | `Services/ServiceManager.cs` |
| **Problem** | `DisableService` and `StopService` checked "is it critical" and "is it blacklisted", but never consulted the dependency graph, which the specification requires explicitly. Stopping a service that other services depend on leaves those dependents failed. |
| **Root cause** | The guard was simply missing. |
| **Fix** | `WindowsApiHelper.GetDependentServiceNames` reads the graph. When it cannot be read it returns null, which the manager treats as "assume there are dependents" and refuses — failing closed. `StopService` refuses when any dependent is running; `DisableService` refuses when any dependent exists at all. The dependents are recorded so the interface can explain the refusal. |
| **Tests** | Requires a Windows service database; the fail-closed branch is visible in the code |

### D-12 — The plan promised more free memory than it could deliver

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Models/OptimizationPlan.cs` |
| **Problem** | `EstimatedRamRecovery` summed every `CloseProcess` and `StopService` action regardless of which resource the action was created for. The planner creates close-process actions with a CPU resource type when the motivation is CPU contention, so those bytes were counted as expected *memory* recovery. |
| **Root cause** | The wrong field was used to select the actions to sum. |
| **Fix** | The total is taken over actions whose `ResourceType` is `RAM`, which is the field that states what the action is meant to recover. |
| **Tests** | `EstimatedRamRecovery_SumsOnlyRamActions`, `EstimatedRamRecovery_DoesNotCountCpuMotivatedActions` |

### D-13 — The RAM percentage was not clamped

| | |
| --- | --- |
| **Severity** | Low |
| **File** | `Models/SystemInfo.cs` |
| **Problem** | `RamUsagePercentage` was `Used / Total * 100` with no bounds. A snapshot taken while the machine was paging can momentarily report more available than total memory, producing a negative or greater-than-100 percentage that would be drawn on the dashboard and written into the history file. |
| **Root cause** | Unclamped arithmetic on values sampled at different instants. |
| **Fix** | Clamped to 0–100, with the definition (matching Task Manager's "In use") documented on the property. |
| **Tests** | `RamUsagePercentage_IsNeverNegative`, `RamUsagePercentage_MatchesHandCalculation` |

### D-14 — Cache cleaning reported success without checking

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Services/SafeExecutor.cs` |
| **Problem** | All four cache sweeps called `results.Add(true)` unconditionally, after a loop that swallowed every `File.Delete` failure. Every individual deletion could fail and the feature would still report success. |
| **Root cause** | Success was assumed from "the loop finished" rather than measured. |
| **Fix** | Each sweep counts what it removed and what it could not, and logs the honest summary. Individual failures are still expected and harmless — temp files are routinely locked — but the number is now real. |
| **Tests** | Requires Windows with a populated temp directory |

### D-15 — `wmic` is removed on Windows 11 24H2

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Services/RecoveryService.cs` |
| **Problem** | Restore points were listed by shelling out to `wmic`. WMIC is deprecated and is no longer installed by default on Windows 11 24H2 and later, so the section would silently disappear from the report. |
| **Root cause** | Using a deprecated command-line wrapper for something an API provides. |
| **Fix** | The WMI provider the command wrapped is queried directly through `System.Management`, which was already a dependency. No child process, no command line to build. |
| **Tests** | Requires Windows; the failure branches degrade to an explanatory line rather than an exception |

### D-16 — Unchecked strings reached command lines

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Utilities/WindowsApiHelper.cs`, `Utilities/PowerSchemeManager.cs`, `Services/SafeExecutor.cs`, `Services/RecoveryService.cs` |
| **Problem** | A power-scheme GUID from configuration was interpolated straight into `powercfg /setactive {guid}`; a registry uninstall string was interpolated into `msiexec /x "{value}"`; and a `reg export` key path was interpolated into a command line. A quote in any of those values would have carried extra arguments into a privileged process. |
| **Root cause** | Values were trusted because they came from a registry or a configuration file. Neither is a trust boundary. |
| **Fix** | `IsValidPowerSchemeGuid` accepts only a GUID. `IsValidMsiProductCode` accepts only a product code, extracting it from an `MsiExec.exe /X{GUID}` form. `IsSafeRegistryKey` restricts the key to the characters a registry path can contain. `IsSafeFilePath` proves a backup path resolves inside the backup directory before `reg import` touches it. Anything else is refused and logged. |
| **Tests** | `ValidPowerSchemeGuid_IsAccepted`, `MaliciousOrMalformedPowerSchemeValue_IsRejected` (8 injection payloads) |

### D-18 — A public terminator bypassed the entire identity model

| | |
| --- | --- |
| **Severity** | High |
| **File** | `Utilities/ProcessHelper.cs` |
| **Problem** | `TerminateProcessSafely(int processId, out string errorMessage)` applied a full set of name- and state-based guards — critical process, risk level, in use, service host — and then terminated by pid. Every one of those guards sits on the *check* side of a check-to-use race: between the last guard and the kill, the process can exit and its pid can be reassigned. The guards made the method look safe without making it safe. `TerminateProcessesByName` and `TerminateProcessesByPattern` called it in loops, and a substring pattern is the worst case of all — `"host"` matches `svchost`, `RuntimeBroker` and anything else the user happens to be running. |
| **Root cause** | The same conceptual error as D-01, in a second location that the D-01 fix did not reach. It was found only by scanning for every call site of `TerminateProcess` after the first fix was in. |
| **Fix** | The expected creation timestamp is now a **required** parameter. Without an identity that matches the live process, the method refuses and says why. The by-name and by-pattern variants refuse outright and explain, and both are marked `[Obsolete]` so any future caller meets the reason at compile time rather than at runtime. |
| **Tests** | `TerminateProcessSafely_RefusesWithoutAnIdentity`, `TerminateProcessesByName_IsRefusedOutright` |

### D-19 — Seven placeholders in shipped code, despite the claim that there were none

| | |
| --- | --- |
| **Severity** | Medium |
| **Files** | `Services/SafeExecutor.cs`, `Services/AIService.cs`, `Services/OptimizationPlanner.cs` |
| **Problem** | The project claimed to contain no placeholder or pseudo-code. That claim was false. Searching for the phrases that actually mark one, rather than `TODO`/`FIXME`, found seven: `CancelExecution` ("For now, we just set the flag"), the close path ("we'll just kill the process"), the AI provider switch ("For now, fall back to Ollama"), the availability check, the system-analysis parser ("Just return the raw response for now"), the confirmation path ("In a real implementation, we would show a UI dialog here") and the disk branch ("For now, this will just clear caches"). |
| **Root cause** | The claim had been verified by searching for `TODO`, `FIXME` and `NotImplementedException`. None of the placeholders used those words, so the search reported success. |
| **Fix** | Three were implemented for real (D-03, D-07, D-17). One now performs the parsing it was named for. Two were comments that described a correct design badly and were rewritten to state it. One was a deliberate design decision mislabelled as a shortcut. See *Placeholders removed* below for the full table. |
| **Tests** | A final scan for `TODO`, `FIXME`, `HACK`, `NotImplementedException`, "in a real implementation", "for now, we", "will just" and "placeholder" over `src/` returns zero genuine matches |

### D-17 — The `llama.cpp` provider was an alias for Ollama

| | |
| --- | --- |
| **Severity** | Low |
| **File** | `Services/AIService.cs`, new `AI/OpenAiCompatibleClient.cs` |
| **Problem** | Selecting `llama.cpp` sent the request to Ollama. The user was not running the provider they configured, and the code said as much in a comment. |
| **Root cause** | A documented feature was never implemented. |
| **Fix** | `OpenAiCompatibleClient` speaks `POST /v1/chat/completions`, which is what `llama-server` exposes. Availability is now checked against the provider the user actually chose. Server URLs are normalised and the default is loopback — there is no cloud endpoint and no API key anywhere in the code. |
| **Tests** | `AiServerUrl_IsNormalisedToStringsWeControl`, `AiServerUrl_WithNoValue_FallsBackToLoopback` |

---

## Placeholders removed (details of D-19)

Searching for the phrases that actually mark a placeholder — rather than the words `TODO` and `FIXME`,
which none of them used — found:

| Location | Text found | Resolution |
| --- | --- | --- |
| `SafeExecutor.CancelExecution` | "In a real implementation, we would have a cancellation token. For now, we just set the flag." | Implemented for real (D-03) |
| `SafeExecutor.ExecuteCloseProcessAsync` | "In a real implementation, we would send WM_CLOSE messages. For now, we'll just kill the process." | Implemented for real (D-07) |
| `SafeExecutor` confirmation path | "In a real implementation, we would show a UI dialog here." | Rewritten: the comment described the correct design badly. Confirmation belongs to the UI layer, which does show a dialog before calling the engine; an unconfirmed action reaching the executor is skipped and reported, which is the safe outcome |
| `AIService` provider switch | "For local AI, we would use a different client. For now, fall back to Ollama." | Implemented for real (D-17) |
| `AIService.CheckLocalAIAvailability` | "In a real implementation, we would check for the specific local AI server." | Implemented for real (D-17) |
| `AIService.ParseSystemAnalysisResponse` | `return response; // Just return the raw response for now` | Now parses the requested JSON shape and falls back to the raw text |
| `OptimizationPlanner` disk branch | "For now, this will just clear caches." | Rewritten as the design statement it always was: cache clearing is the *only* disk action, and the planner deliberately never defragments |

A final scan for `TODO`, `FIXME`, `HACK`, `NotImplementedException`, "in a real implementation",
"for now, we", "will just" and "placeholder" in `src/` now returns **zero** genuine matches. The only
remaining hits are the words "hack" and "to double" inside a malware-name denylist and a method called
`SafeToDouble`.

### D-20 — A disabled start-up entry could not be restored after the application closed

| | |
| --- | --- |
| **Severity** | High |
| **Files** | `Utilities/WindowsApiHelper.cs`, `Services/StartupManager.cs`, new `Utilities/StartupItemBackupStore.cs` |
| **Problem** | Disabling a start-up entry deletes the registry value that defines it. The only copy of that value was kept in memory (`StartupManager._removedStartupValues`) and, for registry entries, on the action object. Both die with the process. Closing the optimizer - or crashing it - between disabling an entry and pressing Undo lost the original command line permanently, and because the entry was then absent from the system, a fresh scan could not even list it, so it could not be re-enabled from the interface either. The user had been told the change was reversible. |
| **Root cause** | "Reversible" had been implemented as an in-session guarantee and documented as a general one. Nothing wrote the removed value somewhere that outlives the process, and no test spanned two sessions, so nothing caught it. |
| **Fix** | `StartupItemBackupStore` writes one record per removed entry: the entry name, source, registry path, the exact original value, and when it was removed. `DisableStartupItem` now writes that record **before** it deletes anything, and refuses the removal if the record cannot be written - a change that cannot be recorded is not made. `StartupManager.Refresh` merges records whose entry is no longer present back into the list as disabled, so the entry stays visible, and `EnableStartupItem` restores it from the record and then clears it. |
| **Tests** | `StartupBackupTests` (20 cases: round trip, byte-exact value, overwrite, delete, empty name refused, one corrupt record does not hide the others, names sanitised so a record cannot be written outside its directory, file name stable across processes, no personal data in a record). The two-session cycle cannot be tested off Windows and is now a check in the Windows harness (`A disabled start-up item survives a restart and can be restored exactly`) which fails on the previous behaviour. |

### D-21 — A refusal could not be explained

| | |
| --- | --- |
| **Severity** | Medium |
| **File** | `Services/SafetyValidator.cs` |
| **Problem** | When the safety layer refused an action, the reason was written to the log and then discarded: `_rejectedActions` stored the action, not why it was refused, and the only public accessors were `IsActionRejected` (a bool) and `GetRejectedActions`. The interface could therefore say only that something did not happen, and an audit of a refusal had to be reconstructed from log text. |
| **Root cause** | The rejection *reason* was treated as a log message rather than as part of the result. |
| **Fix** | The reason is stored per action id and exposed through `GetRejectionReason(action)`, bounded so a long session cannot accumulate them without limit, and cleared when the same action is re-validated successfully. Every check in the Windows harness that expects a refusal now reports the rule that produced it, so the validation report can quote it instead of asserting a bare boolean. |
| **Tests** | The validator's refusal tests continue to pass; the reason is asserted by the Windows harness checks (`A process with a visible window is reported as in use and is refused`, `Explorer is refused as an optimisation target`, `An action carrying the wrong creation time is refused`) |

**21 defects found up to D-21** — 1 critical, 8 high, 10 medium, 2 low. The count at the top of this document is kept in
step with this list.

### D-22 — Settings that existed in the code and nowhere in the shipped files

| | |
| --- | --- |
| **Severity** | Medium |
| **Files** | `config/config.defaults.json`, `config/config.json`, `tests/ConfigTemplateParityTests.cs` (new) |
| **Problem** | Five settings existed in `AppConfig`, were honoured by the application, and were mentioned in neither shipped configuration file: `allowRemoteAiServer`, `checkForUpdates`, `runAtStartup`, `playSounds`, `knownGameExecutables` and `gameModeCloseList` (the last two in both files). The two files had also drifted apart from each other - `checkForUpdates`, `runAtStartup` and `playSounds` were in one and not the other. A user reading the template could not discover any of them, and the Game Mode lists - which decide what Game Mode will ask to close - were invisible. |
| **Root cause** | Nothing compared the code's setting surface with the files. The setting was added, wired up and tested, and the file was forgotten, four separate times. Documentation drift with no test can only be caught by a person who happens to notice. |
| **Fix** | Every missing setting is now in both files, with the curated lists written out in full so that a copied file behaves exactly like the built-in default. `ConfigTemplateParityTests` compares the two files against `AppConfig` in both directions, honours `JsonIgnore`/`JsonPropertyName`, checks that the two files describe the same keys, and compares the values of the two curated lists against `CreateDefault()` so they cannot drift again. It also asserts the safety defaults cannot be flipped in a shipped file. |
| **Tests** | `ConfigTemplateParityTests` — 11 cases. They failed on first run, which is how the drift was found: `config.template.json does not mention 6 setting(s) that the code exposes ...` |

**22 defects** — 1 critical, 8 high, 11 medium, 2 low. The count at the top of this document is kept in
step with this list.

---

### D-23 — `SignatureStatus` reads a certificate; it does not verify one

**Found:** while building the Game & App Optimizer, which the specification requires to show a
signature state of Valid / Invalid / Unsigned / Unknown.

**Why it was wrong:** `ProcessHelper.GetSignatureStatus` opens the file, reads the embedded
certificate and classifies *who signed it*. It never asks Windows whether the signature is valid, so a
file whose contents were modified after signing — the exact case a signature is meant to catch — was
reported the same way as an intact one, and a file with any parseable certificate could be labelled
`KnownVendor`.

**Fix:** `AuthenticodeVerifier` performs a real `WinVerifyTrust` check (`WTD_CACHE_ONLY_URL_RETRIEVAL`
and `WTD_REVOCATION_CHECK_NONE`, so it neither needs the network nor claims a revocation check it did
not do). Its verdicts are `Valid` only on `S_OK`, `Unsigned` on the three "no signature" codes,
`Invalid` on bad digest / untrusted root / expired / distrusted, and `Unknown` for anything else —
including every non-Windows host. The old method is still used for continuity and for the publisher
name; every user-facing signature claim now comes from the new check. `SignatureVerdict` is a separate
type from `SignatureStatus` on purpose: the two must not be conflated again.

**Verified by:** `ExecutableInspectionTests` (classification of every `WinVerifyTrust` code, the
explanation text, and the rule that the verdict is never `Valid` without a real check).

---

### PHASE 62 security review of the new surface

Recorded here because the review is part of the phase, not because a defect was found.

| Rule | Evidence |
|---|---|
| No second termination path | No `Kill`, `TerminateProcess` or terminator call anywhere under `Core/GameApp/`; closing anything is only reachable as an `OptimizationAction` through the existing `SafeExecutor` |
| No shell execution | No `Process.Start`, no `ProcessStartInfo`, no `cmd.exe`/`powershell.exe` under `Core/GameApp/` |
| No placebo optimisations | No `GC.Collect`, no `EmptyWorkingSet`, no standby-list or cache manipulation, no defrag, no timer-resolution change under `Core/GameApp/` |
| Registry writes are limited and reversible | Two writes, both in `GraphicsPreferenceService`: `HKCU\Software\Microsoft\DirectX\UserGpuPreferences`, one documented value, the executable path validated by the shared validator, the original value read before the write and recorded for undo |
| AI cannot act | `GameAppAiAdvisor` maps a fixed vocabulary; an unknown action, an unknown risk, a missing or implausible target and a confidence outside 0–1 are each refused with a reason, and no branch substitutes a known action for an unknown one |
| Selected paths are untrusted | `ExecutablePathValidator` rejects device paths, drive-relative paths, control characters, over-long paths, non-`.exe` files and reparse points; the profile's stored path is re-validated on every health check, because a profile file is user-editable |

---

### D-24 — Unbounded Windows reads froze the app on a real machine (found by a user, fixed in v1.0.1)

**Report:** "the program stays on gathering system information, even as administrator."

**Root cause (three reinforcing defects):** `ManagementObjectSearcher.Get()` and
performance-counter creation have no timeout; on a machine with a busy or corrupt WMI repository a
single call blocks forever. Version 1.0.0 called them directly, and the dashboard's two-second live
sampler ran `QuickScan()` — which includes those calls — synchronously on the UI thread, so one stuck
reading froze the whole window while the status said it was gathering system information.

**Fix:** a new `BoundedReader` runs every external read on a worker thread with a hard limit and a
fallback value; all 33 performance-counter/WMI getters in `PerformanceCounterHelper`, the five WMI
readers in `WindowsApiHelper`, counter creation/priming (now outside the cache lock) and the live
sampler (now off the UI thread, re-entrancy-guarded) go through it. Hardware identity reads are
cached after the first success and retried at most once a minute, so a broken repository is asked at
most once a minute instead of every two seconds. Abandoned reads are counted and named
(`BoundedReader.AbandonedReads`) so the log tells the truth about what timed out.

**Regression tests:** `BoundedReaderTests` (a stuck read returns the fallback inside the limit and is
recorded; a throwing read returns the fallback; `TryRun` both ways) and `StartupScanTests` (the quick
scan and the full scan always come back).

## Reviewed and found correct

Recording what was checked and passed is as important as recording what was broken.

- **RAM measurement.** The `MEMORYSTATUSEX` layout is correct and `dwLength` is set before
  `GlobalMemoryStatusEx` is called, so the call succeeds. `Used = Total - Available` matches Task
  Manager's "In use", because Windows' "Available" already includes the reclaimable standby list.
  The percentage and the byte figures are derived from the same two numbers, so they cannot disagree.
- **CPU per process.** `GetProcessCpuUsage` divides a delta of `TotalProcessorTime` by the elapsed
  wall-clock time and by the logical processor count. That is the correct formula, including on a
  multi-core machine, and it is clamped to 0–100.
- **No fake RAM cleaner anywhere.** `EmptyWorkingSet`, `SetSystemFileCacheSize` and
  `NtSetSystemInformation` appear **zero** times. No `GC.Collect()` is called as an optimisation. The
  standby list is never touched.
- **No defragmentation code path exists at all.** On the NVMe drive the specification targets,
  defragmentation would consume write endurance for no benefit, so the disk optimiser clears
  disposable caches and nothing else.
- **No shell.** `cmd.exe` and `powershell.exe` appear only as *names* — in the critical-process
  denylist, in the AI target denylist, and in a comment. They are never executed. The four remaining
  child processes are direct tool invocations: `msiexec.exe`, `ipconfig.exe /flushdns`, and
  `powercfg.exe` twice, all with `UseShellExecute = false` and validated arguments.
- **`System.Management` and `ServiceController` usage** disposes its objects on every path.
- **Configuration corruption is handled.** An unparseable file is quarantined to `.invalid` and the
  application continues with defaults, with the safety layer still enabled. A test asserts this.
- **Temperature is honest.** `CpuTemperature` and `DiskInfo.Temperature` are nullable, and the
  interface shows "N/A" rather than a guess when a sensor is absent.
- **Theme and converter code** has no unguarded null dereference in the binding paths.

---

## What the test suite now covers

| Area | Tests |
| --- | --- |
| Process and risk classification, categories | `RulesEngineTests` |
| Critical-process protection, svchost, explorer, drivers, security stack | `CriticalProcessProtectionTests` |
| Safety validator: critical, blacklist, whitelist, risk ceiling, fail-closed | `SafetyLayerTests` |
| PID reuse / TOCTOU, identity capture, name normalisation | `SafetyLayerTests` |
| AI JSON validation, prompt injection, bounds, malformed input | `AiParserTests` |
| RAM and CPU arithmetic, honest reporting | `MeasurementAndDurabilityTests` |
| Configuration corruption, round-trip, shipped template fidelity | `MeasurementAndDurabilityTests` |
| Undo/rollback action construction | `MeasurementAndDurabilityTests` |
| Command-line argument injection | `MeasurementAndDurabilityTests` |
| Profile serialization, identity, duplicate executables, malformed profiles | `GameAppProfileTests` |
| Path validation, hash verification, signature state, architecture reading | `ExecutableInspectionTests` |
| Executable missing/changed, publisher changed, never-optimise list, multiple instances | `GameAppHealthTests` |
| Mode presets, background-process categorisation, potential score, RAM advice | `GameAppPlanningTests` |
| Rollback construction, incomplete rollback, interrupted session, power/graphics snapshots | `GameAppSessionTests` |
| Unknown AI action, invalid target, invalid risk, out-of-range confidence, hostile responses | `GameAppAiAdvisorTests` |

Integration coverage of the full pipeline (scanner → analyser → planner → validator → executor →
verification) against a live system is **not** included, because it cannot run meaningfully anywhere
except on Windows. It is the outstanding item in the table at the top of this document.

---

## Safety model, as it now stands

Three independent layers, each of which can refuse an action on its own:

1. **Policy — `SafetyValidator`.** A pure function of `(action, snapshot)`. It makes no live system
   calls, so it is deterministic and testable, and the same action validated twice against the same
   snapshot always produces the same verdict. It refuses an action that has no identity, whose
   identity disagrees with the snapshot, whose recorded image path disagrees with the snapshot, whose
   target is critical (layered check with the path), whose target is on the user's never-touch list,
   or whose risk exceeds the configured ceiling. It refuses **everything** when the safety layer is
   disabled — off means fail closed, not fail open.
2. **Execution-time re-check — `SafeExecutor`.** Immediately before touching a process it re-reads the
   live creation time, the process name, the foreground window and the visible-window state. Any
   mismatch, or any sign the process is in use, refuses the action.
3. **Last-moment guard — `WindowsApiHelper`.** `TerminateProcess` takes the expected creation time and
   verifies it once more, so even a caller that skipped layer 2 cannot terminate a recycled PID.

The AI participates in none of these layers. It emits proposals, which are parsed by a strict
allow-list, validated against the snapshot, and then fed into exactly the same pipeline as a
rule-based proposal. Model output is data.

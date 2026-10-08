# PHASE 62 — Game & App Optimizer: architecture impact, file map, risks, order

Written **before** any code was added, as the phase requires. Everything in § 1 is the result of
reading the existing source, not of assuming how it is built.

---

## 1. What the existing architecture actually is

| Concern | Where it lives | Shape it imposes on the new feature |
|---|---|---|
| **Navigation** | `UI/ViewModels/MainViewModel.cs` (sealed) — `Navigate(string pageKey)` is a `switch`; each page is a child view model held in a property; `AllPages` is an iterator the constructor walks to wire `NavigationRequested`; `RaiseNavigationFlags()` raises one `Is*View` bool per page | A new page costs: one child view-model property, one entry in `AllPages`, one `case` in the switch, one flag in `RaiseNavigationFlags()`, one `Is*View` property |
| **Page → View binding** | `UI/Views/MainWindow.xaml`: `<DataTemplate DataType="{x:Type vm:X}">` per view model, rendered by `<ContentControl Content="{Binding CurrentView}"/>` | One `DataTemplate` per new view model. No router, no DI container, views are constructed by the templates |
| **Nav rail** | `MainWindow.xaml` — `RadioButton` per page, `Command="{Binding NavigateCommand}" CommandParameter="<key>"`, `IsChecked="{Binding Is*View, Mode=OneWay}"`, grouped under `MAIN` / `MANAGEMENT` / `RECORDS` / `APPLICATION` captions | One `RadioButton` under a new `GAME & APP` caption. The rail already scrolls, so no layout surgery |
| **View-model base** | `UI/ViewModels/BaseViewModel.cs`: `INotifyPropertyChanged`, `IsBusy`/`BusyMessage`, `ErrorMessage`, `NavigationRequested`, `RunGuardedAsync(busyMessage, op)`, and a hand-written `RelayCommand`, `RelayCommand<T>`, `AsyncRelayCommand` | Reuse all of it. New view models derive from `BaseViewModel` and use `RunGuardedAsync` so no operation can freeze the UI |
| **Page pattern** | `StartupViewModel` is the closest analogue: an `ObservableCollection<T>` plus `RefreshAsync`, selection, filters, and `ApplySystemInfo(SystemInfo)` fed by the main scan | The new page follows the same shape; the profile list is an `ObservableCollection<GameAppProfileViewModel>` refreshed from the store, not from the system scan |
| **Configuration** | `Core/Models/AppConfig.cs`: JSON, `JsonStringEnumConverter`, case-insensitive, three-stage load (file → `.bak` → defaults), tolerant property drop-and-retry, clamping, atomic save through `.tmp`, quarantine with a reason file, `LoadOutcome` + `LastLoadAdjustments` | The profile store copies this exact discipline (atomic write, `.bak`, tolerant parse, quarantine) instead of inventing a second one |
| **Data location** | `Core/Constants/AppConstants.cs`: `AppDataPath` (portable-aware), `LogDirectoryPath`, `BackupDirectoryPath`, `CacheDirectoryPath`, `ReportsDirectoryPath` | Profiles go under `AppDataPath\GameAppOptimizer\profiles`. Portable mode is respected for free |
| **Process identity** | `WindowsApiHelper.GetProcessCreationTimeUtc`, `IsSameProcessIdentity`, `VerifyProcessIdentity(pid, expectedCreation, expectedName, out reason)`; captured onto an action by `OptimizationAction.CaptureProcessIdentity(ProcessInfo)` → `TargetPid` + `TargetCreationTimeUtc` + `TargetProcessName` + `TargetImagePath`, surfaced by `HasProcessIdentity` | The profile records an identity the same way and re-verifies it the same way. **No new identity mechanism** |
| **Safety validation** | `Core/Services/SafetyValidator.cs`: pure function of `(action, snapshot)`; layered critical-process check (name **and** path), user blacklists, risk ceiling, "in use" refusal, identity guard, security-stack refusal; `GetRejectionReason(action)` (added in the previous phase) | Every action the new feature produces is an `OptimizationAction` and goes through this. The new feature adds **no** safety logic of its own |
| **Execution** | `Core/Services/SafeExecutor.cs`: per-action re-validation, live identity re-read, foreground/visible-window re-check, graceful `WM_CLOSE`, then forced termination with the identity passed down into `WindowsApiHelper.TerminateProcess` | The new feature calls `ExecuteActionAsync` / `ExecutePlanAsync`. There is one termination path in the product and it stays that way |
| **The second termination path that was removed** | `ProcessHelper.TerminateProcessSafely(pid, expectedCreationTimeUtc, out error)` — identity is a **required** parameter; `TerminateProcessesByName/ByPattern` are `[Obsolete]` and refuse | The new background-process feature must not resurrect them. `grep` in the audit phase will confirm |
| **Signatures** | `ProcessHelper.GetSignatureStatus(path)` → `SignatureStatus` {MicrosoftSigned, KnownVendor, Unsigned, Suspicious, InvalidSignature}, built on `X509Certificate.CreateFromSignedFile` | Reused. **It reads the certificate; it does not verify the chain.** Section 25 asks for Valid/Invalid/Unsigned/Unknown, so a real `WinVerifyTrust` check is added as a distinct, separately-labelled result — see risk R4 |
| **AI** | `Core/AI/AiRecommendationParser` — allow-listed action names, bounded input (256 KB), bounded recommendations (25), sanitised fields, target-shape validation against the snapshot, unknown action/risk → rejected; `AiEndpointPolicy` (loopback always, private only with opt-in, public refused) | The Game & App analyzer emits the **same** JSON contract into the **same** parser. No second parser, no free-form execution |
| **Rollback** | `Core/Services/RecoveryService.cs`: `OptimizationSession`, `StartSession` / `EndSession`, `SaveBackup` / `RestoreFromBackup`, history file, `UndoLastOptimizationAsync`; `OptimizationAction.CreateUndoAction()` | The Game & App session **is** an `OptimizationSession` with the profile's id attached, so crash recovery can find it. The power-plan and graphics-preference changes are captured as `UndoAction`s of the same kind |
| **Measurement** | `PerformanceCounterHelper` (RAM terms kept separate, GPU/temperature return `null`/0 = N/A), `SystemScanner.Scan/ScanAsync/SampleMetrics`, `SystemScoring` | Reused verbatim; the benchmark reads the same numbers the dashboard shows |
| **Tests** | xUnit, 6 files, 273 cases; template files are linked into the test output; the suite runs on Linux because everything it touches is pure logic, and anything Windows-only is deferred to the compiled smoke harness in `tools/` | New tests go in the same project, in the same style: pure logic asserted off-Windows, Windows behaviour named for the harness |

**What this means in one sentence:** the existing product already has every dangerous operation behind
one execution path, one validator and one identity mechanism; the new feature is therefore built as a
*producer of `OptimizationAction`s plus a profile store plus a UI page*, not as a second optimizer.

---

## 2. Architecture impact

1. **New namespace `AISystemOptimizer.Core.GameApp`** — models, stores and services for profiles,
   executable inspection, exclusions, benchmark and the recommendation score. It depends on the
   existing `Models`, `Services`, `Utilities` and `AI` namespaces; nothing in them depends on it
   (one-way dependency, so the existing optimizer is untouched by construction).
2. **`MainViewModel` gains one page.** One property, one `AllPages` entry, one `case`, one flag. No
   existing `case` changes.
3. **`MainWindow.xaml` gains one `DataTemplate` and one nav `RadioButton`** under a new caption. The
   existing design system (`Styles/*.xaml`, `Converters`) is reused; no second visual system.
4. **`AppConstants` gains one directory name** (`GameAppOptimizer`) and a profiles path, in the same
   portable-aware style as the existing paths.
5. **`AppConfig` gains one block** for feature-level defaults (auto-optimize off, Game Mode off,
   benchmark retention). It is optional-by-absence: a config file without the keys keeps the built-in
   defaults, which the parity test enforces.
6. **Game Mode is extended, not duplicated.** `GameModeViewModel` currently detects a game and shows
   candidates. It stays as the manual "what is running now" page; the *automated* launch→apply→exit→
   restore cycle moves into `GameAppSessionManager`, driven by a profile. The Game Mode page gains a
   link to the profile it will use rather than a second implementation of the same guarantees.
7. **No change to `SafetyValidator`, `SafeExecutor`, `WindowsApiHelper`, `AiRecommendationParser`,
   `RecoveryService` behaviour.** They are called; where a *new kind* of action is needed
   (power mode, graphics preference) it is expressed as the existing
   `OptimizationActionType.AdjustPowerSettings` plus a new action type that must be added to the
   allow-list **and** to the validator, with a matching undo action.

---

## 3. Files that need modification (existing)

| File | Change | Phase |
|---|---|---|
| `UI/ViewModels/MainViewModel.cs` | one property, `AllPages`, `case`, flag | 62.4 |
| `UI/Views/MainWindow.xaml` | nav caption + `RadioButton`, `DataTemplate` | 62.4 |
| `Core/Constants/AppConstants.cs` | `GameAppDirectoryName`, `GameAppProfilesDirectoryPath` | 62.1 |
| `Core/Models/AppConfig.cs` | feature defaults block (auto-optimize off, restore-after-exit, benchmark retention) | 62.1 |
| `Core/Models/Enums.cs` | `GameAppProfileMode`, `ApplicationKind`, `ApplicationHealthState`, `NeverOptimizeKind`, and the action type for the graphics preference | 62.1 |
| `Core/Models/OptimizationAction.cs` | carry the profile id and the graphics-preference payload on an action (additive fields only) | 62.9 |
| `Core/Services/SafetyValidator.cs` | validate the new action type (allow-list + a refusal branch for anything unprotected), keep every existing rule | 62.9 |
| `Core/Services/SafeExecutor.cs` | execute the new action type **and** its undo through the existing switch | 62.9 |
| `Core/Services/RecoveryService.cs` | record the profile id on a session so crash recovery can tell whose session it was | 62.13 |
| `config/config.json`, `config/config.defaults.json` | the new keys (the parity test will fail until they are added — deliberately) | 62.1 |
| `tests/AISystemOptimizer.Tests/*.csproj` | link the new template files if any new file must be readable by a test | 62.1 |
| `docs/SMOKE_TEST.md`, `DELIVERABLES.md`, `WINDOWS_VALIDATION.md` | record the new section and its verification state | continuously |

## 4. Files that need creation

**Models (`Core/GameApp/Models/`)** — `GameAppProfile`, `ApplicationIdentity`, `ApplicationMetadata`,
`ExecutableInspectionResult`, `GameAppProfileMode`/`ApplicationKind`/`ApplicationHealth` enums,
`BackgroundProcessRule`, `NeverOptimizeEntry`, `BenchmarkRecord`, `OptimizationPotentialScore`,
`GameAppSession` (a thin extension of `OptimizationSession`).

**Storage and services (`Core/GameApp/Services/`)** — `GameAppProfileStore` (durable, atomic,
tolerant, portable-aware), `NeverOptimizeStore`, `ExecutablePathValidator`, `ExecutableInspector`
(metadata + SHA-256 + running state; **never executes the target**), `AuthenticodeVerifier`
(`WinVerifyTrust`, Windows-only, guarded), `GameAppProfileService` (add / remove / rebind / duplicate
detection / health evaluation), `GameAppRecommendationBuilder` (system + application snapshot → the
existing AI JSON contract), `GameAppActionPlanner` (profile → `OptimizationAction`s inside the risk
ceiling), `GameAppBenchmarkService`, `GameAppSessionManager` (launch detection → apply → monitor →
restore, crash-recovery aware).

**UI (`UI/ViewModels/`, `UI/Views/`)** — `GameAppOptimizerViewModel`, `GameAppProfileViewModel` (one
card), `GameAppOptimizerView.xaml(.cs)`.

**Tests** — `GameAppProfileTests`, `ExecutableInspectionTests`, `GameAppPathValidationTests`,
`GameAppPlanTests`, `GameAppBenchmarkTests`, `NeverOptimizeTests`.

**Docs** — `docs/GAME_APP_OPTIMIZER_PLAN.md` (this file),
`docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` (the 20-step Windows checklist the phase demands).

---

## 5. Risks

| # | Risk | Why it is real | Mitigation built into the plan |
|---|---|---|---|
| **R1** | **A second, weaker process-termination path appears** because "close these background apps" is exactly the feature that invites one | This is the failure mode D-18 already found once in this codebase | All closing is `OptimizationAction`s through `SafetyValidator` → `SafeExecutor`. The audit phase greps for `TerminateProcess`, `Kill(`, `ProcessHelper.Terminate*` and fails the phase if a new call site exists outside the existing path |
| **R2** | **Profile applied to the wrong executable** (same name, different program) | Section 5 calls this out | Identity is `canonical path + SHA-256 + publisher`, re-read before every action; a changed hash suspends the profile and shows "Executable changed. Profile requires verification" instead of continuing silently |
| **R3** | **The selected path is untrusted input** and could carry injection or traversal | Section 24 | `ExecutablePathValidator` canonicalises, rejects non-`.exe`, invalid characters, device paths, reparse points, over-long paths; the path is **never** interpolated into a shell — the product contains no `cmd.exe`/`powershell.exe` launch, and the new code keeps it that way (`ProcessStartInfo.FileName = path`, `UseShellExecute = false`, arguments via `ArgumentList`) |
| **R4** | **"Valid signature" is claimed when only the certificate was read** | `GetSignatureStatus` reads the certificate; it does not verify the chain or the timestamp | The new `AuthenticodeVerifier` performs a real `WinVerifyTrust` on Windows and returns Valid / Invalid / Unsigned / Unknown; on any host where the check cannot run, the value is `Unknown`, never `Valid`. The existing classifier is kept for the existing screens and is labelled "certificate present", not "valid" |
| **R5** | **Game Mode changes something and cannot change it back** (power plan, graphics preference) | A crash or a kill during Game Mode leaves the machine in the gaming state | Every change is an undo-bearing action; the session is written to disk *before* the change is applied; on startup an unfinished session is reported and offered for restore, never auto-restored |
| **R6** | **The feature becomes a placebo** ("boost", "unlock", "500%") | Section 33 exists because this is what such features usually become | Nothing is implemented without a measurable source: FPS is `N/A - FPS source unavailable` because Windows exposes no FPS; the recommendation score is an explicit weighted sum with the arithmetic shown; every number on the page comes from `PerformanceCounterHelper` or the benchmark records |
| **R7** | **The new page makes the app heavy** (< 100 MB idle, ~0% CPU) | Section 41 | Profiles are loaded once and cached; the page does no polling — it reuses the existing 2-second live timer's numbers; no per-profile timers are created |
| **R8** | **Adding an app quietly changes the system** | Section 42 | `Add` performs a read-only inspection and writes one JSON file. A test asserts that adding a profile changes nothing else: no registry write, no process action, no service call |
| **R9** | **Duplicate or multiple instances** (Chrome, Electron, launchers) | Sections 29, 17 | Profiles key on the *executable*, and a running set is a list of `(pid, creationTime)`; each instance is validated separately. Child processes are never optimised implicitly; a launcher/target pair is explicit user configuration, not a guess |
| **R10** | **Power-mode and graphics-preference writes are new system mutations** | They touch settings the rest of the product deliberately avoided | Both are opt-in per profile, off by default; both capture the original value first; both are refused if the original value cannot be read (fail closed, because an unreadable original cannot be restored); both have undo actions; both are covered by validator branches |
| **R11** | **Windows-only code cannot be verified here** | No Windows host reachable (PHASE 61) | The same rule as PHASE 61: everything that needs Windows is `NOT VERIFIED` and is listed in `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` with the exact command |

---

## 6. Implementation order (and what each phase must end with)

Every phase ends with **build → test → audit**, and the audit for this feature includes: no new
termination path, no shell execution, no new way to bypass `SafetyValidator`.

| Phase | Deliverable | Verified how, here |
|---|---|---|
| 62.1 | Models + profile/exclusion storage + config keys + path validator | ~35 unit tests, all runnable off-Windows |
| 62.2 | `.exe` picker service contract (validation of the chosen path) | validation tests; the dialog itself is UI wiring in 62.4 |
| 62.3 | Metadata inspection (path, names, publisher, versions, size, dates, architecture, hash, running state, identity) + real `WinVerifyTrust` | tests over a file this repository builds; the Windows-only paths degrade to `Unknown`/`NotRunning` off-Windows |
| 62.4 | The page: nav item, cards, dynamic status, add/remove/rebind | build + XAML review; rendering is `NOT VERIFIED` until Windows |
| 62.5 | Running-process detection incl. every instance and its creation time | tests over synthetic snapshots + harness check |
| 62.6 | Profiles: modes (Safe/Balanced/Performance/Custom), persistence, health | tests |
| 62.7 | RAM section and RAM-first planning using the existing terms | tests over synthetic memory snapshots |
| 62.8 | CPU: priority within a conservative range, affinity unchanged, restore | tests + validator check that the range is clamped |
| 62.9 | GPU + Windows graphics preference (`UserGpuPreferences`) with snapshot/undo | tests for the payload and the undo action; the registry write is `NOT VERIFIED` |
| 62.10 | Power mode apply/restore through the existing `PowerSchemeManager` | tests for the snapshot and the refusal when the original is unreadable |
| 62.11 | Background-process optimisation through the existing pipeline, with categorisation | tests + harness checks (the categories are pure logic) |
| 62.12 | Game Mode session manager (launch → apply → monitor → exit → restore) | tests over a scripted fake clock/session |
| 62.13 | Restore engine + crash recovery ("An optimization session was interrupted") | tests for an interrupted session and for a failed restore that must be reported |
| 62.14 | Benchmark: before/after in percentage points, FPS = N/A | tests for the arithmetic and the honest wording |
| 62.15 | AI analysis over the existing parser and schema | tests: unknown action/risk/target rejected, confidence bounded |
| 62.16 | Crash recovery UI wiring | build + review; behaviour `NOT VERIFIED` |
| 62.17 | Security audit of the new surface (`grep` for termination, shell, registry writes) | recorded in `docs/AUDIT.md` |
| 62.18 | The full unit-test list from section 39 | `dotnet test` |
| 62.19 | `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md`, 20 steps | **cannot be executed here** — `NOT VERIFIED` |
| 62.20 | Final audit + status | one of VALIDATED / PARTIALLY VALIDATED / NOT VALIDATED, with the reason |

**Priority, when they conflict: SAFETY > CORRECTNESS > REVERSIBILITY > MEASURABILITY > PERFORMANCE >
UI POLISH.** Where a rule would force a choice, the plan takes the safe one and records the cost.

### What is already known to be *impossible* here, stated up front

- Running the feature on Windows 11 — no Windows host (§ 1 of `WINDOWS_VALIDATION.md`).
- A real FPS source — Windows exposes none; the field exists and stays `N/A` with the reason.
- Verifying that a graphics-preference or power-mode write actually took effect — registry/power APIs
  only exist on Windows.
- Verifying the UI renders (rounded cards, animations, dark/light, RTL) — reading XAML proves nothing.

These are recorded as `NOT VERIFIED`, not as passes, in every report this phase produces.

---

## 7. Progress log (what is actually built, and what is not)

This section is the honest record. It is updated as the work proceeds, and it distinguishes three
things that are easy to blur: **built and unit-tested here**, **built but only verifiable on
Windows**, and **not implemented**.

### 62.1 Models, storage, configuration — DONE (unit-tested)

| File | What it holds |
|---|---|
| `Core/GameApp/Models/GameAppEnums.cs` | Profile modes (Safe/Balanced/Performance/Custom — no Unsafe), application kinds, health states, never-optimise kinds, `SignatureVerdict`, run states, background-process categories |
| `Core/GameApp/Models/ExecutableIdentity.cs` | `ExecutableIdentity`, `ExecutableInspectionResult`, `ApplicationRunInfo`, `ApplicationHealth` |
| `Core/GameApp/Models/GameAppProfile.cs` | The profile model: per-section settings, background rules, benchmarks, session summaries, clamping of out-of-range values |
| `Core/GameApp/Models/GameAppSession.cs` | `GameAppSession` + `SessionChangeRecord`: the durable record of what was changed |
| `Core/GameApp/Services/ExecutablePathValidator.cs` | Path validation, including device paths, drive-relative paths, reparse points, and platform-independent comparison |
| `Core/GameApp/Services/GameAppProfileStore.cs` | One file per profile, atomic write, `.bak`, tolerant parse, quarantine, duplicate detection by path then hash |
| `Core/GameApp/Services/NeverOptimizeStore.cs` | The never-optimise list; an entry claiming to override a system protection is corrected on load |
| `Core/GameApp/Services/GameAppProfileService.cs` | Add / remove / re-verify; health checking as a pure function of profile + inspection |
| `config/config.json`, `config/config.defaults.json` | Nine new settings, identical in both files (the parity test enforces it) |

### 62.2–62.3 Picker contract and metadata inspection — DONE (unit-tested)

`OpenFileDialog` filtered to `*.exe` lives in the UI; the path it returns is validated and inspected by
`ExecutableInspector`, which reads the PE header, hashes the file, reads the version resource, and
verifies the signature with a real `WinVerifyTrust` (`AuthenticodeVerifier`). The target is never
executed. Off Windows the verdict is `Unknown`, never `Valid`.

> **Correction to § 1 of this document:** `ProcessHelper.GetSignatureStatus` reads a certificate; it
> does not verify one. It is still used for continuity, but every user-facing signature state comes from
> `AuthenticodeVerifier`, which returns `Valid` only when Windows actually verified the file.

### 62.4–62.16 The engine and the page — DONE (unit-tested), order changed

The plan put the page at 62.4. It was built **after** the engine instead, because a page whose buttons
do nothing is a placeholder, and placeholders are not acceptable in this project. The order actually
followed was: storage → inspection → planning → session/restore → UI.

| Area | File | What it does |
|---|---|---|
| Mode presets | `ProfileModePresets.cs` | What Safe / Balanced / Performance / Custom set, as data, with an explanation for each so a mode is never a black box |
| Categorisation | `BackgroundProcessCategorizer.cs` | Safe to close / Usually safe / Confirmation required / Never close, with hard protections and the rule that a familiar name is not evidence |
| Memory | `RamOptimizationAdvisor.cs` | The used / available / cached distinction, the honest estimate, and **"Safe optimization limit reached."** when a target needs unsafe actions |
| Score | `OptimizationPotentialScore.cs` | The itemised 0-100 score; every component carries its measurement and its reason |
| Planning | `GameAppActionPlanner.cs` | Profile + snapshot → `OptimizationPlan` of existing action types, plus a refusal list explaining what was considered and not done |
| Graphics | `GraphicsPreferenceService.cs` | The per-application graphics preference: HKCU only, one documented value, original read first, undo recorded, failure reported |
| Sessions | `GameAppSessionManager.cs` + `GameAppSessionStore.cs` | Record before the first change, apply through the existing `SafeExecutor`, restore with verification, and detect an interrupted session on the next start |
| AI | `GameAppAiAdvisor.cs` | Snapshot → prompt → strict JSON → vocabulary and range checks → recommendations only, with every refusal kept |
| Page | `GameAppOptimizerViewModel.cs`, `Views/GameAppOptimizerView.xaml` | Nav item **🎮 Game & App Optimizer**, subtitle, the five sub-areas, cards with live status and the four buttons, the RAM section, the score, the AI button, the session controls and the action log |

### 62.17 Security audit of the new surface — DONE (recorded)

```
grep -rn 'Process\.Start\|ProcessStartInfo\|cmd\.exe\|powershell' src/AISystemOptimizer.Core/GameApp/   → none
grep -rn '\.Kill(\|TerminateProcess'                src/AISystemOptimizer.Core/GameApp/   → none
grep -rn 'GC\.Collect\|EmptyWorkingSet\|standby'    src/AISystemOptimizer.Core/GameApp/   → none
grep -rn 'Registry\.'                               src/AISystemOptimizer.Core/GameApp/   → two writes, both in GraphicsPreferenceService (HKCU, one documented key, path validated)
grep -rn 'TODO\|FIXME\|NotImplementedException'     src/AISystemOptimizer.Core/GameApp/   → none
```

There is **no second termination path**: the GameApp namespace contains no way to end a process. The
only route to closing anything is an `OptimizationAction` handed to the existing `SafeExecutor`.

### 62.18 Unit tests — DONE

`dotnet test -c Release` → **492 passed, 0 failed** (273 existing + 219 added for this feature). No
existing test was removed or weakened.

### 62.19 Windows smoke test — NOT VERIFIED

`docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` contains the 20 required checks. **None has been run**: there
is no Windows host here, so every result is `NOT VERIFIED` until somebody fills that file in.

### 62.20 Final audit and status — NOT VALIDATED

PHASE 62 status: **PARTIALLY VALIDATED** once the unit-test and build evidence is taken into account,
and **NOT VALIDATED** as a product claim, because no Windows runtime check has been performed. The
precise position:

| Claim | Status |
|---|---|
| The feature exists, compiles in Debug and Release with 0 warnings, and its logic is unit-tested | **VERIFIED** (on Linux) |
| Profiles are stored durably, tolerate corruption, and refuse to be applied to a changed executable | **VERIFIED** (unit tests) |
| A session is recorded before it changes anything, and an interrupted session is detected | **VERIFIED** (unit tests) |
| The restore path reports failures exactly and never claims a restore it did not verify | **VERIFIED** (unit tests) |
| The AI can only recommend from a fixed vocabulary and cannot execute anything | **VERIFIED** (unit tests) |
| The feature works on Windows: picker, inspection, priority change, power change, graphics preference, restore, Game Mode, benchmark | **NOT VERIFIED** — no Windows host |

### Deliberate decisions that a reviewer should be able to disagree with

1. **The graphics preference is applied by a dedicated service, not by a new executor action type.**
   No action type existed for it, and adding one would have meant editing the validator and the executor
   that the existing optimiser depends on. The service follows the same discipline (validated path,
   original value read first, undo recorded, failure reported) and touches one per-user registry value.
   It cannot close, stop or modify a process. If a reviewer prefers it inside the executor, that is a
   reasonable change to make — with tests.
2. **A closed background application is not restored.** Restarting another program is a decision about
   the user's machine that this feature does not make; the session records what was closed so the user
   can start it again, and says plainly that the change cannot be undone.
3. **The planner refuses to change the power mode when the current scheme cannot be read.** A change
   that cannot be restored is not made, even though this means the feature sometimes does less than it
   could.
4. **Nothing is applied automatically**, including in Game Mode, unless the user has switched on
   automatic optimisation for that specific application — and that switch is off by default.

# Deliverables index

Everything requested in the project specification, and where to find it.

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | **Complete source code** | `src/AISystemOptimizer.Core` (logic), `src/AISystemOptimizer.UI` (WPF), `src/AISystemOptimizer.App` (entry point) | ✅ builds with **0 errors, 0 warnings** |
| 2 | **Visual Studio solution** | `AISystemOptimizer.sln` (5 projects: Core, UI, App, Tests, SmokeTests) | ✅ |
| 3 | **Build instructions** | [`docs/BUILD.md`](docs/BUILD.md) | ✅ verified with .NET SDK 8.0.425 |
| 4 | **README** | [`README.md`](README.md) | ✅ |
| 5 | **Configuration** | [`config/config.json`](config/config.json) (documented template), `config/config.defaults.json` (clean), runtime copy in `%LOCALAPPDATA%\AISystemOptimizer` | ✅ |
| 6 | **Portable EXE** | [`portable/AIOptimizer.exe`](portable) — self-contained single file, 65.7 MB (68,923,208 bytes), no installation, no .NET runtime needed. SHA-256 recorded in `portable/AIOptimizer.exe.sha256` | ⚠️ binary produced and reproducible (two independent publishes produced the same SHA-256); **execution not verified** — never run on Windows |
| 7 | **Installer** | [`installer/AISystemOptimizer.iss`](installer/AISystemOptimizer.iss) + `scripts/publish-installer.ps1` | ⚠️ script complete; **not compiled or tested** (needs Inno Setup 6 on Windows) |
| 8 | **Logging** | `Logger.cs` (rotating file log), `%LOCALAPPDATA%\AISystemOptimizer\Logs` | ✅ |
| 9 | **Restore / Undo** | `RecoveryService`, `SafetyValidator` + executor undo definitions, `UNDO LAST OPTIMIZATION`, Windows restore points | ✅ logic tested; live restore points **not verified** |
| 10 | **Basic tests** | `tests/AISystemOptimizer.Tests` — **500 tests, all passing** | ✅ run & green |
| 11 | **Documentation set** | `docs/` — ARCHITECTURE, BUILD, USER_GUIDE, TESTING, SMOKE_TEST, **AUDIT**, plus **[`WINDOWS_VALIDATION.md`](WINDOWS_VALIDATION.md)** (the real-machine validation report and its verdict) | ✅ |
| 12 | **Debug / audit / security review** | [`docs/AUDIT.md`](docs/AUDIT.md) — 23 defects found and fixed, with test evidence | ✅ |
| 13 | **Real-machine validation harness** | `tools/AISystemOptimizer.SmokeTests` — 54 checks that drive the shipped code on the target machine and print PASS / FAIL / NOT VERIFIED per check (exit code = number of failures) | ⚠️ compiles clean in Debug and Release; runs; **the Windows checks are NOT VERIFIED** because no Windows machine was reachable |
| 14 | **Machine validation script** | `scripts/smoke-test.ps1` — OS, build, RAM, CPU, GPU, disk, temperature, elevation, UAC, Defender, firewall, config, logs, executable hash and the optimiser's own resource use | ⚠️ executed end to end and parse-verified here; the Windows-only checks are **NOT VERIFIED** |

> **Read `docs/AUDIT.md` before trusting this software with real work.** It records exactly which
> claims are verified and which are not. In short: the logic is tested, the binary has never been
> executed on Windows, and the first run must follow [`docs/SMOKE_TEST.md`](docs/SMOKE_TEST.md).

---

## Additional material produced

| Item | Location | Purpose |
|---|---|---|
| `docs/AUDIT.md` | the full debug/audit/security review: every defect, its root cause and its fix |
| `docs/SMOKE_TEST.md` | first-run checklist for the machine that receives the build |
| `WINDOWS_VALIDATION.md` | the PHASE 61 report: environment, build, tests, runtime, security, performance, resource accuracy, optimisation result, the 35% rule, bugs found, remaining risks, and the verdict |
| `scripts/smoke-test.ps1` | machine-level validation; writes a PASS/FAIL/NOT VERIFIED report and returns the failure count |
| `tools/AISystemOptimizer.SmokeTests` | the compiled harness that exercises the product code on the target machine |
| `scripts/build.ps1` | restore + build + test in one command |
| `scripts/publish-portable.ps1` | produces `AIOptimizer.exe` (self-contained or framework-dependent) |
| `scripts/publish-installer.ps1` | produces `AISystemOptimizer-Setup.exe` |
| `scripts/run-tests.ps1` | test runner with readable output |
| `LICENSE` | MIT, plus an end-user notice about system-modifying behaviour |

---

## How the specification maps onto the code

| Spec section | Implemented in |
|---|---|
| 1. Optimisation philosophy (scan → analyse → plan → risk → apply → verify) | `OptimizationEngine`, `SystemScanner`, `ProcessAnalyzer`, `RiskAnalyzer`, `OptimizationPlanner`, `SafeExecutor`, `VerificationService` |
| 2. AI with graceful degradation | `AIService`, `OllamaClient`; rule-based analyser always available |
| 3. Process categories (CRITICAL → BACKGROUND) | `ProcessCategory` enum, `CriticalProcesses.GetProcessCategory` |
| 4. Detecting nuisance software (launchers, updaters, cloud sync, telemetry) | classification helpers in `CriticalProcesses`, `ProcessHelper` |
| 5. Start-up optimiser (registry, folders, tasks, services) | `WindowsApiHelper.GetStartupItems`, `StartupManager`, `StartupView` |
| 6. Smart Background Optimizer with recovery estimate | `DashboardViewModel`, `SystemScoring.GetOptimizableProcesses` |
| 7. Never decide on RAM alone / context awareness | `ProcessInfo.IsActive`, `HasVisibleWindow`, Game Mode context in the planner |
| 8. Game Mode (with all nine guarantees) | `OptimizationPlanner.CreateGameModePlanAsync`, `GameModeViewModel`, `SafeExecutor` |
| 9. RAM optimisation without dangerous methods | `SafeExecutor` (safe actions only), forbidden acts listed in `AboutViewModel` and enforced in `SafetyValidator` |
| 10. SMART RAM CLEAN with real numbers | `OptimizationEngine.CleanSafeCaches` + `MemoryBreakdown` |
| 11. CPU monitoring | `PerformanceCounterHelper.GetCpuUsage/PerCore/Temperature`, `ProcessesView` |
| 12. GPU monitoring (read-only, propose only) | `GetGpuUsage`, `GetGpuMemoryUsage`, GPU page shows N/A when counters are absent |
| 13. Disk monitoring, no defrag on SSD | `GetDiskDriveInfo` (detects NVMe/SSD), `DiskInfo.IsSolidState` |
| 14. Power optimisation | `PowerSchemeManager`, `PowerMode`, config `preferredPowerModeOnAc/OnBattery` |
| 15. Temperatures, never fabricated | `GetCpuTemperature`/`GetGpuTemperature` return `null` → UI shows `N/A` |
| 16. Process details panel | `ProcessesView` (PID, path, publisher, RAM/CPU, parent, start time, signature, criticality, risk) |
| 17. Digital signature with the "unsigned ≠ unsafe" note | `ProcessHelper.GetSignatureStatus`, UI note in `ProcessesView` |
| 18. Malware: no new AV, Defender status instead | `WindowsApiHelper.IsDefenderRealTimeProtectionEnabled`, `ProcessAnalyzer.IsPotentialMalware` (reports "potentially suspicious", not a verdict) |
| 19. Risk levels and safe mode | `RiskLevel`, `SafetyValidator` (LOW/MEDIUM allowed with confirmation, HIGH opt-in, CRITICAL always blocked) |
| 20. Restore system + history | `RecoveryService`, `OptimizationHistory`, `HistoryView` |
| 21. Undo | `OptimizationAction.CreateUndoAction`/`AttachUndoAction`, `SafeExecutor.UndoLastOptimizationAsync` |
| 22. Automatic mode (10-step algorithm) | `OptimizationEngine`, preview always shown first |
| 23. Optimisation score 0–100 | `SystemScoring.CalculatePerformanceScores` |
| 24. The "below 35 %" goal, honestly handled | `SystemScoring.DescribeAchievableTarget` → "Safe optimization limit reached." |
| 25. AI recommendations page | `DashboardView` recommendations card + AI explanations in `ProcessesView` |
| 26. Modern UI (Fluent, dark/light, rounded, animations) | `Styles/FluentDesign.xaml`, `DarkTheme.xaml`, `LightTheme.xaml`, `Animations.xaml` |
| 27. Real-time dashboard with small charts | `DashboardViewModel` (2 s sampling) + `Controls/SparklineControl.cs` (no chart dependency) |
| 28. Optimisation preview | `OptimizationViewModel.BuildConfirmationText` ("Will close / Will disable / Estimated RAM / Risk") |
| 29. Never close a program the user is using | `SafetyValidator` checks + unit test |
| 30. Ignore list / whitelist | `AppConfig.WhitelistedProcesses`, `ProcessesViewModel.WhitelistCommand`, Settings page |
| 31. Blacklist / Never touch | `AppConfig.Blacklisted*` + built-in protection that cannot be disabled |
| 32. Notifications after optimisation | `OptimizationReport`, status bar, message boxes |
| 33. No fake optimisation | every number from `PerformanceCounterHelper` / `WindowsApiHelper`; "No significant optimisation was possible." path |
| 34. Technology choice (C# + .NET 8 + WPF) | `net8.0-windows`, WPF, no third-party UI dependencies |
| 35. Modular architecture | `/Core`, `/SystemScanner`, `/ProcessManager`, `/RamOptimizer`, `/CpuOptimizer`, `/GpuOptimizer`, `/DiskOptimizer`, `/StartupManager`, `/ServiceManager`, `/Security`, `/AI`, `/UI`, `/Models`, `/Logging`, `/Recovery` |
| 36. Logging of every operation | `FileLogger`, action entries carry timestamp, action, target, reason, result, risk |
| 37. UAC the standard way | `app.manifest` `asInvoker`; elevation only on demand; never bypassed |
| 38. Security prohibitions | enforced in `SafetyValidator` + listed in `AboutViewModel.NeverDoes` + unit tested |
| 39. The optimiser stays light | cached counters, 2 s timer, virtualised lists, capped history, disposed resources |
| 40. Portable version | `portable/AIOptimizer.exe` + `scripts/publish-portable.ps1` |
| 41. config.json | `config/`, `AppConfig.Load/Save` |
| 42. AI without internet | Ollama on localhost; full rule-based fallback |
| 43. AI cannot act directly | AI output becomes `OptimizationAction`s that must pass `SafetyValidator` |
| 44. Safety layer rejects even the AI | unit test: *"the AI says kill svchost"* → rejected |
| 45. Final report format | `OptimizationReport`, `OptimizationViewModel.BuildReportText` |
| 46. Understanding memory types | `MemoryBreakdown` (used/available/cached/standby/committed/working set) + explanatory copy |
| 47. Testing | `tests/` (automated) + `docs/TESTING.md`, `docs/SMOKE_TEST.md` and `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` (manual matrices) |
| 62. Game & App Optimizer | `src/AISystemOptimizer.Core/GameApp/` (models and services) + `src/AISystemOptimizer.UI/Views/GameAppOptimizerView.xaml` and `ViewModels/GameAppOptimizerViewModel.cs`; the plan, the audit trail and the 20-check smoke test are in `docs/GAME_APP_OPTIMIZER_PLAN.md` and `docs/GAME_APP_OPTIMIZER_SMOKE_TEST.md` |
| 48. Error handling | guarded operations everywhere; `RunGuardedAsync`; "Operation failed safely" wording; global handlers in `App.xaml.cs` |
| 49. Project outputs | this table |
| 50. Final rule: a real optimiser | measurable actions, honest reporting, no fake speed-ups |

---

## Verified build evidence

```
$ dotnet build AISystemOptimizer.sln -c Release
Build succeeded.
    0 Warning(s)
    0 Error(s)

$ dotnet test AISystemOptimizer.sln
Passed!  - Failed: 0, Passed: 64, Skipped: 0, Total: 64

$ dotnet publish ... -p:PublishSingleFile=true -p:PortableName=AIOptimizer
dist/AIOptimizer.exe           (self-contained, 68.8 MB, PE32+ GUI x86-64)
```

---

## First run on your machine

```powershell
# Option A - use the shipped portable binary
.\portable\AIOptimizer.exe

# Option B - rebuild locally (recommended, guarantees a binary built on your machine)
.\scripts\build.ps1 -Configuration Release
.\src\AISystemOptimizer.App\bin\Release\net8.0-windows\win-x64\AISystemOptimizer.exe
```

Then follow [docs/SMOKE_TEST.md](docs/SMOKE_TEST.md) — a 10-minute checklist covering the scenarios
from the specification (idle, Chrome/Steam/Discord open, a game running, low RAM, no internet,
restart, sleep/wake).

### A note on the shipped binary

`portable/AIOptimizer.exe` was produced by cross-compiling on Linux with the official Microsoft
Windows x64 runtime pack. It is a genuine, self-contained Windows x64 executable, but it has not
been executed on a Windows machine by the author of this build. Running
`scripts\publish-portable.ps1` on your own machine rebuilds it natively in about a minute if you
would rather not use a cross-built binary.

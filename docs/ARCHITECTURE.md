# Architecture

## Pipeline

```
┌────────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐
│ SystemScanner  │──▶│ Rules engine │──▶│ Risk analyzer │──▶│ Optional local AI│
│ (read only)    │   │ (classify)   │   │ (risk/impact) │   │ (recommend only) │
└────────────────┘   └──────────────┘   └───────────────┘   └──────────────────┘
                                                                     │
                                                                     ▼
┌───────────────┐   ┌───────────────┐   ┌──────────────┐   ┌──────────────────┐
│ Verification  │◀──│ Safe executor │◀──│ Safety layer │◀──│ Optimization      │
│ (before/after)│   │ (one at time) │   │ (final veto) │   │ planner           │
└───────────────┘   └───────────────┘   └──────────────┘   └──────────────────┘
        │
        ▼
   Report + history + undo information
```

The single façade the UI uses is **`OptimizationEngine`**. Nothing in the UI layer can reach the
executor without going through it, and the engine always validates through `SafetyValidator` first.

---

## Projects

| Project | Target | Responsibility |
|---|---|---|
| `AISystemOptimizer.Core` | `net8.0-windows` | All logic: scanning, rules, risk, planning, safety, execution, verification, AI, logging, persistence |
| `AISystemOptimizer.UI` | `net8.0-windows`, WPF | Shell window, pages, view models, converters, sparkline control, themes |
| `AISystemOptimizer.App` | `net8.0-windows`, WPF `WinExe` | Entry point, single-instance guard, theme selection, global error handling, manifest |
| `AISystemOptimizer.Tests` | `net8.0-windows`, xUnit | Rules, scoring, safety and configuration tests |

---

## Core components

| Class | Role |
|---|---|
| `SystemScanner` | Collects a `SystemInfo` snapshot using performance counters, WMI and documented APIs. Never modifies anything. |
| `ProcessAnalyzer` | Builds `ProcessAnalysisResult` for every process: category, risk, score, estimated recovery, AI commentary. |
| `RiskAnalyzer` | Determines the risk level of an action and its potential side effects, confirmation requirement and recovery options. |
| `OptimizationPlanner` | Turns analysis into an `OptimizationPlan` of concrete `OptimizationAction`s, then validates it. |
| `SafetyValidator` | **The gate.** Refuses anything unsafe, regardless of who proposed it (rules, AI or the user). |
| `SafeExecutor` | Executes one action at a time. Records undo information. Refuses protected targets even if called directly. |
| `VerificationService` | Re-scans after execution, verifies each action had the intended effect, checks system stability. |
| `RecoveryService` | Restore points, backups, optimisation history, undo. |
| `StartupManager` / `ServiceManager` | Enumerate and (with confirmation) modify start-up entries and services. |
| `AIService` / `OllamaClient` | Optional local-AI analysis. Strictly advisory; can be unreachable without breaking anything. |
| `SystemScoring` | Converts measurements into the health scores shown in the UI. |
| `WindowsApiHelper` | Thin, defensive wrappers over documented Win32 APIs (memory, processes, services, power, restore points, DPI). |
| `PerformanceCounterHelper` | Cached performance counters + WMI. Returns neutral values and records `LastError` instead of inventing numbers. |
| `Logger` | Structured, rotating file logging (`FileLogger`, `ConsoleLogger`, `CompositeLogger`). |

---

## Data model

```
SystemInfo ─┬─ List<ProcessInfo>            (category, risk, RAM/CPU/GPU/disk, signature…)
            ├─ List<ServiceInfo>            (status, start type, criticality)
            ├─ List<StartupItem>            (source, impact, estimated RAM, recommendation)
            ├─ List<GpuInfo> / List<DiskInfo> / List<NetworkAdapterInfo>
            ├─ PerformanceScores            (RAM, CPU, GPU, Disk, Startup, Background Apps)
            └─ List<OptimizationRecommendation>

OptimizationPlan ─┬─ List<OptimizationAction>   (type, target, risk, estimate, undo, status)
                  ├─ BeforeSystemInfo
                  └─ AfterSystemInfo

OptimizationHistory ── List<OptimizationSession>  (before/after metrics, plan, notes)
```

`OptimizationAction` carries everything needed to audit a decision: what, why, how much, how risky,
whether it can be undone, who proposed it, and how confident the AI was.

---

## Classification rules

| Category | Meaning | Default risk |
|---|---|---|
| `Critical` | `System`, `csrss`, `lsass`, `winlogon`, `dwm`, `explorer`, `svchost`, … | CRITICAL — never touched |
| `Security` | Defender, firewall, Security Center, third-party AV | CRITICAL — never touched |
| `Driver` | AMD/NVIDIA/Intel graphics, audio, network, Bluetooth, touchpad, storage, USB | HIGH — never touched |
| `System` | Other Windows components under `%SystemRoot%` | HIGH |
| `UserApplication` | Something the user started | LOW |
| `BackgroundApplication` | User software with no visible window | LOW — primary optimisation target |
| `Launcher` / `Updater` / `CloudSync` / `Telemetry` | Lower-value background work | LOW–MEDIUM |
| `Game` | Detected game executable | LOW (Game Mode context) |

Classification matches on **whole name tokens and distinctive path segments**. Loose substring
matching was rejected after a unit test showed `diagtrack` matching the token `ac`.

---

## Safety model

`SafetyValidator` refuses an action when any of the following holds:

1. The safety layer is disabled (fails closed).
2. Risk is above the configured ceiling (default `Low`).
3. The target is a critical process, a security component, or a driver.
4. The target is on the process/service/start-up blacklist.
5. The specific act is "disable Defender", "disable firewall", "disable UAC" or "disable a critical Windows service".
6. The process has a visible window or is the foreground process (the user is using it).
7. The action needs elevation and the process is not elevated.
8. The system state makes it unwise (on battery with a high-risk action; disk already saturated; etc.).
9. The plan as a whole is unsafe (too many high-risk actions, too many services at once, would leave the system unstable).

The validator is unit tested with adversarial input, including the specification's own example —
*"the AI says kill `svchost.exe`"* — which must be rejected.

---

## Threading model

- Scanning runs on a background thread (`Task.Run`) and reports progress through events.
- The UI samples cheap metrics every 2 s on the WPF dispatcher (`DispatcherTimer`).
- Expensive sampling (per-core CPU, GPU engine counters, per-process CPU deltas) happens only on
  explicit scans, never on the live timer.
- Performance counters are cached for two minutes; creating counters is itself expensive.
- The executor runs one action at a time; there is no parallel mutation of system state.

---

## The optimiser's own footprint

Requirement: idle CPU ≈ 0 %, RAM ≲ 100 MB. How that is achieved:

- no polling loops — a single 2 s timer that reads cached counters;
- WPF virtualization on every list; no chart library (a ~120 line `DrawingContext` sparkline);
- history capped at 100 sessions; log files rotated and capped;
- counters disposed on exit; the AI client is created lazily and only when enabled and reachable.

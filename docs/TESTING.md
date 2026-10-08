# Testing

## 1. Automated tests

```powershell
.\scripts\run-tests.ps1
# or
dotnet test AISystemOptimizer.sln
```

**64 tests, all passing.** Coverage focus is deliberately on the parts where a mistake would be
dangerous rather than on line coverage:

| Area | What is asserted |
|---|---|
| Critical process protection | `System`, `Registry`, `smss`, `csrss`, `wininit`, `services`, `lsass`, `winlogon`, `dwm`, `explorer`, `svchost` are all classified `Critical` with `RiskLevel.Critical`. |
| Security stack | Defender, firewall, Security Center and third-party AV are never low/medium risk. |
| Driver helpers | AMD/NVIDIA/Intel/Realtek/Synaptics binaries are never offered for closing. |
| Classification | User apps → `UserApplication`; OneDrive/Dropbox → `CloudSync`; Steam/Epic → `Launcher`; `GoogleUpdate` → `Updater`; `DiagTrack` → `Telemetry`. |
| Safety layer (adversarial) | Closing `svchost`/`lsass`/`csrss`/`dwm` is rejected **even when labelled low-risk**; disabling `WinDefend`/`MpsSvc`/`wscsvc`/`BFE` is rejected; a plan containing one critical action is rejected entirely; an action against a process with a visible window is rejected. |
| Fails closed | With the safety layer switched *off*, the validator declines everything rather than becoming permissive. |
| Scoring | Lower memory usage scores higher; every score stays inside 0–100; target progress is 100 % when already below target. |
| Honest reporting | Unreachable targets produce the "not possible … Safe optimization limit reached" message. |
| Candidate filtering | Critical and in-use processes are excluded from optimisation candidates; an idle background app is included. |
| Configuration | Defaults match the documented values; out-of-range values fail validation; `Clone()` is deep enough that editing the copy does not affect the original. |
| Plan mathematics | Overall risk equals the highest contained risk; CPU-type actions do not inflate the RAM recovery estimate. |

The tests are ordinary logic tests and also run on Linux/macOS CI (Windows-only APIs are only
invoked at runtime and every call site is guarded).

## 2. Manual test matrix

Behaviour that depends on a real machine cannot be unit tested. The matrix below is what the
specification asks for; each row lists the expected outcome so a run is pass/fail.

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | Idle system | Scan completes < 3 s. Health score populated. Memory target card states how far safe optimisation reaches. |
| 2 | Chrome open with many tabs | Chrome appears as `UserApplication`, has a visible window, is **never** offered for closing. Manual close is refused with an explanation. |
| 3 | Steam open | Store client classified `Launcher`, offered as a session optimisation, memory measured from the real working set. |
| 4 | Discord open | Classified as user application; if minimised to tray (no visible window) it becomes a candidate. |
| 5 | A game running | Game Mode detects it, prioritises it to `AboveNormal`, pauses background apps, never touches Defender or drivers. |
| 6 | Low free RAM (fill it with a test allocation) | App still functions; scan does not fail; candidates are still restricted to genuinely safe ones. |
| 7 | High CPU (e.g. a stress tool) | CPU score drops; app itself stays responsive; no CPU-intensive action is proposed while the CPU is already saturated. |
| 8 | Several unknown/unsigned processes | Shown as `Unsigned (not necessarily unsafe)` with the path, and *not* declared malware without evidence. |
| 9 | UAC | App starts un-elevated; elevated-only actions are refused with an explanation rather than failing silently; standard UAC prompt when run as administrator. |
| 10 | No internet | Everything works. AI status shows "not reachable"; rule-based analysis remains complete. |
| 11 | Restart | History, whitelist and settings persist; disabled start-up entries stay disabled; nothing is re-applied automatically. |
| 12 | Sleep / wake | Live charts resume; counters recover; no crash if a counter disappears. |
| 13 | Sensors absent | Temperature and per-process GPU show `N/A` — never a fabricated value. |
| 14 | No optimisation possible | Report says "No significant optimisation was possible" instead of displaying a fake win. |
| 15 | Undo | Start-up entries re-created with the original command line; services restarted; closed applications state that they must be reopened manually. |

## 3. Measurable outcome log

For each optimisation run, record:

```
Before: RAM __%  CPU __%  Processes __
After : RAM __%  CPU __%  Processes __
Reported recovery: __ MB
Actual free-memory delta: __ MB
Actions succeeded / skipped: __ / __
```

If "actual" is far below "reported", the honest-reporting path should have fired — check the report
for the "No significant optimisation" note and the verification section.

## 4. Adding tests

1. Add a test class under `tests/AISystemOptimizer.Tests/`.
2. Prefer theories over repeated facts, and assert on *meaning* ("this must be rejected"), not on
   incidental formatting.
3. Anything touching a Windows API must be guarded so the suite still runs on Linux CI.

## 5. What is intentionally *not* tested automatically

- The WPF user interface (verify manually with the matrix above).
- Real process termination (destructive; verified manually and logged).
- The optional AI path against a live model (verify with *Test connection* in Settings).

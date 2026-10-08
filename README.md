# AI System Optimizer

**A real Windows 11 / Windows 10 system optimiser — not a fake RAM booster.**

It scans your machine, separates what genuinely costs resources from what Windows needs,
proposes only changes it can justify, asks before acting, verifies the result, and tells you
honestly when nothing can be improved.

```
SystemScanner → Rules engine → Risk analyzer → (optional local AI) → Planner
             → Safety layer → Safe executor → Verification → Report
```

---

## Download and run (no build needed)

**You do not need Visual Studio, the .NET SDK, or any installed runtime.**

1. Open the **[Releases page](https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer/releases/latest)**.
2. Under **Assets**, download **`AIOptimizer.exe`** (about 66 MB, self-contained).
3. Put it anywhere you like — your Desktop, a folder, a USB stick.
4. **Right-click → Run as administrator** for the first run. (Without it the app still works, but
   service changes, restore points and some start-up entries are refused — by design.)
5. Windows SmartScreen may warn about an unknown publisher, because this binary is not
   code-signed. Choose **More info → Run anyway**, or build it yourself from source (see below);
   either way the SHA-256 of every released file is published next to it so you can verify the
   download:

   ```powershell
   certutil -hashfile AIOptimizer.exe SHA256
   # compare with the value in AIOptimizer.exe.sha256 and on the release page
   ```

**Persian guide:** [docs/USER_GUIDE_FA.md](docs/USER_GUIDE_FA.md) — راهنمای کامل فارسی، از دانلود تا
استفاده از هر بخش برنامه.

---

## What it is

| | |
|---|---|
| **Platform** | Windows 10 1809+ and Windows 11, x64 (ARM64 publish supported) |
| **Runtime** | .NET 8 (self-contained portable build needs nothing installed) |
| **UI** | WPF, Fluent-styled, dark and light themes, fully offline |
| **Dependencies** | None beyond the .NET base class library — no third-party packages in the UI |
| **Internet** | Not required. Ever. The optional AI runs against a **local** Ollama server |

## What it actually does

- **Scans** processes, services, start-up entries, memory, CPU, GPU, disk and network usage — all from documented Windows APIs and performance counters.
- **Classifies** every process: `CRITICAL`, `SYSTEM`, `DRIVER`, `SECURITY`, `USER APPLICATION`, `BACKGROUND APPLICATION`, plus `LAUNCHER`, `UPDATER`, `CLOUD SYNC`, `TELEMETRY`.
- **Ranks** candidates by measured cost and by the risk of touching them.
- **Closes** inactive background applications you are not using (never one with a visible window).
- **Disables** optional start-up entries, saving the original command line so it can be restored exactly.
- **Stops / disables** third-party services you explicitly approve.
- **Game Mode** raises a running game to `AboveNormal` and pauses background applications for the session only.
- **Cleans** genuinely disposable caches (temp files, thumbnail cache, DNS cache) — and says so when there is nothing to clean.
- **Measures before/after** and prints both numbers, including when nothing changed.
- **Logs everything** and keeps an undo path.
- **🎮 Game & App Optimizer** — per-application profiles. Add any `.exe`; it is inspected (never
  executed) and identified by canonical path + SHA-256 + publisher, so a same-named different program
  can never inherit a profile. Four modes (Safe / Balanced / Performance / Custom — there is no
  "Unsafe"), a mandatory restore engine that records every original value before it changes anything,
  crash recovery that offers *Restore / Review / Keep* instead of acting on its own, a benchmark in
  percentage points, and an AI that may only recommend from a fixed action list.

## What it never does

These are enforced in code (see `SafetyValidator` and the test suite), not just promised in a README:

- ✗ Disable Windows Defender, the firewall, or UAC
- ✗ Kill critical processes (`System`, `csrss`, `lsass`, `winlogon`, `dwm`, `explorer`, `svchost`, …)
- ✗ Touch hardware drivers
- ✗ Disable or resize the pagefile
- ✗ Clear the standby list to make the RAM number look better (that makes Windows *slower*)
- ✗ Bypass UAC
- ✗ Disable Windows Update
- ✗ Change undocumented registry keys
- ✗ Delete system files or remove Windows components
- ✗ Claim a speed-up that was not measured

## Honest reporting

If your RAM target cannot be reached safely, the application says so instead of forcing it:

> *"Even after closing every safely closable application (7 candidates, ~0.94 GB), memory usage would be
> about 41.3 %. Reaching 35 % is not possible without disabling Windows services, security features or
> drivers, which this application will not do. **Safe optimization limit reached.**"*

If an optimisation changes nothing, the report says that too:

> *"No significant optimisation was possible. The memory currently in use is actively required by
> Windows and your open applications — artificially clearing it would not improve performance."*

## Quick start

```powershell
# 1. Build
git clone <repository-url>
cd AISystemOptimizer
.\scripts\build.ps1                 # or: dotnet build AISystemOptimizer.sln

# 2. Run
.\src\AISystemOptimizer.App\bin\Debug\net8.0-windows\win-x64\AISystemOptimizer.exe

# 3. Analyse, review the preview, press Optimize
```

Portable single file:

```powershell
.\scripts\publish-portable.ps1      # → dist\AIOptimizer.exe  (self-contained, no install)

# keep every file beside the executable (USB stick usage):
$env:AISYSTEMOPTIMIZER_PORTABLE = "1"; .\AIOptimizer.exe
```

Installer:

```powershell
.\scripts\publish-installer.ps1     # → dist\AISystemOptimizer-Setup.exe  (needs Inno Setup 6)
```

Details: [docs/BUILD.md](docs/BUILD.md) · User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md) ·
Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Testing: [docs/TESTING.md](docs/TESTING.md)

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 1809 (build 17763) | Windows 11 22H2 or newer |
| Runtime | .NET 8 Desktop Runtime *¹* | — |
| Rights | Standard user (limited features) | Administrator **on demand**, for service changes and restore points |
| Disk | 200 MB | — |
| RAM (the optimiser itself) | < 100 MB target, idle CPU ≈ 0 % | — |

*¹ Not needed for the self-contained portable build or the installer.*

## Configuration

Settings live in `%LOCALAPPDATA%\AISystemOptimizer\config.json` (a documented template is in
[`config/config.json`](config/config.json)). Highlights:

```jsonc
"targetRamUsage": 35,            // your goal — the app tells you if it is safely reachable
"safetyLayerEnabled": true,      // leave this on
"maxAutoRiskLevel": "Low",       // how far automatic mode may go
"allowHighRiskActions": false,
"createRestorePoints": true,
"aiEnabled": true,               // completely optional; rule-based analysis always works
"ollamaServerUrl": "http://localhost:11434",
"whitelistedProcesses": ["chrome.exe"],   // never closed automatically
"blacklistedProcesses": [ ... ]           // never touched
```

## Safety model

```
AI suggestion / rule suggestion / manual click
        │
        ▼
  SafetyValidator  ── layer 1, pure policy over (action, snapshot):
        │               critical processes (name + path + service relation),
        │               security stack, drivers, blacklist, never-touch list,
        │               in-use programs, risk above the configured ceiling,
        │               missing elevation, and the process IDENTITY.
        │               An action with no recorded identity is refused.
        ▼
   SafeExecutor    ── layer 2, re-checked at the moment of use:
        │               re-reads the live process creation time, the name,
        │               the foreground window and the visible-window state.
        │               Asks the application to close itself (WM_CLOSE) and
        │               waits before anything forceful.
        ▼
 WindowsApiHelper  ── layer 3, last-moment guard: TerminateProcess takes the
        │               expected creation time and verifies it once more
        ▼
 VerificationService ── waits for the system to settle, then re-scans and
                        compares before/after
```

The safety layer **fails closed**: if it cannot prove an action is safe, it refuses. Disabling it in
the configuration file makes it refuse *everything* — off means fail closed, not fail open.

### Process identity, or why a PID is not enough

Windows recycles process IDs. Between the scan and the execution a process can exit and an unrelated
program can be given the same number. Every process-scoped action therefore records the kernel
creation timestamp (`GetProcessTimes`), the image path and the normalised name at the moment it is
planned, and all three layers compare that against the live process before acting. A mismatch means
the action is dropped, and the report says why.

Risk levels follow the specification:

| Level | Meaning | Behaviour |
|---|---|---|
| 🟢 LOW | Safe, reversible where possible | Can run in automatic mode |
| 🟡 MEDIUM | Review advised | Requires confirmation |
| 🟠 HIGH | Can affect functionality | Blocked unless explicitly enabled |
| 🔴 CRITICAL | Could destabilise Windows | **Always blocked** |

## Local AI (optional)

Point it at [Ollama](https://ollama.com) and it will explain what an unknown process is and offer
second opinions. The AI **never** executes anything: its output is a *recommendation* that goes
through exactly the same safety validator as everything else. If the AI is off, unreachable, or
slow, the rule-based analyser provides full functionality.

Two local back ends are supported, and each one is really used:

| Setting | Server | Endpoint |
|---|---|---|
| `aiProvider: "Ollama"` | [Ollama](https://ollama.com) | `/api/generate` |
| `aiProvider: "llama.cpp"` | `llama-server` | `/v1/chat/completions` |

```powershell
# Ollama
ollama pull llama3.2:3b
# or a llama.cpp server
llama-server -m your-model.gguf --port 8080
# then set aiEnabled: true in config.json (already the default)
```

Both default to a loopback address. There is no cloud endpoint, no API key and no telemetry anywhere
in the code. If neither is running, the optimiser works exactly as before, minus the explanations.

## Project layout

```
src/AISystemOptimizer.Core/     scanner, rules engine, risk analysis, planner,
                                safety layer, executor, verification, AI client, logging
src/AISystemOptimizer.UI/       WPF shell, pages, view models, converters, sparkline control
src/AISystemOptimizer.App/      application entry point, theme selection, global error handling
tests/                          xUnit tests for the rules, scoring and safety layers
config/                         documented configuration template
docs/                           build, user, architecture and testing documentation
scripts/                        build / publish-portable / publish-installer / run-tests
installer/                      Inno Setup script
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Windows refused to close *X*" | The process is protected or elevated. Run the optimiser as administrator if you are sure. |
| Start-up entry will not disable | `HKLM` entries and policy-managed items need administrator rights. `HKCU` entries do not. |
| Restore point not created | System Protection may be off, or a restore point was made in the last 24 h (Windows rate-limits). |
| Temperatures show *N/A* | Your hardware/driver does not expose the sensor. The app never invents a value. |
| GPU % shows *N/A* | GPU Engine counters are unavailable (older drivers). System-wide values only. |
| AI status: not reachable | Ollama is not running. Start it, or leave the AI disabled — everything else still works. |

Logs: `%LOCALAPPDATA%\AISystemOptimizer\Logs` · Backups: `…\Backups` · Reports: `…\Reports`

## Licence

MIT — see [LICENSE](LICENSE).

## Design principles

1. **Safety** — nothing destructive, ever.
2. **Stability** — Windows keeps working exactly as before.
3. **Security** — Defender, firewall and UAC are out of scope by design.
4. **Real performance** — measured, not claimed.
5. **Memory optimisation** — only memory that is genuinely reclaimable.
6. **CPU / GPU / disk optimisation** — proposed, never forced.
7. **Appearance** — pleasant, but always last.

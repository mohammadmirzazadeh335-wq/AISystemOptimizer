# User guide

## 1. First run

1. Start `AIOptimizer.exe`. The window opens immediately; the first scan runs in the background.
2. Watch the **Dashboard**: four live cards (memory, CPU, GPU, disk), a health score, and your
   memory target with an honest assessment of whether it is reachable.
3. Press **Analyze System** at any time to take a fresh snapshot.

The application starts **without** a UAC prompt. It asks for elevation only when you request an
operation that Windows requires it for (disabling an `HKLM` start-up entry, changing a service,
creating a restore point).

## 2. Reading the dashboard

| Card | What it shows |
|---|---|
| **Memory** | Percentage of physical RAM in use, plus a rolling 2-minute chart. |
| **CPU** | System-wide usage and your CPU model. |
| **GPU** | Usage when the GPU Engine counters are available, otherwise `N/A` — never a guess. |
| **Disk** | Disk busy time and the free space on the system drive. |
| **System Health Score** | 0–100, averaged from the component scores. |
| **Memory Target** | How far safe optimisation alone can move you toward your target. |

**Important:** cached and standby memory are *not* a problem. Windows uses idle RAM to cache files
and hands it back the instant an application asks for it. A high "used" figure is not automatically
bad — which is why this application will not clear the standby list to make the number look better.

## 3. Smart Optimize

Builds a conservative plan and **shows it to you first**. You will see:

```
Will close:
  • Spotify (168 MB)
  • EpicGamesLauncher (121 MB)
Will disable at start-up:
  • Spotify
Estimated memory recovery: 289 MB
Overall risk: LOW
```

Press **Optimize** to run it, or **Cancel** to discard it. Nothing happens until you confirm.

## 4. What gets closed, and what never does

✅ Closed if inactive: background applications, launchers, updaters, cloud-sync clients, telemetry.

⛔ Never closed, at any risk setting: anything with a visible window, the foreground application,
Windows core processes, drivers, security components, and anything on your whitelist.

A program you are *looking at* is never closed, no matter how much memory it uses. That is the
rule from the specification, enforced in `SafetyValidator` and covered by a unit test.

## 5. Processes page

Full table with search, category filter, sorting, and a details pane: PID, path, publisher, digital
signature, parent process, start time, thread/handle counts, risk level, and a plain-language note
explaining *why* the optimiser is (or is not) allowed to touch it.

- **Explain (AI)** — asks your local AI model what an unfamiliar process is. Optional.
- **Never close this** — whitelist. **Never touch this** — blacklist.
- Manual "Close process" uses the same safety validation as the automatic path. It is not a bypass.

Digital signatures: *unsigned does not mean unsafe.* Plenty of legitimate tools ship unsigned.

## 6. Start-up Programs

Shows registry Run keys (`HKLM`/`HKCU`, 32- and 64-bit), both Startup folders, and scheduled
tasks/services. For each entry: source, impact, measured memory *when it is running*, risk and a
recommendation.

- Memory is only reported for entries that are **currently running**. When an entry is not running,
  the app shows *unknown* rather than inventing a number.
- Disabling never deletes anything: registry values are removed (the original command line is saved
  for restore) and Startup-folder shortcuts are moved to the backup folder.
- Windows components, drivers and security software cannot be disabled from here.

## 7. Services

Lists every service with status, start type, criticality and risk. Critical services and everything
on the protected list refuse to be stopped or disabled — the details pane explains why.

Stopping a service can break dependent features; the app says so before you confirm, and a restore
point is recommended for any plan that changes system configuration.

## 8. Game Mode

1. Start your game.
2. Open **Game Mode** → **Detect game**.
3. Choose session options (boost priority, close launchers, pause cloud sync).
4. **Prepare game plan** → review on the Optimization page → **Optimize**.

Guarantees, enforced in code:

- Defender, the firewall and UAC stay on;
- drivers are never touched;
- Windows Update is never disabled;
- start-up entries are **not** modified (session-only changes);
- game priority goes to `AboveNormal` at most (never `High`, never `RealTime`);
- CPU affinity is left to Windows unless you explicitly enable it.

Exit the game and nothing needs undoing — the next reboot is a clean slate.

## 9. SMART RAM CLEAN

This button does **not** fake a memory boost. It removes only genuinely disposable data:

- user and system temporary files (locked files are skipped);
- the thumbnail/icon cache;
- the DNS resolver cache.

It reports exactly what it freed, and states plainly that this frees *storage*, not RAM. It never
clears the standby list and never touches working sets, because doing so makes Windows slower.

## 10. Reports and history

Every session is stored with before/after RAM, CPU and process counts, the actions taken, what was
skipped and why. The report text can be copied or saved to `%LOCALAPPDATA%\AISystemOptimizer\Reports`.

Skipped items are always listed, for example:

```
SKIPPED (and why)
  ⚠ Windows Defender – never touched (security first)
  ⚠ Windows Firewall – never touched
  ⚠ Windows core services and drivers – never touched
  ⚠ Pagefile and memory manager – never modified
```

## 11. Undo

**Undo last** restores what can be restored:

| Action | Undo behaviour |
|---|---|
| Disabled start-up entry | Re-created with the exact original command line |
| Stopped service | Started again |
| Disabled service | Start type restored |
| Changed priority / affinity | Restored |
| Closed application | **Not** reversible — Windows cannot restart an application exactly as it was; reopen it manually |
| Cleared caches | Not reversible (and not harmful) |

## 12. Settings

- **Memory target** — set your goal. The page tells you whether it is safely reachable and refuses to pretend otherwise.
- **Automation** — interval, idle threshold, battery behaviour. Automatic mode still previews before changing anything.
- **Local AI** — Ollama URL and model, with a *Test connection* button.
- **Safety** — safety layer toggle (leave on), medium-risk confirmation, restore points, high-risk allowance.
- **Logging** — level and location.
- **Whitelist** — processes the optimiser must never close.

## 13. Troubleshooting

| Symptom | Explanation |
|---|---|
| "Windows refused to close *X*" | Protected or elevated process. Run as administrator if you are certain. |
| Start-up entry will not disable | `HKLM` or policy-managed entry — needs elevation. |
| "Windows did not allow a restore point" | System Protection is off, you are not elevated, or Windows rate-limits restore points to one per 24 h. |
| Temperature shows N/A | No sensor exposed by your hardware/driver. Values are never fabricated. |
| Nothing to optimise | Your system is genuinely in good shape — a legitimate outcome, reported as such. |
| RAM stays above your target | See the message on the Memory Target card: it names what would be required and why the app refuses. |

Logs: `%LOCALAPPDATA%\AISystemOptimizer\Logs` — every action with timestamp, target, reason, result
and risk level.

# Build instructions

Everything below has been verified with **.NET SDK 8.0.425** on Windows. The Core library and the
unit tests also compile and run on Linux/macOS (the Windows-only APIs are only *called* at runtime,
and every call site is guarded).

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| .NET SDK 8.0 or newer | <https://dotnet.microsoft.com/download/dotnet/8.0> |
| Windows 10 1809+ / Windows 11 | required to *run* the application |
| Git (optional) | only for cloning |
| Inno Setup 6 (optional) | only for the installer |
| PowerShell 5.1+ | the scripts in `scripts\` |

Check your SDK:

```powershell
dotnet --list-sdks
```

You want a `8.0.x` (or newer) entry.

---

## 2. Build from source

```powershell
git clone <repository-url>
cd AISystemOptimizer

dotnet restore AISystemOptimizer.sln
dotnet build   AISystemOptimizer.sln -c Release
```

or, with the convenience script (restore + build + test):

```powershell
.\scripts\build.ps1 -Configuration Release
```

Output:

```
src\AISystemOptimizer.App\bin\Release\net8.0-windows\win-x64\AISystemOptimizer.exe
```

Types of build:

| Command | What it gives you |
|---|---|
| `dotnet build` | debug build, framework-dependent (needs the .NET 8 Desktop Runtime) |
| `dotnet build -c Release` | optimised, still framework-dependent |
| `dotnet publish` | publish output ready to ship |

---

## 3. Portable build (recommended distribution)

Produces a single self-contained executable — nothing to install on the target machine:

```powershell
.\scripts\publish-portable.ps1
# → dist\AIOptimizer.exe            (~80 MB, self-contained, single file)
# → dist\AISystemOptimizer-portable-selfcontained.zip
```

Framework-dependent (≈ 2 MB, requires the .NET 8 Desktop Runtime on the target):

```powershell
.\scripts\publish-portable.ps1 -Flavor framework
```

ARM64:

```powershell
.\scripts\publish-portable.ps1 -Runtime win-arm64 -OutputName AIOptimizer-arm64
```

Under the hood (if you prefer to run it by hand):

```powershell
dotnet publish src\AISystemOptimizer.App\AISystemOptimizer.App.csproj `
  -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true `
  -p:IncludeNativeLibrariesForSelfExtract=true `
  -p:DebugType=None -p:PortableName=AIOptimizer `
  -o dist
```

### Portable data location

By default the portable build still stores settings in `%LOCALAPPDATA%\AISystemOptimizer`.
To keep every file inside the application folder instead (true portable / USB stick usage), set:

```powershell
$env:AISYSTEMOPTIMIZER_PORTABLE = "1"
.\AIOptimizer.exe
```

The application then writes everything into an `AISystemOptimizerData\` folder next to the executable.
On a read-only medium it falls back to `%LOCALAPPDATA%` automatically.

---

## 4. Installer

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
.\scripts\publish-installer.ps1 -Version 1.0.0
# → dist\AISystemOptimizer-Setup.exe
```

Or compile directly:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\AISystemOptimizer.iss
```

Installer behaviour:

- installs to `%ProgramFiles%\AISystemOptimizer` (administrator required for the *installer* only);
- optional desktop shortcut and optional sign-in start (monitoring only — it never changes anything by itself);
- on uninstall, your settings, logs, backups and history in `%LOCALAPPDATA%\AISystemOptimizer` are **kept**.

---

## 5. Tests

```powershell
.\scripts\run-tests.ps1
# or
dotnet test AISystemOptimizer.sln -c Release
```

Expected: **64 tests, 0 failures** (rules engine, scoring, safety layer, configuration).

See [TESTING.md](TESTING.md) for the manual test matrix that covers behaviour that cannot be unit
tested (Game Mode against a real game, sleep/wake, low-memory conditions, and so on).

---

## 6. Running without administrator rights

The application is designed to start **un-elevated**. In that mode:

- scanning, classification, planning, closing user applications and clearing caches all work;
- disabling `HKLM` start-up entries, stopping/disabling services, and creating restore points are
  refused by Windows — the UI explains this instead of failing silently.

To allow everything, launch once as administrator:

```powershell
Start-Process .\AIOptimizer.exe -Verb RunAs
```

UAC is standard Windows elevation; it is never bypassed.

---

## 7. Troubleshooting the build

| Error | Fix |
|---|---|
| `NETSDK1100: To build a project targeting Windows on this operating system...` | You are building on Linux/macOS. `Directory.Build.props` already sets `EnableWindowsTargeting=true`; make sure you did not override it. |
| `NETSDK1135: SupportedOSPlatformVersion ... higher than TargetPlatformVersion` | Keep the target framework as `net8.0-windows` (no explicit platform version). |
| `The type or namespace 'System.Management' / 'System.ServiceProcess' could not be found` | `dotnet restore` was skipped or NuGet is offline; the packages come from `Microsoft.Windows.Compatibility`. |
| `MSB3644: The reference assemblies for .NETFramework...` | You opened an old project file. This solution is SDK-style, .NET 8 only. |
| NuGet restore fails behind a proxy | `dotnet nuget add source <url>` or set `HTTP_PROXY` / `HTTPS_PROXY`. |

---

## 8. Repository hygiene

```powershell
dotnet clean AISystemOptimizer.sln
Remove-Item -Recurse -Force .\src\*\bin, .\src\*\obj, .\tests\*\bin, .\tests\*\obj, .\dist
```

`bin/`, `obj/` and `dist/` are regenerable and are excluded by `.gitignore`. Those directories are not part of the source deliverable.

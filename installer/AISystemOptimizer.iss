; ============================================================================
;  AI System Optimizer - Inno Setup 6 script
; ============================================================================
;  Build with:  scripts\publish-installer.ps1
;  or directly: ISCC.exe installer\AISystemOptimizer.iss
;
;  The installer ships the self-contained publish output, so the target machine
;  does not need a separate .NET runtime download.
; ============================================================================

#define MyAppName "AI System Optimizer"
#define MyAppPublisher "AI System Optimizer Team"
#define MyAppURL "https://github.com/AISystemOptimizer"
#define MyAppExeName "AIOptimizer.exe"

; Overridden from the command line by publish-installer.ps1
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{7C4E1B2A-9F3D-4A86-9C21-5E8B7D4F1A63}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\AISystemOptimizer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=AISystemOptimizer-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The application itself runs un-elevated; only its installer needs admin rights
; to place files under Program Files.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startupicon"; Description: "Start the optimiser automatically at sign-in (monitoring only, no automatic changes)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Payload produced by scripts\publish-portable.ps1
Source: "..\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Documented sample configuration (does not overwrite a user's file)
Source: "..\config\config.json"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\BUILD.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\User Guide"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only remove what the installer created. User data (settings, logs, backups,
; history) lives in %LOCALAPPDATA% and is deliberately left alone so that
; reinstalling keeps your whitelist and history.
Type: filesandordirs; Name: "{app}\config"

[Code]
// Refuse to install over a running instance so no file is locked mid-upgrade.
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  if Exec('tasklist.exe', '/FI "IMAGENAME eq AIOptimizer.exe" /NH', '', SW_HIDE,
          ewWaitUntilTerminated, ResultCode) then
  begin
    // tasklist always returns 0; the message below is only shown if the user
    // keeps the process running, so the check is informational rather than fatal.
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('Your settings, logs, backups and optimisation history were kept in' + #13#10 +
           '%LOCALAPPDATA%\AISystemOptimizer and were not removed.' + #13#10#13#10 +
           'Delete that folder manually if you want a completely clean removal.',
           mbInformation, MB_OK);
  end;
end;

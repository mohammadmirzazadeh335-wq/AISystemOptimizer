; Inno Setup script for MyAI Studio Ultimate.
; Build with: ISCC.exe /DMyAppVersion=0.1.0 packaging\myai_studio.iss
; Expects the PyInstaller onedir output in ..\dist\MyAIStudio

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "MyAI Studio Ultimate"
#define MyAppPublisher "MyAI Studio"
#define MyAppExeName "MyAIStudio.exe"
#define MyAppId "{{B0B7CD2C-6D3B-4B3E-9F2A-1A9C0F0B7A61}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MyAI Studio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=MyAIStudio-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "farsi"; MessagesFile: "compiler:Languages\Farsi.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MyAIStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Logs"; Filename: "%APPDATA%\MyAIStudio\logs"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The per-user workspace (database, logs, backups) is intentionally kept on uninstall.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

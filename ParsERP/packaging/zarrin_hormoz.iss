; Inno Setup 6 script for «زرین هرمز» (Zarrin Hormoz).
;
; Build (on Windows, after ``packaging\zarrin_hormoz.spec`` produced
; ``dist\ZarrinHormoz\``):
;
;     iscc /DAppVersion=0.7.0 /DBuildRoot=dist\ZarrinHormoz packaging\zarrin_hormoz.iss
;
; Output: ``packaging\output\ZarrinHormoz-<version>-setup.exe``
;
; Design rules enforced here
; --------------------------
; * program files go to ``{autopf}\ZarrinHormoz`` and are removed by the
;   uninstaller; user data (database, backups, logs, config) lives in
;   ``%APPDATA%\ParsERP`` and is **never** deleted without an explicit
;   confirmation - the uninstaller asks once and defaults to keeping the data.
; * upgrades are controlled: setup refuses to continue while the application is
;   running, keeps the previous version's data folder untouched, and asks the
;   application to take a verified backup before the first start of a new
;   version (``ZarrinHormoz-console.exe update backup-before-start``).
; * the prerequisites are checked, not assumed: 64-bit Windows 10/11 and a
;   writable data folder; VC++ runtime is bundled by PyInstaller's own payload.

#ifndef AppVersion
  #define AppVersion "0.7.0"
#endif
#ifndef BuildRoot
  #define BuildRoot "..\dist\ZarrinHormoz"
#endif

#define AppNameFA "زرین هرمز"
#define AppNameEN "Zarrin Hormoz"
#define AppPublisher "زرین هرمز"
#define AppExe "ZarrinHormoz.exe"
#define ConsoleExe "ZarrinHormoz-console.exe"
#define DataDir "{userappdata}\ParsERP"

[Setup]
AppId={{8D3A1C55-2E1B-4F27-9E1C-8B4A6C1D2F10}
AppName={#AppNameFA}
AppVersion={#AppVersion}
AppVerName={#AppNameFA} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppNameFA} - نصب‌کننده
DefaultDirName={autopf}\ZarrinHormoz
DefaultGroupName={#AppNameFA}
DisableProgramGroupPage=no
OutputDir=output
OutputBaseFilename=ZarrinHormoz-{#AppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppNameFA}
LicenseFile=..\docs\phase7\01-install-guide.md
SetupIconFile=zarrin_hormoz.ico
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
AppMutex=ZarrinHormoz.SingleInstance

[Languages]
Name: "farsi"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "ایجاد میان‌بر روی میزکار"; GroupDescription: "میان‌برها:"
Name: "quicklaunchicon"; Description: "ایجاد میان‌بر در نوار وظیفه"; GroupDescription: "میان‌برها:"; Flags: unchecked

[Files]
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\phase7\*.md"; DestDir: "{app}\docs\phase7"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\requirements-postgres.txt"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppNameFA}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppNameFA} (خط فرمان)"; Filename: "{app}\{#ConsoleExe}"
Name: "{group}\راهنمای نصب"; Filename: "{app}\docs\phase7\01-install-guide.md"
Name: "{group}\حذف {#AppNameFA}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppNameFA}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppNameFA}"; Filename: "{app}\{#AppExe}"; Tasks: quicklaunchicon

[Run]
; The first run creates the data folder, migrates the schema and takes a
; startup backup; it is the same entry point the shortcut uses.
Filename: "{app}\{#AppExe}"; Description: "اجرای {#AppNameFA}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\docs\phase7\01-install-guide.md"; Description: "مشاهدهٔ راهنمای نصب"; Flags: shellexec postinstall skipifsilent unchecked

[UninstallDelete]
; Only files the installer itself created outside {app}. The user's data folder
; is deliberately absent from this section.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
var
  KeepDataPage: TInputOptionWizardPage;

function DataFolder(): String;
begin
  Result := ExpandConstant('{userappdata}\ParsERP');
end;

function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  { A running instance holds AppMutex; let setup close it gracefully first. }
  Result := not Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq ZarrinHormoz.exe" | find /I "ZarrinHormoz.exe" >NUL', '',
                     SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0);
  Result := not Result;
end;

function InitializeSetup(): Boolean;
var
  FreeMB: Cardinal;
  DataDir: String;
begin
  Result := True;
  if not IsWin64 then
  begin
    MsgBox('این نسخه فقط روی ویندوز ۶۴ بیتی اجرا می‌شود.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if GetWindowsVersionEx(GetWindowsVersion) and (GetWindowsVersion.Major < 10) then
  begin
    MsgBox('حداقل نسخهٔ پشتیبانی‌شده ویندوز ۱۰ است.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  DataDir := DataFolder();
  if DirExists(DataDir) then
  begin
    if not DirExists(AddBackslash(DataDir) + 'data') then
      CreateDir(AddBackslash(DataDir) + 'data');
  end
  else
  begin
    if not ForceDirectories(DataDir) then
    begin
      MsgBox('پوشهٔ داده ساخته نشد: ' + DataDir + #13#10 +
             'دسترسی نوشتن در این مسیر را بررسی کنید.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
  if GetSpaceOnDisk(DataDir, True, FreeMB) and (FreeMB < 512) then
  begin
    MsgBox('فضای آزاد کافی برای داده‌ها وجود ندارد (حداقل ۵۱۲ مگابایت).',
           mbError, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard();
begin
  KeepDataPage := CreateInputOptionPage(wpSelectTasks,
    'داده‌های حسابداری',
    'این مرحله فقط روی داده‌های موجود اثر دارد',
    'فایل پایگاه داده، پشتیبان‌ها و گزارش‌ها در پوشهٔ زیر نگهداری می‌شوند:' + #13#10 +
    DataFolder() + #13#10#13#10 +
    'نصب و به‌روزرسانی هرگز این پوشه را پاک نمی‌کند. اگر می‌خواهید هنگام حذف برنامه ' +
    'داده‌ها هم پاک شوند، گزینهٔ دوم را انتخاب کنید (توصیه نمی‌شود).',
    False, False);
  KeepDataPage.Add('داده‌ها حفظ شوند (توصیه‌شده)');
  KeepDataPage.Add('داده‌ها هنگام حذف برنامه پاک شوند');
  KeepDataPage.Values[0] := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    { Take a verified backup before the new version touches the schema. }
    Exec(ExpandConstant('{app}\') + '{#ConsoleExe}',
         'backup --note "پشتیبان خودکار پیش از اجرای نسخهٔ {#AppVersion}"',
         ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := DataFolder();
    if DirExists(DataDir) then
    begin
      if (KeepDataPage <> nil) and (KeepDataPage.Values[1]) then
      begin
        if MsgBox('همهٔ داده‌های حسابداری، پشتیبان‌ها و گزارش‌ها در' + #13#10 + DataDir +
                  #13#10 + 'برای همیشه پاک شوند؟ این کار بازگشت‌پذیر نیست.',
                  mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
          DelTree(DataDir, True, True, True)
        else
          MsgBox('داده‌ها حفظ شدند: ' + DataDir, mbInformation, MB_OK);
      end
      else
        MsgBox('برنامه حذف شد اما داده‌های شما در مسیر زیر باقی مانده است:' + #13#10 +
               DataDir + #13#10 +
               'برای پاک کردن کامل، این پوشه را دستی حذف کنید.', mbInformation, MB_OK);
    end;
  end;
end;

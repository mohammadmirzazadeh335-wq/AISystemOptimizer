# اعمال یک به‌روزرسانی آماده‌شده (staged) با بررسی سلامت و بازگردانی خودکار.
#
# نمونهٔ اجرا:
#   pwsh -File packaging\apply_update.ps1 -InstallDir "C:\Program Files\ZarrinHormoz"
#
# پیش‌شرط: کاربر (یا برنامه) پیش‌تر `ZarrinHormoz-console.exe update stage --package ...`
# را اجرا کرده باشد، پس فایل `%APPDATA%\ParsERP\updates\pending.json` وجود دارد
# و یک پشتیبان تأییدشدهٔ پایگاه داده در `backups\` ثبت شده است.

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:ProgramFiles\ZarrinHormoz",
    [string]$DataDir = "$env:APPDATA\ParsERP",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$console = Join-Path $InstallDir "ZarrinHormoz-console.exe"
$marker = Join-Path $DataDir "updates\pending.json"

function Fail($text) { Write-Host "خطا: $text" -ForegroundColor Red; exit 1 }
function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

if (-not (Test-Path $console)) { Fail "فایل خط فرمان برنامه یافت نشد: $console" }
if (-not (Test-Path $marker)) { Fail "هیچ به‌روزرسانی آماده‌ای وجود ندارد ($marker)." }

$pending = Get-Content $marker -Raw | ConvertFrom-Json
Step "به‌روزرسانی $($pending.from_version) -> $($pending.to_version)"
Step "وضعیت امضا: $($pending.signature_status)"
if ($pending.signature_status -ne "verified") {
    Fail ("امضای بسته تأیید نشده است. برای نصب دستی، سیاست امضا را در تنظیمات تغییر دهید؛ " +
          "این اسکریپت هرگز بستهٔ تأییدنشده را نصب نمی‌کند.")
}
if (-not $pending.backup) { Fail "پشتیبان پیش از به‌روزرسانی ثبت نشده است؛ نصب متوقف شد." }

$backupFile = Join-Path $DataDir ("backups\" + $pending.backup)
if (-not (Test-Path $backupFile)) { Fail "فایل پشتیبان یافت نشد: $backupFile" }

$package = Join-Path $DataDir ("updates\" + $pending.package)
if (-not (Test-Path $package)) { Fail "فایل بستهٔ به‌روزرسانی یافت نشد: $package" }

Step "بررسی هش بسته پیش از نصب"
$hash = (Get-FileHash $package -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $pending.sha256) { Fail "هش بسته با مانیفست برابر نیست؛ نصب متوقف شد." }

if ($DryRun) { Write-Host "حالت آزمایشی: هیچ تغییری اعمال نشد."; exit 0 }

Step "بستن برنامه در حال اجرا"
Get-Process ZarrinHormoz -ErrorAction SilentlyContinue | ForEach-Object {
    $_.CloseMainWindow() | Out-Null
    if (-not $_.WaitForExit(30000)) { $_.Kill() }
}

Step "اجرای نصب‌کننده به‌صورت بی‌صدا"
$process = Start-Process -FilePath $package -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
if ($process.ExitCode -ne 0) { Fail "نصب‌کننده با کد $($process.ExitCode) پایان یافت." }

Step "بررسی سلامت پس از به‌روزرسانی"
& $console doctor
$health = $LASTEXITCODE
if ($health -ne 0) {
    Write-Host "بررسی سلامت ناموفق بود؛ بازگردانی پایگاه داده به وضعیت پیش از به‌روزرسانی..." -ForegroundColor Yellow
    & $console update rollback --confirm "بازیابی"
    if ($LASTEXITCODE -ne 0) {
        Fail ("بازگردانی خودکار ناموفق بود. فایل پشتیبان را دستی بازیابی کنید: " + $backupFile)
    }
    Write-Host "پایگاه داده بازگردانی شد. برای نصب مجدد، مشکل را بررسی کنید." -ForegroundColor Yellow
    exit 5
}

Remove-Item $marker -Force
Write-Host "`nبه‌روزرسانی با موفقیت اعمال و تأیید شد." -ForegroundColor Green

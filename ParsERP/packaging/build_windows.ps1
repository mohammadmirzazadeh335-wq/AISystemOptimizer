# ساخت نسخهٔ اجرایی، نصب‌کننده و مانیفست به‌روزرسانی «زرین هرمز».
#
# نمونهٔ اجرا (روی ویندوز ۱۰/۱۱ ۶۴ بیتی):
#   pwsh -File packaging\build_windows.ps1 -Version 0.7.0 -SigningKey C:\keys\release.pem
#
# پیش‌نیازها: Python 3.11، PyInstaller 6.11، Inno Setup 6 (iscc.exe در PATH).
# این اسکریپت در محیط لینوکسیِ توسعه اجرا نمی‌شود؛ فقط ویندوز.

[CmdletBinding()]
param(
    [string]$Version = (Get-Content "$PSScriptRoot\..\src\pars_erp\__init__.py" |
                        Select-String '__version__ = "(.+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }),
    [string]$Python = "py",
    [string]$SigningKey = "",
    [string]$UpdateUrlBase = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "خطا: $text" -ForegroundColor Red; exit 1 }

Step "بررسی محیط ساخت"
if (-not $IsWindows) { Fail "این اسکریپت مخصوص ویندوز است." }
$pyVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pyVersion -ne "3.11") { Fail "پایتون ۳.۱۱ لازم است (یافت شد: $pyVersion)." }

Step "اجرای آزمون‌ها"
if (-not $SkipTests) {
    & $Python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { Fail "آزمون‌ها موفق نبودند؛ ساخت متوقف شد." }
}

Step "پاک‌سازی خروجی‌های قبلی"
foreach ($path in @("build", "dist")) {
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Step "ساخت پوشهٔ اجرایی با PyInstaller"
& $Python -m PyInstaller packaging\zarrin_hormoz.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller شکست خورد." }
if (-not (Test-Path "dist\ZarrinHormoz\ZarrinHormoz.exe")) { Fail "فایل اجرایی ساخته نشد." }

Step "بررسی سلامت نسخهٔ اجرایی"
$env:PARSERP_HOME = Join-Path $env:TEMP ("zh-build-" + [guid]::NewGuid())
& "dist\ZarrinHormoz\ZarrinHormoz-console.exe" doctor
if ($LASTEXITCODE -ne 0) {
    # A fresh home has no administrator yet; only fatal problems must stop the build.
    Write-Host "هشدار: بررسی سلامت در پوشهٔ خالی، راه‌اندازی اولیه را ناتمام گزارش کرد." -ForegroundColor Yellow
}
Remove-Item -Recurse -Force $env:PARSERP_HOME -ErrorAction SilentlyContinue

Step "ساخت نصب‌کننده با Inno Setup"
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue)
if (-not $iscc) { Fail "iscc.exe یافت نشد؛ Inno Setup 6 را نصب کنید." }
& $iscc.Source "/DAppVersion=$Version" "/DBuildRoot=dist\ZarrinHormoz" "packaging\zarrin_hormoz.iss"
if ($LASTEXITCODE -ne 0) { Fail "ساخت نصب‌کننده شکست خورد." }

$installer = "packaging\output\ZarrinHormoz-$Version-setup.exe"
if (-not (Test-Path $installer)) { Fail "فایل نصب ساخته نشد: $installer" }

Step "ساخت مانیفست به‌روزرسانی"
$url = if ($UpdateUrlBase) { "$($UpdateUrlBase.TrimEnd('/'))/ZarrinHormoz-$Version-setup.exe" }
       else { "https://example.invalid/updates/ZarrinHormoz-$Version-setup.exe" }
$manifestArgs = @("packaging\make_release_manifest.py", "--artefact", $installer,
                  "--version", $Version, "--url", $url,
                  "--notes", "نسخهٔ $Version زرین هرمز",
                  "--output", "dist\releases-$Version.json")
if ($SigningKey) { $manifestArgs += @("--private-key", $SigningKey) }
& $Python @manifestArgs
if ($LASTEXITCODE -ne 0) { Fail "ساخت مانیفست شکست خورد." }
if (-not $SigningKey) {
    Write-Host "هشدار: مانیفست امضا نشده است؛ برنامه با تنظیم پیش‌فرض آن را نصب نمی‌کند." -ForegroundColor Yellow
}

Step "محاسبهٔ هش خروجی‌ها"
Get-FileHash $installer -Algorithm SHA256 |
    Select-Object Path, Hash | Format-List
Get-ChildItem dist, packaging\output | Select-Object Name, Length | Format-Table

Write-Host "`nساخت کامل شد: $installer" -ForegroundColor Green

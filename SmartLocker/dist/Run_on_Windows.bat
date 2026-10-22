@echo off
echo Smart Locker Generator - Windows + SolidWorks 2025
echo ===================================================
REM Option 1: Python version (works without SolidWorks - DRY-RUN)
python smart_locker_generator.py --output "D:\SmartLocker_CAD" --verbose
REM Option 2: Native binary (if compiled for Windows available, use SmartLockerGenerator.exe)
REM SmartLockerGenerator.exe --output "D:\SmartLocker_CAD" --verbose
pause

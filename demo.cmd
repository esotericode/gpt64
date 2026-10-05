@echo off
setlocal
cd /d "%~dp0"
py -3 scripts\bootstrap.py --demo
if errorlevel 1 echo Check the error above and docs\windows.md.
pause
exit /b

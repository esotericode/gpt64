@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto setup_needed
".venv\Scripts\python.exe" -m gpt64 serve --demo
pause
exit /b
:setup_needed
echo Run setup-windows.cmd first, then demo.cmd again.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto setup_needed
".venv\Scripts\python.exe" -m gpt64 serve --billing chatgpt
pause
exit /b
:setup_needed
echo Run setup-windows.cmd first, then start.cmd again.
pause
exit /b 1

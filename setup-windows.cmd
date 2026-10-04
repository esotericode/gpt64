@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 goto python_error
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install ".[signin]"
if errorlevel 1 goto failed
echo.
echo Setup complete. Open START-HERE.md, then run demo.cmd or start.cmd.
pause
exit /b 0
:python_error
echo Install Python 3.11 or newer with its Windows launcher, then run this again.
pause
exit /b 1
:failed
echo Setup failed. Keep the error above and check docs\windows.md.
pause
exit /b 1

@echo off
cd /d "%~dp0"
"venv\Scripts\python.exe" "train_friday.py" %*
if errorlevel 1 pause

@echo off
cd /d "%~dp0"
if exist "ClaudeCodeManager.exe" (
    start "" "ClaudeCodeManager.exe"
) else (
    echo Building...
    python -m pip install pyinstaller -q
    python -m PyInstaller --noconsole --onefile --name ClaudeCodeManager --add-data "static;static" app.py
    copy dist\ClaudeCodeManager.exe ClaudeCodeManager.exe
    start "" "ClaudeCodeManager.exe"
)
exit

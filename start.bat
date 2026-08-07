@echo off
cd /d "%~dp0"
if exist "ClaudeCodeManager\ClaudeCodeManager.exe" (
    start "" "ClaudeCodeManager\ClaudeCodeManager.exe"
) else (
    echo Building...
    python -m pip install -r requirements.txt -q
    python -m PyInstaller ClaudeCodeManager.spec
    if exist "dist\ClaudeCodeManager" move /Y "dist\ClaudeCodeManager" "ClaudeCodeManager"
    start "" "ClaudeCodeManager\ClaudeCodeManager.exe"
)
exit

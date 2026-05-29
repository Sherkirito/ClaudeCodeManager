' Claude Code Manager - Silent Launcher (no console window)
Set ws = CreateObject("Wscript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
ws.Run "pythonw """ & scriptDir & "\app.py""", 0, False

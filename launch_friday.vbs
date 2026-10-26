' Start FRIDAY's taskbar controls without a console window.
' The desktop process owns startup, duplicate activation and backend cleanup.
Option Explicit
Dim shell, files, root, pythonw
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\venv\Scripts\pythonw.exe"
shell.CurrentDirectory = root
shell.Run """" & pythonw & """ -B """ & root & "\interfaces\taskbar\launch.py""", 0, False

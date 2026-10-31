' Open native College Schedules; reuse FRIDAY's managed backend startup.
Option Explicit
Dim shell, files, root, pythonw
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\venv\Scripts\pythonw.exe"
shell.CurrentDirectory = root
shell.Run """" & pythonw & """ -B -m interfaces.college --ensure-backend", 0, False

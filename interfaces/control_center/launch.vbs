' Open FRIDAY Control Center from Explorer without a console.
Option Explicit
Dim shell, files, root, pythonw
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(files.GetParentFolderName(files.GetParentFolderName(WScript.ScriptFullName)))
pythonw = root & "\venv\Scripts\pythonw.exe"
shell.CurrentDirectory = root
shell.Run """" & pythonw & """ -B -m interfaces.control_center", 0, False

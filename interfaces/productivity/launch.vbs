Option Explicit
Dim files, shell, project, python
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
project = files.GetParentFolderName(files.GetParentFolderName(files.GetParentFolderName(WScript.ScriptFullName)))
python = files.BuildPath(project, "venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
    MsgBox "FRIDAY's Python environment was not found. See docs/HABITS_AND_TODO.md.", 48, "FRIDAY"
    WScript.Quit 1
End If
shell.CurrentDirectory = project
shell.Run Chr(34) & python & Chr(34) & " -B -m interfaces.productivity", 0, False

Option Explicit

Dim shell, fso, appDir, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir
command = "pyw.exe -3 """ & fso.BuildPath(appDir, "app.py") & """"
shell.Run command, 0, False

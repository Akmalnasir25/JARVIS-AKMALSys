' ============================================================
'  Jarvis launcher
'
'  Why this exists: the old Desktop shortcut pointed straight at
'  pythoncore-3.14-64\pythonw.exe. The day that folder is renamed
'  by a Python upgrade, the shortcut dies silently -- double-click,
'  nothing happens, no error, because pythonw swallows everything.
'
'  This resolves Python at launch time, in order of reliability,
'  and shows a real dialog when it cannot find one. It runs
'  main.py from its own folder, so the whole project can be moved
'  or cloned elsewhere without editing a path.
'
'  Run it directly, or through a shortcut to wscript.exe.
'  Check what it resolves without starting the HUD:
'      cscript //nologo launch.vbs --check
' ============================================================
Option Explicit

Dim fso, sh, here, app, checkOnly
Dim py, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

here  = fso.GetParentFolderName(WScript.ScriptFullName)
app   = here & "\main.py"
' VBScript has no short-circuit And/Or: both sides are always evaluated, so
' Unnamed(0) is guarded by its own nested If rather than by "And".
checkOnly = False
If WScript.Arguments.Named.Exists("check") Then
    checkOnly = True
ElseIf WScript.Arguments.Unnamed.Count > 0 Then
    If LCase(WScript.Arguments.Unnamed(0)) = "--check" Then
        checkOnly = True
    End If
End If

If Not fso.FileExists(app) Then
    MsgBox "main.py is not next to this launcher." & vbCrLf & vbCrLf & _
           "Expected: " & app & vbCrLf & vbCrLf & _
           "The launcher has to sit in the jarvis-desktop folder.", _
           16, "Jarvis - can't start"
    WScript.Quit 1
End If

py = ResolvePython()
If py = "" Then
    MsgBox "No Python found on this machine." & vbCrLf & vbCrLf & _
           "Looked for, in order:" & vbCrLf & _
           "  1. the py launcher  (pyw.exe)" & vbCrLf & _
           "  2. pythonw.exe on PATH" & vbCrLf & _
           "  3. %LOCALAPPDATA%\Python\pythoncore-*\pythonw.exe" & vbCrLf & _
           "  4. %LOCALAPPDATA%\Programs\Python\Python*\pythonw.exe" & vbCrLf & vbCrLf & _
           "Install Python 3.11+ from python.org and run this again.", _
           16, "Jarvis - no Python"
    WScript.Quit 2
End If

cmd = """" & py & """ """ & """" & app & """"

If checkOnly Then
    WScript.Echo "python : " & py
    WScript.Echo "app    : " & app
    WScript.Echo "command: " & cmd
    WScript.Quit 0
End If

' WindowState 1 = normal. pythonw has no console, so nothing flashes.
' The HUD itself goes fullscreen from inside main.py.
sh.CurrentDirectory = here
On Error Resume Next
sh.Run cmd, 1, False
If Err.Number <> 0 Then
    MsgBox "Python started but refused the command." & vbCrLf & vbCrLf & _
           cmd & vbCrLf & vbCrLf & Err.Description, 16, "Jarvis - launch failed"
    WScript.Quit 3
End If


' ------------------------------------------------------------
Function ResolvePython()
    Dim p
    ResolvePython = ""

    ' 1. The py launcher. It is installed by every python.org build,
    '    it is always on PATH, and pyw.exe is its windowless twin.
    p = FindOnPath("pyw.exe")
    If p <> "" Then ResolvePython = p : Exit Function

    ' 2. A bare pythonw.exe on PATH.
    p = FindOnPath("pythonw.exe")
    If p <> "" Then ResolvePython = p : Exit Function

    ' 3. The pythoncore-* layout used by the Store / winget builds.
    p = NewestUnder(sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python", "pythonw.exe")
    If p <> "" Then ResolvePython = p : Exit Function

    ' 4. The classic python.org install layout.
    p = NewestUnder(sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python", "pythonw.exe")
    If p <> "" Then ResolvePython = p : Exit Function

    ' 5. Last resort: the interpreter running this script's sibling.
    p = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\python.exe"
    If fso.FileExists(p) Then ResolvePython = p
End Function


' where.exe is the only lookup that respects PATHEXT and App Paths.
Function FindOnPath(exe)
    Dim exec, line
    FindOnPath = ""
    On Error Resume Next
    Set exec = sh.Exec("%comspec% /c where " & exe & " 2>nul")
    If Err.Number <> 0 Then Exit Function
    Do While Not exec.StdOut.AtEndOfStream
        line = Trim(exec.StdOut.ReadLine())
        If line <> "" And fso.FileExists(line) Then
            FindOnPath = line
            Exit Function
        End If
    Loop
End Function


' Walks immediate subfolders of root and returns the newest hit, so
' pythoncore-3.14-64 wins over pythoncore-3.12-64 once both exist.
Function NewestUnder(root, exe)
    Dim f, dir, candidate, best, bestTime
    NewestUnder = ""
    If Not fso.FolderExists(root) Then Exit Function
    bestTime = 0
    For Each dir In fso.GetFolder(root).SubFolders
        candidate = dir.Path & "\" & exe
        If fso.FileExists(candidate) Then
            If dir.DateLastModified > bestTime Then
                bestTime = dir.DateLastModified
                best = candidate
            End If
        End If
        ' one level deeper covers Programs\Python\Python312\pythonw.exe
        For Each f In fso.GetFolder(dir.Path).SubFolders
            candidate = f.Path & "\" & exe
            If fso.FileExists(candidate) Then
                If f.DateLastModified > bestTime Then
                    bestTime = f.DateLastModified
                    best = candidate
                End If
            End If
        Next
    Next
    NewestUnder = best
End Function

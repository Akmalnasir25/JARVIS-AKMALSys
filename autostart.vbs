' ============================================================
'  Start Jarvis at login -- install or remove
'
'      cscript //nologo autostart.vbs --install
'      cscript //nologo autostart.vbs --remove
'      cscript //nologo autostart.vbs --status
'
'  Writes a shortcut into the user's Startup folder, which is the
'  supported way to start a GUI program at login on Windows. It is
'  per-user, survives a reboot, needs no admin rights, and can be
'  undone by deleting one .lnk -- no registry, no scheduled task.
'
'  The shortcut points at launch.vbs, not at a Python path, so the
'  autostart keeps working across a Python upgrade the same way the
'  Desktop icon does.
' ============================================================
Option Explicit

Dim fso, sh, here, action, startupDir, linkPath

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
startupDir = sh.SpecialFolders("Startup")
linkPath = startupDir & "\Jarvis HUD.lnk"

action = "status"
If WScript.Arguments.Unnamed.Count > 0 Then
    action = LCase(Replace(WScript.Arguments.Unnamed(0), "-", ""))
End If

Select Case action
    Case "install"
        If Not fso.FileExists(here & "\launch.vbs") Then
            WScript.Echo "launch.vbs is missing from " & here
            WScript.Quit 1
        End If
        MakeLink
        WScript.Echo "installed : " & linkPath
        WScript.Echo "target    : " & here & "\launch.vbs"
        WScript.Echo "Jarvis will start at the next login."

    Case "remove"
        If fso.FileExists(linkPath) Then
            fso.DeleteFile linkPath, True
            WScript.Echo "removed   : " & linkPath
        Else
            WScript.Echo "nothing to remove -- no startup entry at " & linkPath
        End If

    Case "status"
        If fso.FileExists(linkPath) Then
            WScript.Echo "enabled   : " & linkPath
        Else
            WScript.Echo "disabled  : no startup entry"
        End If

    Case Else
        WScript.Echo "usage: cscript //nologo autostart.vbs --install | --remove | --status"
        WScript.Quit 1
End Select


Sub MakeLink()
    Dim lnk
    Set lnk = sh.CreateShortcut(linkPath)
    lnk.TargetPath = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
    lnk.Arguments = """" & here & "\launch.vbs"""
    lnk.WorkingDirectory = here
    lnk.IconLocation = here & "\logo.ico,0"
    lnk.Description = "Jarvis HUD"
    lnk.WindowStyle = 1
    lnk.Save
End Sub

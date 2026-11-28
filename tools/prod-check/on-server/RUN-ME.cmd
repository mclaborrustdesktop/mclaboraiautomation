@echo off
rem MC Labor one-time setup on the live SQL Server. Right-click this file and choose "Run as administrator".
rem It asks before every change. Nothing restores, drops or replaces a database; no business record is read or changed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-ReadOnlyLogin-OnServer.ps1"
echo.
echo Finished. The report is in the "results" folder next to this file (and on the clipboard).
echo Please give the whole "results" folder back to the MC Labor project. You can close this window.
pause

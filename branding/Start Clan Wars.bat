@echo off
setlocal DisableDelayedExpansion
set "runtime=%~dp0Client Files"
if not exist "%runtime%\python\pythonw.exe" goto :missing
if not exist "%runtime%\clan_wars_windows.pyw" goto :missing
start "" /d "%runtime%" "%runtime%\python\pythonw.exe" -B "%runtime%\clan_wars_windows.pyw"
exit /b %errorlevel%

:missing
echo Extract the entire Clan Wars ZIP before launching.
pause
exit /b 1

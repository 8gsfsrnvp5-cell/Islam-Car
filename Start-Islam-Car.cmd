@echo off
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1"
set "ISLAMCAR_EXIT=%ERRORLEVEL%"
pause
exit /b %ISLAMCAR_EXIT%

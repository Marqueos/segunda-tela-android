@echo off
rem Segunda Tela: clique duas vezes para instalar.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause

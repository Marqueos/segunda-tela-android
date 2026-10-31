@echo off
rem Segunda Tela: clique duas vezes para montar o dist\SegundaTela.exe.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0montar-exe.ps1"
echo.
pause

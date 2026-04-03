@echo off
chcp 65001 >nul
title Ollama Agent - Start Ollama
cls
call "%~dp0find-ollama.bat" || goto :end
call "%~dp0ensure-ollama-running.bat"
if errorlevel 1 (
    echo [ERROR] Ollama no respondio tras arrancar `serve`.
    echo Abre Ollama manualmente y prueba otra vez.
    goto :end
)
echo Ollama esta listo en http://localhost:11434

:end
pause

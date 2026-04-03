@echo off
chcp 65001 >nul
title Ollama Agent - Pull qwen2.5-coder:3b
cls
call "%~dp0find-ollama.bat" || goto :end
call "%~dp0ensure-ollama-running.bat" || goto :backend_error
%OLLAMA_AGENT_OLLAMA% pull qwen2.5-coder:3b
goto :end

:backend_error
echo [ERROR] Ollama no responde en http://localhost:11434.
echo Usa START OLLAMA.bat o inicia Ollama manualmente.
:end
pause

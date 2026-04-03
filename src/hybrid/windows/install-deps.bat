@echo off
chcp 65001 >nul
title Ollama Agent - Install Hybrid Dependencies
cls
echo Instalando dependencias del agente hibrido...
call "%~dp0find-python.bat" || goto :end
%OLLAMA_AGENT_PYTHON% "%~dp0..\..\..\scripts\install.py" --hybrid
:end
pause

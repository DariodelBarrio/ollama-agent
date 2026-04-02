@echo off
chcp 65001 >nul
title Ollama Agent - Install Hybrid Dependencies
cls
echo Instalando dependencias del agente hibrido...
python "%~dp0..\..\..\scripts\install.py" --hybrid
pause

@echo off
chcp 65001 >nul
title Descargando modelos sin censura...
cls
echo.
echo  Descargando modelos sin censura...
echo.
echo [1/3] dolphin3:8b
ollama pull dolphin3:8b
echo.
echo [2/3] hermes3:8b
ollama pull hermes3:8b
echo.
echo [3/3] llama3-groq-tool-use:8b
ollama pull llama3-groq-tool-use:8b
echo.
echo  Listo.
pause

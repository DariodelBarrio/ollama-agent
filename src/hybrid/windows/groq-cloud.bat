@echo off
chcp 65001 >nul
title Ollama Agent - Hybrid Groq Cloud
cls
if "%GROQ_API_KEY%"=="" (
    echo [ERROR] Variable GROQ_API_KEY no definida.
    echo Definela con: setx GROQ_API_KEY tu_clave
    pause
    exit /b 1
)
python "%~dp0..\agent.py" --model qwen2.5-coder:14b --groq-model llama-3.3-70b-versatile --dir "%CD%" --tag GROQ --ctx 32768 --backend groq
pause

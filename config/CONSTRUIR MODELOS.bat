@echo off
chcp 65001 >nul
title Construyendo modelos personalizados...
cls

echo.
echo  Construyendo modelos personalizados con reglas integradas...
echo  Esto tarda ~30 segundos por modelo.
echo.

echo  [1/2] sonnet-agente (qwen3:14b + reglas permanentes)...
ollama create sonnet-agente -f "%~dp0Modelfile.sonnet"
if %errorlevel% neq 0 (
    echo  ERROR al crear sonnet-agente
) else (
    echo  OK - sonnet-agente listo
)

echo.
echo  [2/2] opus-agente (deepseek-r1:14b + reglas permanentes)...
ollama create opus-agente -f "%~dp0Modelfile.opus"
if %errorlevel% neq 0 (
    echo  ERROR al crear opus-agente
) else (
    echo  OK - opus-agente listo
)

echo.
echo  Modelos creados:
ollama list | findstr "agente"
echo.
pause

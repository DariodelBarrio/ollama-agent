@echo off
chcp 65001 >nul
title MEGA - Instalar dependencias
cls
echo Instalando dependencias para MEGA Agent...
echo.
pip install openai rich prompt_toolkit duckduckgo-search requests beautifulsoup4 pydantic
echo.
echo [OK] Dependencias instaladas.
echo.
echo Para usar Groq, define tu API key:
echo   set GROQ_API_KEY=tu_clave_aqui
echo.
echo Para usar SGLang (recomendado para RTX 5070):
echo   pip install sglang
echo   python -m sglang.launch_server --model qwen2.5-coder:14b --port 30000
echo.
echo Para usar vLLM:
echo   pip install vllm
echo   python -m vllm.entrypoints.openai.api_server --model qwen2.5-coder:14b --port 8000
echo.
pause

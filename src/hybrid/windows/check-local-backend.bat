@echo off
set "OLLAMA_AGENT_LOCAL_URL=%OLLAMA_AGENT_LOCAL_URL%"
if "%OLLAMA_AGENT_LOCAL_URL%"=="" set "OLLAMA_AGENT_LOCAL_URL=http://localhost:11434"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing '%OLLAMA_AGENT_LOCAL_URL%/api/tags' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul

if errorlevel 1 (
    echo [ERROR] El backend local no responde en %OLLAMA_AGENT_LOCAL_URL%.
    echo.
    echo Este launcher necesita un backend OpenAI-compatible local activo.
    echo Para Ollama normalmente es:
    echo   1. Inicia Ollama
    echo   2. Ejecuta: ollama serve
    echo   3. Descarga el modelo que vayas a usar
    echo.
    echo Ejemplos:
    echo   ollama pull qwen2.5-coder:7b
    echo   ollama pull deepseek-r1:14b
    exit /b 1
)

exit /b 0

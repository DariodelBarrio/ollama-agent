@echo off
set "OLLAMA_AGENT_OLLAMA="

if defined OLLAMA_AGENT_OLLAMA if exist "%OLLAMA_AGENT_OLLAMA%" goto :found

if exist "%LocalAppData%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_AGENT_OLLAMA=%LocalAppData%\Programs\Ollama\ollama.exe"
    goto :found
)

if exist "%ProgramFiles%\Ollama\ollama.exe" (
    set "OLLAMA_AGENT_OLLAMA=%ProgramFiles%\Ollama\ollama.exe"
    goto :found
)

ollama --version >nul 2>nul
if not errorlevel 1 (
    set "OLLAMA_AGENT_OLLAMA=ollama"
    goto :found
)

echo [ERROR] No se encontro ollama.exe.
echo.
echo Instala Ollama para usar los launchers locales:
echo   https://ollama.com/download/windows
echo.
echo Tambien puedes definir OLLAMA_AGENT_OLLAMA con la ruta completa a ollama.exe
exit /b 1

:found
exit /b 0

@echo off
set "OLLAMA_AGENT_PYTHON="

if defined OLLAMA_AGENT_PYTHON if exist "%OLLAMA_AGENT_PYTHON%" goto :found

if exist "%~dp0..\..\..\.venv\Scripts\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%~dp0..\..\..\.venv\Scripts\python.exe"
    goto :found
)

if exist "%~dp0..\..\..\venv\Scripts\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%~dp0..\..\..\venv\Scripts\python.exe"
    goto :found
)

if exist "%LocalAppData%\Python\bin\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%LocalAppData%\Python\bin\python.exe"
    goto :found
)

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
    goto :found
)

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
    goto :found
)

if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe"
    goto :found
)

if exist "%LocalAppData%\Programs\Python\Python39\python.exe" (
    set "OLLAMA_AGENT_PYTHON=%LocalAppData%\Programs\Python\Python39\python.exe"
    goto :found
)

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
    set "OLLAMA_AGENT_PYTHON=py -3"
    goto :found
)

python -c "import sys" >nul 2>nul
if not errorlevel 1 (
    set "OLLAMA_AGENT_PYTHON=python"
    goto :found
)

echo [ERROR] No se encontro un Python ejecutable para los launchers de Windows.
echo.
echo Opciones:
echo   1. Instala dependencias con una venv en la raiz del repo: .venv\Scripts\python.exe
echo   2. Usa tu Python local en %%LocalAppData%%\Python\bin\python.exe
echo   3. Define OLLAMA_AGENT_PYTHON con la ruta completa a python.exe
exit /b 1

:found
exit /b 0

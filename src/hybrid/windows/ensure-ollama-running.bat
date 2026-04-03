@echo off
call "%~dp0find-ollama.bat" || exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing 'http://localhost:11434/api/tags' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 exit /b 0

start "Ollama" /min %OLLAMA_AGENT_OLLAMA% serve
timeout /t 3 /nobreak >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing 'http://localhost:11434/api/tags' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 exit /b 1

exit /b 0

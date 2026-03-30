@echo off
chcp 65001 >nul
title Descargando modelos...
cls
echo.
echo  Descargando todos los modelos recomendados...
echo.
echo [1/9] qwen2.5-coder:14b  (Mejor coder todo-GPU)
ollama pull qwen2.5-coder:14b
echo.
echo [2/9] deepseek-r1:14b  (Razonamiento todo-GPU)
ollama pull deepseek-r1:14b
echo.
echo [3/9] deepseek-coder-v2:16b  (Coding MoE eficiente)
ollama pull deepseek-coder-v2:16b
echo.
echo [4/9] mistral-nemo:12b  (General + Coding)
ollama pull mistral-nemo:12b
echo.
echo [5/9] dolphin3:8b  (Sin censura rapido)
ollama pull dolphin3:8b
echo.
echo [6/9] dolphin-mistral:7b  (Sin censura Mistral)
ollama pull dolphin-mistral:7b
echo.
echo [7/9] qwen2.5-coder:7b  (Coder mas rapido)
ollama pull qwen2.5-coder:7b
echo.
echo [8/9] qwen2.5-coder:32b  (Maxima calidad coder)
ollama pull qwen2.5-coder:32b
echo.
echo [9/9] deepseek-r1:32b  (Thinking maximo)
ollama pull deepseek-r1:32b
echo.
echo  Todos los modelos descargados.
echo.
ollama list
pause

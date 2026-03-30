@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local CODER-V2 - deepseek-coder-v2:16b
cls
python "%~dp0..\..\src\agent.py" --model deepseek-coder-v2:16b --dir "%CD%" --tag CODER-V2 --ctx 32768
pause

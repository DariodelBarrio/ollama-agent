@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local CODER - qwen2.5-coder:14b
cls
python "%~dp0..\..\src\agent.py" --model qwen2.5-coder:14b --dir "%CD%" --tag CODER --ctx 32768
pause

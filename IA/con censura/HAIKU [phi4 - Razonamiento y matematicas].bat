@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local HAIKU - qwen2.5-coder:7b
cls
python "%~dp0..\..\src\agent.py" --model qwen2.5-coder:7b --dir "%CD%" --tag HAIKU --ctx 32768
pause

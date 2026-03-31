@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_KV_CACHE_TYPE=q8_0
title MEGA - SONNET [qwen2.5-coder:14b] RTX5070
cls
python "%~dp0agent.py" --model qwen2.5-coder:14b --dir "%CD%" --tag SONNET --ctx 8192 --backend auto
pause

@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_KV_CACHE_TYPE=q8_0
title Ollama Agent - Hybrid Local Coder
cls
python "%~dp0..\agent.py" --model qwen2.5-coder:14b --dir "%CD%" --tag LOCAL --ctx 8192 --backend auto
pause

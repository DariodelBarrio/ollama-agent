@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_KV_CACHE_TYPE=q8_0
title MEGA - OPUS [deepseek-r1:14b] Razonamiento
cls
python "%~dp0agent.py" --model deepseek-r1:14b --dir "%CD%" --tag OPUS --ctx 8192 --backend auto
pause

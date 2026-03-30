@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local OPUS - deepseek-r1:14b
cls
python "%~dp0..\..\src\agent.py" --model deepseek-r1:14b --dir "%CD%" --tag OPUS --ctx 32768
pause

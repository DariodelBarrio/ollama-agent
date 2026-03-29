@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local SONNET - sonnet-agente
cls
python "%~dp0..\..\src\agent.py" --model sonnet-agente:latest --dir "%CD%" --tag SONNET --ctx 16384
pause

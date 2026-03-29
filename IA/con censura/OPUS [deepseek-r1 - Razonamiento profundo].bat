@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local OPUS - opus-agente
cls
python "%~dp0..\..\src\agent.py" --model opus-agente:latest --dir "%CD%" --tag OPUS --ctx 16384
pause

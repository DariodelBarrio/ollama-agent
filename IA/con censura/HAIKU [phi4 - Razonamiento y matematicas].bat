@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local HAIKU - phi4:latest
cls
python "%~dp0..\..\src\agent.py" --model phi4:latest --dir "%CD%" --tag HAIKU --ctx 16384
pause

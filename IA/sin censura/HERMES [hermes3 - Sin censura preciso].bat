@echo off
chcp 65001 >nul
set OLLAMA_KEEP_ALIVE=-1
set OLLAMA_NUM_GPU=999
set CUDA_VISIBLE_DEVICES=0
title Agente Local HERMES - hermes3:8b
cls
python "%~dp0..\..\src\agent.py" --model hermes3:8b --dir "%CD%" --tag HERMES
pause

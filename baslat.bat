@echo off
cd /d "%~dp0"
start "Mobiloda site" cmd /k npm start
start "Mobiloda 3D isleyici" cmd /k worker\.venv\Scripts\python.exe worker\worker.py

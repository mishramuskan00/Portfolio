@echo off
cd /d "%~dp0"
py -3 -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

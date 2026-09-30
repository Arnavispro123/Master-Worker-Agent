@echo off
pip install -r requirements.txt
copy /Y .env.example .env >nul
echo Open http://127.0.0.1:8765 after start
python backend\app.py

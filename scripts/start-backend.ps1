# Start backend (browser HUD at http://127.0.0.1:8765)
pip install -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
python backend/app.py

#!/bin/bash
# ═══════════════════════════════════════════════════════
#  MiBloombergEficaz_2026 — Script de inicio Modular
# ═══════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Configurar Backend (FastAPI)
echo -e "\n[1/3] Iniciando Backend FastAPI..."
source ~/.python-global/bin/activate
pip install -q fastapi uvicorn requests beautifulsoup4 \
    python-telegram-bot websockets yfinance lxml numpy \
    instructor openai 2>/dev/null

# Matar backend previo si quedo zombie
pkill -f "uvicorn backend.main:app" 2>/dev/null

# Levantar backend en background
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

# 2. Configurar Frontend (Vite)
echo -e "\n[2/3] Arrancando Interfaz Web Vite..."
cd "$SCRIPT_DIR/frontend"

# Instalar dependencias node solo si no existe node_modules
if [ ! -d "node_modules" ]; then
    echo "Instalando paquetes npm por primera vez..."
    npm install
fi

# 3. Lanzar Vite y abrir navegador
echo -e "\n[3/3] ¡Sistema Bloomberg en línea!"
echo -e "➜ El backend corre en ws://localhost:8000/ws"
echo -e "➜ Cerrar esta ventana apagará todo (Ctrl+C)"

npm run dev -- --port 5173 --open

# Al cerrar con Ctrl+C, matar backend
kill $BACKEND_PID 2>/dev/null

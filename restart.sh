#!/bin/bash
cd /Users/wuchunjie/soft/ai_customer_service

# Kill existing processes
lsof -ti:8502 | xargs kill -9 2>/dev/null
lsof -ti:8501 | xargs kill -9 2>/dev/null
sleep 1

# Start backend
nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8502 > /tmp/backend.log 2>&1 &
echo "Backend started (PID $!)"

# Start frontend
nohup python3 -m streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0 > /tmp/frontend.log 2>&1 &
echo "Frontend started (PID $!)"

sleep 2
echo "=== Backend health ==="
curl -s http://127.0.0.1:8502/health 2>/dev/null || echo "Backend not ready yet"

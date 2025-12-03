#!/bin/bash

# AI Ministry - Start script

echo "Starting AI Ministry..."
echo ""

# Check if LiteLLM should be started
START_LITELLM=${START_LITELLM:-true}

if [ "$START_LITELLM" = "true" ]; then
    # Check if litellm is installed
    if command -v litellm &> /dev/null; then
        echo "Starting LiteLLM proxy on http://localhost:4000..."
        litellm --config litellm_config.yaml --port 4000 &
        LITELLM_PID=$!
        sleep 3
    else
        echo "Warning: LiteLLM not installed. Install with: pip install 'litellm[proxy]'"
        echo "Continuing without LiteLLM (ensure LLM_API_URL points to a valid endpoint)"
        echo ""
    fi
fi

# Start backend
echo "Starting backend on http://localhost:8001..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend
echo "Starting frontend on http://localhost:5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "AI Ministry is running!"
if [ -n "$LITELLM_PID" ]; then
    echo "  LiteLLM:  http://localhost:4000"
fi
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop all servers"

# Wait for Ctrl+C
cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$LITELLM_PID" ] && kill $LITELLM_PID 2>/dev/null
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit
}
trap cleanup SIGINT SIGTERM
wait

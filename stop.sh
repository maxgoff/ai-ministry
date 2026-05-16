#!/bin/bash

# AI Ministry - Stop script
# Stops all running AI Ministry services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Stopping AI Ministry services...${NC}"

PID_FILE="$SCRIPT_DIR/.ai-ministry.pids"
STOPPED=0

# Stop processes from PID file
if [ -f "$PID_FILE" ]; then
    while read -r pid name; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping $name (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            STOPPED=$((STOPPED + 1))
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Also check for processes on known ports — prefer the dynamic ports
# chosen by the last start.sh run, fall back to defaults.
PORTS_FILE="$SCRIPT_DIR/.ai-ministry.ports"
if [ -f "$PORTS_FILE" ]; then
    # shellcheck disable=SC1090
    source "$PORTS_FILE"
fi
LITELLM_PORT=${LITELLM_PORT:-4000}
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-5173}

for port in $LITELLM_PORT $BACKEND_PORT $FRONTEND_PORT; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        case $port in
            $LITELLM_PORT) name="LiteLLM" ;;
            $BACKEND_PORT) name="Backend" ;;
            $FRONTEND_PORT) name="Frontend" ;;
        esac
        echo "  Stopping $name on port $port (PID $pid)..."
        kill $pid 2>/dev/null || true
        STOPPED=$((STOPPED + 1))
    fi
done

rm -f "$PORTS_FILE"

if [ $STOPPED -eq 0 ]; then
    echo -e "${YELLOW}No running services found.${NC}"
else
    echo -e "${GREEN}All services stopped.${NC}"
fi

#!/bin/bash

# AI Ministry - Start script
# Starts LiteLLM, backend, and frontend services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════╗"
echo "║         AI Ministry Startup           ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# =============================================================================
# Load and validate environment
# =============================================================================

if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo ""
    echo "Create a .env file by copying the example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env and add your API keys."
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

echo -e "${GREEN}✓${NC} Loaded .env file"

# Validate required environment variables
MISSING_VARS=()

if [ -z "$LLM_API_KEY" ] || [ "$LLM_API_KEY" = "your-api-key-here" ]; then
    MISSING_VARS+=("LLM_API_KEY")
fi

# Check for at least one provider key if using LiteLLM (localhost:4000)
if [[ "$LLM_API_URL" == *"localhost:4000"* ]]; then
    HAS_PROVIDER_KEY=false
    [ -n "$OPENAI_API_KEY" ] && [ "$OPENAI_API_KEY" != "sk-..." ] && HAS_PROVIDER_KEY=true
    [ -n "$ANTHROPIC_API_KEY" ] && [ "$ANTHROPIC_API_KEY" != "sk-ant-..." ] && HAS_PROVIDER_KEY=true
    [ -n "$GOOGLE_API_KEY" ] && [ "$GOOGLE_API_KEY" != "AI..." ] && HAS_PROVIDER_KEY=true

    if [ "$HAS_PROVIDER_KEY" = false ]; then
        echo -e "${YELLOW}Warning: No provider API keys found for LiteLLM${NC}"
        echo "Set at least one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY"
        echo ""
    fi
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    echo ""
    echo "Edit your .env file and set these variables."
    exit 1
fi

echo -e "${GREEN}✓${NC} Environment validated"

# =============================================================================
# Configuration
# =============================================================================

# Starting ports — actual ports are chosen dynamically via find_free_port()
# so that conflicts with other apps don't require killing them.
LITELLM_PORT_START=${LITELLM_PORT:-4000}
BACKEND_PORT_START=${BACKEND_PORT:-8000}
FRONTEND_PORT_START=${FRONTEND_PORT:-5173}
START_LITELLM=${START_LITELLM:-true}

# PID file for tracking processes
PID_FILE="$SCRIPT_DIR/.ai-ministry.pids"
PORTS_FILE="$SCRIPT_DIR/.ai-ministry.ports"

# Walk forward from $1 until a free TCP port is found, echo it.
# $2 (optional) = max attempts (default 200).
find_free_port() {
    local port=$1
    local max_tries=${2:-200}
    local i
    for ((i=0; i<max_tries; i++)); do
        if ! lsof -ti :$port >/dev/null 2>&1; then
            echo "$port"
            return 0
        fi
        port=$((port + 1))
    done
    return 1
}

# =============================================================================
# Cleanup function
# =============================================================================

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down services...${NC}"

    if [ -f "$PID_FILE" ]; then
        while read -r pid name; do
            if kill -0 "$pid" 2>/dev/null; then
                echo "  Stopping $name (PID $pid)..."
                kill "$pid" 2>/dev/null || true
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi

    # Also kill any orphaned processes on the ports we claimed
    for port in $LITELLM_PORT $BACKEND_PORT $FRONTEND_PORT; do
        [ -z "$port" ] && continue
        pid=$(lsof -ti :$port 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill $pid 2>/dev/null || true
        fi
    done

    rm -f "$PORTS_FILE"

    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# =============================================================================
# Pick ports dynamically (walks forward from defaults to avoid conflicts)
# =============================================================================

if [ "$START_LITELLM" = "true" ]; then
    LITELLM_PORT=$(find_free_port $LITELLM_PORT_START) || {
        echo -e "${RED}Error: no free LiteLLM port near $LITELLM_PORT_START${NC}"; exit 1; }
    if [ "$LITELLM_PORT" != "$LITELLM_PORT_START" ]; then
        echo -e "${YELLOW}!${NC} LiteLLM port $LITELLM_PORT_START in use → using $LITELLM_PORT"
    fi
fi

BACKEND_PORT=$(find_free_port $BACKEND_PORT_START) || {
    echo -e "${RED}Error: no free backend port near $BACKEND_PORT_START${NC}"; exit 1; }
if [ "$BACKEND_PORT" != "$BACKEND_PORT_START" ]; then
    echo -e "${YELLOW}!${NC} Backend port $BACKEND_PORT_START in use → using $BACKEND_PORT"
fi

FRONTEND_PORT=$(find_free_port $FRONTEND_PORT_START) || {
    echo -e "${RED}Error: no free frontend port near $FRONTEND_PORT_START${NC}"; exit 1; }
if [ "$FRONTEND_PORT" != "$FRONTEND_PORT_START" ]; then
    echo -e "${YELLOW}!${NC} Frontend port $FRONTEND_PORT_START in use → using $FRONTEND_PORT"
fi

# If LiteLLM moved and LLM_API_URL points at a local LiteLLM, retarget it.
if [ "$START_LITELLM" = "true" ] && [[ "$LLM_API_URL" =~ ^https?://(localhost|127\.0\.0\.1): ]]; then
    LLM_API_URL="http://localhost:$LITELLM_PORT"
    export LLM_API_URL
fi

# Persist chosen ports for stop.sh and tell the React app where the backend is.
{
    echo "LITELLM_PORT=${LITELLM_PORT:-}"
    echo "BACKEND_PORT=$BACKEND_PORT"
    echo "FRONTEND_PORT=$FRONTEND_PORT"
} > "$PORTS_FILE"

cat > "$SCRIPT_DIR/frontend/.env.local" <<EOF
# Auto-generated by start.sh — overwritten on each run
VITE_API_BASE=http://localhost:$BACKEND_PORT
EOF

# Clear PID file
rm -f "$PID_FILE"

# =============================================================================
# Start LiteLLM
# =============================================================================

if [ "$START_LITELLM" = "true" ]; then
    if command -v litellm &> /dev/null; then
        echo -e "${BLUE}Starting LiteLLM proxy...${NC}"
        litellm --config litellm_config.yaml --port $LITELLM_PORT > /tmp/litellm.log 2>&1 &
        LITELLM_PID=$!
        echo "$LITELLM_PID LiteLLM" >> "$PID_FILE"

        # Wait for LiteLLM to be ready
        # Extract master key from litellm config for authenticated health checks
        LITELLM_MASTER_KEY=$(grep 'master_key:' litellm_config.yaml | awk '{print $2}' | tr -d '"' | tr -d "'")
        LITELLM_AUTH_HEADER=""
        if [ -n "$LITELLM_MASTER_KEY" ]; then
            LITELLM_AUTH_HEADER="-H \"Authorization: Bearer $LITELLM_MASTER_KEY\""
        fi

        echo -n "  Waiting for LiteLLM to start"
        for i in {1..30}; do
            if curl -sf -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://localhost:$LITELLM_PORT/health >/dev/null 2>&1; then
                echo ""
                echo -e "  ${GREEN}✓${NC} LiteLLM running on http://localhost:$LITELLM_PORT"
                break
            fi
            echo -n "."
            sleep 1
        done

        if ! curl -sf -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://localhost:$LITELLM_PORT/health >/dev/null 2>&1; then
            echo ""
            echo -e "  ${RED}✗${NC} LiteLLM failed to start. Check /tmp/litellm.log"
            echo ""
            echo "Recent logs:"
            tail -20 /tmp/litellm.log 2>/dev/null || true
            exit 1
        fi
    else
        echo -e "${YELLOW}Warning: LiteLLM not installed${NC}"
        echo "  Install with: pip install 'litellm[proxy]'"
        echo "  Continuing without LiteLLM..."
        echo ""
    fi
fi

# =============================================================================
# Start Backend
# =============================================================================

echo -e "${BLUE}Starting backend...${NC}"

# Try uvicorn directly first, fall back to uv run
if command -v uvicorn &> /dev/null; then
    python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT > /tmp/backend.log 2>&1 &
elif command -v uv &> /dev/null; then
    uv run python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT > /tmp/backend.log 2>&1 &
else
    python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT > /tmp/backend.log 2>&1 &
fi
BACKEND_PID=$!
echo "$BACKEND_PID Backend" >> "$PID_FILE"

# Wait for backend to be ready
echo -n "  Waiting for backend to start"
for i in {1..30}; do
    if curl -s http://localhost:$BACKEND_PORT/ >/dev/null 2>&1; then
        echo ""
        echo -e "  ${GREEN}✓${NC} Backend running on http://localhost:$BACKEND_PORT"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -s http://localhost:$BACKEND_PORT/ >/dev/null 2>&1; then
    echo ""
    echo -e "  ${RED}✗${NC} Backend failed to start. Check /tmp/backend.log"
    echo ""
    echo "Recent logs:"
    tail -20 /tmp/backend.log 2>/dev/null || true
    cleanup
    exit 1
fi

# =============================================================================
# Start Frontend
# =============================================================================

echo -e "${BLUE}Starting frontend...${NC}"
cd frontend
npm run dev -- --port "$FRONTEND_PORT" --strictPort > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID Frontend" >> "$PID_FILE"
cd "$SCRIPT_DIR"

# Wait for frontend to be ready
echo -n "  Waiting for frontend to start"
for i in {1..30}; do
    if curl -s http://localhost:$FRONTEND_PORT/ >/dev/null 2>&1; then
        echo ""
        echo -e "  ${GREEN}✓${NC} Frontend running on http://localhost:$FRONTEND_PORT"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -s http://localhost:$FRONTEND_PORT/ >/dev/null 2>&1; then
    echo ""
    echo -e "  ${RED}✗${NC} Frontend failed to start. Check /tmp/frontend.log"
    echo ""
    echo "Recent logs:"
    tail -20 /tmp/frontend.log 2>/dev/null || true
    cleanup
    exit 1
fi

# =============================================================================
# Success!
# =============================================================================

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      AI Ministry is running!          ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo "  Services:"
[ "$START_LITELLM" = "true" ] && [ -n "$LITELLM_PID" ] && echo "    LiteLLM:  http://localhost:$LITELLM_PORT"
echo "    Backend:  http://localhost:$BACKEND_PORT"
echo "    Frontend: http://localhost:$FRONTEND_PORT"
echo ""
echo "  Logs:"
[ "$START_LITELLM" = "true" ] && echo "    LiteLLM:  /tmp/litellm.log"
echo "    Backend:  /tmp/backend.log"
echo "    Frontend: /tmp/frontend.log"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

# Wait for any process to exit
wait

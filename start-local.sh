#!/bin/bash

# Cassie Genomics Platform Local Development Startup Script
# This script starts services locally without Docker (requires local Postgres)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

BACKEND_DIR="./backend"
FRONTEND_DIR="./web_app/frontend"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Cassie Local Development Startup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3 found${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js found${NC}"

# Check Postgres
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: PostgreSQL client (psql) is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL client found${NC}"

# Check if Postgres is running
if ! pg_isready -h localhost -p 5432 -U postgres > /dev/null 2>&1; then
    echo -e "${YELLOW}Warning: Postgres may not be running on localhost:5432${NC}"
    echo -e "${YELLOW}Please ensure Postgres is running and accessible${NC}"
fi

# Set environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@localhost:5432/cassie}"
export JWT_SECRET="${JWT_SECRET:-change-me-in-production-local}"
export JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-60}"
export FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:3000}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:3001}"

echo ""
echo -e "${BLUE}Environment:${NC}"
echo -e "  DATABASE_URL: ${DATABASE_URL}"
echo -e "  NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL}"
echo ""

# Setup backend
echo -e "${YELLOW}Setting up backend...${NC}"
cd "$BACKEND_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
if [ ! -f "venv/.installed" ]; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install --upgrade pip
    pip install -r requirements.txt
    touch venv/.installed
else
    echo -e "${GREEN}✓ Python dependencies already installed${NC}"
fi

# Start backend in background
echo -e "${YELLOW}Starting FastAPI backend on port 3001...${NC}"
cd "$(dirname "$BACKEND_DIR")"
export PYTHONPATH="$(pwd)"
uvicorn backend.api.main:app --host 0.0.0.0 --port 3001 --reload &
BACKEND_PID=$!
cd - > /dev/null

# Wait for backend to be ready
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
timeout=30
counter=0
until curl -s http://localhost:3001/api/health > /dev/null 2>&1; do
    sleep 1
    counter=$((counter + 1))
    if [ $counter -ge $timeout ]; then
        echo -e "${RED}Error: Backend failed to start${NC}"
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
done
echo -e "${GREEN}✓ Backend is ready${NC}"

# Setup frontend
echo ""
echo -e "${YELLOW}Setting up frontend...${NC}"
cd "$FRONTEND_DIR"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing Node.js dependencies...${NC}"
    npm install
else
    echo -e "${GREEN}✓ Node.js dependencies already installed${NC}"
fi

# Start frontend
echo -e "${YELLOW}Starting Next.js frontend on port 3000...${NC}"
cd ../..

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down services...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup INT TERM

# Start frontend
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
cd ../..

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Services are running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo -e "  • Backend API: ${GREEN}http://localhost:3001${NC}"
echo -e "  • Frontend:    ${GREEN}http://localhost:3000${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for processes
wait


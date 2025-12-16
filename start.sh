#!/bin/bash

# Cassie Genomics Platform Startup Script
# This script starts the entire system (Postgres, Backend, Frontend)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.yml"
BACKEND_DIR="./backend"
FRONTEND_DIR="./web_app/frontend"

# CLI options: --rebuild (build images on start), --force (force recreate containers),
# --watch (monitor src and redeploy on changes), --no-monitor (disable automatic monitoring)
REBUILD=0
FORCE_RECREATE=0
WATCH=0
MONITOR=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --rebuild)
      REBUILD=1
      shift
      ;;
    --force)
      FORCE_RECREATE=1
      shift
      ;;
    --watch)
      WATCH=1
      shift
      ;;
    --no-monitor)
      MONITOR=0
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--rebuild] [--force] [--watch] [--no-monitor]"
      echo "  --rebuild    Build images when starting services"
      echo "  --force      Force recreate containers"
      echo "  --watch      Watch backend/frontend files and redeploy on changes (requires inotifywait)"
      echo "  --no-monitor Disable automatic container monitoring/restart"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Cassie Genomics Platform Startup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if Docker is installed and running
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed or not in PATH${NC}"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker daemon is not running${NC}"
    exit 1
fi

# Check if docker-compose is available
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo -e "${RED}Error: docker-compose is not installed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker is available${NC}"

# Check if .env file exists, create one if not
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env file with default values...${NC}"
    cat > .env << EOF
# Database Configuration
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/cassie

# JWT Configuration
JWT_SECRET=change-me-in-production-$(openssl rand -hex 16)
JWT_EXPIRES_MINUTES=60

# Frontend Configuration
NEXT_PUBLIC_API_URL=http://localhost:3001
FRONTEND_ORIGIN=http://localhost:3000
EOF
    echo -e "${GREEN}✓ Created .env file${NC}"
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# Stop any existing containers
echo ""
echo -e "${YELLOW}Stopping any existing containers...${NC}"
$COMPOSE_CMD -f $COMPOSE_FILE down 2>/dev/null || true

# Build and start services
echo ""
echo -e "${BLUE}Building and starting services...${NC}"
echo ""

# Start Postgres first
echo -e "${YELLOW}Starting Postgres database...${NC}"
$COMPOSE_CMD -f $COMPOSE_FILE up -d postgres

# Wait for Postgres to be ready
echo -e "${YELLOW}Waiting for Postgres to be ready...${NC}"
timeout=30
counter=0
until docker exec cassie_postgres pg_isready -U postgres > /dev/null 2>&1; do
    sleep 1
    counter=$((counter + 1))
    if [ $counter -ge $timeout ]; then
        echo -e "${RED}Error: Postgres failed to start within ${timeout} seconds${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ Postgres is ready${NC}"

# Start backend
echo -e "${YELLOW}Starting FastAPI backend...${NC}"
$COMPOSE_CMD -f $COMPOSE_FILE up -d backend

# Wait for backend to be ready
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
timeout=30
counter=0
until curl -s http://localhost:3001/api/health > /dev/null 2>&1; do
    sleep 1
    counter=$((counter + 1))
    if [ $counter -ge $timeout ]; then
        echo -e "${YELLOW}Warning: Backend health check timeout (may still be starting)${NC}"
        break
    fi
done
echo -e "${GREEN}✓ Backend is ready${NC}"

# Start frontend
echo -e "${YELLOW}Starting Next.js frontend...${NC}"
$COMPOSE_CMD -f $COMPOSE_FILE up -d frontend

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  All services are starting!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo -e "  • Postgres:    ${GREEN}http://localhost:5432${NC}"
echo -e "  • Backend API: ${GREEN}http://localhost:3001${NC}"
echo -e "  • Frontend:    ${GREEN}http://localhost:3000${NC}"
echo ""
echo -e "${BLUE}API Endpoints:${NC}"
echo -e "  • Health:      ${GREEN}http://localhost:3001/api/health${NC}"
echo -e "  • Auth:        ${GREEN}http://localhost:3001/api/auth/register${NC}"
echo -e "  • Jobs:        ${GREEN}http://localhost:3001/api/jobs${NC}"
echo -e "  • Pipelines:   ${GREEN}http://localhost:3001/api/pipelines${NC}"
echo -e "  • Community:   ${GREEN}http://localhost:3001/api/community/workflows${NC}"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo -e "  docker-compose logs -f"
echo ""
echo -e "${YELLOW}To stop all services:${NC}"
echo -e "  docker-compose down"
echo ""
echo -e "${GREEN}Frontend will be available at http://localhost:3000${NC}"
echo ""

# Helper: redeploy a service, optionally building and forcing recreate
redeploy_service() {
  svc="$1"
  echo -e "${YELLOW}Redeploying $svc...${NC}"
  if [ "$REBUILD" -eq 1 ]; then
    $COMPOSE_CMD -f $COMPOSE_FILE up -d --build "$svc"
  else
    $COMPOSE_CMD -f $COMPOSE_FILE up -d "$svc"
  fi
  if [ "$FORCE_RECREATE" -eq 1 ]; then
    # force recreate to ensure fresh containers
    $COMPOSE_CMD -f $COMPOSE_FILE up -d --force-recreate "$svc"
  fi
}

# Watch for file changes and redeploy when detected (requires inotifywait)
if [ "$WATCH" -eq 1 ]; then
  if ! command -v inotifywait &> /dev/null; then
    echo -e "${YELLOW}inotifywait not found; install inotify-tools to use --watch${NC}"
  else
    echo -e "${GREEN}Watching $BACKEND_DIR and $FRONTEND_DIR for changes...${NC}"
    (while inotifywait -e modify,create,delete -r "$BACKEND_DIR" "$FRONTEND_DIR"; do
      echo -e "${YELLOW}Change detected. Redeploying backend and frontend...${NC}"
      redeploy_service backend
      redeploy_service frontend
      sleep 1
    done) &
  fi
fi

# Monitor containers and attempt redeploy if they stop (runs in background unless disabled)
if [ "$MONITOR" -eq 1 ]; then
  monitor_services() {
    while true; do
      for svc in backend frontend; do
        # container names are defined in docker-compose with container_name
        cn="cassie_${svc}"
        if ! docker inspect "$cn" > /dev/null 2>&1; then
          echo -e "${YELLOW}$cn not present; redeploying ${svc}...${NC}"
          redeploy_service "$svc"
        else
          running=$(docker inspect -f '{{.State.Running}}' "$cn" 2>/dev/null || echo "false")
          if [ "$running" != "true" ]; then
            echo -e "${YELLOW}$cn not running; redeploying ${svc}...${NC}"
            redeploy_service "$svc"
          fi
        fi
      done
      sleep 10
    done
  }
  monitor_services &
fi

# Show logs
echo -e "${YELLOW}Showing logs (Ctrl+C to exit)...${NC}"
$COMPOSE_CMD -f $COMPOSE_FILE logs -f


# Cassie Platform Startup Guide

This guide explains how to start the entire Cassie Genomics Platform system.

## Quick Start (Docker - Recommended)

The easiest way to start everything is using Docker Compose:

```bash
./start.sh
```

This will:
1. Start a Postgres database container
2. Start the FastAPI backend container
3. Start the Next.js frontend container
4. Show logs from all services

**Access Points:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001
- Postgres: localhost:5432

## Manual Docker Compose

If you prefer to use docker-compose directly:

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

## Local Development (Without Docker)

If you want to run services locally without Docker:

**Prerequisites:**
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ running locally
- psql client installed

**Steps:**

1. **Start PostgreSQL** (if not already running):
   ```bash
   # Create database
   createdb cassie
   # Or using psql:
   psql -U postgres -c "CREATE DATABASE cassie;"
   ```

2. **Run the startup script:**
   ```bash
   ./start-local.sh
   ```

   Or manually:

   **Backend:**
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/cassie"
   export JWT_SECRET="your-secret-key"
   uvicorn api.main:app --host 0.0.0.0 --port 3001 --reload
   ```

   **Frontend (in another terminal):**
   ```bash
   cd web_app/frontend
   npm install
   export NEXT_PUBLIC_API_URL="http://localhost:3001"
   npm run dev
   ```

## Environment Variables

Create a `.env` file in the root directory to customize settings:

```env
# Database
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/cassie

# JWT
JWT_SECRET=your-secret-key-change-in-production
JWT_EXPIRES_MINUTES=60

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:3001
FRONTEND_ORIGIN=http://localhost:3000
```

## API Endpoints

Once running, the backend exposes:

- **Health Check**: `GET /api/health`
- **Auth**: 
  - `POST /api/auth/register`
  - `POST /api/auth/login`
- **Jobs**: 
  - `GET /api/jobs`
  - `POST /api/jobs`
  - `GET /api/jobs/{id}`
- **Pipelines**: 
  - `GET /api/pipelines`
  - `POST /api/pipelines`
  - `DELETE /api/pipelines/{id}`
- **Community**: 
  - `GET /api/community/workflows`
  - `POST /api/community/workflows/{id}/vote`

## Troubleshooting

### Port Already in Use

If ports 3000, 3001, or 5432 are already in use:

1. **Change ports in docker-compose.yml** or
2. **Stop conflicting services**:
   ```bash
   # Find process using port
   lsof -i :3001
   # Kill process
   kill -9 <PID>
   ```

### Database Connection Issues

- Ensure Postgres is running and accessible
- Check DATABASE_URL environment variable
- Verify database `cassie` exists
- Check Postgres logs: `docker-compose logs postgres`

### Backend Not Starting

- Check Python dependencies: `pip install -r backend/requirements.txt`
- Verify DATABASE_URL is correct
- Check backend logs: `docker-compose logs backend`

### Frontend Not Connecting to Backend

- Verify `NEXT_PUBLIC_API_URL` is set correctly
- Check CORS settings in backend
- Ensure backend is running and accessible at the URL

## Development Workflow

1. **Start services**: `./start.sh` or `./start-local.sh`
2. **Make changes** to code (hot reload enabled)
3. **Test** in browser at http://localhost:3000
4. **View logs**: `docker-compose logs -f` (Docker) or check terminal output (local)
5. **Stop services**: `docker-compose down` or Ctrl+C (local)

## Production Deployment

For production, you should:

1. Set strong `JWT_SECRET` in environment
2. Use proper database credentials
3. Configure HTTPS
4. Set up proper CORS origins
5. Use production builds:
   - Frontend: `npm run build` then `npm start`
   - Backend: Use gunicorn or similar WSGI server


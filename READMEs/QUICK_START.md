# Quick Start Guide

## 🚀 Start Everything (Docker - Recommended)

```bash
./start.sh
```

This single command will:
- ✅ Start Postgres database
- ✅ Start FastAPI backend (port 3001)
- ✅ Start Next.js frontend (port 3000)
- ✅ Show logs from all services

**Access:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001/api/health

## 📋 What Was Connected

### Frontend Pages → Backend APIs

1. **Login/Register** (`/login`, `/register`)
   - ✅ Already connected to `/api/auth/login` and `/api/auth/register`
   - Stores JWT token and user info

2. **Configure Page** (`/configure`)
   - ✅ Now creates jobs via `POST /api/jobs`
   - Falls back to localStorage if backend unavailable

3. **Jobs List** (`/jobs`)
   - ✅ Fetches jobs from `GET /api/jobs`
   - Shows user's jobs with filters (all/active/completed)

4. **Job Detail** (`/jobs/[id]`)
   - ✅ Fetches single job from `GET /api/jobs/{id}`
   - Displays all job details and results

5. **Pipeline Builder** (`/builder`)
   - ✅ Saves pipelines via `POST /api/pipelines`
   - Stores visual pipeline definitions (nodes/edges)

6. **Profile Page** (`/profile`)
   - ✅ Lists pipelines from `GET /api/pipelines`
   - ✅ Deletes pipelines via `DELETE /api/pipelines/{id}`

7. **Community** (`/community`)
   - ✅ Already connected to `/api/community/workflows`
   - ✅ Voting via `POST /api/community/workflows/{id}/vote`

### Database Tables

All tables are automatically created on first startup:

- `users` - User accounts with email/password
- `jobs` - Analysis jobs with status, files, results
- `pipelines` - Saved pipeline definitions
- `community_workflows` - Shared community workflows

## 🔧 Alternative: Local Development

If you prefer running without Docker:

```bash
./start-local.sh
```

**Requirements:**
- Python 3.11+
- Node.js 18+
- PostgreSQL running locally
- Database `cassie` created

## 🛠️ Manual Commands

### Docker Compose
```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Backend Only
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/cassie"
uvicorn backend.api.main:app --host 0.0.0.0 --port 3001 --reload
```

### Frontend Only
```bash
cd web_app/frontend
npm install
export NEXT_PUBLIC_API_URL="http://localhost:3001"
npm run dev
```

## 📝 Environment Variables

Create `.env` file (optional):
```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/cassie
JWT_SECRET=your-secret-key
NEXT_PUBLIC_API_URL=http://localhost:3001
```

## ✅ Testing the Connection

1. Start services: `./start.sh`
2. Open http://localhost:3000
3. Register a new account
4. Create a job in Configure page
5. View jobs in Jobs page
6. Create a pipeline in Builder
7. View pipelines in Profile

All data is now stored in Postgres! 🎉


# CASSIE Build & Installation Guide

This guide will help you set up the CASSIE project from scratch.

---

## 📋 Prerequisites

Install the following software:

1. **Python 3.9+** - [Download Python](https://www.python.org/downloads/)
2. **Node.js 18+ and npm** - [Download Node.js](https://nodejs.org/)
3. **PostgreSQL 14+** - [Download PostgreSQL](https://www.postgresql.org/download/)
4. **Docker Desktop** - [Download Docker](https://www.docker.com/products/docker-desktop/)
5. **Git** - [Download Git](https://git-scm.com/downloads)

---

## 🚀 Installation Steps

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd CASSIE
```

---

### Step 2: Backend Setup

#### 2.1 Create Virtual Environment

**Windows:**
```bash
cd backend
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
```

#### 2.2 Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Note:** On Windows, you may need Microsoft Visual C++ Build Tools. On Linux, install: `sudo apt-get install python3-dev libpq-dev`

---

### Step 3: Frontend Setup

```bash
cd frontend
npm install
```

---

### Step 4: Configuration (Optional)

The backend uses default configuration, but you can override with environment variables. Create a `.env` file in the `backend` directory if needed:

```env
# Database (defaults shown)
DB_HOST=127.0.0.1
DB_PORT=5433
DB_USER=admin
DB_PASSWORD=admin
DB_NAME=cassie_db

# MinIO (defaults shown)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

**Note:** The backend automatically creates the database and initializes the schema on startup if they don't exist.

---

## 🏃 Running the Application

Follow these steps in order:

### 1. Start Docker Engine

Ensure Docker Desktop is running.

**Verify:**
```bash
docker ps
```

---

### 2. Build Tools (First Time Only)

If tool images haven't been built yet:

```bash
cd dockerized_tools
bash buildtools.sh
```

**Windows (Git Bash or WSL):**
```bash
cd dockerized_tools
bash buildtools.sh
```

This builds:
- FastQC
- GenomeScope2
- SPAdes
- QUAST

**Note:** The script skips images that already exist, so it's safe to run multiple times.

---

### 3. Start Backend

**Windows:**
```bash
cd backend
venv\Scripts\activate
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

**Linux/Mac:**
```bash
cd backend
source venv/bin/activate
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

**What happens automatically:**
- ✅ Checks if database exists, creates it if not
- ✅ Initializes database schema
- ✅ Checks database health
- ✅ Creates Docker containers if needed
- ✅ Logs any failures

You should see:
```
INFO:     Starting CASSIE backend API...
INFO:     Initializing database...
INFO:     Database initialized successfully
INFO:     Database health check passed
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

### 4. Start Frontend

Open a new terminal:

```bash
cd frontend
npm run dev
```

You should see:
```
  VITE v5.x.x  ready in xxx ms
  ➜  Local:   http://localhost:3000/
```

---

## 🌐 Access Points

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API Documentation:** http://localhost:8000/docs
- **MinIO Console:** http://localhost:9001 (if using MinIO)

---

## 🧪 Verify Installation

1. **Backend:** Open http://localhost:8000/docs - you should see the API documentation
2. **Frontend:** Open http://localhost:3000 - you should see the CASSIE landing page
3. **Register a user:** Create an account through the frontend
4. **Login:** Use your credentials to login

---

## 🐛 Troubleshooting

### Database Connection Error

**Error:** `psycopg2.OperationalError: could not connect to server`

**Solutions:**
- Ensure PostgreSQL is running: `sudo systemctl status postgresql` (Linux)
- Check PostgreSQL port (default: 5432, but CASSIE uses 5433 by default)
- Verify connection details in `.env` file (if using custom config)
- Check if PostgreSQL container is running (if using Docker)

### Port Already in Use

**Error:** `Address already in use`

**Solutions:**
- Find process: `netstat -ano | findstr :8000` (Windows) or `lsof -i :8000` (Linux/Mac)
- Kill process or use different port: `uvicorn backend.api.main:app --port 8001`

### Docker Issues

**Error:** `Cannot connect to Docker daemon`

**Solutions:**
- Start Docker Desktop
- Verify: `docker ps`
- On Linux: `sudo systemctl start docker`

### npm Install Fails

**Solutions:**
- Clear cache: `npm cache clean --force`
- Delete `node_modules` and `package-lock.json`, then `npm install`
- Update npm: `npm install -g npm@latest`
- Use: `npm install --legacy-peer-deps` if peer dependency issues

### Module Not Found (Python)

**Error:** `ModuleNotFoundError: No module named 'backend'`

**Solutions:**
- Activate virtual environment: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Linux/Mac)
- Install requirements: `pip install -r requirements.txt`
- Ensure you're in the `backend` directory when running commands

---

## 📚 Project Structure

```
CASSIE/
├── backend/              # Python FastAPI backend
│   ├── api/             # API code
│   ├── scripts/         # Setup scripts
│   └── requirements.txt # Python dependencies
├── frontend/            # React TypeScript frontend
│   ├── src/            # Source code
│   └── package.json    # Node dependencies
├── dockerized_tools/    # Tool build scripts
│   └── buildtools.sh   # Build all tool containers
└── containers/          # Docker containers for tools
```

---

## ✅ Quick Checklist

- [ ] Python 3.9+ installed
- [ ] Node.js 18+ installed
- [ ] PostgreSQL installed and running
- [ ] Docker Desktop installed and running
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] Backend dependencies installed
- [ ] Frontend dependencies installed
- [ ] Tools built (first time): `bash dockerized_tools/buildtools.sh`
- [ ] Backend starts successfully
- [ ] Frontend starts successfully
- [ ] Can access frontend in browser
- [ ] Can access API docs
- [ ] Can register a user

---

## 🔄 Daily Workflow

Once everything is set up, your daily workflow is:

1. **Start Docker Desktop**
2. **Start Backend:**
   ```bash
   cd backend
   venv\Scripts\activate  # Windows
   # source venv/bin/activate  # Linux/Mac
   uvicorn backend.api.main:app --reload
   ```
3. **Start Frontend:**
   ```bash
   cd frontend
   npm run dev
   ```

That's it! The backend handles database initialization, container creation, and health checks automatically.

---

**Last Updated:** December 2024

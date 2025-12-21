# CASSIE Frontend

React + TypeScript frontend for CASSIE platform.

## Setup

1. **Install dependencies:**
   ```bash
   cd frontend
   npm install
   ```

2. **Start development server:**
   ```bash
   npm run dev
   ```

The frontend will be available at http://localhost:3000

## Features

- ✅ User authentication (Login/Register)
- ✅ Dashboard with job list
- ✅ Create new jobs
- ✅ Upload files
- ✅ View job details
- ✅ Real-time job status updates
- ✅ Download files

## API Connection

The frontend connects to the backend API at `http://localhost:8000` by default.

To change the API URL, set the `VITE_API_URL` environment variable or modify `vite.config.ts`.

## Pages

- `/login` - User login
- `/register` - User registration
- `/dashboard` - Job list and management
- `/jobs/create` - Create new job
- `/jobs/:jobId` - Job details and file management


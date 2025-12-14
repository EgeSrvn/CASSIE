#!/bin/bash

echo "Starting Cassie Frontend (standalone mode)..."
echo ""
echo "Note: Backend server is not required for UI development."
echo "Some features will be limited without the backend."
echo ""
echo "Frontend will be available at: http://localhost:3000"
echo ""

cd frontend
npm run dev


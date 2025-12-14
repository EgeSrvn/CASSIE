#!/bin/bash

echo "Setting up Cassie Genomics Platform..."

# Install root dependencies
echo "Installing root dependencies..."
npm install

# Install frontend dependencies
echo "Installing frontend dependencies..."
cd frontend
npm install
cd ..

# Install backend dependencies
echo "Installing backend dependencies..."
cd backend
npm install
cd ..

# Create .env file if it doesn't exist
if [ ! -f backend/.env ]; then
    echo "Creating backend/.env from .env.example..."
    cp backend/.env.example backend/.env
    echo "Please edit backend/.env with your configuration"
fi

echo "Setup complete!"
echo ""
echo "To start the development servers:"
echo "  npm run dev"
echo ""
echo "Or use Docker:"
echo "  docker-compose up"


#!/bin/bash

echo "========================================"
echo "     V47.14 Trading Bot - Starting"
echo "========================================"
echo

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if setup was completed
if [ ! -d "backend/venv" ]; then
    echo -e "${RED}❌ Setup not completed! Please run ./SETUP_LINUX.sh first${NC}"
    exit 1
fi

# Check if configuration files exist
if [ ! -f "backend/access_token.json" ]; then
    echo -e "${RED}❌ access_token.json not found! Please configure your Kite credentials${NC}"
    exit 1
fi

echo -e "${GREEN}🚀 Starting V47.14 Trading Bot...${NC}"
echo
echo -e "${BLUE}Frontend will be available at: http://localhost:3000${NC}"
echo -e "${BLUE}Backend API will be available at: http://localhost:8000${NC}"
echo
echo -e "${YELLOW}To stop the bot, press Ctrl+C${NC}"
echo

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}🛑 Stopping bot...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}✅ Bot stopped${NC}"
    exit 0
}

# Set up trap for cleanup
trap cleanup SIGINT SIGTERM

# Start backend in background
echo -e "${BLUE}🔧 Starting backend server...${NC}"
cd backend
source venv/bin/activate
python main.py &
BACKEND_PID=$!
cd ..

# Wait a moment for backend to start
sleep 3

# Start frontend in background
echo -e "${BLUE}🎨 Starting frontend...${NC}"
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Wait for processes
wait $FRONTEND_PID
cleanup
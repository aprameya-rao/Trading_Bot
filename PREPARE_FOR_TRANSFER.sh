#!/bin/bash

echo "========================================"
echo "   V47.14 Trading Bot - Prepare for Transfer"
echo "========================================"
echo

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🧹 Cleaning up temporary files...${NC}"

# Remove virtual environment
if [ -d "backend/venv" ]; then
    echo "Removing Python virtual environment..."
    rm -rf backend/venv
    echo -e "${GREEN}✅ Virtual environment removed${NC}"
fi

# Remove node_modules
if [ -d "frontend/node_modules" ]; then
    echo "Removing Node.js modules..."
    rm -rf frontend/node_modules
    echo -e "${GREEN}✅ Node modules removed${NC}"
fi

# Remove Python cache
find backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
find backend -name "*.pyc" -delete 2>/dev/null

# Remove database files (optional - comment out if you want to keep data)
if [ -f "backend/trading_data_today.db" ]; then
    echo "Removing today's database..."
    rm backend/trading_data_today.db
fi

if [ -f "backend/trading_data_all.db" ]; then
    echo "Removing historical database..."
    rm backend/trading_data_all.db
fi

# Remove sensitive files (keep templates)
if [ -f "backend/access_token.json" ]; then
    echo "Removing access token file..."
    rm backend/access_token.json
    echo -e "${YELLOW}⚠️ Remember to reconfigure access_token.json on new system${NC}"
fi

# Remove log files
rm -f backend/trading_log.txt
rm -f backend/last_run_date.txt

echo
echo -e "${GREEN}✅ CLEANUP COMPLETE${NC}"
echo
echo -e "${BLUE}📦 Your bot folder is now ready for transfer!${NC}"
echo
echo "NEXT STEPS:"
echo "1. Copy/compress this entire folder"
echo "2. Transfer to new system"
echo "3. Run ./SETUP_LINUX.sh on new system"
echo "4. Configure access_token.json"  
echo "5. Run ./START_BOT_LINUX.sh"
echo
echo "The folder size should now be much smaller."
echo
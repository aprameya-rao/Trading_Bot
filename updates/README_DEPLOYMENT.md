# 🚀 V47.14 Trading Bot - Easy Deployment Guide

## 📋 Quick Setup (Any System)

### 🖥️ Windows Users
1. **Double-click** `SETUP_WINDOWS.bat` → Installs everything automatically
2. **Edit** `backend\access_token.json` → Add your Kite credentials  
3. **Double-click** `START_BOT.bat` → Launches the bot
4. **Open** http://localhost:3000 → Access web interface

### 🐧 Linux/Mac Users  
1. **Run** `./SETUP_LINUX.sh` → Installs everything automatically
2. **Edit** `backend/access_token.json` → Add your Kite credentials
3. **Run** `./START_BOT_LINUX.sh` → Launches the bot
4. **Open** http://localhost:3000 → Access web interface

---

## 📦 What You Need (Pre-installed)

### Essential Software
- **Python 3.8+** → [Download here](https://python.org/downloads)
- **Node.js 16+** → [Download here](https://nodejs.org)
- **Git** (optional) → For version control

### Kite Connect Account
- **Zerodha Account** → Active trading account
- **Kite Connect App** → Create at [kite.trade](https://kite.trade)
- **Access Token** → Generate from your app

---

## 🛠️ Detailed Setup Steps

### Step 1: Download Bot
```bash
# Option 1: Download ZIP and extract
# Option 2: Clone with Git
git clone <repository-url>
cd trading_bot
```

### Step 2: Run Setup Script

**Windows:**
```cmd
SETUP_WINDOWS.bat
```

**Linux/Mac:**
```bash
chmod +x SETUP_LINUX.sh
./SETUP_LINUX.sh
```

**What the setup does:**
- ✅ Checks Python & Node.js installation
- ✅ Creates Python virtual environment
- ✅ Installs all Python dependencies
- ✅ Installs all Node.js dependencies  
- ✅ Creates configuration file templates
- ✅ Sets up folder structure

### Step 3: Configure Credentials

**Edit `backend/access_token.json`:**
```json
{
  "access_token": "your_actual_access_token_here",
  "user_id": "your_zerodha_client_id_here"
}
```

**How to get credentials:**
1. Log in to [kite.trade](https://kite.trade)
2. Go to "My Apps" → Create new app
3. Generate access token
4. Copy token and user ID to the file

### Step 4: Configure Trading Parameters (Optional)

**Edit `backend/strategy_params.json`:**
```json
{
  "trading_mode": "Paper Trading",  // Start with Paper Trading!
  "quantity": 25,
  "daily_sl": 0,
  "daily_pt": 5000
}
```

### Step 5: Start the Bot

**Windows:**
```cmd
START_BOT.bat
```

**Linux/Mac:**
```bash
./START_BOT_LINUX.sh
```

**What happens:**
- 🔧 Backend starts on port 8000
- 🎨 Frontend starts on port 3000
- 🌐 Web interface opens automatically
- 📊 Bot begins monitoring markets

---

## 🌐 Access the Bot

### Web Interface
- **URL:** http://localhost:3000
- **Features:** Live charts, trade logs, performance metrics
- **Mobile:** Works on mobile browsers too!

### API Endpoints  
- **Backend:** http://localhost:8000
- **Health:** http://localhost:8000/health
- **Docs:** http://localhost:8000/docs

---

## 🛑 Stop the Bot

**Windows:**
```cmd
STOP_BOT.bat
```

**Linux/Mac:**
```bash
./STOP_BOT_LINUX.sh
```

Or simply close the terminal/command prompt.

---

## 📁 File Structure

```
trading_bot/
├── 🔧 SETUP_WINDOWS.bat       # Windows setup script
├── 🔧 SETUP_LINUX.sh          # Linux/Mac setup script  
├── 🚀 START_BOT.bat           # Windows start script
├── 🚀 START_BOT_LINUX.sh      # Linux/Mac start script
├── 🛑 STOP_BOT.bat            # Windows stop script
├── 🛑 STOP_BOT_LINUX.sh       # Linux/Mac stop script
├── 📖 README_DEPLOYMENT.md    # This file
├── backend/                    # Python trading engine
│   ├── 📋 requirements.txt     # Python dependencies
│   ├── 🔑 access_token.json    # Your Kite credentials
│   ├── ⚙️ strategy_params.json # Trading parameters
│   ├── 🤖 main.py             # Backend server
│   └── core/                   # Trading logic
└── frontend/                   # Web interface
    ├── 📋 package.json         # Node.js dependencies  
    └── src/                    # React components
```

---

## ⚠️ Important Security Notes

### 🔒 Keep Private
- **Never share** `access_token.json`
- **Never commit** credentials to Git
- **Use .gitignore** to exclude sensitive files

### 🧪 Start with Paper Trading
- Set `"trading_mode": "Paper Trading"` initially
- Test thoroughly before going live
- Monitor performance for several days

### 🔄 Access Token Management
- Tokens expire periodically
- Regenerate when needed
- Keep backup of user_id

---

## 🚨 Troubleshooting

### Common Issues

**❌ "Python not found"**
```bash
# Install Python and add to PATH
# Windows: Check "Add Python to PATH" during installation
# Linux: sudo apt install python3 python3-pip
```

**❌ "Node.js not found"**  
```bash
# Install Node.js from nodejs.org
# Or use package manager: apt install nodejs npm
```

**❌ "Permission denied" (Linux/Mac)**
```bash
chmod +x *.sh
```

**❌ "Port already in use"**
```bash
# Kill existing processes
./STOP_BOT_LINUX.sh
# Or change ports in configuration
```

**❌ "Invalid access token"**
- Check token hasn't expired
- Verify user_id is correct
- Regenerate token if needed

### Getting Help

1. **Check logs** in the terminal output
2. **Review configuration** files
3. **Restart** the bot completely
4. **Use Paper Trading** for testing

---

## 🎯 Quick Reference

### Trading Modes
- **Paper Trading** → Simulated trades (safe for testing)
- **Live Trading** → Real money trades (use with caution)

### Key Files to Edit
- `backend/access_token.json` → Your credentials
- `backend/strategy_params.json` → Trading settings

### Important URLs
- **Web Interface** → http://localhost:3000
- **API Docs** → http://localhost:8000/docs
- **Health Check** → http://localhost:8000/health

### Quick Commands
```bash
# Setup (run once)
./SETUP_LINUX.sh

# Start trading
./START_BOT_LINUX.sh  

# Stop trading
./STOP_BOT_LINUX.sh
```

---

## 📈 Trading Bot Features

### V47.14 Complete System
- ✅ **4 Entry Engines** → Volatility, Supertrend, Trend, Counter-trend
- ✅ **Priority System** → Intelligent signal coordination
- ✅ **3-Layer Validation** → ATM + Candle + Momentum
- ✅ **Advanced Exit Logic** → Multiple profit targets
- ✅ **Risk Management** → Position sizing, daily limits
- ✅ **Order Chasing** → Better fill prices (200-400ms execution)
- ✅ **Real-time UI** → Live charts and performance metrics

### Performance
- **Entry Speed** → 200-400ms average
- **Paper Trading** → Risk-free testing
- **Live Trading** → Real money execution
- **Mobile Ready** → Works on any device

---

## 🎉 You're Ready!

Your V47.14 trading bot is now **portable** and **easy to deploy** on any system:

1. **Copy folder** to new system
2. **Run setup script** 
3. **Add credentials**
4. **Start trading**

**Happy Trading! 🚀📈**
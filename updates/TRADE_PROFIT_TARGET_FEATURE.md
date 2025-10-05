# 🎯 Trade Profit Target Feature Implementation

## Overview
Added **per-trade profit target** feature to V47.14 bot - each individual trade exits automatically when it reaches a specified profit amount.

## ✅ Implementation Complete

### 1. Frontend UI Enhancement
**File:** `frontend/src/components/ParametersPanel.jsx`
- Added "Trade PT (₹)" parameter field
- Positioned between Daily PT and Partial Profit settings

### 2. Default Configuration
**File:** `frontend/src/store/store.js`
- Added `trade_profit_target: 1000` (default ₹1,000)
- Parameter automatically saved/loaded with other settings

### 3. Backend Parameter Handling
**File:** `backend/core/strategy.py`
- Added `trade_profit_target` to parameter conversion list
- Ensures proper float conversion for calculations

### 4. Exit Logic Integration
**File:** `backend/core/strategy.py` - `evaluate_exit_logic()`
- **Layer 0**: Trade Profit Target (highest priority)
- **Layer 1**: Red Candle Exit (existing)
- **Layer 2+**: All other exit logic (trailing SL, etc.)

## 🚀 How It Works

### Logic Flow:
```python
# Check every tick for each active trade
trade_profit_target = self.params.get("trade_profit_target", 0)
if trade_profit_target > 0:
    current_profit = (ltp - p["entry_price"]) * p["qty"]
    if current_profit >= trade_profit_target:
        # Exit immediately with profit amount in reason
        await self.exit_position(f"Trade Profit Target (₹{current_profit:.0f})")
```

### Example Behavior:
```
Trade Entry: BUY 75 NIFTY CE @ ₹120 (Entry Price)
Current Price: ₹133.33
Current Profit: (133.33 - 120) × 75 = ₹999.75

Next Tick: ₹133.50
Current Profit: (133.50 - 120) × 75 = ₹1,012.50
💰 TRADE PROFIT TARGET HIT: Profit ₹1,012.50 >= Target ₹1,000
[Exit Logic] Trade Profit Target (₹1013)
```

## ⚙️ Configuration

### Via Frontend UI:
1. Open Parameters Panel
2. Set "Trade PT (₹)" field (e.g., 500 for ₹500 target)
3. Save parameters

### Via Direct Parameter:
```json
{
    "trade_profit_target": 500  // Exit when trade profit reaches ₹500
}
```

### Disable Feature:
```json
{
    "trade_profit_target": 0  // Disabled (default behavior)
}
```

## 🎯 Key Features

✅ **Per-Trade Basis**: Each trade evaluated individually  
✅ **Real-Time Monitoring**: Checked on every price tick  
✅ **Highest Priority**: Layer 0 - executed before all other exits  
✅ **Configurable Amount**: Set any profit target amount  
✅ **Automatic Exit**: No manual intervention needed  
✅ **Detailed Logging**: Shows exact profit amount achieved  
✅ **UI Integration**: Easy parameter adjustment via frontend  

## 🔄 Integration with Existing Features

- **Compatible with**: Daily profit target, partial exits, trailing SL
- **Priority Order**: Trade PT → Red Candle → Trailing SL → Other exits
- **Works in**: Both Paper Trading and Live Trading modes
- **Position Tracking**: Uses existing position management system

## 📊 Use Cases

### Conservative Trading:
```json
{"trade_profit_target": 500}   // Quick ₹500 profits
```

### Aggressive Trading:
```json
{"trade_profit_target": 2000}  // Hold for ₹2,000 profits
```

### Scalping Strategy:
```json
{"trade_profit_target": 300}   // Fast ₹300 exits
```

## 🧪 Testing Recommendations

1. **Paper Trading First**: Test with various profit targets
2. **Monitor Logs**: Watch for "TRADE PROFIT TARGET HIT" messages  
3. **Adjust Gradually**: Start conservative, increase based on results
4. **Market Condition**: Consider volatility when setting targets

---

**Status**: ✅ **READY FOR USE**  
**Version**: V47.14 + Trade Profit Target  
**Priority**: Layer 0 (Highest)  
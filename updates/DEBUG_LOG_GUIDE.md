# Debug Log Guide - What to Look For

## Overview
I've added comprehensive debug logging to all v47.14 features. Here's what you should see in the debug log when the bot is running.

---

## 🎯 Feature 1: Enhanced Crossover Tracker

### When Crossovers Are Detected
```
[Crossover Detect] 🎯 Detected 2 crossovers: ['BULLISH', 'BULLISH']
[Signal Created] 🎯 Tracking BULLISH_CE_093015 for 5 minutes
[Signal Created] 🎯 Tracking BULLISH_PE_093015 for 5 minutes
```
**What it means:** Supertrend flipped from bearish to bullish, creating signals for both CE (primary) and PE (alternative)

### When Monitoring Active Signals
```
[Tracker Monitor] 🔍 Monitoring 2 active crossover signals
[Tracker Valid] ✅ BULLISH_CE_093015 momentum check PASSED (primary)
```
**What it means:** Bot is continuously checking if tracked signals have momentum

### When Signals Expire
```
[Tracker Expire] ⏰ Signal BULLISH_CE_093015 expired
```
**What it means:** 5 minutes passed without entry conditions being met

### When ATM Filter Blocks Entry
```
[ATM Filter] Tracker trade for CE blocked by ATM confirmation.
```
**What it means:** Signal had momentum but ATM strike wasn't confirming

---

## 📈 Feature 2: Persistent Trend Tracker

### When Trend Extension Detected
```
[Trend Extension] 📊 Price extending beyond recent candles in BULLISH trend
[Trend Tracker] 📈 Created TREND_CONT_CE_093530
```
**What it means:** Index price broke above recent highs, creating continuation signal

### When Monitoring Trend Signals
```
[Trend Monitor] 📈 Monitoring 1 trend continuation signals
[Trend Momentum] ✅ TREND_CONT_CE_093530 has momentum, validating entry...
[Trend Execute] 🚀 Executing trend continuation trade for TREND_CONT_CE_093530
```
**What it means:** Trend signal has option momentum and passed validation

### When Trend Signal Blocked
```
[Trend Block] ❌ TREND_CONT_CE_093530 failed validation
```
**What it means:** Momentum present but entry conditions (candle color, breakout) not met

### When Trend Signals Expire
```
[Trend Expire] ⏰ Trend signal TREND_CONT_CE_093530 expired
```
**What it means:** 3 minutes passed without favorable entry

---

## 🔴 Feature 3: Red Candle Exit

### When Red Candle Detected
```
[Exit Logic] 🔴 RED CANDLE DETECTED: NIFTY2410124850CE LTP 125.50 < Open 128.00
```
**What it means:** Option candle turned red (LTP fell below candle open), triggering instant exit

**Note:** This should be followed immediately by exit confirmation:
```
[Order Chasing] 🎯 Attempting to SELL 75 of NIFTY2410124850CE with order chasing.
[Database] Trade for NIFTY2410124850CE logged successfully.
```

---

## 💰 Feature 4: Multiple Partial Exits

### When Partial Profit Triggered
```
[Profit.Take] Partial exit #1 complete. Remaining quantity: 50. Next level at 1.0%
[Profit.Take] Partial exit #2 complete. Remaining quantity: 25. Next level at 1.5%
```
**What it means:** Bot is taking profits in multiple steps (3 levels by default)

### If Partial Exit Fails
```
[PARTIAL EXIT FAIL] ❌ Partial exit failed: API_ERROR: Connection timeout
```
**What it means:** Network issue prevented partial exit, position remains unchanged

---

## 🎯 Feature 5: Order Chasing Logic

### When Order Chasing Starts
```
[Order Chasing] 🎯 Attempting to BUY 75 of NIFTY2410124850CE with order chasing.
```

### During Limit Order Attempts
```
[Order Chasing] Attempt 1: Placed LIMIT order for 75 @ 125.50. ID: 240101000123456
[Order Chasing] ⏳ Slice not filled. Cancelling order 240101000123456.
[Order Chasing] Attempt 2: Placed LIMIT order for 75 @ 126.00. ID: 240101000123457
[Order Chasing] ✅ Slice of 75 FILLED with LIMIT order @ 126.00
```
**What it means:** Bot tried at 125.50, wasn't filled, updated to 126.00 and got filled

### When Falling Back to Market Order
```
[Order Chasing] ⚠️ Limit attempts failed. Placing MARKET order as fallback.
[Order Chasing] ✅ Market order filled 75 qty
```
**What it means:** After 3 limit attempts, used market order to ensure fill

### When Order Verified
```
[Order Chasing] ✅ Order VERIFIED. Filled 75 @ avg 126.25
```

---

## 🚫 What You WON'T See (Normal Behavior)

### No Crossovers
If no crossover log appears, it means Supertrend hasn't flipped. This is normal during:
- Sideways markets
- Strong trending periods without reversals
- First few minutes after bot starts (needs candle history)

### No Active Monitoring
If you don't see `Tracker Monitor` or `Trend Monitor` messages, it means:
- No signals were created (no crossovers/extensions detected)
- All signals expired
- Bot is in position (trackers pause during trades)

### No Red Candle Exits
If you don't see red candle exits, it's good! It means:
- Option price is rising (green candles)
- Exit happening via stop-loss or target instead

---

## 📊 Typical Log Flow (Full Trade Cycle)

### 1. Signal Creation Phase
```
[Crossover Detect] 🎯 Detected 1 crossovers: ['BULLISH']
[Signal Created] 🎯 Tracking BULLISH_CE_093015 for 5 minutes
```

### 2. Monitoring Phase (Every ~1 second)
```
[Tracker Monitor] 🔍 Monitoring 1 active crossover signals
```

### 3. Entry Validation Phase
```
[Tracker Valid] ✅ BULLISH_CE_093015 momentum check PASSED (primary)
[Validate] ✅ PASS: NIFTY2410124850CE Passed all checks. Momentum (2/3).
```

### 4. Order Execution Phase
```
[Order Chasing] 🎯 Attempting to BUY 75 of NIFTY2410124850CE with order chasing.
[Order Chasing] Attempt 1: Placed LIMIT order for 75 @ 125.50. ID: 123456
[Order Chasing] ✅ Slice of 75 FILLED with LIMIT order @ 125.50
[Order Chasing] ✅ Order VERIFIED. Filled 75 @ avg 125.50
```

### 5. In-Trade Phase
```
[Exit Logic] 🔴 RED CANDLE DETECTED: NIFTY2410124850CE LTP 128.00 < Open 130.00
```
OR
```
[Profit.Take] Partial exit #1 complete. Remaining quantity: 50. Next level at 1.0%
```

### 6. Exit Phase
```
[Order Chasing] 🎯 Attempting to SELL 75 of NIFTY2410124850CE with order chasing.
[Order Chasing] ✅ Order VERIFIED. Filled 75 @ avg 128.75
[Database] Trade for NIFTY2410124850CE logged successfully.
```

---

## 🔧 Troubleshooting

### "I don't see ANY of these messages"
**Problem:** Bot might not be running or log file location is wrong
**Solution:** 
1. Check if backend is running: `http://localhost:8000/docs`
2. Verify `trading_log.txt` exists in bot root folder
3. Check if bot is in "RUNNING" state (not paused)

### "I see Tracker Monitor but never see Tracker Valid"
**Problem:** Signals created but momentum requirements not met
**Possible reasons:**
- Market too choppy (option prices not showing clear momentum)
- ATM strikes not confirming trend
- Entry conditions too strict

**Try:** Lower momentum requirements in entry_strategies.py (line ~115: change 0.6 to 0.5)

### "I see Red Candle messages but no exit"
**Problem:** Log shows detection but exit not executing
**Solution:** Check for errors after the red candle message - there might be API issues

### "Order Chasing always falls back to market order"
**Problem:** Limit orders timing out
**Possible reasons:**
- chase_timeout_ms too short (200ms default)
- Volatile market moving faster than bot can react

**Try:** Increase timeout in order_manager call (line ~726 in strategy.py)

---

## 🎯 Expected Log Volume

### Low Volatility (Sideways Market)
- **Crossover Detect:** 1-2 per hour
- **Tracker Monitor:** Every few seconds when signals active
- **Trend Monitor:** Occasional during consolidations
- **Trades:** 1-3 per hour

### High Volatility (Trending Market)
- **Crossover Detect:** 3-5 per hour
- **Tracker Monitor:** Almost constant
- **Trend Monitor:** Frequent during strong trends
- **Red Candle Exits:** 1-2 per day
- **Trades:** 5-10 per hour

### Very Quiet Market (Pre-open, Lunch)
- Minimal logging except:
  - System status checks
  - Position monitoring if in trade
  - No crossover/trend signals

---

## 📝 Quick Reference: Emoji Guide

| Emoji | Meaning | Priority |
|-------|---------|----------|
| 🎯 | Signal created or order starting | Medium |
| 🔍 | Monitoring/checking activity | Low |
| ✅ | Success/validation passed | Medium |
| ❌ | Failure/blocked | High |
| 🔴 | Red candle exit triggered | HIGH |
| 📈 | Trend-related activity | Medium |
| 📊 | Market data/analysis | Low |
| ⚠️ | Warning (fallback actions) | Medium |
| ⏰ | Timeout/expiration | Low |
| 🚀 | Trade execution starting | High |
| 💰 | Profit-related | Medium |

---

## 🏁 Final Notes

1. **First 5 minutes:** Bot needs candle history, expect minimal logs
2. **Market hours:** 9:15 AM - 3:30 PM logs will be most active
3. **Log file size:** Can grow to 50-100 KB per day (normal)
4. **Performance:** New logging adds <1ms per log, negligible impact

If you still don't see relevant logs after reviewing this guide, share the actual log file content and I can diagnose further!

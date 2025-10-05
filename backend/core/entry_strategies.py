# backend/core/entry_strategies.py - V47.14 FULL IMPLEMENTATION
from abc import ABC, abstractmethod
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==============================================================================
# V47.14 FULL SYSTEM: ALL 4 ENTRY ENGINES + STRATEGY COORDINATOR
# Complete implementation matching original V47.14 specification
# ==============================================================================

class BaseEntryStrategy(ABC):
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        self.params = strategy_instance.params  
        self.data_manager = strategy_instance.data_manager

    @abstractmethod
    async def check(self):
        pass

# ==============================================================================
# V47.14 ENTRY ENGINE 1: VOLATILITY BREAKOUT (HIGHEST PRIORITY)
# ==============================================================================

class V47VolatilityBreakoutEngine(BaseEntryStrategy):
    """V47.14 Entry Logic 1: Volatility Breakout - captures explosive moves"""
    
    async def check(self):
        """Enhanced volatility breakout with frequency & quality improvements"""
        df = self.data_manager.data_df
        if len(df) < 10:  # Need sufficient history for quality analysis
            return None, None, None
            
        current_price = self.data_manager.prices.get(self.strategy.index_symbol)
        if not current_price:
            return None, None, None

        # === 1. OPTIONAL ATR SQUEEZE (BONUS POINTS) ===
        atr_squeeze_bonus = 0
        if await self.strategy._check_atr_squeeze():
            atr_squeeze_bonus = 2  # Bonus points for ATR squeeze setup
            
        # === 2. DYNAMIC RANGE: 3-8 CANDLES BASED ON MARKET CONDITIONS ===
        # Determine optimal range based on recent volatility
        if 'atr' in df.columns and len(df) >= 20:
            recent_atr = df['atr'].iloc[-5:].mean()
            historical_atr = df['atr'].iloc[-20:].mean()
            volatility_ratio = recent_atr / historical_atr if historical_atr > 0 else 1.0
            
            # Dynamic range selection
            if volatility_ratio > 1.3:  # High volatility - use shorter range
                range_periods = 3
            elif volatility_ratio > 1.1:  # Medium volatility 
                range_periods = 5
            else:  # Low volatility - use longer range
                range_periods = 8
        else:
            range_periods = 5  # Default fallback
            
        # Establish dynamic price range
        recent_candles = df.iloc[-range_periods:]
        range_high = recent_candles['high'].max()
        range_low = recent_candles['low'].min()
        range_size = range_high - range_low
        
        # === 5. ENHANCED BREAKOUT DETECTION WITH SIGNIFICANCE ===
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        
        # Calculate percentage breakout threshold (0.1-0.2% of price)
        price_threshold = current_price * 0.0015  # 0.15% of current price
        
        # Get ATR for significance check
        avg_atr = df['atr'].iloc[-10:].mean() if 'atr' in df.columns else range_size
        min_breakout_size = max(price_threshold, avg_atr * 0.3)  # Minimum significance
        
        potential_breakouts = []
        
        # Enhanced Bullish Breakout Detection
        if current_price > (range_high + min_breakout_size):
            bull_score = 0
            
            # Basic breakout confirmed
            bull_score += 1
            
            # === 5. VOLUME CONFIRMATION (IF AVAILABLE) ===
            if 'volume' in df.columns and len(df) >= 10:
                recent_volume = last_candle.get('volume', 0)
                avg_volume = df['volume'].iloc[-10:-1].mean()
                if recent_volume > avg_volume * 1.2:  # 20% volume surge
                    bull_score += 1
                    
            # === 5. MOMENTUM CONFIRMATION ===
            # Check for follow-through momentum
            if (last_candle['close'] > last_candle['open'] and  # Green candle
                last_candle['high'] > prev_candle['high']):     # Higher high
                bull_score += 1
                
            # === 6. CANDLE BODY STRENGTH (AVOID WICKS) ===
            body_size = abs(last_candle['close'] - last_candle['open'])
            candle_range = last_candle['high'] - last_candle['low']
            if candle_range > 0 and body_size > candle_range * 0.6:  # 60% body minimum
                bull_score += 1
                
            potential_breakouts.append(('CE', bull_score))
            
        # Enhanced Bearish Breakout Detection  
        if current_price < (range_low - min_breakout_size):
            bear_score = 0
            
            # Basic breakout confirmed
            bear_score += 1
            
            # === 5. VOLUME CONFIRMATION (IF AVAILABLE) ===
            if 'volume' in df.columns and len(df) >= 10:
                recent_volume = last_candle.get('volume', 0)
                avg_volume = df['volume'].iloc[-10:-1].mean()
                if recent_volume > avg_volume * 1.2:  # 20% volume surge
                    bear_score += 1
                    
            # === 5. MOMENTUM CONFIRMATION ===
            # Check for follow-through momentum
            if (last_candle['close'] < last_candle['open'] and  # Red candle
                last_candle['low'] < prev_candle['low']):       # Lower low
                bear_score += 1
                
            # === 6. CANDLE BODY STRENGTH (AVOID WICKS) ===
            body_size = abs(last_candle['close'] - last_candle['open'])
            candle_range = last_candle['high'] - last_candle['low']
            if candle_range > 0 and body_size > candle_range * 0.6:  # 60% body minimum
                bear_score += 1
                
            potential_breakouts.append(('PE', bear_score))
            
        if not potential_breakouts:
            return None, None, None
            
        # === 6. FALSE BREAKOUT PROTECTION ===
        # Check recent breakout history to avoid failed breakout areas
        for side, base_score in potential_breakouts:
            false_breakout_penalty = 0
            
            # Check last 8 candles for recent failed breakouts
            recent_data = df.iloc[-8:-1]  # Exclude current candle
            
            if side == 'CE':
                # Check for recent failed bullish breakouts
                failed_bull_attempts = 0
                for i, candle in recent_data.iterrows():
                    if (candle['high'] > range_high * 0.999 and  # Near breakout level
                        candle['close'] <= range_high):          # But failed to sustain
                        failed_bull_attempts += 1
                        
                if failed_bull_attempts >= 2:  # Multiple recent failures
                    false_breakout_penalty = 1
                    
            else:  # PE
                # Check for recent failed bearish breakouts
                failed_bear_attempts = 0
                for i, candle in recent_data.iterrows():
                    if (candle['low'] < range_low * 1.001 and    # Near breakdown level
                        candle['close'] >= range_low):           # But failed to sustain
                        failed_bear_attempts += 1
                        
                if failed_bear_attempts >= 2:  # Multiple recent failures
                    false_breakout_penalty = 1
            
            # === 6. MULTI-CANDLE CONFIRMATION ===
            confirmation_bonus = 0
            if len(df) >= 2:
                # Check if previous candle also shows directional bias
                if side == 'CE' and prev_candle['high'] > recent_candles.iloc[-2]['high']:
                    confirmation_bonus = 1  # Previous candle supported upward move
                elif side == 'PE' and prev_candle['low'] < recent_candles.iloc[-2]['low']:
                    confirmation_bonus = 1  # Previous candle supported downward move
            
            # Calculate final quality score
            quality_score = base_score + atr_squeeze_bonus + confirmation_bonus - false_breakout_penalty
            
            # === 3 & 4. SUPERTREND + VOLATILITY BREAKOUT COMBO ===
            trend_alignment_bonus = 0
            consolidation_above_supertrend_bonus = 0
            allow_trade = False
            
            if 'supertrend_uptrend' in df.columns and 'supertrend' in df.columns:
                curr_uptrend = last_candle.get('supertrend_uptrend')
                supertrend_value = last_candle.get('supertrend')
                
                if pd.notna(curr_uptrend) and pd.notna(supertrend_value):
                    
                    # Check trend alignment
                    trend_aligned = ((side == 'CE' and curr_uptrend) or 
                                   (side == 'PE' and not curr_uptrend))
                    
                    if trend_aligned:
                        trend_alignment_bonus = 1
                        
                        # === SUPERTREND + VOLATILITY COMBO: CONSOLIDATION ABOVE/BELOW SUPERTREND ===
                        # Check if consolidation range is positioned correctly relative to Supertrend
                        
                        if side == 'CE' and curr_uptrend:
                            # For bullish breakouts: consolidation should be ABOVE Supertrend line
                            if range_low > supertrend_value:
                                consolidation_above_supertrend_bonus = 2  # Premium setup bonus
                                await self.strategy._log_debug("Supertrend Combo", 
                                    f"🎯 Perfect BULL setup: Consolidation above Supertrend at {supertrend_value:.2f}")
                            elif range_high > supertrend_value:
                                consolidation_above_supertrend_bonus = 1  # Partial bonus
                        
                        elif side == 'PE' and not curr_uptrend:
                            # For bearish breakouts: consolidation should be BELOW Supertrend line  
                            if range_high < supertrend_value:
                                consolidation_above_supertrend_bonus = 2  # Premium setup bonus
                                await self.strategy._log_debug("Supertrend Combo", 
                                    f"🎯 Perfect BEAR setup: Consolidation below Supertrend at {supertrend_value:.2f}")
                            elif range_low < supertrend_value:
                                consolidation_above_supertrend_bonus = 1  # Partial bonus
                        
                        allow_trade = True  # Standard trend-following trade
                    else:
                        # === 4. COUNTER-TREND TRADES WITH EXTRA CONFIRMATIONS ===
                        # Allow counter-trend only with very high quality score
                        if quality_score >= 5:  # Need exceptional setup for counter-trend
                            allow_trade = True
                            await self.strategy._log_debug("Counter-Trend", 
                                f"High-quality counter-trend breakout: Score {quality_score}")
                else:
                    allow_trade = True  # No supertrend data, allow trade
            else:
                allow_trade = True  # No supertrend data, allow trade
                
            # Final scoring and decision
            final_score = quality_score + trend_alignment_bonus + consolidation_above_supertrend_bonus
            
            if allow_trade and final_score >= 3:  # Minimum quality threshold
                opt = self.strategy.get_entry_option(side)
                if opt:
                    # Generate descriptive trigger name based on quality
                    if final_score >= 6:
                        grade = "Premium"
                    elif final_score >= 5:
                        grade = "Strong" 
                    elif final_score >= 4:
                        grade = "Good"
                    else:
                        grade = "Basic"
                        
                    # Enhanced trigger naming for Supertrend combo setups
                    if consolidation_above_supertrend_bonus >= 2:
                        trigger = f"V47_Supertrend_Combo_{grade}_{side}"
                    else:
                        trigger = f"V47_Volatility_Breakout_{grade}_{side}"
                        
                    await self.strategy._log_debug("Enhanced Breakout", 
                        f"🎯 {grade} breakout: Score {final_score}, Range {range_periods}c, "
                        f"ATR squeeze: {atr_squeeze_bonus > 0}, Supertrend combo: {consolidation_above_supertrend_bonus}")
                    return side, trigger, opt
                    
        return None, None, None

# ==============================================================================
# V47.14 ENTRY ENGINE 2: ENHANCED SUPERTREND FLIP 
# ==============================================================================

class V47SupertrendFlipEngine(BaseEntryStrategy):
    """V47.14 Entry Logic 2: Enhanced Supertrend Flip Detection"""
    
    async def check(self):
        """Enhanced supertrend flip with close vs open validation"""
        df = self.data_manager.data_df
        if len(df) < 2 or 'supertrend_uptrend' not in df.columns:
            return None, None, None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        curr_uptrend = last.get('supertrend_uptrend')
        prev_uptrend = prev.get('supertrend_uptrend')

        if pd.isna(curr_uptrend) or pd.isna(prev_uptrend):
            return None, None, None

        flip_signals = []
        
        # Enhanced flip detection with candle confirmation
        # Flipped to Bullish
        if (prev_uptrend is False and curr_uptrend is True and 
            last['close'] > last['open']):  # Green candle confirmation
            flip_signals.extend([
                ('CE', "V47_Enhanced_Supertrend_Flip_CE"), 
                ('PE', "V47_Enhanced_Supertrend_Flip_PE_Alt")
            ])
            
        # Flipped to Bearish  
        elif (prev_uptrend is True and curr_uptrend is False and 
              last['close'] < last['open']):  # Red candle confirmation
            flip_signals.extend([
                ('PE', "V47_Enhanced_Supertrend_Flip_PE"), 
                ('CE', "V47_Enhanced_Supertrend_Flip_CE_Alt")
            ])

        # Return first valid signal (primary first, then alternate)
        for side, trigger in flip_signals:
            opt = self.strategy.get_entry_option(side)
            if opt:
                return side, trigger, opt
                
        return None, None, None

# ==============================================================================
# V47.14 ENTRY ENGINE 3: TREND CONTINUATION
# ==============================================================================

class V47TrendContinuationEngine(BaseEntryStrategy):
    """V47.14 Entry Logic 3: Trend Continuation after consolidation"""
    
    async def check(self):
        """Trend continuation logic for established trends"""
        df = self.data_manager.data_df
        if len(df) < 10:  # Need history for trend analysis
            return None, None, None
            
        # Determine overall trend state from supertrend
        trend_state = await self._determine_trend_state()
        if not trend_state:
            return None, None, None
            
        current_price = self.data_manager.prices.get(self.strategy.index_symbol)
        if not current_price:
            return None, None, None
            
        # Check for range breakout in trend direction
        recent_candles = df.iloc[-10:]  # Last 10 candles for range
        recent_high = recent_candles['high'].max()
        recent_low = recent_candles['low'].min()
        
        continuation_signal = None
        
        # Bullish trend continuation
        if (trend_state == 'BULLISH' and 
            current_price > recent_high):
            continuation_signal = ('CE', 'V47_Trend_Continuation_CE')
            
        # Bearish trend continuation  
        elif (trend_state == 'BEARISH' and 
              current_price < recent_low):
            continuation_signal = ('PE', 'V47_Trend_Continuation_PE')
            
        if continuation_signal:
            side, trigger = continuation_signal
            opt = self.strategy.get_entry_option(side)
            if opt:
                return side, trigger, opt
                
        return None, None, None
    
    async def _determine_trend_state(self):
        """Determine overall trend from supertrend indicator"""
        df = self.data_manager.data_df
        if 'supertrend_uptrend' not in df.columns or len(df) < 5:
            return None
            
        # Look at last 5 candles for trend consistency
        recent_trend = df['supertrend_uptrend'].iloc[-5:]
        
        # Require at least 3 of last 5 candles in same trend
        bullish_count = recent_trend.sum()
        
        if bullish_count >= 3:
            return 'BULLISH'
        elif bullish_count <= 2:
            return 'BEARISH'
        else:
            return None  # Mixed/unclear trend

# ==============================================================================
# V47.14 ENTRY ENGINE 4: COUNTER-TREND/STEEP RE-ENTRY (LOWEST PRIORITY)
# ==============================================================================

class V47CounterTrendEngine(BaseEntryStrategy):
    """V47.14 Entry Logic 4: Counter-trend/Steep re-entry for reversals"""
    
    def __init__(self, strategy_instance):
        super().__init__(strategy_instance)
        self.pending_steep_signal = None
        
    async def check(self):
        """Counter-trend detection with pending signal system"""
        # First check any pending signals
        if self.pending_steep_signal:
            result = await self._validate_pending_signal()
            if result:
                return result
                
        # Look for new counter-trend setups
        return await self._detect_counter_trend_setup()
    
    async def _detect_counter_trend_setup(self):
        """Detect counter-trend opportunities"""
        df = self.data_manager.data_df
        if len(df) < 2:
            return None, None, None
            
        # Get trend state and current candle
        trend_state = await self._get_current_trend()
        if not trend_state:
            return None, None, None
            
        current_candle = df.iloc[-1]
        is_red_candle = current_candle['close'] < current_candle['open']
        is_green_candle = current_candle['close'] > current_candle['open'] 
        
        pending_signal = None
        
        # Counter-trend setups
        if trend_state == 'BULLISH' and is_red_candle:
            # Bullish trend but red candle - potential PE entry
            pending_signal = {
                'side': 'PE',
                'trigger': 'V47_Counter_Trend_PE',
                'created_at': datetime.now(),
                'setup_type': 'counter_bullish_trend'
            }
            
        elif trend_state == 'BEARISH' and is_green_candle:
            # Bearish trend but green candle - potential CE entry  
            pending_signal = {
                'side': 'CE',
                'trigger': 'V47_Counter_Trend_CE',
                'created_at': datetime.now(),
                'setup_type': 'counter_bearish_trend'
            }
            
        if pending_signal:
            self.pending_steep_signal = pending_signal
            await self.strategy._log_debug("Counter-Trend", 
                f"🔄 Pending {pending_signal['side']} counter-trend signal created")
            
        return None, None, None  # No immediate execution, must validate next tick
    
    async def _validate_pending_signal(self):
        """Validate pending counter-trend signal with strict requirements"""
        signal = self.pending_steep_signal
        
        # Check signal age (max 1 minute)
        age = datetime.now() - signal['created_at']
        if age > timedelta(minutes=1):
            self.pending_steep_signal = None
            await self.strategy._log_debug("Counter-Trend", "⏰ Pending signal expired")
            return None, None, None
        
        # Get option for validation
        opt = self.strategy.get_entry_option(signal['side'])
        if not opt:
            return None, None, None
            
        # Enhanced validation required for counter-trend
        if await self.strategy._enhanced_validate_entry_conditions_with_candle_color(
            signal['side'], opt, is_counter_trend=True):
            
            # Clear pending signal and execute
            self.pending_steep_signal = None
            await self.strategy._log_debug("Counter-Trend", 
                f"Counter-trend {signal['side']} validated and executing")
            return signal['side'], signal['trigger'], opt
            
        return None, None, None
    

    
    async def _get_current_trend(self):
        """Get current trend state for counter-trend analysis"""
        df = self.data_manager.data_df
        if 'supertrend_uptrend' not in df.columns or len(df) < 1:
            return None
            
        current_uptrend = df.iloc[-1].get('supertrend_uptrend')
        if pd.isna(current_uptrend):
            return None
            
        return 'BULLISH' if current_uptrend else 'BEARISH'

# ==============================================================================
# V47.14 STRATEGY COORDINATOR - PRIORITY SYSTEM
# ==============================================================================

class V47StrategyCoordinator:
    """Coordinates all 4 V47.14 entry engines with proper priority"""
    
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        
        # Initialize all 4 engines in priority order
        self.engines = [
            V47VolatilityBreakoutEngine(strategy_instance),      # Priority 1
            V47SupertrendFlipEngine(strategy_instance),          # Priority 2  
            V47TrendContinuationEngine(strategy_instance),       # Priority 3
            V47CounterTrendEngine(strategy_instance)             # Priority 4
        ]
        
        self.engine_names = [
            "Volatility Breakout",
            "Supertrend Flip", 
            "Trend Continuation",
            "Counter-Trend"
        ]
    
    async def check_all_v47_entries(self):
        """Check all engines in priority order - first valid signal wins"""
        for i, engine in enumerate(self.engines):
            try:
                result = await engine.check()
                if result and result[0] is not None:  # Valid signal found
                    side, trigger, opt = result
                    
                    # Apply universal validation gauntlet
                    if await self.strategy._enhanced_validate_entry_conditions_with_candle_color(
                        side, opt, is_reversal=(i in [1, 3])):  # Flip and counter-trend are reversals
                        
                        await self.strategy._log_debug("V47 Coordinator", 
                            f"{self.engine_names[i]} signal validated: {trigger}")
                        
                        # Execute the trade
                        await self.strategy.take_trade(trigger, opt)
                        return True
                    else:
                        await self.strategy._log_debug("V47 Coordinator", 
                            f"{self.engine_names[i]} signal failed validation")
                        
            except Exception as e:
                await self.strategy._log_debug("V47 Engine Error", 
                    f"Error in {self.engine_names[i]}: {e}")
                continue
                
        return False  # No valid signals found
    
    async def on_new_candle(self):
        """Called when new minute candle forms - for crossover detection"""
        # Specifically trigger supertrend flip detection on new candles
        try:
            flip_engine = self.engines[1]  # Supertrend flip engine
            result = await flip_engine.check()
            if result and result[0] is not None:
                side, trigger, opt = result
                
                # Quick validation for new candle crossovers (reversal type)
                if await self.strategy._enhanced_validate_entry_conditions_with_candle_color(
                    side, opt, is_reversal=True):
                    
                    await self.strategy._log_debug("V47 New Candle", 
                        f"New candle crossover validated: {trigger}")
                    await self.strategy.take_trade(trigger, opt)
                    return True
                    
        except Exception as e:
            await self.strategy._log_debug("V47 New Candle Error", f"Error: {e}")
            
        return False
    
    async def continuous_monitoring(self):
        """Continuous tick-by-tick monitoring for immediate signals"""
        # Run full priority check for non-crossover signals
        return await self.check_all_v47_entries()

# ==============================================================================
# UOA COMPATIBILITY STRATEGY (EXTERNAL SIGNALS)
# ==============================================================================

class UoaEntryStrategy(BaseEntryStrategy):
    """UOA strategy - external signal source for compatibility"""
    async def check(self):
        if not self.strategy.uoa_watchlist: 
            return None, None, None
        
        for token, data in list(self.strategy.uoa_watchlist.items()):
            symbol, side, strike = data['symbol'], data['type'], data['strike']
            option_candle = self.data_manager.option_candles.get(symbol)
            current_price = self.data_manager.prices.get(symbol)
            
            if not option_candle or 'open' not in option_candle or not current_price: 
                continue
                
            if current_price <= option_candle['open']:
                continue
            
            opt = self.strategy.get_entry_option(side, strike)
            if opt:
                del self.strategy.uoa_watchlist[token]
                await self.strategy._update_ui_uoa_list()
                return side, "UOA_Entry", opt
                
        return None, None, None

# ==============================================================================
# V47.14 FULL SYSTEM READY
# All 4 entry engines + coordinator + universal validation system
# ==============================================================================
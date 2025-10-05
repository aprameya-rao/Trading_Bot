# backend/core/enhanced_trackers.py - V47.14 Enhanced Signal Tracking System
import asyncio
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class SignalStrengthCalculator:
    """
    V47.14 Signal Strength Calculation System
    Calculates signal quality based on Supertrend distance and market conditions
    """
    
    @staticmethod
    def calculate_crossover_strength(current_price: float, supertrend_value: float, 
                                   atr_value: float = None) -> float:
        """
        Calculate signal strength based on distance from Supertrend
        Higher distance = stronger signal
        """
        if not supertrend_value or supertrend_value <= 0:
            return 1.0
            
        distance = abs(current_price - supertrend_value)
        
        # Normalize by ATR if available for better relative strength
        if atr_value and atr_value > 0:
            normalized_strength = distance / atr_value
            # Cap at reasonable maximum (5x ATR)
            return min(normalized_strength, 5.0)
        else:
            # Fallback to percentage distance
            pct_distance = (distance / supertrend_value) * 100
            return min(pct_distance * 0.2, 5.0)  # Scale to 0-5 range
    
    @staticmethod
    def calculate_momentum_strength(price_history: List[Tuple[datetime, float]], 
                                  window: int = 5) -> float:
        """
        Calculate momentum strength based on recent price movement consistency
        """
        if len(price_history) < window:
            return 0.5
            
        prices = [p[1] for p in price_history[-window:]]
        
        # Count consecutive rising ticks
        rising_count = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                rising_count += 1
                
        # Calculate momentum strength (0-1 scale)
        momentum_strength = rising_count / (len(prices) - 1)
        return momentum_strength


class OptionAnalysisEngine:
    """
    V47.14 Option Price History Analysis
    Provides SMA/WMA calculations and multi-tick confirmation
    """
    
    def __init__(self):
        self.price_histories: Dict[str, List[Tuple[datetime, float]]] = {}
        self.analysis_cache: Dict[str, Dict] = {}
        
    def update_price_history(self, symbol: str, price: float):
        """Update price history for option symbol"""
        if symbol not in self.price_histories:
            self.price_histories[symbol] = []
            
        self.price_histories[symbol].append((datetime.now(), price))
        
        # Keep last 100 ticks for analysis
        if len(self.price_histories[symbol]) > 100:
            self.price_histories[symbol] = self.price_histories[symbol][-100:]
    
    def get_sma(self, symbol: str, period: int = 9) -> Optional[float]:
        """Calculate Simple Moving Average for option"""
        if symbol not in self.price_histories:
            return None
            
        prices = [p[1] for p in self.price_histories[symbol]]
        if len(prices) < period:
            return None
            
        return sum(prices[-period:]) / period
    
    def get_wma(self, symbol: str, period: int = 9) -> Optional[float]:
        """Calculate Weighted Moving Average for option"""
        if symbol not in self.price_histories:
            return None
            
        prices = [p[1] for p in self.price_histories[symbol]]
        if len(prices) < period:
            return None
            
        recent_prices = prices[-period:]
        weights = np.arange(1, period + 1)
        
        return np.dot(recent_prices, weights) / weights.sum()
    
    def check_ma_position_confirmation(self, symbol: str, current_price: float) -> bool:
        """Check if current price is above both SMA and WMA"""
        sma = self.get_sma(symbol)
        wma = self.get_wma(symbol)
        
        if sma is None or wma is None:
            return False
            
        return current_price > sma and current_price > wma and wma > sma
    
    def get_acceleration_factor(self, symbol: str, lookback_ticks: int = 4) -> float:
        """Calculate price acceleration factor"""
        if symbol not in self.price_histories:
            return 0.0
            
        prices = [p[1] for p in self.price_histories[symbol]]
        if len(prices) < lookback_ticks:
            return 0.0
            
        recent_prices = prices[-lookback_ticks:]
        
        if len(recent_prices) < 3:
            return 0.0
            
        # Calculate rate of change acceleration
        early_avg = sum(recent_prices[:2]) / 2
        late_avg = sum(recent_prices[-2:]) / 2
        
        if early_avg <= 0:
            return 0.0
            
        acceleration = (late_avg - early_avg) / early_avg
        return max(0.0, acceleration)
    
    def is_actively_rising(self, symbol: str, ticks: int = 3) -> bool:
        """Check if price is strictly increasing over last few ticks"""
        if symbol not in self.price_histories:
            return False
            
        prices = [p[1] for p in self.price_histories[symbol]]
        if len(prices) < ticks:
            return False
            
        recent_prices = prices[-ticks:]
        
        for i in range(1, len(recent_prices)):
            if recent_prices[i] <= recent_prices[i-1]:
                return False
                
        return True


class EnhancedCrossoverTracker:
    """
    V47.14 Enhanced Crossover Tracker
    5-minute signal tracking with momentum analysis and primary/alternative signal logic
    """
    
    def __init__(self, strategy):
        self.strategy = strategy
        self.active_signals: List[Dict] = []
        self.signal_timeout = 300  # 5 minutes tracking window
        self.option_analyzer = OptionAnalysisEngine()
        
    async def create_tracking_signals(self, crossovers: List[Dict]):
        """Create tracking signals from detected crossovers"""
        current_time = datetime.now()
        
        for crossover in crossovers:
            # Calculate signal strength
            current_price = self.strategy.data_manager.prices.get(self.strategy.index_symbol, 0)
            df = self.strategy.data_manager.data_df
            
            strength = 1.0
            if not df.empty and 'supertrend' in df.columns:
                supertrend_val = df.iloc[-1].get('supertrend')
                atr_val = df.iloc[-1].get('atr') if 'atr' in df.columns else None
                strength = SignalStrengthCalculator.calculate_crossover_strength(
                    current_price, supertrend_val, atr_val
                )
            
            # Create primary and alternative signals
            primary_side = crossover.get('side', 'CE')
            alternative_side = 'PE' if primary_side == 'CE' else 'CE'
            
            # Primary signal (stronger)
            primary_signal = {
                'id': f"{crossover['type']}_{primary_side}_{current_time.strftime('%H%M%S')}",
                'type': crossover['type'],
                'side': primary_side,
                'created_at': current_time,
                'expires_at': current_time + timedelta(seconds=self.signal_timeout),
                'strength': strength,
                'priority': 'primary',
                'option_tracking': {
                    'initial_price': None,
                    'price_history': [],
                    'momentum_confirmed': False,
                    'ma_position_confirmed': False,
                    'acceleration_ok': False
                }
            }
            
            # Alternative signal (weaker)
            alternative_signal = {
                'id': f"{crossover['type']}_{alternative_side}_{current_time.strftime('%H%M%S')}_ALT",
                'type': crossover['type'],
                'side': alternative_side,
                'created_at': current_time,
                'expires_at': current_time + timedelta(seconds=self.signal_timeout),
                'strength': strength * 0.7,  # Reduced strength for alternative
                'priority': 'alternative',
                'option_tracking': {
                    'initial_price': None,
                    'price_history': [],
                    'momentum_confirmed': False,
                    'ma_position_confirmed': False,
                    'acceleration_ok': False
                }
            }
            
            self.active_signals.extend([primary_signal, alternative_signal])
            
            # Log signal creation (async call wrapped for safety)
            try:
                import asyncio
                asyncio.create_task(self.strategy._log_debug("Enhanced Tracker", 
                    f"Created signals: {primary_signal['id']} (strength: {strength:.2f}) + ALT"))
            except RuntimeError:
                pass  # No event loop running
    
    async def enhanced_signal_monitoring(self):
        """Monitor active signals and execute trades when conditions are met"""
        current_time = datetime.now()
        
        for signal in self.active_signals[:]:
            # Remove expired signals
            if current_time > signal['expires_at']:
                await self.strategy._log_debug("Signal Timeout", 
                    f"Signal {signal['id']} expired after {self.signal_timeout}s")
                self.active_signals.remove(signal)
                continue
            
            # Get option for this signal
            opt = self.strategy.get_entry_option(signal['side'])
            if not opt:
                continue
                
            symbol = opt['tradingsymbol']
            current_price = self.strategy.data_manager.prices.get(symbol)
            
            if not current_price:
                continue
                
            # Update option price history
            self.option_analyzer.update_price_history(symbol, current_price)
            
            # Track initial price
            if signal['option_tracking']['initial_price'] is None:
                signal['option_tracking']['initial_price'] = current_price
            
            # Update price history for this signal
            signal['option_tracking']['price_history'].append({
                'time': current_time,
                'price': current_price
            })
            
            # Keep only last 10 entries
            if len(signal['option_tracking']['price_history']) > 10:
                signal['option_tracking']['price_history'] = signal['option_tracking']['price_history'][-10:]
            
            # Check if signal is ready for execution
            if await self.check_signal_execution_readiness(signal, opt):
                await self.execute_tracked_trade(signal, opt)
                self.active_signals.remove(signal)
    
    async def check_signal_execution_readiness(self, signal: Dict, opt: Dict) -> bool:
        """Check if signal meets all execution criteria"""
        symbol = opt['tradingsymbol']
        tracking = signal['option_tracking']
        
        # Need at least 3 price updates
        if len(tracking['price_history']) < 3:
            return False
            
        # Check active price rise
        if not self.option_analyzer.is_actively_rising(symbol, ticks=3):
            return False
            
        # Primary signals need stronger confirmation
        if signal['priority'] == 'primary':
            return await self.check_primary_signal_momentum(signal, opt)
        else:
            # Alternative signals need reversal confirmation
            return await self.check_alternative_signal_momentum(signal, opt)
    
    async def check_primary_signal_momentum(self, signal: Dict, opt: Dict) -> bool:
        """Check momentum requirements for primary signals"""
        symbol = opt['tradingsymbol']
        tracking = signal['option_tracking']
        
        # Check recent price momentum (60% rising ticks)
        recent_prices = [p['price'] for p in tracking['price_history'][-5:]]
        if len(recent_prices) >= 3:
            rising_count = sum(1 for i in range(1, len(recent_prices)) 
                             if recent_prices[i] > recent_prices[i-1])
            momentum_ok = rising_count >= len(recent_prices) * 0.6
            tracking['momentum_confirmed'] = momentum_ok
        
        # Check MA position
        current_price = recent_prices[-1] if recent_prices else 0
        ma_position_ok = self.option_analyzer.check_ma_position_confirmation(symbol, current_price)
        tracking['ma_position_confirmed'] = ma_position_ok
        
        # Check acceleration
        acceleration_factor = self.option_analyzer.get_acceleration_factor(symbol)
        tracking['acceleration_ok'] = acceleration_factor > 0.02
        
        # Signal age should be between 30-300 seconds
        signal_age = (datetime.now() - signal['created_at']).total_seconds()
        time_window_ok = 30 <= signal_age <= 300
        
        # Need at least 2 out of 3 conditions + time window
        conditions = [
            tracking.get('momentum_confirmed', False),
            tracking.get('ma_position_confirmed', False),
            tracking.get('acceleration_ok', False)
        ]
        
        passed_conditions = sum(conditions)
        
        if passed_conditions >= 2 and time_window_ok:
            await self.strategy._log_debug("Primary Signal", 
                f"{signal['id']}: Momentum check passed ({passed_conditions}/3)")
            return True
            
        return False
    
    async def check_alternative_signal_momentum(self, signal: Dict, opt: Dict) -> bool:
        """Check reversal momentum for alternative signals"""
        # First pass primary momentum check
        if not await self.check_primary_signal_momentum(signal, opt):
            return False
            
        # Additional reversal confirmation
        symbol = opt['tradingsymbol']
        
        # Get current option and index candles
        option_candle = self.strategy.data_manager.option_candles.get(symbol)
        index_candle = self.strategy.data_manager.current_candle
        
        if not option_candle or not index_candle:
            return False
            
        # Check candle colors
        option_green = option_candle.get('close', 0) > option_candle.get('open', 0)
        index_green = index_candle.get('close', 0) > index_candle.get('open', 0)
        
        if not option_green:
            return False
            
        # Reversal logic based on signal type and side
        if signal['type'] == 'BULLISH_FLIP' and signal['side'] == 'PE':
            # PE trade on bullish flip - need index red candle for reversal
            reversal_confirmed = not index_green
        elif signal['type'] == 'BEARISH_FLIP' and signal['side'] == 'CE':
            # CE trade on bearish flip - need index green candle for reversal
            reversal_confirmed = index_green
        else:
            reversal_confirmed = True  # Primary side doesn't need reversal
            
        if reversal_confirmed:
            await self.strategy._log_debug("Alternative Signal", 
                f"{signal['id']}: Reversal momentum confirmed")
            
        return reversal_confirmed
    
    async def execute_tracked_trade(self, signal: Dict, opt: Dict):
        """Execute trade for validated signal"""
        # Final ATM confirmation check
        if not self.strategy._is_atm_confirming(signal['side'], is_reversal=True):
            # Tracked trade blocked by ATM confirmation (silent)
            return
            
        # Add small premium to current price for execution
        current_price = self.strategy.data_manager.prices.get(opt['tradingsymbol'])
        if not current_price:
            return
            
        reason = f"Enhanced_{signal['type']}_{signal['side']}_{signal['priority']}_ST"
        
        await self.strategy._log_debug("Enhanced Execution", 
            f"EXECUTING: {reason} | Strength: {signal['strength']:.2f}")
        
        await self.strategy.take_trade(reason, opt)


class PersistentTrendTracker:
    """
    V47.14 Persistent Trend Tracker  
    3-minute trend continuation monitoring with multi-tick confirmation
    """
    
    def __init__(self, strategy):
        self.strategy = strategy
        self.trend_signals: List[Dict] = []
        self.continuation_window = 180  # 3 minutes
        self.option_analyzer = OptionAnalysisEngine()
        
    async def check_extended_trend_continuation(self):
        """Check for trend continuation opportunities"""
        if len(self.strategy.data_manager.data_df) < 5:
            return
            
        current_price = self.strategy.data_manager.prices.get(self.strategy.index_symbol)
        if not current_price:
            return
            
        df = self.strategy.data_manager.data_df
        
        # Determine current trend from supertrend
        trend_state = await self._get_trend_state(df)
        if not trend_state:
            return
            
        # Check for breakout above recent highs/lows
        recent_candles = df.tail(10)
        
        for candle in recent_candles.itertuples():
            if trend_state == 'BULLISH' and current_price > candle.high:
                await self.create_trend_continuation_signal('CE', current_price, candle.high)
            elif trend_state == 'BEARISH' and current_price < candle.low:
                await self.create_trend_continuation_signal('PE', current_price, candle.low)
    
    async def create_trend_continuation_signal(self, side: str, current_price: float, breakout_level: float):
        """Create a new trend continuation signal"""
        timestamp = datetime.now()
        signal_id = f"TREND_CONT_{side}_{timestamp.strftime('%H%M%S')}"
        
        # Avoid duplicate signals
        if any(s['id'] == signal_id for s in self.trend_signals):
            return
            
        # Calculate signal strength based on breakout magnitude
        breakout_magnitude = abs(current_price - breakout_level) / breakout_level
        strength = min(breakout_magnitude * 100, 5.0)  # Cap at 5.0
        
        signal = {
            'id': signal_id,
            'side': side,
            'created_at': timestamp,
            'expires_at': timestamp + timedelta(seconds=self.continuation_window),
            'strength': strength,
            'breakout_level': breakout_level,
            'option_momentum_history': [],
            'confirmation_count': 0
        }
        
        self.trend_signals.append(signal)
        
        await self.strategy._log_debug("Trend Tracker", 
            f"Created continuation signal: {signal_id} | Strength: {strength:.2f}")
    
    async def monitor_trend_signals(self):
        """Monitor active trend continuation signals"""
        current_time = datetime.now()
        
        for signal in self.trend_signals[:]:
            # Remove expired signals
            if current_time > signal['expires_at']:
                await self.strategy._log_debug("Trend Timeout", 
                    f"Trend signal {signal['id']} expired after {self.continuation_window}s")
                self.trend_signals.remove(signal)
                continue
            
            # Check ATM confirmation first
            if not self.strategy._is_atm_confirming(signal['side']):
                continue
                
            # Get option and check momentum
            opt = self.strategy.get_entry_option(signal['side'])
            if opt and await self.check_trend_momentum(signal, opt):
                # Final validation through universal gauntlet
                if await self.strategy._enhanced_validate_entry_conditions_with_candle_color(
                    signal['side'], opt, is_reversal=False):
                    
                    reason = f"Enhanced_Trend_Continuation_{signal['side']}"
                    await self.strategy._log_debug("Trend Execution", 
                        f"EXECUTING: {reason} | Confirmations: {signal['confirmation_count']}")
                    
                    await self.strategy.take_trade(reason, opt)
                    self.trend_signals.remove(signal)
    
    async def check_trend_momentum(self, signal: Dict, opt: Dict) -> bool:
        """Check if trend momentum is building for execution"""
        symbol = opt['tradingsymbol']
        current_price = self.strategy.data_manager.prices.get(symbol)
        
        if not current_price:
            return False
            
        # Update option price history
        self.option_analyzer.update_price_history(symbol, current_price)
        
        # Track momentum
        signal['option_momentum_history'].append({
            'time': datetime.now(),
            'price': current_price
        })
        
        # Keep last 10 entries
        if len(signal['option_momentum_history']) > 10:
            signal['option_momentum_history'] = signal['option_momentum_history'][-10:]
            
        # Need at least 3 price updates
        if len(signal['option_momentum_history']) < 3:
            return False
            
        # Check for consistent momentum
        recent_prices = [p['price'] for p in signal['option_momentum_history'][-3:]]
        
        # Must be actively rising
        if not all(recent_prices[i] > recent_prices[i-1] for i in range(1, len(recent_prices))):
            return False
            
        # Check multi-tick confirmation (need 3+ confirmations)
        if recent_prices[-1] > recent_prices[0]:
            signal['confirmation_count'] += 1
            
        # Execute when we have sufficient confirmations and strong momentum
        return signal['confirmation_count'] >= 3 and self.option_analyzer.is_actively_rising(symbol, ticks=3)
    
    async def _get_trend_state(self, df: pd.DataFrame) -> Optional[str]:
        """Determine current trend state from supertrend"""
        supertrend_period = self.strategy.params.get('supertrend_period', 5)
        supertrend_multiplier = self.strategy.params.get('supertrend_multiplier', 0.7)
        st_col = f"SUPERT_{supertrend_period}_{supertrend_multiplier}"
        
        if f"{st_col}_u" not in df.columns:
            return None
            
        is_uptrend = df.iloc[-1][f"{st_col}_u"]
        
        if pd.isna(is_uptrend):
            return None
            
        return 'BULLISH' if is_uptrend else 'BEARISH'


class SignalTimeoutManager:
    """
    V47.14 Signal Timeout Management System
    Automatic signal expiration and cleanup
    """
    
    def __init__(self):
        self.managed_signals: Dict[str, List] = {}
        
    def register_signal_list(self, name: str, signal_list: List):
        """Register a signal list for timeout management"""
        self.managed_signals[name] = signal_list
        
    async def cleanup_expired_signals(self):
        """Clean up expired signals across all registered lists"""
        current_time = datetime.now()
        total_cleaned = 0
        
        for list_name, signal_list in self.managed_signals.items():
            initial_count = len(signal_list)
            
            # Remove expired signals
            signal_list[:] = [
                signal for signal in signal_list 
                if current_time <= signal.get('expires_at', current_time)
            ]
            
            cleaned_count = initial_count - len(signal_list)
            total_cleaned += cleaned_count
            
        return total_cleaned
import math
import asyncio
from datetime import datetime, timedelta

class RiskManager:
    """
    V47.14 Enhanced Risk Manager with Adaptive Features
    
    Enhanced Features:
    - Adaptive stop-loss modes based on market conditions
    - Trailing stop-loss with ATR-based adjustments
    - Position-based risk scaling
    - Volatility-adjusted position sizing
    - Time-based risk management
    - Advanced exit strategies
    """
    def __init__(self, params, log_debug_func):
        self.params = params
        self.log_debug = log_debug_func
        
        # V47.14 Enhanced: Adaptive risk management properties
        self.adaptive_sl_mode = params.get("adaptive_sl_mode", "STANDARD")  # STANDARD, ATR_BASED, VOLATILITY_SCALED
        self.max_daily_loss = float(params.get("max_daily_loss_percent", 3.0))
        self.position_scaling_enabled = params.get("position_scaling_enabled", True)
        self.volatility_risk_adjustment = params.get("volatility_risk_adjustment", True)
        self.time_based_exits = params.get("time_based_exits", True)
        
        # V47.14 Enhanced: Dynamic risk tracking
        self.daily_pnl = 0.0
        self.trade_count_today = 0
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.risk_reduction_factor = 1.0  # Reduces position size after losses

    # MODIFIED: Function now accepts live available_cash
    def calculate_trade_details(self, price, lot_size, available_cash=None):
        """
        Calculates the appropriate quantity and initial stop-loss for a trade,
        capped by the real-time available capital.
        """
        # This is the theoretical capital for risk calculation
        capital = float(self.params.get("start_capital", 50000))
        
        risk_percent = float(self.params.get("risk_per_trade_percent", 1.0))
        sl_points = float(self.params.get("trailing_sl_points", 5.0))
        sl_percent = float(self.params.get("trailing_sl_percent", 10.0))

        if price is None or price < 1.0 or lot_size is None:
            try:
                asyncio.create_task(self.log_debug("Risk", f"Invalid price/lot_size: P={price}, L={lot_size}"))
            except RuntimeError:
                # No event loop running, skip logging
                pass
            return None, None

        initial_sl_price = min(price - sl_points, price * (1 - sl_percent / 100))
        risk_per_share = price - initial_sl_price

        if risk_per_share <= 0:
            try:
                asyncio.create_task(self.log_debug("Risk", f"Cannot calculate quantity. Risk per share is zero or negative."))
            except RuntimeError:
                # No event loop running, skip logging
                pass
            return None, None
            
        risk_amount_per_trade = capital * (risk_percent / 100)
        risk_per_lot = risk_per_share * lot_size
        num_lots_by_risk = math.floor(risk_amount_per_trade / risk_per_lot) if risk_per_lot > 0 else 0

        # --- THIS IS THE NEW LOGIC ---
        # Use live cash if provided, otherwise fall back to theoretical capital
        effective_capital = available_cash if available_cash is not None else capital
        
        value_per_lot = price * lot_size
        if value_per_lot <= 0:
            try:
                asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Invalid price or lot size."))
            except RuntimeError:
                # No event loop running, skip logging
                pass
            return None, None
            
        max_lots_by_capital = math.floor(effective_capital / value_per_lot)

        if num_lots_by_risk == 0:
            try:
                asyncio.create_task(self.log_debug("Risk", f"Trade aborted. Risk per trade is too high for even one lot."))
            except RuntimeError:
                # No event loop running, skip logging
                pass
            return None, None

        # The final number of lots is the minimum of what risk allows and what capital allows
        final_num_lots = min(num_lots_by_risk, max_lots_by_capital)

        if final_num_lots < num_lots_by_risk:
            log_source = "Live Capital" if available_cash is not None else "Start Capital"
            try:
                asyncio.create_task(self.log_debug("Risk", f"Lots adjusted down from {num_lots_by_risk} to {final_num_lots} due to {log_source} limit."))
            except RuntimeError:
                # No event loop running, skip logging
                pass
        
        if final_num_lots == 0:
            try:
                asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Final calculated lots is zero."))
            except RuntimeError:
                # No event loop running, skip logging
                pass
            return None, None
            
        qty = final_num_lots * lot_size
        return qty, initial_sl_price

    # =================================================================
    # V47.14 ENHANCED RISK MANAGEMENT FEATURES
    # =================================================================
    
    def calculate_adaptive_stop_loss(self, entry_price, option_type, current_atr=None, volatility_factor=1.0):
        """
        V47.14 Enhanced: Calculate adaptive stop-loss based on multiple factors
        
        Args:
            entry_price: Entry price of the position
            option_type: 'CE' or 'PE'
            current_atr: Current ATR value for ATR-based SL
            volatility_factor: Market volatility multiplier
            
        Returns:
            Adaptive stop-loss price and stop-loss type
        """
        sl_points = float(self.params.get("trailing_sl_points", 5.0))
        sl_percent = float(self.params.get("trailing_sl_percent", 10.0))
        
        if self.adaptive_sl_mode == "ATR_BASED" and current_atr:
            # ATR-based stop loss (more dynamic)
            atr_multiplier = 1.5 * volatility_factor
            sl_distance = current_atr * atr_multiplier
            adaptive_sl = entry_price - sl_distance
            sl_type = f"ATR_SL_{atr_multiplier:.1f}x"
            
        elif self.adaptive_sl_mode == "VOLATILITY_SCALED":
            # Scale stop-loss based on volatility
            volatility_adjusted_percent = sl_percent * volatility_factor
            adaptive_sl = entry_price * (1 - volatility_adjusted_percent / 100)
            sl_type = f"VOL_SL_{volatility_adjusted_percent:.1f}%"
            
        else:
            # Standard stop-loss calculation
            adaptive_sl = min(entry_price - sl_points, entry_price * (1 - sl_percent / 100))
            sl_type = "STANDARD_SL"
        
        return max(adaptive_sl, 1.0), sl_type
    
    def calculate_enhanced_position_size(self, price, lot_size, available_cash=None, 
                                       volatility_factor=1.0, signal_strength=1.0):
        """
        V47.14 Enhanced: Calculate position size with multiple risk factors
        
        Args:
            price: Option price
            lot_size: Lot size
            available_cash: Available capital
            volatility_factor: Market volatility (higher = reduce size)
            signal_strength: Signal confidence (0.5-1.5, higher = increase size)
            
        Returns:
            Enhanced quantity and risk metrics
        """
        # Base risk calculation
        qty, initial_sl = self.calculate_trade_details(price, lot_size, available_cash)
        
        if qty is None:
            return None, None, {}
        
        risk_metrics = {
            'base_qty': qty,
            'volatility_factor': volatility_factor,
            'signal_strength': signal_strength,
            'risk_reduction_factor': self.risk_reduction_factor,
            'adjustments': []
        }
        
        # V47.14 Enhanced: Apply volatility adjustment
        if self.volatility_risk_adjustment and volatility_factor != 1.0:
            volatility_adjustment = 1.0 / max(volatility_factor, 0.5)
            qty = int(qty * volatility_adjustment)
            risk_metrics['adjustments'].append(f"Volatility: {volatility_adjustment:.2f}x")
        
        # V47.14 Enhanced: Apply signal strength adjustment
        if signal_strength != 1.0:
            signal_adjustment = min(max(signal_strength, 0.5), 1.5)  # Cap between 0.5x and 1.5x
            qty = int(qty * signal_adjustment)
            risk_metrics['adjustments'].append(f"Signal: {signal_adjustment:.2f}x")
        
        # V47.14 Enhanced: Apply consecutive loss reduction
        if self.consecutive_losses > 0:
            loss_reduction = max(0.5, 1.0 - (self.consecutive_losses * 0.1))
            qty = int(qty * loss_reduction)
            risk_metrics['adjustments'].append(f"Loss_Reduction: {loss_reduction:.2f}x")
        
        # V47.14 Enhanced: Daily loss limit check
        if self.is_daily_loss_limit_reached():
            risk_metrics['adjustments'].append("DAILY_LIMIT_REACHED")
            return 0, None, risk_metrics
        
        # V47.14 Enhanced: Position scaling based on time
        if self.position_scaling_enabled:
            time_factor = self.get_time_based_position_factor()
            qty = int(qty * time_factor)
            risk_metrics['adjustments'].append(f"Time: {time_factor:.2f}x")
        
        # Ensure minimum and maximum limits
        min_qty = lot_size  # At least one lot
        max_qty = int(lot_size * 10)  # Maximum 10 lots
        qty = max(min_qty, min(qty, max_qty))
        
        risk_metrics['final_qty'] = qty
        return qty, initial_sl, risk_metrics
    
    def get_time_based_position_factor(self):
        """
        V47.14 Enhanced: Adjust position size based on time of day
        
        Returns:
            Time-based position size multiplier
        """
        if not self.time_based_exits:
            return 1.0
            
        current_time = datetime.now().time()
        
        # Market opening hour (9:15-10:15): Higher volatility, reduce size
        if current_time.hour == 9 or (current_time.hour == 10 and current_time.minute <= 15):
            return 0.8
        # Market closing hour (15:00-15:30): Higher volatility, reduce size
        elif current_time.hour >= 15:
            return 0.7
        # Lunch time (12:00-13:30): Lower volatility, normal size
        elif current_time.hour >= 12 and current_time.hour < 14:
            return 1.0
        # Active trading hours (10:15-12:00, 13:30-15:00): Optimal conditions
        else:
            return 1.1
    
    def is_daily_loss_limit_reached(self):
        """
        V47.14 Enhanced: Check if daily loss limit is reached
        
        Returns:
            True if daily loss limit exceeded
        """
        capital = float(self.params.get("start_capital", 50000))
        daily_loss_threshold = capital * (self.max_daily_loss / 100)
        
        return abs(self.daily_pnl) >= daily_loss_threshold and self.daily_pnl < 0
    
    def update_trade_outcome(self, pnl, is_win):
        """
        V47.14 Enhanced: Update risk management based on trade outcome
        
        Args:
            pnl: Profit/Loss from the trade
            is_win: True if trade was profitable
        """
        self.daily_pnl += pnl
        self.trade_count_today += 1
        self.last_trade_time = datetime.now()
        
        if is_win:
            # Reset consecutive losses on win
            self.consecutive_losses = 0
            # Gradually increase risk factor
            self.risk_reduction_factor = min(1.0, self.risk_reduction_factor + 0.05)
        else:
            # Increase consecutive losses
            self.consecutive_losses += 1
            # Reduce risk factor after losses
            self.risk_reduction_factor = max(0.5, self.risk_reduction_factor - 0.1)
            
        # Log the update
        try:
            asyncio.create_task(self.log_debug("Risk Update", 
                f"Trade: {'WIN' if is_win else 'LOSS'} | PnL: {pnl:.2f} | Daily: {self.daily_pnl:.2f} | "
                f"Consecutive Losses: {self.consecutive_losses} | Risk Factor: {self.risk_reduction_factor:.2f}"))
        except RuntimeError:
            pass
    
    def should_exit_time_based(self, entry_time, current_time=None):
        """
        V47.14 Enhanced: Time-based exit logic
        
        Args:
            entry_time: When the position was entered
            current_time: Current time (default: now)
            
        Returns:
            (should_exit, reason) tuple
        """
        if not self.time_based_exits:
            return False, None
            
        if current_time is None:
            current_time = datetime.now()
            
        # Calculate position holding time
        holding_time = current_time - entry_time
        
        # Exit near market close (3:20 PM)
        if current_time.time() >= datetime.strptime("15:20", "%H:%M").time():
            return True, "TIME_EXIT_MARKET_CLOSE"
        
        # Exit very old positions (more than 2 hours)
        if holding_time > timedelta(hours=2):
            return True, "TIME_EXIT_MAX_HOLDING"
        
        # Exit lunch time positions if held for more than 30 minutes
        if (current_time.time() >= datetime.strptime("12:00", "%H:%M").time() and 
            current_time.time() <= datetime.strptime("13:30", "%H:%M").time() and
            holding_time > timedelta(minutes=30)):
            return True, "TIME_EXIT_LUNCH_TIMEOUT"
            
        return False, None
    
    def calculate_trailing_stop_loss(self, entry_price, current_price, high_since_entry, 
                                   current_atr=None, volatility_factor=1.0):
        """
        V47.14 Enhanced: Advanced trailing stop-loss calculation
        
        Args:
            entry_price: Original entry price
            current_price: Current option price
            high_since_entry: Highest price since entry
            current_atr: Current ATR for dynamic trailing
            volatility_factor: Market volatility factor
            
        Returns:
            New trailing stop-loss price and trailing type
        """
        # Get current profit percentage
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        if self.adaptive_sl_mode == "ATR_BASED" and current_atr:
            # ATR-based trailing stop
            trail_distance = current_atr * 1.0 * volatility_factor
            new_sl = high_since_entry - trail_distance
            trail_type = f"ATR_TRAIL_{volatility_factor:.1f}x"
            
        elif profit_pct > 20:
            # Aggressive trailing for high profits
            trail_distance = (high_since_entry - entry_price) * 0.3  # Trail 30% from high
            new_sl = entry_price + trail_distance
            trail_type = "AGGRESSIVE_TRAIL_30%"
            
        elif profit_pct > 10:
            # Moderate trailing for decent profits
            trail_distance = (high_since_entry - entry_price) * 0.5  # Trail 50% from high
            new_sl = entry_price + trail_distance
            trail_type = "MODERATE_TRAIL_50%"
            
        else:
            # Conservative trailing for small profits
            sl_points = float(self.params.get("trailing_sl_points", 5.0))
            new_sl = max(entry_price - sl_points, current_price * 0.9)  # 10% trailing
            trail_type = "CONSERVATIVE_TRAIL"
        
        return max(new_sl, 1.0), trail_type
    
    def get_risk_summary(self):
        """
        V47.14 Enhanced: Get comprehensive risk summary
        
        Returns:
            Dictionary with current risk metrics
        """
        capital = float(self.params.get("start_capital", 50000))
        
        return {
            'daily_pnl': self.daily_pnl,
            'daily_pnl_percent': (self.daily_pnl / capital) * 100,
            'daily_loss_limit': self.max_daily_loss,
            'trades_today': self.trade_count_today,
            'consecutive_losses': self.consecutive_losses,
            'risk_reduction_factor': self.risk_reduction_factor,
            'adaptive_sl_mode': self.adaptive_sl_mode,
            'loss_limit_reached': self.is_daily_loss_limit_reached(),
            'last_trade_time': self.last_trade_time.strftime("%H:%M:%S") if self.last_trade_time else None
        }

import math
import asyncio

class RiskManager:
    """Handles position sizing and risk calculations."""
    def __init__(self, params, log_debug_func):
        self.params = params
        self.log_debug = log_debug_func

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
            asyncio.create_task(self.log_debug("Risk", f"Invalid price/lot_size: P={price}, L={lot_size}"))
            return None, None

        initial_sl_price = max(price - sl_points, price * (1 - sl_percent / 100))
        risk_per_share = price - initial_sl_price

        if risk_per_share <= 0:
            asyncio.create_task(self.log_debug("Risk", f"Cannot calculate quantity. Risk per share is zero or negative."))
            return None, None
            
        risk_amount_per_trade = capital * (risk_percent / 100)
        risk_per_lot = risk_per_share * lot_size
        num_lots_by_risk = math.floor(risk_amount_per_trade / risk_per_lot) if risk_per_lot > 0 else 0

        # --- THIS IS THE NEW LOGIC ---
        # Use live cash if provided, otherwise fall back to theoretical capital
        effective_capital = available_cash if available_cash is not None else capital
        
        value_per_lot = price * lot_size
        if value_per_lot <= 0:
            asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Invalid price or lot size."))
            return None, None
            
        max_lots_by_capital = math.floor(effective_capital / value_per_lot)

        if num_lots_by_risk == 0:
            if effective_capital > price * lot_size:
                num_lots_by_risk = 1 # Default to 1 lot if capital allows but risk doesn't
            else:
                asyncio.create_task(self.log_debug("Risk", f"Insufficient capital to take even 1 lot."))
                return None, None

        # The final number of lots is the minimum of what risk allows and what capital allows
        final_num_lots = min(num_lots_by_risk, max_lots_by_capital)

        if final_num_lots < num_lots_by_risk:
            log_source = "Live Capital" if available_cash is not None else "Start Capital"
            asyncio.create_task(self.log_debug("Risk", f"Lots adjusted down from {num_lots_by_risk} to {final_num_lots} due to {log_source} limit."))
        
        if final_num_lots == 0:
            asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Final calculated lots is zero."))
            return None, None
            
        qty = final_num_lots * lot_size
        return qty, initial_sl_price

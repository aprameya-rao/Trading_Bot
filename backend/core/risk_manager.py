import math
import asyncio

class RiskManager:
    """Handles position sizing and risk calculations."""
    def __init__(self, params, log_debug_func):
        self.params = params
        self.log_debug = log_debug_func

    def calculate_trade_details(self, price, lot_size):
        """
        Calculates the appropriate quantity and initial stop-loss for a trade.
        Returns a tuple: (quantity, initial_sl_price) or (None, None) if trade is invalid.
        """
        capital = float(self.params.get("start_capital", 50000))
        risk_percent = float(self.params.get("risk_per_trade_percent", 1.0))
        sl_points = float(self.params["trailing_sl_points"])
        sl_percent = float(self.params["trailing_sl_percent"])

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

        if num_lots_by_risk == 0:
            if capital > price * lot_size:
                num_lots_by_risk = 1
                asyncio.create_task(self.log_debug("Risk", "Calculated lots is 0. Defaulting to 1 lot as capital permits."))
            else:
                asyncio.create_task(self.log_debug("Risk", f"Insufficient capital to take even 1 lot."))
                return None, None

        value_per_lot = price * lot_size
        if value_per_lot <= 0:
            asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Invalid price or lot size."))
            return None, None
        
        max_lots_by_capital = math.floor(capital / value_per_lot)
        final_num_lots = min(num_lots_by_risk, max_lots_by_capital)

        if final_num_lots < num_lots_by_risk:
            asyncio.create_task(self.log_debug("Risk", f"Lots adjusted down from {num_lots_by_risk} to {final_num_lots} due to capital limit."))
        
        if final_num_lots == 0:
            asyncio.create_task(self.log_debug("Risk", "Trade Aborted. Insufficient capital for even 1 lot."))
            return None, None
            
        qty = final_num_lots * lot_size
        return qty, initial_sl_price

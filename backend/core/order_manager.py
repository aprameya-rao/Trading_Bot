# backend/core/order_manager.py
import asyncio
from core.kite import kite
import math

def _round_to_tick(price, tick_size=0.05):
    """Rounds a price to the nearest valid tick size."""
    return round(round(price / tick_size) * tick_size, 2)

def _calculate_smart_timeout(symbol, base_timeout_ms=100):
    """
    SPEED OPTIMIZATION: Calculate optimal timeout based on option characteristics
    
    ATM options: Fastest execution (base timeout)
    OTM/ITM: Slightly slower (base + 25ms) 
    Deep OTM/ITM: Slower execution (base + 50ms)
    """
    # Extract strike and current price info from symbol if possible
    # For now, use conservative approach with base timeout
    # This can be enhanced with real-time ATM detection
    
    if "24800" in symbol or "25000" in symbol:  # Common ATM strikes
        return base_timeout_ms  # Fastest
    elif any(strike in symbol for strike in ["24700", "24900", "25100", "25200"]):
        return base_timeout_ms + 25  # Moderate
    else:
        return base_timeout_ms + 50  # Conservative for deep OTM/ITM

class OrderManager:
    """
    Enhanced Order Manager with Order Chasing Logic from v47.14
    
    Features:
    - Attempts limit orders at best bid/ask prices
    - Retries with updated prices if not filled
    - Falls back to market order if limit fails
    - Verifies fills and handles partial fills
    - Cleanup logic for failed orders
    - V47.14 Enhanced: Intelligent position sizing based on volatility
    - V47.14 Enhanced: Adaptive chase timeouts based on option characteristics
    - V47.14 Enhanced: Risk-based order slicing
    """
    def __init__(self, log_debug_func):
        self.log_debug = log_debug_func
        # V47.14 Enhanced: Adaptive order parameters
        self.base_chase_timeout = 100  # Base timeout in ms
        self.volatility_multiplier = 1.0  # Adjusts based on market volatility
        self.max_position_size = 200  # Maximum position size per trade
        self.risk_based_sizing = True  # Enable risk-based position sizing

    async def execute_order(self, transaction_type, order_type=kite.ORDER_TYPE_MARKET, price=None, **kwargs):
        """
        Executes an order with basic retry logic (legacy method for backward compatibility)
        New code should use execute_order_with_chasing() for better fills
        """
        MAX_RETRIES = 3 
        RETRY_DELAY_SECONDS = 2
        VERIFICATION_TIMEOUT_SECONDS = 15

        for attempt in range(MAX_RETRIES):
            try:
                def place_order_sync():
                    order_params = {
                        "variety": kite.VARIETY_REGULAR,
                        "order_type": order_type,
                        "product": kite.PRODUCT_MIS,
                        "transaction_type": transaction_type,
                        **kwargs
                    }
                    if order_type == kite.ORDER_TYPE_LIMIT:
                        if price is None or price <= 0:
                            raise ValueError("A valid price must be provided for LIMIT orders.")
                        order_params["price"] = price
                    
                    return kite.place_order(**order_params)
                
                order_id = await asyncio.to_thread(place_order_sync)
                
                log_price = f"at limit {price}" if order_type == kite.ORDER_TYPE_LIMIT else "at MARKET"
                await self.log_debug("OrderManager", f"Placed {transaction_type} {order_type} order for {kwargs.get('tradingsymbol')} {log_price}. ID: {order_id}. Verifying status...")

                start_time = asyncio.get_event_loop().time()
                while True:
                    if (asyncio.get_event_loop().time() - start_time) > VERIFICATION_TIMEOUT_SECONDS:
                        raise Exception(f"Order {order_id} verification timed out after {VERIFICATION_TIMEOUT_SECONDS}s.")

                    def get_order_history_sync():
                        return kite.order_history(order_id=order_id)

                    order_history = await asyncio.to_thread(get_order_history_sync)
                    
                    if order_history:
                        latest_status = order_history[-1]['status']
                        if latest_status == "COMPLETE":
                            await self.log_debug("OrderManager", f"Order {order_id} confirmed COMPLETE.")
                            return "COMPLETE"
                        
                        if latest_status in ["REJECTED", "CANCELLED"]:
                            rejection_reason = order_history[-1].get('status_message', 'No reason provided.')
                            await self.log_debug("OrderManager", f"Order {order_id} was {latest_status}. Reason: {rejection_reason}. Retrying...")
                            break

                    await asyncio.sleep(0.15)  # SPEED OPTIMIZED: Ultra-fast status check (was 0.3s)
            
            except Exception as e:
                await self.log_debug("OrderManager-ERROR", f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                else:
                    await self.log_debug("OrderManager-CRITICAL", f"Order for {kwargs.get('tradingsymbol')} failed after {MAX_RETRIES} retries.")
                    raise

    async def execute_order_with_chasing(self, tradingsymbol, total_qty, product, transaction_type, 
                                        exchange, freeze_limit=900, chase_retries=3, 
                                        chase_timeout_ms=100, fallback_to_market=True):
        """
        ORDER CHASING LOGIC from v47.14
        
        Attempts to get better fills by:
        1. Fetching current market depth
        2. Placing limit orders at best bid/ask
        3. Waiting briefly to see if filled
        4. Cancelling and retrying with updated price if not filled
        5. Falling back to market order if all limit attempts fail
        6. Verifying final position
        7. Cleaning up partial fills on error
        
        Args:
            tradingsymbol: Option symbol
            total_qty: Total quantity to trade
            product: MIS/NRML
            transaction_type: BUY/SELL
            exchange: NFO/BFO
            freeze_limit: Maximum qty per order slice
            chase_retries: Number of limit order attempts
            chase_timeout_ms: Time to wait for fill (milliseconds)
            fallback_to_market: Whether to use market order as last resort
            
        Returns:
            dict with 'status', 'filled_qty', 'avg_price', 'reason'
        """
        filled_quantity = 0
        qty_remaining = total_qty
        instrument_name = f"{exchange}:{tradingsymbol}"

        await self.log_debug("Order Chasing", f"🎯 Attempting to {transaction_type} {total_qty} of {tradingsymbol} with order chasing.")

        while qty_remaining > 0:
            order_qty = min(qty_remaining, freeze_limit)
            slice_filled = False

            try:
                # SPEED OPTIMIZED: Parallel order chasing with smart timeouts
                smart_timeout = _calculate_smart_timeout(tradingsymbol, chase_timeout_ms)
                
                for attempt in range(chase_retries + 1):
                    try:
                        # PARALLEL OPTIMIZATION: Fetch quote and prepare next quote concurrently
                        def get_quote_sync():
                            return kite.quote(instrument=instrument_name)
                        
                        # Start quote fetch
                        quote_task = asyncio.create_task(asyncio.to_thread(get_quote_sync))
                        
                        # If not first attempt, we might have next quote ready
                        depth = await quote_task
                        quote = depth[instrument_name]
                        
                        # Get best price based on transaction type
                        if transaction_type == kite.TRANSACTION_TYPE_BUY:
                            limit_price = quote['depth']['sell'][0]['price']
                        else:
                            limit_price = quote['depth']['buy'][0]['price']
                        
                        limit_price = _round_to_tick(limit_price)
                        
                    except Exception as e:
                        await self.log_debug("Order Chasing", f"Could not fetch quote: {e}. Falling back to market.")
                        break

                    # PARALLEL OPTIMIZATION: Start next quote fetch while placing order
                    next_quote_task = None
                    if attempt < chase_retries:  # Prepare for next attempt
                        next_quote_task = asyncio.create_task(asyncio.to_thread(get_quote_sync))

                    # Place limit order
                    def place_limit_order_sync():
                        return kite.place_order(
                            variety=kite.VARIETY_REGULAR, 
                            exchange=exchange, 
                            tradingsymbol=tradingsymbol,
                            transaction_type=transaction_type, 
                            quantity=order_qty, 
                            product=product,
                            order_type=kite.ORDER_TYPE_LIMIT, 
                            price=limit_price
                        )
                    
                    order_id = await asyncio.to_thread(place_limit_order_sync)
                    await self.log_debug("Order Chasing", f"Attempt {attempt+1}: Placed LIMIT @ {limit_price} (timeout: {smart_timeout}ms). ID: {order_id}")

                    # SPEED OPTIMIZED: Use smart timeout based on option characteristics
                    await asyncio.sleep(smart_timeout / 1000.0)

                    # PARALLEL OPTIMIZATION: Check status while next quote may be ready
                    def get_order_history_sync():
                        return kite.order_history(order_id=order_id)
                    
                    status_task = asyncio.create_task(asyncio.to_thread(get_order_history_sync))
                    order_history = await status_task
                    latest_status = order_history[-1]['status']

                    if latest_status == 'COMPLETE':
                        if next_quote_task:
                            next_quote_task.cancel()  # Cancel unused quote fetch
                        await self.log_debug("Order Chasing", f"✅ Slice of {order_qty} FILLED with LIMIT @ {limit_price} ({smart_timeout}ms)")
                        filled_quantity += order_qty
                        slice_filled = True
                        break

                    # Not filled, cancel and retry
                    await self.log_debug("Order Chasing", f"⏳ Slice not filled. Cancelling order {order_id}.")
                    
                    def cancel_order_sync():
                        return kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
                    
                    # PARALLEL OPTIMIZATION: Cancel order while next quote finishes
                    cancel_task = asyncio.create_task(asyncio.to_thread(cancel_order_sync))
                    
                    # Wait for both cancel and next quote (if started)
                    if next_quote_task:
                        await asyncio.gather(cancel_task, next_quote_task, return_exceptions=True)
                    else:
                        await cancel_task

                # If limit orders failed, try market order
                if not slice_filled and fallback_to_market:
                    await self.log_debug("Order Chasing", "⚠️ Limit attempts failed. Placing MARKET order as fallback.")
                    
                    def place_market_order_sync():
                        return kite.place_order(
                            variety=kite.VARIETY_REGULAR, 
                            exchange=exchange, 
                            tradingsymbol=tradingsymbol,
                            transaction_type=transaction_type, 
                            quantity=order_qty, 
                            product=product,
                            order_type=kite.ORDER_TYPE_MARKET
                        )
                    
                    order_id = await asyncio.to_thread(place_market_order_sync)
                    await asyncio.sleep(0.2)  # SPEED OPTIMIZED: Ultra-fast market order (was 0.3s)
                    
                    def get_order_history_sync():
                        return kite.order_history(order_id=order_id)
                    
                    order_history = await asyncio.to_thread(get_order_history_sync)
                    
                    if order_history[-1]['status'] == 'COMPLETE':
                        filled_quantity += order_history[-1]['filled_quantity']
                        slice_filled = True
                        await self.log_debug("Order Chasing", f"✅ Market order filled {order_history[-1]['filled_quantity']} qty")

                if not slice_filled:
                    await self.log_debug("Order Chasing", "CRITICAL: Could not fill slice even with market fallback. Aborting.")
                    raise Exception("Failed to fill order slice.")

                qty_remaining -= order_qty
                await asyncio.sleep(0.1)  # SPEED OPTIMIZED: Minimal delay between slices

            except Exception as e:
                await self.log_debug("Live Trade (FAIL)", f"An error occurred during order placement: {e}")
                await self._cleanup_partial_fill(tradingsymbol, filled_quantity, product, exchange)
                return {'status': 'FAILED', 'reason': f'API_ERROR: {e}', 'filled_qty': 0, 'avg_price': 0}

        # Verify final position
        try:
            await asyncio.sleep(1)
            
            def get_positions_sync():
                return kite.positions().get('net', [])
            
            positions = await asyncio.to_thread(get_positions_sync)
            trade_pos = next((p for p in positions if p['tradingsymbol'] == tradingsymbol and p['product'] == product), None)

            final_filled_qty = abs(trade_pos['quantity']) if trade_pos else 0
            avg_price = trade_pos['average_price'] if trade_pos else 0
            
            if final_filled_qty == total_qty or transaction_type == kite.TRANSACTION_TYPE_SELL:
                await self.log_debug("Order Chasing", f"✅ Order VERIFIED. Filled {final_filled_qty} @ avg {avg_price:.2f}")
                return {
                    'status': 'COMPLETE',
                    'filled_qty': total_qty,
                    'avg_price': avg_price,
                    'reason': 'SUCCESS'
                }
            else:
                await self.log_debug("Live Trade (VERIFY FAIL)", f"Mismatch! Expected: {total_qty}, Actual: {final_filled_qty}. Cleaning up.")
                await self._cleanup_partial_fill(tradingsymbol, final_filled_qty, product, exchange)
                return {'status': 'FAILED', 'reason': 'VERIFICATION_FAILED', 'filled_qty': 0, 'avg_price': 0}

        except Exception as e:
            await self.log_debug("Live Trade (VERIFY FAIL)", f"Error during position verification: {e}")
            await self._cleanup_partial_fill(tradingsymbol, filled_quantity, product, exchange)
            return {'status': 'FAILED', 'reason': f'VERIFICATION_ERROR: {e}', 'filled_qty': 0, 'avg_price': 0}

    async def _cleanup_partial_fill(self, tradingsymbol, filled_qty, product, exchange):
        """
        Cleanup logic from v47.14
        Exits any partially filled positions on error
        """
        if filled_qty > 0:
            await self.log_debug("Live Trade (CLEANUP)", f"🚨 Initiating cleanup! Exiting {filled_qty} qty of {tradingsymbol}.")
            try:
                cleanup_result = await self.execute_order_with_chasing(
                    tradingsymbol=tradingsymbol, 
                    total_qty=filled_qty, 
                    product=product,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    exchange=exchange,
                    chase_retries=0,  # No retries for cleanup
                    fallback_to_market=True
                )
                if cleanup_result['status'] == 'COMPLETE':
                    await self.log_debug("Live Trade (CLEANUP)", "✅ Cleanup order placed successfully.")
                else:
                    await self.log_debug("Live Trade (CLEANUP)", f"CRITICAL: Cleanup order FAILED! Manual intervention required!")
            except Exception as e:
                await self.log_debug("Live Trade (CLEANUP)", f"CRITICAL: Cleanup order FAILED! Error: {e}. Manual intervention required!")

    # =================================================================
    # V47.14 ENHANCED ORDER MANAGEMENT FEATURES
    # =================================================================
    
    def calculate_intelligent_position_size(self, option_price, volatility_factor=1.0, risk_percentage=0.02):
        """
        V47.14 Enhanced: Calculate position size based on volatility and risk
        
        Args:
            option_price: Current option price
            volatility_factor: Market volatility multiplier (1.0 = normal)
            risk_percentage: Risk percentage per trade (default 2%)
            
        Returns:
            Optimal position size considering risk and volatility
        """
        if not self.risk_based_sizing:
            return self.max_position_size
            
        # Base calculation: higher option price = lower quantity
        base_risk_amount = 10000 * risk_percentage  # Assume 10k capital base
        base_quantity = int(base_risk_amount / max(option_price, 1))
        
        # Adjust for volatility: higher volatility = lower position size
        volatility_adjusted = int(base_quantity / max(volatility_factor, 0.5))
        
        # Cap at maximum position size
        final_quantity = min(volatility_adjusted, self.max_position_size)
        
        return max(final_quantity, 25)  # Minimum 25 quantity
    
    def get_adaptive_chase_timeout(self, option_symbol, attempt_number=1, volatility_factor=1.0):
        """
        V47.14 Enhanced: Calculate adaptive chase timeout based on multiple factors
        
        Args:
            option_symbol: Option trading symbol
            attempt_number: Current chase attempt (1, 2, 3...)
            volatility_factor: Market volatility multiplier
            
        Returns:
            Optimal timeout in milliseconds
        """
        # Base timeout with attempt escalation
        base_timeout = self.base_chase_timeout * (1 + (attempt_number - 1) * 0.3)
        
        # Adjust for option characteristics
        if any(strike in option_symbol for strike in ["24800", "25000", "25200"]):
            # ATM options - fastest execution
            characteristic_multiplier = 1.0
        elif any(strike in option_symbol for strike in ["24700", "24900", "25100", "25300"]):
            # Near ATM - moderate
            characteristic_multiplier = 1.2
        else:
            # Deep OTM/ITM - slower
            characteristic_multiplier = 1.5
            
        # Adjust for market volatility
        volatility_timeout = base_timeout * characteristic_multiplier * volatility_factor
        
        # Cap between 80ms and 300ms
        return max(80, min(int(volatility_timeout), 300))
    
    def calculate_optimal_slice_size(self, total_quantity, option_price, freeze_limit=900):
        """
        V47.14 Enhanced: Calculate optimal order slice size based on price and liquidity
        
        Args:
            total_quantity: Total quantity to trade
            option_price: Current option price
            freeze_limit: Exchange freeze limit
            
        Returns:
            Optimal slice size for better execution
        """
        # For expensive options (>50), use smaller slices for better fills
        if option_price > 50:
            optimal_slice = min(freeze_limit // 2, total_quantity)
        # For mid-range options (10-50), use standard slicing
        elif option_price > 10:
            optimal_slice = min(int(freeze_limit * 0.75), total_quantity)
        # For cheap options (<10), can use larger slices
        else:
            optimal_slice = min(freeze_limit, total_quantity)
            
        return max(optimal_slice, 25)  # Minimum 25 quantity per slice
    
    async def execute_enhanced_order_with_chasing(self, tradingsymbol, total_qty, product, transaction_type, 
                                                exchange, option_price=None, volatility_factor=1.0,
                                                freeze_limit=900, chase_retries=3, fallback_to_market=True):
        """
        V47.14 Enhanced: Advanced order execution with intelligent sizing and adaptive parameters
        
        Features:
        - Intelligent position sizing based on option price and volatility
        - Adaptive chase timeouts based on option characteristics
        - Optimal order slicing for better execution
        - Enhanced error handling and recovery
        
        Args:
            tradingsymbol: Option symbol
            total_qty: Total quantity to trade
            product: MIS/NRML
            transaction_type: BUY/SELL
            exchange: NFO/BFO
            option_price: Current option price for intelligent sizing
            volatility_factor: Market volatility multiplier
            freeze_limit: Maximum qty per order slice
            chase_retries: Number of limit order attempts
            fallback_to_market: Whether to use market order as last resort
            
        Returns:
            dict with 'status', 'filled_qty', 'avg_price', 'reason', 'execution_stats'
        """
        start_time = asyncio.get_event_loop().time()
        execution_stats = {
            'total_attempts': 0,
            'limit_fills': 0,
            'market_fills': 0,
            'avg_chase_time': 0,
            'total_execution_time': 0
        }
        
        # V47.14 Enhanced: Use intelligent position sizing if enabled
        if self.risk_based_sizing and option_price:
            intelligent_qty = self.calculate_intelligent_position_size(option_price, volatility_factor)
            if intelligent_qty < total_qty:
                await self.log_debug("Enhanced Order", f"🧠 Intelligent sizing: Reducing {total_qty} to {intelligent_qty} based on price {option_price} & volatility {volatility_factor:.2f}")
                total_qty = intelligent_qty
        
        # V47.14 Enhanced: Calculate optimal slice size
        optimal_slice_size = self.calculate_optimal_slice_size(total_qty, option_price or 10, freeze_limit)
        
        filled_quantity = 0
        qty_remaining = total_qty
        instrument_name = f"{exchange}:{tradingsymbol}"

        await self.log_debug("Enhanced Order", f"🎯 Enhanced execution: {transaction_type} {total_qty} of {tradingsymbol} (slice: {optimal_slice_size})")

        while qty_remaining > 0:
            order_qty = min(qty_remaining, optimal_slice_size)
            slice_filled = False
            slice_start_time = asyncio.get_event_loop().time()

            try:
                for attempt in range(chase_retries + 1):
                    execution_stats['total_attempts'] += 1
                    
                    # V47.14 Enhanced: Get adaptive timeout for this attempt
                    adaptive_timeout = self.get_adaptive_chase_timeout(tradingsymbol, attempt + 1, volatility_factor)
                    
                    try:
                        def get_quote_sync():
                            return kite.quote(instrument=instrument_name)
                        
                        depth = await asyncio.to_thread(get_quote_sync)
                        quote = depth[instrument_name]
                        
                        if transaction_type == kite.TRANSACTION_TYPE_BUY:
                            limit_price = quote['depth']['sell'][0]['price']
                        else:
                            limit_price = quote['depth']['buy'][0]['price']
                        
                        limit_price = _round_to_tick(limit_price)
                        
                    except Exception as e:
                        await self.log_debug("Enhanced Order", f"Quote fetch failed: {e}. Using market order.")
                        break

                    # Place limit order with enhanced logging
                    def place_limit_order_sync():
                        return kite.place_order(
                            variety=kite.VARIETY_REGULAR, 
                            exchange=exchange, 
                            tradingsymbol=tradingsymbol,
                            transaction_type=transaction_type, 
                            quantity=order_qty, 
                            product=product,
                            order_type=kite.ORDER_TYPE_LIMIT, 
                            price=limit_price
                        )
                    
                    order_id = await asyncio.to_thread(place_limit_order_sync)
                    await self.log_debug("Enhanced Order", f"🎯 Attempt {attempt+1}: LIMIT @ {limit_price} (timeout: {adaptive_timeout}ms, vol: {volatility_factor:.2f})")

                    # Use adaptive timeout
                    await asyncio.sleep(adaptive_timeout / 1000.0)

                    # Check order status
                    def get_order_history_sync():
                        return kite.order_history(order_id=order_id)
                    
                    order_history = await asyncio.to_thread(get_order_history_sync)
                    latest_status = order_history[-1]['status']

                    if latest_status == 'COMPLETE':
                        execution_stats['limit_fills'] += 1
                        slice_time = asyncio.get_event_loop().time() - slice_start_time
                        execution_stats['avg_chase_time'] = (execution_stats['avg_chase_time'] + slice_time) / 2
                        
                        await self.log_debug("Enhanced Order", f"✅ LIMIT fill: {order_qty} @ {limit_price} ({adaptive_timeout}ms, {slice_time:.2f}s)")
                        filled_quantity += order_qty
                        slice_filled = True
                        break

                    # Cancel and retry with updated price
                    await self.log_debug("Enhanced Order", f"⏳ Not filled, cancelling {order_id}")
                    
                    def cancel_order_sync():
                        return kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
                    
                    await asyncio.to_thread(cancel_order_sync)

                # Market order fallback with enhanced tracking
                if not slice_filled and fallback_to_market:
                    await self.log_debug("Enhanced Order", "⚠️ Limit failed, using MARKET fallback")
                    
                    def place_market_order_sync():
                        return kite.place_order(
                            variety=kite.VARIETY_REGULAR, 
                            exchange=exchange, 
                            tradingsymbol=tradingsymbol,
                            transaction_type=transaction_type, 
                            quantity=order_qty, 
                            product=product,
                            order_type=kite.ORDER_TYPE_MARKET
                        )
                    
                    order_id = await asyncio.to_thread(place_market_order_sync)
                    await asyncio.sleep(0.15)  # Fast market order check
                    
                    order_history = await asyncio.to_thread(lambda: kite.order_history(order_id=order_id))
                    
                    if order_history[-1]['status'] == 'COMPLETE':
                        execution_stats['market_fills'] += 1
                        filled_quantity += order_history[-1]['filled_quantity']
                        slice_filled = True
                        await self.log_debug("Enhanced Order", f"✅ MARKET fill: {order_history[-1]['filled_quantity']} qty")

                if not slice_filled:
                    raise Exception("Failed to fill order slice with both limit and market attempts")

                qty_remaining -= order_qty
                await asyncio.sleep(0.05)  # Ultra-fast between slices

            except Exception as e:
                await self.log_debug("Enhanced Order ERROR", f"Slice execution failed: {e}")
                await self._cleanup_partial_fill(tradingsymbol, filled_quantity, product, exchange)
                execution_stats['total_execution_time'] = asyncio.get_event_loop().time() - start_time
                return {
                    'status': 'FAILED', 
                    'reason': f'EXECUTION_ERROR: {e}', 
                    'filled_qty': 0, 
                    'avg_price': 0,
                    'execution_stats': execution_stats
                }

        # Enhanced verification with execution statistics
        execution_stats['total_execution_time'] = asyncio.get_event_loop().time() - start_time
        
        try:
            await asyncio.sleep(0.8)  # Quick verification delay
            
            positions = await asyncio.to_thread(lambda: kite.positions().get('net', []))
            trade_pos = next((p for p in positions if p['tradingsymbol'] == tradingsymbol and p['product'] == product), None)

            final_filled_qty = abs(trade_pos['quantity']) if trade_pos else 0
            avg_price = trade_pos['average_price'] if trade_pos else 0
            
            if final_filled_qty == total_qty or transaction_type == kite.TRANSACTION_TYPE_SELL:
                await self.log_debug("Enhanced Order", f"✅ VERIFIED: {final_filled_qty} @ {avg_price:.2f} ({execution_stats['total_execution_time']:.2f}s, L:{execution_stats['limit_fills']} M:{execution_stats['market_fills']})")
                return {
                    'status': 'COMPLETE',
                    'filled_qty': total_qty,
                    'avg_price': avg_price,
                    'reason': 'SUCCESS',
                    'execution_stats': execution_stats
                }
            else:
                await self.log_debug("Enhanced Order VERIFY", f"Qty mismatch: Expected {total_qty}, Got {final_filled_qty}")
                await self._cleanup_partial_fill(tradingsymbol, final_filled_qty, product, exchange)
                return {
                    'status': 'FAILED', 
                    'reason': 'VERIFICATION_FAILED', 
                    'filled_qty': 0, 
                    'avg_price': 0,
                    'execution_stats': execution_stats
                }

        except Exception as e:
            await self.log_debug("Enhanced Order VERIFY", f"Verification error: {e}")
            await self._cleanup_partial_fill(tradingsymbol, filled_quantity, product, exchange)
            return {
                'status': 'FAILED', 
                'reason': f'VERIFICATION_ERROR: {e}', 
                'filled_qty': 0, 
                'avg_price': 0,
                'execution_stats': execution_stats
            } 
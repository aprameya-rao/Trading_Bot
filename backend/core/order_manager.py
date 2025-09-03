import asyncio
from core.kite import kite

class OrderManager:
    """
    Handles the execution and verification of orders to make them more robust.
    """
    def __init__(self, log_debug_func):
        self.log_debug = log_debug_func

    async def execute_order(self, transaction_type, **kwargs):
        """
        Places an order and then enters a loop to verify its status.
        Retries on rejection and times out if it's stuck in a pending state.
        Returns the final status or raises an exception on failure.
        """
        MAX_RETRIES = 3
        RETRY_DELAY_SECONDS = 2
        VERIFICATION_TIMEOUT_SECONDS = 15

        for attempt in range(MAX_RETRIES):
            try:
                # --- 1. Place the initial order ---
                def place_order_sync():
                    return kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        order_type=kite.ORDER_TYPE_MARKET,
                        product=kite.PRODUCT_MIS,
                        transaction_type=transaction_type,
                        autoslice=True,
                        **kwargs
                    )
                
                order_id = await asyncio.to_thread(place_order_sync)
                await self.log_debug("OrderManager", f"Placed {transaction_type} order for {kwargs.get('tradingsymbol')}. Order ID: {order_id}. Verifying status...")

                # --- 2. Verify the order status ---
                start_time = asyncio.get_event_loop().time()
                while True:
                    # Check for timeout
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
                            break # Breaks the inner while loop to trigger a retry

                    await asyncio.sleep(1) # Wait 1 second before checking status again
            
            except Exception as e:
                await self.log_debug("OrderManager-ERROR", f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                else:
                    await self.log_debug("OrderManager-CRITICAL", f"Order for {kwargs.get('tradingsymbol')} failed after {MAX_RETRIES} retries.")
                    raise  # Re-raise the final exception to be handled by the strategy
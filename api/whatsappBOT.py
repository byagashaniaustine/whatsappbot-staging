import logging

from services.meta import send_kopagari_message
from api.decision import handle_text_message

logger = logging.getLogger("whatsapp_app")
logger.setLevel(logging.DEBUG)


def calculate_loan(principal: float, duration: int, rate: float):
    """
    Calculate monthly payment, total payment, and total interest for a loan.
    """
    if duration <= 0 or principal <= 0:
        raise ValueError("Principal and duration must be positive.")
        
    monthly_rate_decimal = rate / 100.0
    
    if monthly_rate_decimal == 0:
        monthly_payment = principal / duration
    else:
        n = duration
        i = monthly_rate_decimal
        # Amortization Formula: M = P [ i(1 + i)^n ] / [ (1 + i)^n – 1]
        denominator = (1 + i)**n - 1
        if denominator == 0:
             monthly_payment = principal / duration
        else:
            numerator = i * (1 + i)**n
            monthly_payment = principal * (numerator / denominator)

    total_payment = monthly_payment * duration
    total_interest = total_payment - principal
    
    return monthly_payment, total_payment, total_interest


def calculate_loan_results(user_data: dict):
    """
    Generate Flow UI response for loan calculation results.
    """
    # Retrieve Input Data
    principal = float(user_data.get("principal", 0))
    duration = int(user_data.get("duration", 0))
    rate = float(user_data.get("rate", 0))
    from_number = str(user_data.get("from_number") or "") 
    
    logger.critical(f"✅ Executing Loan Calculation: P={principal}, D={duration}, R={rate} user: {from_number}")

    # Perform Calculation
    try:
        monthly_payment, total_payment, total_interest = calculate_loan(principal, duration, rate)
    except ValueError as e:
        logger.error(f"❌ Calculation failed due to bad input: {e}")
        return {"screen": "MAIN_MENU", "data": {"error": "Invalid input"}}

    # Format and Return Flow Response (for the Flow UI)
    response_screen = {
        "screen": "LOAN_RESULT", 
        "data": {
            "principal": f"{principal:,.0f}",  
            "duration": str(duration),
            "rate": str(rate),
            "monthly_payment": f"{monthly_payment:,.0f}",
            "total_payment": f"{total_payment:,.0f}",
            "total_interest": f"{total_interest:,.0f}"
        }
    }
    
    logger.critical(f"Flow routing answer: {response_screen} ➡️ Calculation Complete. Ready to route to LOAN_RESULT.")
    return response_screen

async def whatsapp_menu(payload: dict):
    """
    Entry point for incoming text messages.
    Delegates to the agentic decision layer (intent → route → execute).
    Payload: {"from_number": "+...", "body": "...", "user_name": "..."}
    """
    from_number = payload.get("from_number")
    user_text = payload.get("body")
    user_name = payload.get("user_name", "")

    if not from_number or not user_text:
        logger.error("❌ whatsapp_menu received incomplete payload.")
        return

    if not from_number.startswith("+"):
        from_number = "+" + from_number

    logger.critical(f"📱 whatsapp_menu → decision layer: {from_number} | {user_text}")

    try:
        await handle_text_message(from_number, user_text, user_name)
    except Exception as e:
        logger.error(f"❌ Decision layer error: {e}", exc_info=True)
        await send_kopagari_message(
            from_number,
            "Samahani, tatizo limetokea. Tafadhali jaribu tena."
        )

       

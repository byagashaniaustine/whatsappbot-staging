import uuid
import logging

from services.intent import analyze_intent
from services.claude_response import get_claude_response
from services.car_search import search_listings, format_listings_for_whatsapp
from services.magari_scout import fetch_on_demand, fetch_on_demand_background
from services.meta import send_kopagari_message, send_kopagari_mtaa_template
from services.supabase import store_session_data
from services.conversation import get_history, save_turn, clear_history

logger = logging.getLogger("whatsapp_app")


async def handle_text_message(from_number: str, user_text: str, user_name: str = ""):
    """
    Decision layer for incoming text messages.
    1. Calls the intent analyzer (Claude Haiku).
    2. Routes to the correct execution path based on intent.
    """
    intent_result = await analyze_intent(user_text)
    intent = intent_result.get("intent", "unknown")
    confidence = intent_result.get("confidence", 0.0)

    # Load conversation history for this phone number
    history = get_history(from_number)

    logger.critical(f"🧭 Decision: intent={intent} confidence={confidence} user={from_number} history={len(history)} msgs")

    # --- Execution paths ---

    if intent == "flow_initiation":
        token = str(uuid.uuid4())
        await store_session_data(phone_number=from_number, message=user_text, session_id=token)
        clear_history(from_number)   # fresh start on menu/greeting
        reply = (
            "Habari! Mimi ni Kulwa, msaidizi wako kutoka Kopagari.\n\n"
            "Tunakusaidia kupata mkopo wa kununua gari wa hadi milioni 100. Ukiwa na namba ya NIDA na bank statement za miezi 6, unaweza kujua kama unastahili ndani ya dakika 5 tu, bila malipo.\n\n"
            "Je ungependa nikuongoze hatua kwa hatua?"
        )
        await send_kopagari_message(from_number, reply)
        save_turn(from_number, user_text, reply)
        logger.critical(f"✅ Flow initiation reply sent to {from_number}")

    elif intent == "loan_services_menu":
        token = str(uuid.uuid4())
        await store_session_data(phone_number=from_number, message=user_text, session_id=token)
        await send_kopagari_mtaa_template(to=from_number)
        logger.critical(f"✅ Loan services template sent to {from_number}")

    elif intent == "car_inquiry":
        entities = intent_result.get("entities", {})
        make  = (entities.get("make") or "").strip()
        model = (entities.get("model") or "").strip()

        # strip make prefix from model if Claude included it (e.g. "Toyota Vitz" → "Vitz")
        if make and model.lower().startswith(make.lower()):
            model = model[len(make):].strip()

        # 1. Query live listings from Supabase
        live_listings = search_listings(user_text, limit=5)

        # Filter to only listings that match the queried make AND model
        if live_listings:
            live_listings = [
                l for l in live_listings
                if (not make  or make.lower()  in (l.get("make")  or "").lower())
                and (not model or model.lower() in (l.get("model") or "").lower())
            ]

        # 2. If nothing relevant in DB, fire background scout + respond immediately
        if not live_listings and make:
            await fetch_on_demand_background(make=make, model=model)
            logger.critical(f"🚀 Background scout fired for '{make} {model}' — responding from general knowledge")

        live_text = format_listings_for_whatsapp(live_listings)

        # 3. Build enriched prompt with live data if available
        if live_text:
            enriched_query = (
                f"{user_text}\n\n"
                f"[Magari yaliyopatikana kwenye database yetu sasa hivi:]\n{live_text}"
            )
            logger.critical(f"🚗 Injecting {len(live_listings)} live listings for {from_number}")
        else:
            enriched_query = user_text
            logger.critical(f"🚗 No DB listings — using general knowledge (scout running in background)")

        reply = await get_claude_response(enriched_query, user_name, history=history)
        await send_kopagari_message(from_number, reply)
        save_turn(from_number, user_text, reply)
        logger.critical(f"✅ Car inquiry answered for {from_number}")

    elif intent in ("car_import_cost", "loan_question", "faq", "loan_calculation"):
        reply = await get_claude_response(user_text, user_name, history=history)
        await send_kopagari_message(from_number, reply)
        save_turn(from_number, user_text, reply)
        logger.critical(f"✅ Claude answer sent to {from_number} for intent={intent}")

    elif intent == "document_upload_reminder":
        reply = (
            "Tafadhali tuma PDF ya taarifa yako ya benki moja kwa moja hapa. "
            "Mfumo wetu utaifanya uchambuzi wa uwezo wako wa kukopa. 📄"
        )
        await send_kopagari_message(from_number, reply)
        save_turn(from_number, user_text, reply)
        logger.critical(f"✅ Document upload reminder sent to {from_number}")

    elif intent in ("general_conversation", "unknown"):
        # Let Claude handle conversationally using history for context
        reply = await get_claude_response(user_text, user_name, history=history)
        await send_kopagari_message(from_number, reply)
        save_turn(from_number, user_text, reply)
        logger.critical(f"✅ Conversational reply sent to {from_number} for intent={intent}")

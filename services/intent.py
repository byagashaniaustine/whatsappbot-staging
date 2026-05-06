import os
import json
import logging
import anthropic

logger = logging.getLogger("whatsapp_app")

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


INTENT_SYSTEM_PROMPT = """
You are an intent classifier for a Tanzanian WhatsApp assistant for Kopagari — a used car sales and financing platform in Tanzania.
Users write in Swahili or English.

Classify the user's message into exactly one of these intents:
- "flow_initiation": greetings or menu triggers (hi, hello, menu, mambo, anza, hola, start, hey, vipi, salam, niambie, mwanzo, vp)
- "car_inquiry": user asks about car prices, car types, availability, specific make/model (e.g. "Toyota Vitz bei gani?", "mnauza Noah?", "Land Cruiser ipo?", "magari gani mna?", "Hilux price?", "duty paid cars", "cars under 20 million")
- "car_import_cost": user wants to know import costs, CIF price, TRA taxes, duty calculation for a specific car
- "loan_services_menu": user asks about available loan/financing services, car loan options, mkopo wa gari
- "loan_question": specific question about loan rates, eligibility, how to apply, loan terms
- "loan_calculation": user wants to calculate loan repayment — has amounts or durations in message
- "document_upload_reminder": user asks how/where to send documents, bank statements, affordability check
- "faq": general question about Kopagari as a company, what it does, how it works
- "general_conversation": any other conversational message — thank you, follow-ups, small talk, short replies ("sawa", "asante", "okay", "hiyo ni ghali", "ndiyo", "hapana"), questions that don't fit above
- "unknown": truly unclassifiable or spam

When in doubt between "unknown" and "general_conversation", always choose "general_conversation".

Respond ONLY with valid JSON and nothing else:
{"intent": "<intent>", "confidence": <float 0-1>, "entities": {"make": "<car make or null>", "model": "<car model or null>", "year": "<year or null>"}}
"""


async def analyze_intent(text: str) -> dict:
    """
    Send user text to Claude Haiku and return a structured intent classification.
    Falls back to {"intent": "unknown"} on any error.
    """
    try:
        client = _get_client()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present (```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        logger.info(f"🧠 Intent analysis: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Intent analysis failed: {e}")
        return {"intent": "unknown", "confidence": 0.0, "entities": {}}

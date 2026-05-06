"""
Query Supabase car_listings table to find live car listings for user queries.
"""
import logging
import re

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("car_search")

# Common make aliases
MAKE_ALIASES = {
    "toyota": "Toyota", "nissan": "Nissan", "honda": "Honda",
    "mitsubishi": "Mitsubishi", "subaru": "Subaru", "mazda": "Mazda",
    "mercedes": "Mercedes", "bmw": "BMW", "land cruiser": "Toyota",
    "hilux": "Toyota", "vitz": "Toyota", "noah": "Toyota",
    "fielder": "Toyota", "probox": "Toyota", "premio": "Toyota",
    "allion": "Toyota", "wish": "Toyota", "rav4": "Toyota",
    "note": "Nissan", "tiida": "Nissan", "x-trail": "Nissan",
    "fit": "Honda", "vezel": "Honda", "freed": "Honda",
    "demio": "Mazda", "axela": "Mazda",
    "forester": "Subaru", "impreza": "Subaru",
    "canter": "Mitsubishi", "l200": "Mitsubishi",
}

MODEL_KEYWORDS = [
    "vitz", "fielder", "probox", "noah", "voxy", "alphard", "prado",
    "land cruiser", "hilux", "rav4", "wish", "premio", "allion", "sienta",
    "fortuner", "harrier", "kluger", "surf", "rush", "aqua", "axio",
    "note", "tiida", "x-trail", "xtrail", "serena", "navara", "juke",
    "fit", "vezel", "freed", "crv",
    "demio", "axela", "cx-5", "cx5",
    "forester", "impreza", "outback",
    "canter", "dyna", "l200", "pajero", "outlander",
    "x1", "x3", "x5", "x6",
    "defender", "discovery", "evoque", "range rover",
]


def _parse_query(user_text: str) -> dict:
    """Extract make, model, max_price, segment hints from free text."""
    text = user_text.lower()
    filters = {}

    # Detect make
    for alias, make in MAKE_ALIASES.items():
        if alias in text:
            filters["make"] = make
            break

    # Detect model
    for model in MODEL_KEYWORDS:
        if model in text:
            filters["model"] = model.title()
            break

    # Detect price ceiling (e.g. "under 20 million", "chini ya 15M")
    price_match = re.search(
        r"(?:under|chini ya|below|less than)\s*(\d+)\s*(?:million|milioni|M|m\b)", text
    )
    if price_match:
        filters["max_price_tsh"] = int(price_match.group(1)) * 1_000_000

    # Detect duty status
    if "duty paid" in text or " dp " in text or text.endswith(" dp"):
        filters["duty_status"] = "Duty Paid"
    elif "duty not paid" in text or " dnp " in text:
        filters["duty_status"] = "Duty Not Paid"

    # Detect segment
    if any(w in text for w in ["luxury", "range rover", "land cruiser", "mercedes", "bmw", "lexus"]):
        filters["segment"] = "luxury"
    elif any(w in text for w in ["truck", "pickup", "hilux", "l200", "canter"]):
        filters["segment"] = "trucks"
    elif any(w in text for w in ["bus", "coaster", "hiace", "rosa"]):
        filters["segment"] = "buses"

    return filters


def search_listings(user_text: str, limit: int = 5) -> list[dict]:
    """
    Search car_listings in Supabase based on the user's query text.
    Priority listings surface first, then most recently scraped.
    Returns up to `limit` matching listings.
    """
    try:
        from services.supabase import supabase

        filters = _parse_query(user_text)
        logger.info(f"🔍 Car search filters: {filters}")

        query = supabase.table("car_listings").select(
            "make, model, year, price_tsh, price_original, transmission, "
            "mileage_km, fuel_type, engine_cc, color, duty_status, "
            "features, contact, region, post_url, summary, segment, is_priority"
        )

        if "make" in filters:
            query = query.ilike("make", f"%{filters['make']}%")
        if "model" in filters:
            query = query.ilike("model", f"%{filters['model']}%")
        if "duty_status" in filters:
            query = query.eq("duty_status", filters["duty_status"])
        # Only apply segment filter when no specific model was identified —
        # segment assignment on scraped rows may differ from query inference
        if "segment" in filters and "model" not in filters:
            query = query.eq("segment", filters["segment"])
        if "max_price_tsh" in filters:
            query = query.lte("price_tsh", filters["max_price_tsh"])

        result = query.order("is_priority", desc=True).order("scraped_at", desc=True).limit(limit).execute()
        listings = result.data or []
        logger.info(f"✅ Found {len(listings)} listings")
        return listings

    except Exception as e:
        logger.error(f"❌ car_search failed: {e}")
        return []


def format_listings_for_whatsapp(listings: list[dict]) -> str:
    """Format Supabase listings into a concise WhatsApp-friendly string."""
    if not listings:
        return ""

    lines = []
    for car in listings:
        make    = car.get("make", "")
        model   = car.get("model", "")
        year    = car.get("year", "")
        price   = car.get("price_original") or (
            f"{car['price_tsh'] // 1_000_000}M TSH" if car.get("price_tsh") else "Bei TBD"
        )
        duty    = "DP" if car.get("duty_status") == "Duty Paid" else ("DNP" if car.get("duty_status") == "Duty Not Paid" else "")
        km      = f"{car['mileage_km']:,}km" if car.get("mileage_km") else ""
        region  = car.get("region", "")
        contact = car.get("contact", "")

        badge = "⭐ " if car.get("is_priority") else ""
        name  = " ".join(filter(None, [str(year) if year else None, make, model]))
        parts = [f"{badge}🚗 {name}".strip(), f"💰 {price}"]
        if duty:
            parts.append(duty)
        if km:
            parts.append(km)
        if region:
            parts.append(f"📍{region}")
        if contact:
            parts.append(f"📞{contact}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)

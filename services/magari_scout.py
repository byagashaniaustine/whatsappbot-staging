"""
Magari Scout — unified car listing scraper.
Sources:
  1. BE Forward (direct HTML scrape) — imported Japanese cars CIF to Dar es Salaam
  2. CarAPIs / BE Forward API       — fallback if direct scrape fails
  3. Instagram accounts             — local Tanzanian dealer posts

Run via: python scripts/run_scout.py
"""
import os
import re
import json
import logging
import asyncio
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from apify_client import ApifyClient
import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("magari_scout")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_ACCOUNTS: list[str] = [
    "magari_sokoni_tz",
    "magari_used_bei_nafuu",
    "magari_mazuri_tz",
    "magari_mtaani",
    "troni_motors",
    "qfk_motors",
    "danny_motors_tz",
    "pelagy_motors_tz",
    "jaco__motorstz",
    "mgayamotors",
    "mpeta_motorstz",
    "mcimotors",
    "beforwardtz",
]

SEGMENTS = {
    "luxury":   ["Land Cruiser", "Range Rover", "Mercedes", "BMW", "Lexus", "Porsche", "Alphard"],
    "midrange": ["Toyota", "Honda", "Nissan", "Mazda", "Mitsubishi", "Subaru"],
    "budget":   ["Suzuki", "Daihatsu", "Vitz", "Probox", "Fielder", "Ractis"],
    "trucks":   ["Canter", "Dyna", "Hilux", "L200", "pickup", "truck"],
    "buses":    ["Coaster", "Rosa", "Hiace", "Noah", "bus", "van"],
}

# TRA import duty rates
TRA_IMPORT_DUTY = 0.25
TRA_EXCISE = {(0, 1000): 0.0, (1001, 2000): 0.05, (2001, 99999): 0.10}
TRA_EXCISE_SURCHARGE_OLD = 0.25   # cars 8+ years old (non-utility)
TRA_VAT = 0.18
USD_TO_TZS = 2600                 # approximate — update periodically

CAR_EXTRACTION_PROMPT = """
You are a car listing data extractor for the Tanzanian market.
Extract structured vehicle data from this Instagram caption.

Swahili: gari=car, bei=price, milioni/ML/M=million TSH, laki=100k TSH,
mwendo=mileage, DP/duty paid=import duty paid, DNP=duty not paid,
auto/otomatiki=automatic, manual/gear moja moja=manual.

Return ONLY valid JSON (no markdown fences):
{
  "listing_type": "For Sale"|"Wanted"|"",
  "vehicle_type": "Sedan"|"SUV"|"Pickup"|"Van"|"Bus"|"Truck"|"Motorcycle"|"",
  "make": string, "model": string, "year": integer|null,
  "mileage_km": integer|null, "transmission": "Automatic"|"Manual"|"",
  "fuel_type": "Petrol"|"Diesel"|"Hybrid"|"Electric"|"",
  "engine_cc": integer|null, "color": string, "condition": string,
  "location": string, "region": string,
  "price_original": string, "price_tsh": integer|null,
  "price_usd": float|null, "currency": "TSH"|"USD"|null,
  "negotiable": "Negotiable"|"Fixed"|"", "features": string,
  "contact": string, "duty_status": "Duty Paid"|"Duty Not Paid"|"",
  "summary": string
}
If NOT a vehicle for sale post return: null
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _get_segment(make: str, model: str) -> str:
    text = f"{make} {model}".lower()
    for segment, keywords in SEGMENTS.items():
        if any(k.lower() in text for k in keywords):
            return segment
    return "midrange"


def _calculate_tra_taxes(cif_usd: float, engine_cc: int, year: int) -> dict:
    """Calculate TRA import taxes from CIF price (USD)."""
    import datetime
    cif_tzs = cif_usd * USD_TO_TZS

    import_duty = cif_tzs * TRA_IMPORT_DUTY

    excise_rate = 0.0
    for (lo, hi), rate in TRA_EXCISE.items():
        if lo <= (engine_cc or 0) <= hi:
            excise_rate = rate
            break

    age = datetime.datetime.now().year - (year or datetime.datetime.now().year)
    if age >= 8:
        excise_rate += TRA_EXCISE_SURCHARGE_OLD

    excise_base = cif_tzs + import_duty
    excise_duty = excise_base * excise_rate

    vat_base = cif_tzs + import_duty + excise_duty
    vat = vat_base * TRA_VAT

    total_taxes = import_duty + excise_duty + vat
    total_landed = cif_tzs + total_taxes + (400 * USD_TO_TZS)  # +$400 clearing/port

    return {
        "cif_usd": round(cif_usd),
        "cif_tzs": round(cif_tzs),
        "import_duty_tzs": round(import_duty),
        "excise_duty_tzs": round(excise_duty),
        "vat_tzs": round(vat),
        "total_taxes_tzs": round(total_taxes),
        "total_landed_tzs": round(total_landed),
        "total_landed_millions": round(total_landed / 1_000_000, 1),
    }


# ---------------------------------------------------------------------------
# SOURCE 1: BE Forward — direct HTML scraper (CIF to Dar es Salaam)
# ---------------------------------------------------------------------------
BF_BASE = "https://www.beforward.jp"
BF_STOCKLIST = f"{BF_BASE}/stocklist/"

# BE Forward make IDs for stocklist URL parameter
BF_MAKE_IDS: dict[str, int] = {
    "Toyota": 1,
    "Honda": 2,
    "Nissan": 3,
    "Mazda": 4,
    "Mitsubishi": 5,
    "Suzuki": 7,
    "Isuzu": 8,
    "Daihatsu": 10,
    "Subaru": 94,
    "Lexus": 68,
    "Mercedes": 106,
    "BMW": 83,
    "Land Rover": 52,
    "Volkswagen": 48,
    "Hino": 103,
}

BF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_price(text: str) -> Optional[float]:
    """Parse '$5,126' or '5126' → 5126.0"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_engine_cc(text: str) -> Optional[int]:
    """Parse '1,980cc' → 1980"""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*cc", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_mileage(text: str) -> Optional[int]:
    """Parse '178,375 km' → 178375"""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*km", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_year(text: str) -> Optional[int]:
    """Parse '2009/4' or '2009' → 2009"""
    if not text:
        return None
    m = re.match(r"(\d{4})", text.strip())
    return int(m.group(1)) if m else None


def _parse_beforward_row(row, make: str) -> Optional[dict]:
    """Parse a single <tr class='stocklist-row'> into a listing dict."""
    try:
        # Skip SOLD listings
        if row.select_one(".price-col-sold"):
            return None

        # Stock reference number
        ref_el = row.select_one("p.veh-stock-no span")
        ref_no = ref_el.get_text(strip=True).replace("Ref No.", "").strip() if ref_el else ""

        # Detail URL
        link_el = row.select_one("a.vehicle-url-link")
        detail_url = (BF_BASE + link_el["href"]) if link_el and link_el.get("href") else ""

        # Model name (e.g. "2009 TOYOTA VOXY ZS KIRAMEKI")
        model_el = row.select_one("p.make-model a")
        full_title = re.sub(r"\s+", " ", model_el.get_text(strip=True)) if model_el else ""

        # Specs
        year_el  = row.select_one("td.year p.val")
        mile_el  = row.select_one("td.mileage p.val")
        eng_el   = row.select_one("td.engine p.val")
        trans_el = row.select_one("td.trans p.val")

        year = _parse_year(year_el.get_text(strip=True) if year_el else "")
        mileage = _parse_mileage(mile_el.get_text(strip=True) if mile_el else "")
        engine_cc = _parse_engine_cc(eng_el.get_text(strip=True) if eng_el else "")
        transmission_raw = trans_el.get_text(strip=True) if trans_el else ""
        transmission = "Automatic" if "AT" in transmission_raw.upper() else ("Manual" if "MT" in transmission_raw.upper() else transmission_raw)

        # FOB price — <span class="price">$2,770</span>
        fob_el = row.select_one("p.vehicle-price span.price")
        fob_usd = _parse_price(fob_el.get_text(strip=True) if fob_el else "")

        # CIF total price — second span inside p.total-price (first is currency-label)
        total_price_p = row.select_one("p.total-price")
        cif_usd = None
        if total_price_p:
            spans = total_price_p.find_all("span")
            for span in spans:
                val = _parse_price(span.get_text(strip=True))
                if val and val > 0:
                    cif_usd = val
                    break

        # Thumbnail image
        img_el = row.select_one("td.photo-col img")
        img_url = ("https:" + img_el["src"]) if img_el and img_el.get("src", "").startswith("//") else (img_el["src"] if img_el else "")

        if not detail_url or not cif_usd:
            return None

        # TRA tax calculation using CIF price
        taxes = _calculate_tra_taxes(cif_usd, engine_cc or 0, year or 0) if cif_usd else {}

        # Derive model name from full_title (strip year + make prefix)
        model = full_title
        for prefix in [str(year), make.upper(), make.title()]:
            model = model.replace(prefix, "").strip()

        return {
            "listing_type": "For Sale",
            "vehicle_type": "",
            "make": make,
            "model": model,
            "year": year,
            "mileage_km": mileage,
            "transmission": transmission,
            "fuel_type": "",
            "engine_cc": engine_cc,
            "color": "",
            "condition": "Used",
            "location": "Japan",
            "region": "Japan (Import)",
            "price_original": f"CIF ${cif_usd:,.0f}" if cif_usd else "",
            "price_tsh": taxes.get("total_landed_tzs"),
            "price_usd": cif_usd,
            "currency": "USD",
            "negotiable": "",
            "features": "",
            "contact": "",
            "duty_status": "Duty Not Paid",
            "summary": (
                f"{year} {make} {model} | "
                f"FOB ${fob_usd:,.0f} | CIF ${cif_usd:,.0f} | "
                f"Landed ~{taxes.get('total_landed_millions','?')}M TSH (TRA taxes incl.)"
            ),
            "source_account": "beforward.jp",
            "post_url": detail_url,
            "display_url": img_url,
            "caption_raw": f"Ref:{ref_no} {full_title}",
            "segment": _get_segment(make, model),
            "post_date": None,
        }
    except Exception as e:
        logger.debug(f"Row parse error: {e}")
        return None


async def fetch_beforward_listings(
    make: str = "Toyota",
    max_results: int = 25,
) -> list[dict]:
    """
    Fetch car listings from BE Forward by scraping the stocklist HTML.
    Destination is always Dar es Salaam (owcc=tz).
    """
    make_id = BF_MAKE_IDS.get(make)
    if not make_id:
        logger.warning(f"⚠️ No BE Forward make ID for {make} — skipping")
        return []

    params = {
        "make": make_id,
        "owcc": "tz",          # Tanzania destination → shows CIF to Dar es Salaam
        "per_page": min(max_results, 50),
        "sortkey": "n",         # newest first
    }

    try:
        async with httpx.AsyncClient(
            timeout=20,
            headers=BF_HEADERS,
            follow_redirects=True,
        ) as client:
            r = await client.get(BF_STOCKLIST, params=params)

        if r.status_code != 200:
            logger.warning(f"⚠️ BE Forward returned {r.status_code} for {make}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("tr.stocklist-row")

        listings = []
        for row in rows[:max_results]:
            listing = _parse_beforward_row(row, make)
            if listing:
                listings.append(listing)

        logger.info(f"✅ BE Forward: {len(listings)} listings for {make} (from {len(rows)} rows)")
        return listings

    except Exception as e:
        logger.error(f"❌ BE Forward fetch failed for {make}: {e}")
        return []


async def fetch_beforward_bulk(makes: list[str] = None, max_per_make: int = 25) -> list[dict]:
    """Fetch multiple makes from BE Forward (direct HTML scrape)."""
    targets = makes or ["Toyota", "Nissan", "Honda", "Mitsubishi", "Subaru", "Mazda"]
    all_listings = []
    for make in targets:
        listings = await fetch_beforward_listings(make=make, max_results=max_per_make)
        all_listings.extend(listings)
        await asyncio.sleep(2)   # be polite to beforward.jp
    return all_listings


# ---------------------------------------------------------------------------
# SOURCE 2: Instagram accounts — via Apify Instagram Scraper
# ---------------------------------------------------------------------------
def _get_apify_client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        raise EnvironmentError("APIFY_TOKEN must be set in .env")
    return ApifyClient(token)


def _extract_car_data_from_caption(caption: str) -> Optional[dict]:
    """Use Claude Haiku to extract structured car data from an Instagram caption."""
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=CAR_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": caption[:2000]}]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"❌ Caption extraction failed: {e}")
        return {}


def _apify_post_to_listing(post: dict, source_account: str) -> Optional[dict]:
    """Convert an Apify Instagram post item into a car listing dict."""
    caption = post.get("caption") or post.get("alt") or ""
    if not caption.strip():
        return None
    car_data = _extract_car_data_from_caption(caption)
    if not car_data:
        return None
    timestamp = post.get("timestamp") or post.get("takenAt") or ""
    post_date = timestamp[:10] if timestamp else None
    post_url = post.get("url") or post.get("shortCode") and f"https://www.instagram.com/p/{post['shortCode']}/" or ""
    display_url = post.get("displayUrl") or ""
    return {
        **car_data,
        "post_date": post_date,
        "source_account": source_account,
        "post_url": post_url,
        "display_url": display_url,
        "caption_raw": caption[:1000],
        "segment": _get_segment(car_data.get("make", ""), car_data.get("model", "")),
    }


def _run_apify_instagram_scraper(usernames: list[str], max_posts: int = 30) -> list[dict]:
    """
    Synchronously run Apify's Instagram Profile Posts Scraper actor.
    Returns raw post items from all accounts.
    """
    try:
        client = _get_apify_client()
        run_input = {
            "directUrls": [f"https://www.instagram.com/{u}/" for u in usernames],
            "resultsType": "posts",
            "resultsLimit": max_posts,
        }
        logger.info(f"📷 Apify Instagram scrape: {usernames} (max {max_posts} posts each)")
        run = client.actor("apify/instagram-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        logger.info(f"✅ Apify returned {len(items)} raw posts")
        return items
    except EnvironmentError as e:
        logger.warning(f"⚠️ Apify skipped: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Apify Instagram scrape failed: {e}")
        return []


async def scrape_instagram_accounts(
    accounts: list[str], max_posts: int = 30
) -> list[dict]:
    """Scrape multiple Instagram accounts via Apify."""
    if not accounts:
        logger.info("ℹ️ No Instagram accounts configured — skipping")
        return []

    # Run Apify in a thread (blocking SDK call)
    raw_posts = await asyncio.to_thread(_run_apify_instagram_scraper, accounts, max_posts)

    all_listings = []
    seen_urls = set()
    for post in raw_posts:
        source = post.get("ownerUsername") or post.get("username") or ""
        listing = _apify_post_to_listing(post, source)
        if listing:
            url = listing.get("post_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_listings.append(listing)
                logger.info(f"  ✅ @{source}: {listing.get('make','?')} {listing.get('model','?')} — {listing.get('price_original','?')}")

    logger.info(f"📦 Instagram total: {len(all_listings)} car listings from {len(raw_posts)} posts")
    return all_listings


# ---------------------------------------------------------------------------
# Supabase storage
# ---------------------------------------------------------------------------
async def store_listings(listings: list[dict]) -> int:
    """Upsert listings into Supabase car_listings table."""
    from services.supabase import supabase

    saved = 0
    for listing in listings:
        try:
            # Remove None post_url entries (can't upsert without unique key)
            if not listing.get("post_url"):
                continue
            supabase.table("car_listings").upsert(
                listing, on_conflict="post_url"
            ).execute()
            saved += 1
        except Exception as e:
            logger.error(f"❌ DB insert failed: {e}")
    return saved


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def run_scout(
    accounts: list[str] = None,
    makes: list[str] = None,
    max_posts_instagram: int = 30,
    max_per_make_beforward: int = 20,
):
    """
    Run both scrapers in parallel:
    - CarAPIs / BE Forward  (imported cars + TRA tax pre-calculated)
    - Instagram accounts    (local Tanzanian dealer posts)
    """
    targets_instagram = accounts or TARGET_ACCOUNTS
    logger.info("🚗 Magari Scout starting — running BE Forward + Instagram in parallel")

    # Run both sources concurrently
    beforward_task = fetch_beforward_bulk(
        makes=makes, max_per_make=max_per_make_beforward
    )
    instagram_task = scrape_instagram_accounts(
        targets_instagram, max_posts=max_posts_instagram
    )

    beforward_listings, instagram_listings = await asyncio.gather(
        beforward_task, instagram_task
    )

    # Merge, deduplicate by post_url
    seen_urls = set()
    all_listings = []
    for listing in beforward_listings + instagram_listings:
        url = listing.get("post_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_listings.append(listing)

    saved = await store_listings(all_listings)

    logger.info(f"✅ Scout complete:")
    logger.info(f"   BE Forward : {len(beforward_listings)} listings")
    logger.info(f"   Instagram  : {len(instagram_listings)} listings")
    logger.info(f"   Total saved: {saved} to Supabase")
    return saved


# ---------------------------------------------------------------------------
# On-demand fetch — triggered live when a car is not in the DB
# ---------------------------------------------------------------------------
async def _scrape_instagram_for_query(make: str, model: str, max_posts: int = 15) -> list[dict]:
    """
    Scrape TARGET_ACCOUNTS via Apify for a specific make/model on demand.
    Post-filters extracted listings by make/model keyword.
    """
    if not TARGET_ACCOUNTS:
        return []

    make_kw  = make.lower()  if make  else ""
    model_kw = model.lower() if model else ""

    # Fetch posts via Apify
    raw_posts = await asyncio.to_thread(
        _run_apify_instagram_scraper, TARGET_ACCOUNTS, max_posts
    )

    all_listings = []
    seen_urls = set()
    for post in raw_posts:
        caption = (post.get("caption") or post.get("alt") or "").lower()
        # Pre-filter: skip posts that don't mention the make/model
        if make_kw and make_kw not in caption:
            continue
        if model_kw and model_kw not in caption:
            continue
        source = post.get("ownerUsername") or post.get("username") or ""
        listing = _apify_post_to_listing(post, source)
        if listing:
            url = listing.get("post_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_listings.append(listing)

    logger.info(f"📷 Instagram on-demand: {len(all_listings)} listings for {make} {model}")
    return all_listings


# Deduplication lock — prevents multiple concurrent scouts for the same make/model
# Key: "Toyota_Harrier", Value: asyncio.Event (set when scout completes)
_in_flight: dict[str, asyncio.Event] = {}


async def _run_scout_core(make: str, model: str, scout_key: str) -> list[dict]:
    """
    Internal: actually runs BE Forward + Instagram and saves to DB.
    Always cleans up _in_flight when done.
    """
    try:
        matched_make = next((k for k in BF_MAKE_IDS if k.lower() == make.lower()), None)

        async def _empty():
            return []

        beforward_task = (
            fetch_beforward_listings(make=matched_make, max_results=25)
            if matched_make else _empty()
        )
        instagram_task = _scrape_instagram_for_query(make=make, model=model, max_posts=15)

        beforward_listings, instagram_listings = await asyncio.gather(
            beforward_task, instagram_task
        )

        # Filter BE Forward by model keyword
        if model and beforward_listings:
            model_kw = model.lower()
            beforward_listings = [
                l for l in beforward_listings
                if model_kw in (l.get("model") or "").lower()
                or model_kw in (l.get("caption_raw") or "").lower()
            ]

        # Merge, deduplicate
        seen_urls: set = set()
        all_listings = []
        for listing in beforward_listings + instagram_listings:
            url = listing.get("post_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_listings.append(listing)

        if all_listings:
            saved = await store_listings(all_listings)
            logger.info(
                f"✅ Scout complete: BEF={len(beforward_listings)} "
                f"IG={len(instagram_listings)} saved={saved}"
            )
        else:
            logger.info(f"⚠️ Scout: no listings found for {make} {model}")

        return all_listings

    finally:
        # Signal any waiters and remove the lock
        event = _in_flight.pop(scout_key, None)
        if event:
            event.set()


async def fetch_on_demand(make: str, model: str = "") -> list[dict]:
    """
    Fetch listings from BE Forward + Instagram for a specific make/model.

    Deduplication: if a scout for the same make/model is already in-flight,
    wait for it to finish then return DB results — no duplicate Apify runs.

    Called by decision.py when DB has no matching listings.
    """
    make  = (make  or "").strip()
    model = (model or "").strip()

    if not make:
        return []

    scout_key = f"{make}_{model}".lower().replace(" ", "_")

    # --- Deduplication: another worker/coroutine already scouting this? ---
    if scout_key in _in_flight:
        logger.info(f"⏳ Scout already in-flight for '{scout_key}' — waiting...")
        await _in_flight[scout_key].wait()
        # Re-query DB now that scout has finished
        from services.car_search import search_listings
        listings = search_listings(f"{make} {model}", limit=5)
        return [
            l for l in listings
            if (not make  or make.lower()  in (l.get("make")  or "").lower())
            and (not model or model.lower() in (l.get("model") or "").lower())
        ]

    # --- Register in-flight lock ---
    event = asyncio.Event()
    _in_flight[scout_key] = event

    logger.info(f"🔍 On-demand scout: {make} {model}")
    return await _run_scout_core(make, model, scout_key)


async def fetch_on_demand_background(make: str, model: str = ""):
    """
    Fire-and-forget version of fetch_on_demand.
    Returns immediately — scout runs in background and populates DB.
    Used when responding immediately from general knowledge is preferred.
    """
    make  = (make  or "").strip()
    model = (model or "").strip()

    if not make:
        return

    scout_key = f"{make}_{model}".lower().replace(" ", "_")

    if scout_key in _in_flight:
        logger.info(f"⏳ Background scout already in-flight for '{scout_key}' — skipping")
        return

    event = asyncio.Event()
    _in_flight[scout_key] = event

    logger.info(f"🚀 Background scout started: {make} {model}")
    asyncio.create_task(_run_scout_core(make, model, scout_key))

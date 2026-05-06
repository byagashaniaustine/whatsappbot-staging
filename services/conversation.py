"""
Conversation memory — per-phone rolling message history.

Architecture:
  L1: in-memory cache (fast, per-worker)
  L2: Supabase `conversation_history` table (shared across all workers)

This means multi-worker uvicorn deployments share history correctly.
L1 acts as a write-through cache — reads hit memory first, fall back to DB.

Supabase table required (run once in SQL editor):
  CREATE TABLE IF NOT EXISTS conversation_history (
    id        BIGSERIAL PRIMARY KEY,
    phone_number TEXT NOT NULL,
    role      TEXT NOT NULL,   -- 'user' | 'assistant'
    content   TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_conv_phone_time
    ON conversation_history (phone_number, created_at DESC);
"""
import time
import logging
import asyncio

logger = logging.getLogger("whatsapp_app")

MAX_TURNS   = 6      # messages kept per phone (3 user + 3 assistant)
TTL_SECONDS = 1800   # 30 min inactivity → clear

# L1 in-memory cache: { phone: {"history": [...], "last_active": float} }
_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# L1 helpers
# ---------------------------------------------------------------------------
def _prune_expired():
    now = time.time()
    expired = [p for p, v in _cache.items() if now - v["last_active"] > TTL_SECONDS]
    for p in expired:
        del _cache[p]


def _cache_get(phone: str) -> list[dict] | None:
    _prune_expired()
    entry = _cache.get(phone)
    return entry["history"] if entry else None


def _cache_set(phone: str, history: list[dict]):
    _cache[phone] = {"history": history, "last_active": time.time()}


# ---------------------------------------------------------------------------
# L2 Supabase helpers (non-blocking — fire-and-forget writes)
# ---------------------------------------------------------------------------
def _db_save(phone: str, role: str, content: str):
    try:
        from services.supabase import supabase
        supabase.table("conversation_history").insert({
            "phone_number": phone,
            "role": role,
            "content": content,
        }).execute()
    except Exception as e:
        logger.warning(f"⚠️ conversation_history DB write failed: {e}")


def _db_fetch(phone: str) -> list[dict]:
    try:
        from services.supabase import supabase
        rows = (
            supabase.table("conversation_history")
            .select("role, content")
            .eq("phone_number", phone)
            .order("created_at", desc=False)
            .limit(MAX_TURNS)
            .execute()
        )
        return [{"role": r["role"], "content": r["content"]} for r in (rows.data or [])]
    except Exception as e:
        logger.warning(f"⚠️ conversation_history DB fetch failed: {e}")
        return []


def _db_clear(phone: str):
    try:
        from services.supabase import supabase
        supabase.table("conversation_history").delete().eq("phone_number", phone).execute()
    except Exception as e:
        logger.warning(f"⚠️ conversation_history DB clear failed: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_history(phone_number: str) -> list[dict]:
    """
    Return conversation history for a phone (oldest first).
    Hits L1 cache first; falls back to Supabase (cross-worker).
    """
    cached = _cache_get(phone_number)
    if cached is not None:
        return cached

    # L1 miss — fetch from DB (another worker may have written it)
    history = _db_fetch(phone_number)
    if history:
        _cache_set(phone_number, history)
    return history


def save_turn(phone_number: str, user_text: str, assistant_reply: str):
    """
    Append a user+assistant turn. Write-through to Supabase.
    Caps history at MAX_TURNS messages.
    """
    history = get_history(phone_number)
    history.append({"role": "user",      "content": user_text})
    history.append({"role": "assistant", "content": assistant_reply})

    if len(history) > MAX_TURNS:
        history = history[-MAX_TURNS:]

    _cache_set(phone_number, history)

    # Persist to DB (fire-and-forget in thread to avoid blocking event loop)
    asyncio.get_event_loop().run_in_executor(None, _db_save, phone_number, "user", user_text)
    asyncio.get_event_loop().run_in_executor(None, _db_save, phone_number, "assistant", assistant_reply)

    logger.info(f"💬 History saved for {phone_number} ({len(history)} msgs)")


def clear_history(phone_number: str):
    """Clear history on greeting/menu — both cache and DB."""
    _cache.pop(phone_number, None)
    asyncio.get_event_loop().run_in_executor(None, _db_clear, phone_number)

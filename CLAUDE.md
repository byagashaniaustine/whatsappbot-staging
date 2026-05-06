# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
pip install -r requirements.txt

# Local dev (expose via ngrok or similar for Meta webhook verification)
uvicorn main:app --reload

# Production
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Endpoints: `POST /whatsapp-webhook/` (messages), `GET /whatsapp-webhook/` (Meta verification), `GET /health`.

## Testing Claude/AI Services Live

```bash
# Test intent classifier and Claude responses directly
python -c "
import asyncio
from dotenv import load_dotenv; load_dotenv()
from services.intent import analyze_intent
asyncio.run(analyze_intent('Toyota Vitz bei gani?'))
"
```

## Magari Scout (Instagram Car Scraper)

```bash
# Scrape all default accounts and populate Supabase
python scripts/run_scout.py

# Scrape specific accounts
python scripts/run_scout.py --accounts magaridar,gari_bora_tz --max-posts 50
```

Before first run, execute `supabase_migration.sql` in the Supabase SQL editor to create the `car_listings` table.

## Architecture Overview

This is a **FastAPI WhatsApp bot** (Kopagari) for the Tanzanian used car and car loan market. It handles two parallel concerns: interactive WhatsApp Flows (encrypted) and conversational AI messages.

### Message Routing (`main.py`)

All traffic enters `POST /whatsapp-webhook/`. The handler distinguishes two payload types:

1. **Encrypted Flow payload** — detected by presence of `encrypted_flow_data` / `encrypted_aes_key` / `initial_vector` keys. Decrypted with RSA-OAEP (private key) + AES-GCM, routed through the flow state machine, re-encrypted and returned as a plain base64 string.
2. **Standard message** — text routes to `whatsapp_menu()` → `handle_text_message()` (AI decision layer); media routes to `process_file_upload()`.

### Flow State Machine (`main.py`)

`FLOW_DEFINITIONS` dict defines two flows. Actions `INIT`, `data_exchange`, `complete` drive screen transitions:

- **`LOAN_FLOW_ID_1`**: `MAIN_MENU → CREDIT_SCORE / LOAN_CALCULATOR / AFFORDABILITY_CHECK / SERVICES → SERVICE_RATING → LAST_SCREEN`. The `LOAN_CALCULATOR → LOAN_RESULT` transition calls `calculate_loan_results()` inline.
- **`ACCOUNT_FLOW_ID_2`**: `PROFILE_UPDATE → SUMMARY`

Flow response encryption: IV is bitwise-flipped (`b ^ 0xFF`) before re-encrypting the response.

### AI Decision Layer (`api/decision.py` → `services/intent.py`)

Text messages go through: `whatsapp_menu()` → `handle_text_message()` → `analyze_intent()` (Claude Haiku) → route by intent:

| Intent | Action |
|--------|--------|
| `flow_initiation` | Create UUID session, send `manka_menu_03` Flow template |
| `loan_services_menu` | Send `mtaa_wa_manka01` template |
| `car_inquiry` | Query `car_listings` in Supabase, inject live results into Claude prompt |
| `car_import_cost` | Claude answers with TRA duty formula |
| `loan_question` / `faq` / `loan_calculation` | Claude answers |
| `document_upload_reminder` | Static WhatsApp message |

**Known issue fixed**: Claude Haiku wraps JSON in markdown code fences — `services/intent.py` strips them before `json.loads()`.

### Car Listing Pipeline

- **Scraper** (`services/magari_scout.py`): **Apify** (`apify/instagram-scraper` actor) fetches public Instagram posts from Tanzanian car dealer accounts; BE Forward HTML and CarAPIs are secondary sources → Claude Haiku extracts structured JSON (make, model, year, price_tsh, duty_status, etc.) → stored in Supabase `car_listings`
- **Search** (`services/car_search.py`): parses Swahili/English queries into Supabase filters (make, model, max price, duty status, segment) and formats results for WhatsApp

### Service Layer

| File | Responsibility |
|------|---------------|
| `api/whatsappBOT.py` | `calculate_loan()` amortization math; `whatsapp_menu()` entry point |
| `api/whatsappfile.py` | Download media from Meta → Manka API or Gemini → store in Supabase |
| `api/decision.py` | Intent routing; injects live car listings for `car_inquiry` |
| `services/intent.py` | Claude Haiku intent classifier (strips markdown fences from response) |
| `services/claude_response.py` | Claude Haiku conversational replies; system prompt encodes Tanzanian car market knowledge and TRA duty formula |
| `services/car_search.py` | Query `car_listings` Supabase table by make/model/price/duty |
| `services/magari_scout.py` | Instagram scraper + Claude extraction for car listings |
| `services/meta.py` | Send text messages, Flow templates via WhatsApp Cloud API |
| `services/supabase.py` | Session records, file metadata, car listings |
| `services/gemini.py` | Gemini 2.5 Flash vision analysis for images and PDFs (Swahili output) |
| `services/pdfendpoint.py` | Manka API affordability scoring; falls back to Gemini |
| `services/mail.py` | Gmail OAuth2 — emails service ratings to company |

### PDF/Image Analysis

PDFs → **Manka API** first (Tanzanian affordability scoring), falls back to **Gemini** on failure or low confidence. Images → **Gemini Vision** directly. Files stored in Supabase Storage (`whatsapp_files` bucket).

## Supabase Schema

- **`whatsapp_sessions`**: `session_id`, `phone_number`, `latest_message`, `status`
- **`wHatsappUsers`**: `user_id`, `user_name`, `user_phone`, `flow_type`, `file_type`, `file_url`
- **`car_listings`**: full vehicle schema — `make`, `model`, `year`, `price_tsh`, `duty_status`, `engine_cc`, `transmission`, `mileage_km`, `contact`, `source_account`, `post_url`, `segment` (see `supabase_migration.sql`)
- **`conversation_history`**: `phone_number`, `role`, `content`, `created_at` — used by the L2 persistence layer in `services/conversation.py`

## Required Environment Variables

```
META_ACCESS_TOKEN           # WhatsApp Business API bearer token
WA_PHONE_NUMBER_ID          # WhatsApp Business phone number ID
WEBHOOK_VERIFY_TOKEN        # Token for Meta webhook verification
PRIVATE_KEY                 # RSA private key (PEM, literal \n) for Flow decryption
ANTHROPIC_API_KEY           # Claude Haiku — intent classification + responses
GEMINI_API_KEY              # Google Gemini — vision analysis
SUPABASE_URL                # Supabase project URL
SUPABASE_KEY                # Supabase anon key
SUPABASE_SERVICE_ROLE_KEY   # Supabase service role key (used by supabase.py)
MANKA_ENDPOINT              # Manka affordability API URL
MANKA_API_KEY               # Manka API bearer token
SENDER_EMAIL                # Gmail account for outbound email
COMPANY_EMAIL               # Service rating email recipient
CC_EMAILS                   # Comma-separated CC addresses
APIFY_TOKEN                 # Apify client token for Instagram scraper actor
CARAPIS_API_KEY             # BE Forward API fallback key
STREAMLOGIA_API_KEY         # Streamlogia log ingestion API key
STREAMLOGIA_PROJECT_ID      # Streamlogia project UUID
```

`token.json` required for Gmail OAuth2 (generated on first auth, gitignored).

## Key Implementation Notes

- **`PRIVATE_KEY` format**: newlines must be literal `\n` in `.env`; `load_private_key()` calls `.replace("\\n", "\n")` before import. This runs at module load — missing/malformed key crashes startup.
- **Flow response format**: the encrypted response is returned as `PlainTextResponse` (plain base64 string), not JSON — Meta requires this.
- **`calculate_loan()` formula**: standard amortization `M = P[i(1+i)^n]/[(1+i)^n-1]`; handles 0% rate as `P/n`.
- **Tanzanian market**: all user-facing messages and Gemini/Claude prompts are in Swahili. Car prices in TSH (milioni/ML = millions, laki = 100k). Duty Paid (DP) / Duty Not Paid (DNP) is a critical field for buyers.
- **TRA import duty formula** (used by Claude for `car_import_cost` intent): Import Duty 25% of CIF → Excise Duty (0/5/10% by CC, +25% surcharge if 8+ years old) → VAT 18% of running total.
- **Conversation history** (`services/conversation.py`): two-level cache — L1 in-memory dict per worker (fast), L2 Supabase `conversation_history` table (shared across workers). Requires the `conversation_history` table to exist in Supabase before first use.

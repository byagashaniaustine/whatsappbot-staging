import os
import json
import base64
import logging
import httpx
import streamlogia
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from starlette.responses import JSONResponse
from typing import Optional
from dotenv import load_dotenv
from datetime import datetime

load_dotenv() 

# Import cryptography libraries
try:
    from Crypto.PublicKey import RSA
    from Crypto.Hash import SHA256
    from Crypto.Cipher import PKCS1_OAEP, AES
except ImportError:
    raise RuntimeError("PyCryptodome is not installed. Please install with: pip install pycryptodome")

# Import WhatsApp handling functions
from api.whatsappBOT import whatsapp_menu, calculate_loan_results
from api.whatsappfile import process_file_upload
from services.meta import (
    send_meta_whatsapp_message, get_media_url,
    send_manka_menu_01, send_mtaa_wa_manka_template
)
from services.mail import send_email_to_company

# Setup logging
logger = logging.getLogger("whatsapp_app")
logger.setLevel(logging.DEBUG)

app = FastAPI()
streamlogia.init(app, source="kopagari-whatsapp-bot", console=True)

# --------------------------------------------------
# HEALTH CHECK ENDPOINT
# --------------------------------------------------
@app.get("/health")
async def health_check():
    response_payload = {
        "body":{
             "version": "3.0",
    "action": "ping"
        },"data": {
            "status": "active"
        }
    }
    logger.critical(f"health check endpoint returns{response_payload}")
    return response_payload    


# --------------------------------------------------
# CTA URL MESSAGE
# ------------------------------------------------__
async def send_cta_url_message(to_phone: str, body_text: str, button_label: str, target_url: str):
    access_token = os.getenv("ELIMUFEDHA_ACCESS_TOKEN")
    phone_id = os.getenv("ELIMUFEDHA_PHONE_NUMBER_ID")

    url = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "header": {"type": "text", "text": "Ripoti ya Mkopo"},
            "body": {"text": body_text},
            "footer": {"text": "Manka"},
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": button_label,
                    "url": target_url
                }
            }
        }
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)


KOPAGARI_VERIFY_TOKEN  = os.getenv("KOPAGARI_WEBHOOK_VERIFY_TOKEN")
ELIMUFEDHA_VERIFY_TOKEN = os.getenv("ELIMUFEDHA_WEBHOOK_VERIFY_TOKEN")

@app.get("/kopagari-webhook/")
async def verify_kopagari_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == KOPAGARI_VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge"))
    return PlainTextResponse("Verification failed", status_code=403)

@app.get("/webhook/ElimuFedha")
async def verify_elimufedha_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == ELIMUFEDHA_VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge"))
    return PlainTextResponse("Verification failed", status_code=403)

# --------------------------------------------------
# FLOW DEFINITIONS - Complete Integration
# --------------------------------------------------
FLOW_DEFINITIONS = {
    "LOAN_FLOW_ID_1": {
  "version": "7.2",
  "data_api_version": "3.0",
  "routing_model": {
    "MAIN_MENU": [
      "CREDIT_SCORE",
      "CREDIT_BANDWIDTH",
      "LOAN_CALCULATOR",
      "LOAN_TYPES",
      "SERVICES",
      "AFFORDABILITY_CHECK"
    ],
    "CREDIT_SCORE": ["SERVICE_RATING"],
    "CREDIT_BANDWIDTH": ["SERVICE_RATING"],
    "LOAN_TYPES": ["SERVICE_RATING"],
    "SERVICES": ["SERVICE_RATING"],
    "LOAN_CALCULATOR": ["LOAN_RESULT"],
    "LOAN_RESULT": [],
    "AFFORDABILITY_CHECK": ["DOCUMENT_REQUEST"],
    "DOCUMENT_REQUEST": ["SERVICE_RATING"],
    "SERVICE_RATING": ["LAST_SCREEN"],
    "LAST_SCREEN": []
  },

  "terminal_screens": [
    "SERVICE_RATING",
    "LOAN_RESULT",
    "LAST_SCREEN"
  ],

  "SUCCESS_ACTION": "complete",

  "SUCCESS_RESPONSE": {
    "screen": "SUCCESS",
    "data": {
      "extension_message_response": {
        "params": {
          "flow_token": "RETURNED_FLOW_TOKEN",
          "message": "Asante kwa kutumia Manka 🙏"
        }
      }
    }
  }
},
    "ACCOUNT_FLOW_ID_2": {
        "SUCCESS_ACTION": "SUBMIT_PROFILE",
        "SUCCESS_RESPONSE": {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": "RETURNED_FLOW_TOKEN",
                        "message": "Profile updated successfully"
                    }
                }
            }
        },
        "PROFILE": {
            "screen": "PROFILE_UPDATE",
            "data": {}
        },
        "SUMMARY": {
            "screen": "SUMMARY",
            "data": {}
        }
    }
}

# --------------------------------------------------
# RSA SETUP
# --------------------------------------------------
def load_private_key(key_string: str) -> RSA.RsaKey:
    key_string = key_string.replace("\\n", "\n")
    return RSA.import_key(key_string)

PRIVATE_KEY = load_private_key(os.getenv("PRIVATE_KEY"))
RSA_CIPHER = PKCS1_OAEP.new(PRIVATE_KEY, hashAlgo=SHA256)

# ========================================================================
# KOPAGARI WEBHOOK — /kopagari-webhook/
# Cars, product knowledge, Claude AI (text only)
# ========================================================================

@app.post("/kopagari-webhook/")
async def kopagari_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.critical("🚀 [Kopagari] Webhook received POST request.")
    try:
        payload = json.loads((await request.body()).decode("utf-8"))

        entry    = payload.get("entry", [{}])[0]
        changes  = entry.get("changes", [{}])[0]
        value    = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        statuses = value.get("statuses", [])

        for s in statuses:
            if s.get("status") == "failed":
                err = s.get("errors", [{}])[0]
                logger.critical(f"🛑 [Kopagari] DELIVERY FAILED! Code: {err.get('code')} - {err.get('message')}")

        if messages:
            message      = messages[0]
            from_number  = message.get("from", "")
            message_type = message.get("type")

            if from_number and not from_number.startswith("+"):
                from_number = "+" + from_number

            user_name = next(
                (c.get("profile", {}).get("name") for c in contacts if c.get("wa_id") == from_number.lstrip("+")),
                from_number
            )

            if message_type == "text":
                text_payload = {
                    "from_number": from_number,
                    "user_name":   user_name,
                    "body":        message.get("text", {}).get("body", "")
                }
                logger.critical(f"💬 [Kopagari] {from_number} ({user_name}): {text_payload['body']}")
                background_tasks.add_task(whatsapp_menu, text_payload)
            else:
                logger.critical(f"⚠️ [Kopagari] Unhandled message type: {message_type} from {from_number}")

        return PlainTextResponse("OK")

    except Exception as e:
        logger.critical(f"🚨 [Kopagari] Webhook Error: {e}", exc_info=True)
        return PlainTextResponse("Internal Server Error", status_code=500)


# ========================================================================
# ELIMUFEDHA WEBHOOK — /webhook/ElimuFedha
# Flows, file analysis, financial literacy templates
# ========================================================================

ELIMUFEDHA_LOAN_KEYWORDS = {"mkopo", "huduma"}


def _encrypt_flow_response(response_obj: dict, aes_key: bytes, iv: bytes) -> str:
    flipped_iv = bytes([b ^ 0xFF for b in iv])
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=flipped_iv)
    encrypted, tag = cipher.encrypt_and_digest(json.dumps(response_obj).encode("utf-8"))
    return base64.b64encode(encrypted + tag).decode("utf-8")


@app.post("/webhook/ElimuFedha")
async def elimufedha_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.critical("🚀 [ElimuFedha] Webhook received POST request.")
    try:
        raw_body = await request.body()
        payload  = json.loads(raw_body.decode("utf-8"))

        entry    = payload.get("entry", [{}])[0]
        changes  = entry.get("changes", [{}])[0]
        value    = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])

        # --- Detect encrypted Flow payload ---
        encrypted_flow_b64    = payload.get("encrypted_flow_data")
        encrypted_aes_key_b64 = payload.get("encrypted_aes_key")
        iv_b64                = payload.get("initial_vector")
        is_flow_payload       = encrypted_flow_b64 and encrypted_aes_key_b64 and iv_b64

        primary_from_number: Optional[str] = None
        if messages and messages[0].get("from"):
            primary_from_number = messages[0].get("from")
        elif contacts and contacts[0].get("wa_id"):
            primary_from_number = contacts[0].get("wa_id")
        if primary_from_number and not primary_from_number.startswith("+"):
            primary_from_number = "+" + primary_from_number

        # ----------------------------------------------------------------
        # ENCRYPTED FLOW PROCESSING
        # ----------------------------------------------------------------
        if is_flow_payload:
            try:
                encrypted_aes_key_bytes = base64.b64decode(encrypted_aes_key_b64)
                aes_key = RSA_CIPHER.decrypt(encrypted_aes_key_bytes)
                iv = base64.b64decode(iv_b64)
                encrypted_flow_bytes = base64.b64decode(encrypted_flow_b64)

                ciphertext = encrypted_flow_bytes[:-16]
                tag        = encrypted_flow_bytes[-16:]
                cipher_aes = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
                decrypted_data = json.loads(cipher_aes.decrypt_and_verify(ciphertext, tag).decode("utf-8"))
                logger.critical(f"📥 [ElimuFedha] Decrypted Flow: {json.dumps(decrypted_data, indent=2)}")

                action         = decrypted_data.get("action")
                flow_token     = decrypted_data.get("flow_token")
                user_data      = decrypted_data.get("data", {})
                current_screen = decrypted_data.get("screen", "UNKNOWN")
                flow_id_key    = user_data.get("flow_id", "LOAN_FLOW_ID_1")
                flow_def       = FLOW_DEFINITIONS.get(flow_id_key, {})
                response_obj   = None

                best_phone = primary_from_number or user_data.get("from_number")
                if best_phone:
                    user_data["from_number"] = best_phone
                    primary_from_number = best_phone

                # 1. PING
                if action == "ping":
                    response_obj = {"version": "3.0", "data": {"status": "active"}}
                    logger.critical("🏓 [ElimuFedha] PING")

                # 2. COMPLETE
                elif action == "complete" or action == flow_def.get("SUCCESS_ACTION"):
                    response_obj = json.loads(json.dumps(flow_def["SUCCESS_RESPONSE"]))
                    if flow_token:
                        response_obj["data"]["extension_message_response"]["params"]["flow_token"] = flow_token
                    logger.critical(f"✅ [ElimuFedha] Flow {flow_id_key} completed")

                    if current_screen == "DOCUMENT_REQUEST":
                        await send_meta_whatsapp_message(
                            primary_from_number,
                            "Asante kwa kutumia Manka! Tafadhali tuma nyaraka zako hapa kupitia WhatsApp."
                        )

                # 3. INIT
                elif action == "INIT":
                    if flow_id_key == "LOAN_FLOW_ID_1":
                        response_obj = {"screen": "MAIN_MENU", "data": user_data}
                    elif flow_id_key == "ACCOUNT_FLOW_ID_2":
                        response_obj = json.loads(json.dumps(flow_def["PROFILE"]))
                        response_obj["data"].update(user_data)
                    else:
                        response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Huduma haipatikani."}}
                    logger.critical(f"🎬 [ElimuFedha] INIT → {response_obj.get('screen')}")

                # 4. DATA EXCHANGE
                elif action == "data_exchange":
                    logger.critical(f"🔄 [ElimuFedha] DATA_EXCHANGE from screen: {current_screen}")

                    if user_data.get("error"):
                        response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Hitilafu imetokea. Tunaanza tena."}}

                    elif flow_id_key == "LOAN_FLOW_ID_1":
                        routing_model = flow_def.get("routing_model", {})

                        if current_screen == "MAIN_MENU":
                            selected = user_data.get("selected_service") or user_data.get("menu_selection")
                            if selected and selected in routing_model.get("MAIN_MENU", []):
                                response_obj = {"screen": selected, "data": user_data}
                                logger.critical(f"📍 MAIN_MENU → {selected}")
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}

                        elif current_screen == "LOAN_CALCULATOR":
                            if user_data.get("next_screen") == "LOAN_RESULT":
                                try:
                                    response_obj = calculate_loan_results(user_data)
                                except Exception as e:
                                    logger.error(f"❌ Loan calc error: {e}")
                                    response_obj = {"screen": "LOAN_RESULT", "data": {"error_message": "Tafadhali jaza nambari sahihi."}}
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}

                        elif current_screen == "SERVICES":
                            if user_data.get("next_screen") == "SERVICE_RATING":
                                response_obj = {"screen": "SERVICE_RATING", "data": user_data}
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}

                        elif current_screen == "SERVICE_RATING":
                            send_email_to_company(user_data)
                            response_obj = {"screen": "LAST_SCREEN", "data": {"message": "Asante kwa uchaguzi wako!"}}

                        elif current_screen == "AFFORDABILITY_CHECK":
                            if user_data.get("next_screen") == "DOCUMENT_REQUEST":
                                response_obj = {"screen": "DOCUMENT_REQUEST", "data": user_data}
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}

                        else:
                            next_screen = user_data.get("next_screen")
                            allowed = routing_model.get(current_screen, [])
                            if next_screen and (next_screen in allowed or next_screen in routing_model):
                                response_obj = {"screen": next_screen, "data": user_data}
                                logger.critical(f"📍 {current_screen} → {next_screen}")
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": user_data}

                    elif flow_id_key == "ACCOUNT_FLOW_ID_2":
                        if current_screen == "PROFILE_UPDATE":
                            response_obj = json.loads(json.dumps(flow_def["SUMMARY"]))
                            response_obj["data"].update(user_data)
                        else:
                            response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Huduma haipatikani."}}
                    else:
                        response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Huduma haipatikani."}}

                if response_obj is not None:
                    logger.critical(f"📤 [ElimuFedha] Responding to screen: {response_obj.get('screen', 'UNKNOWN')}")
                    return PlainTextResponse(
                        content=_encrypt_flow_response(response_obj, aes_key, iv),
                        status_code=200,
                        headers={"Content-Type": "text/plain; charset=utf-8"}
                    )

                logger.warning("⚠️ [ElimuFedha] No response object generated for flow action.")
                return PlainTextResponse("OK")

            except Exception as e:
                error_type = type(e).__name__
                error_msg  = str(e)
                logger.critical(f"🚨 [ElimuFedha] Flow error — {error_type}: {error_msg}", exc_info=True)
                if "Incorrect decryption" in error_msg:
                    logger.critical("🔐 Decryption failed — check PRIVATE_KEY")
                return JSONResponse(
                    content={"error": "Flow processing failed", "error_type": error_type, "timestamp": datetime.utcnow().isoformat()},
                    status_code=500
                )

        # ----------------------------------------------------------------
        # REGULAR MESSAGES — media or text keyword routing
        # ----------------------------------------------------------------
        if messages:
            message      = messages[0]
            from_number  = message.get("from", "")
            message_type = message.get("type")

            if from_number and not from_number.startswith("+"):
                from_number = "+" + from_number

            user_name = next(
                (c.get("profile", {}).get("name") for c in contacts if c.get("wa_id") == from_number.lstrip("+")),
                from_number
            )

            # File uploads → analysis pipeline
            if message_type in ["image", "document", "video", "audio"]:
                media_object = message.get(message_type, {})
                media_id     = media_object.get("id")
                mime_type    = media_object.get("mime_type", "")
                file_name    = media_object.get("filename", f"file.{mime_type.split('/')[-1] if '/' in mime_type else 'dat'}")

                if media_id:
                    logger.critical(f"📎 [ElimuFedha] Media from {from_number}: {message_type}")
                    try:
                        media_url = get_media_url(media_id)
                        await send_meta_whatsapp_message(from_number, "✅ Tumepokea faili lako. Tafadhali subiri uchambuzi wa kwanza...")
                        background_tasks.add_task(
                            process_file_upload,
                            user_id=from_number,
                            user_name=user_name,
                            user_phone=from_number,
                            flow_type="REGULAR_MEDIA",
                            media_url=media_url,
                            mime_type=mime_type,
                            file_name=file_name
                        )
                        logger.critical(f"✅ [ElimuFedha] File analysis queued for {from_number}")
                    except Exception as e:
                        logger.error(f"❌ [ElimuFedha] Media error for {from_number}: {e}", exc_info=True)
                        await send_meta_whatsapp_message(from_number, "Samahani, kuna hitilafu imetokea wakati tukipakia faili lako.")

            # Text → keyword routing
            elif message_type == "text":
                text = message.get("text", {}).get("body", "").lower().strip()
                logger.critical(f"💬 [ElimuFedha] {from_number}: {text}")

                if any(kw in text for kw in ELIMUFEDHA_LOAN_KEYWORDS):
                    await send_mtaa_wa_manka_template(from_number)
                    logger.critical(f"✅ [ElimuFedha] Sent mtaa_wa_manka03 to {from_number}")
                else:
                    await send_manka_menu_01(from_number, "manka_menu_01")
                    logger.critical(f"✅ [ElimuFedha] Sent manka_menu_01 to {from_number}")

        return PlainTextResponse("OK")

    except Exception as e:
        logger.critical(f"🚨 [ElimuFedha] Webhook Error: {e}", exc_info=True)
        return PlainTextResponse("Internal Server Error", status_code=500)
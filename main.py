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
from services.meta import send_meta_whatsapp_message, get_media_url, send_manka_menu_template
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
    access_token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("WA_PHONE_NUMBER_ID")

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
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


WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")

@app.get("/whatsapp-webhook/")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == WEBHOOK_VERIFY_TOKEN:
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

  "success_action": "complete",

  "success_response": {
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

# ----------------------------------------------------------------------
## 🚀 WEBHOOK HANDLER (POST) - All Flow Routing and Message Handling
# ----------------------------------------------------------------------

@app.post("/whatsapp-webhook/")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.critical(f"🚀 [INIT] Webhook received POST request.")
    
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode('utf-8'))
        logger.critical("JSON Parsed Successfully.")

        # --- Extract Metadata ---
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        statuses = value.get("statuses", [])
        if statuses:
         for s in statuses:
          if s.get("status") == "failed":
            err = s.get("errors", [{}])[0]
            logger.critical(f"🛑 DELIVERY FAILED! Code: {err.get('code')} - {err.get('message')}")
        
        # Determine if it's a Flow payload
        encrypted_flow_b64 = payload.get("encrypted_flow_data")
        encrypted_aes_key_b64 = payload.get("encrypted_aes_key")
        iv_b64 = payload.get("initial_vector")
        is_flow_payload = encrypted_flow_b64 and encrypted_aes_key_b64 and iv_b64
        
        # Safely extract primary_from_number from standard locations in the webhook payload
        primary_from_number: Optional[str] = None
        
        if messages and messages[0].get("from"):
            primary_from_number = messages[0].get("from")
        elif contacts and contacts[0].get("wa_id"):
            primary_from_number = contacts[0].get("wa_id")

        if primary_from_number and not primary_from_number.startswith("+"):
            primary_from_number = "+" + primary_from_number
        logger.critical(f"📞 Initial Phone Number Detected: {primary_from_number}")

        # ========================================================================
        # ENCRYPTED FLOW PAYLOAD PROCESSING
        # ========================================================================
        if is_flow_payload:
            try:
                # Validate payload structure
                logger.critical(f"🔍 Flow Payload Validation:")
                logger.critical(f"   - encrypted_flow_data length: {len(encrypted_flow_b64)}")
                logger.critical(f"   - encrypted_aes_key length: {len(encrypted_aes_key_b64)}")
                logger.critical(f"   - initial_vector length: {len(iv_b64)}")
                
                encrypted_aes_key_bytes = base64.b64decode(encrypted_aes_key_b64)
                logger.critical(f"🔑 Decrypting AES key size: {len(encrypted_aes_key_bytes)} bytes.")
                
                if len(encrypted_aes_key_bytes) != 256:
                    logger.warning(f"⚠️ Unexpected AES key size: {len(encrypted_aes_key_bytes)} (expected 256)")
                
                aes_key = RSA_CIPHER.decrypt(encrypted_aes_key_bytes)
                logger.critical(f"✅ AES key decrypted successfully: {len(aes_key)} bytes")
                
                iv = base64.b64decode(iv_b64)
                encrypted_flow_bytes = base64.b64decode(encrypted_flow_b64)
                
                logger.critical(f"📦 Encrypted flow data: {len(encrypted_flow_bytes)} bytes")
                logger.critical(f"🔢 IV: {len(iv)} bytes")
                
                ciphertext = encrypted_flow_bytes[:-16]
                tag = encrypted_flow_bytes[-16:]
                
                logger.critical(f"🔓 Attempting AES-GCM decryption...")
                cipher_aes = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
                decrypted_bytes = cipher_aes.decrypt_and_verify(ciphertext, tag)
                logger.critical(f"✅ Decryption successful: {len(decrypted_bytes)} bytes")
                
                decrypted_data = json.loads(decrypted_bytes.decode("utf-8"))

                logger.critical(f"📥 Decrypted Flow Data: {json.dumps(decrypted_data, indent=2)}")

                action = decrypted_data.get("action")
                flow_token = decrypted_data.get("flow_token")
                user_data = decrypted_data.get("data", {})
                current_screen = decrypted_data.get("screen", "UNKNOWN")
                flow_id_key = user_data.get("flow_id", "LOAN_FLOW_ID_1") 
                current_flow_screens = FLOW_DEFINITIONS.get(flow_id_key)
                response_obj = None
                
                best_phone = primary_from_number if primary_from_number else user_data.get("from_number")
                if best_phone:
                    user_data["from_number"] = best_phone
                    primary_from_number = best_phone
                
                          # Capture Delivery Failures
                
                
                # 1. PING RESPONSE
                
                if action == "ping":
                    response_obj = {
                        "version": "3.0",
                        "data": {
                            "status": "active"
                        }
                    }
                    logger.critical("🏓 PING received - responding with health check")
                
                # 2. COMPLETE/SUCCESS ACTION
                elif action == "complete" or (current_flow_screens and action == current_flow_screens.get("SUCCESS_ACTION")):
                    response_obj = json.loads(json.dumps(current_flow_screens["SUCCESS_RESPONSE"])) 
                    if flow_token:
                        success_params = response_obj["data"]["extension_message_response"]["params"]
                        success_params["flow_token"] = flow_token
                        logger.critical(f"✅ Flow {flow_id_key} completed successfully")
                    
                    # Handle DOCUMENT_REQUEST completion
                    if current_screen == "DOCUMENT_REQUEST":
                        logger.critical(f"📄 Document request screen completed for {primary_from_number}")
                        await send_meta_whatsapp_message(
                            primary_from_number,
                            "Asante kwa kutumia Manka! Tafadhali tuma nyaraka zako hapa kupitia WhatsApp."
                        )
                
                # 3. INIT ACTION
                elif action == "INIT":
                    if flow_id_key == "LOAN_FLOW_ID_1":
                        response_obj = {"screen": "MAIN_MENU", "data": user_data}
                        logger.critical("🎬 INIT: Starting LOAN_FLOW at MAIN_MENU")
                    elif flow_id_key == "ACCOUNT_FLOW_ID_2":
                        response_obj = current_flow_screens["PROFILE"]
                        response_obj["data"].update(user_data)
                        logger.critical("🎬 INIT: Starting ACCOUNT_FLOW at PROFILE")
                    else:
                        response_obj = {
                            "screen": "MAIN_MENU",
                            "data": {"error_message": "Huduma haipatikani."}
                        }
                        logger.error(f"❌ Unknown flow_id: {flow_id_key}")
                
                # 4. DATA EXCHANGE ACTION
                elif action == "data_exchange":
                    logger.critical(f"🔄 DATA_EXCHANGE from screen: {current_screen}")

                    if user_data.get("error"):
                        response_obj = {
                            "screen": "MAIN_MENU", 
                            "data": {"error_message": "Hitilafu imetokea. Tunaanza tena."}
                        }
                        logger.error(f"❌ Error in user_data: {user_data.get('error')}")

                    elif flow_id_key == "LOAN_FLOW_ID_1":
                        # Handle menu selection from MAIN_MENU
                        if current_screen == "MAIN_MENU":
                            selected_service = user_data.get("selected_service") or user_data.get("menu_selection")
                            if selected_service:
                                routing_model = FLOW_DEFINITIONS["LOAN_FLOW_ID_1"]["routing_model"]
                                allowed_screens = routing_model.get("MAIN_MENU", [])
                                
                                if selected_service in allowed_screens:
                                    response_obj = {"screen": selected_service, "data": user_data}
                                    logger.critical(f"📍 Navigating from MAIN_MENU to {selected_service}")
                                else:
                                    response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}
                                    logger.error(f"❌ Invalid menu selection: {selected_service}")
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Tafadhali chagua huduma."}}

                        # Handle LOAN_CALCULATOR -> LOAN_RESULT
                        elif current_screen == "LOAN_CALCULATOR":
                            next_screen = user_data.get("next_screen")
                            if next_screen == "LOAN_RESULT":
                                try:
                                    result = calculate_loan_results(user_data)                
                                    response_obj=result
                                    logger.critical(f"total_payment={result['data']['total_payment']}")
                                    logger.critical(f", monthly_payment={result['data']['monthly_payment']}")
                                    logger.critical(f"total_interest={result['data']['total_interest']}")
                                except Exception as e:
                                    logger.error(f"❌ Loan calculation error: {e}")
                                    response_obj = {
                                        "screen": "LOAN_RESULT",
                                        "data": {"error_message": "Tafadhali jaza nambari sahihi."}
                                    }
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}
                        
                        elif current_screen == "SERVICES":
                            next_screen = user_data.get("next_screen")
                            if next_screen == "SERVICE_RATING":
                                logger.critical(f"📍 Navigating to SERVICE_RATING for service feedback")
                                response_obj = {"screen": "SERVICE_RATING", "data": user_data}
                                logger.critical(f"⭐ Navigating to SERVICE_RATING for service feedback")
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}
                        
                        elif current_screen == "SERVICE_RATING":
                          next_screen = user_data.get("next_screen")
                          send_email_to_company(user_data)
                          response_obj = {
                              "screen": "LAST_SCREEN", 
                              "data": {"message": "Asante kwa uchaguzi wako!"}
                              }
                         
                
                        # Handle AFFORDABILITY_CHECK -> DOCUMENT_REQUEST
                        elif current_screen == "AFFORDABILITY_CHECK":
                            next_screen = user_data.get("next_screen")
                            if next_screen == "DOCUMENT_REQUEST": 
                                response_obj = {"screen": "DOCUMENT_REQUEST", "data": user_data}
                                logger.critical(f"📄 Navigating to DOCUMENT_REQUEST")
                                if next_screen == "SCREEN_RATING":
                                    logger.critical(f"⭐ Navigating to SERVICE_RATING for service feedback")
                                    response_obj = {"screen": "SERVICE_RATING", "data": user_data}
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}
                        # Handle general navigation with next_screen
                        else:
                            next_screen = user_data.get("next_screen")
                            if next_screen:
                                # Validate against routing model
                                routing_model = FLOW_DEFINITIONS["LOAN_FLOW_ID_1"]["routing_model"]
                                allowed_next = routing_model.get(current_screen, [])
                                
                                if next_screen in allowed_next or next_screen in routing_model.keys():
                                    response_obj = {"screen": next_screen, "data": user_data}
                                    logger.critical(f"📍 Navigating from {current_screen} to {next_screen}")
                                else:
                                    response_obj = {"screen": "MAIN_MENU", "data": {"error_message": "Chaguo batili."}}
                                    logger.error(f"❌ Invalid navigation: {current_screen} -> {next_screen}")
                            else:
                                response_obj = {"screen": "MAIN_MENU", "data": user_data}

                    elif flow_id_key == "ACCOUNT_FLOW_ID_2":
                        if current_screen == "PROFILE_UPDATE":
                            response_obj = json.loads(json.dumps(current_flow_screens["SUMMARY"]))
                            response_obj["data"].update(user_data)
                            logger.critical("📝 Profile updated, showing summary")
                        else:
                            response_obj = {
                                "screen": "MAIN_MENU",
                                "data": {"error_message": "Huduma haipatikani."}
                            }
                    else:
                        response_obj = {
                            "screen": "MAIN_MENU",
                            "data": {"error_message": "Huduma haipatikani."}
                        }
                        logger.error(f"❌ Unknown flow_id in data_exchange: {flow_id_key}")

                # --- Encrypt and return response ---
                if response_obj is not None:
                    flipped_iv = bytes([b ^ 0xFF for b in iv]) 
                    cipher_resp = AES.new(aes_key, AES.MODE_GCM, nonce=flipped_iv)
                    response_json_string = json.dumps(response_obj)
                    
                    logger.critical(f"📤 Preparing response for screen: {response_obj.get('screen', 'UNKNOWN')}")
                    logger.critical(f"📋 Response JSON: {response_json_string}")
                    
                    encrypted_resp_bytes, resp_tag = cipher_resp.encrypt_and_digest(response_json_string.encode("utf-8"))
                    full_resp = encrypted_resp_bytes + resp_tag
                    full_resp_b64 = base64.b64encode(full_resp).decode("utf-8")
                    
                    logger.critical(f"✅ Encrypted response length: {len(full_resp_b64)} characters")
                    
                    
                    return PlainTextResponse(
                        content=full_resp_b64,
                        status_code=200,
                        headers={"Content-Type": "text/plain; charset=utf-8"}
                    )
                
                logger.warning("⚠️ Flow action processed, but no response object generated.")
                return PlainTextResponse("Flow action processed, but no response object generated.", status_code=200)

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                
                logger.critical(f"🚨 FLOW ERROR DETAILS:")
                logger.critical(f"   Error Type: {error_type}")
                logger.critical(f"   Error Message: {error_msg}")
                logger.critical(f"   Payload Keys: {list(payload.keys())}")
                logger.critical(f"   Raw Payload: {json.dumps(payload, indent=2)}")
                
                if "Incorrect decryption" in error_msg:
                    logger.critical("🔐 Issue: Decryption failed - check private key configuration")
                elif "RSA" in error_msg or "decrypt" in error_msg.lower():
                    logger.critical("🔑 Issue: RSA decryption problem - verify key format")
                elif "JSON" in error_msg or "decode" in error_msg.lower():
                    logger.critical("📝 Issue: JSON parsing failed after decryption")
                else:
                    logger.critical(f"⚠️ Unexpected error during flow processing", exc_info=True)
                
                # Return a more helpful error for debugging
                return JSONResponse(
                    content={
                        "error": "Flow processing failed",
                        "error_type": error_type,
                        "error_message": error_msg,
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    status_code=500
                )

        # ========================================================================
        # REGULAR WHATSAPP MESSAGE HANDLING (Text and Media)
        # ========================================================================
        
        if messages:
            message = messages[0]
            from_number = message.get("from")
            message_type = message.get("type")
            
            if from_number and not from_number.startswith("+"):
                from_number = "+" + from_number
            
            user_name = next((contact.get("profile", {}).get("name") for contact in contacts if contact.get("wa_id") == from_number.lstrip("+")), from_number)
            
            if not from_number:
                logger.error("❌ Could not determine 'from_number' for regular message.")
                return PlainTextResponse("OK (No Sender)", status_code=200)

            # Handle TEXT messages
            if message_type == "text":
                text_payload = {
                    "from_number": from_number,
                    "user_name": user_name,
                    "body": message.get("text", {}).get("body", "")
                }
                
                logger.critical(f"💬 Message from {from_number} ({user_name}): {text_payload['body']}")
                
                background_tasks.add_task(
                    whatsapp_menu,
                    text_payload
                )
                logger.critical(f"✅ Text message routed to whatsapp_menu for {from_number}.")
            
            # Handle MEDIA messages
            elif message_type in ["image", "document", "video", "audio"]:
                media_object = message.get(message_type, {})
                media_id = media_object.get("id")
                mime_type = media_object.get("mime_type")
                file_name = media_object.get("filename", f"file.{mime_type.split('/')[-1] if '/' in mime_type else 'dat'}")

                if media_id:
                    logger.critical(f"📎 Media message detected: {message_type}, ID: {media_id}")
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
                        logger.critical(f"✅ Media processing task queued for {from_number}")

                    except Exception as e:
                        logger.error(f"❌ Error handling media ID {media_id}: {e}", exc_info=True)
                        await send_meta_whatsapp_message(from_number, "Samahani, kuna hitilafu imetokea wakati tukipakia faili lako.")

            elif message_type == "interactive":
                logger.critical(f"💬 Received Interactive message from {from_number}")
                
            else:
                logger.critical(f"⚠️ Received unhandled message type: {message_type} from {from_number}")
                
        return PlainTextResponse("OK")

    except Exception as e:
        logger.critical(f"🚨 Webhook Error: {e}", exc_info=True)
        return PlainTextResponse("Internal Server Error", status_code=500)
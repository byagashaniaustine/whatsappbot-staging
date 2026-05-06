import os
import uuid 
import logging
import requests
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv 
from services.supabase import get_session_phone_by_id
load_dotenv()

# -----------------------------------
# LOGGER SETUP
# -----------------------------------
logger = logging.getLogger("meta_service")
logger.setLevel(logging.INFO)

# -----------------------------------
# ENVIRONMENT VARIABLES
# -----------------------------------
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID")

# WhatsApp Cloud API version (Using the latest version in your code)
API_VERSION = "v25.0" 

API_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
MEDIA_API_BASE_URL = f"https://graph.facebook.com/{API_VERSION}/"

logger.info(f"*** DEBUG: Using PHONE_NUMBER_ID: {PHONE_NUMBER_ID} for API_URL: {API_URL}")

# ==============================================================
# SEND SIMPLE WHATSAPP TEXT MESSAGE (UNCHANGED)
# ==============================================================
async def send_meta_whatsapp_message(to: str, body: str) -> Dict[str, Any]:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise EnvironmentError("META_ACCESS_TOKEN or WA_PHONE_NUMBER_ID missing.")

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"✅ Text message sent to {to}.")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error sending message to {to}: {e}")
        raise RuntimeError(f"Meta API call failed: {e}")

# ==============================================================
# SEND WHATSAPP TEMPLATE MESSAGE WITH FLOW BUTTON (UNCHANGED)
# ==============================================================
async def send_manka_menu_01(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Send a WhatsApp template message.
    """
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise EnvironmentError("META_ACCESS_TOKEN or WA_PHONE_NUMBER_ID missing.")

    # Normalize phone number - remove + if present
    to = to.replace("+", "")

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code}
        }
    }

    # Add components if provided
    if components:
        payload["template"]["components"] = components

    try:
        logger.info(f"🚀 Sending Template '{template_name}' to {to}")
        
        response = requests.post(API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        logger.info(f"✅ Template sent successfully.")
        return response.json()
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP Error sending template to {to}: {e}")
        logger.error(f"Response: {e.response.text if e.response else 'No response'}")
        raise RuntimeError(f"Meta Template API HTTP error: {e}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Template send error for {to}: {e}")
        raise RuntimeError(f"Meta Template API call failed: {e}")

# ==============================================================
# SEND MANKA MENU TEMPLATE (IMPROVED FOR FLOW TOKEN) (UNCHANGED)
# ==============================================================
async def send_manka_menu_template(to: str,template_name: str, flow_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Send the manka_menu template with flow button, embedding a unique flow_token (UUID).
    """
    final_flow_token = flow_token if flow_token else "unused"

    logger.critical(f"🔑 Embedding flow_token into template: {final_flow_token}")

    components = [
        {
            "type": "button",
            "sub_type": "flow",
            "index": "0",
            "parameters": [
                {
                    "type": "action",
                    "action": {
                        "flow_token": final_flow_token, 
                        "flow_action_data": {
                            "screen": "MAIN_MENU"
                        }
                    }
                }
            ]
        }
    ]
    
    return await send_manka_menu_01(
        to=to,
        template_name=template_name,
        language_code="en",
        components=components
    )

async def send_mtaa_wa_manka_template(to: str):
    to = to.replace("+", "").strip()
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": "mtaa_wa_manka03",
            "language": {
                "code": "en" 
            },
            "components": [] # LAZIMA iwe tupu kwa sababu template haina mabano ya {{1}}
        }
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"❌ Kosa la WhatsApp API: {response.text}")
        
        response.raise_for_status()
        logger.info(f"✅ Ujumbe umetumwa kwa {to}")
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}
# ==============================================================
# GET MEDIA DOWNLOAD URL (UNCHANGED)
# ==============================================================
def get_media_url(media_id: str) -> str:
    """
    Get the download URL for a media file from WhatsApp.
    """
    if not ACCESS_TOKEN:
        raise EnvironmentError("META_ACCESS_TOKEN missing for media lookup.")

    url = f"{MEDIA_API_BASE_URL}{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    try:
        logger.info(f"📥 Fetching media URL for ID {media_id}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        download_url = data.get("url")
        if not download_url:
            raise RuntimeError(f"No URL returned for media_id {media_id}. Response: {data}")

        logger.info("✅ Media URL retrieved successfully")
        return download_url
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Media URL lookup failed: {e}")
        raise RuntimeError(f"Media URL lookup failed: {e}")
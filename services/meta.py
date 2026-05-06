import os
import logging
import requests
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("meta_service")
logger.setLevel(logging.INFO)

API_VERSION = "v25.0"

# --------------------------------------------------
# CREDENTIALS
# --------------------------------------------------
# ElimuFedha — uses ELIMUFEDHA_ACCESS_TOKEN / ELIMUFEDHA_PHONE_NUMBER_ID from .env
ELIMUFEDHA_TOKEN    = os.getenv("ELIMUFEDHA_ACCESS_TOKEN")
ELIMUFEDHA_PHONE_ID = os.getenv("ELIMUFEDHA_PHONE_NUMBER_ID")

# Kopagari — separate WhatsApp number
KOPAGARI_TOKEN    = os.getenv("KOPAGARI_ACCESS_TOKEN")
KOPAGARI_PHONE_ID = os.getenv("KOPAGARI_PHONE_NUMBER_ID")


def _api_url(phone_id: str) -> str:
    return f"https://graph.facebook.com/{API_VERSION}/{phone_id}/messages"


# ==============================================================
# INTERNAL HELPERS
# ==============================================================

async def _send_text(to: str, body: str, token: str, phone_id: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    try:
        response = requests.post(_api_url(phone_id), json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"✅ Text message sent to {to}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error sending message to {to}: {e}")
        raise RuntimeError(f"Meta API call failed: {e}")


async def _send_template(
    to: str,
    template_name: str,
    language_code: str,
    components: List[Dict[str, Any]],
    token: str,
    phone_id: str
) -> Dict[str, Any]:
    to = to.replace("+", "")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components
        }
    }
    try:
        logger.info(f"🚀 Sending template '{template_name}' to {to}")
        response = requests.post(_api_url(phone_id), json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"✅ Template '{template_name}' sent successfully")
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP error sending template to {to}: {e.response.text if e.response else e}")
        raise RuntimeError(f"Meta Template API HTTP error: {e}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Template send error for {to}: {e}")
        raise RuntimeError(f"Meta Template API call failed: {e}")


# ==============================================================
# ELIMUFEDHA — /webhook/ElimuFedha
# ==============================================================

async def send_meta_whatsapp_message(to: str, body: str) -> Dict[str, Any]:
    """Send plain text message via ElimuFedha number."""
    return await _send_text(to, body, ELIMUFEDHA_TOKEN, ELIMUFEDHA_PHONE_ID)


async def send_manka_menu_01(to: str, template_name: str, language_code: str = "en") -> Dict[str, Any]:
    """Send a template (no flow button) via ElimuFedha number."""
    return await _send_template(to, template_name, language_code, [], ELIMUFEDHA_TOKEN, ELIMUFEDHA_PHONE_ID)


async def send_mtaa_wa_manka_template(to: str) -> Dict[str, Any]:
    """Send mtaa_wa_manka03 template via ElimuFedha number."""
    return await _send_template(to, "mtaa_wa_manka03", "en", [], ELIMUFEDHA_TOKEN, ELIMUFEDHA_PHONE_ID)


# ==============================================================
# KOPAGARI — /kopagari-webhook/
# ==============================================================

async def send_kopagari_message(to: str, body: str) -> Dict[str, Any]:
    """Send plain text message via Kopagari number."""
    return await _send_text(to, body, KOPAGARI_TOKEN, KOPAGARI_PHONE_ID)


async def send_kopagari_flow_template(to: str, template_name: str, flow_token: Optional[str] = None) -> Dict[str, Any]:
    """Send a Flow-button template via Kopagari number."""
    final_flow_token = flow_token or "unused"
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
                        "flow_action_data": {"screen": "MAIN_MENU"}
                    }
                }
            ]
        }
    ]
    return await _send_template(to, template_name, "en", components, KOPAGARI_TOKEN, KOPAGARI_PHONE_ID)


async def send_kopagari_mtaa_template(to: str) -> Dict[str, Any]:
    """Send mtaa_wa_manka03 template via Kopagari number."""
    return await _send_template(to, "mtaa_wa_manka03", "en", [], KOPAGARI_TOKEN, KOPAGARI_PHONE_ID)


# ==============================================================
# MEDIA — Kopagari (file uploads arrive via Kopagari webhook)
# ==============================================================

def get_media_url(media_id: str) -> str:
    """Get the download URL for a media file sent to the ElimuFedha number."""
    if not ELIMUFEDHA_TOKEN:
        raise EnvironmentError("ELIMUFEDHA_ACCESS_TOKEN missing for media lookup.")

    url = f"https://graph.facebook.com/{API_VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {ELIMUFEDHA_TOKEN}"}

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

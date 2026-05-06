import os
import uuid
import logging
from supabase import create_client, Client
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # NOTE: In a real environment, this should raise an error immediately.
    # We will log a warning for this self-contained example.
    logger.warning("❌ Supabase credentials missing. Using placeholder client.")
    # Placeholder for running the code without environment variables set
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
PDF_TYPE = "application/pdf"


async def store_session_data(
    phone_number: str,
    message: str,
    session_id: Optional[str] = None # Accepts the pre-generated UUID
) -> Optional[str]:
    """
    Creates a new UUID session row in Whatsapp_sessions.
    Returns the session_id string (UUID).
    """
    if not phone_number:
        logger.error("❌ phone_number missing. Session not saved.")
        return None

    # Use the provided session_id (UUID from whatsappBOT.py) or generate a new one
    final_session_id = session_id if session_id else str(uuid.uuid4())

    session_record = {
        "session_id": final_session_id,
        "phone_number": phone_number,
        "latest_message": message,
        "status": "active"
    }

    try:
        response = supabase.table("whatsapp_sessions").insert(session_record).execute()

        if getattr(response, "data", None):
            logger.info(f"✅ Session stored for {phone_number} (ID: {final_session_id})")
            return final_session_id

        logger.error("❌ Supabase insert returned no data.")
        return None

    except Exception as e:
        logger.error(f"❌ Failed to store session: {e}")
        return None


async def get_session_phone_by_id(session_id: str) -> Optional[str]:
    """
    Retrieves the phone number tied to a session_id (UUID/Flow Token).
    """
    try:
        response = (
            supabase.table("whatsapp_sessions")
            .select("phone_number")
            .eq("session_id", session_id)
            .single()
            .execute()
        )

        if getattr(response, "data", None):
            phone = response.data.get("phone_number")
            logger.info(f"📲 Retrieved phone ({phone}) for session: {session_id}")
            return phone

        return None

    except Exception as e:
        logger.error(f"❌ Error retrieving phone by session ID: {e}")
        return None


# --- The rest of the functions (like store_file) are omitted for brevity, 
# but they would follow the pattern you provided. ---

def store_file(
    user_id: str,
    user_name: str,
    user_phone: str,
    flow_type: str,
    file_name: str,
    file_data: bytes,
    mime_type: str,
) -> dict | None:
    """
    Uploads user file to Supabase Storage + logs metadata.
    Each file path includes a UUID to prevent duplicates.
    """
    try:
        # Generate a unique filename prefix
        unique_prefix = uuid.uuid4().hex
        supabase_path = f"{user_id}/{unique_prefix}_{file_name}"

        # Validate MIME type
        IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        PDF_TYPE = "application/pdf"
        if mime_type not in IMAGE_TYPES + [PDF_TYPE]:
            raise ValueError(f"🚫 Unsupported file type: {mime_type}")

        # Upload to Supabase
        upload_result = supabase.storage.from_("whatsapp_files").upload(
            supabase_path,
            file_data,
            {"content-type": mime_type},
        )

        # Get public URL
        public_url = supabase.storage.from_("whatsapp_files").get_public_url(supabase_path)

        # Insert metadata into database
        metadata = {
            "user_id": user_id,
            "user_name": user_name,
            "user_phone": user_phone,
            "flow_type": flow_type,
            "file_type": mime_type,
            "file_url": public_url,
        }

        supabase.table("wHatsappUsers").insert(metadata).execute()

        logger.info(f"✅ File stored successfully: {supabase_path}")
        return {"file_url": public_url, "file_type": mime_type}

    except Exception as e:
        logger.exception(f"❌ File storage failed for {user_phone}: {e}")
        return None
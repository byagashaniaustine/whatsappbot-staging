import logging
import mimetypes
import requests
import uuid
import os
from services.supabase import store_file
from services.gemini import analyze_image
from services.pdfendpoint import analyze_pdf
from services.meta import send_meta_whatsapp_message
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
ALLOWED_PDF_TYPE = "application/pdf"

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")


async def process_file_upload(
    user_id: str,
    user_name: str,
    user_phone: str,
    flow_type: str,
    media_url: str,
    mime_type: str,
    file_name: str = None
):
    try:
        logger.info(f"Processing file upload: MIME={mime_type}, URL={media_url}")

        if not META_ACCESS_TOKEN:
            error_msg = "Meta Access Token not set. Cannot download media."
            logger.error(error_msg)
            await   send_meta_whatsapp_message(user_phone, f"❌ {error_msg}")
            return {"status": "error", "message": error_msg}

        # Download file from Meta
        response = requests.get(media_url, headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"})
        response.raise_for_status()
        file_data = response.content

        # Determine file extension
        ext = mimetypes.guess_extension(mime_type) if mime_type else ".bin"
        if not file_name:
            file_name = f"{user_id}_{uuid.uuid4()}{ext}"

        # Inform user that file is received
        await send_meta_whatsapp_message(user_phone, "Faili yako imepokelewa, tafadhali subiri uchambuzi.")

        analysis_summary = None

        # PDF Analysis
        if mime_type == ALLOWED_PDF_TYPE:
            logger.info("Starting PDF analysis...")
            result = analyze_pdf(file_data, file_name, user_name)
            # If Manka fails, fallback handled inside analyze_pdf
            if isinstance(result, dict):
                summary = result.get("summary", "")
            else:
                summary = str(result)

            # Check for first analysis failure
            if "INSUFFICIENT DATA" in summary or "unexpected" in summary.lower():
                await send_meta_whatsapp_message(user_phone, "Uchambuzi wa kwanza umefeli, tafadhali subiri uchambuzi wa pili.")
                analysis_summary = "Tafadhali subiri uchambuzi wa pili."
            else:
                analysis_summary = f"📄 PDF Analysis Complete\n\n{summary}"

        # Image Analysis
        elif mime_type in ALLOWED_IMAGE_TYPES:
            logger.info("Starting image analysis...")
            result = analyze_image(file_data, mime_type)
            summary = result.get("summary") if isinstance(result, dict) else str(result)
            analysis_summary = f"🖼️ Image Analysis Complete\n\n{summary}"

        # Unsupported MIME
        else:
            message = f"Unsupported file type ({mime_type}). Please send PDF or image (JPG/PNG/WEBP)."
            await send_meta_whatsapp_message(user_phone, message)
            return {"status": "unsupported", "message": message}

        # Store file in Supabase
        logger.info("Storing file in Supabase...")
        stored_result = store_file(
            user_id=user_id,
            user_name=user_name,
            user_phone=user_phone,
            flow_type=flow_type,
            file_data=file_data,
            mime_type=mime_type,
            file_name=file_name
        )

        if not stored_result or 'file_url' not in stored_result:
            raise Exception("Failed to store file or retrieve public URL.")

        stored_url = stored_result['file_url']
        logger.info(f"File stored successfully at {stored_url}")

        # Send final analysis message if exists
        if analysis_summary:
            await send_meta_whatsapp_message(user_phone, analysis_summary)

        return {"status": "success", "summary": analysis_summary, "file_url": stored_url}

    except requests.exceptions.HTTPError as he:
        error_msg = f"HTTP error downloading file (status {he.response.status_code})"
        logger.exception(error_msg)
        await send_meta_whatsapp_message(user_phone, "Kumekuwa na shida kupakua faili yako. Tafadhali jaribu tena.")
        return {"status": "error", "message": error_msg}

    except Exception as e:
        logger.exception(f"Error processing file: {e}")
        await send_meta_whatsapp_message(user_phone, f" Tatizo lilitokea wakati wa uchambuzi wa faili yako:")
        return {"status": "error", "message": str(e)}

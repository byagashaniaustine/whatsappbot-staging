import os
import logging
from google import genai
from google.genai.errors import APIError
from google.genai.types import Part
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# --- Gemini Client Initialization ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable not found.")
    client = genai.Client(api_key=api_key)
except Exception as e:
    raise EnvironmentError(
        f"Failed to initialize Gemini Client. Ensure your API key is set correctly. Error: {e}"
    )

# --- Constants ---
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
MODEL_NAME = "gemini-2.5-flash"

# -------------------------------------------------
# 🔹 Function 1: Analyze Image
# -------------------------------------------------
def analyze_image(image_bytes: bytes, mime_type: str) -> str:
    """
    Analyzes an image and returns a concise Swahili description.
    """
    try:
        if mime_type not in ALLOWED_IMAGE_TYPES:
            exts = [t.split('/')[1] for t in ALLOWED_IMAGE_TYPES if t != 'image/jpg']
            return f" Ingizo la picha la aina ya '{mime_type}' haliruhusiwi. Tumia moja ya: {', '.join(exts)}."

        image_part = Part.from_bytes(data=image_bytes, mime_type=mime_type)
        prompt = "Fafanua picha hii kwa lugha ya Kiswahili, usizidi herufi 400."

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, image_part],
        )

        return response.text or " Gemini haikurejesha maelezo yoyote."

    except APIError:
        return " Hitilafu ya API ya Gemini."
    except Exception as e:
        logger.error(f"General Error analyzing image: {e}", exc_info=True)
        return " Hitilafu ya Jumla katika kuchambua picha."



def analyze_file_with_gemini(file_data: bytes, filename: str) -> str:
    try:
        file_part = Part.from_bytes(data=file_data, mime_type="application/pdf")

        system_prompt = (
            "Wewe ni msaidizi wa uchambuzi wa nyaraka. "
            "Chambua hati ya kifedha iliyoambatanishwa ili kufupisha chanzo cha mapato, "
            "kadirio la kipato cha kila mwezi, na madeni makubwa ya mara kwa mara. "
            "Toa majibu kwa ufupi kwa lugha ya Kiswahili."
        )

        user_prompt = (
            f"Chambua faili lenye jina '{filename}'. "
            "Toa muhtasari wa taarifa za kifedha (mapato, madeni, uwezo wa kukopa). "
            "Kama ni hati ya utambulisho (mfano NIDA au kitambulisho kingine), eleza hivyo wazi."
        )

        parts = [
        Part.from_text(text=system_prompt),
        Part.from_text(text=user_prompt),
        file_part
        ]

        response = client.models.generate_content(
        model=MODEL_NAME,
        contents=parts
       )
        result_text = getattr(response, "text", None)
        if not result_text:
         return " Gemini haikurejesha maelezo yoyote."

        return result_text

    except APIError as e:
        logger.error(f"Gemini API Error: {e}", exc_info=True)
        return " Hitilafu ya API ya Gemini: Udadisi wa nyaraka umeshindwa."
    except Exception as e:
        logger.exception(f"General Error during Gemini PDF analysis: {e}")
        return f" Hitilafu ya Jumla katika kuchambua faili '{filename}'. Tafadhali jaribu tena."

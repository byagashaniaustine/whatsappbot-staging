import os
import requests
import logging
from services.gemini import analyze_file_with_gemini  # fallback
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)

MANKA_API_KEY = os.getenv("MANKA_API_KEY")
MANKA_ENDPOINT = os.getenv("MANKA_ENDPOINT")
if not MANKA_API_KEY or not MANKA_ENDPOINT:
    logger.warning(
        "MANKA_API_KEY or MANKA_ENDPOINT not set. Only Gemini fallback will be functional."
    )


def analyze_pdf(file_data: bytes, filename: str, user_fullname: str) -> str:
    """
    Attempts analysis with Manka. Falls back to Gemini on failure.
    Returns a Swahili message to the user.
    """
    try:
        if not MANKA_API_KEY or not MANKA_ENDPOINT:
            raise EnvironmentError("Manka environment variables are missing.")

        headers = {"Authorization": f"Bearer {MANKA_API_KEY.strip()}"}
        data = {"fullname": user_fullname}
        files = {"file": (filename, file_data, "application/pdf")}

        response = requests.post(
            str(MANKA_ENDPOINT), headers=headers, data=data, files=files, timeout=60
        )

        if not response.ok:
            logger.error(f"MANKA FAILED (HTTP {response.status_code}): {response.text[:100]}")
            return (
                "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
                "\n\n" + analyze_file_with_gemini(file_data, filename)
            )

        response_data = response.json()
        affordability_data = response_data.get("affordability_scores")

        if affordability_data is None:
            logger.error("Manka response missing 'affordability_scores' key.")
            return (
                "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
                "\n\n" + analyze_file_with_gemini(file_data, filename)
            )

        # Process Manka results
        if isinstance(affordability_data, str):
            return (
                "Taarifa hizo hazitoshi kutafuta uwezo wa mkopo (INSUFFICIENT DATA)\n"
                "---------------------------------------------\n\n"
                "Hatukuweza kujua viwango vyako vya mkopo kwa sababu taarifa zilizokusanywa "
                "ni za chini ya miezi 3.\n"
                "Tafadhali wasilisha taarifa inayoonyesha historia ya miezi 3 kamili au zaidi ya miamala."
            )

        elif isinstance(affordability_data, dict):
            high_risk = affordability_data.get("high", 0.0)
            medium_risk = affordability_data.get("moderate", 0.0)
            low_risk = affordability_data.get("low", 0.0)
            max_credit = max(high_risk, medium_risk, low_risk)

            return (
                f"TZS {'{0:,.0f}'.format(max_credit)} (Kulingana na uchambuzi wa taarifa zako, kiwango chako cha juu) TZS {'{0:,.0f}'.format(high_risk)}\n"
                f"Na kiwango chako cha chini ni TZS {'{0:,.0f}'.format(low_risk)}\n\n"
                "Tunapendekeza uanze na kiwango cha chini kwa urejeshaji wa haraka; "
                "kiwango cha mkopo kitakavyoongezeka kadiri unavyorejesha."
            )

        else:
            logger.error(f"Unexpected data type from Manka: {type(affordability_data)}")
            return (
                "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
                "\n\n" + analyze_file_with_gemini(file_data, filename)
            )

    except requests.exceptions.Timeout:
        logger.error("Manka API timed out.")
        return (
            "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
            "\n\n" + analyze_file_with_gemini(file_data, filename)
        )

    except EnvironmentError as e:
        logger.error(f"Manka Config Error: {e}")
        return (
            "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
            "\n\n" + analyze_file_with_gemini(file_data, filename)
        )

    except Exception as e:
        logger.exception(f"General Error analyzing PDF with Manka: {e}")
        return (
            "Uchambuzi wa kwanza umefaulu, tafadhali subiri uchambuzi wa pili."
            "\n\n" + analyze_file_with_gemini(file_data, filename)
        )

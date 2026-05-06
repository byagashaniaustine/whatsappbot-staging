import os
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
import base64

logger = logging.getLogger("mail_service")
logging.basicConfig(level=logging.INFO)

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

creds = Credentials.from_authorized_user_file('token.json', SCOPES)
service = build('gmail', 'v1', credentials=creds)

COMPANY_EMAIL = os.getenv("COMPANY_EMAIL")
CC_EMAILS = os.getenv("CC_EMAILS")  # comma separated
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

def create_message(sender, to, subject, body_text, cc=None):
    message = MIMEText(body_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject

    if cc:
        message['cc'] = cc

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


def send_email_to_company(user_data):
    try:
        logger.info("📧 EMAIL FUNCTION STARTED")

        user_email = user_data.get("email")
        rating = user_data.get("rating")
        comment = user_data.get("comment")

        # ==============================
        # 📩 Email to Company (with CC)
        # ==============================
        company_subject = "New whatsapp bot Service Rating Submitted"
        company_body = f"""
New Rating Submitted,
From,{user_email}

Has submitted a new whatsapp bot service rating of {rating} ratings and left the following comment "{comment}"
        """

        company_message = create_message(
            sender=SENDER_EMAIL,
            to=COMPANY_EMAIL,
            subject=company_subject,
            body_text=company_body,
            cc=CC_EMAILS
        )

        sent_to_company = service.users().messages().send(
            userId="me",
            body=company_message
        ).execute()

        logger.info(f"✅ Company email sent successfully: Message ID {sent_to_company['id']}")

        # ==============================
        # 📩 Confirmation Email to User
        # ==============================
        user_subject = "Thank you for your feedback!"
        user_body = f"""
Hello {user_email},

Thank you for submitting your service rating!

Here is what we received from you:
Rating: {rating}
Comment: {comment}

We appreciate your feedback, and we will get back to you soon.

Best regards,
Company Team
        """

        user_message = create_message(
            sender=SENDER_EMAIL,
            to=user_email,
            subject=user_subject,
            body_text=user_body
        )

        sent_to_user = service.users().messages().send(
            userId="me",
            body=user_message
        ).execute()

        logger.info(f"✅ Confirmation email sent to user: Message ID {sent_to_user['id']}")

    except HttpError as error:
        logger.error(f"❌ Gmail API error: {error}")
    except Exception as e:
        logger.error(f"❌ Email sending failed: {e}")

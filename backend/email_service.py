import smtplib
import logging

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
logger = logging.getLogger(__name__)

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def send_email_notification(recipient_email, user_name, reminder_text, reminder_time):
    try:
        subject = f"Reminder: {reminder_text}"

        body = f"""
Hi {user_name},

This is a reminder from AI Personal Assistant.

Task: {reminder_text}
Time: {reminder_time}

Have a great day!

Best regards,
AI Personal Assistant
"""

        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(
                EMAIL_ADDRESS,
                recipient_email,
                msg.as_string()
            )

        logger.info(f"Reminder email sent to {recipient_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send reminder email: {e}")
        return False
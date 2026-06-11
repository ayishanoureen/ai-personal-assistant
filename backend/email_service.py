import os
import resend
import logging

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY")

if not resend.api_key:
    logger.warning("RESEND_API_KEY is not set. Email notifications will fail.")


def send_email_notification(
    recipient_email: str,
    user_name: str,
    reminder_text: str,
    reminder_time: str
) -> bool:

    if not resend.api_key:
        logger.error("Cannot send email. Resend API key is missing.")
        return False

    subject = f"🔔 Reminder: {reminder_text}"

    plain_body = f"""
Hi {user_name},

This is a reminder from your AI Personal Assistant.

Task: {reminder_text}
Scheduled Time: {reminder_time}

Have a great and productive day!

Best regards,
AI Personal Assistant
"""

    html_body = f"""
    <html>
        <body>
            <h2>Reminder Notification</h2>
            <p>Hello {user_name},</p>
            <p>This is your reminder:</p>

            <p><b>Task:</b> {reminder_text}</p>
            <p><b>Time:</b> {reminder_time}</p>

            <p>Have a productive day!</p>
        </body>
    </html>
    """

    try:
        logger.info(f"Sending email via Resend to {recipient_email}")

        response = resend.Emails.send({
            "from": "AI Assistant <onboarding@resend.dev>",  
            "to": [recipient_email],
            "subject": subject,
            "text": plain_body,
            "html": html_body,
        })

        logger.info(f"Resend response: {response}")
        return True

    except Exception as e:
        logger.exception(f"Failed to send email via Resend: {e}")
        return False
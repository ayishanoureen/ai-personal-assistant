import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    logger.warning("EMAIL_ADDRESS or EMAIL_PASSWORD environment variables are not set. Email notifications will fail.")

def send_email_notification(recipient_email: str, user_name: str, reminder_text: str, reminder_time: str) -> bool:
 
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.error("Cannot send email. SMTP credentials are not configured.")
        return False

    try:
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
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reminder Notification</title>
            <style>
                body {{
                    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
                    background-color: #f3f4f6;
                    margin: 0;
                    padding: 0;
                    -webkit-font-smoothing: antialiased;
                }}
                .wrapper {{
                    width: 100%;
                    background-color: #f3f4f6;
                    padding: 30px 0;
                }}
                .container {{
                    max-width: 550px;
                    margin: 0 auto;
                    background-color: #ffffff;
                    border-radius: 16px;
                    overflow: hidden;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
                }}
                .header {{
                    background: linear-gradient(135deg, #4f46e5, #7c3aed);
                    color: #ffffff;
                    padding: 35px 25px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 24px;
                    font-weight: 700;
                    letter-spacing: -0.025em;
                }}
                .content {{
                    padding: 35px 30px;
                    color: #374151;
                    line-height: 1.6;
                }}
                .greeting {{
                    font-size: 18px;
                    font-weight: 600;
                    color: #111827;
                    margin-bottom: 15px;
                }}
                .reminder-card {{
                    background-color: #f9fafb;
                    border-left: 4px solid #4f46e5;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 25px 0;
                }}
                .label {{
                    font-size: 11px;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    color: #6b7280;
                    margin-bottom: 4px;
                    font-weight: 700;
                }}
                .value {{
                    font-size: 16px;
                    font-weight: 500;
                    color: #1f2937;
                    margin-bottom: 15px;
                }}
                .value:last-child {{
                    margin-bottom: 0;
                }}
                .footer {{
                    background-color: #f9fafb;
                    padding: 25px;
                    text-align: center;
                    font-size: 12px;
                    color: #9ca3af;
                    border-top: 1px solid #f3f4f6;
                }}
            </style>
        </head>
        <body>
            <div class="wrapper">
                <div class="container">
                    <div class="header">
                        <h1>Reminder Notification</h1>
                    </div>
                    <div class="content">
                        <div class="greeting">Hello {user_name},</div>
                        <p>This is a friendly alert from your AI Personal Assistant. Here is your scheduled task detail:</p>
                        
                        <div class="reminder-card">
                            <div class="label">Task / Reminder</div>
                            <div class="value" style="font-size: 17px; color: #111827; font-weight: 600;">{reminder_text}</div>
                            
                            <div class="label" style="margin-top: 15px;">Scheduled Time (IST)</div>
                            <div class="value" style="color: #4f46e5;">{reminder_time}</div>
                        </div>
                        
                        <p style="margin-bottom: 0;">Have a wonderful and productive day ahead!</p>
                    </div>
                    <div class="footer">
                        Sent automatically by AI Personal Assistant.<br>
                        &copy; 2026 AI Personal Assistant. All rights reserved.
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = recipient_email
        msg["Subject"] = subject

        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        try:
            logger.info("Opening SMTP connection...")

            server = smtplib.SMTP_SSL(
                "smtp.gmail.com",
                465,
                timeout=30
            )

            logger.info("SMTP connected")

            logger.info(f"Logging in as {EMAIL_ADDRESS}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

            logger.info("Logged in successfully")

            logger.info(f"Sending mail to {recipient_email}")

            server.sendmail(
                EMAIL_ADDRESS,
                recipient_email,
                msg.as_string()
            )

            logger.info("Email sent successfully")

            server.quit()

            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.exception(f"SMTP Authentication Error: {e}")
            return False

        except smtplib.SMTPConnectError as e:
            logger.exception(f"SMTP Connect Error: {e}")
            return False

        except TimeoutError as e:
            logger.exception(f"SMTP Timeout Error: {e}")
            return False

        except OSError as e:
            logger.exception(f"Network Error: {e}")
            return False

        except Exception as e:
            logger.exception(f"General SMTP Error: {e}")
            return False

        finally:
            try:
                server.quit()
            except:
                pass
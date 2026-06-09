from fastapi import FastAPI, HTTPException, status, BackgroundTasks, UploadFile, File, Form, Header, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore, auth
from dotenv import load_dotenv
import os
import logging
from PIL import Image
import io
import json
import re
import datetime
import asyncio
import difflib
from scheduler import start_scheduler, calculate_next_occurrence_datetime, WEEKDAY_MAP
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import timezone
import smtplib
from email.mime.text import MIMEText 
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

scheduler = BackgroundScheduler()
router = APIRouter()

async def get_current_user(authorization: str = Header(None)):
    if not authorization: 
        raise HTTPException(401, "Not authenticated")
    token = authorization.replace("Bearer ", "")
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(401, "Invaid token")

def validate_gemini_response(response_dict: dict) -> dict:
    if not isinstance(response_dict, dict):
        response_dict = {}
    return {
        "title": str(response_dict.get("title") or "AI Response"),
        "summary": str(response_dict.get("summary") or "Here is what I found to help you."),
        "details": list(response_dict.get("details") or [])
    }

def extract_json(text):
    res = {}
    try:
        res = json.loads(text)
    except:
        cleaned = re.sub(r"```json|```", "", text).strip()
        try:
            res = json.loads(cleaned)
        except:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    res = json.loads(match.group())
                except:
                    pass
    if not isinstance(res, dict):
        res = {"summary": str(res)}
    return validate_gemini_response(res)

async def extract_memory_with_gemini(user_message: str):
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = f"""
You are a memory extraction system.

Extract ONLY long-term useful memory from the user's message.

Examples:
- name
- likes
- dislikes
- goals
- hobbies
- profession
- preferences

IMPORTANT:
- Return ONLY pure JSON
- No markdown
- No explanation
- No extra text
- If nothing useful exists, return {{}}

Examples:

User: My name is Ayisha
Output:
{{"name":"Ayisha"}}

User: I love machine learning
Output:
{{"interest":"machine learning"}}

User: hello
Output:
{{}}

User message:
{user_message}
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = response.text.strip()
        text = re.sub(r"```json|```", "", text).strip()
        try:
            memory_data = json.loads(text)
            if isinstance(memory_data, dict):
                return memory_data
        except:
             pass
    except Exception as e:
        logger.error(f"Gemini memory extraction error: {e}")
    return {}

async def summarize_text_with_gemini(text: str):
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = f"""
Summarize the following text clearly and concisely.

Rules:
- Keep important information
- Make it short and readable
- Use simple language
- Maximum 8 sentences

Text:
{text}
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        summary = response.text.strip()
        return summary
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return None

def save_user_memory(uid: str, memory_data: dict):
    if not firebase_initialized or not db:
        return {}
    try: 
        doc_ref = db.collection("users").document(uid).collection("memory").document("profile")
        existing_doc = doc_ref.get()
        old_memory = {}
        if existing_doc.exists:
            old_memory = existing_doc.to_dict()
        updated_memory = {
            **old_memory,
            **memory_data
        }
        doc_ref.set(updated_memory)
    except Exception as e:
        logger.error(f"Error saving user memory: {e}")

def load_user_memory(uid: str):

    if not firebase_initialized or not db:
        return {}
    try:
        doc_ref = db.collection("users").document(uid).collection("memory").document("profile")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        logger.error(f"Error loading memory: {e}")
    return {}

async def classify_intent_with_gemini(message: str):

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)

        prompt = f"""
You are an intent classifier.

Classify the user's intent.

Possible intents:
- save_reminder
- get_reminders
- delete_single_reminder
- delete_all_reminders
- save_note
- get_notes
- delete_single_note
- delete_all_notes
- summarize_and_save
- extract_tasks_from_image
- extract_text_and_save_note
- stop_repeating_reminder
- normal_chat

IMPORTANT:
- Return ONLY valid JSON
- No markdown
- No explanation
- No extra text

Format:
{{
  "intent": "intent_name"
}}

User message:
{message}
"""

        response = await asyncio.to_thread(model.generate_content, prompt)

        text = response.text.strip()

        text = re.sub(r"```json|```", "", text).strip()

        data = json.loads(text)

        return data.get("intent", "normal_chat")

    except Exception as e:
        logger.error(f"Intent classification error: {e}")
        return "normal_chat"


def normalize_time(time_str: str) -> str:
    if not time_str:
        return ""
    t = time_str.lower().strip()

    match = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', t)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        period = match.group(3).upper()
        if hour > 12:
            hour = hour - 12
        elif hour == 0:
            hour = 12
        return f"{hour:02d}:{minute:02d} {period}"

    match_24 = re.search(r'\b(\d{1,2}):(\d{2})\b', t)
    if match_24:
        hour = int(match_24.group(1))
        minute = int(match_24.group(2))
        period = "AM"
        if hour >= 12:
            period = "PM"
            if hour > 12:
                hour = hour - 12
        elif hour == 0:
            hour = 12
        return f"{hour:02d}:{minute:02d} {period}"
        
    return time_str.strip()


def normalize_reminder_text(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    
    phrases = [
        "save a reminder to", "remind me to", "add reminder to", "set reminder to",
        "save a reminder for", "remind me for", "add reminder for", "set reminder for",
        "save a reminder", "remind me", "add reminder", "set reminder"
    ]
    for phrase in sorted(phrases, key=len, reverse=True):
        if t.startswith(phrase):
            t = t[len(phrase):].strip()
            break
            
    t = re.sub(r'^(to|for|at|on)\s+', '', t)
    t = re.sub(r'\s+(to|for|at|on)$', '', t)

    t = re.sub(r'[?.!,]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def is_fuzzy_match(str1: str, str2: str, threshold: float = 0.8) -> bool:
    norm1 = normalize_reminder_text(str1)
    norm2 = normalize_reminder_text(str2)
    if not norm1 or not norm2:
        return False
    if norm1 == norm2:
        return True
    ratio = difflib.SequenceMatcher(None, norm1, norm2).ratio()
    return ratio >= threshold


def detect_intent_locally(message: str) -> str | None:
    m = message.lower().strip()
    if re.search(r'\b(delete|remove|clear|cancel)\s+all\s+reminders\b', m):
        return "delete_all_reminders"
        
    if re.search(r'\b(delete|remove|clear)\s+all\s+notes\b', m):
        return "delete_all_notes"
        
    if re.search(r'\b(delete|remove|clear|cancel)\s+(?:the\s+)?reminder\b', m):
        return "delete_single_reminder"
        
    if re.search(r'\b(delete|remove|clear)\s+(?:the\s+)?note\b', m):
        return "delete_single_note"
        
    if re.search(r'\b(show|get|list|view|what\s+are|display)\s+reminders\b', m):
        return "get_reminders"
        
    if re.search(r'\b(show|get|list|view|what\s+are|display)\s+notes\b', m):
        return "get_notes"
        
    if re.search(r'\b(remind|reminder|set a reminder|save a reminder|add a reminder|add reminder)\b', m):
        return "save_reminder"
        
    if re.search(r'\b(save\s+note|add\s+note|take\s+note|write\s+note)\b', m):
        return "save_note"
        
    if re.search(r'\b(summarize|summarise|make\s+a\s+summary|shorten\s+this)\b', m):
        return "summarize_and_save"
    if re.search(r"\b(stop repeating|disable recurrence|one time reminder)\b", m):
        return "stop_repeating_reminder"
        
    return None


def parse_date_robustly(message: str, ref_now: datetime.datetime = None) -> str:
    now = ref_now or datetime.datetime.now()
    message_lower = message.lower()
    days_match = re.search(r'\b(?:in|after)\s+(\d+)\s+days?\b', message_lower)
    if days_match:
        delta_days = int(days_match.group(1))
        return (now + datetime.timedelta(days=delta_days)).strftime("%Y-%m-%d")

    hours_match = re.search(r'\b(?:in|after)\s+(\d+)\s+hours?\b', message_lower)
    if hours_match:
        delta_hours = int(hours_match.group(1))
        return (now + datetime.timedelta(hours=delta_hours)).strftime("%Y-%m-%d")
        
    mins_match = re.search(r'\b(?:in|after)\s+(\d+)\s+(minutes?|mins?)\b', message_lower)
    if mins_match:
        return now.strftime("%Y-%m-%d")

    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_num in weekdays.items():
        if f"next {day_name}" in message_lower:
            today_num = now.weekday()
            days_diff = (day_num - today_num) % 7
            if days_diff == 0:
                days_diff = 7
            days_diff += 7
            return (now + datetime.timedelta(days=days_diff)).strftime("%Y-%m-%d")
        elif day_name in message_lower:
            today_num = now.weekday()
            days_diff = (day_num - today_num) % 7
            if days_diff == 0:
                days_diff = 7
            return (now + datetime.timedelta(days=days_diff)).strftime("%Y-%m-%d")

    exact_date = parse_exact_date(message)
    if exact_date:
        return exact_date
        
    if "tomorrow" in message_lower:
        return (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
    return now.strftime("%Y-%m-%d")


WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def extract_recurrence_and_clean(message: str) -> tuple[dict | None, str]:
    msg_lower = message.lower()
    
    # 1. Weekday shortcut: "every weekday(s)"
    weekday_shortcut_match = re.search(r"\bevery\s+weekdays?\b|\bon\s+weekdays\b", msg_lower)
    if weekday_shortcut_match:
        span = weekday_shortcut_match.span()
        cleaned = message[:span[0]] + message[span[1]:]
        return {
            "repeat_type": "weekday",
            "repeat_interval": 1,
            "repeat_unit": "weekdays",
            "repeat_weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"]
        }, cleaned

    # 2. Weekdays list
    weekday_pattern = r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)s?\b"
    matches = list(re.finditer(weekday_pattern, msg_lower))
    if matches:
        found_weekdays = []
        ends_with_s = False
        for m in matches:
            word = m.group(0)
            base_word = m.group(1)
            found_weekdays.append(WEEKDAY_NAMES[WEEKDAY_MAP[base_word]])
            if word.endswith('s'):
                ends_with_s = True
                
        unique_weekdays = []
        for w in found_weekdays:
            if w not in unique_weekdays:
                unique_weekdays.append(w)
                
        first_start = matches[0].start()
        prefix = msg_lower[max(0, first_start - 15):first_start].strip()
        
        has_recurring_keyword = False
        for kw in ["every", "each", "repeat on", "repeating on", "weekly on"]:
            if kw in prefix:
                has_recurring_keyword = True
                break
                
        has_on = "on" in prefix
        
        if has_recurring_keyword or ends_with_s or len(unique_weekdays) >= 2 or (has_on and ends_with_s):
            start_idx = first_start
            if has_recurring_keyword:
                for kw in ["every", "each", "repeat on", "repeating on", "weekly on"]:
                    idx = prefix.rfind(kw)
                    if idx != -1:
                        start_idx = max(0, first_start - 15) + idx
                        break
            elif has_on:
                idx = prefix.rfind("on")
                if idx != -1:
                    start_idx = max(0, first_start - 15) + idx
                    
            end_idx = matches[-1].end()
            cleaned = message[:start_idx] + message[end_idx:]
            return {
                "repeat_type": "weekday",
                "repeat_interval": 1,
                "repeat_unit": "weekdays",
                "repeat_weekdays": unique_weekdays
            }, cleaned

    # 3. Interval: "every X minutes/hours/days/weeks/months"
    interval_match_1 = re.search(r"\bevery\s+(\d+)\s*(minute|min|hour|hr|day|week|month)s?\b", msg_lower)
    if interval_match_1:
        val = int(interval_match_1.group(1))
        unit = interval_match_1.group(2)
        unit_map = {
            "minute": "minutes", "min": "minutes",
            "hour": "hours", "hr": "hours",
            "day": "days", "week": "weeks", "month": "months"
        }
        std_unit = unit_map[unit]
        span = interval_match_1.span()
        cleaned = message[:span[0]] + message[span[1]:]
        return {
            "repeat_type": "interval",
            "repeat_interval": val,
            "repeat_unit": std_unit,
            "repeat_weekdays": []
        }, cleaned

    # 4. Singular interval: "every minute/hour/day/week/month"
    interval_match_2 = re.search(r"\bevery\s+(minute|min|hour|hr|day|week|month)s?\b", msg_lower)
    if interval_match_2:
        unit = interval_match_2.group(1)
        unit_map = {
            "minute": "minutes", "min": "minutes",
            "hour": "hours", "hr": "hours",
            "day": "days", "week": "weeks", "month": "months"
        }
        std_unit = unit_map[unit]
        span = interval_match_2.span()
        cleaned = message[:span[0]] + message[span[1]:]
        return {
            "repeat_type": "interval",
            "repeat_interval": 1,
            "repeat_unit": std_unit,
            "repeat_weekdays": []
        }, cleaned

    # 5. Shortcuts: "daily", "weekly", "monthly"
    shortcut_match = re.search(r"\b(daily|weekly|monthly)\b", msg_lower)
    if shortcut_match:
        word = shortcut_match.group(1)
        unit_map = {
            "daily": "days",
            "weekly": "weeks",
            "monthly": "months"
        }
        span = shortcut_match.span()
        cleaned = message[:span[0]] + message[span[1]:]
        return {
            "repeat_type": "interval",
            "repeat_interval": 1,
            "repeat_unit": unit_map[word],
            "repeat_weekdays": []
        }, cleaned

    return None, message


def make_future_datetime(
    dt: datetime.datetime,
    is_recurring: bool,
    recurrence_data: dict | None,
    ref_now: datetime.datetime
) -> datetime.datetime:
    if dt > ref_now:
        return dt
        
    if is_recurring and recurrence_data:
        next_run = calculate_next_occurrence_datetime(
            start_dt=dt,
            repeat_type=recurrence_data.get("repeat_type"),
            repeat_interval=recurrence_data.get("repeat_interval"),
            repeat_unit=recurrence_data.get("repeat_unit"),
            repeat_weekdays=recurrence_data.get("repeat_weekdays"),
            now=ref_now
        )
        if next_run:
            return next_run
            
    while dt <= ref_now:
        dt += datetime.timedelta(days=1)
    return dt


def parse_reminder_message(message: str, ref_now: datetime.datetime = None) -> dict:
    if ref_now is None:
        ref_now = datetime.datetime.now()
        
    repeat_data, cleaned_message = extract_recurrence_and_clean(message)
    message_lower = cleaned_message.lower()
    
    clock_match = re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", message_lower, re.IGNORECASE)
    time_str = ""
    time_extracted = False
    
    if clock_match:
        time_str = normalize_time(clock_match.group(0))
        time_extracted = True
        cleaned_message = re.sub(re.escape(clock_match.group(0)), "", cleaned_message, flags=re.IGNORECASE).strip()
    else:
        clock_24_match = re.search(r"\b(\d{1,2}):(\d{2})\b", message_lower)
        if clock_24_match:
            time_str = normalize_time(clock_24_match.group(0))
            time_extracted = True
            cleaned_message = re.sub(re.escape(clock_24_match.group(0)), "", cleaned_message, flags=re.IGNORECASE).strip()
            
    relative_match = re.search(r"\b(?:in|after)\s+(\d+)\s+(minutes?|mins?|hours?|hrs?)\b", cleaned_message.lower(), re.IGNORECASE)
    if relative_match and not time_extracted:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2).lower()
        future = ref_now
        if "hour" in unit or "hr" in unit:
            future += datetime.timedelta(hours=amount)
        else:
            future += datetime.timedelta(minutes=amount)
        date_str = future.strftime("%Y-%m-%d")
        time_str = future.strftime("%I:%M %p")
        time_extracted = True
        cleaned_message = re.sub(relative_match.group(0), "", cleaned_message, flags=re.IGNORECASE).strip()
    else:
        date_str = parse_date_robustly(cleaned_message, ref_now)
        date_patterns = [
            r"\btomorrow\b", r"\btoday\b", r"\btonight\b",
            r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?\b",
            r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
            r"\b\d{4}-\d{1,2}-\d{1,2}\b"
        ]
        for pattern in date_patterns:
            cleaned_message = re.sub(pattern, "", cleaned_message, flags=re.IGNORECASE).strip()
            
    if not time_str:
        time_str = "09:00 AM"
        
    if not date_str:
        date_str = ref_now.strftime("%Y-%m-%d")
        
    task_text = normalize_reminder_text(cleaned_message)
    if task_text:
        task_text = task_text[0].upper() + task_text[1:]
        
    try:
        parsed_time = datetime.datetime.strptime(time_str, "%I:%M %p").time()
        parsed_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        reminder_dt = datetime.datetime.combine(parsed_date, parsed_time)
    except Exception:
        reminder_dt = datetime.datetime.combine(ref_now.date(), datetime.time(9, 0))
        
    is_recurring = repeat_data is not None
    final_dt = make_future_datetime(reminder_dt, is_recurring, repeat_data, ref_now)
    
    return {
        "text": task_text,
        "date": final_dt.strftime("%Y-%m-%d"),
        "time": final_dt.strftime("%I:%M %p"),
        "repeat_type": repeat_data["repeat_type"] if repeat_data else None,
        "repeat_interval": repeat_data["repeat_interval"] if repeat_data else None,
        "repeat_unit": repeat_data["repeat_unit"] if repeat_data else None,
        "repeat_weekdays": repeat_data["repeat_weekdays"] if repeat_data else None
    }

def send_due_reminder_emails():
    try:
        logger.info("Checking due reminders..")
        now = datetime.datetime.now()

        logger.info("STEP 1 - Starting email check")
        reminders = list(db.collection_group("reminders").stream())
        logger.info(f"STEP 2 - Found {len(reminders)} reminders")
        for reminder_doc in reminders:
            logger.info(f"Processing reminder: {reminder_doc.id}")
            reminder = reminder_doc.to_dict()
            logger.info(f"Reminder data: {reminder}")
            if reminder.get("email_sent", False):
                continue
            repeat_type = reminder.get("repeat_type")
            if repeat_type and repeat_type != "none":
                continue
            reminder_date = reminder.get("date")
            reminder_time = reminder.get("time")
            if not reminder_date or not reminder_time:
                continue
            try:
                reminder_datetime = datetime.datetime.strptime(
                    f"{reminder_date} {reminder_time}",
                    "%Y-%m-%d %I:%M %p"
                )
            except Exception:
                continue
            if reminder_datetime <= now:
                user_ref = (reminder_doc.reference.parent.parent)
                user_doc = user_ref.get()
                if not user_doc.exists:
                    continue
                user_data = user_doc.to_dict()
                email = user_data.get("email")
                name = user_data.get("name", "User")

                if not email:
                    continue

                success = send_email_notification(email, name, reminder.get("text", ""), reminder_time)
                if success:
                    reminder_doc.reference.update({"email_sent": True})
                    logger.info(
                        f"Notification sent for reminder "
                        f"{reminder_doc.id}"
                    )
    except Exception as e:
        logger.exception(f"send_due_reminder_emails failed: {e}")


def cleanup_expired_reminders():
    try:
        logger.info("Starting expired reminder cleanup...")

        now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
        deleted_count = 0

        # Search ALL reminders across ALL users
        reminders = db.collection_group("reminders").stream()

        for reminder_doc in reminders:
            try:
                data = reminder_doc.to_dict()

                # Skip recurring reminders
                repeat_type = data.get("repeat_type")
                if repeat_type and repeat_type != "none":
                    continue

                reminder_date = data.get("date")
                reminder_time = data.get("time")

                if not reminder_date or not reminder_time:
                    continue

                try:
                    datetime_str = f"{reminder_date} {reminder_time}"

                    formats = [
                        "%Y-%m-%d %I:%M %p",  # 07:00 PM
                        "%Y-%m-%d %I %p",     # 7 PM
                        "%Y-%m-%d %H:%M",     # 19:00
                    ]

                    reminder_datetime = None

                    for fmt in formats:
                        try:
                            reminder_datetime = datetime.datetime.strptime(
                                datetime_str,
                                fmt
                            )
                            reminder_datetime = reminder_datetime.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                            break
                        except ValueError:
                            pass

                    if reminder_datetime is None:
                        logger.warning(
                            f"Failed parsing reminder datetime for "
                            f"{reminder_doc.id}: {datetime_str}"
                        )
                        continue
                except Exception as e:
                    logger.warning(
                        f"Failed parsing reminder datetime "
                        f"for {reminder_doc.id}: {e}"
                    )
                    continue

                if reminder_datetime < now and data.get("email_sent", False):
                    reminder_doc.reference.delete()

                    deleted_count += 1

                    logger.info(
                        f"Deleted expired reminder: "
                        f"{data.get('text', 'Unknown')}"
                    )

            except Exception as e:
                logger.error(
                    f"Error processing reminder {reminder_doc.id}: {e}"
                )

        logger.info(
            f"Cleanup complete. Deleted {deleted_count} reminders."
        )

    except Exception as e:
        logger.exception(
            f"cleanup_expired_reminders failed: {e}"
        )

def extract_reminder_details(message: str):
    res = parse_reminder_message(message, datetime.datetime.now())
    return res["text"], res["date"], res["time"]


def is_valid_reminder(text: str) -> bool:
    if not text:
        return False

    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return False

    junk_words = {
        "for", "at", "my", "reminders", "reminder", "me", "to", "set", "add", 
        "please", "tomorrow", "today", "day", "the", "a", "an", "on", "in", "of", "and"
    }

    meaningful_words = [w for w in words if w not in junk_words]
    if not meaningful_words:
        return False

    cleaned_text = " ".join(meaningful_words)
    if len(cleaned_text) < 2:
        return False
    return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ai_assistant_backend")


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set in environment variables! Gemini requests will fail.")
else:
    logger.info(f"Configuring Gemini with model: {GEMINI_MODEL}")
    genai.configure(api_key=GEMINI_API_KEY)

db = None
firebase_initialized = False

try:
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")

    if firebase_credentials:
        cred_dict = json.loads(firebase_credentials)

        cred = credentials.Certificate(cred_dict)

        firebase_admin.initialize_app(cred)

        db = firestore.client()

        firebase_initialized = True

        logger.info(
            f"Successfully connected to Firestore project: "
            f"{firebase_admin.get_app().project_id}"
        )

    else:
        logger.warning("FIREBASE_CREDENTIALS environment variable not found.")

except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")
app = FastAPI(
    title="AI Personal Assistant API",
    description="Backend API for AI Personal Assistant with Gemini and Firestore integration.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

def personalize_reply(ai_reply, user_name=""):
    if (user_name and isinstance(ai_reply, dict) and "summary" in ai_reply and not ai_reply["summary"].startswith(user_name)):
        ai_reply["summary"] = f"{user_name}, {ai_reply['summary']}"
    return ai_reply  

def get_system_prompt(user_name: str = "") -> str:

    now = datetime.datetime.now()

    time_str = now.strftime(
        "%A, %B %d, %Y, %I:%M:%S %p"
    )

    name_context = ""

    if user_name:
        name_context = f"""
USER INFORMATION:
Name = {user_name}

PERSONALIZATION RULES:
- The user's name is {user_name}.
- Use the user's name when:
  * confirming reminders
  * creating notes
  * discussing tasks
  * giving recommendations
  * greeting the user
  * summarizing completed actions
- Use the name naturally and professionally.
- Do not use the name in every sentence.
- Do not force the name into technical explanations.
"""
    
    return f"""
{name_context}
You are a smart, warm, conversational AI personal assistant.

Current date and time:
{time_str}

IMPORTANT BEHAVIOR RULES:

1. Be natural and human-like.
2. Be friendly during greetings.
3. Be emotionally intelligent.
4. Avoid robotic wording.
5. Keep replies concise unless detailed explanation is needed.
6. During greetings:
   - respond casually
   - sound warm
   - ask follow-up questions sometimes
7. Use memory naturally when relevant.
8. For reminders/notes/tasks:
   - be clear and professional
9. Never sound repetitive.
10. Avoid overexplaining simple things.

RESPONSE FORMAT RULES:

Always return ONLY valid JSON.

Format:

{{
  "title": "short natural title",
  "summary": "main conversational response",
  "details": ["optional extra point 1", "optional extra point 2"]
}}

GREETING EXAMPLES:

User: hi
Response:
{{
  "title": "Hello",
  "summary": "Hey! How’s your day going?",
  "details": []
}}

User: good morning
Response:
{{
  "title": "Good Morning",
  "summary": "Good morning! Hope you have a productive day ahead.",
  "details": []
}}

User: how are you
Response:
{{
  "title": "Doing Great",
  "summary": "I’m doing great! Thanks for asking. How about you?",
  "details": []
}}

User: thanks
Response:
{{
  "title": "You're Welcome",
  "summary": "Anytime! Happy to help.",
  "details": []
}}

User: bye
Response:
{{
  "title": "Goodbye",
  "summary": "See you later! Take care.",
  "details": []
}}

IMPORTANT:
- No markdown
- No code blocks
- No extra explanations
- Output ONLY valid JSON
"""

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def home():
    return {
        "status": "online",
        "message": "FastAPI backend is running successfully!",
        "firebase_connected": firebase_initialized,
        "gemini_configured": bool(GEMINI_API_KEY)
    }


def save_to_firestore_bg(uid: str, user_message: str, ai_reply: dict):
    if firebase_initialized and db:
        try:
            logger.info("Attempting to save conversation to Firestore in background task...")
            db.collection("users").document(uid).collection("chat_history").add({
                "user_message": user_message,
                "ai_reply": ai_reply,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            logger.info("Successfully saved conversation to Firestore (background).")
        except Exception as e:
            logger.error(f"Firestore Error (Bypassed in background): {e}")
def extract_repeat_type(message):
    msg = message.lower()

    weekdays = [
        "monday","tuesday","wednesday",
        "thursday","friday","saturday","sunday"
    ]

    # 1. every X days/weeks etc
    match = re.search(r"every\s+(\d+)\s+(hour|day|week|month)s?", msg)
    if match:
        return {
            "type": "interval",
            "repeat_interval": int(match.group(1)),
            "repeat_unit": match.group(2)
        }

    # 2. daily/weekly/monthly
    if "daily" in msg or "every day" in msg:
        return {"type": "interval", "interval": 1, "unit": "days", "weekdays": []}

    if "weekly" in msg or "every week" in msg:
        return {"type": "interval", "interval": 1, "unit": "weeks", "weekdays": []}

    if "monthly" in msg or "every month" in msg:
        return {"type": "interval", "interval": 1, "unit": "months", "weekdays": []}

    # 3. weekday recurrence (IMPORTANT FIX)
    found_days = [d for d in weekdays if f"every {d}" in msg or f"on {d}" in msg]

    if found_days:
        return {
            "type": "weekday",
            "weekdays": found_days
        }

    return None


@app.post("/chat")
async def chat(
    background_tasks: BackgroundTasks,
    message: str = Form(""),
    image: UploadFile = File(None),
    authorization: str = Header(None)
):
    db_updated = False
    user_message = message.strip()
    
    if not user_message and not image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty."
        )

    if not GEMINI_API_KEY:
        logger.error("Gemini API key is not configured.")
        return {
            "reply": {
                "title": "System Error",
                "summary": "Gemini API key is missing. Please configure GEMINI_API_KEY.",
                "details": []
            },
            "status": "error"
        }

    pil_image = None
    if image:
        try:
            image_bytes = await image.read()
            logger.info(f"Processing uploaded image: {image.filename} ({image.content_type}), Size: {len(image_bytes)} bytes")
            pil_image = Image.open(io.BytesIO(image_bytes))
            
            max_dimension = 1024
            if pil_image.width > max_dimension or pil_image.height > max_dimension:
                logger.info(f"Compressing image from {pil_image.size} to max {max_dimension}px...")
                resample_filter = getattr(Image, "Resampling", None)
                if resample_filter:
                    filter_type = resample_filter.LANCZOS
                else:
                    filter_type = getattr(Image, "ANTIALIAS", 1)
                
                pil_image.thumbnail((max_dimension, max_dimension), filter_type)
                logger.info(f"Compressed image size: {pil_image.size}")
        except Exception as img_err:
            logger.error(f"Failed to process image: {img_err}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image format or corrupted file."
            )

    try:
        uid = await get_current_user(authorization)
        user_doc = db.collection("users").document(uid).get()
        user_name = ""
        if user_doc.exists:
            user_name = user_doc.to_dict().get("name", "")
        if image and ("note" in user_message.lower() and ("image" in user_message.lower() or "text" in user_message.lower() or "extract" in user_message.lower() or "convert" in user_message.lower())):
            intent = "extract_text_and_save_note"
        else: 
            intent = detect_intent_locally(user_message)
            if intent:
                logger.info(f"[INTENT_DETECTED] local rule matched: {intent}")
            else:
                intent = await classify_intent_with_gemini(user_message)
                logger.info(f"[INTENT_DETECTED] final intent: {intent}")
            
        memory_data  = await extract_memory_with_gemini(user_message)
        if memory_data:
            save_user_memory(uid, memory_data)

        if intent == "save_reminder":
            ref_now = datetime.datetime.now()
            res = parse_reminder_message(user_message, ref_now)
            
            reminder_text = res["text"]
            reminder_date = res["date"]
            reminder_time = res["time"]
            repeat_type = res["repeat_type"]
            repeat_interval = res["repeat_interval"]
            repeat_unit = res["repeat_unit"]
            repeat_weekdays = res["repeat_weekdays"]
            is_recurring = repeat_type is not None

            if not is_valid_reminder(reminder_text):
                ai_reply = {
                    "title": "Invalid Reminder",
                    "summary": "Could not save reminder. The reminder text is empty or invalid.",
                    "details": [
                        "Please specify a valid task to be reminded of (e.g., 'remind me to drink water').",
                        f"Parsed text was: '{reminder_text}'" if reminder_text else "No task text detected."
                    ]
                }
                return {
                    "reply": personalize_reply(ai_reply, user_name),
                    "status": "error"
                }

            is_duplicate = False
            if firebase_initialized and db: 
                try:
                    docs = db.collection("users").document(uid).collection("reminders").stream()
                    for doc in docs:
                        data = doc.to_dict() or {}
                        db_text = data.get("text", "")
                        db_date = data.get("date", "")
                        db_time = data.get("time", "")
                        
                        db_repeat_type = data.get("repeat_type")
                        db_repeat_interval = data.get("repeat_interval")
                        db_repeat_unit = data.get("repeat_unit")
                        db_repeat_weekdays = data.get("repeat_weekdays")
                        
                        # Compare normalized task + date + time case-insensitively using fuzzy matching
                        texts_match = is_fuzzy_match(db_text, reminder_text)
                        times_match = normalize_time(db_time) == normalize_time(reminder_time)
                        
                        if texts_match and times_match:
                            if is_recurring:
                                db_weekdays = [w.lower().strip() for w in (db_repeat_weekdays or [])]
                                curr_weekdays = [w.lower().strip() for w in (repeat_weekdays or [])]
                                if (db_repeat_type == repeat_type and
                                    db_repeat_interval == repeat_interval and
                                    (db_repeat_unit or "").lower().strip() == (repeat_unit or "").lower().strip() and
                                    sorted(db_weekdays) == sorted(curr_weekdays)):
                                    is_duplicate = True
                                    break
                            else:
                                if not db_repeat_type and db_date == reminder_date:
                                    is_duplicate = True
                                    break
                except Exception as db_err:
                    logger.error(f"Error checking duplicate reminder: {db_err}")
                    
            if is_duplicate:
                ai_reply = {
                    "title": "Reminder Already Exists",
                    "summary": "This reminder has already been set.",
                    "details": [
                        f"Task: {reminder_text}",
                        f"Time: {reminder_time}" + (" (Repeats)" if is_recurring else "")
                    ]
                }
                return {
                    "reply": personalize_reply(ai_reply, user_name),
                    "status": "success",
                    "db_updated": False
                }

            if firebase_initialized and db:
                db.collection("users").document(uid).collection("reminders").add({
                    "text": reminder_text,
                    "date": reminder_date,
                    "time": reminder_time,
                    "repeat_type": repeat_type,
                    "repeat_interval": repeat_interval,
                    "repeat_unit": repeat_unit,
                    "repeat_weekdays": repeat_weekdays,
                    "email_sent": False,
                    "created_at": firestore.SERVER_TIMESTAMP
                })    
                logger.info(f"[REMINDER_CREATED] Text: '{reminder_text}', Date: '{reminder_date}', Time: '{reminder_time}', Recurring: {is_recurring}")
                db_updated = True

            ai_reply = {
                "title": "Reminder Saved",
                "summary": "Reminder saved successfully",
                "details": [
                    f"Task: {reminder_text}",
                    f"Time: {reminder_time}" + (" (Repeats)" if is_recurring else "")
                ]
            }

            background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)

            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }

        elif intent == "get_reminders":

            reminders = []
            day_filter = extract_day_filter(user_message)
            show_upcoming = "upcoming" in user_message.lower()
            now = datetime.datetime.now()

            if firebase_initialized and db:

                docs = db.collection("users").document(uid).collection("reminders").stream()

                for doc in docs:

                    data = doc.to_dict() or {}

                    text = data.get("text", "").strip()
                    time = data.get("time", "").strip()
                    date = data.get("date", "").strip()

                    if not text:
                        continue

                    if day_filter:
                        if date != day_filter:
                            continue
                    if show_upcoming and date == now.strftime("%Y-%m-%d"):
                        try:
                            reminder_time = datetime.datetime.strptime(time, "%I:%M %p").time()
                            if reminder_time <= now.time():
                                continue
                        except ValueError:
                            pass
                    reminder_parts = [text]
                    repeat_type = data.get("repeat_type")
                    repeat_interval = data.get("repeat_interval")
                    repeat_unit = data.get("repeat_unit")
                    repeat_weekdays = data.get("repeat_weekdays")

                    if repeat_type == "weekday" and repeat_weekdays:
                        days_cap = [w.capitalize() for w in repeat_weekdays]
                        if len(days_cap) == 5 and all(d in days_cap for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
                            reminder_parts.append("every Weekday")
                        else:
                            if len(days_cap) > 1:
                                reminder_parts.append(f"every {', '.join(days_cap[:-1])} and {days_cap[-1]}")
                            else:
                                reminder_parts.append(f"every {days_cap[0]}")
                    elif repeat_unit:
                        if repeat_interval:
                            unit_display = repeat_unit
                            if repeat_interval == 1:
                                if repeat_unit.endswith("s"):
                                    unit_display = repeat_unit[:-1]
                            reminder_parts.append(f"every {repeat_interval} {unit_display}" if repeat_interval > 1 else f"every {unit_display}")

                    if time:
                        reminder_parts.append(f"at {time}")

                    if not day_filter and date:
                        try:
                            parsed_date = datetime.datetime.strptime(
                                date,
                                "%Y-%m-%d"
                            )

                            formatted_date = parsed_date.strftime(
                                "%A, %B %d, %Y"
                            )

                            reminder_parts.append(f"on {formatted_date}")

                        except:
                            reminder_parts.append(f"on {date}")

                    reminder_text = " ".join(reminder_parts)

                    reminders.append(reminder_text)

            if len(reminders) == 0:

                if day_filter:

                    try:
                        parsed_dt = datetime.datetime.strptime(
                            day_filter,
                            "%Y-%m-%d"
                        )

                        date_display = parsed_dt.strftime(
                            "%A, %B %d, %Y"
                        )

                    except:
                        date_display = day_filter

                    summary_text = (
                        f"You have no reminders set for {date_display}."
                    )

                else:

                    summary_text = (
                        "You don't have any reminders set."
                    )

                ai_reply = {
                    "title": "No Reminders Found",
                    "summary": summary_text,
                    "details": []
                }

            else:

                if day_filter:

                    try:
                        parsed_dt = datetime.datetime.strptime(
                            day_filter,
                            "%Y-%m-%d"
                        )

                        date_display = parsed_dt.strftime(
                            "%A, %B %d, %Y"
                        )

                    except:
                        date_display = day_filter

                    summary_text = (
                        f"Here are your reminders for {date_display}:"
                    )

                else:

                    summary_text = (
                        f"You have {len(reminders)} reminder(s):"
                    )

                ai_reply = {
                    "title": "Your Reminders",
                    "summary": summary_text,
                    "details": reminders
                }

            background_tasks.add_task(
                save_to_firestore_bg,
                uid,
                user_message,
                ai_reply
            )

            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": False
            }

        elif intent == "summarize_and_save":
            cleaned_text = re.sub(r"(summarize this|summarise this|summarize and save|summarise and save|summary of this|make a summary|shorten this|give me a summary)", "", user_message, flags=re.IGNORECASE).strip()
            if len(cleaned_text) < 30:
                ai_reply = {
                    "title": "Text Too Short",
                    "summary": "Please provide longer text to summarize.",
                    "details": []
                }
                return {
                    "reply": personalize_reply(ai_reply, user_name),
                    "status": "error",
                    "db_updated": False
                }
            summary = await summarize_text_with_gemini(cleaned_text)
            if not summary:
                ai_reply = {
                    "title": "Summarization Failed",
                    "summary": "Failed to generate summary. Please try again.",
                    "details": []
                }
                return {
                    "reply": personalize_reply(ai_reply, user_name),
                    "status": "error",
                    "db_updated": False
                }
            if firebase_initialized and db:
                db.collection("users").document(uid).collection("notes").add({
                    "content": summary,
                    "original_text": cleaned_text,
                    "type": "summary",
                    "created_at": firestore.SERVER_TIMESTAMP
                })
                db_updated = True
            ai_reply = {
                "title": "Summary Saved",
                "summary": "Text summarized and saved successfully.",
                "details": [summary]
            }
            background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }
        elif intent == "extract_text_and_save_note":
            model = genai.GenerativeModel(GEMINI_MODEL)
            prompt = """
            Extract all text from this image.
            Return only the extracted text
            """
            response = await model.generate_content_async([prompt, pil_image])
            extracted_text = response.text.strip()
            if firebase_initialized and db:
                db.collection("users").document(uid).collection("notes").add({
                    "content": extracted_text,
                    "type": "image_note",
                    "created_at": firestore.SERVER_TIMESTAMP
                })
                db_updated = True
            ai_reply ={
                "title": "Note Saved",
                "summary": "Your extracted text note was saved successfully.",
                "details": [extracted_text]
            }
            background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }
        elif intent == "save_note":
            if firebase_initialized and db:
                db.collection("users").document(uid).collection("notes").add({
                    "content": user_message,
                    "created_at": firestore.SERVER_TIMESTAMP
                })
                db_updated = True
            ai_reply = {
                "title": "Note Saved",
                "summary": "Your note was saved successfully",
                "details": [user_message]
            }

            background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)

            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }
            
        elif intent == "get_notes":

            notes = []

            if firebase_initialized and db:
                docs = db.collection("users").document(uid).collection("notes").stream()

                for doc in docs:
                    data = doc.to_dict()
                    notes.append(data.get("content"))

            ai_reply = {
                "title": "Saved Notes",
                "summary": f"You have {len(notes)} saved notes",
                "details": notes
            }

            background_tasks.add_task(
                save_to_firestore_bg,
                uid,
                user_message,
                ai_reply
            )

            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": False
            }

        elif intent == "delete_all_reminders":
            deleted_count = 0
            if firebase_initialized and db:
                docs = db.collection("users").document(uid).collection("reminders").stream()
                for doc in docs:
                    doc.reference.delete()
                    deleted_count += 1
                if deleted_count > 0:
                    db_updated = True

            ai_reply = {
                "title": "Reminders Deleted",
                "summary": f"Successfully deleted {deleted_count} reminder(s).",
                "details": ["All your reminders have been cleared."]
            }
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }

        elif intent == "delete_all_notes":
            deleted_count = 0
            if firebase_initialized and db:
                docs = db.collection("users").document(uid).collection("notes").stream()
                for doc in docs:
                    doc.reference.delete()
                    deleted_count += 1
                if deleted_count > 0:
                    db_updated = True

            ai_reply = {
                "title": "Notes Deleted",
                "summary": f"Successfully deleted {deleted_count} note(s).",
                "details": ["All your notes have been cleared."]
            }
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }

        elif intent == "delete_single_reminder":
            # Clean deletion prefixes case-insensitively
            cleaned = user_message.strip()
            
            delete_prefixes = [
                r"^delete\s+the\s+reminder\s+to\b",
                r"^delete\s+the\s+reminder\s+for\b",
                r"^delete\s+the\s+reminder\b",
                r"^delete\s+reminder\s+to\b",
                r"^delete\s+reminder\s+for\b",
                r"^delete\s+reminder\b",
                r"^remove\s+the\s+reminder\s+to\b",
                r"^remove\s+the\s+reminder\s+for\b",
                r"^remove\s+the\s+reminder\b",
                r"^remove\s+reminder\s+to\b",
                r"^remove\s+reminder\s+for\b",
                r"^remove\s+reminder\b",
                r"^cancel\s+the\s+reminder\s+to\b",
                r"^cancel\s+the\s+reminder\s+for\b",
                r"^cancel\s+the\s+reminder\b",
                r"^cancel\s+reminder\s+to\b",
                r"^cancel\s+reminder\s+for\b",
                r"^cancel\s+reminder\b",
                r"^clear\s+the\s+reminder\s+to\b",
                r"^clear\s+the\s+reminder\s+for\b",
                r"^clear\s+the\s+reminder\b",
                r"^clear\s+reminder\s+to\b",
                r"^clear\s+reminder\s+for\b",
                r"^clear\s+reminder\b",
                r"^delete\b",
                r"^remove\b",
                r"^cancel\b",
                r"^clear\b"
            ]
            
            for prefix in delete_prefixes:
                match = re.search(prefix, cleaned, re.IGNORECASE)
                if match:
                    cleaned = cleaned[match.end():].strip()
                    break
                    
            extracted_task = cleaned
            extracted_time = ""
            
            # Time patterns from extract_reminder_details to extract time separately
            time_patterns = [
                r"\b(in|after)\s+\d+\s+(minutes?|mins?|hours?|hrs?|days?)\b",
                r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
                r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
                r"\bat\s+(\d{1,2}(?::\d{2})?\s+in\s+the\s+(morning|evening|afternoon|night))\b",
                r"\b(\d{1,2}(?::\d{2})?\s+in\s+the\s+(morning|evening|afternoon|night))\b",
                r"\bat\s+(\d{1,2}(?::\d{2})?\s+(morning|evening|afternoon|night|morn|eve))\b",
                r"\b(\d{1,2}(?::\d{2})?\s+(morning|evening|afternoon|night|morn|eve))\b",
                r"\bat\s+(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b",
                r"\b(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b",
                r"\b(tomorrow|today|tonight|this evening|this morning)\b",
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, extracted_task, re.IGNORECASE)
                if match:
                    clock_match = re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", match.group(0), re.IGNORECASE)
                    if clock_match:
                        extracted_time = normalize_time(clock_match.group(0))
                    else:
                        extracted_time = normalize_time(match.group(0))
                    extracted_task = re.sub(pattern, "", extracted_task, flags=re.IGNORECASE).strip()
                    break
            
            # Clean up residual connector words and punctuation from task
            extracted_task = re.sub(r'^(to|for|at|on)\s+', '', extracted_task, flags=re.IGNORECASE)
            extracted_task = re.sub(r'\s+(to|for|at|on)$', '', extracted_task, flags=re.IGNORECASE)
            extracted_task = extracted_task.strip().rstrip('.!?,')
            
            deleted_count = 0
            if firebase_initialized and db and extracted_task:
                try:
                    # Find all matches matching the task case-insensitively using fuzzy matching
                    matches = []
                    docs = db.collection("users").document(uid).collection("reminders").stream()
                    for doc in docs:
                        data = doc.to_dict() or {}
                        db_text = data.get("text", "")
                        db_time = data.get("time", "")
                        db_date = data.get("date", "")
                        
                        if is_fuzzy_match(db_text, extracted_task):
                            matches.append({
                                "doc": doc,
                                "text": db_text,
                                "time": db_time,
                                "date": db_date
                            })
                            
                    doc_to_delete = None
                    if len(matches) > 1 and not extracted_time:
                        # Multiple matches found without time specifier, return list of matches to user
                        match_details = []
                        for idx, m_item in enumerate(matches, 1):
                            time_disp = f" at {m_item['time']}" if m_item['time'] else ""
                            date_disp = f" on {m_item['date']}" if m_item['date'] else ""
                            match_details.append(f"{idx}. {m_item['text']}{time_disp}{date_disp}")
                            
                        ai_reply = {
                            "title": "Multiple Matches Found",
                            "summary": f"I found multiple reminders matching '{extracted_task}'. Which one would you like to delete? Please specify the exact time.",
                            "details": match_details
                        }
                        background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)
                        return {
                            "reply": personalize_reply(ai_reply, user_name),
                            "status": "success",
                            "db_updated": False
                        }
                    
                    if extracted_time:
                        normalized_extracted_time = normalize_time(extracted_time)
                        for item in matches:
                            normalized_db_time = normalize_time(item["time"])
                            if normalized_db_time == normalized_extracted_time:
                                doc_to_delete = item["doc"]
                                break
                    else:
                        if len(matches) > 0:
                            doc_to_delete = matches[0]["doc"]
                            
                    if doc_to_delete:
                        # Fetch values for logging before deleting
                        deleted_data = doc_to_delete.get().to_dict() or {}
                        deleted_text = deleted_data.get("text", "")
                        deleted_time = deleted_data.get("time", "")
                        
                        doc_to_delete.delete()
                        deleted_count = 1
                        db_updated = True
                        logger.info(f"[REMINDER_DELETED] Deleted reminder: Text: '{deleted_text}', Time: '{deleted_time}'")
                except Exception as db_err:
                    logger.error(f"Error deleting reminder: {db_err}")
            
            if deleted_count > 0:
                details_msg = [f"Task: {extracted_task}"]
                if extracted_time:
                    details_msg.append(f"Time: {extracted_time}")
                ai_reply = {
                    "title": "Reminder Deleted",
                    "summary": f"Successfully deleted the reminder matching '{extracted_task}'" + (f" at {extracted_time}" if extracted_time else "") + ".",
                    "details": details_msg
                }
            else:
                ai_reply = {
                    "title": "Reminder Not Found",
                    "summary": f"No reminder found matching '{extracted_task}'" + (f" at {extracted_time}" if extracted_time else "") + ".",
                    "details": ["Try saying 'show reminders' to see your current reminders."]
                }
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }

        elif intent == "delete_single_note":
            cleaned = re.sub(r'[?.!,]', '', user_message.lower()).strip()
            match = re.search(r"^(?:delete|remove|clear)\s+(?:the\s+)?note\s+(.+)$", cleaned)
            search_text = match.group(1).strip() if match else ""
            
            deleted_count = 0
            if firebase_initialized and db and search_text:
                docs = db.collection("users").document(uid).collection("notes").stream()
                for doc in docs:
                    data = doc.to_dict()
                    if search_text in data.get("content", "").lower():
                        doc.reference.delete()
                        deleted_count += 1
                        db_updated = True
                        break

            if deleted_count > 0:
                ai_reply = {
                    "title": "Note Deleted",
                    "summary": f"Successfully deleted the note matching '{search_text}'.",
                    "details": []
                }
            else:
                ai_reply = {
                    "title": "Note Not Found",
                    "summary": f"No note found matching '{search_text}'.",
                    "details": ["Try saying 'show notes' to see your current notes."]
                }
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": db_updated
            }

        elif intent == "stop_repeating_reminder":
            task = re.sub(r"stop repeating reminder", "", user_message, flags=re.IGNORECASE).strip()
            task = normalize_reminder_text(task)

            docs = db.collection("users").document(uid).collection("reminders").stream()

            updated = False

            for doc in docs:
                data = doc.to_dict()

                if is_fuzzy_match(data.get("text", ""), task):

                    doc.reference.update({
                        "repeat_interval": None,
                        "repeat_unit": None
                    })

                    updated = True
                    break

            if updated:
                ai_reply = {
                    "title": "Recurring Reminder Disabled",
                    "summary": "The reminder will no longer repeat.",
                    "details": []
                }
            else:
                ai_reply = {
                    "title": "Reminder Not Found",
                    "summary": "I couldn't find that recurring reminder.",
                    "details": []
                }

            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success"
            }

        elif intent == "extract_tasks_from_image" and pil_image:
            model = genai.GenerativeModel(GEMINI_MODEL)
            extraction_prompt = """
Extract all tasks from this image.

Return ONLY JSON:

{
  "title": "Tasks Found",
  "summary": "Short summary",
  "details": ["task 1", "task 2"]
}
"""
            response = await asyncio.wait_for(model.generate_content_async([extraction_prompt, pil_image]), timeout=20.0)
            ai_reply = extract_json(response.text)

            background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)
            return {
                "reply": personalize_reply(ai_reply, user_name),
                "status": "success",
                "db_updated": False
            }

        model = genai.GenerativeModel(GEMINI_MODEL)
        contents = []
        system_prompt = get_system_prompt(user_name)
        user_memory = load_user_memory(uid)
        if user_memory:
            memory_text = """

You have long-term memory about this user.

Use this information naturally in conversation whenever relevant.

Known User Information:
"""
            for key, value in user_memory.items():
                memory_text += f"{key}: {value}\n"
            system_prompt += memory_text
        contents.append(system_prompt)
        if pil_image:
            contents.append(pil_image)
        contents.append(user_message)
        response = await asyncio.wait_for(
            model.generate_content_async(contents),
            timeout = 25.0
        )

        raw_text = response.text
        ai_reply = extract_json(raw_text)

        background_tasks.add_task(save_to_firestore_bg, uid, user_message, ai_reply)

        return {
            "reply": personalize_reply(ai_reply, user_name),
            "status": "success",
            "db_updated": False
        }
    
        

    except asyncio.TimeoutError as e:
        logger.error(f"[GEMINI_FAILURE] TimeoutError: {e}")
        ai_reply = {
            "title": "AI Assistant Offline",
            "summary": "I'm having trouble connecting to my brain right now, but I can still help you with standard commands. Try saying 'show reminders' or 'add reminder to buy milk'.",
            "details": ["Request timed out"]
        }
        return {
            "reply": personalize_reply(ai_reply, user_name),
            "status": "success",
            "db_updated": False
        }

    except Exception as e:
        logger.error(f"[GEMINI_FAILURE] Error: {e}")
        ai_reply = {
            "title": "AI Assistant Offline",
            "summary": "I'm having trouble connecting to my brain right now, but I can still help you with standard commands. Try saying 'show reminders' or 'add reminder to buy milk'.",
            "details": [str(e)]
        }
        return {
            "reply": personalize_reply(ai_reply, user_name),
            "status": "success",
            "db_updated": False
        }


# --- Pydantic Models for REST endpoints ---

def map_repeat_type_to_frontend(
    repeat_type: str | None,
    repeat_interval: int | None,
    repeat_unit: str | None,
    repeat_weekdays: list | None
) -> str:
    if not repeat_type:
        return "none"
        
    repeat_type_clean = repeat_type.lower().strip()
    
    if repeat_type_clean == "weekday":
        return "weekly"
        
    if repeat_type_clean == "interval":
        unit = (repeat_unit or "").lower().strip()
        interval = repeat_interval or 1
        if "day" in unit:
            return "daily"
        elif "week" in unit:
            return "weekly"
        elif "month" in unit:
            return "monthly"
            
    return "none"

class ReminderUpdate(BaseModel):
    text: str
    time: str
    date: str | None = None
    repeat_type: str | None = None
    repeat_interval: int | None = None
    repeat_unit: str | None = None
    repeat_weekdays: list[str] | None = None

class NoteUpdate(BaseModel):
    content: str

class ProfileRequest(BaseModel):
    name: str
    email: str

# --- REST CRUD Endpoints ---

def parse_exact_date(message: str) -> str | None:
    message_lower = message.lower()

    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", message_lower)
    if iso_match:
        year = int(iso_match.group(1))
        month = int(iso_match.group(2))
        day = int(iso_match.group(3))
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    slash_match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", message_lower)
    if slash_match:
        day = int(slash_match.group(1))
        month = int(slash_match.group(2))
        year_str = slash_match.group(3)
        if len(year_str) == 2:
            year = 2000 + int(year_str)
        else:
            year = int(year_str)
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    month_day_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        message_lower
    )
    if month_day_match:
        month_name = month_day_match.group(1)
        day = int(month_day_match.group(2))
        month = months[month_name]
        year = datetime.datetime.now().year
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    day_month_match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
        message_lower
    )
    if day_month_match:
        day = int(day_month_match.group(1))
        month_name = day_month_match.group(2)
        month = months[month_name]
        year = datetime.datetime.now().year
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    return None

def extract_day_filter(message: str) -> str | None:
    message_lower = message.lower()
    now = datetime.datetime.now()
    
    if "today" in message_lower:
        return now.strftime("%Y-%m-%d")
        
    if "tomorrow" in message_lower:
        return (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6
    }
    for day_name, day_num in weekdays.items():
        if day_name in message_lower:
            today_weekday = now.weekday()
            days_diff = day_num - today_weekday
            target_date = now + datetime.timedelta(days=days_diff)
            return target_date.strftime("%Y-%m-%d")
            
    exact_date = parse_exact_date(message)
    if exact_date:
        return exact_date
        
    return None


@app.get("/reminders")
def get_all_reminders(uid: str = Depends(get_current_user)):
    try:
        reminders = []

        if firebase_initialized and db:
            docs = db.collection("users").document(uid).collection("reminders").stream()

            for doc in docs:
                try:
                    data = doc.to_dict() or {}
                    
                    db_repeat_type = data.get("repeat_type")
                    db_repeat_interval = data.get("repeat_interval")
                    db_repeat_unit = data.get("repeat_unit")
                    db_repeat_weekdays = data.get("repeat_weekdays")
                    
                    frontend_repeat_type = map_repeat_type_to_frontend(
                        db_repeat_type,
                        db_repeat_interval,
                        db_repeat_unit,
                        db_repeat_weekdays
                    )

                    reminders.append({
                        "id": doc.id,
                        "text": data.get("text", ""),
                        "date": data.get("date", ""),
                        "time": data.get("time", ""),
                        "repeat_type": frontend_repeat_type,
                        "repeat_interval": db_repeat_interval,
                        "repeat_unit": db_repeat_unit,
                        "repeat_weekdays": db_repeat_weekdays,
                        "created_at": str(data.get("created_at", ""))
                    })

                except Exception as inner_error:
                    logger.error(f"Reminder document error: {inner_error}")

        return {"reminders": reminders}

    except Exception as e:
        logger.error(f"/reminders endpoint error: {e}")

        return {
            "reminders": [],
            "error": str(e)
        }


@app.get("/notes")
def get_all_notes(uid: str = Depends(get_current_user)):
    try:
        notes = []

        if firebase_initialized and db:
            docs = db.collection("users").document(uid).collection("notes").stream()

            for doc in docs:
                try:
                    data = doc.to_dict() or {}

                    notes.append({
                        "id": doc.id,
                        "content": data.get("content", ""),
                        "created_at": str(data.get("created_at", ""))
                    })

                except Exception as inner_error:
                    logger.error(f"Note document error: {inner_error}")

        return {"notes": notes}

    except Exception as e:
        logger.error(f"/notes endpoint error: {e}")

        return {
            "notes": [],
            "error": str(e)
        }


@app.put("/reminders/{reminder_id}")
def update_reminder(reminder_id: str, data: ReminderUpdate, uid: str = Depends(get_current_user)):
    if not firebase_initialized or not db:
        raise HTTPException(status_code=500, detail="Firestore not available")
    text = data.text.strip()
    time_val = data.time.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reminder text cannot be empty")
    doc_ref = db.collection("users").document(uid).collection("reminders").document(reminder_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Reminder not found")
        
    repeat_type = data.repeat_type
    repeat_interval = data.repeat_interval
    repeat_unit = data.repeat_unit
    repeat_weekdays = data.repeat_weekdays
    
    # Normalize frontend select values (none, daily, weekly, monthly)
    if repeat_type:
        repeat_type_lower = repeat_type.lower().strip()
        if repeat_type_lower == "none":
            repeat_type = None
            repeat_interval = None
            repeat_unit = None
            repeat_weekdays = None
        elif repeat_type_lower == "daily":
            repeat_type = "interval"
            repeat_interval = 1
            repeat_unit = "days"
            repeat_weekdays = None
        elif repeat_type_lower == "weekly":
            repeat_type = "interval"
            repeat_interval = 1
            repeat_unit = "weeks"
            repeat_weekdays = None
        elif repeat_type_lower == "monthly":
            repeat_type = "interval"
            repeat_interval = 1
            repeat_unit = "months"
            repeat_weekdays = None
            
    if not repeat_type:
        if repeat_weekdays:
            repeat_type = "weekday"
        elif repeat_unit and repeat_interval:
            repeat_type = "interval"
            
    if repeat_type == "interval":
        repeat_interval = repeat_interval or 1
        if repeat_unit:
            unit_clean = str(repeat_unit).lower().strip()
            if not unit_clean.endswith("s"):
                if unit_clean.startswith("min"):
                    unit_clean = "minutes"
                elif unit_clean.startswith("hour") or unit_clean.startswith("hr"):
                    unit_clean = "hours"
                elif unit_clean.startswith("day"):
                    unit_clean = "days"
                elif unit_clean.startswith("week"):
                    unit_clean = "weeks"
                elif unit_clean.startswith("month"):
                    unit_clean = "months"
                else:
                    unit_clean = unit_clean + "s"
            repeat_unit = unit_clean
        repeat_weekdays = None
    elif repeat_type == "weekday":
        repeat_interval = 1
        repeat_unit = "weekdays"
        if not repeat_weekdays:
            repeat_weekdays = []
        repeat_weekdays = [str(w).lower().strip() for w in repeat_weekdays]
    else:
        repeat_type = None
        repeat_interval = None
        repeat_unit = None
        repeat_weekdays = None
        
    # Get existing date/time if not supplied and roll forward if in the past
    existing_data = doc.to_dict() or {}
    reminder_date = data.date or existing_data.get("date") or datetime.datetime.now().strftime("%Y-%m-%d")
    reminder_time = normalize_time(time_val)
    
    try:
        parsed_time = datetime.datetime.strptime(reminder_time, "%I:%M %p").time()
        parsed_date = datetime.datetime.strptime(reminder_date, "%Y-%m-%d").date()
        reminder_dt = datetime.datetime.combine(parsed_date, parsed_time)
        
        ref_now = datetime.datetime.now()
        is_recurring = repeat_type is not None
        recurrence_data = {
            "repeat_type": repeat_type,
            "repeat_interval": repeat_interval,
            "repeat_unit": repeat_unit,
            "repeat_weekdays": repeat_weekdays
        }
        final_dt = make_future_datetime(reminder_dt, is_recurring, recurrence_data, ref_now)
        reminder_date = final_dt.strftime("%Y-%m-%d")
        reminder_time = final_dt.strftime("%I:%M %p")
    except Exception as err:
        logger.error(f"Error calculating future datetime on update: {err}")
        
    update_dict = {
        "text": text,
        "date": reminder_date,
        "time": reminder_time,
        "repeat_type": repeat_type,
        "repeat_interval": repeat_interval,
        "repeat_unit": repeat_unit,
        "repeat_weekdays": repeat_weekdays
    }
    
    doc_ref.update(update_dict)
    return {"status": "success", "message": "Reminder updated"}


@app.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str, uid: str = Depends(get_current_user)):
    if not firebase_initialized or not db:
        raise HTTPException(status_code=500, detail="Firestore not available")
    doc_ref = db.collection("users").document(uid).collection("reminders").document(reminder_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Reminder not found")
    doc_ref.delete()
    return {"status": "success", "message": "Reminder deleted"}


@app.put("/notes/{note_id}")
def update_note(note_id: str, data: NoteUpdate, uid: str = Depends(get_current_user)):
    if not firebase_initialized or not db:
        raise HTTPException(status_code=500, detail="Firestore not available")
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content cannot be empty")
    doc_ref = db.collection("users").document(uid).collection("notes").document(note_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Note not found")
    doc_ref.update({"content": content})
    return {"status": "success", "message": "Note updated"}


@app.delete("/notes/{note_id}")
def delete_note(note_id: str, uid: str = Depends(get_current_user)):
    if not firebase_initialized or not db:
        raise HTTPException(status_code=500, detail="Firestore not available")
    doc_ref = db.collection("users").document(uid).collection("notes").document(note_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Note not found")
    doc_ref.delete()
    return {"status": "success", "message": "Note deleted"}

@app.get("/memory")
def get_memory(uid: str = Depends(get_current_user)):
    memory = load_user_memory(uid)
    return {"memory": memory}

@app.delete("/memory")
def clear_memory(uid: str = Depends(get_current_user)):
    if firebase_initialized and db:
        db.collection("users").document(uid).collection("memory").document("profile").delete()
        return {"status": "success", "message": "Memory cleared"}
    return {"status": "error", "message": "Firebase not available"}
@app.on_event("startup")
async def startup_event():
    try:
        scheduler.add_job(
            cleanup_expired_reminders,
            "interval",
            minutes=1
        )
        scheduler.add_job(
            send_due_reminder_emails,
            "interval",
            minutes=1
        )
        scheduler.start()

        logger.info("Scheduler started successfully")

    except Exception as e:
        logger.error(f"Scheduler failed: {e}")

@app.post("/save-profile")
async def save_profile(
    request: ProfileRequest,
    authorization: str = Header(None)
):
    uid = await get_current_user(authorization)

    db.collection("users").document(uid).set(
        {
            "name": request.name,
            "email": request.email
        },
        merge=True
    )

    return {"success": True}

@router.get("/process-reminders")
async def process_reminders():
    try:
        logger.info("Starting reminder processing")
        now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
        processed = 0
        reminders = db.collection_group("reminders").stream()
        for reminder_doc in reminders:
            try:
                data = reminder_doc.to_dict()
                if data.get("email_sent", False):
                    continue
                reminder_date = data.get("date")
                reminder_time = data.get("time")

                if not reminder_date or not reminder_time:
                    continue

                datetime_str = (f"{reminder_date} {reminder_time}")

                format = ["%Y-%m-%d %H:%M %p", "%Y-%m-%d %I %p", "%Y-%m-%d %H:%M"]
                reminder_datetime = None
                for fmt in format:
                    try:
                        reminder_datetime = datetime.datetime.strptime(datetime_str, fmt)
                        reminder_datetime = reminder_datetime.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                        break
                    except ValueError:
                        pass
                if reminder_datetime is None:
                    logger.warning(f"Could not parse reminder {reminder_doc.id}: {datetime_str}")
                    continue

                if reminder_datetime <= now:
                    user_id = (
                        reminder_doc.reference
                        .parent.parent.id
                    )
                    user_doc = db.collection("users").document(user_id).get()
                    if not user_doc.exists:
                        continue
                    user_data = user_doc.to_dict()
                    email = user_data.get("email")
                    if not email:
                        logger.warning(f"User {user_id} has no email")
                        continue
                    reminder_text = data.get("text", "reminder")
                    user_name = user_data.get("name", "User")
                    email_sent = send_email_notification(recipient_email=email, user_name=user_name, reminder_text=reminder_text, reminder_time=reminder_time)
                    if email_sent:
                        reminder_doc.reference.update({"email_sent": True, "sent_at": firestore.SERVER_TIMESTAMP})
                        processed +=1
                        logger.info(f"Sent reminder {reminder_text} to {email}")
            except Exception as e:
                logger.error(f"Error processing reminder {reminder_doc.id}")
        return {
            "status": "success",
            "processed": processed,
            "checked_at": now.isoformat()
        }
    except Exception as e:
        logger.exception(f"process_reminders failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

                    

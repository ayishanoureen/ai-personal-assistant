from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from firebase_admin import firestore
from dateutil.relativedelta import relativedelta

scheduler = BackgroundScheduler()

db = firestore.client()

def calculate_next_occurrence(date_str, time_str, interval, unit):
    try:
        current = datetime.strptime(
            f"{date_str} {time_str}",
            "%Y-%m-%d %I:%M %p"
        )

        now = datetime.now()

        next_dt = current

        if unit == "hours":

            while next_dt <= now:
                next_dt += timedelta(hours=interval)

        elif unit == "days":

            while next_dt <= now:
                next_dt += timedelta(days=interval)

        elif unit == "weeks":

            while next_dt <= now:
                next_dt += timedelta(weeks=interval)

        elif unit == "months":

            while next_dt <= now:
                next_dt += relativedelta(months=interval)

        else:
            return None

        return next_dt

    except Exception as e:
        print(f"Error calculating next occurrence: {e}")
        return None


def process_recurring_reminders():
    db = firestore.client()

    users = db.collection("users").stream()

    for user_doc in users:

        uid = user_doc.id

        reminders = (
            db.collection("users")
            .document(uid)
            .collection("reminders")
            .stream()
        )

        for reminder in reminders:

            data = reminder.to_dict()

            date_str = data.get("date")
            time_str = data.get("time")

            repeat_interval = data.get("repeat_interval")
            repeat_unit = data.get("repeat_unit")

            if repeat_unit and (
                repeat_interval is None
                or repeat_interval <= 0
            ):
                reminder.reference.delete()
                continue

            if not date_str or not time_str:
                continue

            try:

                reminder_dt = datetime.strptime(
                    f"{date_str} {time_str}",
                    "%Y-%m-%d %I:%M %p"
                )

            except Exception:
                continue

            now = datetime.now()

            if reminder_dt <= now:

                print(
                    f"Triggering reminder for user {uid}: "
                    f"{data.get('text', '')}"
                )

                # One-time reminder
                if not repeat_interval or not repeat_unit:

                    reminder.reference.delete()

                    continue

                next_dt = calculate_next_occurrence(
                    date_str,
                    time_str,
                    repeat_interval,
                    repeat_unit
                )

                if not next_dt:

                    reminder.reference.delete()

                    continue

                reminder.reference.update({
                    "date": next_dt.strftime("%Y-%m-%d"),
                    "time": next_dt.strftime("%I:%M %p")
                })


scheduler.add_job(
    process_recurring_reminders,
    "interval",
    minutes=1,
    max_instance=1,
    coalesce=True
)

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        print("Recurring reminder scheduler started")


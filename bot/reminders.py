from datetime import datetime

from telegram.ext import ContextTypes

from . import db


async def reminder_loop(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow().isoformat(timespec="minutes")
    reminders = db.get_due_reminders(now)
    for reminder_id, user_id, ev_date, ev_time, ev_type in reminders:
        try:
            await context.bot.send_message(chat_id=user_id,
                                           text=f"⏰ Напоминание!\n📅 {ev_date} 🕒 {ev_time}\n🎯 {ev_type}")
        except Exception as e:
            print("Ошибка отправки напоминания:", e)
        db.mark_reminder_sent(reminder_id)

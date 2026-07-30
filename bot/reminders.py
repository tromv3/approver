import logging
from datetime import datetime

from telegram.ext import ContextTypes

from . import db

logger = logging.getLogger(__name__)


async def reminder_loop(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow().isoformat(timespec="minutes")
    reminders = db.get_due_reminders(now)
    for reminder_id, user_id, ev_date, ev_time, ev_type in reminders:
        try:
            await context.bot.send_message(chat_id=user_id,
                                           text=f"⏰ Напоминание!\n📅 {ev_date} 🕒 {ev_time}\n🎯 {ev_type}")
        except Exception:
            logger.exception("Ошибка отправки напоминания пользователю %s", user_id)
        db.mark_reminder_sent(reminder_id)

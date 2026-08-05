import logging
from datetime import datetime, timezone

from telegram.ext import ContextTypes

from . import db

logger = logging.getLogger(__name__)


async def reminder_loop(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes")
    reminders = db.claim_due_reminders(now)
    for reminder_id, user_id, event_id, ev_date, ev_time, ev_type, creator_id, participant_id in reminders:
        other_id = participant_id if user_id == creator_id else creator_id
        other_label = db.get_user_label(other_id)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Напоминание!\n📅 {ev_date} 🕒 {ev_time}\n🎯 {ev_type}\n👤 С кем: {other_label}\n#{event_id}",
            )
        except Exception:
            logger.exception("Ошибка отправки напоминания пользователю %s", user_id)

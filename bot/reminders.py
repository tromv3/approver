import logging
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import db, health

logger = logging.getLogger(__name__)

SNOOZE_OPTIONS = {10: "10 минут", 60: "1 час"}


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def reminder_loop(context: ContextTypes.DEFAULT_TYPE):
    health.beat()
    now = _utc_naive_now().isoformat(timespec="minutes")
    reminders = db.claim_due_reminders(now)
    for reminder_id, user_id, event_id, ev_date, ev_time, ev_type, creator_id, participant_id in reminders:
        other_id = participant_id if user_id == creator_id else creator_id
        other_label = db.get_user_label(other_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"⏰ Через {label}", callback_data=f"snooze_{event_id}_{minutes}")
            for minutes, label in SNOOZE_OPTIONS.items()
        ]])
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Напоминание!\n📅 {ev_date} 🕒 {ev_time}\n🎯 {ev_type}\n👤 С кем: {other_label}\n#{event_id}",
                reply_markup=kb,
            )
        except Exception:
            logger.exception("Ошибка отправки напоминания пользователю %s", user_id)


async def snooze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка «Отложить» под напоминанием: ставит ещё одно напоминание через N минут."""
    q = update.callback_query
    try:
        _, event_id, minutes = q.data.split("_")
        event_id, minutes = int(event_id), int(minutes)
    except ValueError:
        return await q.answer()
    if minutes not in SNOOZE_OPTIONS:
        return await q.answer()

    ev = db.get_event(event_id)
    if not ev or q.from_user.id not in (ev[1], ev[2]) or ev[6] != "accepted":
        return await q.answer("Событие уже недоступно.", show_alert=True)

    remind_at = (_utc_naive_now() + timedelta(minutes=minutes)).isoformat(timespec="minutes")
    db.add_reminder_at(q.from_user.id, event_id, remind_at)
    await q.answer(f"Напомню через {SNOOZE_OPTIONS[minutes]}")
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

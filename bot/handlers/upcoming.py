from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import db
from ..constants import MONTHS_RU_GEN, WEEKDAYS_RU
from .common import send_text

MAX_TEXT = 3800  # лимит Telegram — 4096 символов на сообщение
MAX_ACTION_ROWS = 5  # сколько приглашений с кнопками «Принять/Отклонить» показываем


def _day_title(d: date, today: date) -> str:
    if d == today:
        return "Сегодня"
    if d == today + timedelta(days=1):
        return "Завтра"
    return f"{d.day} {MONTHS_RU_GEN[d.month]}, {WEEKDAYS_RU[d.weekday()]}"


def _event_line(ev, viewer_id: int) -> str:
    event_id, creator_id, participant_id, _, ev_time, etype, status = ev[:7]
    other_id = participant_id if viewer_id == creator_id else creator_id
    who = db.get_user_label(other_id)
    if status == "accepted":
        mark = "🟢"
    elif viewer_id == participant_id:
        mark = "⏳ ждёт вашего ответа"
    else:
        mark = "⏳ ждёт ответа"
    return f"🕒 {ev_time} — 🎯 {etype} · {who} {mark} (#{event_id})"


def build_upcoming(user_id: int, days: int):
    """Текст и клавиатура для экрана «Ближайшие» на `days` дней вперёд (1 = только сегодня)."""
    now = db.now_local()
    today = now.date()
    to_date = today + timedelta(days=days - 1)
    events = db.get_upcoming_events_for_user(
        user_id, today.isoformat(), now.strftime("%H:%M"), to_date.isoformat())

    title = "📆 События на сегодня" if days == 1 else f"📆 Ближайшие события ({days} дн.)"
    nav = [InlineKeyboardButton("📅 События", callback_data="events"),
           InlineKeyboardButton("⬅️ В меню", callback_data="back_to_main")]

    if not events:
        text = f"{title}\n\nПока ничего не запланировано."
        kb = [[InlineKeyboardButton("➕ Создать событие", callback_data="event_create")], nav]
        return text, InlineKeyboardMarkup(kb)

    lines = [title]
    current_day = None
    shown = 0
    for ev in events:
        ev_day = date.fromisoformat(ev[3])
        block = []
        if ev_day != current_day:
            block.append(f"\n{_day_title(ev_day, today)}")
            current_day = ev_day
        block.append(_event_line(ev, user_id))
        if len("\n".join(lines + block)) > MAX_TEXT:
            lines.append(f"\n… и ещё {len(events) - shown}. Откройте «Мои события» для полного списка.")
            break
        lines.extend(block)
        shown += 1

    kb = []
    incoming = [ev for ev in events if ev[2] == user_id and ev[6] == "pending"][:MAX_ACTION_ROWS]
    for ev in incoming:
        kb.append([InlineKeyboardButton(f"✅ Принять #{ev[0]}", callback_data=f"accept_event_{ev[0]}"),
                   InlineKeyboardButton(f"❌ Отклонить #{ev[0]}", callback_data=f"reject_event_{ev[0]}")])
    kb.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int = 7):
    if update.callback_query:
        await update.callback_query.answer()
    text, kb = build_upcoming(update.effective_user.id, days)
    await send_text(update, text, kb)


async def upcoming_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_upcoming(update, context, days=7)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_upcoming(update, context, days=1)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_upcoming(update, context, days=7)

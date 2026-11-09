from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from .. import db
from . import events, friends, upcoming
from .common import (BTN_EVENTS, BTN_FRIENDS, BTN_HELP, BTN_UPCOMING, HELP_TEXT, REPLY_KEYBOARD,
                     clear_flow_state, send_text, show_main_menu)


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет запись о пользователе на каждом апдейте: username и имя в Telegram
    меняются, а поиск друзей работает по сохранённым значениям."""
    u = update.effective_user
    if u is None or u.is_bot:
        return
    db.upsert_user(u.id, u.username, u.first_name, u.last_name, datetime.now(timezone.utc).isoformat())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    clear_flow_state(context)
    await update.message.reply_text(
        f"Привет, {u.first_name or 'друг'}! Я помогаю договариваться о встречах: предлагайте друзьям "
        "события, а они принимают или отклоняют их. Перед событием я напомню.\n\n"
        "Меню внизу всегда под рукой, а /help расскажет подробнее.",
        reply_markup=REPLY_KEYBOARD,
    )
    if context.args and context.args[0].startswith("inv_"):
        await friends.handle_invite(update, context, context.args[0][4:])
    await show_main_menu(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В меню", callback_data="back_to_main")]])
    await send_text(update, HELP_TEXT, kb)


async def reply_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нижняя клавиатура приходит обычным текстом. Работает раньше остальных текстовых
    хендлеров (group -1) и останавливает дальнейшую обработку, чтобы подпись кнопки не
    приняли за ввод имени друга, времени и т.п."""
    text = update.message.text
    clear_flow_state(context)
    if text == BTN_UPCOMING:
        await upcoming.show_upcoming(update, context, days=7)
    elif text == BTN_EVENTS:
        await events.handle_events_menu(update, context)
    elif text == BTN_FRIENDS:
        await friends.handle_friends_menu(update, context)
    elif text == BTN_HELP:
        await help_command(update, context)
    raise ApplicationHandlerStop

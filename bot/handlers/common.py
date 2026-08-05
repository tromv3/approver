from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.ext import ContextTypes

from .. import db

# Ключи в context.user_data, которыми хендлеры отмечают "жду текстовый ввод для X".
# Сбрасываются при любом возврате в одно из главных меню, чтобы случайный текст
# после нажатия "Назад"/"Отмена" не был ошибочно принят за ввод для незавершённого флоу.
FLOW_STATE_KEYS = (
    "adding_friend",
    "awaiting_event_type_custom",
    "awaiting_reject_for_event",
    "event_date",
    "event_time",
    "event_type",
    "event_friend_id",
    "event_reminder_minutes",
)


def clear_flow_state(context: ContextTypes.DEFAULT_TYPE):
    for key in FLOW_STATE_KEYS:
        context.user_data.pop(key, None)


def mention(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"ID {user.id}"


# small helper to reply whether update is callback_query or message
async def send_text(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_flow_state(context)
    kb = [
        [InlineKeyboardButton("Друзья", callback_data="friends")],
        [InlineKeyboardButton("События", callback_data="events")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text="Главное меню. Выберите раздел:",
            reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(
            text="Главное меню. Выберите раздел:",
            reply_markup=InlineKeyboardMarkup(kb))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    date_joined = (update.message.date or datetime.now(timezone.utc)).isoformat()
    db.upsert_user(u.id, u.username, u.first_name, u.last_name, date_joined)
    await show_main_menu(update, context)

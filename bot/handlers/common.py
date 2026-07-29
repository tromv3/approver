from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import db


# small helper to reply whether update is callback_query or message
async def send_text(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    date_joined = (update.message.date or datetime.utcnow()).isoformat()
    db.upsert_user(u.id, u.username, u.first_name, u.last_name, date_joined)
    await show_main_menu(update, context)

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import db
from .common import send_text, show_main_menu

logger = logging.getLogger(__name__)


async def handle_friends_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("Добавить в друзья", callback_data="add_friend")],
        [InlineKeyboardButton("Мои друзья", callback_data="list_friends")],
        [InlineKeyboardButton("Заявки в друзья", callback_data="pending_requests")],
        [InlineKeyboardButton("Удалить из друзей", callback_data="remove_friend")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")],
        [InlineKeyboardButton("К Событиям", callback_data="events")],
    ]
    await q.edit_message_text(text="Раздел 'Друзья'. Выберите действие:", reply_markup=InlineKeyboardMarkup(kb))


async def add_friend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["adding_friend"] = True
    kb = [
        [InlineKeyboardButton("Назад", callback_data="back_to_main")],
    ]
    return await send_text(update, "Введите @username или числовой ID пользователя, которого хотите добавить:",
                           reply_markup=InlineKeyboardMarkup(kb))


async def add_friend_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("adding_friend", False):
        return None
    text = update.message.text.strip()
    me = update.effective_user
    target = db.get_user_by_identifier(text)
    if not target:
        return await update.message.reply_text("Пользователь не найден или не запускал бота.")
    tid, _ = target
    if tid == me.id:
        return await update.message.reply_text("Нельзя добавить себя в друзья.")

    if db.get_friend_status(me.id, tid) == "accepted":
        await update.message.reply_text("Вы уже в друзьях.")
        return await show_main_menu(update, context)

    # insert pending request (from me -> tid)
    db.add_pending_friend_request(me.id, tid)

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Принять", callback_data=f"friend_accept_{me.id}"),
          InlineKeyboardButton("Отклонить", callback_data=f"friend_reject_{me.id}")]]
    )
    try:
        await context.bot.send_message(chat_id=tid, text=f"@{me.username} отправил(а) вам заявку в друзья.",
                                       reply_markup=kb)
    except Exception:
        logger.exception("Не удалось отправить заявку в друзья пользователю %s", tid)

    await update.message.reply_text("Заявка отправлена.")
    return await show_main_menu(update, context)


async def pending_requests_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    rows = db.get_pending_requests(user.id)
    if not rows:
        await q.edit_message_text("Нет входящих заявок.")
        return await show_main_menu(update, context)

    kb = []
    text = "Заявки:"
    for sender_id, uname in rows:
        label = f"@{uname}" if uname else str(sender_id)
        kb.append([InlineKeyboardButton(f"Принять {label}", callback_data=f"friend_accept_{sender_id}"),
                   InlineKeyboardButton("Отклонить", callback_data=f"friend_reject_{sender_id}")])
        text += f"{label}"
    kb.append([InlineKeyboardButton("Назад", callback_data="friends")])
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def friend_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    db.accept_friend_request(sender_id, recipient_id)

    try:
        await context.bot.send_message(chat_id=sender_id,
                                       text=f"Пользователь @{q.from_user.username} принял вашу заявку.")
        await q.edit_message_text("Заявка принята.")
    except Exception:
        pass


async def friend_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    db.delete_friend_request(sender_id, recipient_id)

    try:
        await context.bot.send_message(chat_id=sender_id,
                                       text=f"Пользователь @{q.from_user.username} отклонил вашу заявку.")
        await q.edit_message_text("Заявка отклонена.")
        return await show_main_menu(update, context)
    except Exception:
        return await show_main_menu(update, context)


async def list_friends_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = db.get_friends(q.from_user.id)
    if not rows:
        return await q.edit_message_text("У вас нет друзей.")

    text = "Ваши друзья:\n" + "".join([f"@{r[1]}\n" if r[1] else str(r[0]) for r in rows])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Назад", callback_data="friends")]]))
    return None


async def remove_friend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = db.get_friends(q.from_user.id)
    if not rows:
        await q.edit_message_text("Нет друзей для удаления.")
        return await show_main_menu(update, context)

    kb = [[InlineKeyboardButton(f"Удалить @{r[1] or r[0]}", callback_data=f"friend_remove_{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton("Назад", callback_data="friends")])
    await q.edit_message_text("Выберите друга для удаления:", reply_markup=InlineKeyboardMarkup(kb))
    return None


async def friend_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fid = int(q.data.split("_")[-1])
    me = q.from_user.id

    db.remove_friendship(me, fid)

    try:
        await context.bot.send_message(chat_id=fid, text=f"Пользователь @{q.from_user.username} удалил вас из друзей.")
    except Exception:
        pass

    await q.edit_message_text("Друг удалён.")
    return await show_main_menu(update, context)

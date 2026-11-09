import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.ext import ContextTypes

from .. import db
from ..pagination import nav_row, paginate
from .common import clear_flow_state, mention, send_text, show_main_menu

logger = logging.getLogger(__name__)


async def handle_friends_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    clear_flow_state(context)
    kb = [
        [InlineKeyboardButton("Добавить в друзья", callback_data="add_friend")],
        [InlineKeyboardButton("🔗 Пригласить по ссылке", callback_data="invite_link")],
        [InlineKeyboardButton("Мои друзья", callback_data="list_friends")],
        [InlineKeyboardButton("Заявки в друзья", callback_data="pending_requests")],
        [InlineKeyboardButton("Удалить из друзей", callback_data="remove_friend")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")],
        [InlineKeyboardButton("К Событиям", callback_data="events")],
    ]
    await send_text(update, "Раздел 'Друзья'. Выберите действие:", InlineKeyboardMarkup(kb))


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
        return await update.message.reply_text(
            "Пользователь не найден или не запускал бота. Можно отправить ему ссылку-приглашение "
            "(Друзья → Пригласить по ссылке).")
    tid, _ = target
    if tid == me.id:
        return await update.message.reply_text("Нельзя добавить себя в друзья.")

    my_status = db.get_friend_status(me.id, tid)
    if my_status == "accepted":
        await update.message.reply_text("Вы уже в друзьях.")
        return await show_main_menu(update, context)
    if my_status == "pending":
        await update.message.reply_text("Вы уже отправили заявку этому пользователю. Ожидайте ответа.")
        return await show_main_menu(update, context)

    if db.get_friend_status(tid, me.id) == "pending":
        # Этот пользователь уже прислал нам заявку — принимаем её вместо
        # того чтобы заводить встречную pending-заявку, которая всё равно
        # ни к чему не приведёт без ручного принятия.
        db.accept_friend_request(tid, me.id)
        try:
            await context.bot.send_message(chat_id=tid, text=f"{mention(me)} принял(а) вашу заявку в друзья.")
        except Exception:
            logger.exception("Не удалось уведомить пользователя %s о принятии заявки", tid)
        await update.message.reply_text(
            "У этого пользователя уже была заявка вам — вы автоматически стали друзьями.")
        return await show_main_menu(update, context)

    # insert pending request (from me -> tid)
    db.add_pending_friend_request(me.id, tid)

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Принять", callback_data=f"friend_accept_{me.id}"),
          InlineKeyboardButton("Отклонить", callback_data=f"friend_reject_{me.id}")]]
    )
    try:
        await context.bot.send_message(chat_id=tid, text=f"{mention(me)} отправил(а) вам заявку в друзья.",
                                       reply_markup=kb)
    except Exception:
        logger.exception("Не удалось отправить заявку в друзья пользователю %s", tid)

    await update.message.reply_text("Заявка отправлена.")
    return await show_main_menu(update, context)


# ---------------- приглашение по ссылке ----------------
def _invite_link(context: ContextTypes.DEFAULT_TYPE, token: str) -> str:
    return f"https://t.me/{context.bot.username}?start=inv_{token}"


async def _show_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, note: str = ""):
    text = (
        f"{note}🔗 Ваша ссылка-приглашение:\n{_invite_link(context, token)}\n\n"
        "Отправьте её другу: открыв ссылку, он сразу станет вашим другом в боте. "
        "Если ссылка попала не тому человеку — сбросьте её, старая перестанет работать."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Сбросить ссылку", callback_data="invite_reset")],
        [InlineKeyboardButton("Назад", callback_data="friends")],
    ])
    await update.callback_query.edit_message_text(
        text, reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True))


async def invite_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _show_invite(update, context, db.get_or_create_invite_token(update.effective_user.id))


async def invite_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    token = db.reset_invite_token(update.effective_user.id)
    await _show_invite(update, context, token, note="✅ Старая ссылка отключена.\n\n")


async def handle_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    """Пользователь открыл бота по чужой ссылке-приглашению (/start inv_<токен>)."""
    me = update.effective_user
    inviter = db.get_user_by_invite_token(token)
    if not inviter:
        return await update.message.reply_text("Ссылка-приглашение недействительна или была сброшена.")
    inviter_id, _ = inviter
    if inviter_id == me.id:
        return await update.message.reply_text("Это ваша собственная ссылка — отправьте её другу.")
    if db.get_friend_status(me.id, inviter_id) == "accepted":
        return await update.message.reply_text(f"Вы уже друзья с {db.get_user_label(inviter_id)}.")

    db.make_friends(me.id, inviter_id)
    await update.message.reply_text(f"🎉 Вы теперь друзья с {db.get_user_label(inviter_id)}!")
    try:
        await context.bot.send_message(
            chat_id=inviter_id, text=f"🎉 {mention(me)} присоединился(ась) по вашей ссылке — вы теперь друзья.")
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о принятии приглашения", inviter_id)


# ---------------- заявки ----------------
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
        text += f"\n{label}"
    kb.append([InlineKeyboardButton("Назад", callback_data="friends")])
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def friend_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="back_to_main")]])
    # Кнопка могла устареть (заявку уже приняли/отклонили/отозвали): без этой проверки
    # старое сообщение создавало бы одностороннюю дружбу.
    if db.get_friend_status(sender_id, recipient_id) != "pending":
        try:
            await q.edit_message_text("Эта заявка уже обработана или отозвана.", reply_markup=kb)
        except Exception:
            pass
        return None

    db.accept_friend_request(sender_id, recipient_id)

    try:
        await context.bot.send_message(chat_id=sender_id,
                                       text=f"Пользователь {mention(q.from_user)} принял вашу заявку.")
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о принятии заявки", sender_id)
    try:
        await q.edit_message_text("Заявка принята.", reply_markup=kb)
    except Exception:
        pass
    return None


async def friend_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    if db.get_friend_status(sender_id, recipient_id) != "pending":
        try:
            await q.edit_message_text(
                "Эта заявка уже обработана или отозвана.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="back_to_main")]]))
        except Exception:
            pass
        return None

    db.delete_friend_request(sender_id, recipient_id)

    try:
        await context.bot.send_message(chat_id=sender_id,
                                       text=f"Пользователь {mention(q.from_user)} отклонил вашу заявку.")
        await q.edit_message_text("Заявка отклонена.")
        return await show_main_menu(update, context)
    except Exception:
        return await show_main_menu(update, context)


# ---------------- списки ----------------
def _friend_label(row) -> str:
    return f"@{row[1]}" if row[1] else str(row[0])


async def list_friends_start(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    q = update.callback_query
    await q.answer()
    rows = db.get_friends(q.from_user.id)
    back = [InlineKeyboardButton("Назад", callback_data="friends")]
    if not rows:
        return await q.edit_message_text("У вас нет друзей.", reply_markup=InlineKeyboardMarkup([back]))

    chunk, page, pages = paginate(rows, page)
    text = f"Ваши друзья ({len(rows)}):\n" + "".join(f"{_friend_label(r)}\n" for r in chunk)
    kb = nav_row("frlist", page, pages) + [back]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return None


async def remove_friend_start(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    q = update.callback_query
    await q.answer()
    rows = db.get_friends(q.from_user.id)
    if not rows:
        await q.edit_message_text("Нет друзей для удаления.")
        return await show_main_menu(update, context)

    chunk, page, pages = paginate(rows, page)
    kb = [[InlineKeyboardButton(f"Удалить {_friend_label(r)}", callback_data=f"friend_remove_{r[0]}")] for r in chunk]
    kb += nav_row("frrm", page, pages)
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
        await context.bot.send_message(chat_id=fid, text=f"Пользователь {mention(q.from_user)} удалил вас из друзей.")
    except Exception:
        pass

    await q.edit_message_text("Друг удалён.")
    return await show_main_menu(update, context)

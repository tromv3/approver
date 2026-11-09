import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import db
from ..constants import AWAIT_REJECT, EV_CONFIRM, EV_SEL_DATE, EV_SEL_REM, EV_SEL_TIME, EV_TYPE_CH, EV_TYPE_CUSTOM, \
    STD_REMS, STD_TYPES
from ..keyboards import build_calendar_keyboard
from ..pagination import nav_row, paginate
from .common import clear_flow_state, mention

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "pending": "⏳ Ожидает ответа",
    "accepted": "🟢 Принято",
    "declined": "🔴 Отклонено",
    "cancelled": "⚪ Отменено",
}


def format_event_row(ev, viewer_id):
    user_1 = db.get_user_by_identifier(ev[1])
    user_2 = db.get_user_by_identifier(ev[2])
    if user_1[0] == viewer_id:
        user = user_2[1]
    else:
        user = user_1[1]
    status_label = STATUS_LABELS.get(ev[6], ev[6])
    line = f"#{ev[0]} — 📅 {ev[3]} 🕒 {ev[4]} — 🎯 {ev[5]} c {user} — {status_label}"
    if ev[6] == "declined" and ev[7]:
        line += f" (причина: {ev[7]})"
    return line


async def handle_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Определяем источник обновления
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        is_callback = True
    else:
        chat_id = update.message.chat_id
        message_id = None
        is_callback = False

    clear_flow_state(context)

    # Создаем клавиатуру меню событий
    kb = [
        [InlineKeyboardButton("Создать событие", callback_data="event_create")],
        [InlineKeyboardButton("Мои события", callback_data="event_my")],
        [InlineKeyboardButton("Изменить событие", callback_data="event_edit")],
        [InlineKeyboardButton("Ожидают ответа", callback_data="event_pending_sent")],
        [InlineKeyboardButton("Удалить событие", callback_data="event_delete")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]

    # Отправляем/редактируем сообщение
    if is_callback:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="Меню событий",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Меню событий",
            reply_markup=InlineKeyboardMarkup(kb)
        )


# Добавляем удобный выбор времени
async def show_time_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Получаем выбранную дату
    selected_date = datetime.strptime(context.user_data["event_date"], "%Y-%m-%d").date()
    today = db.now_local().date()

    # Проверка на прошедшую дату
    if selected_date < today:
        await query.edit_message_text(
            "❌ Нельзя создавать события на прошедшие даты!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return None

    # Генерация временных слотов
    time_slots = []
    now = db.now_local()

    # Если выбрана сегодняшняя дата - начинаем с текущего времени + 30 минут
    if selected_date == today:
        start_time = now + timedelta(minutes=30)
        current_hour = start_time.hour
        current_minute = (start_time.minute // 30) * 30  # Округляем до ближайших 30 минут
    else:
        # Для будущих дней начинаем с 8:00
        current_hour = 8
        current_minute = 0

    # Создаем слоты с интервалом 30 минут
    while current_hour < 22 or (current_hour == 22 and current_minute == 0):
        time_str = f"{current_hour:02d}:{current_minute:02d}"

        # Для сегодняшней даты дополнительно проверяем, не прошло ли уже время
        if selected_date == today:
            selected_datetime = datetime.combine(selected_date, datetime.strptime(time_str, "%H:%M").time())
            if selected_datetime < now:
                current_minute += 30
                if current_minute >= 60:
                    current_hour += 1
                    current_minute = 0
                continue  # Пропускаем прошедшие временные слоты

        time_slots.append(InlineKeyboardButton(time_str, callback_data=f"time_{time_str}"))

        # Увеличиваем время на 30 минут
        current_minute += 30
        if current_minute >= 60:
            current_hour += 1
            current_minute = 0

    # Если нет доступных временных слотов (все уже прошли)
    if not time_slots and selected_date == today:
        await query.edit_message_text(
            "❌ На сегодня все возможные временные слоты уже прошли!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return None

    # Разбиваем на строки по 4 кнопки
    keyboard = [time_slots[i:i + 4] for i in range(0, len(time_slots), 4)]
    keyboard.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data="manual_time_input")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="events")])

    await query.edit_message_text(
        "🕒 Выберите время или введите вручную (HH:MM):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EV_SEL_TIME


async def event_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ждём время только в окне между выбором даты и выбором времени; иначе это
    # текст для другого флоу (кастомный тип события, причина отказа и т.п.) —
    # не перехватываем его.
    if "event_date" not in context.user_data or "event_time" in context.user_data:
        return None

    text = update.message.text.strip()

    try:
        # Проверяем формат времени
        input_time = datetime.strptime(text, "%H:%M").time()
        selected_date = datetime.strptime(context.user_data["event_date"], "%Y-%m-%d").date()
        selected_datetime = datetime.combine(selected_date, input_time)

        # Проверка на прошедшее время
        if selected_datetime < db.now_local():
            await update.message.reply_text("❌ Нельзя создавать события в прошедшем времени! Выберите будущее время.")
            return EV_SEL_TIME

        context.user_data["event_time"] = text
        return await show_event_type_selection(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Введите в формате ЧЧ:ММ (например, 14:30) или выберите из предложенных вариантов.")
        return EV_SEL_TIME


async def handle_time_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "manual_time_input":
        await query.edit_message_text(
            "⌨️ Введите время в формате ЧЧ:ММ (например, 14:30):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="events")]])
        )
        return EV_SEL_TIME

    # Обработка выбранного времени
    if query.data.startswith("time_"):
        time_str = query.data.split("_")[1]
        context.user_data["event_time"] = time_str

        # Показываем подтверждение
        await query.edit_message_text(f"✅ Выбрано время: {time_str}")

        # Переходим к выбору типа события
        return await show_event_type_selection(update, context)

    return None


async def show_event_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(t, callback_data=f"event_type_{t}")] for t in STD_TYPES]
    kb.append([InlineKeyboardButton("Назад", callback_data="events")])

    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "Выберите тип события или введите свой:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        query = update.callback_query
        await query.edit_message_text(
            "Выберите тип события или введите свой:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    return EV_TYPE_CH


async def event_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    today = db.now_local().date()
    kb = build_calendar_keyboard(today.year, today.month, uid, mode="create")
    await q.edit_message_text(text="Выберите дату для события:", reply_markup=kb)
    return EV_SEL_DATE


async def event_my_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    today = db.now_local().date()
    kb = build_calendar_keyboard(today.year, today.month, user_id, mode="view")
    await query.edit_message_text("Календарь — дни с событиями помечены ✱. Выберите день для просмотра:",
                                  reply_markup=kb)


def _calendar_title(mode: str) -> str:
    if mode == "create":
        return "Выберите дату для события:"
    if mode == "editdate":
        return "Выберите новую дату:"
    return "Календарь событий"


async def event_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("select_date_create_"):
        day_str = data.split("_", 3)[3]
        selected_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        today = db.now_local().date()

        if selected_date < today:
            await q.edit_message_text(
                "❌ Нельзя создавать события на прошедшие даты!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
            )
            return None

        context.user_data["event_date"] = day_str

        return await show_time_suggestions(update, context)

    if data.startswith("cal_prev_"):
        # Обработка перехода к предыдущему месяцу
        _, _, mode, year, month, _ = data.split('_')
        year = int(year)
        month = int(month)

        # Вычисляем предыдущий месяц
        if month == 1:
            prev_month = 12
            prev_year = year - 1
        else:
            prev_month = month - 1
            prev_year = year

        # Перестраиваем календарь для предыдущего месяца
        kb = build_calendar_keyboard(prev_year, prev_month, q.from_user.id, mode)
        await q.edit_message_text(text=_calendar_title(mode), reply_markup=kb)
        return EV_SEL_DATE if mode == "create" else None

    elif data.startswith("cal_next_"):
        # Обработка перехода к следующему месяцу
        _, _, mode, year, month, _ = data.split('_')
        year = int(year)
        month = int(month)

        # Вычисляем следующий месяц
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year

        # Перестраиваем календарь для следующего месяца
        kb = build_calendar_keyboard(next_year, next_month, q.from_user.id, mode)
        await q.edit_message_text(text=_calendar_title(mode), reply_markup=kb)
        return EV_SEL_DATE if mode == "create" else None

    if data.startswith("select_date_editdate_"):
        if "editing_event_id" not in context.user_data:
            await q.edit_message_text(
                "Сессия изменения истекла, начните заново.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))
            return None

        day_str = data.split("_", 3)[3]
        selected_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        today = db.now_local().date()

        if selected_date < today:
            await q.edit_message_text(
                "❌ Нельзя переносить событие на прошедшую дату!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
            )
            return None

        context.user_data["editing_event_date"] = day_str
        await q.edit_message_text(f"Новая дата: {day_str}\nТеперь введите новое время (ЧЧ:ММ):")
        return None

    if data.startswith("select_date_view_"):
        day_str = data.split("_", 3)[3]
        events = db.get_events_on_day_for_user(q.from_user.id, day_str)
        if not events:
            await q.edit_message_text(
                text=f"📅 На {day_str} у вас нет событий.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_my")]])
            )
            return None

        text = f"📅 События на {day_str}:\n"
        text += "\n".join([format_event_row(e, q.from_user.id) for e in events])
        await q.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_my")]])
        )
        return None

    return None


async def event_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chosen = data[len("event_type_"):]
    if chosen == "Другое (ввести свой)":
        context.user_data["awaiting_event_type_custom"] = True
        await q.edit_message_text(text="Введите название типа события (например, Встреча с клиентом):",
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("Отмена", callback_data="events")]]))
        return EV_TYPE_CUSTOM
    context.user_data["event_type"] = chosen
    return await prompt_choose_friend_for_event(update, context)


async def event_type_custom_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_event_type_custom", False):
        return None
    text = update.message.text.strip()
    if not text:
        return await update.message.reply_text("Пустой тип. Введите текст типа события:")
    context.user_data["event_type"] = text
    return await prompt_choose_friend_for_event(update, context)


async def prompt_choose_friend_for_event(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        send = q.edit_message_text
        user = q.from_user
    else:
        msg = update.message
        send = msg.reply_text
        user = msg.from_user

    friends = db.get_friends(user.id)
    if not friends:
        return await send("У вас нет друзей для предложения события. Добавьте друзей и попробуйте снова.",
                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))

    chunk, page, pages = paginate(friends, page)
    kb = [[InlineKeyboardButton(f"@{u[1]}" if u[1] else str(u[0]), callback_data=f"event_friend_{u[0]}")] for u in
          chunk]
    kb += nav_row("evfr", page, pages)
    kb.append([InlineKeyboardButton("Отмена", callback_data="events")])
    return await send("Кому предложить событие? Выберите друга:", reply_markup=InlineKeyboardMarkup(kb))


async def event_select_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    friend_id = int(q.data.split("_")[-1])
    if db.get_friend_status(q.from_user.id, friend_id) != "accepted":
        return await q.edit_message_text(
            "Этот пользователь не в списке ваших друзей.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))
    context.user_data["event_friend_id"] = friend_id
    kb = [[InlineKeyboardButton(label, callback_data=f"rem_{minutes}")] for label, minutes in STD_REMS]
    kb.append([InlineKeyboardButton("Отмена", callback_data="events")])
    await q.edit_message_text(text="Выберите напоминание (когда бот должен напомнить вам перед событием):",
                              reply_markup=InlineKeyboardMarkup(kb))
    return EV_SEL_REM


async def event_select_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    minutes = int(q.data.split("_")[-1])
    context.user_data["event_reminder_minutes"] = minutes

    date_str = context.user_data.get("event_date")
    time_str = context.user_data.get("event_time")
    type_str = context.user_data.get("event_type")
    friend_id = context.user_data.get("event_friend_id")

    friend_username = db.get_username(friend_id) or str(friend_id)

    text = (
        f"Подтвердите создание события:\nДата: {date_str}\nВремя: {time_str}\nТип: {type_str}\nКому: @{friend_username}\nНапомнить: {minutes} минут(ы) до события\n\nСоздать?"
    )
    kb = [[InlineKeyboardButton("Создать", callback_data="event_confirm_create")],
          [InlineKeyboardButton("Отмена", callback_data="events")]]
    await q.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(kb))
    return EV_CONFIRM


async def event_confirm_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    creator_id = q.from_user.id
    participant_id = context.user_data.get("event_friend_id")
    day_str = context.user_data.get("event_date")
    time_str = context.user_data.get("event_time")
    type_str = context.user_data.get("event_type")
    reminder_minutes = context.user_data.get("event_reminder_minutes", 0)

    try:
        event_id = db.create_event(creator_id, participant_id, day_str, time_str, type_str, reminder_minutes)
    except Exception:
        logger.exception("Ошибка создания события в БД")
        return await q.edit_message_text("Не удалось создать событие.")

    kb = [[InlineKeyboardButton("Принять", callback_data=f"accept_event_{event_id}")],
          [InlineKeyboardButton("Отклонить", callback_data=f"reject_event_{event_id}")]]
    try:
        await context.bot.send_message(chat_id=participant_id,
                                       text=f"{mention(q.from_user)} предлагает вам событие:\n📅 {day_str} 🕒 {time_str}\n🎯 {type_str}",
                                       reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о новом событии", participant_id)

    await q.edit_message_text("Событие предложено. Ожидайте ответа.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Назад", callback_data="events")]]))

    for k in ("event_date", "event_time", "event_type", "event_friend_id", "event_reminder_minutes"):
        context.user_data.pop(k, None)
    return None


async def event_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Начало процесса удаления события - показывает список событий пользователя"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    events = db.get_active_events_for_user(user_id)

    if not events:
        await query.edit_message_text(
            "У вас нет активных событий для удаления.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return

    # Формируем клавиатуру с событиями
    keyboard = []
    chunk, page, pages = paginate(events, page)
    for event in chunk:
        event_id, creator_id, ev_date, ev_time, etype, status, decline_reason = event
        prefix = "🟢" if status == "accepted" else "🟡" if status == "pending" else "🔴"
        text = f"{prefix} {ev_date} {ev_time} - {etype} (ID: {event_id})"
        if creator_id == user_id:
            text += " [вы создатель]"
        if status == "declined" and decline_reason:
            text += f" — причина: {decline_reason}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"delete_event_{event_id}")])

    keyboard += nav_row("evdel", page, pages)
    keyboard.append([InlineKeyboardButton("Назад", callback_data="events")])

    await query.edit_message_text(
        "Выберите событие для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def event_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления события"""
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split('_')[-1])
    user_id = query.from_user.id

    event = db.get_event(event_id)

    if not event:
        await query.edit_message_text(
            "Событие не найдено или уже удалено.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_delete")]])
        )
        return

    _, creator_id, participant_id, ev_date, ev_time, etype = event[:6]

    # Проверяем права пользователя
    if user_id not in (creator_id, participant_id):
        await query.edit_message_text(
            "Вы не можете удалить это событие.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_delete")]])
        )
        return

    # Формируем сообщение подтверждения
    text = (
        f"Вы уверены, что хотите удалить событие?\n\n"
        f"📅 Дата: {ev_date}\n"
        f"🕒 Время: {ev_time}\n"
        f"🎯 Тип: {etype}\n\n"
        f"ID: {event_id}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{event_id}")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data="event_delete")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def event_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фактическое удаление события"""
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split('_')[-1])
    user_id = query.from_user.id

    event = db.get_event(event_id)

    if not event:
        await query.edit_message_text(
            "Событие не найдено или уже удалено.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return

    _, creator_id, participant_id, ev_date, ev_time, etype = event[:6]

    db.delete_event(event_id)

    # Уведомляем другого участника
    other_user_id = participant_id if user_id == creator_id else creator_id
    try:
        await context.bot.send_message(
            chat_id=other_user_id,
            text=f"Событие было удалено:\n{ev_date} {ev_time} - {etype}\nID: {event_id}"
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s об удалении события", other_user_id)

    await query.edit_message_text(
        "Событие успешно удалено.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Вернуться в меню", callback_data="events")]])
    )


# accept / reject flows
async def event_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_")[-1])
    ev = db.get_event(event_id)
    if not ev:
        return await q.edit_message_text("Событие не найдено или уже удалено.")
    user_id = q.from_user.id
    if user_id != ev[2]:
        return await q.answer("Вы не можете принять это событие.", show_alert=True)
    if ev[6] != "pending":
        return await q.edit_message_text(f"Событие #{event_id} уже обработано ранее.")

    db.mark_event_accepted(event_id)
    ev2 = db.get_event(event_id)
    reminder_minutes = ev2[8] or 0
    if reminder_minutes > 0:
        db.add_reminder_for_user(ev2[1], event_id, ev2[3], ev2[4], reminder_minutes)
        db.add_reminder_for_user(ev2[2], event_id, ev2[3], ev2[4], reminder_minutes)

    try:
        await context.bot.send_message(chat_id=ev2[1],
                                       text=f"Пользователь {mention(q.from_user)} принял ваше приглашение на событие #{event_id} ({ev2[3]} {ev2[4]}).")
        await context.bot.send_message(chat_id=ev2[2],
                                       text=f"Вы подтвердили участие в событии #{event_id} ({ev2[3]} {ev2[4]}).")
    except Exception:
        pass

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Меню событий", callback_data="events")]])
    try:
        await q.edit_message_text(f"Вы приняли событие #{event_id} — спасибо!", reply_markup=kb)
        return None
    except Exception:
        return None


async def event_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_")[-1])
    ev = db.get_event(event_id)
    if not ev:
        return await q.edit_message_text("Событие не найдено или уже удалено.")
    if q.from_user.id != ev[2]:
        return await q.answer("Вы не можете отклонить это событие.", show_alert=True)
    if ev[6] != "pending":
        return await q.edit_message_text(f"Событие #{event_id} уже обработано ранее.")

    context.user_data["awaiting_reject_for_event"] = event_id
    await q.edit_message_text(
        "Вы решили отклонить событие. Укажите причину отказа (или введите '-' для пустой причины):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="events")]]))
    return AWAIT_REJECT


async def event_reject_reason_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_reject_for_event" not in context.user_data:
        return
    text = update.message.text.strip()
    event_id = context.user_data.pop("awaiting_reject_for_event")
    db.mark_event_declined(event_id, text if text != "-" else "")
    ev = db.get_event(event_id)
    if ev:
        try:
            await context.bot.send_message(chat_id=ev[1],
                                           text=f"Пользователь отклонил ваше событие #{event_id}. Причина: {text or '(не указана)'}")
        except Exception:
            pass
    await update.message.reply_text("Отказ отправлен.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Меню событий", callback_data="events")]]))


# ---------------- pending (sent, awaiting friend's answer) ----------------
async def event_pending_sent_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = db.get_pending_sent_events_for_user(query.from_user.id)
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
    if not rows:
        return await query.edit_message_text("Нет событий, ожидающих ответа.", reply_markup=back_kb)

    lines = ["⏳ Предложены вами, ждут ответа:"]
    for event_id, participant_id, ev_date, ev_time, etype in rows:
        label = db.get_user_label(participant_id)
        lines.append(f"#{event_id} — 📅 {ev_date} 🕒 {ev_time} — 🎯 {etype} — кому: {label}")
    await query.edit_message_text("\n".join(lines), reply_markup=back_kb)


# ---------------- edit event (creator only: дата/время, тип) ----------------
async def event_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    events = db.get_editable_events_for_user(user_id)
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
    if not events:
        return await query.edit_message_text("Нет событий, которые можно изменить.", reply_markup=back_kb)

    keyboard = []
    chunk, page, pages = paginate(events, page)
    for event_id, ev_date, ev_time, etype, status in chunk:
        prefix = "🟢" if status == "accepted" else "🟡"
        keyboard.append([InlineKeyboardButton(
            f"{prefix} {ev_date} {ev_time} - {etype} (ID: {event_id})", callback_data=f"edit_event_{event_id}")])
    keyboard += nav_row("evedit", page, pages)
    keyboard.append([InlineKeyboardButton("Назад", callback_data="events")])
    await query.edit_message_text(
        "Выберите событие для изменения (менять может только создатель):",
        reply_markup=InlineKeyboardMarkup(keyboard))


async def event_edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_")[-1])
    ev = db.get_event(event_id)
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
    if not ev or ev[1] != q.from_user.id:
        return await q.edit_message_text("Событие не найдено или вы не можете его изменить.", reply_markup=back_kb)
    if ev[6] not in ("pending", "accepted"):
        return await q.edit_message_text("Это событие уже нельзя изменить.", reply_markup=back_kb)

    context.user_data["editing_event_id"] = event_id
    kb = [
        [InlineKeyboardButton("📅 Дата и время", callback_data="edit_field_datetime")],
        [InlineKeyboardButton("🎯 Тип", callback_data="edit_field_type")],
        [InlineKeyboardButton("Отмена", callback_data="events")],
    ]
    await q.edit_message_text(
        f"Событие #{event_id}: 📅 {ev[3]} 🕒 {ev[4]} — 🎯 {ev[5]}\nЧто изменить?",
        reply_markup=InlineKeyboardMarkup(kb))


async def event_edit_pick_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if "editing_event_id" not in context.user_data:
        return await q.edit_message_text(
            "Сессия изменения истекла, начните заново.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))
    today = db.now_local().date()
    kb = build_calendar_keyboard(today.year, today.month, q.from_user.id, mode="editdate")
    await q.edit_message_text("Выберите новую дату:", reply_markup=kb)


async def event_edit_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ждём время только когда уже редактируем конкретное событие и выбрали
    # для него новую дату — иначе это текст для другого флоу.
    if "editing_event_id" not in context.user_data or "editing_event_date" not in context.user_data:
        return None

    text = update.message.text.strip()
    try:
        input_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Введите в формате ЧЧ:ММ (например, 14:30).")
        return None

    day_str = context.user_data["editing_event_date"]
    selected_datetime = datetime.combine(datetime.strptime(day_str, "%Y-%m-%d").date(), input_time)
    if selected_datetime < db.now_local():
        await update.message.reply_text("❌ Нельзя переносить событие в прошедшее время! Введите будущее время.")
        return None

    event_id = context.user_data.pop("editing_event_id")
    context.user_data.pop("editing_event_date", None)

    kb_out = InlineKeyboardMarkup([[InlineKeyboardButton("Меню событий", callback_data="events")]])
    ev = db.get_event(event_id)
    if not ev or ev[1] != update.effective_user.id or ev[6] not in ("pending", "accepted"):
        return await update.message.reply_text("Событие уже нельзя изменить.", reply_markup=kb_out)

    was_accepted = ev[6] == "accepted"
    db.update_event_datetime(event_id, day_str, text)
    if was_accepted:
        db.reset_event_to_pending(event_id)

    participant_id = ev[2]
    label = mention(update.effective_user)
    try:
        if was_accepted:
            notify_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Принять", callback_data=f"accept_event_{event_id}"),
                                               InlineKeyboardButton("Отклонить", callback_data=f"reject_event_{event_id}")]])
            await context.bot.send_message(
                chat_id=participant_id,
                text=f"{label} перенёс(ла) событие #{event_id} на 📅 {day_str} 🕒 {text}. Требуется подтверждение.",
                reply_markup=notify_kb)
        else:
            await context.bot.send_message(
                chat_id=participant_id,
                text=f"{label} изменил(а) время события #{event_id}: теперь 📅 {day_str} 🕒 {text}.")
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s об изменении события", participant_id)

    reply = f"Событие #{event_id} обновлено: 📅 {day_str} 🕒 {text}."
    if was_accepted:
        reply += " Ждём повторного подтверждения от собеседника."
    await update.message.reply_text(reply, reply_markup=kb_out)


async def event_edit_pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if "editing_event_id" not in context.user_data:
        return await q.edit_message_text(
            "Сессия изменения истекла, начните заново.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))
    kb = [[InlineKeyboardButton(t, callback_data=f"edit_type_{t}")] for t in STD_TYPES if t != "Другое (ввести свой)"]
    kb.append([InlineKeyboardButton("✏️ Свой вариант", callback_data="edit_type_custom")])
    kb.append([InlineKeyboardButton("Отмена", callback_data="events")])
    await q.edit_message_text("Выберите новый тип события:", reply_markup=InlineKeyboardMarkup(kb))


async def event_edit_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if "editing_event_id" not in context.user_data:
        return await q.edit_message_text(
            "Сессия изменения истекла, начните заново.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]]))

    chosen = q.data[len("edit_type_"):]
    if chosen == "custom":
        context.user_data["awaiting_edit_type_custom"] = True
        await q.edit_message_text("Введите новый тип события:",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="events")]]))
        return None
    return await _finish_type_edit(update, context, chosen)


async def event_edit_type_custom_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_edit_type_custom", False):
        return None
    text = update.message.text.strip()
    if not text:
        return await update.message.reply_text("Пустой тип. Введите текст типа события:")
    return await _finish_type_edit(update, context, text, from_message=True)


async def _finish_type_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, new_type: str, from_message: bool = False):
    kb_out = InlineKeyboardMarkup([[InlineKeyboardButton("Меню событий", callback_data="events")]])

    async def reply(text_out):
        if from_message:
            await update.message.reply_text(text_out, reply_markup=kb_out)
        else:
            await update.callback_query.edit_message_text(text_out, reply_markup=kb_out)

    event_id = context.user_data.pop("editing_event_id", None)
    if event_id is None:
        return await reply("Сессия изменения истекла, начните заново.")

    actor = update.effective_user
    ev = db.get_event(event_id)
    if not ev or ev[1] != actor.id or ev[6] not in ("pending", "accepted"):
        return await reply("Событие уже нельзя изменить.")

    was_accepted = ev[6] == "accepted"
    db.update_event_type(event_id, new_type)
    if was_accepted:
        db.reset_event_to_pending(event_id)

    participant_id = ev[2]
    label = mention(actor)
    try:
        if was_accepted:
            notify_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Принять", callback_data=f"accept_event_{event_id}"),
                                               InlineKeyboardButton("Отклонить", callback_data=f"reject_event_{event_id}")]])
            await context.bot.send_message(
                chat_id=participant_id,
                text=f"{label} изменил(а) тип события #{event_id} на «{new_type}». Требуется подтверждение.",
                reply_markup=notify_kb)
        else:
            await context.bot.send_message(
                chat_id=participant_id,
                text=f"{label} изменил(а) тип события #{event_id} на «{new_type}».")
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s об изменении события", participant_id)

    text_out = f"Тип события #{event_id} изменён на «{new_type}»."
    if was_accepted:
        text_out += " Ждём повторного подтверждения от собеседника."
    await reply(text_out)

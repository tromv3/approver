from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update, User
from telegram.ext import ContextTypes

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
    "editing_event_id",
    "editing_event_date",
    "awaiting_edit_type_custom",
)

# Подписи кнопок нижней клавиатуры; handlers/start.py ловит их как обычный текст.
BTN_UPCOMING = "📆 Ближайшие"
BTN_EVENTS = "📅 События"
BTN_FRIENDS = "👥 Друзья"
BTN_HELP = "ℹ️ Помощь"
REPLY_BUTTONS = (BTN_UPCOMING, BTN_EVENTS, BTN_FRIENDS, BTN_HELP)

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_UPCOMING, BTN_EVENTS], [BTN_FRIENDS, BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)

HELP_TEXT = (
    "ℹ️ Как это работает\n\n"
    "👥 Друзья — добавьте друга по @username или пригласите его по личной ссылке.\n"
    "📅 События — выберите дату, время и тип, затем друга. Он получит приглашение и сможет "
    "принять его или отклонить с причиной. Своё событие можно изменить или удалить.\n"
    "📆 Ближайшие — что запланировано на неделю и какие приглашения ждут вашего ответа.\n"
    "⏰ Напоминания приходят перед событием; их можно отложить кнопкой под сообщением.\n\n"
    "Команды:\n"
    "/menu — главное меню\n"
    "/today — события на сегодня\n"
    "/week — события на 7 дней\n"
    "/cancel — отменить текущее действие\n"
    "/help — эта справка"
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


async def ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопки-заглушки (заголовок календаря, номер страницы): просто гасим «часики»."""
    await update.callback_query.answer()


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_flow_state(context)
    kb = [
        [InlineKeyboardButton("📆 Ближайшие", callback_data="upcoming")],
        [InlineKeyboardButton("📅 События", callback_data="events"),
         InlineKeyboardButton("👥 Друзья", callback_data="friends")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    await send_text(update, "Главное меню. Выберите раздел:", InlineKeyboardMarkup(kb))

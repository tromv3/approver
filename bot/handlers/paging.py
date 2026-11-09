from telegram import Update
from telegram.ext import ContextTypes

from . import events, friends

# kind (из callback_data "pg:<kind>:<page>") -> экран-список, умеющий принимать page=
PAGE_HANDLERS = {
    "evdel": events.event_delete_start,
    "evedit": events.event_edit_start,
    "evfr": events.prompt_choose_friend_for_event,
    "frlist": friends.list_friends_start,
    "frrm": friends.remove_friend_start,
}


async def paging_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, kind, page = q.data.split(":")
        page = int(page)
    except ValueError:
        return await q.answer()
    target = PAGE_HANDLERS.get(kind)
    if target is None:
        return await q.answer()
    return await target(update, context, page=page)

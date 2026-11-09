from telegram import InlineKeyboardButton

PER_PAGE = 8


def paginate(items, page: int, per_page: int = PER_PAGE):
    """Возвращает (элементы страницы, номер страницы, всего страниц); номер страницы
    приводится к допустимому диапазону."""
    pages = max(1, -(-len(items) // per_page))
    page = min(max(page, 0), pages - 1)
    return items[page * per_page:(page + 1) * per_page], page, pages


def nav_row(kind: str, page: int, pages: int):
    """Ряд кнопок «◀ 2/5 ▶» для inline-клавиатуры (пустой список, если страница одна).
    callback_data вида pg:<kind>:<номер> обрабатывает handlers/paging.py."""
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"pg:{kind}:{page - 1}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="ignore"))
    if page < pages - 1:
        row.append(InlineKeyboardButton("➡️", callback_data=f"pg:{kind}:{page + 1}"))
    return [row]

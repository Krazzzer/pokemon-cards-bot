from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Меню")]],
        resize_keyboard=True,
        is_persistent=True,
    )

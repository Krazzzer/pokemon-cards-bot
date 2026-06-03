from aiogram.types import CallbackQuery, Message, User

from bot.config import get_settings


DENIED_TEXT = (
    "У вас нет доступа к командам продавца.\n"
    "Обратитесь к администратору, чтобы вас добавили в белый список."
)


def is_seller_allowed(user: User | None) -> bool:
    if user is None:
        return False

    settings = get_settings()
    allowed_ids = set(settings.seller_ids) | set(settings.admin_ids)
    if not allowed_ids:
        return True
    return user.id in allowed_ids


async def ensure_seller_message(message: Message) -> bool:
    if is_seller_allowed(message.from_user):
        return True
    await message.answer(DENIED_TEXT)
    return False


async def ensure_seller_callback(callback: CallbackQuery) -> bool:
    if is_seller_allowed(callback.from_user):
        return True
    await callback.answer(DENIED_TEXT, show_alert=True)
    return False

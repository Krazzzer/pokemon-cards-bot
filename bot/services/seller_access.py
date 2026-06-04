from aiogram.types import CallbackQuery, Message, User

from bot.config import get_settings
from bot.db.session import get_session_factory
from bot.services.access import is_user_allowed as is_menu_user_allowed


DENIED_TEXT = (
    "У вас нет доступа к командам продавца.\n"
    "Обратитесь к администратору, чтобы вас добавили в белый список."
)


async def is_seller_allowed(user: User | None) -> bool:
    if user is None:
        return False

    settings = get_settings()
    allowed_ids = set(settings.seller_ids) | set(settings.admin_ids)
    if not allowed_ids:
        return True
    if user.id in allowed_ids:
        return True

    async with get_session_factory()() as session:
        return await is_menu_user_allowed(session, user.id)


async def ensure_seller_message(message: Message) -> bool:
    if await is_seller_allowed(message.from_user):
        return True
    await message.answer(DENIED_TEXT)
    return False


async def ensure_seller_callback(callback: CallbackQuery) -> bool:
    if await is_seller_allowed(callback.from_user):
        return True
    await callback.answer(DENIED_TEXT, show_alert=True)
    return False

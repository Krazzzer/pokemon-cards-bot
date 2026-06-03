from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from bot.config import get_settings


DENIED_TEXT = "У вас нет доступа к личному меню этого бота."


def is_user_allowed(user: User | None) -> bool:
    if user is None:
        return False

    settings = get_settings()
    allowed_ids = (
        set(settings.allowed_user_ids)
        | set(settings.seller_ids)
        | set(settings.admin_ids)
    )
    if not allowed_ids:
        return True
    return user.id in allowed_ids


class UserAccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if isinstance(event, Message) and event.chat.type != "private":
            return await handler(event, data)

        if (
            isinstance(event, CallbackQuery)
            and event.message is not None
            and event.message.chat.type != "private"
        ):
            return await handler(event, data)

        if is_user_allowed(user):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(DENIED_TEXT, show_alert=True)
        elif isinstance(event, Message) and event.chat.type == "private":
            await event.answer(DENIED_TEXT)
        return None

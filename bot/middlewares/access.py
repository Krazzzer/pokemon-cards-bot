from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from bot.db.session import get_session_factory
from bot.services.access import is_user_allowed as is_user_allowed_in_db


DENIED_TEXT = "У вас нет доступа к личному меню этого бота."


async def is_user_allowed(user: User | None) -> bool:
    if user is None:
        return False

    async with get_session_factory()() as session:
        return await is_user_allowed_in_db(session, user.id)


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

        if await is_user_allowed(user):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(DENIED_TEXT, show_alert=True)
        elif isinstance(event, Message) and event.chat.type == "private":
            await event.answer(DENIED_TEXT)
        return None

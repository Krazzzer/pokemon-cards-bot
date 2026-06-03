"""Ignore harmless Telegram edit errors."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


def is_message_not_modified(exc: BaseException) -> bool:
    if not isinstance(exc, TelegramBadRequest):
        return False
    return "message is not modified" in str(exc).lower()


def is_callback_query_expired(exc: BaseException) -> bool:
    if not isinstance(exc, TelegramBadRequest):
        return False
    text = str(exc).lower()
    return (
        "query is too old" in text
        or "response timeout expired" in text
        or "query id is invalid" in text
    )


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool | None = None,
) -> bool:
    try:
        await callback.answer(text, show_alert=show_alert)
        return True
    except TelegramBadRequest as exc:
        if is_callback_query_expired(exc):
            return False
        raise


async def safe_edit_message_reply_markup(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as exc:
        if is_message_not_modified(exc):
            return True
        raise


async def safe_edit_message_text(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as exc:
        if is_message_not_modified(exc):
            return True
        raise


async def safe_edit_message_caption(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    caption: str,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as exc:
        if is_message_not_modified(exc):
            return True
        raise

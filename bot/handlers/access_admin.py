import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db.session import get_session_factory
from bot.services.access import (
    add_allowed_user,
    is_admin,
    list_allowed_users,
    remove_allowed_user,
)

router = Router(name="access_admin")


def _parse_user_id(message: Message) -> int | None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1].strip())
    except ValueError:
        return None


def _format_allowed_user(row) -> str:
    user_id = row.allowed.telegram_id
    if row.user and row.user.username:
        name = f"@{html.escape(row.user.username)}"
    elif row.user and row.user.full_name:
        name = html.escape(row.user.full_name)
    else:
        name = "ник неизвестен"

    added_at = (
        row.allowed.created_at.strftime("%d.%m.%Y %H:%M")
        if row.allowed.created_at
        else "неизвестно"
    )
    return f"• <code>{user_id}</code> — {name} — добавлен {added_at}"


async def _ensure_admin(message: Message) -> bool:
    if message.from_user and is_admin(message.from_user.id):
        return True
    return False


@router.message(Command("allow"), F.chat.type == "private")
async def cmd_allow(message: Message) -> None:
    if not await _ensure_admin(message):
        return

    user_id = _parse_user_id(message)
    if user_id is None:
        await message.answer("Использование: /allow 123456789")
        return

    async with get_session_factory()() as session:
        await add_allowed_user(
            session,
            user_id,
            added_by=message.from_user.id if message.from_user else None,
        )

    await message.answer(
        f"Пользователь <code>{user_id}</code> добавлен в whitelist.",
        parse_mode="HTML",
    )


@router.message(Command("deny"), F.chat.type == "private")
async def cmd_deny(message: Message) -> None:
    if not await _ensure_admin(message):
        return

    user_id = _parse_user_id(message)
    if user_id is None:
        await message.answer("Использование: /deny 123456789")
        return

    async with get_session_factory()() as session:
        removed = await remove_allowed_user(session, user_id)

    if removed:
        await message.answer(
            f"Пользователь <code>{user_id}</code> удалён из whitelist.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"Пользователя <code>{user_id}</code> нет в whitelist.",
            parse_mode="HTML",
        )


@router.message(Command("allowed", "list_allowed"), F.chat.type == "private")
async def cmd_allowed(message: Message) -> None:
    if not await _ensure_admin(message):
        return

    async with get_session_factory()() as session:
        users = await list_allowed_users(session)

    if not users:
        await message.answer("Динамический whitelist пуст.")
        return

    lines = ["<b>Whitelist:</b>"]
    lines.extend(_format_allowed_user(user) for user in users)
    await message.answer("\n".join(lines), parse_mode="HTML")

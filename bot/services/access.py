from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import AllowedUser, User


@dataclass(frozen=True)
class AllowedUserInfo:
    allowed: AllowedUser
    user: User | None


def is_env_allowed(user_id: int) -> bool:
    settings = get_settings()
    return user_id in (
        set(settings.allowed_user_ids)
        | set(settings.seller_ids)
        | set(settings.admin_ids)
    )


def has_static_allowlist() -> bool:
    settings = get_settings()
    return bool(settings.allowed_user_ids or settings.seller_ids or settings.admin_ids)


def is_admin(user_id: int) -> bool:
    return user_id in set(get_settings().admin_ids)


async def has_dynamic_allowlist(session: AsyncSession) -> bool:
    result = await session.execute(select(AllowedUser.telegram_id).limit(1))
    return result.scalar_one_or_none() is not None


async def is_user_allowed(session: AsyncSession, user_id: int) -> bool:
    if is_env_allowed(user_id):
        return True
    if not has_static_allowlist() and not await has_dynamic_allowlist(session):
        return True
    return await session.get(AllowedUser, user_id) is not None


async def add_allowed_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    added_by: int | None = None,
) -> AllowedUser:
    allowed = await session.get(AllowedUser, telegram_id)
    if allowed is None:
        allowed = AllowedUser(telegram_id=telegram_id, added_by=added_by)
        session.add(allowed)
    else:
        allowed.added_by = added_by
    await session.commit()
    return allowed


async def remove_allowed_user(session: AsyncSession, telegram_id: int) -> bool:
    allowed = await session.get(AllowedUser, telegram_id)
    if allowed is None:
        return False
    await session.delete(allowed)
    await session.commit()
    return True


async def list_allowed_users(session: AsyncSession) -> list[AllowedUserInfo]:
    result = await session.execute(
        select(AllowedUser, User)
        .select_from(AllowedUser)
        .outerjoin(User, User.telegram_id == AllowedUser.telegram_id)
        .order_by(AllowedUser.created_at)
    )
    return [
        AllowedUserInfo(allowed=allowed, user=user)
        for allowed, user in result.all()
    ]

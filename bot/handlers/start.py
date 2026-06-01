from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.config import get_settings
from bot.db.session import get_session_factory
from bot.keyboards.inline import start_keyboard
from bot.services.listings import upsert_user

router = Router(name="start")


WELCOME_TEXT = (
    "Привет! Я бот для продажи Pokémon-карт в вашей группе.\n\n"
    "<b>Продавцам:</b>\n"
    "• /sell — объявление с фиксированной ценой\n"
    "• /auction — аукцион (старт, шаг ставки, дата окончания)\n"
    "• /my — ваши активные лоты\n\n"
    "<b>Покупателям:</b>\n"
    "• «Купить» — резерв фиксированного лота\n"
    "• «Сделать ставку» — участие в аукционе (далее в ЛС бота)\n\n"
    "/cancel — отменить создание объявления или аукциона."
)


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    async with get_session_factory()() as session:
        await upsert_user(
            session,
            user.id,
            user.username,
            user.full_name,
        )

    await message.answer(WELCOME_TEXT, parse_mode="HTML", reply_markup=start_keyboard())


@router.message(Command("groupid"))
async def cmd_group_id(message: Message) -> None:
    settings = get_settings()
    if message.from_user and message.from_user.id not in settings.admin_ids:
        if settings.admin_ids:
            return

    chat = message.chat
    await message.reply(
        f"ID этого чата: <code>{chat.id}</code>\n"
        "Укажите его в GROUP_CHAT_ID в файле .env",
        parse_mode="HTML",
    )

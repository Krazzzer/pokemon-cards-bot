from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.config import get_settings
from bot.db.session import get_session_factory
from bot.keyboards.inline import bid_prompt_keyboard, listing_items_buy_keyboard, start_keyboard
from bot.keyboards.reply import main_menu_reply_keyboard
from bot.services.listing_utils import is_auction
from bot.services.listings import get_listing, has_listing_items, min_bid_amount, upsert_user
from bot.services.posts import format_price, render_caption

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


async def _upsert_message_user(message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False

    async with get_session_factory()() as session:
        await upsert_user(
            session,
            user.id,
            user.username,
            user.full_name,
        )
    return True


@router.message(CommandStart(deep_link=True), F.chat.type == "private")
async def cmd_start_deep_link(message: Message, command: CommandObject) -> None:
    if not await _upsert_message_user(message):
        return

    args = command.args or ""
    if args.startswith("buy_"):
        await _show_buy_menu(message, args.removeprefix("buy_"))
        return
    if args.startswith("bid_"):
        await _show_bid_menu(message, args.removeprefix("bid_"))
        return

    await _show_start_menu(message)


async def _show_buy_menu(message: Message, listing_id: str) -> None:
    async with get_session_factory()() as session:
        listing = await get_listing(session, listing_id)

    if listing is None or not has_listing_items(listing):
        await message.answer("Объявление недоступно или уже снято.")
        return

    await message.answer(
        "Выберите товар для покупки:\n\n"
        f"{render_caption(listing)}",
        parse_mode="HTML",
        reply_markup=listing_items_buy_keyboard(listing, include_back=False),
    )


async def _show_bid_menu(message: Message, listing_id: str) -> None:
    async with get_session_factory()() as session:
        listing = await get_listing(session, listing_id)

    if listing is None or not is_auction(listing):
        await message.answer("Аукцион недоступен или уже снят.")
        return

    minimum = min_bid_amount(listing)
    text = (
        f"<b>{listing.title}</b>\n"
        f"Текущая ставка: {format_price(listing.price, listing.currency)}\n"
        f"Минимум для вашей ставки: {format_price(minimum, listing.currency)}\n\n"
        "Выберите сумму или введите свою:"
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=bid_prompt_keyboard(listing),
    )


async def _show_start_menu(message: Message) -> None:
    await message.answer(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_reply_keyboard(),
    )
    await message.answer(
        "Выберите действие:",
        reply_markup=start_keyboard(),
    )


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message) -> None:
    if not await _upsert_message_user(message):
        return

    await _show_start_menu(message)


@router.message(F.text == "Меню", F.chat.type == "private")
async def menu_button(message: Message) -> None:
    if not await _upsert_message_user(message):
        return

    await _show_start_menu(message)


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

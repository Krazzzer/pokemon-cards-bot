from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.services.listing_utils import is_auction
from bot.db.session import get_session_factory
from bot.handlers.sell_fsm import parse_price
from bot.keyboards.inline import bid_prompt_keyboard
from bot.services.listings import (
    get_listing,
    min_bid_amount,
    place_bid,
    upsert_user,
)
from bot.services.posts import format_price, update_listing_post

router = Router(name="auction_bids")


class BidStates(StatesGroup):
    amount = State()


_BID_FAIL_MESSAGES = {
    "not_found": "Аукцион не найден.",
    "not_auction": "Это не аукцион.",
    "not_active": "Аукцион уже завершён.",
    "ended": "Время аукциона истекло.",
    "own_listing": "Нельзя ставить на свой лот.",
    "too_low": "Ставка слишком низкая.",
    "concurrent_bid": "Кто-то сделал ставку раньше. Попробуйте снова.",
}


async def _prompt_bid(callback: CallbackQuery, listing_id: str) -> None:
    if callback.from_user is None:
        return

    async with get_session_factory()() as session:
        listing = await get_listing(session, listing_id)

    if listing is None or not is_auction(listing):
        await callback.answer("Аукцион не найден.", show_alert=True)
        return

    minimum = min_bid_amount(listing)
    text = (
        f"<b>{listing.title}</b>\n"
        f"Текущая ставка: {format_price(listing.price, listing.currency)}\n"
        f"Минимум для вашей ставки: {format_price(minimum, listing.currency)}\n\n"
        "Выберите сумму или введите свою:"
    )
    try:
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            parse_mode="HTML",
            reply_markup=bid_prompt_keyboard(listing),
        )
        await callback.answer("Инструкция отправлена в личные сообщения бота.")
    except Exception:
        await callback.answer(
            "Напишите боту /start в личке, затем снова нажмите «Сделать ставку».",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("bid:"))
async def on_bid_start(callback: CallbackQuery, state: FSMContext) -> None:
    listing_id = (callback.data or "").removeprefix("bid:")
    await state.clear()
    await _prompt_bid(callback, listing_id)


@router.callback_query(F.data.startswith("bidcustom:"))
async def on_bid_custom(callback: CallbackQuery, state: FSMContext) -> None:
    listing_id = (callback.data or "").removeprefix("bidcustom:")
    await callback.answer()
    await state.set_state(BidStates.amount)
    await state.update_data(listing_id=listing_id)
    if callback.message:
        await callback.message.answer(
            "Введите сумму вашей ставки числом:",
        )


@router.callback_query(F.data.startswith("bidamt:"))
async def on_bid_quick(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        return

    parts = (callback.data or "").removeprefix("bidamt:").split(":")
    if len(parts) != 2:
        await callback.answer("Ошибка.", show_alert=True)
        return

    listing_id, amount_str = parts[0], parts[1]
    try:
        amount = float(amount_str)
    except ValueError:
        await callback.answer("Ошибка.", show_alert=True)
        return

    await _process_bid(callback, listing_id, amount, state)


@router.message(BidStates.amount, F.chat.type == "private")
async def on_bid_amount_message(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    listing_id = data.get("listing_id")
    if not listing_id:
        await state.clear()
        return

    amount = parse_price(message.text or "")
    if amount is None:
        await message.answer("Введите положительное число:")
        return

    await _apply_bid(
        message.bot,
        listing_id=listing_id,
        user=message.from_user,
        amount=amount,
        state=state,
        reply_to=message,
    )


async def _process_bid(
    callback: CallbackQuery,
    listing_id: str,
    amount: float,
    state: FSMContext,
) -> None:
    if callback.from_user is None:
        return
    await _apply_bid(
        callback.bot,
        listing_id=listing_id,
        user=callback.from_user,
        amount=amount,
        state=state,
        callback=callback,
    )


async def _apply_bid(
    bot,
    *,
    listing_id: str,
    user,
    amount: float,
    state: FSMContext,
    callback: CallbackQuery | None = None,
    reply_to: Message | None = None,
) -> None:
    async with get_session_factory()() as session:
        await upsert_user(session, user.id, user.username, user.full_name)
        result = await place_bid(session, listing_id, user.id, amount)

    if not result.ok or result.listing is None:
        reason = _BID_FAIL_MESSAGES.get(result.reason or "", "Ставка не принята.")
        if result.reason == "too_low" and result.listing:
            minimum = min_bid_amount(result.listing)
            reason = (
                f"Ставка слишком низкая. Минимум: "
                f"{format_price(minimum, result.listing.currency)}"
            )
        if callback:
            await callback.answer(reason, show_alert=True)
        elif reply_to:
            await reply_to.answer(reason)
        return

    listing = result.listing
    await update_listing_post(
        bot,
        listing,
        leader_username=user.username,
    )

    if result.previous_bidder_id and result.previous_bidder_id != user.id:
        try:
            await bot.send_message(
                chat_id=result.previous_bidder_id,
                text=(
                    f"Вас перебили в аукционе <b>{listing.title}</b>.\n"
                    f"Новая ставка: {format_price(listing.price, listing.currency)}"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    msg = (
        f"Ставка принята: {format_price(amount, listing.currency)}\n"
        "Текущий лидер: вы"
    )
    if callback:
        await callback.answer("Ставка принята!")
        if callback.message:
            await callback.message.answer(msg)
    elif reply_to:
        await reply_to.answer(msg)

    await state.clear()

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.db.models import ListingStatus
from bot.db.session import get_session_factory
from bot.keyboards.inline import seller_listing_keyboard
from bot.services.listing_utils import (
    is_active_listing,
    is_auction,
    listing_status_value,
)
from bot.services.auction_lifecycle import notify_auction_finished
from bot.services.listings import (
    cancel_auction_if_no_bids,
    cancel_listing,
    end_auction_by_seller,
    get_seller_listings,
    mark_sold,
    unreserve_listing,
)
from bot.services.posts import render_caption, update_listing_post

router = Router(name="seller_actions")


def _status_label(listing) -> str:
    if is_auction(listing) and is_active_listing(listing):
        return "🔨 аукцион"
    labels = {
        "active": "🟢 в продаже",
        "reserved": "🟡 зарезервировано",
        "sold": "🔴 продано",
        "cancelled": "⚫ снято",
    }
    return labels.get(listing_status_value(listing), listing_status_value(listing))


async def _send_listing_card(target: Message, listing) -> None:
    text = (
        f"<b>{listing.title}</b> — {_status_label(listing)}\n"
        f"{render_caption(listing)}"
    )
    kb = seller_listing_keyboard(listing)
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("my"), F.chat.type == "private")
async def cmd_my(message: Message) -> None:
    if message.from_user is None:
        return

    async with get_session_factory()() as session:
        listings = await get_seller_listings(session, message.from_user.id)

    if not listings:
        await message.answer(
            "У вас нет активных объявлений. Создайте: /sell или /auction"
        )
        return

    sales = [item for item in listings if not is_auction(item)]
    auctions = [item for item in listings if is_auction(item)]

    await message.answer(
        f"Всего активных: {len(listings)} "
        f"(продажи: {len(sales)}, аукционы: {len(auctions)})"
    )

    if sales:
        await message.answer(f"<b>Продажи</b> ({len(sales)}):", parse_mode="HTML")
        for listing in sales:
            await _send_listing_card(message, listing)

    if auctions:
        await message.answer(f"<b>Аукционы</b> ({len(auctions)}):", parse_mode="HTML")
        for listing in auctions:
            await _send_listing_card(message, listing)


@router.callback_query(F.data.startswith("sold:"))
async def on_sold(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("sold:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await mark_sold(session, listing_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось отметить как проданное.", show_alert=True)
        return

    await callback.answer("Отмечено как продано!")
    await update_listing_post(callback.bot, listing)

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=None,
        )


@router.callback_query(F.data.startswith("unreserve:"))
async def on_unreserve(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("unreserve:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await unreserve_listing(session, listing_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось снять резерв.", show_alert=True)
        return

    await callback.answer("Резерв снят, снова в продаже.")
    await update_listing_post(callback.bot, listing)

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=seller_listing_keyboard(listing),
        )


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_listing(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("cancel:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await cancel_listing(session, listing_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось отменить.", show_alert=True)
        return

    await callback.answer("Объявление снято.")
    await update_listing_post(callback.bot, listing)

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=None,
        )


@router.callback_query(F.data.startswith("endauc:"))
async def on_end_auction(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("endauc:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await end_auction_by_seller(session, listing_id, seller_id)

    if listing is None:
        await callback.answer(
            "Не удалось завершить (не ваш аукцион или уже закрыт).",
            show_alert=True,
        )
        return

    await update_listing_post(callback.bot, listing)
    await notify_auction_finished(callback.bot, listing)

    if listing.high_bidder_id:
        await callback.answer("Аукцион завершён. Победитель уведомлён.")
    else:
        await callback.answer("Аукцион завершён без ставок.")

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=None,
        )


@router.callback_query(F.data.startswith("cancelauc:"))
async def on_cancel_auction(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("cancelauc:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await cancel_auction_if_no_bids(session, listing_id, seller_id)

    if listing is None:
        await callback.answer(
            "Нельзя отменить (уже есть ставки или аукцион не активен).",
            show_alert=True,
        )
        return

    await callback.answer("Аукцион отменён.")
    await update_listing_post(callback.bot, listing)

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=None,
        )

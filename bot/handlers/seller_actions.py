from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.db.models import ListingItem, ListingStatus, User
from bot.db.session import get_session_factory
from bot.keyboards.inline import seller_listing_item_keyboard, seller_listing_keyboard
from bot.services.listing_utils import (
    is_active_listing,
    is_auction,
    listing_status_value,
)
from bot.services.auction_lifecycle import notify_auction_finished
from bot.services.listings import (
    cancel_auction_if_no_bids,
    cancel_listing,
    cancel_listing_item,
    end_auction_by_seller,
    get_seller_listings,
    has_listing_items,
    mark_listing_item_sold,
    mark_sold,
    revert_last_bid,
    unreserve_listing_item,
    unreserve_listing,
)
from bot.services.posts import format_price, render_caption, update_listing_post
from bot.services.seller_access import ensure_seller_message

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


def _item_status_label(item: ListingItem) -> str:
    status = (
        item.status.value
        if isinstance(item.status, ListingStatus)
        else str(item.status).lower()
    )
    labels = {
        "active": "🟢 в продаже",
        "reserved": "🟡 зарезервировано",
        "sold": "🔴 продано",
        "cancelled": "⚫ снято",
    }
    return labels.get(status, status)


def _listing_card_text(listing, *, leader_username: str | None = None) -> str:
    caption = render_caption(listing, leader_username=leader_username)
    return f"<b>{listing.title}</b> — {_status_label(listing)}\n{caption}"


async def _send_listing_card(target: Message, listing) -> None:
    if has_listing_items(listing):
        await target.answer(render_caption(listing), parse_mode="HTML")
        for item in listing.items:
            kb = seller_listing_item_keyboard(item)
            if kb is None:
                continue
            await target.answer(
                f"<b>{item.position}. {item.title}</b> — {_item_status_label(item)}",
                parse_mode="HTML",
                reply_markup=kb,
            )
        return

    kb = seller_listing_keyboard(listing)
    await target.answer(_listing_card_text(listing), parse_mode="HTML", reply_markup=kb)


def _find_item(listing, item_id: str) -> ListingItem | None:
    for item in getattr(listing, "items", []):
        if item.id == item_id:
            return item
    return None


@router.message(Command("my"), F.chat.type == "private")
async def cmd_my(message: Message) -> None:
    if message.from_user is None:
        return
    if not await ensure_seller_message(message):
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


@router.callback_query(F.data.startswith("solditem:"))
async def on_sold_item(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    item_id = (callback.data or "").removeprefix("solditem:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await mark_listing_item_sold(session, item_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось отметить товар как проданный.", show_alert=True)
        return

    await callback.answer("Товар отмечен как проданный!")
    await update_listing_post(callback.bot, listing)

    item = _find_item(listing, item_id)
    if callback.message and item:
        await callback.message.edit_text(
            f"<b>{item.position}. {item.title}</b> — {_item_status_label(item)}",
            parse_mode="HTML",
            reply_markup=seller_listing_item_keyboard(item),
        )


@router.callback_query(F.data.startswith("unresitem:"))
async def on_unreserve_item(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    item_id = (callback.data or "").removeprefix("unresitem:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await unreserve_listing_item(session, item_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось снять резерв с товара.", show_alert=True)
        return

    await callback.answer("Резерв снят, товар снова в продаже.")
    await update_listing_post(callback.bot, listing)

    item = _find_item(listing, item_id)
    if callback.message and item:
        await callback.message.edit_text(
            f"<b>{item.position}. {item.title}</b> — {_item_status_label(item)}",
            parse_mode="HTML",
            reply_markup=seller_listing_item_keyboard(item),
        )


@router.callback_query(F.data.startswith("cancelitem:"))
async def on_cancel_listing_item(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    item_id = (callback.data or "").removeprefix("cancelitem:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await cancel_listing_item(session, item_id, seller_id)

    if listing is None:
        await callback.answer("Не удалось отменить товар.", show_alert=True)
        return

    await callback.answer("Товар снят с продажи.")
    await update_listing_post(callback.bot, listing)

    item = _find_item(listing, item_id)
    if callback.message and item:
        await callback.message.edit_text(
            f"<b>{item.position}. {item.title}</b> — {_item_status_label(item)}",
            parse_mode="HTML",
            reply_markup=seller_listing_item_keyboard(item),
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


_UNDO_BID_FAIL_MESSAGES = {
    "not_found": "Аукцион не найден.",
    "not_seller": "Это не ваш аукцион.",
    "not_auction": "Это не аукцион.",
    "not_active": "Аукцион уже завершён.",
    "ended": "Время аукциона истекло.",
    "no_bids": "Ставок для отмены нет.",
    "stale": "Состояние аукциона изменилось. Обновите /my.",
    "concurrent_change": "Появилась новая ставка. Обновите /my.",
}


@router.callback_query(F.data.startswith("undobid:"))
async def on_undo_bid(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("undobid:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        result = await revert_last_bid(session, listing_id, seller_id)
        leader = (
            await session.get(User, result.listing.high_bidder_id)
            if result.ok and result.listing and result.listing.high_bidder_id
            else None
        )

    if not result.ok or result.listing is None:
        reason = _UNDO_BID_FAIL_MESSAGES.get(
            result.reason or "",
            "Не удалось отменить ставку.",
        )
        await callback.answer(reason, show_alert=True)
        return

    listing = result.listing
    leader_username = leader.username if leader else None
    await update_listing_post(
        callback.bot,
        listing,
        leader_username=leader_username,
    )

    if result.removed_bidder_id and result.removed_amount is not None:
        try:
            await callback.bot.send_message(
                result.removed_bidder_id,
                text=(
                    f"Продавец отменил вашу ставку в аукционе "
                    f"<b>{listing.title}</b> "
                    f"({format_price(result.removed_amount, listing.currency)})."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer("Последняя ставка отменена.")

    if callback.message:
        await callback.message.edit_text(
            _listing_card_text(listing, leader_username=leader_username),
            parse_mode="HTML",
            reply_markup=seller_listing_keyboard(listing),
        )


@router.callback_query(F.data.startswith("endauc:"))
async def on_end_auction(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("endauc:")
    seller_id = callback.from_user.id

    async with get_session_factory()() as session:
        listing = await end_auction_by_seller(session, listing_id, seller_id)
        winner = (
            await session.get(User, listing.high_bidder_id)
            if listing and listing.high_bidder_id
            else None
        )

    if listing is None:
        await callback.answer(
            "Не удалось завершить (не ваш аукцион или уже закрыт).",
            show_alert=True,
        )
        return

    winner_username = winner.username if winner else None
    await update_listing_post(callback.bot, listing, leader_username=winner_username)
    await notify_auction_finished(
        callback.bot,
        listing,
        winner_username=winner_username,
    )

    if listing.high_bidder_id:
        await callback.answer("Аукцион завершён. Победитель уведомлён.")
    else:
        await callback.answer("Аукцион завершён без ставок.")

    if callback.message:
        await callback.message.edit_text(
            render_caption(listing, leader_username=winner_username),
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

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.db.session import get_session_factory
from bot.keyboards.inline import (
    listing_group_keyboard,
    listing_items_buy_keyboard,
    seller_listing_item_keyboard,
)
from bot.services.listing_utils import is_auction
from bot.services.listings import (
    get_listing,
    has_listing_items,
    reserve_listing,
    reserve_listing_item,
    upsert_user,
)
from bot.services.posts import render_caption, update_listing_post
from bot.services.telegram_safe import safe_callback_answer

router = Router(name="callbacks")


async def _send_private_buy_menu(callback: CallbackQuery, listing) -> None:
    if callback.from_user is None:
        return

    try:
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=(
                "Выберите товар для покупки:\n\n"
                f"{render_caption(listing)}"
            ),
            parse_mode="HTML",
            reply_markup=listing_items_buy_keyboard(listing, include_back=False),
        )
    except Exception:
        await safe_callback_answer(
            callback,
            "Не могу отправить меню в ЛС. Откройте чат с ботом и нажмите /start, затем попробуйте снова.",
            show_alert=True,
        )
        return

    await safe_callback_answer(
        callback,
        "Меню покупки отправлено в личные сообщения с ботом.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("noop:"))
async def on_noop(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Этот товар сейчас недоступен.", show_alert=True)


@router.callback_query(F.data.startswith("buylist:"))
async def on_buy_list(callback: CallbackQuery) -> None:
    listing_id = (callback.data or "").removeprefix("buylist:")
    async with get_session_factory()() as session:
        listing = await get_listing(session, listing_id)

    if listing is None or not has_listing_items(listing):
        await safe_callback_answer(callback, "Объявление недоступно.", show_alert=True)
        return

    await _send_private_buy_menu(callback, listing)


@router.callback_query(F.data.startswith("backbuy:"))
async def on_buy_back(callback: CallbackQuery) -> None:
    listing_id = (callback.data or "").removeprefix("backbuy:")
    async with get_session_factory()() as session:
        listing = await get_listing(session, listing_id)

    if listing is None:
        await safe_callback_answer(callback, "Объявление недоступно.", show_alert=True)
        return

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=listing_group_keyboard(listing))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("buyitem:"))
async def on_buy_item(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    item_id = (callback.data or "").removeprefix("buyitem:")
    buyer = callback.from_user

    async with get_session_factory()() as session:
        await upsert_user(
            session,
            buyer.id,
            buyer.username,
            buyer.full_name,
        )
        result = await reserve_listing_item(session, item_id, buyer.id)

    if result.own_listing:
        await safe_callback_answer(callback, "Это ваше объявление.", show_alert=True)
        return

    if result.same_buyer and result.item:
        await safe_callback_answer(callback, "Вы уже зарезервировали этот товар.")
        return

    if result.already_reserved or not result.ok or result.listing is None or result.item is None:
        await safe_callback_answer(
            callback,
            "Товар уже зарезервирован или недоступен.",
            show_alert=True,
        )
        return

    listing = result.listing
    item = result.item
    await safe_callback_answer(
        callback,
        "Товар зарезервирован! Продавец получит уведомление.",
    )
    await update_listing_post(callback.bot, listing)
    if callback.message and callback.message.chat.type == "private":
        await callback.message.edit_text(
            "Выберите товар для покупки:\n\n"
            f"{render_caption(listing)}",
            parse_mode="HTML",
            reply_markup=listing_items_buy_keyboard(listing, include_back=False),
        )

    seller_text = (
        f"🟡 Товар <b>{item.position}. {item.title}</b> зарезервирован!\n"
        f"Покупатель: "
    )
    if buyer.username:
        seller_text += f"@{buyer.username} (id: {buyer.id})"
    else:
        seller_text += (
            f'<a href="tg://user?id={buyer.id}">'
            f'{buyer.full_name or "покупатель"}</a>'
        )
    seller_text += "\n\nСвяжитесь в ЛС для оплаты и отправки."

    try:
        await callback.bot.send_message(
            chat_id=listing.seller_id,
            text=seller_text,
            parse_mode="HTML",
            reply_markup=seller_listing_item_keyboard(item),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("buy:"))
async def on_buy(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    listing_id = (callback.data or "").removeprefix("buy:")
    buyer = callback.from_user

    async with get_session_factory()() as session:
        await upsert_user(
            session,
            buyer.id,
            buyer.username,
            buyer.full_name,
        )
        listing_check = await get_listing(session, listing_id)
        if listing_check and is_auction(listing_check):
            await safe_callback_answer(
                callback,
                "Это аукцион — нажмите «Сделать ставку».",
                show_alert=True,
            )
            return
        if listing_check and has_listing_items(listing_check):
            await _send_private_buy_menu(callback, listing_check)
            return

        result = await reserve_listing(session, listing_id, buyer.id)

    if result.own_listing:
        await safe_callback_answer(callback, "Это ваше объявление.", show_alert=True)
        return

    if result.same_buyer and result.listing:
        await safe_callback_answer(callback, "Вы уже зарезервировали этот лот.")
        return

    if result.already_reserved or not result.ok or result.listing is None:
        await safe_callback_answer(
            callback,
            "Уже зарезервировано или недоступно.",
            show_alert=True,
        )
        return

    listing = result.listing
    await safe_callback_answer(
        callback,
        "Лот зарезервирован! Продавец получит уведомление.",
    )

    await update_listing_post(
        callback.bot,
        listing,
        buyer_username=buyer.username,
    )

    seller_text = (
        f"🟡 Ваш лот <b>{listing.title}</b> зарезервирован!\n"
        f"Покупатель: "
    )
    if buyer.username:
        seller_text += f"@{buyer.username} (id: {buyer.id})"
    else:
        seller_text += f'<a href="tg://user?id={buyer.id}">{buyer.full_name or "покупатель"}</a>'

    seller_text += "\n\nСвяжитесь в ЛС для оплаты и отправки."

    from bot.keyboards.inline import seller_listing_keyboard

    try:
        await callback.bot.send_message(
            chat_id=listing.seller_id,
            text=seller_text,
            parse_mode="HTML",
            reply_markup=seller_listing_keyboard(listing),
        )
    except Exception:
        pass

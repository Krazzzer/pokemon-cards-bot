from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.db.session import get_session_factory
from bot.services.listing_utils import is_auction
from bot.services.listings import get_listing, reserve_listing, upsert_user
from bot.services.posts import update_listing_post

router = Router(name="callbacks")


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
            await callback.answer(
                "Это аукцион — нажмите «Сделать ставку».",
                show_alert=True,
            )
            return

        result = await reserve_listing(session, listing_id, buyer.id)

    if result.own_listing:
        await callback.answer("Это ваше объявление.", show_alert=True)
        return

    if result.same_buyer and result.listing:
        await callback.answer("Вы уже зарезервировали этот лот.")
        return

    if result.already_reserved or not result.ok or result.listing is None:
        await callback.answer("Уже зарезервировано или недоступно.", show_alert=True)
        return

    listing = result.listing
    await callback.answer("Лот зарезервирован! Продавец получит уведомление.")

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

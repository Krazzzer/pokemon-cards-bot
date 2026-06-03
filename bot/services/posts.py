import html
import json

from aiogram import Bot
from aiogram.types import InputMediaPhoto

from bot.config import get_settings
from bot.db.models import Listing, ListingItem, ListingStatus, User
from bot.keyboards.inline import auction_group_keyboard, listing_group_keyboard
from bot.services.listing_utils import is_auction
from bot.services.listings import has_listing_items, parse_media_file_ids
from bot.services.telegram_safe import (
    safe_edit_message_caption,
    safe_edit_message_reply_markup,
    safe_edit_message_text,
)
from bot.utils.datetime_parse import format_ends_at_local


CURRENCY_SYMBOLS = {
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
    "MDL": "MDL",
}


def _format_amount(price: float, currency: str) -> str:
    cur = currency.upper()
    unit = CURRENCY_SYMBOLS.get(cur, cur)
    if price == int(price):
        number = f"{int(price):,}".replace(",", " ")
    else:
        number = f"{price:,.2f}".replace(",", " ")
    return f"{number} {unit}"


def format_price(price: float, currency: str) -> str:
    return _format_amount(price, currency)


def _seller_mention(seller: User | None, seller_id: int) -> str:
    if seller and seller.username:
        return f"@{html.escape(seller.username)}"
    return f'<a href="tg://user?id={seller_id}">продавец</a>'


def _buyer_mention(buyer_id: int, buyer_username: str | None) -> str:
    if buyer_username:
        return f"@{html.escape(buyer_username)}"
    return f'<a href="tg://user?id={buyer_id}">покупатель</a>'


def _format_includes_block(description: str) -> list[str]:
    block = ["📦<b>Описание товара:</b>"]
    for raw_line in description.splitlines():
        line = raw_line.strip().lstrip("•").lstrip("-").lstrip("—").strip()
        if line:
            block.append(f"• {html.escape(line)}")
    return block


def _item_status_line(item: ListingItem) -> str:
    status = (
        item.status.value
        if isinstance(item.status, ListingStatus)
        else str(item.status).lower()
    )
    if status == ListingStatus.ACTIVE.value:
        return "🟢 в продаже"
    if status == ListingStatus.RESERVED.value and item.buyer_id:
        return f"🟡 резерв — {_buyer_mention(item.buyer_id, None)}"
    if status == ListingStatus.SOLD.value:
        return "🔴 продано"
    if status == ListingStatus.CANCELLED.value:
        return "⚫ снято"
    return "недоступно"


def render_multi_sale_caption(listing: Listing) -> str:
    seller = listing.seller
    lines = [
        "🃏 <b>Товары в продаже</b>",
        "",
    ]

    for item in listing.items:
        lines.append(
            f"{item.position}. <b>{html.escape(item.title)}</b> — "
            f"{format_price(item.price, item.currency)}"
        )
        if item.description:
            lines.append(f"   📝 {html.escape(item.description)}")
        lines.append(f"   Статус: {_item_status_line(item)}")

    lines.append("")
    lines.append(f"Продавец: {_seller_mention(seller, listing.seller_id)}")
    return "\n".join(lines)


def render_multi_sale_preview(items: list[dict], *, currency: str, seller: User) -> str:
    lines = [
        "🃏 <b>Товары в продаже</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. <b>{html.escape(item['title'])}</b> — "
            f"{format_price(float(item['price']), currency)}"
        )
        if item.get("description"):
            lines.append(f"   📝 {html.escape(item['description'])}")
        lines.append("   Статус: 🟢 в продаже")

    lines.append("")
    lines.append(f"Продавец: {_seller_mention(seller, seller.telegram_id)}")
    return "\n".join(lines)


def render_auction_caption(
    listing: Listing,
    *,
    leader_username: str | None = None,
) -> str:
    settings = get_settings()
    seller = listing.seller
    start = listing.start_price or listing.price
    step = listing.min_bid_step or 0

    lines = [
        f"⭐️ Аукцион — {html.escape(listing.title)} ⭐️",
        "",
    ]

    if listing.description:
        lines.extend(_format_includes_block(listing.description))
        lines.append("")

    lines.append(f"💵 Стартовая цена: {_format_amount(start, listing.currency)}")
    lines.append("")

    if (
        listing.status == ListingStatus.ACTIVE
        and listing.price > start
    ):
        lines.append(
            f"💰 Текущая ставка: {_format_amount(listing.price, listing.currency)}"
        )
        lines.append("")

    lines.append(
        f"📈 Минимальный шаг ставки: +{_format_amount(step, listing.currency)}"
    )
    lines.append("")

    if listing.status == ListingStatus.SOLD and listing.buyer_id:
        winner = _buyer_mention(listing.buyer_id, leader_username)
        lines.append(f"Потенциальный покупатель: {winner}")
    elif listing.status == ListingStatus.CANCELLED:
        lines.append("Потенциальный покупатель:")
    elif listing.high_bidder_id:
        leader = _buyer_mention(listing.high_bidder_id, leader_username)
        lines.append(f"Потенциальный покупатель: {leader}")
    else:
        lines.append("Потенциальный покупатель:")

    if listing.ends_at:
        ends_text = format_ends_at_local(listing.ends_at, settings.auction_timezone)
        lines.append("")
        if listing.status == ListingStatus.CANCELLED:
            lines.append("Аукцион завершён без ставок ✨")
        else:
            lines.append(f"Конец аукциона {ends_text} ✨")

    lines.append("")
    lines.append(f"Продавец: {_seller_mention(seller, listing.seller_id)}")

    return "\n".join(lines)


def render_sale_caption(
    listing: Listing,
    *,
    buyer_username: str | None = None,
) -> str:
    seller = listing.seller
    lines = [
        f"🃏 <b>{html.escape(listing.title)}</b>",
        f"💰 {format_price(listing.price, listing.currency)}",
    ]
    if listing.description:
        lines.append(f"📝 {html.escape(listing.description)}")

    lines.append("")
    if listing.status == ListingStatus.ACTIVE:
        lines.append("Статус: 🟢 В продаже")
    elif listing.status == ListingStatus.RESERVED and listing.buyer_id:
        buyer = _buyer_mention(listing.buyer_id, buyer_username)
        lines.append(f"Статус: 🟡 Зарезервировано — {buyer}")
    elif listing.status == ListingStatus.SOLD:
        lines.append("Статус: 🔴 Продано")
    elif listing.status == ListingStatus.CANCELLED:
        lines.append("Статус: ⚫ Снято с продажи")

    lines.append(f"Продавец: {_seller_mention(seller, listing.seller_id)}")
    return "\n".join(lines)


def render_caption(
    listing: Listing,
    *,
    buyer_username: str | None = None,
    leader_username: str | None = None,
) -> str:
    if is_auction(listing):
        return render_auction_caption(listing, leader_username=leader_username)
    if has_listing_items(listing):
        return render_multi_sale_caption(listing)
    return render_sale_caption(listing, buyer_username=buyer_username)


def group_keyboard(listing: Listing, *, bot_username: str | None = None):
    if is_auction(listing):
        return auction_group_keyboard(listing, bot_username=bot_username)
    return listing_group_keyboard(listing, bot_username=bot_username)


async def group_keyboard_for_bot(bot: Bot, listing: Listing):
    me = await bot.get_me()
    bot_username = me.username
    return group_keyboard(listing, bot_username=bot_username)


def _keyboard_for_publish(listing: Listing | None):
    if listing is None or not listing.id or listing.id == "preview":
        return None
    return group_keyboard(listing)


async def attach_group_listing_keyboard(bot: Bot, listing: Listing) -> bool:
    if listing.group_chat_id is None or listing.message_id is None:
        return False
    keyboard = await group_keyboard_for_bot(bot, listing)
    if keyboard is None:
        return False
    await safe_edit_message_reply_markup(
        bot,
        chat_id=listing.group_chat_id,
        message_id=listing.message_id,
        reply_markup=keyboard,
    )
    return True


async def publish_listing(
    bot: Bot,
    *,
    group_chat_id: int,
    title: str,
    description: str | None,
    price: float,
    currency: str,
    media_file_ids: list[str],
    seller: User,
    listing: Listing | None = None,
    caption_listing: Listing | None = None,
) -> tuple[int, list[str]]:
    """Publish to group. Use caption_listing for post text (e.g. auction draft before DB insert)."""
    if caption_listing is not None:
        draft = caption_listing
    elif listing is not None:
        draft = listing
    else:
        draft = Listing(
            id="preview",
            seller_id=seller.telegram_id,
            title=title,
            description=description,
            price=price,
            currency=currency,
            status=ListingStatus.ACTIVE,
            seller=seller,
        )

    caption = render_caption(draft)
    keyboard = _keyboard_for_publish(listing)

    if len(media_file_ids) == 1:
        msg = await bot.send_photo(
            chat_id=group_chat_id,
            photo=media_file_ids[0],
            caption=caption,
            parse_mode="HTML",
        )
        if keyboard:
            await safe_edit_message_reply_markup(
                bot,
                chat_id=group_chat_id,
                message_id=msg.message_id,
                reply_markup=keyboard,
            )
        return msg.message_id, media_file_ids

    # Альбом: кнопки на media group часто не работают — текст + кнопка отдельным сообщением
    media = [InputMediaPhoto(media=fid) for fid in media_file_ids[:10]]
    album_messages = await bot.send_media_group(chat_id=group_chat_id, media=media)
    album_first_id = album_messages[0].message_id

    control_text = f"{caption}\n\n<i>↑ фото лота ({len(media)} шт.)</i>"

    control = await bot.send_message(
        chat_id=group_chat_id,
        text=control_text,
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=album_first_id,
    )
    return control.message_id, media_file_ids


async def publish_multi_item_listing(
    bot: Bot,
    *,
    group_chat_id: int,
    items: list[dict],
    currency: str,
    media_file_ids: list[str],
    seller: User,
) -> tuple[int, list[str]]:
    caption = render_multi_sale_preview(items, currency=currency, seller=seller)

    if not media_file_ids:
        msg = await bot.send_message(
            chat_id=group_chat_id,
            text=caption,
            parse_mode="HTML",
        )
        return msg.message_id, media_file_ids

    if len(media_file_ids) == 1:
        msg = await bot.send_photo(
            chat_id=group_chat_id,
            photo=media_file_ids[0],
            caption=caption,
            parse_mode="HTML",
        )
        return msg.message_id, media_file_ids

    media = [InputMediaPhoto(media=fid) for fid in media_file_ids[:10]]
    album_messages = await bot.send_media_group(chat_id=group_chat_id, media=media)
    album_first_id = album_messages[0].message_id

    control_text = f"{caption}\n\n<i>↑ фото товаров ({len(media)} шт.)</i>"
    control = await bot.send_message(
        chat_id=group_chat_id,
        text=control_text,
        parse_mode="HTML",
        reply_to_message_id=album_first_id,
    )
    return control.message_id, media_file_ids


async def update_listing_post(
    bot: Bot,
    listing: Listing,
    *,
    buyer_username: str | None = None,
    leader_username: str | None = None,
) -> None:
    if listing.group_chat_id is None or listing.message_id is None:
        return

    caption = render_caption(
        listing,
        buyer_username=buyer_username,
        leader_username=leader_username,
    )
    keyboard = await group_keyboard_for_bot(bot, listing)

    file_ids = parse_media_file_ids(listing)
    chat_id = listing.group_chat_id
    message_id = listing.message_id

    if not file_ids:
        await safe_edit_message_text(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            text=caption,
            reply_markup=keyboard,
        )
    elif len(file_ids) == 1:
        await safe_edit_message_caption(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=keyboard,
        )
    else:
        photo_label = "товаров" if has_listing_items(listing) else "лота"
        text = f"{caption}\n\n<i>↑ фото {photo_label} ({len(file_ids)} шт.)</i>"
        await safe_edit_message_text(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
        )

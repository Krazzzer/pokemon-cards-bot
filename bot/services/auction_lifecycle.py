"""Auction completion and notifications."""

from aiogram import Bot

from bot.db.models import ListingStatus
from bot.services.posts import format_price


async def notify_auction_finished(bot: Bot, listing) -> None:
    if listing.high_bidder_id and listing.status == ListingStatus.SOLD:
        winner_text = (
            f"Аукцион <b>{listing.title}</b> завершён.\n"
            f"Вы победили со ставкой {format_price(listing.price, listing.currency)}.\n"
            "Свяжитесь с продавцом в ЛС."
        )
        seller_text = (
            f"Аукцион <b>{listing.title}</b> завершён.\n"
            f"Победитель: id {listing.buyer_id}\n"
            f"Ставка: {format_price(listing.price, listing.currency)}"
        )
        try:
            await bot.send_message(
                listing.high_bidder_id, winner_text, parse_mode="HTML"
            )
        except Exception:
            pass
        try:
            await bot.send_message(
                listing.seller_id, seller_text, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        try:
            await bot.send_message(
                listing.seller_id,
                f"Аукцион <b>{listing.title}</b> завершён без ставок.",
                parse_mode="HTML",
            )
        except Exception:
            pass

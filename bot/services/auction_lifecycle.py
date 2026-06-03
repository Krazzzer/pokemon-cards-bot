"""Auction completion and notifications."""

import html

from aiogram import Bot

from bot.db.models import ListingStatus
from bot.services.posts import format_price


def _winner_mention(winner_id: int, winner_username: str | None) -> str:
    if winner_username:
        return f"@{html.escape(winner_username)}"
    return f'<a href="tg://user?id={winner_id}">победитель</a>'


async def notify_auction_finished(
    bot: Bot,
    listing,
    *,
    winner_username: str | None = None,
) -> None:
    if listing.high_bidder_id and listing.status == ListingStatus.SOLD:
        winner = _winner_mention(listing.high_bidder_id, winner_username)
        winner_text = (
            f"Аукцион <b>{listing.title}</b> завершён.\n"
            f"Вы победили со ставкой {format_price(listing.price, listing.currency)}.\n"
            "Свяжитесь с продавцом в ЛС."
        )
        seller_text = (
            f"Аукцион <b>{listing.title}</b> завершён.\n"
            f"Победитель: {winner}\n"
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

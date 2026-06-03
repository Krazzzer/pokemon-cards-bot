import asyncio
import logging

from aiogram import Bot

from bot.db.models import User
from bot.db.session import get_session_factory
from bot.services.auction_lifecycle import notify_auction_finished
from bot.services.listings import finalize_auction, get_expired_auctions
from bot.services.posts import update_listing_post

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 30


async def finalize_expired_auctions(bot: Bot) -> int:
    count = 0
    async with get_session_factory()() as session:
        expired = await get_expired_auctions(session)
        for listing in expired:
            finalized = await finalize_auction(session, listing.id)
            if finalized is None:
                continue
            count += 1
            winner = (
                await session.get(User, finalized.high_bidder_id)
                if finalized.high_bidder_id
                else None
            )
            winner_username = winner.username if winner else None
            await update_listing_post(bot, finalized, leader_username=winner_username)
            await notify_auction_finished(
                bot,
                finalized,
                winner_username=winner_username,
            )
    return count


async def auction_scheduler_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    logger.info("Auction scheduler started (interval=%ss)", POLL_INTERVAL_SEC)
    while not stop_event.is_set():
        try:
            n = await finalize_expired_auctions(bot)
            if n:
                logger.info("Finalized %s auction(s)", n)
        except Exception:
            logger.exception("Auction scheduler error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass
    logger.info("Auction scheduler stopped")

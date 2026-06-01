from aiogram import Router

from bot.handlers import (
    auction_bids,
    auction_fsm,
    callbacks,
    sell_fsm,
    seller_actions,
    start,
)


def setup_routers() -> Router:
    root = Router()
    root.include_router(start.router)
    root.include_router(sell_fsm.router)
    root.include_router(auction_fsm.router)
    root.include_router(auction_bids.router)
    root.include_router(callbacks.router)
    root.include_router(seller_actions.router)
    return root

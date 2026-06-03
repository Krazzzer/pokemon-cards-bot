from aiogram import Router

from bot.handlers import (
    access_admin,
    auction_bids,
    auction_fsm,
    callbacks,
    sell_fsm,
    seller_actions,
    start,
)
from bot.middlewares.access import UserAccessMiddleware


def setup_routers() -> Router:
    root = Router()
    access_middleware = UserAccessMiddleware()
    root.message.middleware(access_middleware)
    root.callback_query.middleware(access_middleware)
    root.include_router(access_admin.router)
    root.include_router(start.router)
    root.include_router(sell_fsm.router)
    root.include_router(auction_fsm.router)
    root.include_router(auction_bids.router)
    root.include_router(callbacks.router)
    root.include_router(seller_actions.router)
    return root

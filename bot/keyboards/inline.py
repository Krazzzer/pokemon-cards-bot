from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Listing
from bot.services.listing_utils import is_active_listing, is_auction
from bot.services.listings import min_bid_amount


def listing_group_keyboard(listing: Listing) -> InlineKeyboardMarkup | None:
    if is_auction(listing):
        return auction_group_keyboard(listing)
    if is_active_listing(listing):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Купить",
                        callback_data=f"buy:{listing.id}",
                    )
                ]
            ]
        )
    return None


def auction_group_keyboard(listing: Listing) -> InlineKeyboardMarkup | None:
    if not is_auction(listing) or not is_active_listing(listing):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сделать ставку",
                    callback_data=f"bid:{listing.id}",
                )
            ]
        ]
    )


def bid_prompt_keyboard(listing: Listing) -> InlineKeyboardMarkup:
    step = listing.min_bid_step or 0
    minimum = min_bid_amount(listing)
    quick1 = minimum
    quick2 = minimum + step if step else minimum

    rows = [
        [
            InlineKeyboardButton(
                text=f"Ставка {int(quick1) if quick1 == int(quick1) else quick1}",
                callback_data=f"bidamt:{listing.id}:{quick1}",
            ),
        ],
    ]
    if quick2 > quick1:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Ставка {int(quick2) if quick2 == int(quick2) else quick2}",
                    callback_data=f"bidamt:{listing.id}:{quick2}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Ввести свою сумму",
                callback_data=f"bidcustom:{listing.id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seller_listing_keyboard(listing: Listing) -> InlineKeyboardMarkup | None:
    if is_auction(listing):
        if not is_active_listing(listing):
            return None
        if listing.high_bidder_id is not None:
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Завершить аукцион",
                            callback_data=f"endauc:{listing.id}",
                        )
                    ]
                ]
            )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отменить аукцион",
                        callback_data=f"cancelauc:{listing.id}",
                    )
                ]
            ]
        )

    from bot.db.models import ListingStatus

    if listing.status == ListingStatus.RESERVED:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Продано",
                        callback_data=f"sold:{listing.id}",
                    ),
                    InlineKeyboardButton(
                        text="Снять резерв",
                        callback_data=f"unreserve:{listing.id}",
                    ),
                ]
            ]
        )
    if is_active_listing(listing):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отменить объявление",
                        callback_data=f"cancel:{listing.id}",
                    )
                ]
            ]
        )
    return None


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать объявление", callback_data="sell_start"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Создать аукцион", callback_data="auction_start"
                )
            ],
        ]
    )


def sell_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Опубликовать", callback_data="sell_publish"),
                InlineKeyboardButton(text="Отмена", callback_data="sell_abort"),
            ]
        ]
    )


def auction_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Опубликовать", callback_data="auction_publish"
                ),
                InlineKeyboardButton(text="Отмена", callback_data="auction_abort"),
            ]
        ]
    )


def sell_skip_description_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="sell_skip_desc")]
        ]
    )


def sell_photos_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="sell_photos_done")]
        ]
    )


def auction_photos_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Готово", callback_data="auction_photos_done"
                )
            ]
        ]
    )

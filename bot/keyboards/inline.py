from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Listing, ListingItem, ListingStatus
from bot.services.listing_utils import is_active_listing, is_auction
from bot.services.listings import has_listing_items, min_bid_amount


def _item_is_active(item: ListingItem) -> bool:
    status = (
        item.status.value
        if isinstance(item.status, ListingStatus)
        else str(item.status).lower()
    )
    return status == ListingStatus.ACTIVE.value


def listing_group_keyboard(
    listing: Listing,
    *,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup | None:
    if is_auction(listing):
        return auction_group_keyboard(listing)
    if has_listing_items(listing):
        rows = []
        row = []
        for item in listing.items:
            if _item_is_active(item):
                row.append(
                    InlineKeyboardButton(
                        text=f"Купить {item.position}",
                        callback_data=f"buyitem:{item.id}",
                    )
                )
            else:
                row.append(
                    InlineKeyboardButton(
                        text=f"Нет {item.position}",
                        callback_data=f"noop:{item.id}",
                    )
                )
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
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


def listing_items_buy_keyboard(
    listing: Listing,
    *,
    include_back: bool = True,
) -> InlineKeyboardMarkup | None:
    if not has_listing_items(listing):
        return listing_group_keyboard(listing)

    rows = []
    for item in listing.items:
        if _item_is_active(item):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{item.position}. Купить — {item.title[:30]}",
                        callback_data=f"buyitem:{item.id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{item.position}. Недоступно — {item.title[:25]}",
                        callback_data=f"noop:{item.id}",
                    )
                ]
            )

    if include_back:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Свернуть",
                    callback_data=f"backbuy:{listing.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def listing_item_confirm_keyboard(item: ListingItem) -> InlineKeyboardMarkup | None:
    if not _item_is_active(item):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Товар недоступен",
                        callback_data=f"noop:{item.id}",
                    )
                ]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Купить — {item.title[:30]}",
                    callback_data=f"buyitem:{item.id}",
                )
            ]
        ]
    )


def auction_group_keyboard(
    listing: Listing,
    *,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup | None:
    if not is_auction(listing) or not is_active_listing(listing):
        return None
    amount = min_bid_amount(listing)
    button_text = (
        "Сделать шаг ставки"
        if listing.high_bidder_id is not None
        else "Сделать начальную ставку"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"bidamt:{listing.id}:{amount}",
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
                            text="Отменить последнюю ставку",
                            callback_data=f"undobid:{listing.id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Завершить аукцион",
                            callback_data=f"endauc:{listing.id}",
                        )
                    ],
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


def seller_listing_item_keyboard(item: ListingItem) -> InlineKeyboardMarkup | None:
    status = (
        item.status.value
        if isinstance(item.status, ListingStatus)
        else str(item.status).lower()
    )
    if status == ListingStatus.RESERVED.value:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Продано",
                        callback_data=f"solditem:{item.id}",
                    ),
                    InlineKeyboardButton(
                        text="Снять резерв",
                        callback_data=f"unresitem:{item.id}",
                    ),
                ]
            ]
        )
    if status == ListingStatus.ACTIVE.value:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отменить товар",
                        callback_data=f"cancelitem:{item.id}",
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


def sell_items_menu_keyboard(
    has_items: bool,
    *,
    can_add_items: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    top_row: list[InlineKeyboardButton] = []
    if can_add_items:
        top_row.append(
            InlineKeyboardButton(text="Добавить товар", callback_data="sell_add_item")
        )
    if has_items:
        top_row.append(
            InlineKeyboardButton(text="Добавить фото", callback_data="sell_add_photo")
        )
        rows.append(
            [
                InlineKeyboardButton(text="Предпросмотр", callback_data="sell_preview"),
                InlineKeyboardButton(text="Опубликовать", callback_data="sell_publish"),
            ]
        )
    if top_row:
        rows.insert(0, top_row)
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="sell_abort")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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

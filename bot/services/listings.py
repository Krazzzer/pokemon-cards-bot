import json
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Bid, Listing, ListingItem, ListingKind, ListingStatus, User
from bot.services.listing_utils import is_auction


async def upsert_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
        )
        session.add(user)
    else:
        user.username = username
        user.full_name = full_name
    await session.commit()
    return user


async def create_listing(
    session: AsyncSession,
    *,
    seller_id: int,
    title: str,
    description: str | None,
    price: float,
    currency: str,
    media_file_ids: list[str],
    group_chat_id: int,
    message_id: int,
) -> Listing:
    listing = Listing(
        seller_id=seller_id,
        kind=ListingKind.SALE,
        title=title,
        description=description,
        price=price,
        currency=currency,
        status=ListingStatus.ACTIVE,
        group_chat_id=group_chat_id,
        message_id=message_id,
        media_file_ids=json.dumps(media_file_ids),
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


async def create_multi_item_listing(
    session: AsyncSession,
    *,
    seller_id: int,
    items: list[dict],
    currency: str,
    media_file_ids: list[str],
    group_chat_id: int,
    message_id: int,
) -> Listing:
    listing = Listing(
        seller_id=seller_id,
        kind=ListingKind.SALE,
        title=f"Список товаров ({len(items)} шт.)",
        description=None,
        price=sum(float(item["price"]) for item in items),
        currency=currency,
        status=ListingStatus.ACTIVE,
        group_chat_id=group_chat_id,
        message_id=message_id,
        media_file_ids=json.dumps(media_file_ids),
    )
    for index, item in enumerate(items, start=1):
        listing.items.append(
            ListingItem(
                position=index,
                title=item["title"],
                description=item.get("description"),
                price=float(item["price"]),
                currency=currency,
                status=ListingStatus.ACTIVE,
                media_file_ids=json.dumps(item.get("photos", [])),
            )
        )
    session.add(listing)
    await session.commit()
    loaded = await get_listing(session, listing.id)
    assert loaded is not None
    return loaded


async def get_listing(session: AsyncSession, listing_id: str) -> Listing | None:
    result = await session.execute(
        select(Listing)
        .options(selectinload(Listing.seller), selectinload(Listing.items))
        .where(Listing.id == listing_id)
    )
    return result.scalar_one_or_none()


async def get_listing_item(session: AsyncSession, item_id: str) -> ListingItem | None:
    result = await session.execute(
        select(ListingItem)
        .options(
            selectinload(ListingItem.listing).selectinload(Listing.seller),
            selectinload(ListingItem.listing).selectinload(Listing.items),
        )
        .where(ListingItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def get_seller_listings(
    session: AsyncSession,
    seller_id: int,
    *,
    include_sold: bool = False,
) -> list[Listing]:
    statuses = [ListingStatus.ACTIVE, ListingStatus.RESERVED]
    if include_sold:
        statuses.append(ListingStatus.SOLD)
    result = await session.execute(
        select(Listing)
        .options(selectinload(Listing.seller), selectinload(Listing.items))
        .where(Listing.seller_id == seller_id, Listing.status.in_(statuses))
        .order_by(Listing.created_at.desc())
    )
    return list(result.scalars().all())


def has_listing_items(listing: Listing) -> bool:
    return bool(getattr(listing, "items", None))


def _item_status_value(item: ListingItem) -> str:
    status = item.status
    if isinstance(status, ListingStatus):
        return status.value
    if status is None:
        return ListingStatus.ACTIVE.value
    return str(status).lower()


async def _increment_seller_successful_deals(
    session: AsyncSession,
    seller_id: int,
) -> None:
    seller = await session.get(User, seller_id)
    if seller is not None:
        seller.successful_deals = (seller.successful_deals or 0) + 1


async def _sync_parent_listing_status(
    session: AsyncSession, listing_id: str
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None:
        return None
    if not has_listing_items(listing):
        return listing

    statuses = [_item_status_value(item) for item in listing.items]
    if any(status == ListingStatus.ACTIVE.value for status in statuses):
        listing.status = ListingStatus.ACTIVE
        listing.buyer_id = None
        listing.reserved_at = None
        listing.sold_at = None
    elif any(status == ListingStatus.RESERVED.value for status in statuses):
        listing.status = ListingStatus.RESERVED
        listing.buyer_id = None
        listing.sold_at = None
    elif statuses and all(status == ListingStatus.SOLD.value for status in statuses):
        listing.status = ListingStatus.SOLD
        listing.buyer_id = None
        listing.sold_at = datetime.utcnow()
    else:
        listing.status = ListingStatus.CANCELLED
        listing.buyer_id = None

    await session.commit()
    return await get_listing(session, listing_id)


class ReserveResult:
    def __init__(
        self,
        ok: bool,
        listing: Listing | None = None,
        *,
        already_reserved: bool = False,
        own_listing: bool = False,
        same_buyer: bool = False,
    ):
        self.ok = ok
        self.listing = listing
        self.already_reserved = already_reserved
        self.own_listing = own_listing
        self.same_buyer = same_buyer


class ItemReserveResult:
    def __init__(
        self,
        ok: bool,
        listing: Listing | None = None,
        item: ListingItem | None = None,
        *,
        already_reserved: bool = False,
        own_listing: bool = False,
        same_buyer: bool = False,
    ):
        self.ok = ok
        self.listing = listing
        self.item = item
        self.already_reserved = already_reserved
        self.own_listing = own_listing
        self.same_buyer = same_buyer


async def reserve_listing(
    session: AsyncSession,
    listing_id: str,
    buyer_id: int,
) -> ReserveResult:
    listing = await get_listing(session, listing_id)
    if listing is None:
        return ReserveResult(False)

    if is_auction(listing):
        return ReserveResult(False, listing, already_reserved=True)

    if listing.seller_id == buyer_id:
        return ReserveResult(False, listing, own_listing=True)

    if listing.status == ListingStatus.RESERVED:
        if listing.buyer_id == buyer_id:
            return ReserveResult(True, listing, same_buyer=True)
        return ReserveResult(False, listing, already_reserved=True)

    if listing.status != ListingStatus.ACTIVE:
        return ReserveResult(False, listing, already_reserved=True)

    now = datetime.utcnow()
    result = await session.execute(
        update(Listing)
        .where(Listing.id == listing_id, Listing.status == ListingStatus.ACTIVE)
        .values(
            status=ListingStatus.RESERVED,
            buyer_id=buyer_id,
            reserved_at=now,
        )
    )
    await session.commit()

    if result.rowcount == 0:
        listing = await get_listing(session, listing_id)
        if listing and listing.buyer_id == buyer_id:
            return ReserveResult(True, listing, same_buyer=True)
        return ReserveResult(False, listing, already_reserved=True)

    listing = await get_listing(session, listing_id)
    return ReserveResult(True, listing)


async def reserve_listing_item(
    session: AsyncSession,
    item_id: str,
    buyer_id: int,
) -> ItemReserveResult:
    item = await get_listing_item(session, item_id)
    if item is None:
        return ItemReserveResult(False)

    listing = item.listing
    if is_auction(listing):
        return ItemReserveResult(False, listing, item, already_reserved=True)

    if listing.seller_id == buyer_id:
        return ItemReserveResult(False, listing, item, own_listing=True)

    item_status = _item_status_value(item)
    if item_status == ListingStatus.RESERVED.value:
        if item.buyer_id == buyer_id:
            return ItemReserveResult(True, listing, item, same_buyer=True)
        return ItemReserveResult(False, listing, item, already_reserved=True)

    if item_status != ListingStatus.ACTIVE.value:
        return ItemReserveResult(False, listing, item, already_reserved=True)

    now = datetime.utcnow()
    result = await session.execute(
        update(ListingItem)
        .where(ListingItem.id == item_id, ListingItem.status == ListingStatus.ACTIVE)
        .values(
            status=ListingStatus.RESERVED,
            buyer_id=buyer_id,
            reserved_at=now,
        )
    )
    await session.commit()

    if result.rowcount == 0:
        item = await get_listing_item(session, item_id)
        if item and item.buyer_id == buyer_id:
            return ItemReserveResult(True, item.listing, item, same_buyer=True)
        return ItemReserveResult(
            False,
            item.listing if item else None,
            item,
            already_reserved=True,
        )

    item = await get_listing_item(session, item_id)
    listing = await _sync_parent_listing_status(session, item.listing_id) if item else None
    if item and listing:
        item = await get_listing_item(session, item.id)
    return ItemReserveResult(True, listing, item)


async def mark_sold(session: AsyncSession, listing_id: str, seller_id: int) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None or listing.seller_id != seller_id:
        return None
    if is_auction(listing):
        return None
    if listing.status not in (ListingStatus.RESERVED, ListingStatus.ACTIVE):
        return None

    listing.status = ListingStatus.SOLD
    listing.sold_at = datetime.utcnow()
    await _increment_seller_successful_deals(session, listing.seller_id)
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


async def mark_listing_item_sold(
    session: AsyncSession, item_id: str, seller_id: int
) -> Listing | None:
    item = await get_listing_item(session, item_id)
    if item is None or item.listing.seller_id != seller_id:
        return None
    if is_auction(item.listing):
        return None
    if _item_status_value(item) not in (
        ListingStatus.RESERVED.value,
        ListingStatus.ACTIVE.value,
    ):
        return None

    item.status = ListingStatus.SOLD
    item.sold_at = datetime.utcnow()
    await _increment_seller_successful_deals(session, item.listing.seller_id)
    await session.commit()
    return await _sync_parent_listing_status(session, item.listing_id)


async def unreserve_listing(
    session: AsyncSession, listing_id: str, seller_id: int
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None or listing.seller_id != seller_id:
        return None
    if listing.status != ListingStatus.RESERVED:
        return None

    listing.status = ListingStatus.ACTIVE
    listing.buyer_id = None
    listing.reserved_at = None
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


async def unreserve_listing_item(
    session: AsyncSession, item_id: str, seller_id: int
) -> Listing | None:
    item = await get_listing_item(session, item_id)
    if item is None or item.listing.seller_id != seller_id:
        return None
    if _item_status_value(item) != ListingStatus.RESERVED.value:
        return None

    item.status = ListingStatus.ACTIVE
    item.buyer_id = None
    item.reserved_at = None
    await session.commit()
    return await _sync_parent_listing_status(session, item.listing_id)


async def cancel_listing(
    session: AsyncSession, listing_id: str, seller_id: int
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None or listing.seller_id != seller_id:
        return None
    if is_auction(listing):
        return await cancel_auction_if_no_bids(session, listing_id, seller_id)
    if listing.status in (ListingStatus.SOLD, ListingStatus.CANCELLED):
        return None

    listing.status = ListingStatus.CANCELLED
    listing.buyer_id = None
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


async def cancel_listing_item(
    session: AsyncSession, item_id: str, seller_id: int
) -> Listing | None:
    item = await get_listing_item(session, item_id)
    if item is None or item.listing.seller_id != seller_id:
        return None
    if is_auction(item.listing):
        return None
    if _item_status_value(item) in (
        ListingStatus.SOLD.value,
        ListingStatus.CANCELLED.value,
    ):
        return None

    item.status = ListingStatus.CANCELLED
    item.buyer_id = None
    await session.commit()
    return await _sync_parent_listing_status(session, item.listing_id)


def parse_media_file_ids(listing: Listing) -> list[str]:
    try:
        data = json.loads(listing.media_file_ids or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def parse_item_media_file_ids(item: ListingItem) -> list[str]:
    try:
        data = json.loads(item.media_file_ids or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def new_auction_listing(
    *,
    seller_id: int,
    title: str,
    description: str | None,
    start_price: float,
    min_bid_step: float,
    ends_at: datetime,
    currency: str,
    group_chat_id: int,
    seller: User | None = None,
) -> Listing:
    listing = Listing(
        seller_id=seller_id,
        kind=ListingKind.AUCTION,
        title=title,
        description=description,
        price=start_price,
        start_price=start_price,
        min_bid_step=min_bid_step,
        ends_at=ends_at,
        currency=currency,
        status=ListingStatus.ACTIVE,
        group_chat_id=group_chat_id,
        message_id=None,
        media_file_ids="[]",
    )
    if seller is not None:
        listing.seller = seller
    return listing


async def save_auction_listing(
    session: AsyncSession,
    listing: Listing,
    *,
    message_id: int,
    media_file_ids: list[str],
) -> Listing:
    listing.message_id = message_id
    listing.media_file_ids = json.dumps(media_file_ids)
    session.add(listing)
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


def min_bid_amount(listing: Listing) -> float:
    assert listing.start_price is not None and listing.min_bid_step is not None
    if listing.high_bidder_id is None:
        return listing.start_price
    return listing.price + listing.min_bid_step


class BidResult:
    def __init__(
        self,
        ok: bool,
        listing: Listing | None = None,
        *,
        reason: str | None = None,
        previous_bidder_id: int | None = None,
    ):
        self.ok = ok
        self.listing = listing
        self.reason = reason
        self.previous_bidder_id = previous_bidder_id


async def place_bid(
    session: AsyncSession,
    listing_id: str,
    user_id: int,
    amount: float,
) -> BidResult:
    listing = await get_listing(session, listing_id)
    if listing is None:
        return BidResult(False, reason="not_found")

    if not is_auction(listing):
        return BidResult(False, listing, reason="not_auction")

    if listing.status != ListingStatus.ACTIVE:
        return BidResult(False, listing, reason="not_active")

    now = datetime.utcnow()
    if listing.ends_at is None or listing.ends_at <= now:
        return BidResult(False, listing, reason="ended")

    if listing.seller_id == user_id:
        return BidResult(False, listing, reason="own_listing")

    required = min_bid_amount(listing)
    if amount < required:
        return BidResult(False, listing, reason="too_low")

    previous_bidder = listing.high_bidder_id
    expected_price = listing.price

    result = await session.execute(
        update(Listing)
        .where(
            Listing.id == listing_id,
            Listing.kind == ListingKind.AUCTION,
            Listing.status == ListingStatus.ACTIVE,
            Listing.ends_at > now,
            Listing.price == expected_price,
        )
        .values(price=amount, high_bidder_id=user_id)
    )

    if result.rowcount == 0:
        listing = await get_listing(session, listing_id)
        return BidResult(False, listing, reason="concurrent_bid")

    session.add(
        Bid(listing_id=listing_id, user_id=user_id, amount=amount, created_at=now)
    )
    await session.commit()
    listing = await get_listing(session, listing_id)
    return BidResult(True, listing, previous_bidder_id=previous_bidder)


async def get_expired_auctions(session: AsyncSession) -> list[Listing]:
    now = datetime.utcnow()
    result = await session.execute(
        select(Listing)
        .options(selectinload(Listing.seller))
        .where(
            Listing.kind == ListingKind.AUCTION,
            Listing.status == ListingStatus.ACTIVE,
            Listing.ends_at <= now,
        )
    )
    return list(result.scalars().all())


async def finalize_auction(
    session: AsyncSession,
    listing_id: str,
    *,
    force: bool = False,
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None:
        return None
    if not is_auction(listing) or listing.status != ListingStatus.ACTIVE:
        return listing

    now = datetime.utcnow()
    if not force and (listing.ends_at is None or listing.ends_at > now):
        return listing

    if listing.high_bidder_id is not None:
        listing.status = ListingStatus.SOLD
        listing.buyer_id = listing.high_bidder_id
        listing.sold_at = now
        await _increment_seller_successful_deals(session, listing.seller_id)
    else:
        listing.status = ListingStatus.CANCELLED

    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing


async def end_auction_by_seller(
    session: AsyncSession, listing_id: str, seller_id: int
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None or listing.seller_id != seller_id:
        return None
    if not is_auction(listing) or listing.status != ListingStatus.ACTIVE:
        return None
    return await finalize_auction(session, listing_id, force=True)


async def cancel_auction_if_no_bids(
    session: AsyncSession, listing_id: str, seller_id: int
) -> Listing | None:
    listing = await get_listing(session, listing_id)
    if listing is None or listing.seller_id != seller_id:
        return None
    if not is_auction(listing) or listing.status != ListingStatus.ACTIVE:
        return None
    if listing.high_bidder_id is not None:
        return None

    listing.status = ListingStatus.CANCELLED
    await session.commit()
    await session.refresh(listing, attribute_names=["seller"])
    return listing

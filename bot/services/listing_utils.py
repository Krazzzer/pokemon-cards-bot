"""Helpers for listing kind/status (SQLite-safe)."""

from bot.db.models import Listing, ListingKind, ListingStatus


def listing_kind_value(listing: Listing) -> str:
    kind = listing.kind
    if isinstance(kind, ListingKind):
        return kind.value
    if kind is None:
        return ListingKind.SALE.value
    return str(kind).lower()


def listing_status_value(listing: Listing) -> str:
    status = listing.status
    if isinstance(status, ListingStatus):
        return status.value
    if status is None:
        return ListingStatus.ACTIVE.value
    return str(status).lower()


def is_auction(listing: Listing) -> bool:
    if listing_kind_value(listing) == ListingKind.AUCTION.value:
        return True
    return (
        listing.start_price is not None
        and listing.min_bid_step is not None
        and listing.ends_at is not None
    )


def is_sale(listing: Listing) -> bool:
    return not is_auction(listing)


def is_active_listing(listing: Listing) -> bool:
    return listing_status_value(listing) == ListingStatus.ACTIVE.value

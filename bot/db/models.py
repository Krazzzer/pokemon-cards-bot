import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ListingStatus(str, enum.Enum):
    ACTIVE = "active"
    RESERVED = "reserved"
    SOLD = "sold"
    CANCELLED = "cancelled"


class ListingKind(str, enum.Enum):
    SALE = "sale"
    AUCTION = "auction"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="seller")
    bids: Mapped[list["Bid"]] = relationship(back_populates="user")


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    kind: Mapped[ListingKind] = mapped_column(
        Enum(
            ListingKind,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
        ),
        default=ListingKind.SALE,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    status: Mapped[ListingStatus] = mapped_column(
        Enum(
            ListingStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
        ),
        default=ListingStatus.ACTIVE,
        nullable=False,
    )
    buyer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_file_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    start_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_bid_step: Mapped[float | None] = mapped_column(Float, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    high_bidder_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    seller: Mapped["User"] = relationship(back_populates="listings")
    items: Mapped[list["ListingItem"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="ListingItem.position",
    )
    bids: Mapped[list["Bid"]] = relationship(
        back_populates="listing", order_by="Bid.created_at"
    )


class ListingItem(Base):
    __tablename__ = "listing_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    listing_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("listings.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    status: Mapped[ListingStatus] = mapped_column(
        Enum(
            ListingStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
        ),
        default=ListingStatus.ACTIVE,
        nullable=False,
    )
    buyer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_file_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    listing: Mapped["Listing"] = relationship(back_populates="items")


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("listings.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    listing: Mapped["Listing"] = relationship(back_populates="bids")
    user: Mapped["User"] = relationship(back_populates="bids")

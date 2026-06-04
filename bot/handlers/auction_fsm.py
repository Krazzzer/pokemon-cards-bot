from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User as TelegramUser

from bot.config import get_settings
from bot.db.models import Listing, ListingKind, ListingStatus, User
from bot.db.session import get_session_factory
from bot.handlers.sell_fsm import MAX_PHOTOS, parse_price
from bot.keyboards.inline import (
    auction_confirm_keyboard,
    auction_photos_done_keyboard,
    seller_listing_keyboard,
)
from bot.services.listings import new_auction_listing, save_auction_listing, upsert_user
from bot.services.posts import (
    attach_group_listing_keyboard,
    group_keyboard,
    publish_listing,
    render_caption,
)
from bot.services.seller_access import ensure_seller_callback, ensure_seller_message
from bot.utils.datetime_parse import parse_auction_end

router = Router(name="auction_fsm")


class AuctionStates(StatesGroup):
    title = State()
    description = State()
    start_price = State()
    min_step = State()
    ends_at = State()
    photos = State()
    confirm = State()


async def _start_auction(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AuctionStates.title)
    await message.answer(
        "Создание <b>аукциона</b>.\n\n"
        "Введите <b>название</b> лота:",
        parse_mode="HTML",
    )


@router.message(Command("auction"), F.chat.type == "private")
async def cmd_auction(message: Message, state: FSMContext) -> None:
    if not await ensure_seller_message(message):
        return
    await _start_auction(message, state)


@router.callback_query(F.data == "auction_start")
async def cb_auction_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    if not await ensure_seller_callback(callback):
        return
    await callback.answer()
    await _start_auction(callback.message, state)


@router.message(AuctionStates.title, F.chat.type == "private")
async def auction_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Введите ещё раз:")
        return
    if len(title) > 256:
        await message.answer("Название слишком длинное (макс. 256 символов).")
        return
    await state.update_data(title=title)
    await state.set_state(AuctionStates.description)
    await message.answer(
        "Введите <b>описание товара</b> (что входит в лот, по строкам):",
        parse_mode="HTML",
    )


@router.message(AuctionStates.description, F.chat.type == "private")
async def auction_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    if len(desc) < 2:
        await message.answer("Описание слишком короткое. Введите ещё раз:")
        return
    if len(desc) > 2000:
        await message.answer("Описание слишком длинное.")
        return
    await state.update_data(description=desc)
    await state.set_state(AuctionStates.start_price)
    await message.answer(
        "Введите <b>стартовую цену</b> (число):",
        parse_mode="HTML",
    )


@router.message(AuctionStates.start_price, F.chat.type == "private")
async def auction_start_price(message: Message, state: FSMContext) -> None:
    price = parse_price(message.text or "")
    if price is None:
        await message.answer("Некорректная цена. Введите положительное число:")
        return
    await state.update_data(start_price=price)
    await state.set_state(AuctionStates.min_step)
    await message.answer(
        "Введите <b>минимальный шаг ставки</b> (число):",
        parse_mode="HTML",
    )


@router.message(AuctionStates.min_step, F.chat.type == "private")
async def auction_min_step(message: Message, state: FSMContext) -> None:
    step = parse_price(message.text or "")
    if step is None:
        await message.answer("Некорректный шаг. Введите положительное число:")
        return
    await state.update_data(min_bid_step=step)
    await state.set_state(AuctionStates.ends_at)
    settings = get_settings()
    await message.answer(
        "Введите <b>дату и время окончания</b> аукциона.\n"
        f"Формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code> или <code>ДД.ММ.ГГГГ</code> "
        f"(до 23:59), часовой пояс <b>{settings.auction_timezone}</b>.\n"
        "Пример: <code>15.06.2026 20:00</code>",
        parse_mode="HTML",
    )


@router.message(AuctionStates.ends_at, F.chat.type == "private")
async def auction_ends_at(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    ends = parse_auction_end(message.text or "", settings.auction_timezone)
    if ends is None:
        await message.answer(
            "Не удалось разобрать дату. Пример: <code>15.06.2026 20:00</code>",
            parse_mode="HTML",
        )
        return
    if ends <= datetime.utcnow():
        await message.answer("Дата должна быть в будущем. Введите снова:")
        return
    await state.update_data(ends_at=ends.isoformat())
    await state.update_data(photos=[])
    await state.set_state(AuctionStates.photos)
    await message.answer(
        f"Отправьте от 1 до {MAX_PHOTOS} фото.\n"
        "Когда загрузите все — нажмите «Готово».",
        reply_markup=auction_photos_done_keyboard(),
    )


@router.message(AuctionStates.photos, ~F.photo, F.chat.type == "private")
async def auction_photos_other(message: Message) -> None:
    await message.answer(
        "Отправьте фото или нажмите «Готово».",
        reply_markup=auction_photos_done_keyboard(),
    )


@router.message(AuctionStates.photos, F.photo, F.chat.type == "private")
async def auction_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = list(data.get("photos", []))
    if len(photos) >= MAX_PHOTOS:
        await message.answer(f"Максимум {MAX_PHOTOS} фото. Нажмите «Готово».")
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)
    await message.answer(
        f"Фото добавлено ({len(photos)}/{MAX_PHOTOS}).",
        reply_markup=auction_photos_done_keyboard(),
    )


@router.callback_query(AuctionStates.photos, F.data == "auction_photos_done")
async def auction_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("photos"):
        await callback.answer("Добавьте хотя бы одно фото.", show_alert=True)
        return
    await callback.answer()
    await _show_auction_preview(
        callback.message,
        state,
        seller_user=callback.from_user,
    )


async def _show_auction_preview(
    message: Message | None,
    state: FSMContext,
    *,
    seller_user: TelegramUser | None,
) -> None:
    if message is None or seller_user is None:
        return
    data = await state.get_data()
    settings = get_settings()
    preview_user = User(
        telegram_id=seller_user.id,
        username=seller_user.username,
        full_name=seller_user.full_name,
    )
    ends_at = datetime.fromisoformat(data["ends_at"])
    preview = Listing(
        id="preview",
        kind=ListingKind.AUCTION,
        seller_id=preview_user.telegram_id,
        title=data["title"],
        description=data.get("description"),
        price=data["start_price"],
        start_price=data["start_price"],
        min_bid_step=data["min_bid_step"],
        ends_at=ends_at,
        currency=settings.default_currency,
        status=ListingStatus.ACTIVE,
        seller=preview_user,
    )
    caption = render_caption(preview)
    await state.set_state(AuctionStates.confirm)
    photos: list[str] = data.get("photos", [])
    if len(photos) == 1:
        await message.answer_photo(
            photo=photos[0],
            caption=f"<b>Превью аукциона:</b>\n\n{caption}",
            parse_mode="HTML",
            reply_markup=auction_confirm_keyboard(),
        )
    else:
        await message.answer(
            f"<b>Превью аукциона:</b>\n\n{caption}\n\n"
            f"<i>Фото: {len(photos)}</i>",
            parse_mode="HTML",
            reply_markup=auction_confirm_keyboard(),
        )


@router.callback_query(AuctionStates.confirm, F.data == "auction_abort")
async def auction_abort(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Аукцион отменён.")


@router.callback_query(AuctionStates.confirm, F.data == "auction_publish")
async def auction_publish(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    data = await state.get_data()
    settings = get_settings()
    photos: list[str] = data.get("photos", [])
    if not photos:
        await callback.answer("Нет фото.", show_alert=True)
        return

    ends_at = datetime.fromisoformat(data["ends_at"])
    await callback.answer("Публикую…")

    async with get_session_factory()() as session:
        seller = await upsert_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )

        listing = new_auction_listing(
            seller_id=seller.telegram_id,
            title=data["title"],
            description=data.get("description"),
            start_price=data["start_price"],
            min_bid_step=data["min_bid_step"],
            ends_at=ends_at,
            currency=settings.default_currency,
            group_chat_id=settings.group_chat_id,
            seller=seller,
        )
        session.add(listing)
        await session.flush()

        try:
            message_id, file_ids = await publish_listing(
                callback.bot,
                group_chat_id=settings.group_chat_id,
                title=data["title"],
                description=data.get("description"),
                price=data["start_price"],
                currency=settings.default_currency,
                media_file_ids=photos,
                seller=seller,
                listing=listing,
                caption_listing=listing,
                message_thread_id=settings.auction_topic_id,
            )
        except Exception as exc:
            await session.rollback()
            await callback.message.answer(
                f"Не удалось опубликовать: {exc}\n"
                "Проверьте права бота и GROUP_CHAT_ID."
            )
            return

        listing = await save_auction_listing(
            session,
            listing,
            message_id=message_id,
            media_file_ids=file_ids,
        )

    if group_keyboard(listing) is None:
        await callback.message.answer(
            "Аукцион сохранён, но кнопка «Сделать ставку» недоступна "
            "(проверьте статус лота в /my)."
        )
    else:
        await attach_group_listing_keyboard(callback.bot, listing)

    await state.clear()
    await callback.message.answer(
        f"Аукцион опубликован!\nID: <code>{listing.id}</code>\n/my — управление",
        parse_mode="HTML",
    )
    kb = seller_listing_keyboard(listing)
    if kb:
        await callback.message.answer(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=kb,
        )

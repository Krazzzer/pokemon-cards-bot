import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.db.session import get_session_factory
from bot.keyboards.inline import (
    sell_confirm_keyboard,
    sell_photos_done_keyboard,
    sell_skip_description_keyboard,
)
from bot.services.listings import create_listing, upsert_user
from bot.services.posts import attach_group_listing_keyboard, publish_listing, render_caption

router = Router(name="sell_fsm")

MAX_PHOTOS = 10


class SellStates(StatesGroup):
    title = State()
    price = State()
    photos = State()
    description = State()
    confirm = State()


@router.message(Command("sell"), F.chat.type == "private")
async def cmd_sell(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SellStates.title)
    await message.answer(
        "Создание объявления.\n\nВведите <b>название</b> лота:",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "sell_start")
async def cb_sell_start_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await state.clear()
    await state.set_state(SellStates.title)
    await callback.message.answer(
        "Создание объявления.\n\nВведите <b>название</b> лота:",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), F.chat.type == "private")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Создание отменено.")


@router.message(SellStates.title, F.chat.type == "private")
async def sell_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Введите ещё раз:")
        return
    if len(title) > 256:
        await message.answer("Название слишком длинное (макс. 256 символов).")
        return
    await state.update_data(title=title)
    await state.set_state(SellStates.price)
    await message.answer(
        "Введите <b>цену</b> числом (например: 12500 или 12500.50):",
        parse_mode="HTML",
    )


def parse_price(text: str) -> float | None:
    cleaned = text.strip().replace(" ", "").replace(",", ".")
    if not re.match(r"^\d+(\.\d{1,2})?$", cleaned):
        return None
    value = float(cleaned)
    if value <= 0:
        return None
    return value


@router.message(SellStates.price, F.chat.type == "private")
async def sell_price(message: Message, state: FSMContext) -> None:
    price = parse_price(message.text or "")
    if price is None:
        await message.answer("Некорректная цена. Введите положительное число:")
        return
    await state.update_data(price=price)
    await state.update_data(photos=[])
    await state.set_state(SellStates.photos)
    await message.answer(
        f"Отправьте от 1 до {MAX_PHOTOS} фото товара.\n"
        "Когда загрузите все — нажмите «Готово».",
        reply_markup=sell_photos_done_keyboard(),
    )


@router.message(SellStates.photos, ~F.photo, F.chat.type == "private")
async def sell_photos_other(message: Message) -> None:
    await message.answer(
        "Отправьте фото товара или нажмите «Готово».",
        reply_markup=sell_photos_done_keyboard(),
    )


@router.message(SellStates.photos, F.photo, F.chat.type == "private")
async def sell_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = list(data.get("photos", []))
    if len(photos) >= MAX_PHOTOS:
        await message.answer(f"Максимум {MAX_PHOTOS} фото. Нажмите «Готово».")
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)
    await message.answer(
        f"Фото добавлено ({len(photos)}/{MAX_PHOTOS}). "
        "Отправьте ещё или нажмите «Готово».",
        reply_markup=sell_photos_done_keyboard(),
    )


@router.callback_query(SellStates.photos, F.data == "sell_photos_done")
async def sell_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos", [])
    if not photos:
        await callback.answer("Добавьте хотя бы одно фото.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(SellStates.description)
    if callback.message:
        await callback.message.answer(
            "Введите <b>описание</b> (состояние, доставка и т.д.) "
            "или нажмите «Пропустить»:",
            parse_mode="HTML",
            reply_markup=sell_skip_description_keyboard(),
        )


@router.callback_query(SellStates.description, F.data == "sell_skip_desc")
async def sell_skip_description(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(description=None)
    await _show_preview(callback.message, state)


@router.message(SellStates.description, F.chat.type == "private")
async def sell_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    if len(desc) > 2000:
        await message.answer("Описание слишком длинное (макс. 2000 символов).")
        return
    await state.update_data(description=desc or None)
    await _show_preview(message, state)


async def _show_preview(message: Message | None, state: FSMContext) -> None:
    if message is None:
        return
    data = await state.get_data()
    settings = get_settings()

    from bot.db.models import Listing, ListingStatus, User

    user = message.from_user
    preview_user = User(
        telegram_id=user.id if user else 0,
        username=user.username if user else None,
    )
    preview = Listing(
        id="preview",
        seller_id=preview_user.telegram_id,
        title=data["title"],
        description=data.get("description"),
        price=data["price"],
        currency=settings.default_currency,
        status=ListingStatus.ACTIVE,
        seller=preview_user,
    )
    caption = render_caption(preview)
    await state.set_state(SellStates.confirm)

    photos: list[str] = data.get("photos", [])
    if len(photos) == 1:
        await message.answer_photo(
            photo=photos[0],
            caption=f"<b>Превью объявления:</b>\n\n{caption}",
            parse_mode="HTML",
            reply_markup=sell_confirm_keyboard(),
        )
    else:
        await message.answer(
            f"<b>Превью объявления:</b>\n\n{caption}\n\n"
            f"<i>Фото в альбоме: {len(photos)}</i>",
            parse_mode="HTML",
            reply_markup=sell_confirm_keyboard(),
        )


@router.callback_query(SellStates.confirm, F.data == "sell_abort")
async def sell_abort(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Публикация отменена.")


@router.callback_query(SellStates.confirm, F.data == "sell_publish")
async def sell_publish(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    data = await state.get_data()
    settings = get_settings()
    photos: list[str] = data.get("photos", [])

    if not photos:
        await callback.answer("Нет фото.", show_alert=True)
        return

    await callback.answer("Публикую…")

    async with get_session_factory()() as session:
        seller = await upsert_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )

        try:
            message_id, file_ids = await publish_listing(
                callback.bot,
                group_chat_id=settings.group_chat_id,
                title=data["title"],
                description=data.get("description"),
                price=data["price"],
                currency=settings.default_currency,
                media_file_ids=photos,
                seller=seller,
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось опубликовать в группу: {exc}\n\n"
                "Проверьте, что бот добавлен в группу с правами на отправку "
                "и редактирование сообщений, и что GROUP_CHAT_ID верный."
            )
            return

        listing = await create_listing(
            session,
            seller_id=seller.telegram_id,
            title=data["title"],
            description=data.get("description"),
            price=data["price"],
            currency=settings.default_currency,
            media_file_ids=file_ids,
            group_chat_id=settings.group_chat_id,
            message_id=message_id,
        )

    try:
        await attach_group_listing_keyboard(callback.bot, listing)
    except Exception as exc:
        await callback.message.answer(
            f"Объявление создано, но кнопка «Купить» не обновилась: {exc}\n"
            "Опубликуйте объявление заново или проверьте права бота в группе."
        )

    await state.clear()
    await callback.message.answer(
        f"Объявление опубликовано!\n"
        f"ID: <code>{listing.id}</code>\n\n"
        "При резерве или продаже вы получите уведомление. "
        "Управлять лотом: /my",
        parse_mode="HTML",
    )

    from bot.keyboards.inline import seller_listing_keyboard
    from bot.services.posts import render_caption

    kb = seller_listing_keyboard(listing)
    if kb:
        await callback.message.answer(
            render_caption(listing),
            parse_mode="HTML",
            reply_markup=kb,
        )

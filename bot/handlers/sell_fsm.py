import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.db.session import get_session_factory
from bot.keyboards.inline import (
    sell_items_menu_keyboard,
    sell_photos_done_keyboard,
    sell_skip_description_keyboard,
)
from bot.services.listings import create_multi_item_listing, upsert_user
from bot.services.posts import (
    attach_group_listing_keyboard,
    publish_multi_item_listing,
    render_caption,
    render_multi_sale_preview,
)
from bot.services.seller_access import ensure_seller_callback, ensure_seller_message

router = Router(name="sell_fsm")

MAX_PHOTOS = 10


class SellStates(StatesGroup):
    menu = State()
    item_title = State()
    item_price = State()
    item_photos = State()
    item_description = State()


@router.message(Command("sell"), F.chat.type == "private")
async def cmd_sell(message: Message, state: FSMContext) -> None:
    if not await ensure_seller_message(message):
        return
    await state.clear()
    await state.update_data(items=[], photos=[])
    await _show_menu(message, state)


@router.callback_query(F.data == "sell_start")
async def cb_sell_start_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    if not await ensure_seller_callback(callback):
        return
    await callback.answer()
    await state.clear()
    await state.update_data(items=[], photos=[])
    await _show_menu(callback.message, state)


@router.message(Command("cancel"), F.chat.type == "private")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Создание отменено.")


def _items_summary(items: list[dict], currency: str) -> str:
    if not items:
        return "Пока товаров нет."
    lines = []
    for index, item in enumerate(items, start=1):
        price = item["price"]
        price_text = int(price) if price == int(price) else price
        lines.append(f"{index}. {item['title']} — {price_text} {currency}")
    return "\n".join(lines)


async def _show_menu(message: Message | None, state: FSMContext) -> None:
    if message is None:
        return
    data = await state.get_data()
    items: list[dict] = data.get("items", [])
    photos: list[str] = data.get("photos", [])
    settings = get_settings()
    await state.set_state(SellStates.menu)
    await message.answer(
        "<b>Создание объявления со списком товаров</b>\n\n"
        f"{_items_summary(items, settings.default_currency)}\n\n"
        f"Фото в посте: {len(photos)}/{MAX_PHOTOS}\n\n"
        "Добавьте товары по порядку. Когда список будет готов — опубликуйте.",
        parse_mode="HTML",
        reply_markup=sell_items_menu_keyboard(bool(items)),
    )


@router.callback_query(SellStates.menu, F.data == "sell_add_item")
async def sell_add_item(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    items: list[dict] = data.get("items", [])
    await callback.answer()
    await state.update_data(current_item={})
    await state.set_state(SellStates.item_title)
    if callback.message:
        await callback.message.answer(
            f"Товар #{len(items) + 1}.\n\nВведите <b>название</b>:",
            parse_mode="HTML",
        )


@router.message(SellStates.item_title, F.chat.type == "private")
async def sell_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Введите ещё раз:")
        return
    if len(title) > 256:
        await message.answer("Название слишком длинное (макс. 256 символов).")
        return
    await state.update_data(current_item={"title": title})
    await state.set_state(SellStates.item_price)
    await message.answer(
        "Введите <b>цену</b>:",
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


@router.message(SellStates.item_price, F.chat.type == "private")
async def sell_price(message: Message, state: FSMContext) -> None:
    price = parse_price(message.text or "")
    if price is None:
        await message.answer("Некорректная цена. Введите положительное число:")
        return
    data = await state.get_data()
    item = dict(data.get("current_item", {}))
    item["price"] = price
    await state.update_data(current_item=item)
    await state.set_state(SellStates.item_description)
    await message.answer(
        "Введите <b>описание</b> (состояние, доставка и т.д.) "
        "или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=sell_skip_description_keyboard(),
    )


@router.callback_query(SellStates.menu, F.data == "sell_add_photo")
async def sell_add_photo(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos", [])
    if len(photos) >= MAX_PHOTOS:
        await callback.answer(
            f"Достигнут общий лимит {MAX_PHOTOS} фото.",
            show_alert=True,
        )
        return
    await callback.answer()
    await state.set_state(SellStates.item_photos)
    if callback.message:
        await callback.message.answer(
            f"Отправьте фото для общего поста.\n"
            f"Общий лимит — {MAX_PHOTOS} фото.\n"
            "Когда загрузите все — нажмите «Готово».",
            reply_markup=sell_photos_done_keyboard(),
        )


@router.message(SellStates.item_photos, ~F.photo, F.chat.type == "private")
async def sell_photos_other(message: Message) -> None:
    await message.answer(
        "Отправьте фото товара или нажмите «Готово».",
        reply_markup=sell_photos_done_keyboard(),
    )


@router.message(SellStates.item_photos, F.photo, F.chat.type == "private")
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
        f"Фото добавлено. Всего фото в посте: {len(photos)}/{MAX_PHOTOS}. "
        "Отправьте ещё или нажмите «Готово».",
        reply_markup=sell_photos_done_keyboard(),
    )


@router.callback_query(SellStates.item_photos, F.data == "sell_photos_done")
async def sell_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Фото добавлены.")
    await _show_menu(callback.message, state)


@router.callback_query(SellStates.item_description, F.data == "sell_skip_desc")
async def sell_skip_description(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _finish_current_item(callback.message, state, None)


@router.message(SellStates.item_description, F.chat.type == "private")
async def sell_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    if len(desc) > 2000:
        await message.answer("Описание слишком длинное (макс. 2000 символов).")
        return
    await _finish_current_item(message, state, desc or None)


async def _finish_current_item(
    message: Message | None,
    state: FSMContext,
    description: str | None,
) -> None:
    data = await state.get_data()
    item = dict(data.get("current_item", {}))
    item["description"] = description
    items: list[dict] = list(data.get("items", []))
    items.append(item)
    await state.update_data(items=items, current_item=None)
    if message:
        await message.answer(f"Товар #{len(items)} добавлен.")
    await _show_menu(message, state)


@router.callback_query(SellStates.menu, F.data == "sell_preview")
async def sell_preview(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    items: list[dict] = data.get("items", [])
    if not items:
        await callback.answer("Сначала добавьте товар.", show_alert=True)
        return
    await callback.answer()
    settings = get_settings()
    from bot.db.models import User

    user = callback.from_user
    preview_user = User(
        telegram_id=user.id if user else 0,
        username=user.username if user else None,
        full_name=user.full_name if user else None,
    )
    caption = render_multi_sale_preview(
        items,
        currency=settings.default_currency,
        seller=preview_user,
    )
    photos: list[str] = data.get("photos", [])
    if callback.message:
        await callback.message.answer(
            f"<b>Превью объявления:</b>\n\n{caption}\n\n"
            f"<i>Фото в посте: {len(photos)} шт.</i>",
            parse_mode="HTML",
            reply_markup=sell_items_menu_keyboard(True),
        )


@router.callback_query(F.data == "sell_abort")
async def sell_abort(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Публикация отменена.")


@router.callback_query(SellStates.menu, F.data == "sell_publish")
async def sell_publish(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    data = await state.get_data()
    settings = get_settings()
    items: list[dict] = data.get("items", [])
    photos: list[str] = data.get("photos", [])

    if not items:
        await callback.answer("Добавьте хотя бы один товар.", show_alert=True)
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
            message_id, file_ids = await publish_multi_item_listing(
                callback.bot,
                group_chat_id=settings.group_chat_id,
                currency=settings.default_currency,
                items=items,
                media_file_ids=photos,
                seller=seller,
                message_thread_id=settings.sale_topic_id,
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось опубликовать в группу: {exc}\n\n"
                "Проверьте, что бот добавлен в группу с правами на отправку "
                "и редактирование сообщений, и что GROUP_CHAT_ID верный."
            )
            return

        listing = await create_multi_item_listing(
            session,
            seller_id=seller.telegram_id,
            currency=settings.default_currency,
            items=items,
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
        "При резерве отдельных товаров вы получите уведомление. "
        "Управлять лотом: /my",
        parse_mode="HTML",
    )
    await callback.message.answer(render_caption(listing), parse_mode="HTML")

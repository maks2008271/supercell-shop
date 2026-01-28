from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
from database import get_products_by_game_and_subcategory
from pathlib import Path

router = Router()

# Путь к папке с изображениями
BASE_DIR = Path(__file__).parent.parent
CATEGORY_IMAGES_DIR = BASE_DIR / "miniapp" / "static" / "images" / "categories"

# Изображения для каждой игры
GAME_IMAGES = {
    "brawlstars": "stars.png",
    "clashroyale": "royale.png",
    "clashofclans": "clans.png",
}

# ===== КОНФИГУРАЦИЯ КАТЕГОРИЙ =====
# Добавляй новые категории сюда - они автоматически появятся в боте и мини-аппе

CATEGORIES = {
    "brawlstars": {
        "name": "Brawl Stars",
        "categories": [
            {"id": "akcii", "name": "Акции", "emoji": "🔥"},
            {"id": "gems", "name": "Гемы", "emoji": "💎"},
        ]
    },
    "clashroyale": {
        "name": "Clash Royale",
        "categories": [
            {"id": "akcii", "name": "Акции", "emoji": "🔥"},
            {"id": "gems", "name": "Гемы", "emoji": "💎"},
            {"id": "geroi", "name": "Герои", "emoji": "🦸"},
            {"id": "evolutions", "name": "Эволюции", "emoji": "⚡"},
            {"id": "emoji", "name": "Эмодзи", "emoji": "😀"},
            {"id": "etapnye", "name": "Этапные", "emoji": "📈"},
            {"id": "karty", "name": "Карты", "emoji": "🃏"},
        ]
    },
    "clashofclans": {
        "name": "Clash of Clans",
        "categories": [
            {"id": "akcii", "name": "Акции", "emoji": "🔥"},
            {"id": "gems", "name": "Гемы", "emoji": "💎"},
        ]
    }
}


def get_category_name(game: str, subcategory: str) -> str:
    """Получить название категории по ID"""
    if game in CATEGORIES:
        for cat in CATEGORIES[game]["categories"]:
            if cat["id"] == subcategory:
                return cat["name"]
    return subcategory


def get_game_name(game: str) -> str:
    """Получить название игры по ID"""
    return CATEGORIES.get(game, {}).get("name", game)


def build_game_keyboard(game: str, products_all=None) -> InlineKeyboardMarkup:
    """Построить клавиатуру категорий для игры"""
    keyboard = []

    if game in CATEGORIES:
        categories = CATEGORIES[game]["categories"]
        # Размещаем по 2 кнопки в ряд
        row = []
        for cat in categories:
            btn_text = f"{cat['emoji']} {cat['name']}"
            btn = InlineKeyboardButton(
                text=btn_text,
                callback_data=f"{game}_{cat['id']}"
            )
            row.append(btn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    # Добавляем общие товары если есть
    if products_all:
        for product in products_all:
            product_id, name = product[0], product[1]
            keyboard.append([InlineKeyboardButton(
                text=name,
                callback_data=f"buy_product_{product_id}"
            )])

    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="shop")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def show_category_products(callback: CallbackQuery, game: str, subcategory: str):
    """Универсальный показ товаров категории"""
    try:
        products = await get_products_by_game_and_subcategory(game, subcategory)

        keyboard = []

        if products:
            for product in products:
                product_id, name = product[0], product[1]
                keyboard.append([InlineKeyboardButton(
                    text=name,
                    callback_data=f"buy_product_{product_id}"
                )])

        keyboard.append([InlineKeyboardButton(text="Назад", callback_data=f"category_{game}")])

        cat_name = get_category_name(game, subcategory)
        game_name = get_game_name(game)

        caption = f"{game_name} / {cat_name}\n\n"
        if subcategory == "akcii":
            caption += "Проверяйте наличие акции в игре перед покупкой!\n\n"

        if products:
            caption += "Выберите товар:"
        else:
            caption += "Товары скоро появятся!"

        # Пытаемся найти изображение для категории
        category_image_path = CATEGORY_IMAGES_DIR / game / f"{subcategory}.png"

        if category_image_path.exists():
            # Используем изображение категории
            image_path = category_image_path
        else:
            # Используем общее изображение игры
            image_filename = GAME_IMAGES.get(game)
            if image_filename:
                image_path = BASE_DIR / image_filename
            else:
                image_path = None

        if image_path and image_path.exists():
            try:
                photo = FSInputFile(str(image_path))
                await callback.message.edit_media(
                    media=InputMediaPhoto(media=photo, caption=caption),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )
                await callback.answer()
                return
            except Exception as e:
                print(f"Failed to edit media in show_category_products: {e}")

        # Если не удалось поменять изображение, просто меняем caption/text
        try:
            await callback.message.edit_caption(
                caption=caption,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        except Exception:
            try:
                await callback.message.edit_text(
                    text=caption,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )
            except Exception:
                pass
    except Exception as e:
        print(f"Error in show_category_products: {e}")
    finally:
        await callback.answer()


# ===== BRAWL STARS =====
@router.callback_query(F.data == "category_brawlstars")
async def show_brawlstars(callback: CallbackQuery):
    """Показать категории Brawl Stars"""
    products_all = await get_products_by_game_and_subcategory("brawlstars", "all")
    caption = "Brawl Stars\n\nВыберите категорию"
    keyboard = build_game_keyboard("brawlstars", products_all)

    # Загружаем изображение игры
    image_path = BASE_DIR / GAME_IMAGES["brawlstars"]
    if image_path.exists():
        try:
            photo = FSInputFile(str(image_path))
            await callback.message.edit_media(
                media=InputMediaPhoto(media=photo, caption=caption),
                reply_markup=keyboard
            )
        except:
            await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    else:
        await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("brawlstars_"))
async def show_brawlstars_category(callback: CallbackQuery):
    """Показать товары категории Brawl Stars"""
    subcategory = callback.data.replace("brawlstars_", "")
    await show_category_products(callback, "brawlstars", subcategory)


# ===== CLASH ROYALE =====
@router.callback_query(F.data == "category_clashroyale")
async def show_clashroyale(callback: CallbackQuery):
    """Показать категории Clash Royale"""
    products_all = await get_products_by_game_and_subcategory("clashroyale", "all")
    caption = "Clash Royale\n\nВыберите категорию"
    keyboard = build_game_keyboard("clashroyale", products_all)

    # Загружаем изображение игры
    image_path = BASE_DIR / GAME_IMAGES["clashroyale"]
    if image_path.exists():
        try:
            photo = FSInputFile(str(image_path))
            await callback.message.edit_media(
                media=InputMediaPhoto(media=photo, caption=caption),
                reply_markup=keyboard
            )
        except:
            await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    else:
        await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("clashroyale_"))
async def show_clashroyale_category(callback: CallbackQuery):
    """Показать товары категории Clash Royale"""
    subcategory = callback.data.replace("clashroyale_", "")
    await show_category_products(callback, "clashroyale", subcategory)


# ===== CLASH OF CLANS =====
@router.callback_query(F.data == "category_clashofclans")
async def show_clashofclans(callback: CallbackQuery):
    """Показать категории Clash of Clans"""
    products_all = await get_products_by_game_and_subcategory("clashofclans", "all")
    caption = "Clash of Clans\n\nВыберите категорию"
    keyboard = build_game_keyboard("clashofclans", products_all)

    # Загружаем изображение игры
    image_path = BASE_DIR / GAME_IMAGES["clashofclans"]
    if image_path.exists():
        try:
            photo = FSInputFile(str(image_path))
            await callback.message.edit_media(
                media=InputMediaPhoto(media=photo, caption=caption),
                reply_markup=keyboard
            )
        except:
            await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    else:
        await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("clashofclans_"))
async def show_clashofclans_category(callback: CallbackQuery):
    """Показать товары категории Clash of Clans"""
    subcategory = callback.data.replace("clashofclans_", "")
    await show_category_products(callback, "clashofclans", subcategory)


# ===== ЗАГЛУШКИ =====
@router.callback_query(F.data == "coming_soon")
async def coming_soon(callback: CallbackQuery):
    await callback.answer("Скоро будет доступно!", show_alert=True)


@router.callback_query(F.data.startswith("category_"))
async def show_other_categories(callback: CallbackQuery):
    """Показать остальные категории (заглушка)"""
    category = callback.data.replace("category_", "")

    if category not in CATEGORIES:
        await callback.answer("Эта игра скоро будет доступна!", show_alert=True)

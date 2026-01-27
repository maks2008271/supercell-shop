from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_all_products, add_sample_products
from keyboards import get_back_to_menu

router = Router()


@router.callback_query(F.data == "products")
async def show_all_products(callback: CallbackQuery):
    """Показать все товары"""
    # Добавляем примеры товаров, если их нет
    await add_sample_products()

    products = await get_all_products()

    if not products:
        text = "📦 <b>Товары</b>\n\n❌ В данный момент товаров нет в наличии"
    else:
        text = "📦 <b>Доступные товары</b>\n\n"
        for product in products[:10]:  # Показываем первые 10 товаров
            product_id, name, description, price, category, in_stock, image_url, created_at = product
            text += f"🔸 <b>{name}</b>\n"
            text += f"💰 Цена: {price:.2f} ₽\n"
            if description:
                text += f"📝 {description}\n"
            text += "\n"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_back_to_menu()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery):
    """Показать товары по категории"""
    category = callback.data.split("_")[1]

    # Добавляем примеры товаров, если их нет
    await add_sample_products()

    products = await get_all_products(category=category)

    category_names = {
        "donate": "💎 Донат",
        "currency": "🎮 Игровые валюты",
        "gifts": "🎁 Подарки"
    }

    category_name = category_names.get(category, "Товары")

    if not products:
        text = f"<b>{category_name}</b>\n\n❌ В данной категории товаров пока нет"
    else:
        text = f"<b>{category_name}</b>\n\n"
        for product in products:
            product_id, name, description, price, cat, in_stock, image_url, created_at = product
            text += f"🔸 <b>{name}</b>\n"
            text += f"💰 Цена: {price:.2f} ₽\n"
            if description:
                text += f"📝 {description}\n"
            text += "\n"

    # Кнопка назад к категориям
    keyboard = [
        [InlineKeyboardButton(text="🔙 К категориям", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ]

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

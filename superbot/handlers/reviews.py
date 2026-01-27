from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import REVIEWS_CHANNEL
from keyboards import get_back_to_menu

router = Router()


@router.callback_query(F.data == "reviews")
async def show_reviews(callback: CallbackQuery):
    """Показать отзывы"""
    keyboard = [
        [InlineKeyboardButton(text="Перейти к отзывам", url=REVIEWS_CHANNEL)],
        [InlineKeyboardButton(text="Назад", callback_data="main_menu")]
    ]

    await callback.message.edit_caption(
        caption="Отзывы наших клиентов\n\n"
                "Мы ценим каждого клиента!\n\n"
                "⭐️ Более 1000+ довольных покупателей\n"
                "💬 Реальные отзывы в нашем канале\n"
                "✅ Гарантия качества и безопасности\n\n"
                "Перейдите в наш канал с отзывами, чтобы увидеть мнения других покупателей:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

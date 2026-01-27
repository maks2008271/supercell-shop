from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_back_to_menu
from config import SUPPORT_URL, OFFER_URL

router = Router()


@router.callback_query(F.data == "support")
async def show_support(callback: CallbackQuery):
    """Показать информацию о поддержке"""
    keyboard = [
        [InlineKeyboardButton(text="Написать в поддержку", url=SUPPORT_URL)],
        [InlineKeyboardButton(text="Оферта обслуживания", url=OFFER_URL)],
        [InlineKeyboardButton(text="Назад", callback_data="main_menu")]
    ]

    await callback.message.edit_caption(
        caption="Поддержка 24/7\n\n"
                "Если у вас возникла проблема или любой интересующий вас вопрос, обратитесь в поддержку - \n"
                "Мы обработаем ваш запрос максимально быстро ❤️",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from keyboards import get_back_to_menu, get_product_categories

router = Router()


@router.callback_query(F.data == "shop")
async def show_shop(callback: CallbackQuery):
    """Показать магазин"""
    try:
        await callback.message.edit_caption(
            caption="Выберите категорию 👇",
            reply_markup=get_product_categories()
        )
        await callback.answer()
    except Exception:
        # Message is already the same or can't be edited
        await callback.answer()

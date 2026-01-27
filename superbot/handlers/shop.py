from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from keyboards import get_back_to_menu, get_product_categories
from pathlib import Path

router = Router()

# Путь к главному изображению
BASE_DIR = Path(__file__).parent.parent
MAIN_IMAGE_PATH = BASE_DIR / "main.png"


@router.callback_query(F.data == "shop")
async def show_shop(callback: CallbackQuery):
    """Показать магазин"""
    try:
        # Пытаемся вернуть главное изображение
        if MAIN_IMAGE_PATH.exists():
            photo = FSInputFile(str(MAIN_IMAGE_PATH))
            await callback.message.edit_media(
                media=InputMediaPhoto(media=photo, caption="Выберите категорию 👇"),
                reply_markup=get_product_categories()
            )
        else:
            # Если файла нет, просто меняем caption
            await callback.message.edit_caption(
                caption="Выберите категорию 👇",
                reply_markup=get_product_categories()
            )
    except Exception as e:
        # Если не получилось, пытаемся изменить текст
        try:
            await callback.message.edit_text(
                text="Выберите категорию 👇",
                reply_markup=get_product_categories()
            )
        except Exception:
            # Если и это не помогло, логируем ошибку
            print(f"Error in show_shop: {e}")

    await callback.answer()

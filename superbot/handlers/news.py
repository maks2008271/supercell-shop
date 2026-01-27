from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import NEWS_CHANNEL
from keyboards import get_back_to_menu

router = Router()


@router.callback_query(F.data == "news")
async def show_news(callback: CallbackQuery):
    """Показать новостной канал"""
    # Формируем URL канала
    if NEWS_CHANNEL.startswith("@"):
        channel_url = f"https://t.me/{NEWS_CHANNEL.replace('@', '')}"
    elif NEWS_CHANNEL.startswith("https://"):
        channel_url = NEWS_CHANNEL
    else:
        channel_url = f"https://t.me/{NEWS_CHANNEL}"

    keyboard = [
        [InlineKeyboardButton(text="📢 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton(text="Назад", callback_data="main_menu")]
    ]

    caption = (
        "Новостной канал Supercell Shop\n\n"
        "Будьте в курсе всех новостей и обновлений!\n\n"
        "- Актуальные новости магазина\n"
        "- Информация о новых товарах\n"
        "- Специальные акции и скидки\n"
        "- Важные объявления\n\n"
        "Подпишитесь, чтобы не пропустить ничего важного:"
    )

    try:
        await callback.message.edit_caption(
            caption=caption,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except:
        await callback.message.edit_text(
            text=caption,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    await callback.answer()

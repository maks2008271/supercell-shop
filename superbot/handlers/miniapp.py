from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

router = Router()


@router.callback_query(F.data == "open_miniapp")
async def open_miniapp(callback: CallbackQuery):
    """Открыть Mini App"""
    # URL вашего Mini App
    # Для ngrok: "https://abc123.ngrok.io"
    # Для Railway/Vercel: "https://ваш-домен.com"
    webapp_url = "https://supercellshop.xyz"  # ngrok URL

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Открыть магазин", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="Назад", callback_data="main_menu")]
    ])

    try:
        await callback.message.edit_caption(
            caption="🌟 Bubs Shop Mini App 🌟\n\n"
                    "Откройте наш удобный магазин прямо в Telegram!\n\n"
                    "✨ Удобный каталог товаров\n"
                    "🔍 Быстрый поиск\n"
                    "💳 Покупка в один клик\n"
                    "📱 Красивый интерфейс",
            reply_markup=keyboard
        )
    except:
        await callback.message.edit_text(
            text="🌟 Bubs Shop Mini App 🌟\n\n"
                 "Откройте наш удобный магазин прямо в Telegram!\n\n"
                 "✨ Удобный каталог товаров\n"
                 "🔍 Быстрый поиск\n"
                 "💳 Покупка в один клик\n"
                 "📱 Красивый интерфейс",
            reply_markup=keyboard
        )

    await callback.answer()

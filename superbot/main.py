import asyncio
import logging
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database import init_db, get_or_create_user, register_referral_visit, get_referral_link_by_code
from keyboards import get_main_menu, get_back_to_menu
from handlers import profile, support, reviews, products, shop, news, categories, admin, purchase, orders_admin, miniapp
from miniapp.wata_payment import WataPaymentClient



# Получаем путь к директории, где находится этот файл
BASE_DIR = Path(__file__).parent

# Настройка подробного логирования
logging.basicConfig(
    level=logging.DEBUG,  # Включаем DEBUG уровень
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('/tmp/bot_debug.log', encoding='utf-8')  # Вывод в файл
    ]
)

# Устанавливаем DEBUG уровень для aiogram
logging.getLogger('aiogram').setLevel(logging.DEBUG)
logging.getLogger('aiogram.event').setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# Rate Limiting - защита от спама
_rate_limit_storage = defaultdict(list)
RATE_LIMIT_MESSAGES = 30  # Максимум сообщений
RATE_LIMIT_PERIOD = 60  # За период в секундах


def check_rate_limit(user_id: int) -> bool:
    """Проверка лимита запросов пользователя"""
    now = datetime.now()
    # Очищаем старые запросы
    _rate_limit_storage[user_id] = [
        timestamp for timestamp in _rate_limit_storage[user_id]
        if now - timestamp < timedelta(seconds=RATE_LIMIT_PERIOD)
    ]

    # Проверяем лимит
    if len(_rate_limit_storage[user_id]) >= RATE_LIMIT_MESSAGES:
        return False

    # Добавляем текущий запрос
    _rate_limit_storage[user_id].append(now)
    return True

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    logger.info(f"START command from user {user_id} (@{message.from_user.username})")

    # Проверка rate limit
    if not check_rate_limit(user_id):
        logger.warning(f"Rate limit exceeded for user {user_id}")
        await message.answer("Вы отправляете запросы слишком часто. Пожалуйста, подождите минуту.")
        return

    try:
        # Получаем или создаем пользователя
        username = message.from_user.username or ""
        first_name = message.from_user.first_name
        logger.debug(f"Creating/getting user: {user_id}, username: {username}, name: {first_name}")
        await get_or_create_user(user_id, username, first_name)
        logger.debug(f"User {user_id} created/retrieved successfully")
    except Exception as e:
        logger.error(f"Ошибка при создании пользователя {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
        return

    # Проверяем, есть ли реферальный код в команде
    args = message.text.split()
    if len(args) > 1:
        referral_code = args[1]
        # Проверяем, существует ли такая реферальная ссылка
        link = await get_referral_link_by_code(referral_code)
        if link:
            # Регистрируем переход
            await register_referral_visit(referral_code, user_id)

    # Используем абсолютный путь к файлу
    photo_path = BASE_DIR / "main.png"

    if photo_path.exists():
        photo = FSInputFile(str(photo_path))
        await message.answer_photo(
            photo=photo,
            caption="👋 Приветствуем тебя в Supercell Shop!\n\n"
                    "Самые низкие цены и безопасный донат ждут тебя!\n"
                    "Воспользуйся кнопками ниже 👇",
            reply_markup=get_main_menu()
        )
    else:
        # Если файл не найден, отправляем без фото
        await message.answer(
            text="👋 Приветствуем тебя в Supercell Shop!\n\n"
                 "Самые низкие цены и безопасный донат ждут тебя!\n"
                 "Воспользуйся кнопками ниже 👇",
            reply_markup=get_main_menu()
        )


@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    # Проверка rate limit
    if not check_rate_limit(callback.from_user.id):
        await callback.answer("Слишком много запросов. Подождите минуту.", show_alert=True)
        return

    caption_text = ("👋 Приветствуем тебя в Supercell Shop!\n\n"
                    "Самые низкие цены и безопасный донат ждут тебя!\n"
                    "Воспользуйся кнопками ниже 👇")

    photo_path = BASE_DIR / "main.png"

    try:
        # Пытаемся отредактировать caption (если это уже фото)
        await callback.message.edit_caption(
            caption=caption_text,
            reply_markup=get_main_menu()
        )
    except Exception as e:
        # Если не получилось (сообщение без фото), используем edit_media
        try:
            if photo_path.exists():
                photo = FSInputFile(str(photo_path))
                await callback.message.edit_media(
                    media=InputMediaPhoto(media=photo, caption=caption_text),
                    reply_markup=get_main_menu()
                )
            else:
                # Если фото не найдено, просто редактируем текст
                await callback.message.edit_text(
                    text=caption_text,
                    reply_markup=get_main_menu()
                )
        except Exception as inner_e:
            logger.error(f"Ошибка при возврате в меню: {inner_e}")
    await callback.answer()


async def main():
    """Главная функция запуска бота"""
    try:
        # Инициализация базы данных с пулом соединений
        logger.info("Инициализация базы данных...")
        await init_db()
        logger.info("База данных инициализирована успешно!")

        # Регистрация роутеров
        dp.include_router(admin.router)  # Админ-панель первой
        dp.include_router(orders_admin.router)  # Управление заказами
        dp.include_router(purchase.router)  # Покупка товаров
        dp.include_router(miniapp.router)  # Mini App
        dp.include_router(shop.router)
        dp.include_router(categories.router)
        dp.include_router(profile.router)
        dp.include_router(support.router)
        dp.include_router(reviews.router)
        dp.include_router(news.router)
        dp.include_router(products.router)

        logger.info("Бот запущен! Готов обрабатывать 1000+ запросов в минуту")
        logger.info("Активированы оптимизации:")
        logger.info("  - Пул соединений к БД (20 подключений)")
        logger.info("  - Кэширование данных пользователей и товаров")
        logger.info("  - Rate limiting (30 запросов/минуту на пользователя)")
        logger.info("  - WAL режим SQLite для параллельной работы")

        # Запуск бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

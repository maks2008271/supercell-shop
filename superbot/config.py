import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройки базы данных (используем абсолютный путь)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(_BASE_DIR, "shop_bot.db")

# ID администраторов (для поддержки)
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# Канал с отзывами
REVIEWS_CHANNEL = os.getenv("REVIEWS_CHANNEL", "https://t.me/SupercellShopreviews")

# Новостной канал
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "@your_news_channel")

# Ссылка на поддержку
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/Supercellshop_abmin")

# Ссылка на оферту обслуживания
OFFER_URL = os.getenv("OFFER_URL", "https://telegra.ph/Oferta-obsluzhivaniya-01-19")

# Медиа файлы для категорий
CATEGORY_MEDIA = {
    "brawlstars": os.getenv("CATEGORY_BRAWLSTARS_MEDIA", "main.png"),
    "clashroyale": os.getenv("CATEGORY_CLASHROYALE_MEDIA", "main.png"),
    "clashofclans": os.getenv("CATEGORY_CLASHOFCLANS_MEDIA", "main.png"),
}

# Supercell Shop Bot

Telegram бот-магазин для продажи игровых товаров Supercell (Brawl Stars, Clash Royale, Clash of Clans).

## Структура проекта

```
├── main.py                 # Точка входа бота
├── config.py               # Конфигурация (читает .env)
├── database.py             # Работа с SQLite
├── keyboards.py            # Клавиатуры бота
│
├── handlers/               # Обработчики команд
│   ├── admin.py            # Админ-панель (/admin)
│   ├── categories.py       # Категории товаров
│   ├── shop.py             # Магазин в боте
│   ├── profile.py          # Профиль пользователя
│   ├── support.py          # Поддержка
│   ├── purchase.py         # Покупка товаров
│   ├── orders_admin.py     # Управление заказами
│   └── ...
│
├── miniapp/                # Telegram Mini App
│   ├── api.py              # FastAPI сервер
│   ├── wata_payment.py     # Интеграция оплаты wata.pro
│   ├── templates/
│   │   └── index.html      # HTML страница
│   └── static/
│       ├── css/style.css   # Стили
│       └── js/app.js       # JavaScript
│
└── deploy/                 # Файлы для деплоя
    ├── setup.sh            # Скрипт установки
    ├── nginx.conf          # Конфиг Nginx
    ├── supercell-bot.service
    └── supercell-api.service
```

## Быстрый старт

### 1. Установка зависимостей
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка
```bash
cp .env.example .env
# Отредактируй .env - добавь BOT_TOKEN и другие данные
```

### 3. Запуск (разработка)
```bash
# Терминал 1 - бот
python main.py

# Терминал 2 - Mini App API
cd miniapp && uvicorn api:app --reload --port 8000

# Терминал 3 - ngrok (для тестирования Mini App)
ngrok http 8000
```

## Ключевые файлы

### Категории товаров
Категории определены в 3 местах (синхронизируй при изменении):
- `handlers/categories.py` - CATEGORIES dict
- `handlers/admin.py` - GAME_CATEGORIES (в функции select_game_for_product)
- `miniapp/static/js/app.js` - displayCategories()

### Добавление новой категории
1. Добавь в `handlers/categories.py`:
```python
CATEGORIES = {
    "brawlstars": {
        "categories": [
            {"id": "new_cat", "name": "Новая", "emoji": "🆕"},
            ...
        ]
    }
}
```

2. Добавь в `handlers/admin.py` GAME_CATEGORIES

3. Добавь в `miniapp/static/js/app.js`:
   - `getCategoryName()`
   - `displayCategories()`

## API эндпоинты (Mini App)

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/products?game=X&subcategory=Y` | Список товаров |
| GET | `/api/product/{id}` | Товар по ID |
| GET | `/api/user/{id}` | Профиль пользователя |
| POST | `/api/purchase` | Создать заказ |
| GET | `/api/search?q=X` | Поиск товаров |

## База данных (SQLite)

Таблицы:
- `users` - пользователи
- `products` - товары
- `orders` - заказы
- `referral_links` - реферальные ссылки
- `referral_visits` - переходы по ссылкам

## Деплой на Timeweb VPS

```bash
# На сервере
sudo ./deploy/setup.sh

# После установки
sudo systemctl start supercell-bot
sudo systemctl start supercell-api
```

## Переменные окружения (.env)

```
BOT_TOKEN=           # Токен от @BotFather
ADMIN_IDS=           # ID админов через запятую
WEBHOOK_BASE_URL=    # URL для Mini App (домен)
WATA_API_TOKEN=      # Токен wata.pro (опционально)
```

## Контакты

Разработано для Supercell Shop.

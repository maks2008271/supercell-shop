from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import ADMIN_IDS
from database import (
    get_stats_users, get_stats_revenue, get_stats_sales_by_game,
    get_all_users_ids, add_product, get_products_by_game_and_subcategory,
    update_product, delete_product, get_all_products_admin, get_product_by_id,
    create_referral_link, get_all_referral_links, get_referral_stats, delete_referral_link,
    get_all_users, search_user_by_id, get_user_full_stats,
    search_user_by_uid, get_user_uid
)
import json
import asyncio
import aiosqlite

router = Router()


# FSM для рассылки
class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirm_broadcast = State()


# FSM для добавления товара
class AddProductStates(StatesGroup):
    select_game = State()
    select_subcategory = State()
    enter_name = State()
    enter_description = State()
    enter_price = State()
    upload_image = State()  # Новое состояние для загрузки изображения


# FSM для редактирования товара
class EditProductStates(StatesGroup):
    select_game = State()
    select_subcategory = State()
    select_product = State()
    edit_menu = State()
    edit_name = State()
    edit_description = State()
    edit_price = State()


# FSM для создания реферальной ссылки
class CreateReferralStates(StatesGroup):
    enter_code = State()
    enter_name = State()


# FSM для управления пользователями
class UserManagementStates(StatesGroup):
    search_user = State()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


def get_admin_menu() -> InlineKeyboardMarkup:
    """Главное меню админ-панели"""
    keyboard = [
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="Трекинг ссылка", callback_data="admin_tracking")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Управление товарами", callback_data="admin_products")],
        [InlineKeyboardButton(text="Управление пользователями", callback_data="admin_users")],
        [InlineKeyboardButton(text="Назад в главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда /admin для входа в админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к админ-панели")
        return

    await message.answer(
        "Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_menu()
    )


@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    """Показать админ-панель"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def show_all_stats(callback: CallbackQuery):
    """Показать всю статистику в одном окне"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    # Получаем статистику по пользователям
    users_total = await get_stats_users("all")
    users_today = await get_stats_users("today")
    users_week = await get_stats_users("7days")

    # Получаем статистику по обороту
    revenue_total = await get_stats_revenue("all")
    revenue_today = await get_stats_revenue("today")
    revenue_week = await get_stats_revenue("7days")

    # Получаем статистику по играм
    games = {
        "brawlstars": "Brawl Stars",
        "clashroyale": "Clash Royale",
        "clashofclans": "Clash of Clans"
    }

    games_text = ""
    for game_id, game_name in games.items():
        total = await get_stats_sales_by_game(game_id, "all")
        today = await get_stats_sales_by_game(game_id, "today")

        games_text += f"{game_name}: {total['count']} шт / {total['revenue']:.0f} ₽\n"

    text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователи:\n"
        f"Всего: {users_total}\n"
        f"Сегодня: {users_today}\n"
        f"За 7 дней: {users_week}\n\n"
        f"💰 Оборот:\n"
        f"Всего: {revenue_total:.0f} ₽\n"
        f"Сегодня: {revenue_today:.0f} ₽\n"
        f"За 7 дней: {revenue_week:.0f} ₽\n\n"
        f"🎮 Продажи по играм:\n"
        f"{games_text}"
    )

    keyboard = [[InlineKeyboardButton(text="Назад", callback_data="admin_panel")]]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_tracking")
async def show_referral_links(callback: CallbackQuery):
    """Показать управление реферальными ссылками"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    # Получаем все реферальные ссылки
    links = await get_all_referral_links()

    # Получаем username бота
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username

    keyboard = []

    # Добавляем кнопки для каждой ссылки
    for link in links:
        code, name, created_at = link
        # Получаем статистику по ссылке
        stats = await get_referral_stats(code)
        keyboard.append([InlineKeyboardButton(
            text=f"🔗 {name} ({stats['users_total']} пер.)",
            callback_data=f"refstats_{code}"
        )])

    # Кнопка создания новой ссылки
    keyboard.append([InlineKeyboardButton(text="➕ Создать ссылку", callback_data="create_referral")])
    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="admin_panel")])

    if links:
        text = "🔗 Управление реферальными ссылками\n\nВыберите ссылку для просмотра статистики:"
    else:
        text = "🔗 Управление реферальными ссылками\n\nУ вас пока нет реферальных ссылок.\nНажмите 'Создать ссылку' чтобы добавить."

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("refstats_"))
async def show_referral_stats_handler(callback: CallbackQuery):
    """Показать статистику по реферальной ссылке"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    code = callback.data.replace("refstats_", "")
    stats = await get_referral_stats(code)

    # Получаем username бота для формирования ссылки
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    link = f"https://t.me/{bot_username}?start={code}"

    text = (
        f"📊 Статистика реферальной ссылки\n\n"
        f"🔗 Ссылка: {link}\n\n"
        f"👥 Пользователи:\n"
        f"Всего: {stats['users_total']}\n"
        f"Сегодня: {stats['users_today']}\n"
        f"За 7 дней: {stats['users_week']}\n\n"
        f"💰 Оборот:\n"
        f"Всего: {stats['revenue_total']:.0f} ₽\n"
        f"Сегодня: {stats['revenue_today']:.0f} ₽\n"
        f"За 7 дней: {stats['revenue_week']:.0f} ₽\n\n"
        f"📦 Заказы:\n"
        f"Всего: {stats['orders_total']} шт\n"
        f"Сегодня: {stats['orders_today']} шт\n"
        f"За 7 дней: {stats['orders_week']} шт"
    )

    keyboard = [
        [InlineKeyboardButton(text="🗑 Удалить ссылку", callback_data=f"delref_{code}")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_tracking")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delref_"))
async def delete_referral_handler(callback: CallbackQuery):
    """Показать подтверждение удаления реферальной ссылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    code = callback.data.replace("delref_", "")

    keyboard = [
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirmdelref_{code}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"refstats_{code}")]
    ]

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить эту реферальную ссылку?\n\n"
        "Все данные статистики будут сохранены, но ссылка перестанет работать.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirmdelref_"))
async def confirm_delete_referral(callback: CallbackQuery):
    """Подтверждение удаления реферальной ссылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    code = callback.data.replace("confirmdelref_", "")
    await delete_referral_link(code)

    await callback.answer("Ссылка удалена", show_alert=True)
    await show_referral_links(callback)


@router.callback_query(F.data == "create_referral")
async def start_create_referral(callback: CallbackQuery, state: FSMContext):
    """Начать создание реферальной ссылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create_ref")]]

    await callback.message.edit_text(
        "Создание реферальной ссылки\n\n"
        "Введите уникальный код для ссылки (латиница, цифры):\n\n"
        "Пример: promo1, sale2024, vk",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(CreateReferralStates.enter_code)
    await callback.answer()


@router.callback_query(F.data == "cancel_create_ref")
async def cancel_create_referral_callback(callback: CallbackQuery, state: FSMContext):
    """Отменить создание реферальной ссылки через кнопку"""
    await state.clear()
    await callback.answer("Создание ссылки отменено")
    await show_referral_links(callback)


@router.message(CreateReferralStates.enter_code, F.text == "/cancel")
@router.message(CreateReferralStates.enter_name, F.text == "/cancel")
async def cancel_create_referral(message: Message, state: FSMContext):
    """Отменить создание реферальной ссылки"""
    await state.clear()
    await message.answer(
        "Создание ссылки отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="admin_tracking")]
        ])
    )


@router.message(CreateReferralStates.enter_code, F.text)
async def enter_referral_code(message: Message, state: FSMContext):
    """Ввести код реферальной ссылки"""
    code = message.text.strip().lower()

    # Проверяем, что код содержит только латиницу и цифры
    if not code.replace("_", "").isalnum():
        await message.answer("Код может содержать только латинские буквы, цифры и подчеркивание. Попробуйте еще раз:")
        return

    await state.update_data(code=code)

    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create_ref")]]

    await message.answer(
        "Введите название для ссылки (для удобства):\n\n"
        "Пример: Промо ВК, Реклама в ТГ, Скидка 10%",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(CreateReferralStates.enter_name)


@router.message(CreateReferralStates.enter_name, F.text)
async def enter_referral_name(message: Message, state: FSMContext):
    """Ввести название реферальной ссылки и создать её"""
    name = message.text.strip()
    data = await state.get_data()
    code = data["code"]

    # Создаем ссылку
    success = await create_referral_link(code, name)

    if not success:
        await message.answer(
            "❌ Ошибка: код уже используется. Выберите другой код.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="admin_tracking")]
            ])
        )
        await state.clear()
        return

    # Получаем username бота для формирования ссылки
    bot_info = await message.bot.get_me()
    bot_username = bot_info.username
    link = f"https://t.me/{bot_username}?start={code}"

    await message.answer(
        f"✅ Реферальная ссылка создана!\n\n"
        f"Название: {name}\n"
        f"Код: {code}\n"
        f"Ссылка: {link}\n\n"
        f"Все пользователи, перешедшие по этой ссылке, будут отслеживаться в статистике.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад к ссылкам", callback_data="admin_tracking")]
        ])
    )
    await state.clear()


# ===== РАССЫЛКА =====

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начать создание рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]]

    await callback.message.edit_text(
        "Отправьте готовый пост\n\n"
        "Бот поддерживает inline-кнопки, media-файлы\n\n"
        "Для добавления кнопок используйте формат:\n"
        "[[Текст|url]]\n"
        "Пример: [[Перейти|https://example.com]]",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()


@router.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    """Отменить рассылку через кнопку"""
    await state.clear()
    await callback.answer("Рассылка отменена")
    await callback.message.edit_text(
        "Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_menu()
    )


@router.message(BroadcastStates.waiting_for_message, F.text == "/cancel")
@router.message(BroadcastStates.confirm_broadcast, F.text == "/cancel")
async def cancel_broadcast(message: Message, state: FSMContext):
    """Отменить рассылку"""
    await state.clear()
    await message.answer(
        "Рассылка отменена",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin_panel")]
        ])
    )


@router.message(BroadcastStates.waiting_for_message)
async def receive_broadcast_message(message: Message, state: FSMContext):
    """Получить сообщение для рассылки"""
    # Сохраняем данные сообщения
    data = {
        "text": message.html_text if message.text else message.caption,
        "photo": message.photo[-1].file_id if message.photo else None,
        "entities": message.entities or message.caption_entities,
    }

    # Парсим inline-кнопки из текста
    keyboard = None
    if data["text"] and "[[" in data["text"]:
        buttons = []
        import re
        pattern = r'\[\[([^\|]+)\|([^\]]+)\]\]'
        matches = re.findall(pattern, data["text"])

        for text, url in matches:
            buttons.append([InlineKeyboardButton(text=text.strip(), url=url.strip())])

        if buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            # Убираем кнопки из текста
            data["text"] = re.sub(pattern, '', data["text"]).strip()

    await state.update_data(**data, keyboard=keyboard)

    # Показываем превью
    preview_text = f"Превью рассылки:\n\n{'-'*30}\n"

    try:
        if data["photo"]:
            await message.answer_photo(
                photo=data["photo"],
                caption=f"{preview_text}{data['text']}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"{preview_text}{data['text']}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception as e:
        await message.answer(f"Ошибка при создании превью: {e}")
        await state.clear()
        return

    # Спрашиваем подтверждение
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_broadcast_yes"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_broadcast_no")
        ]
    ])

    users_count = len(await get_all_users_ids())
    await message.answer(
        f"Отправить рассылку {users_count} пользователям?",
        reply_markup=confirm_kb
    )

    await state.set_state(BroadcastStates.confirm_broadcast)


@router.callback_query(F.data == "confirm_broadcast_no")
async def cancel_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    """Отменить рассылку"""
    await state.clear()
    await callback.message.edit_text(
        "Рассылка отменена",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin_panel")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_broadcast_yes")
async def send_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отправить рассылку"""
    data = await state.get_data()
    users_ids = await get_all_users_ids()

    await callback.message.edit_text("Начинаю рассылку...")
    await callback.answer()

    success_count = 0
    fail_count = 0

    for user_id in users_ids:
        try:
            if data.get("photo"):
                await callback.bot.send_photo(
                    chat_id=user_id,
                    photo=data["photo"],
                    caption=data["text"],
                    reply_markup=data.get("keyboard"),
                    parse_mode="HTML"
                )
            else:
                await callback.bot.send_message(
                    chat_id=user_id,
                    text=data["text"],
                    reply_markup=data.get("keyboard"),
                    parse_mode="HTML"
                )
            success_count += 1
            await asyncio.sleep(0.05)  # Задержка между сообщениями
        except Exception:
            fail_count += 1
            continue

    await state.clear()

    await callback.message.edit_text(
        f"Рассылка завершена!\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Ошибок: {fail_count}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin_panel")]
        ])
    )


# ===== УПРАВЛЕНИЕ ТОВАРАМИ =====

@router.callback_query(F.data == "admin_products")
async def show_products_menu(callback: CallbackQuery):
    """Показать меню управления товарами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="product_add")],
        [InlineKeyboardButton(text="📋 Управление товарами", callback_data="product_manage")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_panel")]
    ]

    await callback.message.edit_text(
        "Управление товарами\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# ===== УПРАВЛЕНИЕ ТОВАРАМИ (РЕДАКТИРОВАНИЕ) =====

@router.callback_query(F.data == "product_manage")
async def start_manage_products(callback: CallbackQuery, state: FSMContext):
    """Начать управление товарами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text="Brawl Stars", callback_data="manageprod_brawlstars")],
        [InlineKeyboardButton(text="Clash Royale", callback_data="manageprod_clashroyale")],
        [InlineKeyboardButton(text="Clash of Clans", callback_data="manageprod_clashofclans")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin_products")]
    ]

    await callback.message.edit_text(
        "Управление товарами\n\nВыберите игру:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(EditProductStates.select_game)
    await callback.answer()


@router.callback_query(F.data.startswith("manageprod_"), EditProductStates.select_game)
async def manage_select_game(callback: CallbackQuery, state: FSMContext):
    """Выбрать игру для управления"""
    game = callback.data.replace("manageprod_", "")
    await state.update_data(game=game)

    # Категории синхронизированы с GAME_CATEGORIES
    MANAGE_CATEGORIES = {
        "brawlstars": [
            ("all", "Общее"),
            ("akcii", "Акции"),
            ("gems", "Гемы"),
        ],
        "clashroyale": [
            ("all", "Общее"),
            ("akcii", "Акции"),
            ("gems", "Гемы"),
            ("geroi", "Герои"),
            ("evolutions", "Эволюции"),
            ("emoji", "Эмодзи"),
            ("etapnye", "Этапные"),
            ("karty", "Карты"),
        ],
        "clashofclans": [
            ("all", "Общее"),
            ("akcii", "Акции"),
            ("gems", "Гемы"),
            ("oformlenie", "Оформление"),
        ]
    }

    categories = MANAGE_CATEGORIES.get(game, [])
    keyboard = []
    for cat_id, cat_name in categories:
        keyboard.append([InlineKeyboardButton(text=cat_name, callback_data=f"managesubcat_{cat_id}")])
    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data="admin_products")])

    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(EditProductStates.select_subcategory)
    await callback.answer()


@router.callback_query(F.data.startswith("managesubcat_"), EditProductStates.select_subcategory)
async def manage_select_subcategory(callback: CallbackQuery, state: FSMContext):
    """Выбрать подкатегорию и показать товары"""
    subcategory = callback.data.replace("managesubcat_", "")
    data = await state.get_data()
    game = data["game"]

    await state.update_data(subcategory=subcategory)

    # Получаем товары
    products = await get_products_by_game_and_subcategory(game, subcategory)

    if not products:
        keyboard = [[InlineKeyboardButton(text="Назад", callback_data=f"manageprod_{game}")]]
        await callback.message.edit_text(
            "В этой категории нет товаров",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(EditProductStates.select_game)
        await callback.answer()
        return

    keyboard = []
    for product in products:
        # product: (id, name, description, price, game, subcategory, in_stock, image_file_id, created_at, image_path)
        product_id = product[0]
        name = product[1]
        price = product[3]
        in_stock = product[6]
        status = "✅" if in_stock else "❌"
        keyboard.append([InlineKeyboardButton(
            text=f"{status} {name} - {price:.0f} ₽",
            callback_data=f"editprod_{product_id}"
        )])

    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data="admin_products")])

    await callback.message.edit_text(
        "Выберите товар для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(EditProductStates.select_product)
    await callback.answer()


async def _show_edit_menu_internal(callback: CallbackQuery, state: FSMContext, product_id: int):
    """Внутренняя функция для показа меню редактирования товара"""
    await state.update_data(product_id=product_id)

    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        await state.clear()
        return

    # product: (id, name, description, price, game, subcategory, in_stock, created_at)
    name, description, price, game, subcategory, in_stock = product[1], product[2], product[3], product[4], product[5], product[6]

    status_text = "Показан" if in_stock else "Скрыт"
    toggle_text = "🙈 Скрыть" if in_stock else "👁 Показать"

    text = (
        f"📦 Товар #{product_id}\n\n"
        f"Название: {name}\n"
        f"Описание: {description}\n"
        f"Цена: {price:.2f} ₽\n"
        f"Статус: {status_text}"
    )

    keyboard = [
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"edit_name_{product_id}")],
        [InlineKeyboardButton(text="📝 Изменить описание", callback_data=f"edit_desc_{product_id}")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"edit_price_{product_id}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"toggle_visibility_{product_id}")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"delete_prod_{product_id}")],
        [InlineKeyboardButton(text="Назад", callback_data=f"managesubcat_{subcategory}")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(EditProductStates.edit_menu)
    await callback.answer()


@router.callback_query(F.data.startswith("editprod_"), EditProductStates.select_product)
async def show_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Показать меню редактирования товара"""
    product_id = int(callback.data.replace("editprod_", ""))
    await _show_edit_menu_internal(callback, state, product_id)


@router.callback_query(F.data.startswith("backtoprod_"))
async def back_to_product(callback: CallbackQuery, state: FSMContext):
    """Вернуться к редактированию товара после изменений"""
    product_id = int(callback.data.replace("backtoprod_", ""))
    await state.set_state(EditProductStates.edit_menu)
    await _show_edit_menu_internal(callback, state, product_id)


@router.callback_query(F.data.startswith("managesubcat_"), EditProductStates.edit_menu)
async def back_to_category_from_edit(callback: CallbackQuery, state: FSMContext):
    """Вернуться к списку товаров категории из меню редактирования"""
    subcategory = callback.data.replace("managesubcat_", "")
    data = await state.get_data()
    game = data.get("game")

    if not game:
        await callback.answer("Ошибка: игра не найдена", show_alert=True)
        await state.clear()
        return

    await state.update_data(subcategory=subcategory)

    # Получаем товары
    products = await get_products_by_game_and_subcategory(game, subcategory)

    if not products:
        keyboard = [[InlineKeyboardButton(text="Назад", callback_data=f"manageprod_{game}")]]
        await callback.message.edit_text(
            "В этой категории нет товаров",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(EditProductStates.select_game)
        await callback.answer()
        return

    keyboard = []
    for product in products:
        # product: (id, name, description, price, game, subcategory, in_stock, image_file_id, created_at, image_path)
        product_id = product[0]
        name = product[1]
        price = product[3]
        in_stock = product[6]
        status = "✅" if in_stock else "❌"
        keyboard.append([InlineKeyboardButton(
            text=f"{status} {name} - {price:.0f} ₽",
            callback_data=f"editprod_{product_id}"
        )])

    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data="admin_products")])

    await callback.message.edit_text(
        "Выберите товар для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(EditProductStates.select_product)
    await callback.answer()


# Обработчики действий с товаром
@router.callback_query(F.data.startswith("toggle_visibility_"))
async def toggle_product_visibility(callback: CallbackQuery, state: FSMContext):
    """Переключить видимость товара"""
    product_id = int(callback.data.replace("toggle_visibility_", ""))

    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    in_stock = product[6]
    new_status = 0 if in_stock else 1

    # Обновляем статус
    from config import DB_NAME
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE products SET in_stock = ? WHERE id = ?", (new_status, product_id))
        await db.commit()

    status_text = "скрыт" if new_status == 0 else "показан"
    await callback.answer(f"Товар {status_text}", show_alert=True)

    # Обновляем меню
    await _show_edit_menu_internal(callback, state, product_id)


@router.callback_query(F.data.startswith("delete_prod_"))
async def confirm_delete_product(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления товара"""
    product_id = int(callback.data.replace("delete_prod_", ""))

    keyboard = [
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{product_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"editprod_{product_id}")
        ]
    ]

    await callback.message.edit_text(
        "Вы уверены, что хотите удалить этот товар?\n\n"
        "Это действие нельзя отменить.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_"))
async def delete_product_confirmed(callback: CallbackQuery, state: FSMContext):
    """Удалить товар окончательно"""
    product_id = int(callback.data.replace("confirm_delete_", ""))

    await delete_product(product_id)
    await callback.answer("Товар удален", show_alert=True)
    await state.clear()

    keyboard = [[InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]]
    await callback.message.edit_text(
        "✅ Товар успешно удален",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("edit_name_"))
async def start_edit_name(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование названия"""
    product_id = int(callback.data.replace("edit_name_", ""))
    await state.update_data(product_id=product_id)

    await callback.message.edit_text(
        "Введите новое название товара:\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(EditProductStates.edit_name)
    await callback.answer()


@router.message(EditProductStates.edit_name, F.text == "/cancel")
async def cancel_edit_name(message: Message, state: FSMContext):
    """Отменить редактирование"""
    await state.clear()
    await message.answer(
        "Редактирование отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]
        ])
    )


@router.message(EditProductStates.edit_name, F.text)
async def save_edit_name(message: Message, state: FSMContext):
    """Сохранить новое название"""
    data = await state.get_data()
    product_id = data["product_id"]

    await update_product(product_id, name=message.text)
    await message.answer(
        "✅ Название обновлено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад к товару", callback_data=f"backtoprod_{product_id}")]
        ])
    )


@router.callback_query(F.data.startswith("edit_desc_"))
async def start_edit_description(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование описания"""
    product_id = int(callback.data.replace("edit_desc_", ""))
    await state.update_data(product_id=product_id)

    await callback.message.edit_text(
        "Введите новое описание товара:\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(EditProductStates.edit_description)
    await callback.answer()


@router.message(EditProductStates.edit_description, F.text == "/cancel")
async def cancel_edit_description(message: Message, state: FSMContext):
    """Отменить редактирование"""
    await state.clear()
    await message.answer(
        "Редактирование отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]
        ])
    )


@router.message(EditProductStates.edit_description, F.text)
async def save_edit_description(message: Message, state: FSMContext):
    """Сохранить новое описание"""
    data = await state.get_data()
    product_id = data["product_id"]

    await update_product(product_id, description=message.text)
    await message.answer(
        "✅ Описание обновлено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад к товару", callback_data=f"backtoprod_{product_id}")]
        ])
    )


@router.callback_query(F.data.startswith("edit_price_"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование цены"""
    product_id = int(callback.data.replace("edit_price_", ""))
    await state.update_data(product_id=product_id)

    await callback.message.edit_text(
        "Введите новую цену товара (в рублях, например: 100 или 99.99):\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(EditProductStates.edit_price)
    await callback.answer()


@router.message(EditProductStates.edit_price, F.text == "/cancel")
async def cancel_edit_price(message: Message, state: FSMContext):
    """Отменить редактирование"""
    await state.clear()
    await message.answer(
        "Редактирование отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]
        ])
    )


@router.message(EditProductStates.edit_price, F.text)
async def save_edit_price(message: Message, state: FSMContext):
    """Сохранить новую цену"""
    try:
        # Очищаем текст от лишних символов (₽, руб, р, пробелы, +)
        price_text = message.text.strip()
        price_text = price_text.replace("₽", "").replace("руб", "").replace("р", "").replace(" ", "").replace("+", "")
        # Заменяем запятую на точку
        price_text = price_text.replace(",", ".")

        price = float(price_text)
        if price <= 0:
            raise ValueError("Цена должна быть больше 0")
    except (ValueError, AttributeError):
        await message.answer("Неверный формат цены. Введите число больше 0 (например: 100 или 99.99):")
        return

    data = await state.get_data()
    product_id = data["product_id"]

    await update_product(product_id, price=price)
    await message.answer(
        "✅ Цена обновлена",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад к товару", callback_data=f"backtoprod_{product_id}")]
        ])
    )


# ===== ДОБАВЛЕНИЕ ТОВАРА =====

@router.callback_query(F.data == "product_add")
async def start_add_product(callback: CallbackQuery, state: FSMContext):
    """Начать добавление товара"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text="Brawl Stars", callback_data="addprod_brawlstars")],
        [InlineKeyboardButton(text="Clash Royale", callback_data="addprod_clashroyale")],
        [InlineKeyboardButton(text="Clash of Clans", callback_data="addprod_clashofclans")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin_products")]
    ]

    await callback.message.edit_text(
        "Добавление товара\n\nВыберите игру:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(AddProductStates.select_game)
    await callback.answer()


@router.callback_query(F.data.startswith("addprod_"), AddProductStates.select_game)
async def select_game_for_product(callback: CallbackQuery, state: FSMContext):
    """Выбрать игру для товара"""
    game = callback.data.replace("addprod_", "")
    await state.update_data(game=game)

    # Категории синхронизированы с handlers/categories.py
    # "all" - товары для общего списка (показываются в каталоге игры)
    GAME_CATEGORIES = {
        "brawlstars": [
            ("all", "📦 Общее"),
            ("akcii", "🔥 Акции"),
            ("gems", "💎 Гемы"),
        ],
        "clashroyale": [
            ("all", "📦 Общее"),
            ("akcii", "🔥 Акции"),
            ("gems", "💎 Гемы"),
            ("geroi", "🦸 Герои"),
            ("evolutions", "⚡ Эволюции"),
            ("emoji", "😀 Эмодзи"),
            ("etapnye", "📈 Этапные"),
            ("karty", "🃏 Карты"),
        ],
        "clashofclans": [
            ("all", "📦 Общее"),
            ("akcii", "🔥 Акции"),
            ("gems", "💎 Гемы"),
            ("oformlenie", "🏠 Оформление"),
        ]
    }

    categories = GAME_CATEGORIES.get(game, [])

    if not categories:
        await callback.message.edit_text(
            "Категории для этой игры не настроены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="admin_products")]
            ])
        )
        await callback.answer()
        return

    # Строим клавиатуру по 2 кнопки в ряд
    keyboard = []
    row = []
    for cat_id, cat_name in categories:
        row.append(InlineKeyboardButton(text=cat_name, callback_data=f"addsubcat_{cat_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data="admin_products")])

    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(AddProductStates.select_subcategory)
    await callback.answer()


@router.callback_query(F.data.startswith("addsubcat_"), AddProductStates.select_subcategory)
async def select_subcategory_for_product(callback: CallbackQuery, state: FSMContext):
    """Выбрать подкатегорию для товара"""
    subcategory = callback.data.replace("addsubcat_", "")
    await state.update_data(subcategory=subcategory)

    await callback.message.edit_text(
        "Введите название товара:\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(AddProductStates.enter_name)
    await callback.answer()


@router.message(AddProductStates.enter_name, F.text == "/cancel")
@router.message(AddProductStates.enter_description, F.text == "/cancel")
@router.message(AddProductStates.enter_price, F.text == "/cancel")
async def cancel_add_product(message: Message, state: FSMContext):
    """Отменить добавление товара"""
    await state.clear()
    await message.answer(
        "Добавление товара отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]
        ])
    )


@router.message(AddProductStates.enter_name, F.text)
async def enter_product_name(message: Message, state: FSMContext):
    """Ввести название товара"""
    await state.update_data(name=message.text)

    await message.answer(
        "Введите описание товара:\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(AddProductStates.enter_description)


@router.message(AddProductStates.enter_description, F.text)
async def enter_product_description(message: Message, state: FSMContext):
    """Ввести описание товара"""
    await state.update_data(description=message.text)

    await message.answer(
        "Загрузите изображение товара:\n\n"
        "Отправьте фото товара (обязательно)\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(AddProductStates.upload_image)


@router.message(AddProductStates.upload_image, F.text == "/skip")
async def skip_image_upload(message: Message, state: FSMContext):
    """Изображение обязательно - нельзя пропустить"""
    await message.answer(
        "Изображение обязательно для каждого товара.\n\n"
        "Пожалуйста, отправьте фото товара:"
    )


@router.message(AddProductStates.upload_image, F.photo)
async def upload_product_image(message: Message, state: FSMContext):
    """Загрузить изображение товара"""
    # Получаем file_id самого большого фото
    photo = message.photo[-1]
    await state.update_data(image_file_id=photo.file_id)

    await message.answer(
        "✅ Изображение загружено!\n\n"
        "Введите цену товара (в рублях, например: 100 или 99.99):\n\n"
        "Отправьте /cancel для отмены"
    )
    await state.set_state(AddProductStates.enter_price)


@router.message(AddProductStates.enter_price, F.text)
async def enter_product_price(message: Message, state: FSMContext):
    """Ввести цену товара и завершить добавление"""
    try:
        # Очищаем текст от лишних символов (₽, руб, р, пробелы, +)
        price_text = message.text.strip()
        price_text = price_text.replace("₽", "").replace("руб", "").replace("р", "").replace(" ", "").replace("+", "")
        # Заменяем запятую на точку
        price_text = price_text.replace(",", ".")

        price = float(price_text)
        if price <= 0:
            raise ValueError("Цена должна быть больше 0")
    except (ValueError, AttributeError):
        await message.answer("Неверный формат цены. Введите число больше 0 (например: 100 или 99.99):")
        return

    data = await state.get_data()
    
    # Добавляем товар в базу
    product_id = await add_product(
        name=data["name"],
        description=data["description"],
        price=price,
        game=data["game"],
        subcategory=data["subcategory"],
        image_file_id=data.get("image_file_id")
    )

    await state.clear()

    game_names = {
        "brawlstars": "Brawl Stars",
        "clashroyale": "Clash Royale",
        "clashofclans": "Clash of Clans",
        "all": "Все игры"
    }
    
    subcat_names = {
        "akcii": "Акции",
        "gems": "Гемы",
        "all": "Все категории"
    }

    text = (
        f"✅ Товар успешно добавлен!\n\n"
        f"ID: {product_id}\n"
        f"Название: {data['name']}\n"
        f"Описание: {data['description']}\n"
        f"Цена: {price:.2f} ₽\n"
        f"Игра: {game_names.get(data['game'], data['game'])}\n"
        f"Категория: {subcat_names.get(data['subcategory'], data['subcategory'])}"
    )

    keyboard = [[InlineKeyboardButton(text="Назад в управление товарами", callback_data="admin_products")]]

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


# ===== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =====

@router.callback_query(F.data == "admin_users")
async def show_users_menu(callback: CallbackQuery, state: FSMContext):
    """Показать меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text="🔍 Поиск пользователя", callback_data="search_user")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_panel")]
    ]

    await callback.message.edit_text(
        "Управление пользователями\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data == "search_user")
async def start_search_user(callback: CallbackQuery, state: FSMContext):
    """Начать поиск пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_users")]]

    await callback.message.edit_text(
        "Поиск пользователя\n\n"
        "Введите Telegram ID или UID пользователя:\n\n"
        "Например:\n"
        "5932761527 - поиск по Telegram ID\n"
        "#123 - поиск по UID бота",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(UserManagementStates.search_user)
    await callback.answer()


@router.message(UserManagementStates.search_user, F.text)
async def process_search_user(message: Message, state: FSMContext):
    """Обработать поиск пользователя"""
    search_text = message.text.strip()

    # Проверяем, поиск по UID или Telegram ID
    if search_text.startswith("#"):
        # Поиск по UID
        try:
            uid = int(search_text[1:])
            user_id = await search_user_by_uid(uid)
            if not user_id:
                await message.answer(
                    f"Пользователь с UID #{uid} не найден",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="admin_users")]
                    ])
                )
                await state.clear()
                return
        except ValueError:
            await message.answer("Неверный формат UID. Введите число после #:")
            return
    else:
        # Поиск по Telegram ID
        try:
            user_id = int(search_text)
        except ValueError:
            await message.answer("Неверный формат. Введите Telegram ID (число) или UID (#123):")
            return

    # Получаем полную статистику пользователя
    user_stats = await get_user_full_stats(user_id)

    if not user_stats:
        await message.answer(
            "Пользователь не найден",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="admin_users")]
            ])
        )
        await state.clear()
        return

    # Формируем текст
    username = f"@{user_stats['username']}" if user_stats['username'] else "Нет username"
    ref_code = user_stats['referral_code'] if user_stats['referral_code'] else "Нет"

    text = (
        f"Пользователь\n\n"
        f"UID: #{user_stats['uid']}\n"
        f"Telegram ID: {user_stats['user_id']}\n"
        f"Имя: {user_stats['first_name']}\n"
        f"Username: {username}\n"
        f"Заказов: {user_stats['orders_count']}\n"
        f"Потрачено: {user_stats['total_spent']:.0f} ₽\n"
        f"Регистрация: {user_stats['registered_at']}\n"
        f"Реферальный код: {ref_code}"
    )

    keyboard = [
        [InlineKeyboardButton(text="Назад", callback_data="admin_users")]
    ]

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.clear()




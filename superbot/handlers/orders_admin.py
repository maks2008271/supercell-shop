from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import (
    get_pending_orders, get_order_by_id, confirm_order, cancel_order,
    get_user_full_stats, get_user_uid
)

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


@router.callback_query(F.data == "admin_orders")
async def show_admin_orders(callback: CallbackQuery):
    """Показать незакрытые заказы"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    orders = await get_pending_orders()

    if not orders:
        keyboard = [[InlineKeyboardButton(text="Назад", callback_data="admin_panel")]]
        await callback.message.edit_text(
            "Нет незакрытых заказов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
        return

    keyboard = []
    for order in orders:
        order_id, user_id, product_name, amount, pickup_code, created_at = order
        keyboard.append([InlineKeyboardButton(
            text=f"Заказ #{order_id} - {product_name} ({amount:.0f} ₽)",
            callback_data=f"view_order_{order_id}"
        )])

    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="admin_panel")])

    await callback.message.edit_text(
        f"Незакрытые заказы ({len(orders)}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_order_"))
async def view_order_details(callback: CallbackQuery):
    """Показать детали заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("view_order_", ""))

    order = await get_order_by_id(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # order: (id, user_id, product_id, product_name, amount, game, pickup_code, status, created_at)
    user_id = order[1]
    product_name = order[3]
    amount = order[4]
    pickup_code = order[6]
    created_at = order[8]

    # Получаем UID пользователя
    user_uid = await get_user_uid(user_id)

    text = (
        f"Заказ #{order_id}\n\n"
        f"Товар: {product_name}\n"
        f"Сумма: {amount:.0f} ₽\n"
        f"Покупатель: UID #{user_uid}\n"
        f"Telegram ID: {user_id}\n"
        f"Код получения: {pickup_code}\n"
        f"Дата: {created_at}"
    )

    keyboard = [
        [InlineKeyboardButton(text="Перейти к пользователю", callback_data=f"admin_goto_user_{user_id}")],
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_order_{order_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel_order_{order_id}")
        ],
        [InlineKeyboardButton(text="Назад", callback_data="admin_orders")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_goto_user_"))
async def admin_goto_user(callback: CallbackQuery, state: FSMContext):
    """Перейти к пользователю (показать его профиль)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_goto_user_", ""))

    # Получаем полную статистику пользователя
    user_stats = await get_user_full_stats(user_id)

    if not user_stats:
        await callback.answer("Пользователь не найден", show_alert=True)
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
        f"Баланс: {user_stats['balance']:.0f} ₽\n"
        f"Заказов: {user_stats['orders_count']}\n"
        f"Потрачено: {user_stats['total_spent']:.0f} ₽\n"
        f"Регистрация: {user_stats['registered_at']}\n"
        f"Реферальный код: {ref_code}"
    )

    keyboard = [
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"edit_user_balance_{user_id}")],
        [InlineKeyboardButton(text="Назад к заказам", callback_data="admin_orders")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_order_"))
async def ask_confirm_order(callback: CallbackQuery):
    """Запросить подтверждение выполнения заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("admin_confirm_order_", ""))

    keyboard = [
        [InlineKeyboardButton(text="✅ Да, подтвердить", callback_data=f"confirm_yes_{order_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"view_order_{order_id}")]
    ]

    await callback.message.edit_text(
        f"Вы уверены, что хотите подтвердить заказ #{order_id}?\n\n"
        f"Заказ будет помечен как выполненный.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_yes_"))
async def confirm_order_final(callback: CallbackQuery):
    """Финальное подтверждение заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("confirm_yes_", ""))

    await confirm_order(order_id)

    await callback.answer("Заказ подтвержден!", show_alert=True)
    await show_admin_orders(callback)


@router.callback_query(F.data.startswith("admin_cancel_order_"))
async def ask_cancel_order(callback: CallbackQuery):
    """Запросить подтверждение отмены заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("admin_cancel_order_", ""))

    keyboard = [
        [InlineKeyboardButton(text="✅ Да, отменить заказ", callback_data=f"cancel_yes_{order_id}")],
        [InlineKeyboardButton(text="❌ Назад", callback_data=f"view_order_{order_id}")]
    ]

    await callback.message.edit_text(
        f"Вы уверены, что хотите отменить заказ #{order_id}?\n\n"
        f"Деньги будут возвращены на баланс пользователя.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_yes_"))
async def cancel_order_final(callback: CallbackQuery):
    """Финальная отмена заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("cancel_yes_", ""))

    success = await cancel_order(order_id)

    if success:
        await callback.answer("Заказ отменен, деньги возвращены!", show_alert=True)
    else:
        await callback.answer("Ошибка отмены заказа", show_alert=True)

    await show_admin_orders(callback)

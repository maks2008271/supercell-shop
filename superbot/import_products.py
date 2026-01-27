"""
Скрипт для импорта товаров из miniapp.txt в базу данных
"""
import sqlite3
import re

# Путь к базе данных
DB_PATH = "shop_bot.db"

# Данные из txt файла - товары Clash Royale Эволюции
products = [
    {"name": "Эволюция Стенобоев", "subcategory": "Стенобои", "price": 580, "image": "1.jpg"},
    {"name": "Эволюция Теслы", "subcategory": "Тесла", "price": 580, "image": "2.jpg"},
    {"name": "Эволюция Снежка", "subcategory": "Снежок", "price": 580, "image": "3.jpg"},
    {"name": "Эволюция Ледяного Духа", "subcategory": "Ледяной Дух", "price": 580, "image": "4.jpg"},
    {"name": "Эволюция Кабанов", "subcategory": "Кабаны", "price": 580, "image": "5.jpg"},
    {"name": "Эволюция Рыцаря", "subcategory": "Рыцарь", "price": 580, "image": "6.jpg"},
    {"name": "Эволюция Огненной Лучницы", "subcategory": "Огненная Лучница", "price": 580, "image": "7.jpg"},
    {"name": "Эволюция Пушки", "subcategory": "Пушка", "price": 580, "image": "8.jpg"},
    {"name": "Эволюция Бомбера", "subcategory": "Бомбер", "price": 580, "image": "9.jpg"},
    {"name": "Эволюция Печки", "subcategory": "Печка", "price": 580, "image": "10.jpg"},
    {"name": "Эволюция Палача", "subcategory": "Палач", "price": 580, "image": "11.jpg"},
    {"name": "Эволюция Охотника", "subcategory": "Охотник", "price": 580, "image": "12.jpg"},
    {"name": "Эволюция Мушкетера", "subcategory": "Мушкетер", "price": 580, "image": "13.jpg"},
    {"name": "Эволюция Мортиры", "subcategory": "Мортира", "price": 580, "image": "14.jpg"},
    {"name": "Эволюция Лучницы", "subcategory": "Лучницы", "price": 580, "image": "15.jpg"},
    {"name": "Эволюция Мышки", "subcategory": "Мышки", "price": 580, "image": "16.jpg"},
    {"name": "Эволюция Призрака", "subcategory": "Призрак", "price": 580, "image": "17.jpg"},
    {"name": "Эволюция Кор.Гиганта", "subcategory": "Кор.Гигант", "price": 580, "image": "18.jpg"},
    {"name": "Эволюция Дракончика", "subcategory": "Пламенный дракон", "price": 580, "image": "19.jpg"},
    {"name": "Эволюция Разряда", "subcategory": "Разряд", "price": 580, "image": "20.jpg"},
    {"name": "Эволюция Гоблина с дротиками", "subcategory": "Гоблин с дротиками", "price": 580, "image": "21.jpg"},
    {"name": "Эволюция Дровосека", "subcategory": "Дровосек", "price": 580, "image": "22.jpg"},
    {"name": "Эволюция Дракона", "subcategory": "Дракон", "price": 580, "image": "23.jpg"},
    {"name": "Эволюция Гоблин-Гиганта", "subcategory": "Гоблин-Гигант", "price": 580, "image": "24.jpg"},
    {"name": "Эволюция Варваров", "subcategory": "Варвары", "price": 580, "image": "25.jpg"},
    {"name": "Эволюция Валькирии", "subcategory": "Валькирия", "price": 580, "image": "26.jpg"},
    {"name": "Эволюция Рекрутов", "subcategory": "Рекруты", "price": 580, "image": "27.jpg"},
    {"name": "Эволюция Бура", "subcategory": "Бур", "price": 580, "image": "28.jpg"},
    {"name": "Эволюция Электро-Дракона", "subcategory": "Электро-Дракон", "price": 580, "image": "29.jpg"},
    {"name": "Эволюция Клетки с Гоблином", "subcategory": "Клетка с Гоблином", "price": 580, "image": "30.jpg"},
    {"name": "Эволюция Ведьмы", "subcategory": "Ведьма", "price": 580, "image": "31.jpg"},
    {"name": "Эволюция Бочки со скелетами", "subcategory": "Бочка со скелетами", "price": 580, "image": "32.jpg"},
    {"name": "Эволюция Гоблинской бочки", "subcategory": "Гоблинская бочка", "price": 580, "image": "33.jpg"},
    {"name": "Эволюция Армии скелетов", "subcategory": "Армия скелетов", "price": 580, "image": "34.jpg"},
    {"name": "Эволюция Тарана", "subcategory": "Таран", "price": 580, "image": "35.jpg"},
    {"name": "Эволюция Пекки", "subcategory": "Пекка", "price": 580, "image": "36.jpg"},
    {"name": "Эволюция Пекки 2", "subcategory": "Пекка", "price": 580, "image": "37.jpg"},
    {"name": "Эволюция Колдуна", "subcategory": "Колдун", "price": 580, "image": "38.jpg"},
    {"name": "Эволюция Мегарыцаря", "subcategory": "Мегарыцарь", "price": 580, "image": "39.jpg"},
]

def import_products():
    """Импортирует товары в базу данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Проверяем структуру таблицы products
    cursor.execute("PRAGMA table_info(products)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"Колонки в таблице products: {columns}")

    # Добавляем колонку image_path если её нет
    if 'image_path' not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
        conn.commit()
        print("Добавлена колонка image_path")

    # Счётчики
    added = 0
    skipped = 0

    for product in products:
        # Проверяем, существует ли уже такой товар
        cursor.execute(
            "SELECT id FROM products WHERE name = ? AND game = ?",
            (product["name"], "clashroyale")
        )
        existing = cursor.fetchone()

        if existing:
            print(f"Пропускаем (уже существует): {product['name']}")
            skipped += 1
            continue

        # Путь к изображению (относительный для веб)
        image_path = f"/static/images/products/{product['image']}"

        # Добавляем товар
        cursor.execute("""
            INSERT INTO products (name, description, price, game, subcategory, in_stock, image_path)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (
            product["name"],
            f"Эволюция карты {product['subcategory']} для Clash Royale",
            product["price"],
            "clashroyale",
            "evolutions",
            image_path
        ))
        added += 1
        print(f"Добавлен: {product['name']}")

    conn.commit()
    conn.close()

    print(f"\n=== Результат ===")
    print(f"Добавлено: {added}")
    print(f"Пропущено (дубликаты): {skipped}")
    print(f"Всего товаров в списке: {len(products)}")

if __name__ == "__main__":
    import_products()

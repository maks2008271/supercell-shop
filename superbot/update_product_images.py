"""
Скрипт для обновления путей к изображениям товаров
Добавляет image_path для всех товаров на основе их ID
"""

import asyncio
import aiosqlite
from pathlib import Path

DB_NAME = "shop.db"

async def update_product_images():
    """Обновить пути к изображениям товаров"""

    # Проверяем наличие картинок
    products_dir = Path("miniapp/static/images/products")
    if not products_dir.exists():
        print(f"❌ Папка {products_dir} не найдена!")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем все товары
        cursor = await db.execute("SELECT id, name, image_file_id, image_path FROM products")
        products = await cursor.fetchall()

        print(f"Найдено товаров: {len(products)}")
        print()

        updated = 0
        for product_id, name, image_file_id, image_path in products:
            # Проверяем наличие файла картинки
            # Формат: /static/images/products/{id}.jpg
            image_file_jpg = products_dir / f"{product_id}.jpg"
            image_file_png = products_dir / f"{product_id}.png"

            new_image_path = None

            if image_file_jpg.exists():
                new_image_path = f"/static/images/products/{product_id}.jpg"
            elif image_file_png.exists():
                new_image_path = f"/static/images/products/{product_id}.png"

            # Обновляем только если найдена картинка и image_path отличается
            if new_image_path and new_image_path != image_path:
                await db.execute(
                    "UPDATE products SET image_path = ? WHERE id = ?",
                    (new_image_path, product_id)
                )
                print(f"✅ ID {product_id}: {name[:40]} -> {new_image_path}")
                updated += 1
            elif not new_image_path:
                print(f"⚠️  ID {product_id}: {name[:40]} - картинка не найдена")

        await db.commit()
        print()
        print(f"Обновлено товаров: {updated}")

if __name__ == "__main__":
    asyncio.run(update_product_images())

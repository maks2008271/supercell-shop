#!/bin/bash
# ============================================
# Скрипт установки Supercell Shop на Timeweb VPS
# ============================================
# Запуск: chmod +x setup.sh && sudo ./setup.sh

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Установка Supercell Shop${NC}"
echo -e "${GREEN}========================================${NC}"

# Проверка root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Запустите скрипт с sudo${NC}"
    exit 1
fi

# Переменные (ИЗМЕНИТЕ ПОД СВОИ ДАННЫЕ)
DOMAIN="your-domain.ru"  # Ваш домен
APP_DIR="/var/www/supercell-shop"
BOT_DIR="$APP_DIR/superbot"
LOG_DIR="/var/log/supercell-shop"

echo -e "${YELLOW}[1/8] Обновление системы...${NC}"
apt update && apt upgrade -y

echo -e "${YELLOW}[2/8] Установка зависимостей...${NC}"
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

echo -e "${YELLOW}[3/8] Создание директорий...${NC}"
mkdir -p $APP_DIR
mkdir -p $LOG_DIR
chown -R www-data:www-data $LOG_DIR

echo -e "${YELLOW}[4/8] Копирование файлов...${NC}"
# Скопируйте файлы проекта в $APP_DIR
# scp -r ./* user@server:$APP_DIR/
echo -e "${YELLOW}Скопируйте файлы проекта в $APP_DIR${NC}"

echo -e "${YELLOW}[5/8] Создание виртуального окружения...${NC}"
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r $BOT_DIR/requirements.txt

echo -e "${YELLOW}[6/8] Настройка systemd сервисов...${NC}"
cp $BOT_DIR/deploy/supercell-bot.service /etc/systemd/system/
cp $BOT_DIR/deploy/supercell-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable supercell-bot
systemctl enable supercell-api

echo -e "${YELLOW}[7/8] Настройка Nginx...${NC}"
# Замените домен в конфиге
sed -i "s/your-domain.ru/$DOMAIN/g" $BOT_DIR/deploy/nginx.conf
cp $BOT_DIR/deploy/nginx.conf /etc/nginx/sites-available/supercell-shop
ln -sf /etc/nginx/sites-available/supercell-shop /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo -e "${YELLOW}[8/8] Получение SSL сертификата...${NC}"
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m admin@$DOMAIN

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Следующие шаги:"
echo -e "1. Отредактируйте ${YELLOW}$BOT_DIR/.env${NC} файл"
echo -e "2. Запустите сервисы:"
echo -e "   ${YELLOW}sudo systemctl start supercell-bot${NC}"
echo -e "   ${YELLOW}sudo systemctl start supercell-api${NC}"
echo -e "3. Проверьте статус:"
echo -e "   ${YELLOW}sudo systemctl status supercell-bot${NC}"
echo -e "   ${YELLOW}sudo systemctl status supercell-api${NC}"
echo ""
echo -e "Логи:"
echo -e "   ${YELLOW}tail -f $LOG_DIR/bot.log${NC}"
echo -e "   ${YELLOW}tail -f $LOG_DIR/api.log${NC}"

#!/bin/bash

# Скрипт настройки SSL для AI DB
# Использование: ./setup_ssl.sh your-domain.com

set -e

if [ $# -eq 0 ]; then
    echo "❌ Укажите домен!"
    echo "Использование: ./setup_ssl.sh your-domain.com"
    exit 1
fi

DOMAIN=$1

echo "🔒 Настраиваем SSL для домена: $DOMAIN"

# Проверяем, установлен ли Certbot
if ! command -v certbot &> /dev/null; then
    echo "📦 Устанавливаем Certbot..."
    sudo apt update
    sudo apt install -y certbot python3-certbot-nginx
fi

# Проверяем, что Nginx настроен
if [ ! -f /etc/nginx/sites-available/ai-db ]; then
    echo "❌ Nginx не настроен!"
    echo "Сначала выполните: ./setup_nginx.sh $DOMAIN"
    exit 1
fi

# Получаем SSL сертификат
echo "🎫 Получаем SSL сертификат..."
sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN

# Настраиваем автообновление
echo "⏰ Настраиваем автообновление сертификата..."
if ! sudo crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (sudo crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | sudo crontab -
fi

# Проверяем статус сертификата
echo "🔍 Проверяем статус сертификата..."
sudo certbot certificates

echo "✅ SSL настроен!"
echo ""
echo "🌐 Сайт доступен по адресу: https://$DOMAIN"
echo ""
echo "📋 Полезные команды:"
echo "  Проверить сертификат: sudo certbot certificates"
echo "  Обновить вручную: sudo certbot renew"
echo "  Проверить автообновление: sudo crontab -l" 
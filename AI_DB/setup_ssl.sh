#!/bin/bash

# Настройка SSL для ai-db.ru
echo "🔒 Настройка SSL сертификата..."

# Устанавливаем Certbot
if ! command -v certbot &> /dev/null; then
    echo "📦 Устанавливаем Certbot..."
    apt update
    apt install -y certbot python3-certbot-nginx
fi

# Получаем SSL сертификат
echo "🎫 Получаем SSL сертификат для ai-db.ru..."
certbot --nginx -d ai-db.ru -d www.ai-db.ru --non-interactive --agree-tos --email admin@ai-db.ru

if [ $? -eq 0 ]; then
    echo "✅ SSL сертификат успешно установлен!"
    echo "🌐 Сайт доступен по адресу: https://ai-db.ru"
    
    # Настраиваем автообновление сертификата
    echo "🔄 Настраиваем автообновление сертификата..."
    (crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | crontab -
    
    echo "✅ Автообновление сертификата настроено"
else
    echo "❌ Ошибка при получении SSL сертификата"
    exit 1
fi 
#!/bin/bash

# Скрипт настройки Nginx для AI DB
# Использование: ./setup_nginx.sh your-domain.com

set -e

if [ $# -eq 0 ]; then
    echo "❌ Укажите домен!"
    echo "Использование: ./setup_nginx.sh your-domain.com"
    exit 1
fi

DOMAIN=$1

echo "🌐 Настраиваем Nginx для домена: $DOMAIN"

# Проверяем, установлен ли Nginx
if ! command -v nginx &> /dev/null; then
    echo "📦 Устанавливаем Nginx..."
    sudo apt update
    sudo apt install -y nginx
fi

# Создаем конфигурацию Nginx
echo "📝 Создаем конфигурацию Nginx..."
sudo tee /etc/nginx/sites-available/ai-db > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Увеличиваем лимиты для загрузки файлов
    client_max_body_size 100M;
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
}
EOF

# Активируем сайт
echo "🔗 Активируем сайт..."
sudo ln -sf /etc/nginx/sites-available/ai-db /etc/nginx/sites-enabled/

# Удаляем дефолтный сайт
sudo rm -f /etc/nginx/sites-enabled/default

# Проверяем конфигурацию
echo "🔍 Проверяем конфигурацию Nginx..."
sudo nginx -t

# Перезапускаем Nginx
echo "🔄 Перезапускаем Nginx..."
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "✅ Nginx настроен!"
echo ""
echo "🌐 Сайт доступен по адресу: http://$DOMAIN"
echo ""
echo "🔒 Для настройки SSL выполните:"
echo "sudo apt install -y certbot python3-certbot-nginx"
echo "sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN" 
#!/bin/bash

# Настройка Nginx для AI_DB
echo "🔧 Настройка Nginx..."

# Создаем конфигурацию Nginx
cat > /etc/nginx/sites-available/ai-db.ru << 'EOF'
server {
    listen 80;
    server_name ai-db.ru www.ai-db.ru;
    
    # Логи
    access_log /var/log/nginx/ai-db.ru.access.log;
    error_log /var/log/nginx/ai-db.ru.error.log;
    
    # Проксирование на приложение
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Статические файлы
    location /static/ {
        alias /root/AI_DB/uploads/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Здоровье приложения
    location /health {
        proxy_pass http://localhost:8000/health;
        access_log off;
    }
}
EOF

# Активируем сайт
ln -sf /etc/nginx/sites-available/ai-db.ru /etc/nginx/sites-enabled/

# Удаляем дефолтную конфигурацию
rm -f /etc/nginx/sites-enabled/default

# Проверяем конфигурацию
nginx -t

if [ $? -eq 0 ]; then
    echo "✅ Конфигурация Nginx корректна"
    systemctl reload nginx
    echo "✅ Nginx перезагружен"
else
    echo "❌ Ошибка в конфигурации Nginx"
    exit 1
fi 
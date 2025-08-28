#!/bin/bash

# Скрипт настройки автозапуска AI DB
# Использование: ./setup_autostart.sh

set -e

echo "🚀 Настраиваем автозапуск AI DB..."

# Получаем текущую директорию
CURRENT_DIR=$(pwd)
USER=$(whoami)

# Создаем systemd сервис
echo "📝 Создаем systemd сервис..."
sudo tee /etc/systemd/system/ai-db.service > /dev/null <<EOF
[Unit]
Description=AI DB Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$CURRENT_DIR
User=$USER
Group=$USER
ExecStart=/usr/local/bin/docker-compose -f docker-compose.prod.yml up -d
ExecStop=/usr/local/bin/docker-compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

# Перезагружаем systemd
echo "🔄 Перезагружаем systemd..."
sudo systemctl daemon-reload

# Активируем сервис
echo "✅ Активируем сервис..."
sudo systemctl enable ai-db.service

# Создаем скрипт бэкапа
echo "💾 Создаем скрипт бэкапа..."
tee backup.sh > /dev/null <<EOF
#!/bin/bash
DATE=\$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$CURRENT_DIR/backups"

mkdir -p \$BACKUP_DIR

# Бэкап базы данных
docker exec ai_db_postgres pg_dump -U ai_user ai_db > \$BACKUP_DIR/db_backup_\$DATE.sql

# Бэкап файлов
tar -czf \$BACKUP_DIR/uploads_backup_\$DATE.tar.gz uploads/

# Удаление старых бэкапов (оставляем последние 7)
find \$BACKUP_DIR -name "*.sql" -mtime +7 -delete
find \$BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Бэкап завершен: \$DATE"
EOF

# Делаем скрипт исполняемым
chmod +x backup.sh

# Настраиваем автоматические бэкапы
echo "⏰ Настраиваем автоматические бэкапы..."
if ! crontab -l 2>/dev/null | grep -q "backup.sh"; then
    (crontab -l 2>/dev/null; echo "0 2 * * * $CURRENT_DIR/backup.sh") | crontab -
fi

echo "✅ Автозапуск настроен!"
echo ""
echo "📋 Полезные команды:"
echo "  Запустить: sudo systemctl start ai-db"
echo "  Остановить: sudo systemctl stop ai-db"
echo "  Статус: sudo systemctl status ai-db"
echo "  Логи: sudo journalctl -u ai-db -f"
echo "  Бэкап вручную: ./backup.sh"
echo ""
echo "🔄 Приложение будет автоматически запускаться при перезагрузке сервера" 
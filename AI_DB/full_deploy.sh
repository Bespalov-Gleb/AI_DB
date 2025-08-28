#!/bin/bash

# Полное развертывание AI DB на Timeweb VPS
# Использование: ./full_deploy.sh [domain]

set -e

echo "🚀 Полное развертывание AI DB на Timeweb VPS"
echo "=============================================="

# Проверяем аргументы
DOMAIN=""
if [ $# -eq 1 ]; then
    DOMAIN=$1
    echo "🌐 Домен: $DOMAIN"
fi

# Проверяем, что мы root или используем sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ Этот скрипт должен выполняться с правами root"
    echo "Используйте: sudo ./full_deploy.sh [domain]"
    exit 1
fi

# Обновляем систему
echo "📦 Обновляем систему..."
apt update && apt upgrade -y

# Устанавливаем необходимые пакеты
echo "📦 Устанавливаем необходимые пакеты..."
apt install -y curl wget git nano htop ufw

# Настраиваем файрвол
echo "🔥 Настраиваем файрвол..."
ufw allow ssh
ufw allow 80
ufw allow 443
ufw allow 8000
ufw --force enable

# Создаем пользователя для приложения
echo "👤 Создаем пользователя для приложения..."
if ! id "aiuser" &>/dev/null; then
    adduser --disabled-password --gecos "" aiuser
    usermod -aG sudo aiuser
    echo "aiuser ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/aiuser
fi

# Устанавливаем Docker
echo "🐳 Устанавливаем Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    usermod -aG docker aiuser
fi

# Устанавливаем Docker Compose
echo "🐳 Устанавливаем Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Переключаемся на пользователя aiuser
echo "👤 Переключаемся на пользователя aiuser..."
su - aiuser << 'EOF'

# Переходим в домашнюю директорию
cd ~

# Клонируем репозиторий (если нужно)
if [ ! -d "AI_DB" ]; then
    echo "📥 Клонируем репозиторий..."
    git clone https://github.com/YOUR_USERNAME/AI_DB.git
fi

cd AI_DB

# Проверяем наличие .env
if [ ! -f .env ]; then
    echo "❌ Файл .env не найден!"
    echo "Создайте файл .env с необходимыми настройками"
    exit 1
fi

# Делаем скрипты исполняемыми
chmod +x deploy.sh
chmod +x setup_nginx.sh
chmod +x setup_ssl.sh
chmod +x setup_autostart.sh

# Запускаем развертывание
echo "🚀 Запускаем развертывание приложения..."
./deploy.sh

# Настраиваем автозапуск
echo "🔄 Настраиваем автозапуск..."
./setup_autostart.sh

EOF

# Если указан домен, настраиваем Nginx и SSL
if [ ! -z "$DOMAIN" ]; then
    echo "🌐 Настраиваем домен: $DOMAIN"
    
    # Переключаемся на aiuser для настройки Nginx
    su - aiuser -c "cd ~/AI_DB && ./setup_nginx.sh $DOMAIN"
    
    echo "🔒 Настраиваем SSL..."
    su - aiuser -c "cd ~/AI_DB && ./setup_ssl.sh $DOMAIN"
fi

echo ""
echo "🎉 Развертывание завершено!"
echo ""
echo "📋 Что было настроено:"
echo "  ✅ Система обновлена"
echo "  ✅ Файрвол настроен"
echo "  ✅ Docker и Docker Compose установлены"
echo "  ✅ Пользователь aiuser создан"
echo "  ✅ Приложение развернуто"
echo "  ✅ Автозапуск настроен"
echo "  ✅ Автоматические бэкапы настроены"

if [ ! -z "$DOMAIN" ]; then
    echo "  ✅ Nginx настроен"
    echo "  ✅ SSL сертификат установлен"
    echo ""
    echo "🌐 Ваш сайт доступен по адресу: https://$DOMAIN"
else
    echo ""
    echo "🌐 Приложение доступно по адресу: http://$(hostname -I | awk '{print $1}'):8000"
fi

echo ""
echo "📋 Полезные команды:"
echo "  Статус приложения: sudo systemctl status ai-db"
echo "  Логи приложения: sudo journalctl -u ai-db -f"
echo "  Перезапуск: sudo systemctl restart ai-db"
echo "  Бэкап: sudo -u aiuser ~/AI_DB/backup.sh"
echo ""
echo "🔐 Не забудьте:"
echo "  - Изменить пароли в .env файле"
echo "  - Проверить работу Telegram бота"
echo "  - Создать токены доступа в веб-интерфейсе" 
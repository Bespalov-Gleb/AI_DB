#!/bin/bash

# Скрипт автоматического развертывания AI DB на Timeweb VPS
# Использование: ./deploy.sh

set -e  # Остановка при ошибке

echo "🚀 Начинаем развертывание AI DB..."

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "❌ Файл .env не найден!"
    echo "Создайте файл .env с необходимыми настройками"
    exit 1
fi

# Проверяем наличие docker-compose.prod.yml
if [ ! -f docker-compose.prod.yml ]; then
    echo "❌ Файл docker-compose.prod.yml не найден!"
    exit 1
fi

# Создаем необходимые директории
echo "📁 Создаем директории..."
mkdir -p uploads secrets backups

# Останавливаем существующие контейнеры
echo "🛑 Останавливаем существующие контейнеры..."
docker-compose -f docker-compose.prod.yml down || true

# Удаляем старые образы (опционально)
echo "🧹 Очищаем старые образы..."
docker system prune -f

# Собираем и запускаем контейнеры
echo "🔨 Собираем и запускаем контейнеры..."
docker-compose -f docker-compose.prod.yml up -d --build

# Ждем запуска базы данных
echo "⏳ Ждем запуска базы данных..."
sleep 10

# Проверяем статус контейнеров
echo "📊 Проверяем статус контейнеров..."
docker-compose -f docker-compose.prod.yml ps

# Проверяем логи
echo "📋 Проверяем логи приложения..."
docker-compose -f docker-compose.prod.yml logs app --tail=20

echo "📋 Проверяем логи бота..."
docker-compose -f docker-compose.prod.yml logs bot --tail=20

# Проверяем доступность API
echo "🔍 Проверяем доступность API..."
sleep 5
if curl -f http://localhost:8000/health/ > /dev/null 2>&1; then
    echo "✅ API доступен!"
else
    echo "❌ API недоступен!"
    echo "Проверьте логи: docker-compose -f docker-compose.prod.yml logs"
    exit 1
fi

# Проверяем доступность веб-интерфейса
echo "🔍 Проверяем доступность веб-интерфейса..."
if curl -f http://localhost:8000/web/ > /dev/null 2>&1; then
    echo "✅ Веб-интерфейс доступен!"
else
    echo "❌ Веб-интерфейс недоступен!"
    echo "Проверьте логи: docker-compose -f docker-compose.prod.yml logs app"
    exit 1
fi

echo ""
echo "🎉 Развертывание завершено успешно!"
echo ""
echo "📋 Полезные команды:"
echo "  Статус: docker-compose -f docker-compose.prod.yml ps"
echo "  Логи: docker-compose -f docker-compose.prod.yml logs -f"
echo "  Перезапуск: docker-compose -f docker-compose.prod.yml restart"
echo "  Остановка: docker-compose -f docker-compose.prod.yml down"
echo ""
echo "🌐 Веб-интерфейс: http://localhost:8000/web/"
echo "📊 API документация: http://localhost:8000/docs"
echo "💚 Состояние системы: http://localhost:8000/health/"
echo ""
echo "🤖 Не забудьте проверить работу Telegram бота!" 
# 🚀 Развертывание AI DB на Timeweb VPS

## Подготовка сервера

### 1. Создание VPS в Timeweb

1. **Войдите в панель Timeweb**
2. **Создайте новый VPS:**
   - **ОС:** Ubuntu 22.04 LTS
   - **Конфигурация:** минимум 2 CPU, 4 GB RAM, 20 GB SSD
   - **Тариф:** VPS-2 или выше
   - **Локация:** выбирайте ближайшую к вам

### 2. Подключение к серверу

```bash
# Подключитесь по SSH
ssh root@YOUR_SERVER_IP

# Обновите систему
apt update && apt upgrade -y

# Установите необходимые пакеты
apt install -y curl wget git nano htop ufw
```

### 3. Настройка безопасности

```bash
# Настройте файрвол
ufw allow ssh
ufw allow 80
ufw allow 443
ufw allow 8000
ufw enable

# Создайте пользователя для приложения
adduser aiuser
usermod -aG sudo aiuser

# Переключитесь на пользователя
su - aiuser
```

## Установка Docker и Docker Compose

### 1. Установка Docker

```bash
# Установите Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Добавьте пользователя в группу docker
sudo usermod -aG docker $USER

# Перезапустите сессию или выполните
newgrp docker
```

### 2. Установка Docker Compose

```bash
# Установите Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Проверьте установку
docker-compose --version
```

## Развертывание приложения

### 1. Клонирование репозитория

```bash
# Перейдите в домашнюю директорию
cd ~

# Клонируйте репозиторий (замените на ваш URL)
git clone https://github.com/YOUR_USERNAME/AI_DB.git
cd AI_DB

# Или создайте проект вручную
mkdir AI_DB
cd AI_DB
```

### 2. Создание файла .env

```bash
# Создайте файл .env
nano .env
```

**Содержимое .env для продакшена:**

```env
# Настройки приложения
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
TIMEZONE=Europe/Moscow

# База данных
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=ai_db
POSTGRES_USER=ai_user
POSTGRES_PASSWORD=YOUR_STRONG_PASSWORD_HERE

# API ключи (ОБЯЗАТЕЛЬНО заполните!)
OPENAI_API_KEY=your_openai_api_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ADMIN_CHAT_ID=your_admin_chat_id_here

# Веб-интерфейс (замените на ваш домен)
WEB_BASE_URL=https://your-domain.com
# или
WEB_BASE_URL=http://YOUR_SERVER_IP:8000

# Административные учетные данные (ОБЯЗАТЕЛЬНО измените!)
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=your_strong_password_here

# SMTP настройки (опционально)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com
SMTP_TO=recipient@example.com

# S3 настройки (опционально)
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=your_access_key
S3_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET=your_bucket_name

# Загрузки
UPLOAD_DIR=uploads
```

### 3. Настройка Docker Compose

**Создайте файл docker-compose.prod.yml:**

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    container_name: ai_db_postgres
    environment:
      POSTGRES_DB: ai_db
      POSTGRES_USER: ai_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - ai_db_network

  app:
    build: .
    container_name: ai_db_app
    environment:
      - APP_ENV=${APP_ENV}
      - APP_HOST=${APP_HOST}
      - APP_PORT=${APP_PORT}
      - TIMEZONE=${TIMEZONE}
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_PORT=${POSTGRES_PORT}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
      - WEB_BASE_URL=${WEB_BASE_URL}
      - ADMIN_USERNAME=${ADMIN_USERNAME}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_PORT=${SMTP_PORT}
      - SMTP_USERNAME=${SMTP_USERNAME}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
      - SMTP_FROM=${SMTP_FROM}
      - SMTP_TO=${SMTP_TO}
      - S3_ENDPOINT_URL=${S3_ENDPOINT_URL}
      - S3_REGION=${S3_REGION}
      - S3_ACCESS_KEY_ID=${S3_ACCESS_KEY_ID}
      - S3_SECRET_ACCESS_KEY=${S3_SECRET_ACCESS_KEY}
      - S3_BUCKET=${S3_BUCKET}
      - UPLOAD_DIR=${UPLOAD_DIR}
    ports:
      - "8000:8000"
    volumes:
      - ./uploads:/app/uploads
      - ./secrets:/app/secrets
    depends_on:
      - postgres
    restart: unless-stopped
    networks:
      - ai_db_network

  bot:
    build: .
    container_name: ai_db_bot
    command: python -m bot.main
    environment:
      - APP_ENV=${APP_ENV}
      - APP_HOST=${APP_HOST}
      - APP_PORT=${APP_PORT}
      - TIMEZONE=${TIMEZONE}
      - POSTGRES_HOST=${POSTGRES_HOST}
      - POSTGRES_PORT=${POSTGRES_PORT}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
      - WEB_BASE_URL=${WEB_BASE_URL}
      - ADMIN_USERNAME=${ADMIN_USERNAME}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_PORT=${SMTP_PORT}
      - SMTP_USERNAME=${SMTP_USERNAME}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
      - SMTP_FROM=${SMTP_FROM}
      - SMTP_TO=${SMTP_TO}
      - S3_ENDPOINT_URL=${S3_ENDPOINT_URL}
      - S3_REGION=${S3_REGION}
      - S3_ACCESS_KEY_ID=${S3_ACCESS_KEY_ID}
      - S3_SECRET_ACCESS_KEY=${S3_SECRET_ACCESS_KEY}
      - S3_BUCKET=${S3_BUCKET}
      - UPLOAD_DIR=${UPLOAD_DIR}
    volumes:
      - ./uploads:/app/uploads
      - ./secrets:/app/secrets
    depends_on:
      - postgres
      - app
    restart: unless-stopped
    networks:
      - ai_db_network

volumes:
  postgres_data:

networks:
  ai_db_network:
    driver: bridge
```

### 4. Запуск приложения

```bash
# Создайте необходимые директории
mkdir -p uploads secrets

# Запустите приложение
docker-compose -f docker-compose.prod.yml up -d --build

# Проверьте статус
docker-compose -f docker-compose.prod.yml ps

# Посмотрите логи
docker-compose -f docker-compose.prod.yml logs -f
```

## Настройка домена и SSL

### 1. Настройка домена в Timeweb

1. **В панели Timeweb** перейдите в раздел "Домены"
2. **Добавьте ваш домен** (например, `ai-db.yourdomain.com`)
3. **Настройте DNS записи:**
   - Тип: A
   - Имя: @ (или поддомен)
   - Значение: IP вашего сервера

### 2. Установка Nginx

```bash
# Установите Nginx
sudo apt install -y nginx

# Создайте конфигурацию
sudo nano /etc/nginx/sites-available/ai-db
```

**Конфигурация Nginx:**

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Увеличиваем лимиты для загрузки файлов
    client_max_body_size 100M;
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
}
```

```bash
# Активируйте сайт
sudo ln -s /etc/nginx/sites-available/ai-db /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 3. Установка SSL сертификата

```bash
# Установите Certbot
sudo apt install -y certbot python3-certbot-nginx

# Получите SSL сертификат
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Настройте автообновление
sudo crontab -e
# Добавьте строку:
# 0 12 * * * /usr/bin/certbot renew --quiet
```

### 4. Обновите .env

```bash
# Обновите WEB_BASE_URL
nano .env
```

```env
WEB_BASE_URL=https://your-domain.com
```

```bash
# Перезапустите приложение
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

## Настройка автозапуска

### 1. Создание systemd сервиса

```bash
sudo nano /etc/systemd/system/ai-db.service
```

**Содержимое файла:**

```ini
[Unit]
Description=AI DB Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/aiuser/AI_DB
ExecStart=/usr/local/bin/docker-compose -f docker-compose.prod.yml up -d
ExecStop=/usr/local/bin/docker-compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
# Активируйте сервис
sudo systemctl enable ai-db.service
sudo systemctl start ai-db.service
```

### 2. Настройка автоматических бэкапов

```bash
# Создайте скрипт бэкапа
nano ~/backup.sh
```

**Содержимое backup.sh:**

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/aiuser/backups"

mkdir -p $BACKUP_DIR

# Бэкап базы данных
docker exec ai_db_postgres pg_dump -U ai_user ai_db > $BACKUP_DIR/db_backup_$DATE.sql

# Бэкап файлов
tar -czf $BACKUP_DIR/uploads_backup_$DATE.tar.gz uploads/

# Удаление старых бэкапов (оставляем последние 7)
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
```

```bash
# Сделайте скрипт исполняемым
chmod +x ~/backup.sh

# Добавьте в cron (ежедневно в 2:00)
crontab -e
# Добавьте строку:
# 0 2 * * * /home/aiuser/backup.sh
```

## Мониторинг и обслуживание

### 1. Полезные команды

```bash
# Проверка статуса
docker-compose -f docker-compose.prod.yml ps

# Просмотр логов
docker-compose -f docker-compose.prod.yml logs -f app
docker-compose -f docker-compose.prod.yml logs -f bot

# Перезапуск сервисов
docker-compose -f docker-compose.prod.yml restart app
docker-compose -f docker-compose.prod.yml restart bot

# Обновление приложения
git pull
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d --build
```

### 2. Мониторинг ресурсов

```bash
# Установите htop для мониторинга
sudo apt install -y htop

# Проверьте использование ресурсов
htop
df -h
docker system df
```

## Проверка работоспособности

### 1. Проверьте доступность

```bash
# Проверьте API
curl http://localhost:8000/health/

# Проверьте веб-интерфейс
curl http://localhost:8000/web/
```

### 2. Проверьте бота

1. Найдите вашего бота в Telegram
2. Отправьте команду `/start`
3. Проверьте команду `/веб` - должна вернуть правильную ссылку

### 3. Создайте тестовую запись

1. Откройте веб-интерфейс
2. Войдите как администратор
3. Создайте тестовую запись
4. Проверьте, что она отображается в списке

## Устранение проблем

### Приложение не запускается:

```bash
# Проверьте логи
docker-compose -f docker-compose.prod.yml logs

# Проверьте переменные окружения
docker-compose -f docker-compose.prod.yml config

# Проверьте доступность базы данных
docker exec -it ai_db_postgres psql -U ai_user -d ai_db
```

### Проблемы с доменом:

```bash
# Проверьте DNS
nslookup your-domain.com

# Проверьте Nginx
sudo nginx -t
sudo systemctl status nginx

# Проверьте SSL
sudo certbot certificates
```

### Проблемы с SSL:

```bash
# Обновите сертификат вручную
sudo certbot renew

# Проверьте автообновление
sudo crontab -l
```

## Рекомендации по безопасности

1. **Измените пароли** администратора в .env
2. **Используйте сильные пароли** для базы данных
3. **Регулярно обновляйте** систему и Docker образы
4. **Настройте файрвол** (уже сделано выше)
5. **Используйте SSH ключи** вместо паролей
6. **Регулярно делайте бэкапы** (уже настроено выше)

## Стоимость

**Примерная стоимость на Timeweb:**
- VPS-2: ~500-800 руб/месяц
- Домен: ~200-500 руб/год
- SSL сертификат: бесплатно (Let's Encrypt)

**Итого:** ~600-900 руб/месяц за полностью рабочую систему 
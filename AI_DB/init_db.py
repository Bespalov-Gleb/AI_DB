#!/usr/bin/env python3
"""
Скрипт инициализации базы данных
"""

import os
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from app.db import Base, engine
from app.models import (
    User, Listing, Photo, Reminder, ChatMessage, 
    AuditLog, AccessToken
)

def init_database():
    """Создает все таблицы в базе данных"""
    print("🔧 Инициализация базы данных...")
    
    try:
        # Создаем все таблицы
        Base.metadata.create_all(bind=engine)
        print("✅ Таблицы успешно созданы!")
        
        # Проверяем созданные таблицы
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"📋 Созданные таблицы: {', '.join(tables)}")
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблиц: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)

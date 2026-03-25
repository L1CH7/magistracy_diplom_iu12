import pytest
import uuid
import asyncpg
import os
from loguru import logger
from services.common.config import load_settings

# Получаем настройки через наш загрузчик
try:
    settings = load_settings()
except Exception:
    # Fallback для контейнера
    class DummySettings:
        class DB:
            host = "postgis"
            port = 5432
            user = "postgres"
            password = "postgres"
            name = "nav_mas"
        db = DB()
    settings = DummySettings()

@pytest.fixture(scope="function")
async def db_schema():
    """
    Создает изолированную схему для каждого теста.
    ОПТИМИЗАЦИЯ: Граф читается из public, запись идет в test_schema.
    Копирование таблиц запрещено для производительности.
    """
    schema_name = f"test_results_{uuid.uuid4().hex[:8]}"
    
    conn = await asyncpg.connect(
        host=settings.db.host,
        port=settings.db.port,
        user=settings.db.user,
        password=settings.db.password,
        database=settings.db.name
    )
    
    try:
        # 1. Setup: Создаем схему и настраиваем путь поиска
        logger.info(f"[Fixture] Подготовка схемы: {schema_name}")
        await conn.execute(f"CREATE SCHEMA {schema_name}")
        
        # Устанавливаем search_path: сначала тестовая схема (для записи), затем public (для чтения графа)
        await conn.execute(f"SET search_path TO {schema_name}, public")
        
        # Передаем имя схемы в тест
        yield schema_name

    finally:
        # 2. Teardown: Удаляем схему
        logger.info(f"[Fixture] Очистка схемы: {schema_name}")
        await conn.execute(f"DROP SCHEMA {schema_name} CASCADE")
        await conn.close()

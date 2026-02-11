import asyncpg
import random
from services.common.config import load_settings

async def get_random_points(count: int = 50):
    """
    Извлекает случайные точки (начала ребер) из базы данных.
    """
    try:
        settings = load_settings()
        db_params = {
            "host": settings.db.host,
            "port": settings.db.port,
            "user": settings.db.user,
            "password": settings.db.password,
            "database": settings.db.name
        }
    except Exception as e:
        logger.warning(f"Failed to load settings: {e}. Using defaults.")
        # Fallback defaults work inside Docker if env vars are missing during test collection
        db_params = {
            "host": "postgis",
            "port": 5432,
            "user": "postgres",
            "password": "postgres",
            "database": "nav_mas"
        }
    
    conn = await asyncpg.connect(**db_params)
    
    try:
        if count == 2:
            # Для тестов из 2 точек гарантируем связность, выбирая начало и конец одного ребра
            query = """
                SELECT 
                    ST_Y(ST_StartPoint(geometry)) as s_lat, 
                    ST_X(ST_StartPoint(geometry)) as s_lon,
                    ST_Y(ST_EndPoint(geometry)) as e_lat,
                    ST_X(ST_EndPoint(geometry)) as e_lon
                FROM graphs.edges
                ORDER BY random()
                LIMIT 1
            """
            row = await conn.fetchrow(query)
            return [
                {"lat": row['s_lat'], "lon": row['s_lon']},
                {"lat": row['e_lat'], "lon": row['e_lon']}
            ]

        # Стандартная выборка по сетке для большого количества точек
        query = """
            WITH grid AS (
                SELECT 
                    ST_Y(ST_StartPoint(geometry)) as lat, 
                    ST_X(ST_StartPoint(geometry)) as lon,
                    ST_SnapToGrid(ST_StartPoint(geometry), 0.05) as cell -- Ячейка ~5км
                FROM graphs.edges
            )
            SELECT DISTINCT ON (cell) lat, lon
            FROM grid
            ORDER BY cell, random()
            LIMIT $1;
        """
        rows = await conn.fetch(query, count)
        
        # Если сетка слишком крупная и точек мало, попробуем просто случайную выборку
        if len(rows) < count:
             query = "SELECT ST_Y(ST_StartPoint(geometry)) as lat, ST_X(ST_StartPoint(geometry)) as lon FROM graphs.edges ORDER BY random() LIMIT $1;"
             rows = await conn.fetch(query, count)
             
        return [{"lat": row['lat'], "lon": row['lon']} for row in rows]
    finally:
        await conn.close()
async def get_distant_random_points(min_dist_km: float = 5.0):
    """
    Извлекает две точки, которые находятся как минимум в min_dist_km друг от друга.
    """
    try:
        settings = load_settings()
        db_params = {
            "host": settings.db.host,
            "port": settings.db.port,
            "user": settings.db.user,
            "password": settings.db.password,
            "database": settings.db.name
        }
    except Exception:
        db_params = {"host": "postgis", "port": 5432, "user": "postgres", "password": "postgres", "database": "nav_mas"}
    
    conn = await asyncpg.connect(**db_params)
    try:
        # Берем случайную точку и ищем другую на расстоянии > min_dist_km
        query = """
            WITH p1 AS (
                SELECT ST_StartPoint(geometry) as geom FROM graphs.edges ORDER BY random() LIMIT 1
            ),
            p2 AS (
                SELECT ST_StartPoint(geometry) as geom 
                FROM graphs.edges, p1 
                WHERE ST_Distance(ST_StartPoint(geometry)::geography, p1.geom::geography) > $1 * 1000
                ORDER BY random() 
                LIMIT 1
            )
            SELECT ST_Y(p1.geom) as lat1, ST_X(p1.geom) as lon1, ST_Y(p2.geom) as lat2, ST_X(p2.geom) as lon2
            FROM p1, p2;
        """
        row = await conn.fetchrow(query, min_dist_km)
        if not row:
            # Fallback if no such pair found (unlikely for 5km in Moscow)
            return await get_random_points(2) # Fallback to original
            
        return [
            {"lat": row['lat1'], "lon": row['lon1']},
            {"lat": row['lat2'], "lon": row['lon2']}
        ]
    finally:
        await conn.close()

def load_curated_waypoints():
    """Загружает вручную отобранные точки из JSON."""
    import json
    import os
    json_path = os.path.join(os.path.dirname(__file__), "waypoints.json")
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            return json.load(f)
    return []

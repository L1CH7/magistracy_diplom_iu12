import osmium
import osmium.geom
import json
import asyncio
import argparse
import sys
import time
import yaml
import os
import multiprocessing
import asyncpg
import io
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from loguru import logger

# Добавляем корень проекта в путь для импортов
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from src.db.queries import OSMQueries

# Фабрика геометрии для вывода WKB
wkbfactory = osmium.geom.WKBFactory()

class CountHandler(osmium.SimpleHandler):
    """Быстрый предварительный скан для подсчета общего количества объектов."""
    def __init__(self):
        super().__init__()
        self.count = 0
    def node(self, n): self.count += 1
    def way(self, w): self.count += 1
    def relation(self, r): self.count += 1

class PBFHandler(osmium.SimpleHandler):
    """
    Обработчик Osmium для извлечения дорог, барьеров и ограничений поворотов из PBF.
    Отправляет извлеченные данные в multiprocessing.Queue.
    """
    def __init__(self, queue, bbox=None):
        super().__init__()
        self.queue = queue
        self.bbox = bbox # [min_lon, min_lat, max_lon, max_lat]
        self.found_count = 0
        self.local_batch = []
        self.batch_limit = 1000
        
        # Фильтрующие наборы
        self.highway_types = {
            'motorway', 'motorway_link', 'trunk', 'trunk_link', 
            'primary', 'primary_link', 'secondary', 'secondary_link',
            'tertiary', 'tertiary_link', 'residential', 'living_street',
            'unclassified', 'service', 'road', 'track', 'bus_guideway', 'escape'
        }
        self.barrier_types = {
            'gate', 'boom', 'bollard', 'block', 'wall', 'lift_gate', 'sliding_gate',
            'fence', 'stile', 'turnstile', 'bollard', 'cycle_barrier'
        }

    def _is_in_bbox(self, lon: float, lat: float) -> bool:
        if not self.bbox: return True
        return self.bbox[0] <= lon <= self.bbox[2] and self.bbox[1] <= lat <= self.bbox[3]

    def node(self, n):
        self.found_count += 1
        tags = {t.k: t.v for t in n.tags}
        if not tags: return
        
        if not self._is_in_bbox(n.location.lon, n.location.lat): return
        
        wkb = wkbfactory.create_point(n)
        self._send_to_worker('node', (n.id, wkb, json.dumps(tags)))
        
        barrier = tags.get('barrier')
        if barrier and barrier in self.barrier_types:
            self._send_to_worker('barrier', (n.id, wkb, json.dumps(tags), barrier, 'node'))

    def way(self, w):
        self.found_count += 1
        tags = {t.k: t.v for t in w.tags}
        highway = tags.get('highway')
        barrier = tags.get('barrier')
        
        is_highway = highway in self.highway_types
        is_barrier = barrier in self.barrier_types
        
        if is_highway or is_barrier:
            if self.bbox:
                in_bbox = False
                for node in w.nodes:
                    if self._is_in_bbox(node.lon, node.lat):
                        in_bbox = True
                        break
                if not in_bbox: return

            try:
                wkb = wkbfactory.create_linestring(w)
                if is_barrier:
                    self._send_to_worker('barrier', (w.id, wkb, json.dumps(tags), barrier, 'way'))
                
                if is_highway:
                    lanes = tags.get('lanes')
                    l_val = int(lanes) if (lanes and str(lanes).isdigit()) else None
                    self._send_to_worker('way', (w.id, wkb, json.dumps(tags), highway, tags.get('name'), l_val, tags.get('maxspeed')))
            except Exception:
                pass

    def relation(self, r):
        self.found_count += 1
        if r.tags.get('type') == 'restriction':
            tags = {t.k: t.v for t in r.tags}
            members = []
            for m in r.members:
                members.append({'type': str(m.type), 'ref': m.ref, 'role': m.role})
            self._send_to_worker('relation', (r.id, json.dumps(tags), json.dumps(members)))

    def _send_to_worker(self, type_, data):
        self.local_batch.append((type_, data))
        if len(self.local_batch) >= self.batch_limit:
            self.queue.put(self.local_batch)
            self.local_batch = []

    def flush(self):
        if self.local_batch:
            self.queue.put(self.local_batch)
            self.local_batch = []

class DBWorker(multiprocessing.Process):
    """Процесс воркер, который использует COPY для высокоскоростной загрузки."""
    def __init__(self, queue, settings, stats_queue):
        super().__init__()
        self.queue = queue
        self.settings = settings
        self.stats_queue = stats_queue
        self.batch_size = 50000

    def run(self):
        try:
            # Для немедленного завершения по Ctrl+C внутри воркера
            asyncio.run(self.main())
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Worker {self.name} crashed: {e}")

    async def main(self):
        conn = await asyncpg.connect(
            host=self.settings['host'],
            port=self.settings['port'],
            user=self.settings['user'],
            password=self.settings['password'],
            database=self.settings['database']
        )
        await conn.execute("SET search_path TO osm, public")
        
        batches = {
            'node': [],
            'way': [],
            'barrier': [],
            'relation': []
        }
        
        try:
            while True:
                items = self.queue.get()
                if items is None:
                    # Сбрасываем остатки
                    for table, data in batches.items():
                        if data: await self._flush(conn, table, data)
                    break
                
                for table, record in items:
                    batches[table].append(record)
                    if len(batches[table]) >= self.batch_size:
                        await self._flush(conn, table, batches[table])
                        batches[table] = []
        finally:
            await conn.close()

    async def _flush(self, conn, table_type, data):
        text_buf = io.StringIO()
        writer = csv.writer(text_buf, delimiter='\t', quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator='\n')

        def to_hex(wkb):
            return wkb.hex() if isinstance(wkb, bytes) else wkb

        try:
            if table_type == 'way':
                for r in data:
                    writer.writerow(['\\N' if x is None else x for x in (r[0], to_hex(r[1]), r[2], r[3], r[4], r[5], r[6])])
                
                data_bytes = text_buf.getvalue().encode('utf-8')
                async def source_gen(): yield data_bytes
                
                await conn.copy_to_table(
                    'ways', schema_name='osm', source=source_gen(), 
                    columns=['osm_id', 'geom', 'tags', 'highway', 'name', 'lanes', 'maxspeed'],
                    format='csv', delimiter='\t', null='\\N'
                )

            elif table_type == 'node':
                for r in data:
                    writer.writerow(['\\N' if x is None else x for x in (r[0], to_hex(r[1]), r[2])])
                
                data_bytes = text_buf.getvalue().encode('utf-8')
                async def source_gen(): yield data_bytes
                
                await conn.copy_to_table(
                    'nodes', schema_name='osm', source=source_gen(), 
                    columns=['osm_id', 'geom', 'tags'],
                    format='csv', delimiter='\t', null='\\N'
                )

            elif table_type == 'barrier':
                for r in data:
                    writer.writerow(['\\N' if x is None else x for x in (r[0], to_hex(r[1]), r[2], r[3], r[4])])
                
                data_bytes = text_buf.getvalue().encode('utf-8')
                async def source_gen(): yield data_bytes
                
                await conn.copy_to_table(
                    'barriers', schema_name='osm', source=source_gen(), 
                    columns=['osm_id', 'geom', 'tags', 'barrier_type', 'type'],
                    format='csv', delimiter='\t', null='\\N'
                )

            elif table_type == 'relation':
                for r in data:
                    writer.writerow(['\\N' if x is None else x for x in (r[0], r[1], r[2])])
                
                data_bytes = text_buf.getvalue().encode('utf-8')
                async def source_gen(): yield data_bytes
                
                await conn.copy_to_table(
                    'turn_restrictions', schema_name='osm', source=source_gen(), 
                    columns=['osm_id', 'tags', 'members'],
                    format='csv', delimiter='\t', null='\\N'
                )

            self.stats_queue.put(len(data))
        except Exception as e:
            logger.error(f"Error flushing to {table_type}: {e}")
        finally:
            text_buf.close()

class OSMPBFImporter:
    def __init__(self, pbf_path: str, num_workers: int = 3):
        self.pbf_path = pbf_path
        self.num_workers = num_workers
        self.queue = multiprocessing.Queue(maxsize=200000)
        self.stats_queue = multiprocessing.Queue()
        self.start_time = time.time()
        self.total_inserted = 0

    async def _manage_indices(self, mode='drop'):
        from services.common.config import load_settings
        settings = load_settings()
        conn = await asyncpg.connect(
            host=settings.db.host,
            user=settings.db.user,
            password=settings.db.password,
            database=settings.db.name,
            port=settings.db.port
        )
        try:
            if mode == 'drop':
                logger.info("Dropping indices and constraints for high-speed import...")
                queries = OSMQueries.DROP_INDEXES_WAYS + OSMQueries.DROP_INDEXES_NODES + OSMQueries.DROP_INDEXES_BARRIERS
            else:
                logger.info("Recreating indices and constraints...")
                queries = OSMQueries.CREATE_INDEXES_WAYS + OSMQueries.CREATE_INDEXES_NODES + OSMQueries.CREATE_INDEXES_BARRIERS
            
            for q in queries:
                try:
                    await conn.execute(q)
                except Exception as e:
                    logger.warning(f"Index operation failed: {q} -> {e}")
        finally:
            await conn.close()

    def _get_default_bbox(self) -> Optional[List[float]]:
        try:
            config_path = Path("/app/configs/data-processor/bboxes.yaml")
            if not config_path.exists():
                config_path = project_root / "configs" / "data-processor" / "bboxes.yaml"
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
                return cfg.get(cfg.get('default', 'moscow_mkad'), {}).get('coords')
        except: return None

    async def run(self):
        from services.common.config import load_settings
        settings = load_settings()
        db_settings = {
            'host': settings.db.host,
            'port': settings.db.port,
            'user': settings.db.user,
            'password': settings.db.password,
            'database': settings.db.name
        }

        # Шаг 0: Управление индексами
        await self._manage_indices('drop')
        
        # Шаг 1: Очистка и Инициализация
        conn = await asyncpg.connect(**db_settings)
        await conn.execute("CREATE SCHEMA IF NOT EXISTS osm;")
        await conn.execute("SET search_path TO osm, public")
        
        # Убеждаемся, что таблицы существуют (self-healing)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS osm.barriers (
                id BIGSERIAL PRIMARY KEY,
                osm_id BIGINT NOT NULL,
                geom geometry(Geometry, 4326) NOT NULL,
                tags JSONB NOT NULL DEFAULT '{}'::jsonb,
                barrier_type VARCHAR(50),
                type VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS osm.turn_restrictions (
                osm_id BIGINT PRIMARY KEY,
                tags JSONB NOT NULL DEFAULT '{}'::jsonb,
                members JSONB NOT NULL DEFAULT '[]'::jsonb
            );
        """)
        
        await conn.execute("TRUNCATE osm.ways, osm.nodes, osm.barriers, osm.turn_restrictions RESTART IDENTITY CASCADE;")
        await conn.close()

        # Шаг 2: Предварительный скан
        logger.info("Phase 1/2: Pre-scanning PBF...")
        counter = CountHandler()
        await asyncio.to_thread(counter.apply_file, self.pbf_path)
        total_objects = counter.count
        logger.success(f"PBF scanned: {total_objects} objects.")

        # Шаг 3: Запуск воркеров
        workers = []
        for i in range(self.num_workers):
            p = DBWorker(self.queue, db_settings, self.stats_queue)
            p.daemon = True # Позволяет воркерам умирать вместе с главным процессом
            p.start()
            workers.append(p)

        try:
            # Шаг 4: Извлечение
            logger.info("Phase 2/2: Extracting and Ingesting...")
            self.start_time = time.time()
            bbox = self._get_default_bbox()
            handler = PBFHandler(self.queue, bbox=bbox)
            
            logger.info("Phase 2/2: Extracting and inserting data...")
            extract_task = asyncio.create_task(asyncio.to_thread(handler.apply_file, self.pbf_path, locations=True))
            
            # Мониторинг прогресса
            while not extract_task.done():
                await asyncio.sleep(2)
                while not self.stats_queue.empty():
                    self.total_inserted += self.stats_queue.get()
                
                speed = self.total_inserted / (time.time() - self.start_time) if (time.time() - self.start_time) > 0 else 0
                logger.info(f"Progress: {handler.found_count}/{total_objects} handled, {self.total_inserted} inserted. Speed: {speed:.1f} obj/sec")

            await extract_task
            handler.flush()
            logger.success("Extraction finished. Draining queue...")
            
            # Отправляем стоп-сигналы
            for _ in range(self.num_workers): self.queue.put(None)
            
            # Ждем завершения
            for w in workers:
                w.join(timeout=2)
                if w.is_alive(): w.terminate()

            # Шаг 5: Пост-импортная индексация
            await self._manage_indices('create')
            
            dt = time.time() - self.start_time
            logger.success(f"PBF Import V2 Finished in {dt:.1f}s!")

        except KeyboardInterrupt:
            logger.warning("Interrupted by user. Terminating processes...")
            for w in workers:
                if w.is_alive():
                    w.terminate()
            raise
        finally:
            # Очистка стоп-сигналов (необязательно)
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", required=True)
    args = parser.parse_args()
    
    # Увеличиваем лимит рекурсии для глубоких связей
    sys.setrecursionlimit(2000)
    
    try:
        asyncio.run(OSMPBFImporter(args.pbf).run())
    except KeyboardInterrupt:
        sys.exit(1)

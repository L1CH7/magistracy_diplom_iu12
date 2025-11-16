"""
ПРИМЕР: Загрузка данных через Data Processor API с прогресс-баром.

Использование:
1. Запустить Data Processor: docker compose up data-processor
2. Запустить скрипт: python EXAMPLE_DATA_FETCH.py
3. Следить за логами: grep "tiles_fetch_progress" logs/client/app.log

Формат лога прогресса:
    tiles_fetch_progress loaded=155 total=1202
"""

import asyncio
import aiohttp
import yaml
from loguru import logger as log
from pathlib import Path


class DataFetchExample:
    """Пример загрузки данных через Data Processor API."""
    
    def __init__(self):
        # Загрузка конфига
        config_path = Path("configs/client/data.yaml")
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        # Data Processor endpoint (НЕ server:8000, а отдельный сервис!)
        self.data_processor_url = "http://localhost:8005"
        
        # BBOX для загрузки (moscow_mkad из конфига)
        self.bbox = self.config['bboxes']['moscow_mkad']['coords']
        
        log.info("data_fetch_initialized",
                 bbox=self.bbox,
                 endpoint=self.data_processor_url)
    
    async def fetch_osm_data(self):
        """Запуск загрузки OSM данных."""
        async with aiohttp.ClientSession() as session:
            # 1. Запуск fetch job
            url = f"{self.data_processor_url}/api/v1/data/fetch"
            payload = {
                "bbox": self.bbox,
                "highway_types": []  # Пустой список = все типы по умолчанию
            }
            
            log.info("fetch_job_starting", bbox=self.bbox)
            
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    log.error("fetch_job_failed",
                              status=resp.status,
                              text=await resp.text())
                    return
                
                data = await resp.json()
                job_id = data['job_id']
                log.info("fetch_job_started", job_id=job_id)
            
            # 2. Polling job status
            await self._poll_job_status(session, job_id)
    
    async def _poll_job_status(self, session: aiohttp.ClientSession,
                               job_id: str):
        """Polling статуса job с выводом прогресса."""
        url = f"{self.data_processor_url}/api/v1/data/jobs/{job_id}"
        
        while True:
            await asyncio.sleep(2)  # Poll каждые 2 секунды
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.error("status_poll_failed", status=resp.status)
                    break
                
                status = await resp.json()
                
                # Статус может быть: started, running, done, error
                state = status.get('status', 'unknown')
                progress = status.get('progress', 0.0)
                
                if state == 'error':
                    error = status.get('error', 'Unknown error')
                    log.error("fetch_job_error", job_id=job_id, error=error)
                    break
                
                elif state == 'done':
                    # Готово!
                    total_ways = status.get('total_ways', 0)
                    log.info("fetch_job_completed", 
                             job_id=job_id,
                             total_ways=total_ways)
                    
                    # ФИНАЛЬНЫЙ ПРОГРЕСС (для grep)
                    log.info("tiles_fetch_progress", 
                             loaded=total_ways, 
                             total=total_ways)
                    break
                
                else:
                    # running или started - показываем прогресс
                    # Примечание: progress - это доля (0.0 - 1.0)
                    # Конвертируем в "загружено X тайлов"
                    
                    # Для демонстрации предположим, что всего ~1200 тайлов
                    # В реальности можно получить из status.get('total_tiles')
                    estimated_total = status.get('estimated_tiles', 1200)
                    loaded = int(progress * estimated_total)
                    
                    # ПРОГРЕСС ЛОГ (формат для grep)
                    log.info("tiles_fetch_progress", 
                             loaded=loaded, 
                             total=estimated_total)


async def main():
    """Точка входа."""
    fetcher = DataFetchExample()
    await fetcher.fetch_osm_data()


if __name__ == "__main__":
    # Настройка loguru
    log.add("logs/data_fetch_example.log", 
            rotation="10 MB",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    
    asyncio.run(main())


"""
GREP команды для отслеживания прогресса:

1. Следить за прогрессом в реальном времени:
   tail -f logs/data_fetch_example.log | grep tiles_fetch_progress

2. Проверить финальный результат:
   grep "tiles_fetch_progress.*loaded.*total" logs/data_fetch_example.log | tail -1

3. Отфильтровать только цифры:
   grep -oP 'loaded=\K\d+|total=\K\d+' logs/data_fetch_example.log

ПРИМЕР ВЫВОДА:
2025-01-19 15:30:12 | INFO | tiles_fetch_progress loaded=0 total=1200
2025-01-19 15:30:14 | INFO | tiles_fetch_progress loaded=48 total=1200
2025-01-19 15:30:16 | INFO | tiles_fetch_progress loaded=155 total=1200
2025-01-19 15:30:18 | INFO | tiles_fetch_progress loaded=312 total=1200
...
2025-01-19 15:30:45 | INFO | tiles_fetch_progress loaded=1200 total=1200
"""

import httpx
from loguru import logger
from typing import Dict, List, Tuple

class OSMDownloader:
    def __init__(self, overpass_url: str = "http://overpass-api.de/api/interpreter"):
        self.overpass_url = overpass_url

    async def download_bbox(self, bbox: Tuple[float, float, float, float]) -> Dict:
        """
        Download OSM data for bbox (south, west, north, east).
        Returns a dict (JSON response from Overpass).
        """
        south, west, north, east = bbox
        
        # Query for ways with generic highway tag, their nodes, and relations (restrictions)
        query = f"""
        [out:json][timeout:60];
        (
          way["highway"]({south},{west},{north},{east});
          relation["type"="restriction"]({south},{west},{north},{east});
        );
        (._;>;);
        out body;
        """
        
        logger.info(f"Downloading OSM data for bbox: {bbox}")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.overpass_url, data={"data": query}, timeout=90.0)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Downloaded {len(data.get('elements', []))} elements.")
                return data
            except Exception as e:
                logger.error(f"Failed to download OSM data: {e}")
                raise

downloader = OSMDownloader()

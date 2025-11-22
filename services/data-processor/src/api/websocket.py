"""
WebSocket API for real-time data updates.

Provides /ws/data_updates endpoint for clients to receive:
- OSM data load completion events
- Way count updates after graph saves
- MVT tile invalidation notifications
"""

from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from loguru import logger
from typing import Set
import asyncio

router = APIRouter()

# Connected WebSocket clients
connected_clients: Set[WebSocket] = set()


@router.websocket("/ws/data_updates")
async def websocket_data_updates(websocket: WebSocket):
    """
    WebSocket endpoint for real-time data update notifications.
    
    Clients receive events:
    - {"type": "ways_updated", "count": N} - after OSM data save
    - {"type": "tiles_invalidated"} - when MVT cache should refresh
    """
    await websocket.accept()
    connected_clients.add(websocket)
    
    logger.info(
        f"WebSocket client connected "
        f"(total: {len(connected_clients)})"
    )
    
    try:
        # Keep connection alive with ping/pong
        while True:
            try:
                # Wait for messages from client (heartbeat)
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                if message == "ping":
                    await websocket.send_text("pong")
                    
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await websocket.send_json({"type": "ping"})
                
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(
            f"WebSocket client disconnected "
            f"(remaining: {len(connected_clients)})"
        )
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=e)
        connected_clients.discard(websocket)


async def broadcast_ways_updated(count: int):
    """
    Broadcast ways_updated event to all connected clients.
    
    Called after OSM data is saved to database.
    """
    if not connected_clients:
        return
    
    message = {
        "type": "ways_updated",
        "count": count
    }
    
    logger.info(f"Broadcasting ways_updated: {count} ways")
    
    # Send to all clients (parallel)
    await asyncio.gather(
        *[ws.send_json(message) for ws in connected_clients],
        return_exceptions=True
    )


async def broadcast_tiles_invalidated():
    """
    Broadcast tiles_invalidated event to all connected clients.
    
    Called when MVT cache should be refreshed.
    """
    if not connected_clients:
        return
    
    message = {"type": "tiles_invalidated"}
    
    logger.info("Broadcasting tiles_invalidated")
    
    await asyncio.gather(
        *[ws.send_json(message) for ws in connected_clients],
        return_exceptions=True
    )

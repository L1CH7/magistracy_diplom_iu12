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
                # Wait for messages from client
                message = await websocket.receive()
                
                if message["type"] == "websocket.receive":
                    text = message.get("text")
                    if not text:
                         continue
                         
                    try:
                        import json
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        if text == "ping":
                             await websocket.send_json({"type": "pong"})
                        continue

                    if not isinstance(data, dict):
                        continue
                
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    
                elif data.get("type") == "config":
                    # Client sent LOD configuration
                    # format: {"type": "config", "lod": {...}}
                    lod_config = data.get("lod")
                    if lod_config:
                        logger.info("Received LOD config from client via WebSocket")
                        logger.trace(f"Client LOD config: {lod_config}")
                        
                        # Update MVT handler config via app state
                        if hasattr(websocket.app.state, "mvt_handler"):
                            if hasattr(websocket.app.state.mvt_handler, "update_lod_config"):
                                websocket.app.state.mvt_handler.update_lod_config(lod_config)
                                
                                # Broadcast invalidation to ALL clients (including self)
                                # This forces them to reload tiles with new LOD
                                await broadcast_tiles_invalidated()
                                
                                await websocket.send_json({
                                    "type": "ack", 
                                    "message": "LOD config updated"
                                })
                    
            except asyncio.TimeoutError:
                # Send ping to keep alive
                # await websocket.send_json({"type": "ping"})
                pass
                
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

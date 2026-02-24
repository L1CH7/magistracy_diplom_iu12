"""
WebSocket client for Coordinator Service.

Receives real-time agent positions.
"""

import asyncio
import json
from typing import Callable, Optional

import websockets
from loguru import logger


class DataSocketClient:
    """
    WebSocket client for Data Processor updates.
    
    Receives real-time notifications about tile downloads.
    
    Usage:
        client = DataSocketClient("ws://localhost:8000")
        client.on_message = lambda data: print(data)
        await client.connect()
    """
    
    def __init__(self, gateway_url: str):
        # Convert HTTP/HTTPS to WS/WSS
        if gateway_url.startswith("https"):
            ws_base = gateway_url.replace("https", "wss")
        elif gateway_url.startswith("http"):
            ws_base = gateway_url.replace("http", "ws")
        else:
            ws_base = f"ws://{gateway_url}"
            
        self.url = f"{ws_base}/ws/data_updates"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        
        # Callback for updates
        self.on_message: Optional[Callable] = None
        self.on_connect: Optional[Callable] = None
        
        logger.info(f"DataSocketClient created: {self.url}")
    
    async def connect(self):
        """Connect to Data Processor WebSocket."""
        try:
            self.ws = await websockets.connect(self.url)
            self.connected = True
            
            logger.success(f"Connected to Data Socket: {self.url}")
            
            if self.on_connect:
                try:
                    # If it's a coroutine, we should await it? 
                    # But this is inside async connect(), so we can await.
                    if asyncio.iscoroutinefunction(self.on_connect):
                        await self.on_connect()
                    else:
                        self.on_connect()
                except Exception as e:
                    logger.error(f"Error in on_connect callback: {e}")
            
            # Start receiving loop
            await self._receive_loop()
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            # Don't raise, just log - we might retry
            self.connected = False
            raise e

    async def send_lod_config(self, lod_config: dict):
        """Send LOD configuration to server."""
        if not self.ws or not self.connected:
            logger.warning("Cannot send LOD config: WebSocket not connected")
            return
            
        message = {
            "type": "config",
            "lod": lod_config
        }
        
        try:
            await self.ws.send(json.dumps(message))
            logger.info("Sent LOD config to server")
        except Exception as e:
            logger.error(f"Failed to send LOD config: {e}")
    
    async def disconnect(self):
        """Disconnect from Data Processor."""
        if self.ws:
            await self.ws.close()
            self.connected = False
            
            logger.info("Disconnected from Data Socket")
    
    async def _receive_loop(self):
        """Receive updates."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    # Call callback
                    if self.on_message:
                        self.on_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON message: {message}")
                
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
            
        except Exception as e:
            logger.error(f"WebSocket receive error: {e}", exc_info=e)

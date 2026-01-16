"""
WebSocket client for Coordinator Service.

Receives real-time agent positions.
"""

import asyncio
import json
from typing import Callable, Optional

import websockets
from loguru import logger


class CoordinatorWSClient:
    """
    WebSocket client for Coordinator Service.
    
    Usage:
        client = CoordinatorWSClient("ws://localhost:8002/ws/positions")
        client.on_positions = lambda data: print(data)
        await client.connect()
    """
    
    def __init__(self, url: str):
        self.url = url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        
        # Callback for position updates
        self.on_positions: Optional[Callable] = None
        
        logger.info(f"CoordinatorWSClient created: {url}")
    
    async def connect(self):
        """Connect to Coordinator WebSocket."""
        try:
            self.ws = await websockets.connect(self.url)
            self.connected = True
            
            logger.success(f"Connected to Coordinator: {self.url}")
            
            # Start receiving loop
            asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Coordinator."""
        if self.ws:
            await self.ws.close()
            self.connected = False
            
            logger.info("Disconnected from Coordinator")
    
    async def _receive_loop(self):
        """Receive position updates."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                
                # Call callback
                if self.on_positions:
                    self.on_positions(data)
                
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
            
        except Exception as e:
            logger.error(f"WebSocket receive error: {e}", exc_info=e)

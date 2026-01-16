from fastapi import WebSocket
from loguru import logger
import websockets
from starlette.websockets import WebSocketDisconnect

async def websocket_proxy(client_ws: WebSocket, target_url: str):
    await client_ws.accept()
    logger.info(f"WebSocket proxy started: -> {target_url}")
    
    try:
        async with websockets.connect(target_url) as server_ws:
            # Create tasks for bidirectional communication
            import asyncio
            
            async def forward_to_server():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await server_ws.send(data)
                except WebSocketDisconnect:
                    logger.info("Client disconnected")
                except Exception as e:
                    logger.error(f"Error forwarding to server: {e}")

            async def forward_to_client():
                try:
                    async for message in server_ws:
                        await client_ws.send_text(message)
                except Exception as e:
                    logger.error(f"Error forwarding to client: {e}")
            
            # Run both tasks
            task1 = asyncio.create_task(forward_to_server())
            task2 = asyncio.create_task(forward_to_client())
            
            done, pending = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                
    except Exception as e:
        logger.error(f"WebSocket proxy error: {e}")
        try:
            await client_ws.close(code=1011)
        except:
            pass

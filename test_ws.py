import asyncio
import websockets

async def test_connection():
    uri = "ws://localhost:8000/ws/data_updates"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected successfully!")
            await websocket.send("ping")
            print("Sent ping")
            # Wait for any message (broadcast updates)
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"Received: {msg}")
            except asyncio.TimeoutError:
                print("No message received in 5s (expected if no updates)")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())

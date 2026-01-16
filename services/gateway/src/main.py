import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from src.config import settings
from src.proxy import reverse_proxy
from src.ws_proxy import websocket_proxy
from loguru import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gateway Service")
    yield
    logger.info("Stopping Gateway Service")

app = FastAPI(
    title="Navigation MAS Gateway",
    version="2.0.0",
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "gateway"}

# WebSocket Proxy
@app.websocket("/ws/data_updates")
async def ws_data_updates(websocket: WebSocket):
    # Construct target URL (replace http/https with ws/wss)
    target = settings.DATA_PROCESSOR_URL.replace("http://", "ws://").replace("https://", "wss://")
    await websocket_proxy(websocket, f"{target}/ws/data_updates")

# API Routing (Gateway Pattern)
# Rewrites gateway/{feature}/* -> service/api/v1/{feature}/*

@app.api_route("/tiles/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_tiles(request: Request, path: str):
    # tiles -> data-processor/api/v1/tiles
    return await reverse_proxy(request, path, settings.DATA_PROCESSOR_URL, f"/api/v1/tiles/{path}")

@app.api_route("/routing/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_routing(request: Request, path: str):
    # routing -> router/api/v1/route
    return await reverse_proxy(request, path, settings.ROUTER_URL, f"/api/v1/route/{path}")

@app.api_route("/graph/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_graph(request: Request, path: str):
    # graph -> router/api/v1/graph
    return await reverse_proxy(request, path, settings.ROUTER_URL, f"/api/v1/graph/{path}")

@app.api_route("/debug/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_debug(request: Request, path: str):
    # debug -> data-processor/api/v1/debug
    return await reverse_proxy(request, path, settings.DATA_PROCESSOR_URL, f"/api/v1/debug/{path}")

@app.api_route("/status/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_status(request: Request, path: str):
    # status -> data-processor/api/v1/status
    return await reverse_proxy(request, path, settings.DATA_PROCESSOR_URL, f"/api/v1/status/{path}")

# Compatibility for direct /api/v1 calls (optional, but good to keep)
@app.api_route("/api/v1/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_api_v1(request: Request, service: str, path: str):
    if service == "tiles":
         return await reverse_proxy(request, path, settings.DATA_PROCESSOR_URL, f"/api/v1/tiles/{path}")
    elif service == "routing":
         return await reverse_proxy(request, path, settings.ROUTER_URL, f"/api/v1/route/{path}")
    elif service == "graph":
         return await reverse_proxy(request, path, settings.ROUTER_URL, f"/api/v1/graph/{path}")
    elif service == "debug":
         return await reverse_proxy(request, path, settings.DATA_PROCESSOR_URL, f"/api/v1/debug/{path}")
    
    return JSONResponse(status_code=404, content={"message": "Service not found"})

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)

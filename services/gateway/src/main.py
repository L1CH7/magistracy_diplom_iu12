import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from services.common.config import Settings, config_loader
from src.proxy import reverse_proxy
from src.ws_proxy import websocket_proxy
from loguru import logger

# Load Global Settings
settings = Settings()

import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gateway Service")
    # Initialize shared AsyncClient with connection pooling
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    app.state.client = httpx.AsyncClient(limits=limits, timeout=30.0)
    yield
    # Cleanup
    await app.state.client.aclose()
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
    # Using data_processor service from settings
    data_processor_url = settings.services.data_processor.url
    target = data_processor_url.replace("http://", "ws://").replace("https://", "wss://")
    await websocket_proxy(websocket, f"{target}/ws/data_updates")

# --- Dynamic Route Registration ---

def register_routes():
    try:
        # Load registry
        # config_loader handles path resolution (e.g. searching in configs/gateway/...)
        registry = config_loader.load("gateway/route_registry.yaml")
        
        for route in registry.get("routes", []):
            path_prefix = route["path"]
            service_name = route["service"]
            internal_prefix = route["internal_prefix"]
            
            # Resolve service URL dynamically
            try:
                service_config = getattr(settings.services, service_name)
                target_base_url = service_config.url
            except AttributeError:
                logger.error(f"Service '{service_name}' not found in settings. Skipping route {path_prefix}")
                continue

            # We need to capture variables in closure or use a factory
            # to avoid Loop Variable Capture issue.
            # Define handler factory
            def create_handler(target_url: str, internal_prefix: str):
                async def handler(request: Request, path: str = ""):
                    # Construct full target path
                    # e.g. path_prefix="/tiles", internal_prefix="/api/v1/tiles"
                    # request to /tiles/foo/bar -> path="foo/bar"
                    # target -> target_url + /api/v1/tiles/foo/bar
                    
                    # Ensure internal_prefix doesn't have double slashes if path is empty
                    final_path = f"{internal_prefix}/{path}" if path else internal_prefix
                    # clean double slashes if any (though reverse_proxy might handle it, better be safe)
                    # simpler: reverse_proxy takes target_base and path
                    return await reverse_proxy(request, path, target_url, final_path, request.app.state.client)
                return handler

            handler_func = create_handler(target_base_url, internal_prefix)
            
            # Register route: /prefix/{path:path}
            # Note: We configure it to handle all methods
            app.add_api_route(
                path=f"{path_prefix}/{{path:path}}", 
                endpoint=handler_func, 
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
            )
            
            # Also register the root exact match if needed (e.g. /tiles -> /api/v1/tiles)
            # FastAPI's {path:path} usually matches subpaths. 
            # To catch the exact /tiles, we might need another route or rely on client sending /tiles/
            # Pattern "/tiles/{path:path}" matches "/tiles/something", but NOT "/tiles".
            # Let's add the exact path too.
            
            def create_root_handler(target_url: str, internal_prefix: str):
                async def root_handler(request: Request):
                     return await reverse_proxy(request, "", target_url, internal_prefix, request.app.state.client)
                return root_handler

            root_handler_func = create_root_handler(target_base_url, internal_prefix)
            app.add_api_route(
                path=path_prefix,
                endpoint=root_handler_func,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
            )

            logger.info(f"Registered dynamic route: {path_prefix} -> {service_name} ({target_base_url}{internal_prefix})")

    except Exception as e:
        logger.error(f"Failed to load route registry: {e}")
        # In production, we might want to crash if routes fail to load.
        raise e

# Execute registration
register_routes()

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)


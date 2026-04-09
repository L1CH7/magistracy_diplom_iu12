import uvicorn
from fastapi import FastAPI, Request, WebSocket, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from services.common.config import Settings, config_loader
from src.proxy import reverse_proxy
from src.ws_proxy import websocket_proxy
from loguru import logger

# Load Global Settings
settings = Settings()

import zmq
import zmq.asyncio
import struct
import httpx
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gateway Service")
    # Initialize shared AsyncClient with connection pooling
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    app.state.client = httpx.AsyncClient(limits=limits, timeout=60.0)
    
    # Initialize Async ZMQ Context for Traffic Core control
    app.state.zmq_ctx = zmq.asyncio.Context()
    app.state.zmq_lock = asyncio.Lock() # Lock for thread-safe socket usage
    app.state.zmq_socket = app.state.zmq_ctx.socket(zmq.REQ)
    app.state.zmq_socket.connect("tcp://traffic-core:5555")
    
    yield
    # Cleanup
    await app.state.client.aclose()
    app.state.zmq_socket.close()
    app.state.zmq_ctx.term()
    logger.info("Stopping Gateway Service")

async def send_core_command(app, payload: bytes, timeout: float = 5.0):
    """
    Send binary command to Traffic Core via ZMQ REQ/REP.
    Uses asyncio.Lock to ensure serialized usage of the REQ socket.
    """
    async with app.state.zmq_lock:
        socket = app.state.zmq_socket
        try:
            await socket.send(payload)
            # Use asyncio.wait_for for robust timeout handling
            return await asyncio.wait_for(socket.recv(), timeout=timeout)
        except (asyncio.TimeoutError, zmq.ZMQError) as e:
            logger.error(f"Core communication error: {e}. Recreating ZMQ socket...")
            socket.close(linger=0)
            # Recreate socket
            app.state.zmq_socket = app.state.zmq_ctx.socket(zmq.REQ)
            app.state.zmq_socket.connect("tcp://traffic-core:5555")
            raise HTTPException(status_code=504, detail=f"Core Timeout or Error: {str(e)}")

app = FastAPI(
    title="Navigation MAS Gateway",
    version="2.0.0",
    lifespan=lifespan
)

@app.post("/api/v1/sim/control")
async def sim_control(request: Request):
    """
    Proxy simulation commands (START, STOP, SET_SPEED, STEP) to Traffic Core via ZeroMQ binary protocol.
    Expected JSON: { "opcode": int, "num_agents": int, "acceleration": float, "fps": float, "chaos": float, "duration_sec": int, "respawn_enabled": bool }
    """
    try:
        data = await request.json()
        opcode = int(data.get("opcode", 1))
        num_agents = int(data.get("num_agents", 50000))
        duration = int(data.get("duration_sec", 0))
        asf = int(data.get("asf", 50))
        accel = float(data.get("acceleration", 1.0))
        telemetry_fps = float(data.get("fps", 25.0))
        chaos_factor = float(data.get("chaos", 0.0))
        respawn = 1 if data.get("respawn_enabled", True) else 0

        # Pack binary structure: < B I I I H f f f 3B (30 bytes, packed)
        # B=opcode, I=duration(session_id), I=request, I=num_agents, H=asf, f=accel, f=fps, f=chaos, 3B=respawn+reserved
        payload = struct.pack("<BIIIHfff3B", opcode, duration, 0, num_agents, asf, accel, telemetry_fps, chaos_factor, respawn, 0, 0)
        
        # Call encapsulated ZMQ logic. Use 30s for START (opcode 1).
        timeout = 30.0 if opcode == 1 else 5.0
        ack_raw = await send_core_command(request.app, payload, timeout=timeout)
        
        if len(ack_raw) < 2:
            return JSONResponse({"status": "error", "message": "Invalid ACK from Traffic Core"}, status_code=500)
        
        success, state = struct.unpack("<BB", ack_raw)
        state_map = {0: "IDLE", 1: "RUNNING", 2: "PAUSED"}
        return {
            "status": "success" if success else "failed",
            "engine_state": state_map.get(state, "IDLE")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sim control error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/routing/calculate")
async def calculate_route(request: Request):
    """
    Proxy legacy routing requests to Traffic Core via binary ZMQ.
    Handles multi-point paths and returns full geometry.
    """
    try:
        body = await request.json()
        waypoints = body.get("waypoints", [])
        if len(waypoints) < 2:
            return JSONResponse({"status": "error", "detail": "At least 2 waypoints required"}, status_code=400)
        
        logger.debug(f"Calculating route for {len(waypoints)} points")
        # CommandRequest (30b) + OneOffRouteHeader (5b)
        # opcode=5 (ROUTE_ONE_OFF), followed by reserved/default fields for agents/sim params
        cmd_head = struct.pack("<BIIIHfff3B", 5, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0, 0, 0)
        # OneOffRouteHeader: num_waypoints (B), start_time (I)
        route_head = struct.pack("<BI", len(waypoints), 0) 
        
        points_data = b""
        for pt in waypoints:
            points_data += struct.pack("<ff", pt["lon"], pt["lat"])
        
        full_request = cmd_head + route_head + points_data
        
        socket = request.app.state.zmq_socket
        await socket.send(full_request)
        
        # 2. Receive Multi-part Response
        # We MUST use recv_multipart() for REQ sockets to consume all frames at once
        frames = await socket.recv_multipart()
        
        if len(frames) < 5:
            logger.error(f"Invalid multi-part response: expected 5+ frames, got {len(frames)}")
            return JSONResponse({"status": "error", "message": "Corrupted response from Traffic Core"}, status_code=500)

        # Frame 1: Header (19 bytes: B, H, I, f, f, f)
        res_header_raw = frames[0]
        # B = success, H = num_edges (2), I = total_pts (4), f = dist, f = time, f = calc_ms
        success, num_edges, total_pts, dist, total_time, calc_ms = struct.unpack("<BHIfff", res_header_raw)
        
        if not success:
            return JSONResponse({"status": "error", "detail": "Routing failed"}, status_code=404)
        
        # Frame 2: EdgeIDs (uint32)
        edge_ids = struct.unpack(f"<{num_edges}I", frames[1])
        
        # Frame 3: ETAs (float)
        etas = struct.unpack(f"<{num_edges}f", frames[2])
        
        # Frame 4: PointCounts (uint16)
        point_counts = struct.unpack(f"<{num_edges}H", frames[3])
        
        # Frame 5: GeometryData (float x, float y)
        all_points = struct.unpack(f"<{total_pts * 2}f", frames[4])
        
        # 3. Reconstruct JSON Response
        segments = []
        pt_idx = 0
        for i in range(num_edges):
            count = point_counts[i]
            edge_coords = []
            for _ in range(count):
                lon = all_points[pt_idx * 2]
                lat = all_points[pt_idx * 2 + 1]
                edge_coords.append([lon, lat])
                pt_idx += 1
            
            segments.append({
                "edge_id": edge_ids[i],
                "from_node": 0, # Omitted or dummy
                "to_node": 0,
                "distance_m": 0.0, # Could be calculated but usually provided at segment level
                "speed_limit": 0.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": edge_coords
                }
            })
            
        return {
            "status": "success",
            "calculation_time_ms": calc_ms,
            "routes": [{
                "route_id": 0,
                "segments": segments,
                "total_distance_m": dist,
                "estimated_time_sec": total_time,
                "diversity_score": 1.0,
                "edge_ids": list(edge_ids)
            }]
        }
        
    except zmq.Again:
        return JSONResponse({"status": "error", "message": "Traffic Core timeout"}, status_code=504)
    except Exception as e:
        logger.error(f"Routing calculate error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

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
            # Router: Graph Management (Moved to ZMQ/Daemon if needed, removing legacy HTTP proxy)
            # - path: "/routing"
            #   service: "router"
            #   internal_prefix: "/api/v1/routing"
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

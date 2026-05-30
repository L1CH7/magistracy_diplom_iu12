import zmq
import struct
import time
import requests
import pytest
from loguru import logger

# --- Constants aligned with telemetry_protocol.hpp ---
GATEWAY_URL = "http://localhost:8000/routing/calculate"
DAEMON_ADDR = "tcp://localhost:5555"
SUB_ADDR = "tcp://localhost:5556"

RES_HEADER_SIZE = 19 # OneOffRouteResponseHeader (B, H, I, f, f, f)
TEL_HEADER_SIZE = 16 # TelemetryHeader
AGENT_STATE_SIZE = 12 # AgentState

# --- Simulation Parameters ---
TARGET_AGENTS = 2000
TARGET_SIM_DURATION = 300.0  # Seconds of simulated time
TARGET_ACCEL = 20.0

@pytest.fixture(scope="session")
def zmq_context():
    context = zmq.Context()
    yield context
    context.term()

@pytest.fixture
def cmd_client(zmq_context):
    socket = zmq_context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 60000) # 60s timeout for heavy spawning
    socket.connect(DAEMON_ADDR)
    yield socket
    socket.close()

@pytest.fixture
def telemetry_sub(zmq_context):
    socket = zmq_context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.RCVHWM, 10000) 
    socket.setsockopt(zmq.RCVTIMEO, 1000)
    socket.connect(SUB_ADDR)
    time.sleep(0.3) 
    yield socket
    socket.close()

def test_routing_latency_breakdown():
    """Verify routing latency and payload overhead via Gateway breakdown."""
    payload = {
        "waypoints": [
            {"lat": 55.7558, "lon": 37.6173},
            {"lat": 55.7517, "lon": 37.6184}
        ]
    }
    
    start_time = time.perf_counter()
    response = requests.post(GATEWAY_URL, json=payload, timeout=5)
    end_time = time.perf_counter()
    
    rtt_ms = (end_time - start_time) * 1000
    assert response.status_code == 200, f"Gateway error: {response.text}"
    
    data = response.json()
    core_logic_ms = data.get("calculation_time_ms", 0.0) 
    net_overhead_ms = rtt_ms - core_logic_ms
    
    logger.info("Routing Performance Profile:")
    logger.info(f"  - Total RTT:    {rtt_ms:.2f}ms")
    logger.info(f"  - Core Logic:   {core_logic_ms:.2f}ms")
    logger.info(f"  - Net Delay:    {net_overhead_ms:.2f}ms")
    
    assert rtt_ms < 500
    assert len(data['routes'][0]['edge_ids']) > 0

def test_simulation_stress(cmd_client, telemetry_sub):
    """Stress test simulation using simulated time for faster-than-realtime verification."""
    
    # 1. Start Simulation
    start_cmd = struct.pack("<BIIIHfB", 1, 0, 0, TARGET_AGENTS, 10, TARGET_ACCEL, 0)
    logger.info("Starting Stress Test:")
    logger.info(f"  - Target Agents: {TARGET_AGENTS}")
    logger.info(f"  - Target Accel:  {TARGET_ACCEL}x")
    logger.info(f"  - Sim Duration:  {TARGET_SIM_DURATION}s")
    
    cmd_client.send(start_cmd)
    ack = cmd_client.recv()
    success, state = struct.unpack("<BB", ack)
    assert success, "Engine rejected START command"
    
    # 2. Profile Telemetry
    logger.info(f"Monitoring simulated progress (expecting {TARGET_SIM_DURATION}s)...")
    packets = 0
    total_bytes = 0
    actual_agents = 0
    start_sim_time = None
    last_sim_time = 0
    
    wall_start = time.time()
    MAX_WALL_TIMEOUT = 60.0 # Safety wall-clock timeout
    
    while True:
        # Check Wall-clock Safety
        if time.time() - wall_start > MAX_WALL_TIMEOUT:
            logger.warning("Reached wall-clock safety timeout (60s)")
            break

        try:
            frames = telemetry_sub.recv_multipart()
            if not frames: continue
            
            header_raw = frames[0]
            if len(header_raw) != TEL_HEADER_SIZE: continue
            
            packets += 1
            total_bytes += sum(len(f) for f in frames)
            
            tick_id, sim_time, tps, current_agents = struct.unpack("<IffI", header_raw)
            actual_agents = current_agents
            
            if start_sim_time is None:
                start_sim_time = sim_time
                logger.debug(f"Initial Sim Time: {start_sim_time:.2f}s")
            
            last_sim_time = sim_time
            
            # Check Sim-time Duration
            if (sim_time - start_sim_time) >= TARGET_SIM_DURATION:
                logger.info(f"Target sim duration reached at tick {tick_id}")
                break
                
        except zmq.Again:
            continue

    wall_elapsed = time.time() - wall_start
    real_sim_progress = last_sim_time - (start_sim_time or 0)
    throughput = (total_bytes * 8) / (max(wall_elapsed, 0.1) * 1024)
    
    logger.info(f"Results (Final Sim Time: {last_sim_time:.2f}s):")
    logger.info(f"  - Real Wall Time: {wall_elapsed:.2f}s")
    logger.info(f"  - Sim Progress:   {real_sim_progress:.2f}s")
    logger.info(f"  - Avg Throughput: {throughput:.2f} Kbps")
    logger.info(f"  - Total Packets:  {packets}")
    logger.info(f"  - Current Agents: {actual_agents}")

    # 3. Validation
    if packets == 0:
        pytest.fail("No telemetry packets received.")
    
    assert 0 < actual_agents <= TARGET_AGENTS, f"Simulated {actual_agents}, expected max {TARGET_AGENTS}"
    assert real_sim_progress >= TARGET_SIM_DURATION * 0.95, "Failed to reach target sim duration"

    # 4. Stop Simulation
    stop_cmd = struct.pack("<BIIIHfB", 2, 0, 0, 0, 0, 0.0, 0)
    cmd_client.send(stop_cmd)
    cmd_client.recv()

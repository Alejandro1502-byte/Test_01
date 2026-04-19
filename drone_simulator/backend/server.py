"""
DRONE SIMULATOR – Backend Server
FastAPI + WebSocket + MAVLink/SITL bridge
"""

import asyncio
import json
import math
import time
import uuid
import random
import os
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from core.drone import Drone, DroneMode, FlightPhase
from core.mission_planner import MissionPlanner
from core.swarm_manager import SwarmManager
from terrain.elevation import TerrainProvider
from mavlink.sitl_bridge import SITLBridge

# ─── App setup ───────────────────────────────────────────────────────────────
app = FastAPI(title="Drone Sim Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas absolutas — funcionan desde cualquier directorio de trabajo
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

# Servir /css/... y /js/... directamente (el HTML los pide así)
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js",  StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")),  name="js")

@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# ─── Global state ────────────────────────────────────────────────────────────
terrain    = TerrainProvider()
planner    = MissionPlanner(terrain)
swarm_mgr  = SwarmManager()
sitl       = SITLBridge()

# Connected WebSocket clients
clients: Dict[str, WebSocket] = {}

# Active simulation loop task
sim_task: Optional[asyncio.Task] = None
sim_running = False

# ─── WebSocket hub ───────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    cid = str(uuid.uuid4())[:8]
    clients[cid] = ws
    print(f"[WS] Client connected: {cid}")

    try:
        await ws.send_json({"type": "hello", "client_id": cid,
                            "drones": swarm_mgr.serialize_all()})
        async for raw in ws.iter_text():
            msg = json.loads(raw)
            await handle_client_message(cid, ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(cid, None)
        print(f"[WS] Client disconnected: {cid}")


async def broadcast(payload: dict):
    """Send a message to all connected clients."""
    dead = []
    for cid, ws in clients.items():
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(cid)
    for cid in dead:
        clients.pop(cid, None)


# ─── Message router ──────────────────────────────────────────────────────────
async def handle_client_message(cid: str, ws: WebSocket, msg: dict):
    t = msg.get("type")

    if t == "ping":
        await ws.send_json({"type": "pong"})

    elif t == "add_drone":
        drone = swarm_mgr.add_drone(msg)
        await broadcast({"type": "drone_added", "drone": drone.serialize()})

    elif t == "remove_drone":
        swarm_mgr.remove_drone(msg["drone_id"])
        await broadcast({"type": "drone_removed", "drone_id": msg["drone_id"]})

    elif t == "set_mode":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.set_mode(msg["mode"], msg.get("params", {}))
            await broadcast({"type": "mode_changed",
                             "drone_id": drone.id,
                             "mode": drone.mode.value,
                             "params": msg.get("params", {})})

    elif t == "plan_mission":
        # Auto-plan waypoints for a drone / all drones
        result = planner.plan(msg)
        await broadcast({"type": "mission_planned", "result": result})

    elif t == "add_waypoint":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.add_waypoint(msg["waypoint"])
            await broadcast({"type": "waypoint_added",
                             "drone_id": drone.id,
                             "waypoint": msg["waypoint"]})

    elif t == "set_rtl_home":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.rtl_home = {"lat": msg["lat"], "lon": msg["lon"],
                              "alt": msg.get("alt", 0)}
            await ws.send_json({"type": "rtl_home_set", "drone_id": drone.id})

    elif t == "set_rally_point":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.rally_point = {"lat": msg["lat"], "lon": msg["lon"],
                                 "alt": msg.get("alt", drone.rtl_safe_alt)}
            await broadcast({"type": "rally_point_set",
                             "drone_id": drone.id,
                             "rally": drone.rally_point})

    elif t == "abort_mission":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            params = {"safe_alt": msg.get("safe_alt", drone.rtl_safe_alt)}
            if msg.get("rally_lat") and msg.get("rally_lon"):
                drone.rally_point = {
                    "lat": msg["rally_lat"],
                    "lon": msg["rally_lon"],
                    "alt": msg.get("rally_alt", drone.rtl_safe_alt),
                }
            drone.set_mode("ABORT", params)
            await broadcast({"type": "mode_changed",
                             "drone_id": drone.id,
                             "mode": "ABORT",
                             "rally": drone.rally_point})

    elif t == "start_simulation":
        await start_simulation()
        await broadcast({"type": "sim_started"})

    elif t == "stop_simulation":
        await stop_simulation()
        await broadcast({"type": "sim_stopped"})

    elif t == "reset":
        await stop_simulation()
        swarm_mgr.reset()
        await broadcast({"type": "reset"})

    elif t == "get_elevation":
        lat, lon = msg["lat"], msg["lon"]
        elev = terrain.get_elevation(lat, lon)
        await ws.send_json({"type": "elevation", "lat": lat, "lon": lon, "elevation": elev})

    elif t == "get_terrain_tile":
        tile = terrain.get_tile_elevations(msg["bounds"])
        await ws.send_json({"type": "terrain_tile", "data": tile})

    elif t == "mavlink_command":
        # Forward raw MAVLink command to SITL bridge
        result = sitl.send_command(msg.get("drone_id"), msg.get("command"), msg.get("params", {}))
        await ws.send_json({"type": "mavlink_ack", "result": result})

    elif t == "set_speed":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.speed = float(msg["speed"])

    elif t == "set_altitude_hold":
        drone = swarm_mgr.get(msg["drone_id"])
        if drone:
            drone.target_alt = float(msg["altitude"])

    elif t == "formation_launch":
        # Lanzar todos los drones en formación desde un punto de takeoff
        # msg: {takeoff: {lat,lon}, landing: {lat,lon}, formation: str,
        #       n_drones: int, altitude: float, speed: float}
        result = planner.plan_formation(msg)
        for drone_cfg in result["drones"]:
            drone = swarm_mgr.add_drone(drone_cfg)
            drone.waypoints.clear()
            for wp in drone_cfg["waypoints"]:
                drone.add_waypoint(wp)
            drone.set_mode("AUTO", {})
            drone.speed = float(msg.get("speed", 12))
            await broadcast({"type": "drone_added", "drone": drone.serialize()})
        await broadcast({"type": "formation_ready", "result": result})

    elif t == "abort_all":
        # Todos los drones vuelven al punto de salida
        home = msg.get("home")
        for drone in swarm_mgr.all_drones():
            if home:
                drone.rtl_home = home
            drone.set_mode("RTL", {})
        await broadcast({"type": "abort_all_sent",
                         "drone_count": len(swarm_mgr.all_drones())})

    elif t == "set_takeoff_point":
        # Guardar punto de takeoff global
        swarm_mgr.takeoff_point = {"lat": msg["lat"], "lon": msg["lon"]}
        await ws.send_json({"type": "takeoff_point_set",
                            "lat": msg["lat"], "lon": msg["lon"]})

    elif t == "set_landing_point":
        swarm_mgr.landing_point = {"lat": msg["lat"], "lon": msg["lon"]}
        await ws.send_json({"type": "landing_point_set",
                            "lat": msg["lat"], "lon": msg["lon"]})


# ─── Simulation loop ─────────────────────────────────────────────────────────
SIM_HZ = 20          # simulation ticks per second
SIM_DT = 1.0 / SIM_HZ

async def start_simulation():
    global sim_task, sim_running
    if sim_running:
        return
    sim_running = True
    sim_task = asyncio.create_task(simulation_loop())

async def stop_simulation():
    global sim_task, sim_running
    sim_running = False
    if sim_task:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass
        sim_task = None

async def simulation_loop():
    """Main physics tick – runs at SIM_HZ."""
    global sim_running
    t0 = time.monotonic()
    tick = 0
    try:
        while sim_running:
            t_start = time.monotonic()

            # Step all drones
            updates = []
            for drone in swarm_mgr.all_drones():
                state = drone.step(SIM_DT, terrain)
                if state:
                    updates.append(state)

            # Broadcast telemetry batch
            if updates:
                await broadcast({"type": "telemetry_batch",
                                 "tick": tick,
                                 "t": round(time.monotonic() - t0, 3),
                                 "drones": updates})

            tick += 1
            elapsed = time.monotonic() - t_start
            await asyncio.sleep(max(0, SIM_DT - elapsed))
    except asyncio.CancelledError:
        pass


# ─── REST endpoints ───────────────────────────────────────────────────────────
@app.get("/api/elevation")
async def api_elevation(lat: float, lon: float):
    return {"elevation": terrain.get_elevation(lat, lon)}

@app.get("/api/terrain")
async def api_terrain(n: float, s: float, e: float, w: float):
    return terrain.get_tile_elevations({"n": n, "s": s, "e": e, "w": w})

@app.get("/api/drones")
async def api_drones():
    return swarm_mgr.serialize_all()

@app.post("/api/drones")
async def api_add_drone(body: dict):
    drone = swarm_mgr.add_drone(body)
    return drone.serialize()

@app.delete("/api/drones/{drone_id}")
async def api_remove_drone(drone_id: str):
    swarm_mgr.remove_drone(drone_id)
    return {"ok": True}

@app.get("/api/mavlink/sitl_status")
async def api_sitl_status():
    return sitl.status()


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=True)
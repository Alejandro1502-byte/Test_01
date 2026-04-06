"""
mavlink/sitl_bridge.py
MAVLink / ArduPilot SITL bridge.

In production, connect to a running ArduPilot SITL instance via UDP.
When SITL is not available, the bridge operates in "demo" mode –
all commands are acknowledged and simulated internally by the Python drone model.

ArduPilot SITL setup (external):
  ./arducopter --model quad --speedup 1 --home 40.416775,-3.703790,600,0
  Connection: udp:127.0.0.1:14550
"""

import time
import math
import socket
import threading
from typing import Optional, Dict, Any

# Try to import pymavlink (optional dependency)
try:
    from pymavlink import mavutil
    MAVLINK_AVAILABLE = True
except ImportError:
    MAVLINK_AVAILABLE = False

# MAVLink command IDs (subset used here)
MAV_CMD_NAV_WAYPOINT     = 16
MAV_CMD_NAV_LOITER_TIME  = 19
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_NAV_LAND         = 21
MAV_CMD_NAV_TAKEOFF      = 22
MAV_CMD_DO_CHANGE_SPEED  = 178
MAV_CMD_DO_SET_HOME      = 179

# Flight mode IDs (ArduCopter)
COPTER_MODES = {
    "STABILIZE": 0,
    "ACRO":      1,
    "ALT_HOLD":  2,
    "AUTO":      3,
    "GUIDED":    4,
    "LOITER":    5,
    "RTL":       6,
    "CIRCLE":    7,
    "LAND":      9,
    "DRIFT":    11,
    "SPORT":    13,
    "POSHOLD":  16,
    "BRAKE":    17,
}


class SITLBridge:
    """
    Bridge between the Python simulator and ArduPilot SITL.

    If pymavlink is installed and SITL is running on udp:14550,
    commands are forwarded to the real flight stack.
    Otherwise, everything is simulated in demo mode.
    """

    def __init__(self, sitl_address: str = "udp:127.0.0.1:14550"):
        self._conn   = None
        self._alive  = False
        self._status = {"connected": False, "mode": "DEMO",
                        "sitl_address": sitl_address}
        self._vehicles: Dict[str, Any] = {}  # drone_id → mavlink connection

        if MAVLINK_AVAILABLE:
            self._try_connect(sitl_address)
        else:
            print("[SITL] pymavlink not installed – running in DEMO mode")

    # ── Connection ────────────────────────────────────────────────────────────
    def _try_connect(self, address: str):
        try:
            conn = mavutil.mavlink_connection(address, timeout=2)
            conn.wait_heartbeat(timeout=3)
            self._conn  = conn
            self._alive = True
            self._status["connected"] = True
            self._status["mode"]      = "SITL"
            print(f"[SITL] Connected to {address} – heartbeat received")
            # Start listener thread
            threading.Thread(target=self._recv_loop, daemon=True).start()
        except Exception as e:
            print(f"[SITL] Could not connect ({e}) – DEMO mode")

    def _recv_loop(self):
        """Background thread: receive MAVLink messages from SITL."""
        while self._alive and self._conn:
            try:
                msg = self._conn.recv_match(blocking=True, timeout=1)
                if msg:
                    self._handle_msg(msg)
            except Exception:
                break

    def _handle_msg(self, msg):
        mtype = msg.get_type()
        # Here you would update drone telemetry from real SITL data
        # For now just log
        if mtype in ("GLOBAL_POSITION_INT", "ATTITUDE", "SYS_STATUS"):
            pass  # hook into drone state update

    # ── Command dispatch ──────────────────────────────────────────────────────
    def send_command(self, drone_id: Optional[str],
                     command: str, params: dict = {}) -> dict:
        """
        Send a high-level command. Returns ack dict.
        """
        t0 = time.time()

        if self._conn and self._alive:
            result = self._mavlink_command(command, params)
        else:
            result = self._demo_command(command, params)

        return {"ok": result, "command": command,
                "drone_id": drone_id, "latency_ms": round((time.time()-t0)*1000, 1)}

    def _mavlink_command(self, command: str, params: dict) -> bool:
        """Send actual MAVLink command to SITL."""
        try:
            if command == "SET_MODE":
                mode_id = COPTER_MODES.get(params.get("mode", "LOITER"), 5)
                self._conn.set_mode(mode_id)
                return True

            elif command == "ARM":
                self._conn.arducopter_arm()
                return True

            elif command == "DISARM":
                self._conn.arducopter_disarm()
                return True

            elif command == "TAKEOFF":
                alt = params.get("alt", 20)
                self._conn.mav.command_long_send(
                    self._conn.target_system,
                    self._conn.target_component,
                    MAV_CMD_NAV_TAKEOFF, 0,
                    0, 0, 0, 0, 0, 0, alt
                )
                return True

            elif command == "RTL":
                self._conn.mav.command_long_send(
                    self._conn.target_system,
                    self._conn.target_component,
                    MAV_CMD_NAV_RETURN_TO_LAUNCH, 0,
                    0,0,0,0,0,0,0
                )
                return True

            elif command == "WAYPOINT":
                # Send mission item
                lat = params.get("lat", 0)
                lon = params.get("lon", 0)
                alt = params.get("alt", 50)
                self._conn.mav.mission_item_send(
                    self._conn.target_system,
                    self._conn.target_component,
                    0, 3,  # seq, frame=MAV_FRAME_GLOBAL_RELATIVE_ALT
                    MAV_CMD_NAV_WAYPOINT,
                    0, 1,  # current, autocontinue
                    0, 0, 0, 0,
                    lat, lon, alt
                )
                return True

            elif command == "SPEED":
                speed = params.get("speed", 10)
                self._conn.mav.command_long_send(
                    self._conn.target_system,
                    self._conn.target_component,
                    MAV_CMD_DO_CHANGE_SPEED, 0,
                    0, speed, -1, 0, 0, 0, 0
                )
                return True

        except Exception as e:
            print(f"[SITL] MAVLink error: {e}")
            return False
        return False

    def _demo_command(self, command: str, params: dict) -> bool:
        """Demo mode: just acknowledge commands."""
        print(f"[SITL-DEMO] CMD={command} params={params}")
        return True

    # ── Status ────────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return self._status

    def close(self):
        self._alive = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass


# ── MAVLink mission upload helper ─────────────────────────────────────────────
def upload_mission(conn, waypoints: list):
    """
    Upload a list of {lat, lon, alt} waypoints to SITL as a full mission.
    """
    if not MAVLINK_AVAILABLE or not conn:
        return False
    count = len(waypoints)
    conn.mav.mission_count_send(conn.target_system, conn.target_component, count)
    for i, wp in enumerate(waypoints):
        conn.mav.mission_item_send(
            conn.target_system, conn.target_component,
            i, 3,  # MAV_FRAME_GLOBAL_RELATIVE_ALT
            MAV_CMD_NAV_WAYPOINT,
            1 if i == 0 else 0, 1,
            0, 0, 0, 0,
            wp["lat"], wp["lon"], wp["alt"]
        )
    return True
#!/usr/bin/env python3
"""
client/gcs_terminal.py – Ground Control Station en terminal
Cliente Python independiente que se conecta al servidor via WebSocket
y muestra telemetría en tiempo real en la consola.

Uso:
    python gcs_terminal.py
    python gcs_terminal.py --url ws://192.168.1.10:8765/ws
    python gcs_terminal.py --add-drone --lat 40.416 --lon -3.703
    python gcs_terminal.py --mission grid --bounds 40.41,40.43,-3.72,-3.70
"""
import asyncio
import json
import argparse
import sys
import os
import time
import math
from datetime import datetime

try:
    import websockets
except ImportError:
    print("Instala: pip install websockets")
    sys.exit(1)

# ANSI colours
G  = "\033[92m"   # green
R  = "\033[91m"   # red
Y  = "\033[93m"   # yellow
C  = "\033[96m"   # cyan
DIM = "\033[2m"
RST = "\033[0m"
BOLD = "\033[1m"
CLR  = "\033[2J\033[H"

DRONE_MODES = ["AUTO","LOITER","ALT_HOLD","ACRO","RTL","LAND","IDLE"]


def fmt_mode(mode):
    colors = {"ACRO": R, "RTL": Y, "AUTO": G, "LOITER": C, "ALT_HOLD": C}
    c = colors.get(mode, DIM)
    return f"{c}{mode:<10}{RST}"

def fmt_bat(v):
    c = G if v > 50 else (Y if v > 20 else R)
    bar = "█" * int(v / 10) + "░" * (10 - int(v / 10))
    return f"{c}{bar} {v:.0f}%{RST}"

def fmt_phase(p):
    colors = {"CRUISE":"", "TAKEOFF": C, "RTL_FLY": Y, "RTL_CLIMB": Y,
              "RTL_LAND": Y, "LAND": DIM, "IDLE": DIM, "ACRO": R}
    c = colors.get(p, "")
    return f"{c}{p}{RST}"

def draw_attitude(roll, pitch):
    """Mini ASCII artificial horizon."""
    w, h = 20, 5
    lines = []
    for row in range(h):
        line = []
        y_norm = (row - h//2) / (h//2)
        for col in range(w):
            x_norm = (col - w//2) / (w//2)
            # horizon line equation with roll/pitch
            roll_r  = math.radians(roll)
            pitch_r = math.radians(pitch)
            horizon_y = x_norm * math.tan(roll_r) - math.tan(pitch_r) * 0.5
            if abs(y_norm - horizon_y) < 0.3:
                c = "─"
            elif y_norm < horizon_y:
                c = "▄" if row == h//2 else "·"
            else:
                c = " "
            line.append(c)
        lines.append("".join(line))
    return lines


class GCSTerminal:
    def __init__(self, url: str):
        self.url      = url
        self.drones   = {}
        self.tick     = 0
        self.start_t  = time.time()
        self._ws      = None
        self._running = True

    async def run(self, commands: list = []):
        print(f"{C}Conectando a {self.url}…{RST}")
        try:
            async with websockets.connect(self.url) as ws:
                self._ws = ws
                print(f"{G}✓ Conectado{RST}")

                # Send queued commands after hello
                async def sender():
                    for cmd in commands:
                        await asyncio.sleep(0.5)
                        await ws.send(json.dumps(cmd))
                        print(f"{DIM}→ {cmd['type']}{RST}")

                asyncio.create_task(sender())

                # Heartbeat
                async def heartbeat():
                    while self._running:
                        await asyncio.sleep(5)
                        try:
                            await ws.send(json.dumps({"type": "ping"}))
                        except Exception:
                            break
                asyncio.create_task(heartbeat())

                async for raw in ws:
                    msg = json.loads(raw)
                    await self._handle(msg)

        except Exception as e:
            print(f"{R}Error: {e}{RST}")

    async def _handle(self, msg: dict):
        t = msg.get("type")

        if t == "hello":
            for d in msg.get("drones", []):
                self.drones[d["id"]] = d
            self._redraw()

        elif t == "drone_added":
            d = msg["drone"]
            self.drones[d["id"]] = d
            print(f"\n{G}+ Drone añadido: {d['name']} [{d['id']}]{RST}")

        elif t == "drone_removed":
            self.drones.pop(msg.get("drone_id"), None)
            print(f"\n{Y}− Drone eliminado: {msg.get('drone_id')}{RST}")

        elif t == "telemetry_batch":
            self.tick = msg.get("tick", 0)
            for d in msg.get("drones", []):
                self.drones[d["id"]] = d
            self._redraw()

        elif t == "mode_changed":
            did = msg.get("drone_id")
            if did in self.drones:
                self.drones[did]["mode"] = msg.get("mode")
            print(f"\n{Y}MODE → {msg.get('mode')} [{did}]{RST}")

        elif t == "mission_planned":
            r = msg.get("result", {})
            print(f"\n{G}✓ Misión planificada: {len(r.get('waypoints',[]))} WPs{RST}")

        elif t == "pong":
            pass  # heartbeat ack

        elif t == "sim_started":
            print(f"\n{G}▶ Simulación iniciada{RST}")

        elif t == "sim_stopped":
            print(f"\n{Y}■ Simulación detenida{RST}")

        elif t in ("elevation",):
            print(f"{C}Elevación: {msg.get('elevation')}m @ "
                  f"{msg.get('lat')},{msg.get('lon')}{RST}")

    def _redraw(self):
        if not self.drones:
            return
        elapsed = time.time() - self.start_t
        m, s = int(elapsed/60), int(elapsed%60)

        print(CLR, end="")
        print(f"{BOLD}{C}╔══════════════════════════════════════════════════════════════╗")
        print(f"║  DRONE GCS TERMINAL  T+{m:02d}:{s:02d}  TICK:{self.tick:<8}               ║")
        print(f"╚══════════════════════════════════════════════════════════════╝{RST}")

        for d in self.drones.values():
            spd = d.get("speed", 0)
            alt = d.get("alt",   0)
            bat = d.get("battery", 100)
            hdg = d.get("yaw",   0)
            vz  = d.get("vz",    0)
            lat = d.get("lat",   0)
            lon = d.get("lon",   0)
            mode  = d.get("mode",  "—")
            phase = d.get("phase", "—")
            name  = d.get("name",  "—")
            wp_i  = d.get("wp_idx",   0)
            wp_t  = d.get("wp_total", 0)

            print(f"\n{BOLD}  {name} [{d.get('id')}]{RST}  {fmt_mode(mode)}  {fmt_phase(phase)}")
            print(f"  {'─'*60}")

            # Left column: telemetry
            rows = [
                f"  LAT/LON  {lat:.6f}, {lon:.6f}",
                f"  ALT      {alt:>8.1f} m   {'↑' if vz>0.1 else ('↓' if vz<-0.1 else '→')} {abs(vz):.1f} m/s",
                f"  SPEED    {spd:>8.1f} m/s",
                f"  HEADING  {hdg:>8.1f}°",
                f"  WP       {wp_i}/{wp_t}",
                f"  GPS SATS {d.get('gps_sats',0):>5}",
                f"  RSSI     {d.get('rssi', -99):>5} dBm",
            ]
            horiz = draw_attitude(d.get("roll",0), d.get("pitch",0))

            for i, row in enumerate(rows):
                att = f"  │{horiz[i]}│" if i < len(horiz) else ""
                print(f"{row:<38}{C}{att}{RST}")

            print(f"\n  {fmt_bat(bat)}")
            print(f"  {'─'*60}")

        print(f"\n{DIM}  [Ctrl+C para salir]  UTC {datetime.utcnow().strftime('%H:%M:%S')}{RST}")


# ── Interactive command loop ──────────────────────────────────────────────────
async def interactive_loop(ws_url: str, pre_cmds: list):
    term = GCSTerminal(ws_url)
    task = asyncio.create_task(term.run(pre_cmds))

    # Give WS time to connect
    await asyncio.sleep(1.5)

    print(f"\n{C}Comandos disponibles:{RST}")
    cmds_help = [
        ("add",  "Añadir dron en posición actual del mapa"),
        ("mode <ID> <MODE>", "Cambiar modo: AUTO LOITER ALT_HOLD ACRO RTL"),
        ("start","Iniciar simulación"),
        ("stop", "Parar simulación"),
        ("arm <ID>", "Armar dron"),
        ("elev <lat> <lon>", "Consultar elevación"),
        ("quit","Salir"),
    ]
    for cmd, desc in cmds_help:
        print(f"  {G}{cmd:<25}{RST} {DIM}{desc}{RST}")
    print()

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input(f"{C}gcs>{RST} ").strip()
            )
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("quit","exit","q"):
                break
            elif cmd == "add":
                await term._ws.send(json.dumps({
                    "type": "add_drone",
                    "lat": 40.416775, "lon": -3.703790, "alt": 0,
                    "armed": True,
                }))
            elif cmd == "start":
                await term._ws.send(json.dumps({"type": "start_simulation"}))
            elif cmd == "stop":
                await term._ws.send(json.dumps({"type": "stop_simulation"}))
            elif cmd == "mode" and len(parts) >= 3:
                await term._ws.send(json.dumps({
                    "type": "set_mode",
                    "drone_id": parts[1],
                    "mode": parts[2].upper(),
                    "params": {},
                }))
            elif cmd == "arm" and len(parts) >= 2:
                await term._ws.send(json.dumps({
                    "type": "mavlink_command",
                    "drone_id": parts[1],
                    "command": "ARM",
                    "params": {},
                }))
            elif cmd == "elev" and len(parts) >= 3:
                await term._ws.send(json.dumps({
                    "type": "get_elevation",
                    "lat": float(parts[1]),
                    "lon": float(parts[2]),
                }))
            elif cmd == "rtl" and len(parts) >= 2:
                await term._ws.send(json.dumps({
                    "type": "set_mode",
                    "drone_id": parts[1],
                    "mode": "RTL",
                    "params": {},
                }))
            elif cmd == "help":
                for c, d in cmds_help:
                    print(f"  {G}{c:<25}{RST} {DIM}{d}{RST}")
            else:
                print(f"{R}Comando desconocido. Escribe 'help'.{RST}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        term._running = False
        task.cancel()


def main():
    ap = argparse.ArgumentParser(description="GCS Terminal Client")
    ap.add_argument("--url",  default="ws://localhost:8765/ws")
    ap.add_argument("--add-drone", action="store_true")
    ap.add_argument("--lat",  type=float, default=40.416775)
    ap.add_argument("--lon",  type=float, default=-3.703790)
    ap.add_argument("--start",action="store_true", help="Iniciar sim al conectar")
    ap.add_argument("--mission", choices=["grid","orbit","direct"], default=None)
    ap.add_argument("--bounds", default=None,
                    help="N,S,E,W p.ej: 40.42,40.41,-3.70,-3.72")
    args = ap.parse_args()

    pre_cmds = []
    if args.add_drone:
        pre_cmds.append({"type":"add_drone","lat":args.lat,"lon":args.lon,"alt":0,"armed":True})
    if args.start:
        pre_cmds.append({"type":"start_simulation"})
    if args.mission and args.bounds:
        n,s,e,w = map(float, args.bounds.split(","))
        pre_cmds.append({
            "type": "plan_mission",
            "pattern": args.mission,
            "altitude": 60,
            "bounds": {"n":n,"s":s,"e":e,"w":w},
        })

    try:
        asyncio.run(interactive_loop(args.url, pre_cmds))
    except KeyboardInterrupt:
        print(f"\n{Y}Desconectado.{RST}")


if __name__ == "__main__":
    main()
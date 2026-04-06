#!/usr/bin/env python3
"""
run.py – Script de arranque del simulador completo
Uso:
    python run.py                   # Modo normal
    python run.py --demo            # Sin necesidad de servidor (abre HTML directamente)
    python run.py --sitl            # Con ArduPilot SITL en udp:14550
    python run.py --host 0.0.0.0 --port 8765
"""
import argparse
import os
import sys
import subprocess
import webbrowser
import time
import threading


def parse_args():
    p = argparse.ArgumentParser(description="Drone Simulator Launcher")
    p.add_argument("--host",   default="0.0.0.0",  help="Bind host")
    p.add_argument("--port",   default=8765, type=int, help="Bind port")
    p.add_argument("--demo",   action="store_true", help="Abrir frontend sin servidor")
    p.add_argument("--sitl",   action="store_true", help="Conectar con ArduPilot SITL")
    p.add_argument("--reload", action="store_true", default=True,  help="Hot-reload")
    p.add_argument("--open",   action="store_true", default=True,  help="Abrir navegador")
    return p.parse_args()


def open_browser(url, delay=1.5):
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


def check_deps():
    missing = []
    for pkg in ["fastapi", "uvicorn", "websockets"]:
        try:
            __import__(pkg.replace("-","_"))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[!] Dependencias faltantes: {', '.join(missing)}")
        print(f"    Instala con: pip install {' '.join(missing)}")
        ans = input("¿Instalar ahora? [s/N]: ").strip().lower()
        if ans == 's':
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        else:
            sys.exit(1)


def main():
    args = parse_args()

    if args.demo:
        # Solo abrir el HTML localmente
        html = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            "..", "frontend", "index.html"))
        print(f"[DEMO] Abriendo {html}")
        webbrowser.open(f"file://{html}")
        return

    check_deps()

    # Set env vars
    os.environ["SIM_HOST"]    = args.host
    os.environ["SIM_PORT"]    = str(args.port)
    os.environ["SITL_ENABLED"] = "1" if args.sitl else "0"

    url = f"http://localhost:{args.port}"
    print(f"""
╔══════════════════════════════════════════════╗
║        DRONE SIM // ArduPilot SITL          ║
╠══════════════════════════════════════════════╣
║  Servidor : {url:<33}║
║  SITL     : {'ACTIVO' if args.sitl else 'DEMO (sin SITL)':<33}║
║  Docs API : {url+'/docs':<33}║
╚══════════════════════════════════════════════╝
""")

    if args.open:
        open_browser(url)

    # Change to backend dir so imports work
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)
    sys.path.insert(0, backend_dir)

    import uvicorn
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
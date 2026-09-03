#!/usr/bin/env python3
"""
recoil_control.py
------------------
Mientras se mantiene click derecho (apuntar) Y click izquierdo (disparar),
mueve el mouse hacia abajo en pequeños incrementos para compensar el recoil.

Funciona bajo Wayland/Sway porque:
  - Lee los eventos del mouse directamente vía evdev (no depende de X11).
  - Inyecta el movimiento vía ydotool, que usa /dev/uinput y funciona en
    cualquier compositor Wayland.

REQUISITOS
----------
1. Paquetes del sistema:
     sudo pacman -S ydotool          # Arch
     sudo apt install ydotool        # Debian/Ubuntu
   (o compílalo desde https://github.com/ReimuNotMoe/ydotool)

2. Librería Python:
     pip install --user evdev

3. Demonio ydotoold corriendo (necesario para inyectar eventos):
     ydotoold &
   O como servicio:
     systemctl --user enable --now ydotool.service   # si tu paquete lo trae

4. Permisos:
   - Tu usuario debe pertenecer al grupo "input" para leer el mouse:
       sudo usermod -aG input $USER
   - ydotoold necesita acceso a /dev/uinput (normalmente corre como root
     o con udev rule que da acceso al grupo "input").
   - Cierra sesión/vuelve a iniciar sesión después de añadirte al grupo.

5. Encuentra el path de tu mouse:
     python3 -c "import evdev; [print(d.path, d.name) for d in evdev.list_devices()]"
   Copia el path (algo como /dev/input/event4) en MOUSE_DEVICE abajo.

USO
---
   python3 recoil_control.py

Ajusta las constantes de configuración según el arma/juego que estés probando.
"""

import subprocess
import threading
import time
import sys

try:
    import evdev
    from evdev import ecodes
except ImportError:
    sys.exit(
        "Falta la librería 'evdev'. Instálala con: pip install --user evdev"
    )

# ---------------------- CONFIGURACIÓN ----------------------

# Path del dispositivo de mouse (ver instrucciones arriba para encontrarlo).
MOUSE_DEVICE = "/dev/input/event4"

# Píxeles que se mueve hacia abajo en cada "tick" de compensación.
PULL_DOWN_PX = 3

# Cada cuánto tiempo (segundos) se aplica un tick mientras ambos botones
# están presionados. 0.02s = 50 veces por segundo.
TICK_INTERVAL = 0.02

# Pequeño delay antes de empezar a compensar tras presionar ambos botones,
# para no mover el mouse en el instante mismo del primer disparo.
START_DELAY = 0.05

# -------------------------------------------------------------


def move_mouse_down(pixels: int) -> None:
    """Inyecta un movimiento relativo hacia abajo usando ydotool."""
    try:
        subprocess.run(
            ["ydotool", "mousemove", "--relative", "-x", "0", "-y", str(pixels)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        sys.exit("No se encontró 'ydotool'. Instálalo y asegúrate de que esté en el PATH.")
    except subprocess.CalledProcessError:
        # Probablemente ydotoold no está corriendo.
        print("Aviso: no se pudo enviar el movimiento. ¿Está corriendo 'ydotoold'?")


# Estado compartido entre el hilo lector de eventos y el loop de compensación.
state_lock = threading.Lock()
state = {
    "left_down": False,
    "right_down": False,
    "hold_start": None,  # timestamp desde que ambos botones están presionados
}


def event_reader(device: "evdev.InputDevice") -> None:
    """Corre en un hilo aparte: solo actualiza el estado de los botones.

    NOTA: no se hace device.grab(), así el juego sigue recibiendo los
    eventos originales del mouse con normalidad; este hilo solo "escucha".
    """
    for event in device.read_loop():
        if event.type != ecodes.EV_KEY:
            continue
        if event.code not in (ecodes.BTN_LEFT, ecodes.BTN_RIGHT):
            continue

        with state_lock:
            if event.code == ecodes.BTN_LEFT:
                state["left_down"] = event.value == 1
            elif event.code == ecodes.BTN_RIGHT:
                state["right_down"] = event.value == 1

            if state["left_down"] and state["right_down"]:
                if state["hold_start"] is None:
                    state["hold_start"] = time.time()
            else:
                state["hold_start"] = None


def compensation_loop() -> None:
    """Loop en tiempo real: aplica ticks de compensación mientras ambos
    botones sigan presionados, sin depender de que lleguen eventos nuevos.
    Esto es lo que hace que funcione tanto con click izquierdo sostenido
    (arma automática) como con clicks sueltos repetidos.
    """
    last_tick = 0.0
    while True:
        time.sleep(0.005)  # resolución del loop, más fino que TICK_INTERVAL

        with state_lock:
            both_held = state["left_down"] and state["right_down"]
            hold_start = state["hold_start"]

        if not both_held or hold_start is None:
            last_tick = 0.0
            continue

        now = time.time()
        if now - hold_start < START_DELAY:
            continue
        if now - last_tick >= TICK_INTERVAL:
            move_mouse_down(PULL_DOWN_PX)
            last_tick = now


def main() -> None:
    try:
        device = evdev.InputDevice(MOUSE_DEVICE)
    except FileNotFoundError:
        sys.exit(
            f"No se encontró el dispositivo {MOUSE_DEVICE}.\n"
            "Lista tus dispositivos con:\n"
            "  python3 -c \"import evdev; [print(d.path, d.name) for d in evdev.list_devices()]\""
        )
    except PermissionError:
        sys.exit(
            "Permiso denegado al abrir el dispositivo.\n"
            "Añade tu usuario al grupo 'input': sudo usermod -aG input $USER\n"
            "y vuelve a iniciar sesión."
        )

    print(f"Escuchando en: {device.name} ({MOUSE_DEVICE})")
    print("Ctrl+C para salir.\n")

    reader_thread = threading.Thread(target=event_reader, args=(device,), daemon=True)
    reader_thread.start()

    try:
        compensation_loop()
    except KeyboardInterrupt:
        print("\nSaliendo.")


if __name__ == "__main__":
    main()

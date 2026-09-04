#!/usr/bin/env python3
"""
recoil_control_x11.py
----------------------
Versión para X11 (Xfce y en general cualquier sesión X11/Xorg).

Mientras se mantiene click derecho (apuntar) Y click izquierdo (disparar),
mueve el mouse hacia abajo en pequeños incrementos para compensar el recoil,
solo durante los primeros MAX_COMPENSATION_DURATION segundos de hold.

Funciona bajo X11/Xfce porque:
  - Lee los eventos del mouse directamente vía evdev (a nivel de kernel,
    no depende de si es X11 o Wayland).
  - Inyecta el movimiento vía xdotool, que usa la extensión XTest de X11.

Diferencia con la versión de Sway/Wayland: ahí se usaba ydotool porque
XTest no existe en Wayland. Bajo X11, xdotool es más simple porque no
necesita un demonio corriendo aparte ni permisos de uinput.

REQUISITOS
----------
1. Paquete del sistema:
     sudo pacman -S xdotool           # Arch
     sudo apt install xdotool         # Debian/Ubuntu/Xfce

2. Librería Python:
     pip install --user evdev

3. Permisos:
   - Tu usuario debe pertenecer al grupo "input" para leer el mouse crudo:
       sudo usermod -aG input $USER
   - Cierra sesión/vuelve a iniciar sesión después de añadirte al grupo.
   - xdotool en sí no necesita permisos especiales bajo X11 normal.

4. Encuentra el path de tu mouse:
     python3 -c "import evdev; [print(d.path, d.name) for d in evdev.list_devices()]"
   Copia el path (algo como /dev/input/event5) en MOUSE_DEVICE abajo.

USO
---
   python3 recoil_control_x11.py
   python3 recoil_control_x11.py --debug   # para ver qué está detectando/enviando

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
print ("Busque su mouse en los event Usa ctrl + C para continuar")
os.system("evtest")
print ()
event = input("Ingresa el numero del event: ")

# Path del dispositivo de mouse (ver instrucciones arriba para encontrarlo).
MOUSE_DEVICE = "/dev/input/event" + event

# Píxeles que se mueve hacia abajo en cada "tick" de compensación.
PULL_DOWN_PX = 2

# Cada cuánto tiempo (segundos) se aplica un tick mientras ambos botones
# están presionados. 0.02s = 50 veces por segundo.
TICK_INTERVAL = 0.02

# Pequeño delay antes de empezar a compensar tras presionar ambos botones,
# para no mover el mouse en el instante mismo del primer disparo.
START_DELAY = 0.05

# Duración máxima (segundos) que se compensa el recoil tras empezar a
# disparar, aunque ambos botones se sigan manteniendo presionados.
# Pasado este tiempo, se detiene la compensación hasta que se suelten
# y se vuelvan a presionar ambos botones.
MAX_COMPENSATION_DURATION = 2.5

# -------------------------------------------------------------


DEBUG = "--debug" in sys.argv


def move_mouse_down(pixels: int) -> None:
    """Inyecta un movimiento relativo hacia abajo usando xdotool (XTest)."""
    try:
        result = subprocess.run(
            ["xdotool", "mousemove_relative", "--", "0", str(pixels)],
            capture_output=True,
            text=True,
        )
        if DEBUG:
            print(f"[xdotool] rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")
        if result.returncode != 0:
            print(f"Aviso: xdotool falló (rc={result.returncode}): {result.stderr.strip()}")
    except FileNotFoundError:
        sys.exit("No se encontró 'xdotool'. Instálalo y asegúrate de que esté en el PATH.")


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

            if DEBUG:
                print(f"[evdev] left={state['left_down']} right={state['right_down']}")

            if state["left_down"] and state["right_down"]:
                if state["hold_start"] is None:
                    state["hold_start"] = time.time()
                    if DEBUG:
                        print("[evdev] -> ambos botones presionados, iniciando compensación")
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
        elapsed = now - hold_start

        if elapsed < START_DELAY:
            continue
        if elapsed >= MAX_COMPENSATION_DURATION:
            # Ya pasó el tiempo máximo de compensación: no se mueve más
            # aunque los botones sigan presionados.
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

    print(f"[X11] Escuchando en: {device.name} ({MOUSE_DEVICE})")
    print("Ctrl+C para salir.\n")

    reader_thread = threading.Thread(target=event_reader, args=(device,), daemon=True)
    reader_thread.start()

    try:
        compensation_loop()
    except KeyboardInterrupt:
        print("\nSaliendo.")


if __name__ == "__main__":
    main()

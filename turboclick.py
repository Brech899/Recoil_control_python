#!/usr/bin/env python3

import time
import threading
from evdev import InputDevice, UInput, ecodes

# CAMBIA esto por el event de tu mouse
MOUSE = "/dev/input/event4"

# 0.01 = aproximadamente 100 clicks por segundo
CLICK_DELAY = 0.01

device = InputDevice(MOUSE)

# Captura el mouse para que BTN_SIDE no llegue al resto del sistema
#device.grab()

ui = UInput({
    ecodes.EV_KEY: [
        ecodes.BTN_LEFT
    ]
}, name="Turbo Click")

clicking = False


def turbo():
    global clicking

    while True:
        if clicking:
            ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
            ui.syn()

            ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
            ui.syn()

            time.sleep(CLICK_DELAY)
        else:
            time.sleep(0.010)


threading.Thread(target=turbo, daemon=True).start()

print("Turbo click activo.")
print("Mantén BTN_SIDE para hacer clicks.")
print("Ctrl+C para salir.")

try:
    for event in device.read_loop():

        if event.type == ecodes.EV_KEY and event.code == ecodes.BTN_SIDE:

            if event.value == 1:
                clicking = True

            elif event.value == 0:
                clicking = False

except KeyboardInterrupt:
    pass

finally:
    clicking = False
    device.ungrab()
    ui.close()

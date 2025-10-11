#!/usr/bin/env python3
from evdev import InputDevice, ecodes, categorize

device_path = "/dev/input/event0"  # your RFID reader
dev = InputDevice(device_path)

print(f"Using {dev.name} at {device_path}")
print("Waiting for RFID scans...")

# grab prevents it from typing into text boxes
dev.grab()

buffer = []
for event in dev.read_loop():
    if event.type == ecodes.EV_KEY:
        key = categorize(event)
        if key.keystate == key.key_down:
            code = key.keycode
            if isinstance(code, list):
                code = code[-1]
            if code == "KEY_ENTER":
                tag = "".join(buffer)
                print("Tag:", tag)
                buffer = []
            elif code.startswith("KEY_"):
                k = code[4:]
                if len(k) == 1:
                    buffer.append(k)
                elif k == "MINUS":
                    buffer.append("-")
                # add other symbols if needed

#!/usr/bin/env python3
from evdev import InputDevice, list_devices, ecodes, categorize

dev = None
for path in list_devices():
    d = InputDevice(path)
    if "arm cm0" in d.name.lower() or "hid keyboard" in d.name.lower():
        dev = d
        break

if not dev:
    print("RFID device not found")
    exit(1)

print(f"Using {dev.path} ({dev.name})")
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
                char = code[4:]
                if len(char) == 1:
                    buffer.append(char)
                elif char == "MINUS":
                    buffer.append("-")

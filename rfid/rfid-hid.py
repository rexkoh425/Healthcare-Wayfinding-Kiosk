from flask import Flask, jsonify
from flask_cors import cross_origin
import threading, time, logging
from evdev import InputDevice, categorize, ecodes

app = Flask(__name__)
logger = logging.getLogger(__name__)

dev = InputDevice('/dev/input/event0')  # adjust for your HID device
current_tag = None
last_seen = 0
TAG_TIMEOUT = 2.0  # seconds without detection → tag removed


def tag_reader_loop():
    global current_tag, last_seen

    buffer = []

    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY:
            continue

        key = categorize(event)
        if key.keystate != key.key_down:
            continue

        code = key.keycode
        if isinstance(code, list):
            code = code[-1]

        if code == "KEY_ENTER":
            tag = "".join(buffer)
            buffer = []
            if len(tag) == 24:
                if tag != current_tag:
                    logger.info(f"New tag detected: {tag}")
                current_tag = tag
                last_seen = time.time()
            else:
                logger.debug(f"Ignoring invalid tag: {tag}")
        elif code.startswith("KEY_"):
            char = code[4:]
            if len(char) == 1:
                buffer.append(char)
            elif char == "MINUS":
                buffer.append("-")

# Thread that monitors tag removal
def tag_monitor_loop():
    global current_tag
    while True:
        if current_tag and time.time() - last_seen > TAG_TIMEOUT:
            logger.info(f"Tag {current_tag} removed")
            current_tag = None
        time.sleep(0.2)


@app.route("/", methods=["GET"])
@cross_origin()
def get_tag_status():
    """Return the current tag state."""
    if current_tag:
        return jsonify({"epc": current_tag.lower()})
    else:
        return jsonify({"status": "no_tag"})


if __name__ == "__main__":
    # Start background threads
    threading.Thread(target=tag_reader_loop, daemon=True).start()
    threading.Thread(target=tag_monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5001)

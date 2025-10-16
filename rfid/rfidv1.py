#!/usr/bin/env python3
from evdev import InputDevice, list_devices, ecodes, categorize
from flask import Flask, jsonify
from flask_cors import CORS, cross_origin
import time
import logging
# import usb.core
# import usb.util
# -----------------------
# Logging Setup
# -----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# -----------------------
# Flask Setup
# -----------------------
app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

SERVER_PORT = 5000
CERT_FILE = "/certs/cert.pem"
KEY_FILE = "/certs/key.pem"


IGNORED_TAGS = {"E2827802000000000D952A4C"}

# -----------------------
# RFID Setup
# -----------------------
dev = None        # InputDevice handle
vid = 0xffff
pid = 0x0035

# -----------------------
# Unused Functions: Auto detection of rfid removal
# -----------------------
def reset_rfid_device(vid=vid, pid=pid):
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        print("RFID device not found for reset")
        return False
    try:
        dev.reset()  # USB-level reset
        time.sleep(0.3)  # allow device to re-enumerate
        print("RFID device reset successfully")
        return True
    except usb.core.USBError as e:
        print("USB reset failed:", e)
        return False

def wait_for_tag_removal(timeout=3.0):
    """
    Wait until a tag is removed (physically), ignoring specific phantom tags.
    """
    logger.info("Waiting for tag to be removed...")
    reset_rfid_device()
    start_time = time.time()
    buffer = []


    while True:
        # Check timeout regardless of events
        if time.time() - start_time > timeout:
            logger.info("Tag removal timeout reached")
            return True

        event = dev.read_one()  # non-blocking read

        if event and event.type == ecodes.EV_KEY:
            key = categorize(event)
            if key.keystate == key.key_down:
                code = key.keycode
                if isinstance(code, list):
                    code = code[-1]

                if code == "KEY_ENTER":
                    tag = "".join(buffer)
                    buffer = []
                    # Ignore phantom tag
                    if tag in IGNORED_TAGS:
                        logger.info(f"Ignoring phantom tag: {tag}")
                        continue
                    else:
                        logger.info(f"Tag still there: {tag}")                       
                        reset_rfid_device()
                        start_time = time.time()  # reset timer
                        continue

                elif code.startswith("KEY_"):
                    char = code[4:]
                    if len(char) == 1:
                        buffer.append(char)
                    elif char == "MINUS":
                        buffer.append("-")

# -----------------------
# Functions
# -----------------------

def find_rfid_device():
    for path in list_devices():
        d = InputDevice(path)
        if "arm cm0" in d.name.lower() or "hid keyboard" in d.name.lower():
            logger.info(f"Found RFID device at {path} ({d.name})")
            return d
    return None


def ensure_device():
    """Ensure the device exists and is grabbed."""
    global dev
    while True:
        try:
            if dev is None:
                dev = find_rfid_device()
                if not dev:
                    logger.info("Waiting for RFID device...")
                    time.sleep(2)
                    continue
                dev.grab()
                logger.info(f"RFID device {dev.path} grabbed permanently.")
            _ = dev.fd  # check if device still valid
            return dev
        except (OSError, AttributeError) as e:
            logger.warning("Device disconnected or access error. Reinitializing...")
            dev = None
            time.sleep(2)


def read_tag():
    """Read a full tag from the HID reader."""
    buffer = []
    logger.info("Waiting for RFID tag...")

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
            if len(tag)!=24 or tag in IGNORED_TAGS:
                logger.info(f"Ignoring phantom tag: {tag}")
                continue
            logger.info(f"Tag read: {tag}")
            return tag
        elif code.startswith("KEY_"):
            char = code[4:]
            if len(char) == 1:
                buffer.append(char)
            elif char == "MINUS":
                buffer.append("-")


# -----------------------
# Flask Endpoints
# -----------------------
@app.route("/", methods=["GET"])
@cross_origin()
def readTag():
    """Read one RFID tag and return it as JSON."""
    ensure_device()
    epc = read_tag()
    if epc:
        return jsonify({"epc": epc.lower()})
    else:
        return jsonify({"error": "RFID device not found"}), 500


# @app.route("/removetag", methods=["GET"])
# @cross_origin()
# def isTagRemoved():
#     """Wait for the user to physically remove the last tag."""
#     removed = wait_for_tag_removal()
#     if removed:
#         return jsonify({"status": "Tag removed"})
#     else:
#         return jsonify({"error": "Tag removal timeout"}), 500


# -----------------------
# Main Entry
# -----------------------
if __name__ == "__main__":
    logger.info(f"Initialising RFID Device on port {SERVER_PORT}")
    ensure_device()   
    logger.info(f"Starting RFID Flask server on port {SERVER_PORT}")
    app.run(host="0.0.0.0", port=SERVER_PORT, ssl_context=(CERT_FILE, KEY_FILE))

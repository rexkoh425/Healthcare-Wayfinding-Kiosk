import serial
import time
from flask import Flask, jsonify
from flask_cors import cross_origin
import threading, time, logging
from motor import *

# -----------------------
# Flask Setup
# -----------------------
app = Flask(__name__)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
SERVER_PORT = 5000
CERT_FILE = "/certs/cert.pem"
KEY_FILE = "/certs/key.pem"

current_tag = None
last_seen = 0
TAG_TIMEOUT = 1.5  # seconds without detection → tag removed

DEVICE_PORT = "/dev/ttyACM0"
BAUDRATE=9600

def tag_reader_loop():
    global current_tag, last_seen
    ser = serial.Serial(DEVICE_PORT, baudrate=BAUDRATE, timeout=0.1)
    buffer = b""

    while True:
        data = ser.read(64)  # read up to 64 bytes
        if data:
            buffer += data
            # Check for newline or known end marker (depends on your reader)
            if b"\r" in buffer or b"\n" in buffer:
                # clean + decode
                raw = data.decode('ascii', errors='ignore')
                # print(raw)
                raw = raw.replace('\r', '').replace('\n', '').replace('\x02', '').replace('\x03', '')
                
                buffer = b""
                if len(raw) == 24:  # adjust based on your tag length
                    if raw != current_tag:
                        logger.info(f"Tag detected: {raw}")
                    current_tag = raw
                    last_seen = time.time()
        time.sleep(0.05)

# Thread that monitors tag removal
def tag_monitor_loop():
    global current_tag
    while True:
        if current_tag and time.time() - last_seen > TAG_TIMEOUT:
            logger.info(f"Tag {current_tag} removed")
            current_tag = None
        time.sleep(0.2)

@app.route("/getTag", methods=["GET"])
@cross_origin()
def read_tag_endpoint():
    """Wait until a tag is detected, then return it."""
    motor_on()
    while current_tag is None:
        time.sleep(0.05)  # short sleep to avoid busy-waiting
    motor_off()
    return jsonify({"epc": current_tag.lower()})

@app.route("/tagRemoved", methods=["GET"])
@cross_origin()
def wait_tag_remove():
    """Return the current tag state."""
    if current_tag:
        logger.info("Tag still on reader")
    while current_tag:
        time.sleep(0.1)
    return jsonify({"status": "no_tag"})


if __name__ == "__main__":
    try:
        motor_off()
        threading.Thread(target=tag_reader_loop, daemon=True).start()
        threading.Thread(target=tag_monitor_loop, daemon=True).start()
        app.run(host="0.0.0.0", port=SERVER_PORT, ssl_context=(CERT_FILE, KEY_FILE))
    finally:
        motor_off()

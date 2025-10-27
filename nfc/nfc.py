#!/usr/bin/env python3
"""
This example shows connecting to the PN532 and reading an NTAG215
type RFID tag
"""
import time
import pn532.pn532 as nfc
from pn532 import *
from flask import Flask, jsonify
from flask_cors import CORS, cross_origin
import time
import logging
import csv

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

SERVER_PORT = 5001
CERT_FILE = "/certs/cert.pem"
KEY_FILE = "/certs/key.pem"


# -----------------------
# Get Location NFC ID mappings
# -----------------------
filename = '/data/directions-nus.csv'
mapping = {}

with open(filename, 'r', newline='') as file:
    reader = csv.reader(file)
    headers = next(reader)  # skip header if present

    for row in reader:
        # row[0] = first column, row[2] = third column
        mapping[row[2]] = [row[0]]


# -----------------------
# NFC Setup
# -----------------------

# pn532 = PN532_SPI(debug=False, reset=20, cs=4)
# pn532 = PN532_I2C(debug=False, reset=20, req=16)
pn532 = PN532_UART('/dev/serial0', debug=False)

ic, ver, rev, support = pn532.get_firmware_version()
logger.info('Found PN532 with firmware version: {0}.{1}'.format(ver, rev))

# Configure PN532 to communicate with NTAG215 cards
pn532.SAM_configuration()

def get_uid():
    logger.info('Waiting for NFC card!')
    while True:
        try:
            # Check if a card is available to read
            uid = pn532.read_passive_target(timeout=0.5)
            # Try again if no card is available.
            if uid is not None:
                break
        except (RuntimeError) as e : #untested
            logger.error(e)
            logger.info("Rerunning")
            continue
    uid_str = ''.join(f'{i:02x}' for i in uid)
    logger.info("UID: {}".format(uid_str))
    return uid_str 

@app.route("/", methods=["GET"])
@cross_origin()
def read_nfc():
    uid = get_uid()
    dest = mapping[uid]
    logger.info(f"Destination: {dest}")
    return jsonify({"destinations": dest}) #only 1 destination now
    

if __name__ == "__main__":
    logger.info(f"Starting NFC Flask server on port {SERVER_PORT}")
    app.run(host="0.0.0.0", port=SERVER_PORT, ssl_context=(CERT_FILE, KEY_FILE))
    # get_uid()
    # GPIO.cleanup()
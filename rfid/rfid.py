# rfid_server.py
import os   
from flask import Flask, jsonify
from flask_cors import CORS, cross_origin

app = Flask(__name__)
latest_epc = None
buffer = []
cors=CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

SERVER_PORT = 5000  # port for GET /activate

# Path to mounted certs
CERT_FILE = "certs/cert.pem"
KEY_FILE = "certs/key.pem"

# -----------------------
# RFID Keyboard Capture
# -----------------------

def start_rfid_listener():
    epc = input("Listening for EPC: ")
    return epc 
    

# -----------------------
# HTTP Endpoint
# -----------------------
@app.route("/", methods=["GET"])
@cross_origin()
def activate():
    epc = start_rfid_listener().lower()
    return jsonify({"epc": epc})
    

# -----------------------
# Start everything
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVER_PORT, ssl_context=(CERT_FILE, KEY_FILE))

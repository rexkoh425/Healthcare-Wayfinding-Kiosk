# Devices & Hardware

## Hologram Display
- Assets: `hologram-display/assets` (`wave.mp4`, `listen.mp4`, `reply.mp4`)
- Serve via HTTP (e.g., `npx http-server hologram-display -p 3001`)

## RFID
- Scripts & Dockerfile in `rfid/`
- HID mode quickstart (Linux):
```bash
cd rfid
sudo apt update
sudo apt install python3-evdev
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
sudo .venv/bin/python rfidv1.py
```
- Device info: `cat /proc/bus/input/devices`
- Docker example:
```bash
docker build -t rfidimage .
docker run --rm -p 5000:5000 --device /dev/input/event1:/dev/input/event1 rfidimage
```

## NFC
- Code in `nfc/`
- Uses PN532 reader; adjust serial device mapping in Docker/host as needed.

## OCR Service
- Code in `ocr-service/`
- Expects camera devices (`/dev/video*`) on hardware; environment:
  - `USB_DEVICE_INDEX`, `USB_WIDTH`, `USB_HEIGHT`, `USB_FPS`
  - `YOLO_CONFIG_DIR`, `YOLO_DEBUG_DIR`, `YOLO_DEBUG_LIMIT`
- Run via Docker Compose or `uvicorn service:app --host 0.0.0.0 --port 9000`

## Signboards (Long-Range RFID)
- ESP32 UHF RFID for long-range detection; integrate prompts with WS/HTTP to signboard displays.
- Provide per-device calibration and placement; not included in repo code.

## Sticker Dispenser
- Custom friction-based sticker dispenser; trigger logic in backend/signboard flow (not included here). Document GPIO/pinouts separately if needed.

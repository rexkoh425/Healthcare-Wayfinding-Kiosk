from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import os, time, json, asyncio
from threading import Lock
from pathlib import Path
from datetime import datetime
# this is for USB camera
import cv2
import numpy as np
import pytesseract
import logging

from ultralytics import YOLO

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS", "model_weights/best.pt")
CLASS_TO_VARIANT = {"1": 1, "2": 2, "3": 3}

TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "templates"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "/data/ocr_latest/frames"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Livestream detection throttling
STREAM_DET_INTERVAL = int(os.environ.get("STREAM_DET_INTERVAL", "10"))   # detect every N frames
STREAM_IMG_SIZE     = int(os.environ.get("STREAM_IMG_SIZE", "640"))     # YOLO imgsz for stream
STREAM_CONF         = float(os.environ.get("STREAM_CONF", "0.75"))

# Still-capture detection (kept for parity)
CAPTURE_IMG_SIZE    = int(os.environ.get("CAPTURE_IMG_SIZE", "800"))
CAPTURE_CONF        = float(os.environ.get("CAPTURE_CONF", "0.40"))

# Rotation flags for the stream frames
ROTATE_STILL_180  = os.environ.get("ROTATE_STILL_180", "0") == "1"
ROTATE_STREAM_180 = os.environ.get("ROTATE_STREAM_180", "1") == "1"
ROTATE_STREAM_90  = os.environ.get("ROTATE_STREAM_90",  "1") == "1"  # default True to match previous

# OCR gating
OCR_MIN_CONF      = 0.99     # 90%
OCR_COOLDOWN_SEC  = 5
_last_ocr_time    = 0.0

OCR_CHAR_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
OCR_CONFIGS = [
    f"--psm 6 -l eng --oem 3 -c tessedit_char_whitelist={OCR_CHAR_WHITELIST}",
    f"--psm 7 -l eng --oem 3 -c tessedit_char_whitelist={OCR_CHAR_WHITELIST}",
]

# Latest result cache for frontend polling
_latest_result     = None
_latest_result_ts  = 0.0

# Camera enable
CAMERA_ENABLED = os.environ.get("CAMERA_ENABLED", "0") == "1"

# USB camera settings
USB_DEVICE_INDEX = int(os.environ.get("USB_DEVICE_INDEX", "0"))
USB_WIDTH        = int(os.environ.get("USB_WIDTH", "1280"))
USB_HEIGHT       = int(os.environ.get("USB_HEIGHT", "720"))
USB_FPS          = int(os.environ.get("USB_FPS", "25"))

# Stream pacing (prevents fast/slow bursts)
TARGET_STREAM_FPS = int(os.environ.get("TARGET_STREAM_FPS", "15"))
_FRAME_PERIOD     = 1.0 / max(1, TARGET_STREAM_FPS)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# YOLO
# ──────────────────────────────────────────────────────────────────────────────
yolo_model = YOLO(YOLO_WEIGHTS, task="detect")

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI router + Camera (USB only)
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter()
_camera_init_lock = Lock()
_capture_lock     = Lock()

usb_cap = None           # type: cv2.VideoCapture | None
_camera_started = False

def _open_usb_camera():
    """
    Open a USB UVC camera. Use MJPG + tiny buffer for low latency.
    """
    # Prefer V4L2 backend on Linux
    cap = cv2.VideoCapture(USB_DEVICE_INDEX, cv2.CAP_V4L2)
    if not cap or not cap.isOpened():
        cap = cv2.VideoCapture(USB_DEVICE_INDEX)
    if not cap or not cap.isOpened():
        raise HTTPException(status_code=500, detail=f"USB camera not available at index {USB_DEVICE_INDEX}")

    # Best-effort property sets (some cams may ignore certain sets)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  USB_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, USB_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS,          USB_FPS)

    # Sanity-check: try one grab (don’t block if it fails)
    ok, _ = cap.read()
    if not ok:
        cap.release()
        raise HTTPException(status_code=500, detail="USB camera opened but failed to read a frame")

    return cap

def _ensure_camera_started():
    """Initialise and start the USB camera lazily."""
    global usb_cap, _camera_started
    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera disabled")

    with _camera_init_lock:
        if _camera_started and usb_cap is not None:
            return usb_cap

        usb_cap = _open_usb_camera()
        _camera_started = True
        log.info(f"USB camera started (idx={USB_DEVICE_INDEX}, {USB_WIDTH}x{USB_HEIGHT}@{USB_FPS}, MJPG)")
        return usb_cap

# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers for deskew
# ──────────────────────────────────────────────────────────────────────────────
def clip_box(box, w, h):
    x1, y1, x2, y2 = box
    return [max(0, int(x1)), max(0, int(y1)), min(w - 1, int(x2)), min(h - 1, int(y2))]

def enlarge_box_by_scale(box, img_w, img_h, scale_w=1.2, scale_h=1.2):
    """
    Expand a box by scale factors around its centre and clamp to the frame.
    """
    x1, y1, x2, y2 = map(float, box)
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    bw = (x2 - x1)
    bh = (y2 - y1)

    new_w = bw * float(scale_w)
    new_h = bh * float(scale_h)

    nx1 = int(round(cx - new_w * 0.5))
    ny1 = int(round(cy - new_h * 0.5))
    nx2 = int(round(cx + new_w * 0.5))
    ny2 = int(round(cy + new_h * 0.5))

    nx1 = max(0, min(img_w - 1, nx1))
    ny1 = max(0, min(img_h - 1, ny1))
    nx2 = max(1, min(img_w, nx2))
    ny2 = max(1, min(img_h, ny2))

    if nx2 <= nx1:
        nx2 = min(img_w, nx1 + 1)
    if ny2 <= ny1:
        ny2 = min(img_h, ny1 + 1)
    return nx1, ny1, nx2, ny2

def _order_box_points(pts):
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")

def find_minrect_and_crop(upright_bgr):
    dbg = []
    h, w = upright_bgr.shape[:2]
    g = cv2.cvtColor(upright_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    edges = cv2.Canny(g, 60, 160)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, dbg
    img_area = float(h * w)
    best_rect, best_c, best_score = None, None, -1.0
    for c in cnts:
        if len(c) < 4:
            continue
        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        rect_area = float(max(rw * rh, 1.0))
        if rect_area < 0.25 * img_area:
            continue
        aspect = max(rw, rh) / (min(rw, rh) + 1e-6)
        if aspect > 5.0:
            continue
        cnt_area = cv2.contourArea(c)
        extent = float(cnt_area) / rect_area
        (cx, cy) = rect[0]
        dx = (cx - w / 2.0) / w
        dy = (cy - h / 2.0) / h
        center_bonus = 1.0 - min(1.0, (dx * dx + dy * dy) ** 0.5 * 2.0)
        score = (rect_area / img_area) + 0.8 * extent + 0.2 * center_bonus - 0.02 * abs(aspect - 1.5)
        if score > best_score:
            best_score, best_rect, best_c = score, rect, c
    if best_rect is None:
        return None, dbg
    box = cv2.boxPoints(best_rect).astype("float32")
    ordered = _order_box_points(box)
    (tl, tr, br, bl) = ordered
    widthA  = np.linalg.norm(br - bl)
    widthB  = np.linalg.norm(tr - tl)
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    W = int(round(max(widthA, widthB))); W = max(W, 1)
    H = int(round(max(heightA, heightB))); H = max(H, 1)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
    P = cv2.getPerspectiveTransform(ordered, dst)
    roi = cv2.warpPerspective(upright_bgr, P, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return roi, [("chosen_score", round(best_score,3)), ("rect_size",(W,H))]

# ──────────────────────────────────────────────────────────────────────────────
# Template selection + crop
# ──────────────────────────────────────────────────────────────────────────────
def select_template_path_from_class(cls_name: str) -> Path:
    variant = CLASS_TO_VARIANT.get(cls_name)
    if not variant:
        raise FileNotFoundError(f"No template mapping for class '{cls_name}'")
    p = TEMPLATE_DIR / f"registration_{variant}.json"
    if not p.exists():
        raise FileNotFoundError(f"Template not found: {p}")
    return p

def apply_template_crops(img_bgr, template_path: Path, out_dir: Path, stem: str, draw_overlay=True):
    H, W = img_bgr.shape[:2]
    tpl = json.loads(Path(template_path).read_text())
    overlay = img_bgr.copy()
    out_paths = []
    for spec in tpl:
        x = int(float(spec["x"]) * W); y = int(float(spec["y"]) * H)
        w = int(float(spec["w"]) * W); h = int(float(spec["h"]) * H)
        x2, y2 = min(W, x + w), min(H, y + h)

        pad = 4
        yy1 = max(0, y - pad); yy2 = min(H, y2 + pad)
        xx1 = max(0, x - pad); xx2 = min(W, x2 + pad)
        roi = img_bgr[yy1:yy2, xx1:xx2].copy()

        out_p = out_dir / f"{stem}_{spec['name']}.jpg"
        cv2.imwrite(str(out_p), roi)
        out_paths.append(out_p)
        if draw_overlay:
            cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)
            (tw, th), base = cv2.getTextSize(spec["name"], cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            lx, ly = x, max(th + 6, y - 6)
            cv2.rectangle(overlay, (lx - 3, ly - th - 3), (lx + tw + 3, ly + base + 2), (0, 0, 0), cv2.FILLED)
            cv2.putText(overlay, spec["name"], (lx, ly),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    if draw_overlay:
        ov_p = out_dir / f"{stem}.template_overlay.jpg"
        cv2.imwrite(str(ov_p), overlay)
    return out_paths

# ──────────────────────────────────────────────────────────────────────────────
# Livestream overlay (YOLO)
# ──────────────────────────────────────────────────────────────────────────────
_last_boxes = []
_frame_idx  = 0

def _yolo_detect_boxes(img_bgr, imgsz, conf):
    if yolo_model is None:
        return []
    res = yolo_model.predict(img_bgr, imgsz=imgsz, conf=conf, verbose=False)[0]
    out = []
    for bb in res.boxes:
        c = float(bb.conf.detach().cpu().item())
        cls_id = int(bb.cls.detach().cpu().item())
        cls_name = yolo_model.names[cls_id]
        x1, y1, x2, y2 = [float(v) for v in bb.xyxy[0].tolist()]
        out.append((x1, y1, x2, y2, c, cls_name))
    return out

def _draw_boxes(img_bgr, boxes, color=(0,255,0)):
    for (x1,y1,x2,y2,c,cls) in boxes:
        p1 = (int(x1), int(y1)); p2 = (int(x2), int(y2))
        cv2.rectangle(img_bgr, p1, p2, color, 2)
        label = f"{cls} {c:.2f}"
        cv2.putText(img_bgr, label, (p1[0], max(15, p1[1]-6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return img_bgr

# ──────────────────────────────────────────────────────────────────────────────
# OCR
# ──────────────────────────────────────────────────────────────────────────────
def _run_ocr_on_detection(frame_bgr, det, cls_name):
    # det = (x1,y1,x2,y2,conf,cls_name)
    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = map(int, det[:4])

    # Expand and clamp the detection box; improves downstream deskew.
    x1c, y1c, x2c, y2c = clip_box((x1, y1, x2, y2), W, H)
    ex1, ey1, ex2, ey2 = enlarge_box_by_scale((x1c, y1c, x2c, y2c), W, H, 1.2, 1.2)
    crop = frame_bgr[ey1:ey2, ex1:ex2].copy()
    if crop.size == 0:
        raise RuntimeError("Scaled crop for OCR is empty")

    # deskew to min-area rectangle
    rect_img, dbg = find_minrect_and_crop(crop)
    if rect_img is None or rect_img.size == 0:
        raise RuntimeError("Rectangular slip region not found in stream frame.")

    # choose template by class
    tpl_path = select_template_path_from_class(cls_name)

    # save crops + overlay
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    stem = f"slip_{ts}"
    _ = apply_template_crops(rect_img, tpl_path, OUT_DIR, stem, draw_overlay=True)

    # OCR the clinic_* fields, keep order
    clinics_in_order, fields = [], {}
    for idx in (1, 2, 3):
        p = OUT_DIR / f"{stem}_clinic_{idx}.jpg"
        if p.exists():
            imgc = cv2.imread(str(p))
            if imgc is None or imgc.size == 0:
                continue

            text = ""
            for cfg in OCR_CONFIGS:
                text = pytesseract.image_to_string(imgc, config=cfg).strip()
                if text:
                    break

            fields[f"clinic_{idx}"] = text
            if text:
                clinics_in_order.append(text)

    result = {
        "capture_id": ts,
        "yolo": {"class": cls_name, "conf": float(det[4]), "box": [x1,y1,x2,y2]},
        "locations": clinics_in_order,
        "clinics": clinics_in_order,
        "fields": fields,
        "outputs": {
            "overlay": str((OUT_DIR / f"{stem}.template_overlay.jpg").as_posix()),
            "crops_dir": str(OUT_DIR.as_posix())
        }
    }
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2))

    # publish latest result for frontend polling
    global _latest_result, _latest_result_ts
    _latest_result = {
        "locations": result.get("locations", []),
        "yolo": result["yolo"],
        "capture_id": result["capture_id"],
    }
    _latest_result_ts = time.time()

    return result

# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/ocr")
async def run_ocr():
    # Demo payload (real OCR is triggered from the stream when a good box appears)
    result = {
        "capture_id": "demo-capture",
        "locations": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "yolo": {"class": "slip_1", "conf": 0.99, "box": [12, 34, 200, 320]},
        "clinics": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "fields": {
            "clinic_1": "Ward 2",
            "clinic_2": "Orthopaedic Centre",
            "clinic_3": "Clinic J",
        },
        "outputs": {
            "overlay": "/data/ocr_latest/frames/demo-capture.template_overlay.jpg",
            "crops_dir": "/data/ocr_latest/frames"
        },
    }

    global _latest_result, _latest_result_ts
    _latest_result = {
        "locations": result["locations"],
        "yolo": result["yolo"],
        "capture_id": result["capture_id"],
    }
    _latest_result_ts = time.time()

    return JSONResponse(content=result)

def _render_stream_frame():
    """
    Capture, annotate, and encode a single frame for the MJPEG stream (USB cam).
    Includes:
      - MJPG + buffer=1 at device level (set in _open_usb_camera)
      - Pacing to TARGET_STREAM_FPS to avoid burstiness
      - YOLO on a downsized copy; boxes rescaled to original frame
    """
    global _last_boxes, _frame_idx, _last_ocr_time

    if not CAMERA_ENABLED:
        raise RuntimeError("Camera disabled")

    cam_handle = _ensure_camera_started()

    with _capture_lock:
        ret, frame = cam_handle.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to read from USB camera")
        # frame is BGR

    if ROTATE_STREAM_180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    if ROTATE_STREAM_90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    # Run detection every N frames on a downsized copy; rescale boxes back
    if yolo_model is not None and (_frame_idx % STREAM_DET_INTERVAL == 0):
        try:
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (STREAM_IMG_SIZE, STREAM_IMG_SIZE), interpolation=cv2.INTER_AREA)
            boxes_small = _yolo_detect_boxes(small, STREAM_IMG_SIZE, STREAM_CONF)
            sx = w / float(STREAM_IMG_SIZE)
            sy = h / float(STREAM_IMG_SIZE)
            _last_boxes = [(x1*sx, y1*sy, x2*sx, y2*sy, c, cls) for (x1,y1,x2,y2,c,cls) in boxes_small]
        except Exception as e:
            _last_boxes = []

    _frame_idx += 1

    best_conf = 0.0
    best_det = None
    if _last_boxes:
        best_det = max(_last_boxes, key=lambda b: b[4])
        best_conf = best_det[4]
        frame = _draw_boxes(frame, _last_boxes, (0, 255, 0))

    cv2.putText(
        frame,
        f"frm:{_frame_idx} det:{len(_last_boxes)} conf:{best_conf*100:.1f}%",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
    )

    # Time-gated OCR (by seconds), not every frame
    now = time.time()
    if best_det and best_conf >= OCR_MIN_CONF and (now - _last_ocr_time) >= OCR_COOLDOWN_SEC:
        try:
            _ = _run_ocr_on_detection(frame.copy(), best_det, best_det[5])
            _last_ocr_time = now
            cv2.putText(frame, "OCR OK", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        except Exception as e:
            cv2.putText(frame, f"OCR ERR: {str(e)[:28]}", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # Pace the stream output to a fixed FPS to avoid burstiness
    t_now = time.time()
    if not hasattr(_render_stream_frame, "_last_t"):
        _render_stream_frame._last_t = t_now
    dt = t_now - _render_stream_frame._last_t
    if dt < _FRAME_PERIOD:
        time.sleep(_FRAME_PERIOD - dt)
    _render_stream_frame._last_t = time.time()

    # Encode MJPEG chunk
    ok, jpeg = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return (
        b"--FRAME\r\n"
        b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
    )

@router.get("/stream.mjpg")
async def stream(request: Request):
    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera livestream disabled")

    async def generate():
        log.info("USB stream start")
        try:
            while True:
                if await request.is_disconnected():
                    log.info("client disconnected; stopping MJPEG stream")
                    break
                chunk = await asyncio.to_thread(_render_stream_frame)
                yield chunk
        except asyncio.CancelledError:
            raise
        finally:
            log.info("stream generator closed")

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=FRAME",
    )

@router.get("/latest_result")
def latest_result():
    if _latest_result is None:
        return {"ready": False}
    return {"ready": True, "updated_at": _latest_result_ts, "data": _latest_result}

@router.get("/health")
def health():
    return {"ok": True}

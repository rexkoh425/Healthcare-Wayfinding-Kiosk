from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import os, time, json, traceback, glob, asyncio
from threading import Lock
from pathlib import Path
from datetime import datetime
# This is for PI camera
import cv2
import numpy as np
import pytesseract
import logging

from picamera2 import Picamera2
from libcamera import controls
from ultralytics import YOLO

# If you need existing helpers, keep them; not strictly used in this pipeline.
# from .ocr_v3 import extract
# from .helpers import preprocess_bgr, extract_clinic_locations, crop_percent

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
#YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS", "model_weights/best_ncnn_model")
YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS", "model_weights/best.pt")
CLASS_TO_VARIANT = {"slip_1": 1, "slip_2": 2, "slip_3": 3}
TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "templates"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "/data/ocr_latest/frames"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Livestream detection throttling
STREAM_DET_INTERVAL = int(os.environ.get("STREAM_DET_INTERVAL", "5"))  # detect every N frames
STREAM_IMG_SIZE = int(os.environ.get("STREAM_IMG_SIZE", "640"))        # YOLO imgsz for stream
STREAM_CONF = float(os.environ.get("STREAM_CONF", "0.25"))

# Still-capture detection
CAPTURE_IMG_SIZE = int(os.environ.get("CAPTURE_IMG_SIZE", "800"))
CAPTURE_CONF = float(os.environ.get("CAPTURE_CONF", "0.25"))

ROTATE_STILL_180 = os.environ.get("ROTATE_STILL_180", "0") == "1"
ROTATE_STREAM_180 = False
ROTATE_STREAM_90 = True

OCR_MIN_CONF = 0.90          # 90%
OCR_COOLDOWN_SEC = 5         # don’t OCR more than once every 5s
_last_ocr_time = 0.0

_latest_result = None
_latest_result_ts = 0.0
CAMERA_ENABLED = os.environ.get("CAMERA_ENABLED", "0") == "1"


log = logging.getLogger(__name__)
# ──────────────────────────────────────────────────────────────────────────────
# YOLO
# ──────────────────────────────────────────────────────────────────────────────
yolo_model = YOLO(YOLO_WEIGHTS, task="detect")

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI router + Camera
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter()
_camera_init_lock = Lock()
_capture_lock = Lock()

os.environ['PICAMERA2_USE_V4L2'] = '1'

picam: Picamera2 | None = None
vid_config = None
pic_config = None
_camera_started = False


def _ensure_camera_started() -> Picamera2:
    """Initialise and start the camera lazily, retrying once on failure."""
    global picam, vid_config, pic_config, _camera_started

    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera disabled")

    with _camera_init_lock:
        if picam is None:
            picam = Picamera2()
            vid_config = picam.create_video_configuration(
                main={"size": (1536, 864)},
                controls={"FrameRate": 20},
            )
            pic_config = picam.create_still_configuration(
                main={"size": (4608, 2592)},
                controls={"AfMode": 1},
            )

        if not _camera_started:
            try:
                picam.configure(vid_config)
                picam.start()
                _camera_started = True
                log.info("Camera started")
            except RuntimeError as exc:
                log.error("Primary camera start failed: %s", exc)
                try:
                    picam.close()
                except Exception:
                    pass
                picam = Picamera2()
                vid_config = picam.create_video_configuration(
                    main={"size": (1536, 864)},
                    controls={"FrameRate": 20},
                )
                pic_config = picam.create_still_configuration(
                    main={"size": (4608, 2592)},
                    controls={"AfMode": 1},
                )
                try:
                    picam.configure(vid_config)
                    picam.start()
                    _camera_started = True
                    log.info("Camera restarted after recovery")
                except RuntimeError as exc2:
                    log.error("Camera restart failed: %s", exc2)
                    raise HTTPException(status_code=500, detail="Camera unavailable") from exc2

    return picam

# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers for deskew
# ──────────────────────────────────────────────────────────────────────────────
def clip_box(box, w, h):
    x1, y1, x2, y2 = box
    return [max(0, int(x1)), max(0, int(y1)), min(w - 1, int(x2)), min(h - 1, int(y2))]

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
        x = int(spec["x"] * W); y = int(spec["y"] * H)
        w = int(spec["w"] * W); h = int(spec["h"] * H)
        x2, y2 = min(W, x+w), min(H, y+h)
        roi = img_bgr[y:y2, x:x2].copy()
        out_p = out_dir / f"{stem}_{spec['name']}.jpg"
        cv2.imwrite(str(out_p), roi)
        out_paths.append(out_p)
        if draw_overlay:
            cv2.rectangle(overlay, (x,y), (x+w,y+h), (0,0,255), 2)
            cv2.putText(overlay, spec["name"], (x, max(16,y-6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
    if draw_overlay:
        ov_p = out_dir / f"{stem}.template_overlay.jpg"
        cv2.imwrite(str(ov_p), overlay)
    return out_paths

# ──────────────────────────────────────────────────────────────────────────────
# Livestream overlay (YOLO)
# ──────────────────────────────────────────────────────────────────────────────
_last_boxes = []
_frame_idx = 0

def _yolo_detect_boxes(img_bgr, imgsz, conf):
    if yolo_model is None:
        log.info("[det] no models found")
        return []
    res = yolo_model.predict(img_bgr, imgsz=imgsz, conf=conf, verbose=False)[0]
    out = []
    log.info(f"boxes{len(res.boxes)}")
    h, w = img_bgr.shape[:2]
    for bb in res.boxes:
        c = float(bb.conf.detach().cpu().item())
        cls_id = int(bb.cls.detach().cpu().item())
        log.error(yolo_model.names)
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

    # pad & clip
    PAD = 12
    x1p = max(0, x1 - PAD); y1p = max(0, y1 - PAD)
    x2p = min(W - 1, x2 + PAD); y2p = min(H - 1, y2 + PAD)
    crop = frame_bgr[y1p:y2p, x1p:x2p].copy()

    # deskew to min-area rectangle
    rect_img, dbg = find_minrect_and_crop(crop)
    if rect_img is None or rect_img.size == 0:
        raise RuntimeError("Rectangular slip region not found in stream frame.")

    # choose template by class
    tpl_path = select_template_path_from_class(cls_name)

    # save crops + overlay
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    stem = f"slip_{ts}"
    crop_paths = apply_template_crops(rect_img, tpl_path, OUT_DIR, stem, draw_overlay=True)

    # OCR the clinic_* fields, keep order
    clinics_in_order, fields = [], {}
    for idx in [1, 2, 3]:
        p = OUT_DIR / f"{stem}_clinic_{idx}.jpg"
        if p.exists():
            imgc = cv2.imread(str(p))
            txt = pytesseract.image_to_string(imgc, config="--psm 6").strip()
            fields[f"clinic_{idx}"] = txt
            if txt:
                clinics_in_order.append(txt)

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

    (OUT_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2))

    # publish latest result for frontend polling
    global _latest_result, _latest_result_ts
    _latest_result = {
        "locations": result.get("locations", []),   # important: frontend expects locations
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
    """Capture, annotate, and encode a single frame for the MJPEG stream."""
    global _last_boxes, _frame_idx, _last_ocr_time

    if not CAMERA_ENABLED:
        raise RuntimeError("Camera disabled")

    camera = _ensure_camera_started()

    with _capture_lock:
        frame = camera.capture_array()
        if frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    if ROTATE_STREAM_180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)

    if ROTATE_STREAM_90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if yolo_model is not None and (_frame_idx % STREAM_DET_INTERVAL == 0):
        try:
            _last_boxes = _yolo_detect_boxes(frame, STREAM_IMG_SIZE, STREAM_CONF)
            log.error("Ran inference")
        except Exception as e:
            print(f"[stream] YOLO predict error: {e}")
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

    now = time.time()
    if best_det and best_conf >= OCR_MIN_CONF and (now - _last_ocr_time) >= OCR_COOLDOWN_SEC:
        try:
            frame_copy = frame.copy()
            cls_name = best_det[5]
            _ = _run_ocr_on_detection(frame_copy, best_det, cls_name)
            _last_ocr_time = now
            cv2.putText(frame, "OCR OK", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        except Exception as e:
            cv2.putText(frame, f"OCR ERR: {str(e)[:28]}", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    _, jpeg = cv2.imencode(".jpg", frame)
    return (
        b"--FRAME\r\n"
        b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
    )


@router.get("/stream.mjpg")
async def stream(request: Request):
    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera livestream disabled")

    async def generate():
        log.error("running stream")
        try:
            while True:
                if await request.is_disconnected():
                    log.info("client disconnected; stopping MJPEG stream")
                    break
                chunk = await asyncio.to_thread(_render_stream_frame)
                yield chunk
        except asyncio.CancelledError:
            log.info("stream generator cancelled")
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
def health(): return {"ok": True}

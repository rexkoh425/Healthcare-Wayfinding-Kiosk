from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import os, time, json, asyncio
import re
from collections import deque
from threading import Lock
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from typing import Tuple, Optional, List, Dict, Any
import cv2
import numpy as np
import pytesseract
import logging
from picamera2 import Picamera2
from libcamera import controls
from ultralytics import YOLO

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS", "model_weights/best.pt")
CLASS_TO_VARIANT = {"1": 1, "2": 2, "3": 3}

TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "templates"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "/data/ocr_latest/frames"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("PICAMERA2_USE_V4L2", "1")

# Detection settings
STREAM_DET_INTERVAL = int(os.environ.get("STREAM_DET_INTERVAL", "10"))
STREAM_IMG_SIZE     = int(os.environ.get("STREAM_IMG_SIZE", "640"))
STREAM_CONF         = float(os.environ.get("STREAM_CONF", "0.25"))

# Rotation flags
ROTATE_STREAM_90  = os.environ.get("ROTATE_STREAM_90",  "1") == "1"
ROTATE_STREAM_180 = os.environ.get("ROTATE_STREAM_180", "0") == "1"

# OCR settings
OCR_MIN_CONF      = 0.88
OCR_COOLDOWN_SEC  = 5
_last_ocr_time    = 0.0

FUZZY_MATCH_THRESHOLD = float(os.environ.get("OCR_FUZZY_MATCH_THRESHOLD", "0.1"))

# Camera settings
CAMERA_ENABLED = os.environ.get("CAMERA_ENABLED", "0") == "1"
PICAM_VIDEO_SIZE = (1280, 720)
PICAM_FRAME_RATE = 15
PICAM_AF_MODE    = controls.AfModeEnum.Continuous
PICAM_AF_RANGE   = controls.AfRangeEnum.Full
PICAM_AF_SPEED   = controls.AfSpeedEnum.Normal

# Stream settings
TARGET_STREAM_FPS = int(os.environ.get("TARGET_STREAM_FPS", "8"))
_FRAME_PERIOD     = 1.0 / max(1, TARGET_STREAM_FPS)
STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "85"))
PICAM_COLOR_SPACE = os.environ.get("PICAM_COLOR_SPACE", "RGB").strip().upper()

TEMPLATE_CROP_PAD = int(os.environ.get("TEMPLATE_CROP_PAD", "4"))
TESSERACT_WIN_PATH = os.environ.get("TESSERACT_WIN_PATH", "")

# Latest result cache
_latest_result     = None
_latest_result_ts  = 0.0

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Location matching (simplified)
# ──────────────────────────────────────────────────────────────────────────────
LOCATION_CANDIDATES = [
    "Diagnostic Imaging 2", "Urgent Care Centre", "Ward 8", "Ward 9",
    "Diagnostic Imaging 3", "Major Operating Theatres 1 & 2", "Ward 10", "Ward 11",
    "Intensive Care Unit 1", "Major Operating Theatres 3 & 4", "Ward 12", "Ward 13",
    "Clinical Measurement Centre", "Pharmacy", "Clinic J", "Clinic K", "Ward 7",
    "Care and Counselling", "Ear, Nose and Throat Centre", "Eye Surgery Centre",
    "Surgery Centre", "Ambulatory Surgery Centre", "Endoscopy Centre", 
    "NUCOHS Dental Clinic", "Orthopaedic Centre", "Rehabilitation 1", "Ward 2",
    "Ward 3", "Day Surgery Operating Theatre", "Ward 4", "Ward 5",
    "Diagnostic Imaging 1",
]

def sanitize_ocr_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    cleaned = str(value).replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def fuzzy_match_location(text: Optional[str], threshold: float = FUZZY_MATCH_THRESHOLD) -> Tuple[Optional[str], float]:
    threshold = max(0.0, min(1.0, float(threshold)))
    cleaned = sanitize_ocr_text(text).lower()
    if not cleaned:
        return None, 0.0
    cleaned_simple = re.sub(r"[^a-z0-9]+", "", cleaned)
    best_name, best_score = None, 0.0
    for candidate in LOCATION_CANDIDATES:
        cand_lower = candidate.lower()
        candidate_simple = re.sub(r"[^a-z0-9]+", "", cand_lower)
        base = SequenceMatcher(None, cleaned, cand_lower).ratio()
        simple = SequenceMatcher(None, cleaned_simple, candidate_simple).ratio()
        score = max(base, simple)
        if score > best_score:
            best_score = score
            best_name = candidate
    if best_score < threshold:
        return None, best_score
    return best_name, best_score

# ──────────────────────────────────────────────────────────────────────────────
# YOLO OBB Model
# ──────────────────────────────────────────────────────────────────────────────
yolo_model = YOLO(YOLO_WEIGHTS, task="obb")

# ──────────────────────────────────────────────────────────────────────────────
# Camera setup
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter()
_camera_init_lock = Lock()
_capture_lock     = Lock()

picam: Optional[Picamera2] = None
_picam_video_config = None
_camera_started = False

def _ensure_camera_started():
    global picam, _picam_video_config, _camera_started
    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera disabled")

    with _camera_init_lock:
        def _init_camera():
            cam = Picamera2()
            video_cfg = cam.create_video_configuration(
                main={"size": PICAM_VIDEO_SIZE},
                controls={
                    "FrameRate": PICAM_FRAME_RATE,
                    "AfMode": PICAM_AF_MODE,
                    "AfRange": PICAM_AF_RANGE,
                    "AfSpeed": PICAM_AF_SPEED,
                },
            )
            return cam, video_cfg

        if picam is None or _picam_video_config is None:
            picam, _picam_video_config = _init_camera()

        if not _camera_started:
            try:
                picam.configure(_picam_video_config)
                picam.start()
                _camera_started = True
                log.info("Pi camera started (%dx%d@%d)", PICAM_VIDEO_SIZE[0], PICAM_VIDEO_SIZE[1], PICAM_FRAME_RATE)
            except RuntimeError as exc:
                log.error("Camera start failed: %s", exc)
                raise HTTPException(status_code=500, detail="Pi camera unavailable") from exc

        return picam

# ──────────────────────────────────────────────────────────────────────────────
# Drawing functions from video annotation script
# ──────────────────────────────────────────────────────────────────────────────
GREEN = (0, 255, 0)

def _put_label(img, anchor_xy, text, color=GREEN):
    x1, y1 = map(int, anchor_xy)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    th = max(th, 16)
    bg_y1 = max(0, y1 - th - 4)
    x1 = max(0, min(x1, img.shape[1] - 1))
    y1 = max(0, min(y1, img.shape[0] - 1))
    cv2.rectangle(img, (x1, bg_y1), (x1 + tw + 8, y1), color, -1)
    cv2.putText(img, text, (x1 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)

def _draw_obb_poly(img, pts4x2, label_text, color=GREEN, thickness=2):
    pts = pts4x2.astype(int)
    cv2.polylines(img, [pts], isClosed=True, color=color, thickness=thickness)
    tl_idx = np.lexsort((pts[:,0], pts[:,1]))[0]
    _put_label(img, pts[tl_idx], label_text, color)


def _yolo_detect_obb(img_bgr, imgsz, conf):
    if yolo_model is None:
        return []
    
    try:
        # YOLO handles resizing internally via the imgsz parameter
        res = yolo_model.predict(img_bgr, imgsz=imgsz, conf=conf, iou=0.45, verbose=False)[0]
        
        if res is None or not hasattr(res, 'obb') or res.obb is None:
            return []
        
        out = []
        obb = res.obb
        
        # Handle both OBB formats
        if hasattr(obb, 'xyxyxyxy') and obb.xyxyxyxy is not None:
            xy8 = obb.xyxyxyxy.cpu().numpy()
            confs = obb.conf.cpu().numpy() if obb.conf is not None else np.ones(len(xy8), dtype=np.float32)
            cls_ids = obb.cls.cpu().numpy().astype(int) if obb.cls is not None else np.zeros(len(xy8), dtype=int)
            
            for idx, pts8 in enumerate(xy8):
                polygon = pts8.reshape(4, 2)
                confidence = float(confs[idx])
                cls_id = cls_ids[idx]
                cls_name = yolo_model.names.get(int(cls_id), str(int(cls_id)))
                out.append((polygon, confidence, cls_name))
                
        elif hasattr(obb, 'xywhr') and obb.xywhr is not None:
            xywhr = obb.xywhr.cpu().numpy()
            confs = obb.conf.cpu().numpy() if obb.conf is not None else np.ones(len(xywhr), dtype=np.float32)
            cls_ids = obb.cls.cpu().numpy().astype(int) if obb.cls is not None else np.zeros(len(xywhr), dtype=int)
            
            for idx, (cx, cy, w, h, angle_rad) in enumerate(xywhr):
                angle_deg = np.degrees(angle_rad)
                rect = ((float(cx), float(cy)), (float(w), float(h)), float(angle_deg))
                polygon = cv2.boxPoints(rect)
                confidence = float(confs[idx])
                cls_id = cls_ids[idx]
                cls_name = yolo_model.names.get(int(cls_id), str(int(cls_id)))
                out.append((polygon, confidence, cls_name))
        
        return out
        
    except Exception as e:
        log.error(f"YOLO OBB detection error: {e}")
        return []
    

def normalize_frame_color(frame: np.ndarray) -> np.ndarray:
    if frame is None or frame.ndim != 3:
        return frame

    channels = frame.shape[2]
    try:
        if channels == 4:
            if PICAM_COLOR_SPACE == "RGB":
                return cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
            if PICAM_COLOR_SPACE == "BGR":
                return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            return frame[:, :, :3]
        if channels >= 3:
            if PICAM_COLOR_SPACE == "RGB":
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if PICAM_COLOR_SPACE == "BGR":
                return frame
    except Exception:
        pass
    return frame

# ──────────────────────────────────────────────────────────────────────────────
# OCR Functions (simplified)
# ──────────────────────────────────────────────────────────────────────────────
def select_template_path_from_class(cls_name: str) -> Path:
    variant = CLASS_TO_VARIANT.get(cls_name)
    if not variant:
        raise FileNotFoundError(f"No template mapping for class '{cls_name}'")
    p = TEMPLATE_DIR / f"registration_{variant}.json"
    if not p.exists():
        raise FileNotFoundError(f"Template not found: {p}")
    return p

def load_template_rects(template_path: Path, rect_W: int, rect_H: int) -> List[Dict[str, Any]]:
    tpl = json.loads(Path(template_path).read_text(encoding="utf-8"))
    rect_specs: List[Dict[str, Any]] = []
    for i, spec in enumerate(tpl):
        for key in ("x", "y", "w", "h", "name"):
            if key not in spec:
                raise ValueError(f"template item #{i} missing key '{key}'")
        x = int(float(spec["x"]) * rect_W)
        y = int(float(spec["y"]) * rect_H)
        w = int(float(spec["w"]) * rect_W)
        h = int(float(spec["h"]) * rect_H)
        rect_specs.append(dict(name=spec["name"], x=x, y=y, w=w, h=h))
    return rect_specs

def crop_by_specs(rect_img: np.ndarray, rect_specs: List[Dict[str, Any]], pad: int = 4) -> Dict[str, np.ndarray]:
    H, W = rect_img.shape[:2]
    out: Dict[str, np.ndarray] = {}
    for spec in rect_specs:
        x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
        x2, y2 = x + w, y + h
        yy1 = max(0, y - pad)
        yy2 = min(H, y2 + pad)
        xx1 = max(0, x - pad)
        xx2 = min(W, x2 + pad)
        if yy2 <= yy1 or xx2 <= xx1:
            continue
        roi = rect_img[yy1:yy2, xx1:xx2].copy()
        out[spec["name"]] = roi
    return out

def ocr_clinic_fields_for_crops(crops: Dict[str, np.ndarray]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if pytesseract is None:
        return results

    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    cfgs = [
        f"--psm 6 -l eng --oem 3 -c tessedit_char_whitelist={whitelist}",
        f"--psm 7 -l eng --oem 3 -c tessedit_char_whitelist={whitelist}",
    ]

    for name, img in crops.items():
        if img is None or img.size == 0:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bw = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 5
        )
        best_text = ""
        raw_text = ""
        for cfg in cfgs:
            candidate = pytesseract.image_to_string(bw, config=cfg)
            candidate_clean = sanitize_ocr_text(candidate)
            if candidate_clean:
                best_text = candidate_clean
                raw_text = candidate.strip()
                break
        if not best_text:
            continue
        match, score = fuzzy_match_location(best_text)
        results.append({
            "field": name,
            "raw": raw_text,
            "text": best_text,
            "fuzzy_match": match,
            "fuzzy_score": round(score, 4) if score is not None else None,
        })
    return results

def _run_ocr_on_detection(frame_bgr, det, cls_name):
    """Run OCR using proper OBB perspective transformation"""
    cls_name = str(cls_name)
    H, W = frame_bgr.shape[:2]

    if isinstance(det[0], np.ndarray):  # OBB detection
        polygon, conf, det_cls_name = det
        if det_cls_name:
            cls_name = det_cls_name
        
        quad_global = polygon.astype(np.float32)
        det_conf_value = conf
        
        # Perspective transformation for deskewing
        width = int(max(np.linalg.norm(quad_global[0] - quad_global[1]),
                       np.linalg.norm(quad_global[2] - quad_global[3])))
        height = int(max(np.linalg.norm(quad_global[1] - quad_global[2]),
                        np.linalg.norm(quad_global[3] - quad_global[0])))
        
        dst_points = np.array([
            [0, 0],
            [width, 0], 
            [width, height],
            [0, height]
        ], dtype=np.float32)
        
        M = cv2.getPerspectiveTransform(quad_global, dst_points)
        rect_img = cv2.warpPerspective(frame_bgr, M, (width, height))
        
    else:  # Regular detection fallback
        x1, y1, x2, y2, conf, det_cls_name = det
        if det_cls_name:
            cls_name = det_cls_name
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        rect_img = frame_bgr[max(0,y1):min(H,y2), max(0,x1):min(W,x2)].copy()
        det_conf_value = conf

    if rect_img.size == 0:
        return None

    rect_h, rect_w = rect_img.shape[:2]
    final_cls = cls_name

    try:
        tpl_path = select_template_path_from_class(final_cls)
        rect_specs = load_template_rects(tpl_path, rect_w, rect_h)
        crops_by_name = crop_by_specs(rect_img, rect_specs, pad=TEMPLATE_CROP_PAD)

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        stem = f"slip_{ts}"

        # Save crops
        for name, roi in crops_by_name.items():
            if roi is not None and roi.size > 0:
                crop_path = OUT_DIR / f"{stem}_{name}.jpg"
                cv2.imwrite(str(crop_path), roi)

        ocr_results = ocr_clinic_fields_for_crops(crops_by_name)
        results_by_name = {item["field"]: item for item in ocr_results}
        
        fields = {}
        clinics_in_order: List[str] = []
        for spec in rect_specs:
            name = spec["name"]
            entry = results_by_name.get(name)
            if not entry:
                continue
            fields[name] = {
                "raw": entry.get("raw") or "",
                "clean": entry.get("text") or "",
                "match": entry.get("fuzzy_match"),
                "match_score": entry.get("fuzzy_score"),
            }
            if entry.get("fuzzy_match"):
                clinics_in_order.append(entry["fuzzy_match"])
            elif entry.get("text"):
                clinics_in_order.append(entry["text"])

        # Compute AABB for backward compatibility
        if isinstance(det[0], np.ndarray):
            x_coords = polygon[:, 0]
            y_coords = polygon[:, 1]
            bbox = [x_coords.min(), y_coords.min(), x_coords.max(), y_coords.max()]
            x1c, y1c, x2c, y2c = [int(v) for v in bbox]
        else:
            x1c, y1c, x2c, y2c = int(x1), int(y1), int(x2), int(y2)

        result = {
            "capture_id": ts,
            "yolo": {
                "class": final_cls,
                "conf": float(det_conf_value),
                "box": [x1c, y1c, x2c, y2c],
                "height_px": rect_h,
            },
            "locations": clinics_in_order,
            "clinics": clinics_in_order,
            "fields": fields,
        }

        global _latest_result, _latest_result_ts
        _latest_result = {
            "locations": result.get("locations", []),
            "yolo": result["yolo"],
            "capture_id": result["capture_id"],
        }
        _latest_result_ts = time.time()
        
        log.info("OCR capture_id=%s class=%s clinics=%s", result["capture_id"], final_cls, clinics_in_order)
        return result

    except Exception as e:
        log.error(f"OCR processing error: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# Real-time streaming with OBB
# ──────────────────────────────────────────────────────────────────────────────
_last_boxes = []
_frame_idx  = 0

def _render_stream_frame():
    global _last_boxes, _frame_idx, _last_ocr_time

    if not CAMERA_ENABLED:
        raise RuntimeError("Camera disabled")

    cam_handle = _ensure_camera_started()

    with _capture_lock:
        frame = cam_handle.capture_array("main")
        if frame is None or frame.size == 0:
            raise RuntimeError("Failed to capture frame from Pi camera")
        frame = normalize_frame_color(frame)

    if ROTATE_STREAM_90 and ROTATE_STREAM_180:
        log.warning("Both ROTATE_STREAM_90 and ROTATE_STREAM_180 enabled; applying single 90-degree rotation.")
    if ROTATE_STREAM_90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif ROTATE_STREAM_180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)

    # FIXED: Run OBB detection on original frame - no manual resizing
    if yolo_model is not None and (_frame_idx % STREAM_DET_INTERVAL == 0):
        try:
            # Let YOLO handle resizing internally - remove manual resizing
            obbs = _yolo_detect_obb(frame, STREAM_IMG_SIZE, STREAM_CONF)
            
            # FIXED: No scaling needed - YOLO returns coordinates in original image space
            _last_boxes = obbs
            
        except Exception as e:
            log.error(f"Error in OBB detection: {e}")
            _last_boxes = []

    _frame_idx += 1

    now = time.time()
    best_conf = 0.0
    best_det = None

    # Draw OBB detections using the video annotation style
    if _last_boxes:
        best_det = max(_last_boxes, key=lambda x: x[1])
        best_conf = best_det[1]
        
        # Draw all OBB detections
        for (poly, c, cls) in _last_boxes:
            _draw_obb_poly(frame, poly, f"{cls} {c:.2f}")

    # Draw frame info
    cv2.putText(
        frame,
        f"frm:{_frame_idx} det:{len(_last_boxes)} conf:{best_conf*100:.1f}%",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
    )

    # OCR triggering
    can_run_ocr = (
        best_det
        and best_conf >= OCR_MIN_CONF
        and (now - _last_ocr_time) >= OCR_COOLDOWN_SEC
    )

    if can_run_ocr:
        try:
            result = _run_ocr_on_detection(frame.copy(), best_det, best_det[2])
            if result:
                _last_ocr_time = now
                cv2.putText(frame, "OCR OK", (10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        except Exception as e:
            cv2.putText(frame, f"OCR ERR", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            log.error(f"OCR error: {e}")
    elif best_det and best_conf >= OCR_MIN_CONF:
        cooldown_remaining = OCR_COOLDOWN_SEC - (now - _last_ocr_time)
        if cooldown_remaining > 0:
            cv2.putText(
                frame,
                f"OCR WAIT ({cooldown_remaining:.1f}s)",
                (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 215, 255),
                2,
            )

    # Pace the stream output
    t_now = time.time()
    if not hasattr(_render_stream_frame, "_last_t"):
        _render_stream_frame._last_t = t_now
    dt = t_now - _render_stream_frame._last_t
    if dt < _FRAME_PERIOD:
        time.sleep(_FRAME_PERIOD - dt)
    _render_stream_frame._last_t = time.time()

    # Encode MJPEG chunk
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
    ok, jpeg = cv2.imencode(".jpg", frame, encode_params)
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return (
        b"--FRAME\r\n"
        b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
    )
# ──────────────────────────────────────────────────────────────────────────────
# FastAPI Routes
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/stream.mjpg")
async def stream(request: Request):
    if not CAMERA_ENABLED:
        raise HTTPException(status_code=503, detail="Camera livestream disabled")

    async def generate():
        log.info("Pi camera stream start")
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

@router.post("/ocr")
async def run_ocr():
    result = {
        "capture_id": "demo-capture",
        "locations": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "yolo": {"class": "slip_1", "conf": 0.99, "box": [12, 34, 200, 320]},
        "clinics": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "fields": {
            "clinic_1": {
                "raw": "Ward 2",
                "clean": "Ward 2",
                "match": "Ward 2",
                "match_score": 1.0,
            },
            "clinic_2": {
                "raw": "Orthopaedic Centre",
                "clean": "Orthopaedic Centre",
                "match": "Orthopaedic Centre",
                "match_score": 1.0,
            },
            "clinic_3": {
                "raw": "Clinic J",
                "clean": "Clinic J",
                "match": "Clinic J",
                "match_score": 1.0,
            },
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

@router.get("/latest_result")
def latest_result():
    if _latest_result is None:
        return {"ready": False}
    return {"ready": True, "updated_at": _latest_result_ts, "data": _latest_result}

@router.post("/latest_result/reset")
def reset_latest_result():
    global _latest_result, _latest_result_ts
    _latest_result = None
    _latest_result_ts = time.time()
    return {"ok": True}

@router.get("/health")
def health():
    return {"ok": True}
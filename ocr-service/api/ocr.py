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
STREAM_IOU          = float(os.environ.get("STREAM_IOU", "0.45"))

# Rotation flags
ROTATE_STREAM_90  = os.environ.get("ROTATE_STREAM_90",  "1") == "1"
ROTATE_STREAM_180 = os.environ.get("ROTATE_STREAM_180", "0") == "1"

# OCR gating (NO cooldown; we use an armed delay)
OCR_MIN_CONF          = float(os.environ.get("OCR_MIN_CONF", "0.90"))
OCR_ARM_DELAY_SEC     = float(os.environ.get("OCR_ARM_DELAY_SEC", "1.0"))  # wait this long after first detection
STABILITY_MIN_FRAMES  = int(os.environ.get("STABILITY_MIN_FRAMES", "2"))   # 0 to disable stability gate
STABILITY_IOU_THRESH  = float(os.environ.get("STABILITY_IOU_THRESH", "0.5"))
DET_MISS_RESET_FRAMES = int(os.environ.get("DET_MISS_RESET_FRAMES", "1"))  # reset timer as soon as detections disappear

# Legacy vars kept for compatibility in logs if referenced
OCR_COOLDOWN_SEC  = 0.0
_last_ocr_time    = 0.0

FUZZY_MATCH_THRESHOLD = float(os.environ.get("OCR_FUZZY_MATCH_THRESHOLD", "0.1"))

# Camera settings
CAMERA_ENABLED   = os.environ.get("CAMERA_ENABLED", "0") == "1"
PICAM_VIDEO_SIZE = (1280, 720)
PICAM_FRAME_RATE = 15
PICAM_AF_MODE    = controls.AfModeEnum.Continuous
PICAM_AF_RANGE   = controls.AfRangeEnum.Full
PICAM_AF_SPEED   = controls.AfSpeedEnum.Normal

# Stream settings
TARGET_STREAM_FPS   = int(os.environ.get("TARGET_STREAM_FPS", "8"))
_FRAME_PERIOD       = 1.0 / max(1, TARGET_STREAM_FPS)
STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "85"))
PICAM_COLOR_SPACE   = os.environ.get("PICAM_COLOR_SPACE", "RGB").strip().upper()

TEMPLATE_CROP_PAD    = int(os.environ.get("TEMPLATE_CROP_PAD", "4"))
TESSERACT_WIN_PATH   = os.environ.get("TESSERACT_WIN_PATH", "")

# Blur gating (same as video pipeline)
BLUR_METHOD        = os.environ.get("BLUR_METHOD", "laplacian").strip().lower()  # "laplacian" or "tenengrad"
BLUR_MIN_LAP       = float(os.environ.get("BLUR_MIN_LAP", "45.0"))
BLUR_MIN_TEN       = float(os.environ.get("BLUR_MIN_TEN", "30000.0"))
BLUR_SMOOTH_ALPHA  = float(os.environ.get("BLUR_SMOOTH_ALPHA", "0.3"))
_show_blur_ema     = None  # runtime EMA state

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
# Drawing helpers
# ──────────────────────────────────────────────────────────────────────────────
GREEN = (0, 255, 0)
WHT   = (255, 255, 255)
YEL   = (0, 215, 255)
RED   = (0, 0, 255)

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

# ──────────────────────────────────────────────────────────────────────────────
# IoU + bbox helpers (stability)
# ──────────────────────────────────────────────────────────────────────────────
def _bbox_from_det(det):
    """Return (x1,y1,x2,y2) AABB for OBB polygon or axis-aligned det."""
    if isinstance(det[0], np.ndarray):
        poly = det[0].astype(np.float32)
        x1, y1 = poly[:,0].min(), poly[:,1].min()
        x2, y2 = poly[:,0].max(), poly[:,1].max()
        return (float(x1), float(y1), float(x2), float(y2))
    else:
        x1, y1, x2, y2 = det[0], det[1], det[2], det[3]
        return (float(x1), float(y1), float(x2), float(y2))

def _iou(a, b):
    if a is None or b is None:
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = a_area + b_area - inter
    return inter / denom if denom > 0 else 0.0

# ──────────────────────────────────────────────────────────────────────────────
# YOLO detection
# ──────────────────────────────────────────────────────────────────────────────
def _yolo_detect_obb(img_bgr, imgsz, conf):
    if yolo_model is None:
        return []
    try:
        res = yolo_model.predict(img_bgr, imgsz=imgsz, conf=conf, iou=STREAM_IOU, verbose=False)[0]
        if res is None or not hasattr(res, 'obb') or res.obb is None:
            return []
        out = []
        obb = res.obb

        if hasattr(obb, 'xyxyxyxy') and obb.xyxyxyxy is not None:
            xy8 = obb.xyxyxyxy.cpu().numpy()
            confs = obb.conf.cpu().numpy() if obb.conf is not None else np.ones(len(xy8), dtype=np.float32)
            cls_ids = obb.cls.cpu().numpy().astype(int) if obb.cls is not None else np.zeros(len(xy8), dtype=int)
            for idx, pts8 in enumerate(xy8):
                polygon = pts8.reshape(4, 2)
                confidence = float(confs[idx])
                cls_id = int(cls_ids[idx])
                cls_name = yolo_model.names.get(cls_id, str(cls_id)) if isinstance(yolo_model.names, dict) else (
                    yolo_model.names[cls_id] if 0 <= cls_id < len(yolo_model.names) else str(cls_id)
                )
                out.append((polygon, confidence, cls_name))

        elif hasattr(obb, 'xywhr') and obb.xywhr is not None:
            xywhr = obb.xywhr.cpu().numpy()
            confs = obb.conf.cpu().numpy() if obb.conf is not None else np.ones(len(xywhr), dtype=np.float32)
            cls_ids = obb.cls.cpu().numpy().astype(int) if obb.cls is not None else np.zeros(len(xywhr), dtype=int)
            for idx, (cx, cy, w, h, angle_rad) in enumerate(xywhr):
                angle_deg = np.degrees(angle_rad)
                rect = ((float(cx), float(cy)), (max(float(w),1.0), max(float(h),1.0)), float(angle_deg))
                polygon = cv2.boxPoints(rect)
                confidence = float(confs[idx])
                cls_id = int(cls_ids[idx])
                cls_name = yolo_model.names.get(cls_id, str(cls_id)) if isinstance(yolo_model.names, dict) else (
                    yolo_model.names[cls_id] if 0 <= cls_id < len(yolo_model.names) else str(cls_id)
                )
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
# Blur helpers
# ──────────────────────────────────────────────────────────────────────────────
def blur_laplacian(img_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def blur_tenengrad(img_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float((gx * gx + gy * gy).mean())

def measure_blur(img_bgr: np.ndarray) -> float:
    if BLUR_METHOD == "tenengrad":
        return blur_tenengrad(img_bgr)
    return blur_laplacian(img_bgr)

def format_blur_txt(val: float) -> str:
    return f"{val:.0f}" if BLUR_METHOD == "tenengrad" else f"{val:.1f}"

# ──────────────────────────────────────────────────────────────────────────────
# OCR core
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

    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789&/:-() "
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
        best_text, raw_text = "", ""
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
    """Run OCR with OBB perspective transform; returns result dict or None."""
    cls_name = str(cls_name)
    H, W = frame_bgr.shape[:2]

    if isinstance(det[0], np.ndarray):  # OBB
        polygon, conf, det_cls_name = det
        if det_cls_name:
            cls_name = det_cls_name

        quad_global = polygon.astype(np.float32)
        det_conf_value = float(conf)

        width = int(max(np.linalg.norm(quad_global[0] - quad_global[1]),
                        np.linalg.norm(quad_global[2] - quad_global[3])))
        height = int(max(np.linalg.norm(quad_global[1] - quad_global[2]),
                         np.linalg.norm(quad_global[3] - quad_global[0])))
        width = max(width, 10); height = max(height, 10)

        dst_points = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(quad_global, dst_points)
        rect_img = cv2.warpPerspective(frame_bgr, M, (width, height))

        x_coords = polygon[:, 0]
        y_coords = polygon[:, 1]
        x1c, y1c, x2c, y2c = int(x_coords.min()), int(y_coords.min()), int(x_coords.max()), int(y_coords.max())
    else:
        x1, y1, x2, y2, conf, det_cls_name = det
        if det_cls_name:
            cls_name = det_cls_name
        x1c, y1c, x2c, y2c = int(x1), int(y1), int(x2), int(y2)
        rect_img = frame_bgr[max(0,y1c):min(H,y2c), max(0,x1c):min(W,x2c)].copy()
        det_conf_value = float(conf)

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

        # Attach blur metric
        global _show_blur_ema
        try:
            blur_val_now = measure_blur(frame_bgr)
            result.setdefault("metrics", {})["blur"] = {
                "method": BLUR_METHOD,
                "value": float(blur_val_now)
            }
        except Exception:
            pass

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
# Real-time streaming with ARMED TIMER + BLUR/STABILITY gates
# ──────────────────────────────────────────────────────────────────────────────
_last_boxes = []
_frame_idx  = 0

# NEW: timer + stability state
_ocr_pending_since = None     # when we first saw a detection (arms the timer)
_last_best_bbox    = None     # (x1,y1,x2,y2) of last best det
_stable_frames     = 0        # consecutive frames box stayed similar
_det_miss_frames   = 0        # consecutive processed frames with no detection

def _render_stream_frame():
    global _last_boxes, _frame_idx, _last_ocr_time, _show_blur_ema
    global _ocr_pending_since, _last_best_bbox, _stable_frames, _det_miss_frames

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

    # OBB detection (on interval)
    if yolo_model is not None and (_frame_idx % STREAM_DET_INTERVAL == 0):
        try:
            obbs = _yolo_detect_obb(frame, STREAM_IMG_SIZE, STREAM_CONF)
            _last_boxes = obbs
        except Exception as e:
            log.error(f"Error in OBB detection: {e}")
            _last_boxes = []

    _frame_idx += 1

    now = time.time()
    best_conf = 0.0
    best_det = None

    # Draw OBBs and pick best
    if _last_boxes:
        best_det = max(_last_boxes, key=lambda x: x[1])
        best_conf = best_det[1]
        for (poly, c, cls) in _last_boxes:
            _draw_obb_poly(frame, poly, f"{cls} {c:.2f}")

    # Blur measurement + EMA
    blur_val = measure_blur(frame)
    if _show_blur_ema is None:
        _show_blur_ema = blur_val
    else:
        _show_blur_ema = (1.0 - BLUR_SMOOTH_ALPHA) * _show_blur_ema + BLUR_SMOOTH_ALPHA * blur_val

    # Blur gating
    if BLUR_METHOD == "tenengrad":
        blur_ok = blur_val >= BLUR_MIN_TEN
        blur_thresh_txt = f">={int(BLUR_MIN_TEN)}"
    else:
        blur_ok = blur_val >= BLUR_MIN_LAP
        blur_thresh_txt = f">={BLUR_MIN_LAP:.0f}"

    # ── OCR arming + stability tracking ───────────────────────────────────────
    if best_det is not None:
        curr_bbox = _bbox_from_det(best_det)
        iou_vs_last = _iou(curr_bbox, _last_best_bbox)
        if iou_vs_last >= STABILITY_IOU_THRESH:
            _stable_frames += 1
        else:
            _stable_frames = 1
        _last_best_bbox = curr_bbox

        if _ocr_pending_since is None:
            _ocr_pending_since = now

        _det_miss_frames = 0
    else:
        # Reset the timer immediately when detections disappear (per requirement)
        _det_miss_frames += 1
        if _det_miss_frames >= DET_MISS_RESET_FRAMES:
            _ocr_pending_since = None
            _last_best_bbox = None
            _stable_frames = 0

    # HUD
    hud_text = f"frm:{_frame_idx} det:{len(_last_boxes)} conf:{best_conf*100:.1f}%  blur:{format_blur_txt(_show_blur_ema)} {BLUR_METHOD[0].upper()}"
    cv2.putText(frame, hud_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHT, 2)
    blur_color = (0, 200, 0) if blur_ok else (0, 0, 255)
    cv2.putText(frame, f"BLUR{'' if blur_ok else ' LOW'} (thr {blur_thresh_txt})",
                (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.6, blur_color, 2)

    if _ocr_pending_since is not None:
        time_waited = now - _ocr_pending_since
        time_left = max(0.0, OCR_ARM_DELAY_SEC - time_waited)
        cv2.putText(frame, f"OCR ARM: {time_left:.1f}s",
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, YEL, 2)

    # Conditions for OCR (do NOT affect timer)
    conditions_ok = (
        best_det is not None and
        (best_conf >= OCR_MIN_CONF) and
        blur_ok and
        (_stable_frames >= STABILITY_MIN_FRAMES)
    )
    ready_by_timer = (_ocr_pending_since is not None) and ((now - _ocr_pending_since) >= OCR_ARM_DELAY_SEC)

    # FIRE OCR when delay elapsed AND gates satisfied
    if ready_by_timer and conditions_ok:
        try:
            result = _run_ocr_on_detection(frame.copy(), best_det, best_det[2])
            if result:
                _last_ocr_time = now
                cv2.putText(frame, "OCR OK", (10, 92),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # RESET timer + stability after firing
                _ocr_pending_since = None
                _stable_frames = 0
                _last_best_bbox = None
                _det_miss_frames = 0
        except Exception as e:
            cv2.putText(frame, "OCR ERR", (10, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.7, RED, 2)
            log.error(f"OCR error: {e}")
    else:
        # Show gating reason while waiting
        if _ocr_pending_since is not None:
            reasons = []
            if not ready_by_timer: reasons.append("TIMER")
            if best_det is None: reasons.append("NO DET")
            else:
                if best_conf < OCR_MIN_CONF: reasons.append("CONF")
                if not blur_ok: reasons.append("BLUR")
                if _stable_frames < STABILITY_MIN_FRAMES: reasons.append("STABLE")
            if reasons:
                cv2.putText(frame, "WAIT " + "/".join(reasons),
                            (10, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.6, YEL, 2)

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
    # demo stub (kept)
    result = {
        "capture_id": "demo-capture",
        "locations": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "yolo": {"class": "1", "conf": 0.99, "box": [12, 34, 200, 320]},
        "clinics": ["Ward 2", "Orthopaedic Centre", "Clinic J"],
        "fields": {
            "clinic_1": {"raw": "Ward 2", "clean": "Ward 2", "match": "Ward 2", "match_score": 1.0},
            "clinic_2": {"raw": "Orthopaedic Centre", "clean": "Orthopaedic Centre", "match": "Orthopaedic Centre", "match_score": 1.0},
            "clinic_3": {"raw": "Clinic J", "clean": "Clinic J", "match": "Clinic J", "match_score": 1.0},
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
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
from service import log

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

# Spiral search tuning
OCR_ROI_DIR       = Path(os.environ.get("OCR_ROI_DIR", "OCR_ROI"))
SPIRAL_STEP_NORM  = float(os.environ.get("SPIRAL_STEP_NORM", "0.01"))
UPSCALE_FOR_OCR   = float(os.environ.get("UPSCALE_FOR_OCR", "2.0"))

# Rotation flags
ROTATE_STREAM_90  = os.environ.get("ROTATE_STREAM_90",  "1") == "1"
ROTATE_STREAM_180 = os.environ.get("ROTATE_STREAM_180", "0") == "1"

# OCR gating (NO cooldown; we use an armed delay)
OCR_MIN_CONF          = float(os.environ.get("OCR_MIN_CONF", "0.90"))
OCR_ARM_DELAY_SEC     = float(os.environ.get("OCR_ARM_DELAY_SEC", "4.0"))  # wait this long after first detection
STABILITY_MIN_FRAMES  = int(os.environ.get("STABILITY_MIN_FRAMES", "2"))   # 0 to disable stability gate
STABILITY_IOU_THRESH  = float(os.environ.get("STABILITY_IOU_THRESH", "0.5"))
DET_MISS_RESET_FRAMES = int(os.environ.get("DET_MISS_RESET_FRAMES", "1"))  # reset timer as soon as detections disappear

# Spiral/Y-sweep toggles
OCR_SWEEP_ENABLED = os.environ.get("OCR_SWEEP_ENABLED", "1") == "0"  # turn sweep on/off
OCR_SWEEP_AXIS    = os.environ.get("OCR_SWEEP_AXIS", "y").strip().lower()  # "y" (vertical only) or "xy" (full 2D grid)
EARLY_STOP_FUZZY  = float(os.environ.get("EARLY_STOP_FUZZY", "0.98"))      # stop sweep early if fuzzy ≥ this

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

# Overlay settings
STREAM_DEBUG_OVERLAY = os.environ.get("STREAM_DEBUG_OVERLAY", "1") == "1"

# Aspect-ratio classification settings
USE_ASPECT_RATIO_CLASS = os.environ.get("USE_ASPECT_RATIO_CLASS", "0") == "1"
ASPECT_RATIO_DIR  = Path(os.environ.get("ASPECT_RATIO_DIR", "aspect_ratio"))
ASPECT_RATIO_FILE = ASPECT_RATIO_DIR / os.environ.get("ASPECT_RATIO_FILE", "aspect_ratio.json")

TEMPLATE_CROP_PAD    = int(os.environ.get("TEMPLATE_CROP_PAD", "4"))
TESSERACT_WIN_PATH   = os.environ.get("TESSERACT_WIN_PATH", "")

# Blur gating (same as video pipeline)
BLUR_METHOD        = os.environ.get("BLUR_METHOD", "laplacian").strip().lower()  # "laplacian" or "tenengrad"
BLUR_MIN_LAP       = float(os.environ.get("BLUR_MIN_LAP", "45.0"))
BLUR_MIN_TEN       = float(os.environ.get("BLUR_MIN_TEN", "30000.0"))
BLUR_SMOOTH_ALPHA  = float(os.environ.get("BLUR_SMOOTH_ALPHA", "0.3"))
_show_blur_ema     = None  # runtime EMA state

# Exposure gating (matches the offline pipeline)
USE_EXPO_GATE       = os.environ.get("USE_EXPO_GATE", "1") == "1"
EXPO_P95_MAX        = float(os.environ.get("EXPO_P95_MAX", "240"))   # 95th percentile gray <= this
EXPO_MAX_WHITE_FRAC = float(os.environ.get("EXPO_MAX_WHITE_FRAC", "0.15"))  # frac pixels >=245

# Latest result cache
_latest_result     = None
_latest_result_ts  = 0.0

#log = logging.getLogger(__name__)

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
# Aspect-ratio class mapping
# ──────────────────────────────────────────────────────────────────────────────
_aspect_ratio_bounds: Optional[Dict[str, Tuple[float, float]]] = None

def _load_aspect_ratio_bounds(path: Path) -> Dict[str, Tuple[float, float]]:
    js = json.loads(path.read_text(encoding="utf-8"))
    bounds: Dict[str, Tuple[float, float]] = {}
    for k, v in js.items():
        lo = float(v["lower"])
        hi = float(v["upper"])
        bounds[str(k)] = (lo, hi)
    items = [(k, *bounds[k]) for k in bounds]
    for i in range(len(items)):
        ki, li, ui = items[i]
        for j in range(i+1, len(items)):
            kj, lj, uj = items[j]
            if max(li, lj) < min(ui, uj):
                log.warning("Aspect ratio ranges overlap: %s[%s,%s] vs %s[%s,%s]", ki, li, ui, kj, lj, uj)
    return bounds

def _get_aspect_ratio_bounds() -> Dict[str, Tuple[float, float]]:
    global _aspect_ratio_bounds
    if _aspect_ratio_bounds is None:
        if not ASPECT_RATIO_FILE.exists():
            raise FileNotFoundError(f"Aspect ratio file not found: {ASPECT_RATIO_FILE}")
        _aspect_ratio_bounds = _load_aspect_ratio_bounds(ASPECT_RATIO_FILE)
    return _aspect_ratio_bounds

def classify_by_aspect_ratio(height_px: int, width_px: int) -> str:
    if width_px <= 0:
        raise ValueError("Width must be > 0 for aspect ratio classification")
    ratio = float(height_px) / float(width_px)
    bounds = _get_aspect_ratio_bounds()
    for cls_key, (lo, hi) in bounds.items():
        if ratio >= lo and ratio < hi:
            return str(cls_key)
    for cls_key, (lo, hi) in bounds.items():
        if abs(ratio - hi) < 1e-9:
            return str(cls_key)
    raise ValueError(f"Aspect ratio {ratio:.6f} not covered by any class bounds")

# ──────────────────────────────────────────────────────────────────────────────
# YOLO OBB Model
# ──────────────────────────────────────────────────────────────────────────────
yolo_model = YOLO(YOLO_WEIGHTS, task="obb")

# ──────────────────────────────────────────────────────────────────────────────
# Camera setup
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter()
_camera_init_lock = Lock()

# New: short-lived camera lock used ONLY during capture
_picam_lock = Lock()

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

def _capture_frame_array(stream_name: str = "main") -> np.ndarray:
    """
    Centralized capture that holds the picam lock ONLY during capture_array().
    """
    cam = _ensure_camera_started()
    with _picam_lock:
        frame = cam.capture_array(stream_name)
    if frame is None or frame.size == 0:
        raise RuntimeError("Failed to capture frame from Pi camera")
    return frame

# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers
# ──────────────────────────────────────────────────────────────────────────────
GREEN = (0, 255, 0)
WHT   = (255, 255, 255)
YEL   = (0, 215, 255)
RED   = (0, 0, 255)
CYA   = (255, 255, 0)

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

def _draw_template_boxes_on_frame(frame_bgr: np.ndarray, best_det) -> None:
    """
    Draw template field rectangles (projected back to frame) for the current best detection.
    Controlled by STREAM_DEBUG_OVERLAY (call guarded by caller).
    """
    try:
        rect_img, Minv, (rect_w, rect_h) = _rectified_from_detection(frame_bgr, best_det)

        # Decide class key
        if USE_ASPECT_RATIO_CLASS:
            cls_key = classify_by_aspect_ratio(rect_h, rect_w)
        else:
            det_cls = best_det[2] if isinstance(best_det[0], np.ndarray) else best_det[5]
            cls_key = str(det_cls)
            if cls_key in {"slip1", "slip2", "slip3"}:
                cls_key = cls_key[-1]

        # Load template specs
        tpl_path = select_template_path_from_class(cls_key)
        rect_specs = load_template_rects(tpl_path, rect_w, rect_h)

        # Project each rect's 4 corners using Minv and draw on the live frame
        for spec in rect_specs:
            x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
            pts_rect = np.array(
                [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                dtype=np.float32
            ).reshape(-1, 1, 2)
            pts_global = cv2.perspectiveTransform(pts_rect, Minv).reshape(-1, 2)
            pts_int = pts_global.astype(int)
            cv2.polylines(frame_bgr, [pts_int], isClosed=True, color=CYA, thickness=1)
            # label near top-left of the quad
            tl_idx = np.lexsort((pts_int[:,0], pts_int[:,1]))[0]
            _put_label(frame_bgr, pts_int[tl_idx], spec["name"], color=CYA)
    except Exception as e:
        log.debug(f"Template overlay draw skipped: {e}")

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
# Exposure helpers
# ──────────────────────────────────────────────────────────────────────────────
def _exposure_metrics_gray(gray: np.ndarray) -> Tuple[float, float]:
    p95 = float(np.percentile(gray, 95))
    white_frac = float((gray >= 245).mean())
    return p95, white_frac

def _roi_gray_from_det(frame_bgr: np.ndarray, det) -> Optional[np.ndarray]:
    H, W = frame_bgr.shape[:2]
    if isinstance(det[0], np.ndarray):  # OBB polygon
        poly = det[0]
        x1 = int(max(0, np.floor(poly[:, 0].min()))); y1 = int(max(0, np.floor(poly[:, 1].min())))
        x2 = int(min(W, np.ceil(poly[:, 0].max())));  y2 = int(min(H, np.ceil(poly[:, 1].max())))
    else:  # AABB
        x1, y1, x2, y2 = map(int, det[:4])
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(W, x2); y2 = min(H, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    roi = frame_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

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
                raise ValueError(f"template item #%i missing key '%s'" % (i, key))
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
    """Run OCR (with optional Y-only sweep) for the live stream trigger.
       Returns result dict or None.
    """
    cls_name = str(cls_name)
    H, W = frame_bgr.shape[:2]

    # ---- Rectify detection (OBB preferred) ----
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

        x_coords = polygon[:, 0]; y_coords = polygon[:, 1]
        x1c, y1c, x2c, y2c = int(x_coords.min()), int(y_coords.min()), int(x_coords.max()), int(y_coords.max())

        rect_w, rect_h = width, height

    else:  # axis-aligned
        x1, y1, x2, y2, conf, det_cls_name = det
        if det_cls_name:
            cls_name = det_cls_name
        x1c, y1c, x2c, y2c = int(x1), int(y1), int(x2), int(y2)
        rect_img = frame_bgr[max(0,y1c):min(H,y2c), max(0,x1c):min(W,x2c)].copy()
        det_conf_value = float(conf)
        rect_h, rect_w = rect_img.shape[:2]

    if rect_img.size == 0:
        return None

    # ---- Choose class by aspect ratio if enabled ----
    final_cls = cls_name
    try:
        if USE_ASPECT_RATIO_CLASS:
            final_cls = classify_by_aspect_ratio(rect_h, rect_w)
    except Exception as e:
        log.error(f"Aspect-ratio classification error: {e}")
        return None

    try:
        # ---- Load template rects (pixel coords in rectified space) ----
        tpl_path = select_template_path_from_class(final_cls)
        rect_specs = load_template_rects(tpl_path, rect_w, rect_h)

        # ---- Decide OCR mode for STREAM: Y-only sweep or template-only ----
        if OCR_SWEEP_ENABLED and OCR_SWEEP_AXIS == "y":
            bigroi_path = select_bigroi_path_from_class(final_cls)  # from step 2
            bigrois = _load_big_roi(bigroi_path)                   # normalized big-ROI per field
            ocr_list = _ocr_fields_y_sweep(rect_img, rect_specs, rect_w, rect_h, bigrois)
        else:
            ocr_list = _ocr_fields_template_only(rect_img, rect_specs, rect_w, rect_h, pad=TEMPLATE_CROP_PAD)

        results_by_name = {item["field"]: item for item in ocr_list}

        fields = {}
        clinics_in_order = []
        for spec in rect_specs:
            name = spec["name"]
            entry = results_by_name.get(name)
            if not entry:
                continue
            clean_text = entry.get("text") or ""
            match = entry.get("fuzzy_match")
            score = entry.get("fuzzy_score")

            fields[name] = {
                "raw": clean_text,
                "clean": clean_text,
                "match": match,
                "match_score": score,
            }
            if match:
                clinics_in_order.append(match)
            elif clean_text:
                clinics_in_order.append(clean_text)

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
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

        global _show_blur_ema
        try:
            blur_val_now = measure_blur(frame_bgr)
            result.setdefault("metrics", {})["blur"] = {"method": BLUR_METHOD, "value": float(blur_val_now)}
        except Exception:
            pass

        result.setdefault("sweep", {})["enabled"] = bool(OCR_SWEEP_ENABLED and OCR_SWEEP_AXIS == "y")
        if result["sweep"]["enabled"]:
            result["sweep"]["axis"] = "y"
            result["sweep"]["step_norm"] = SPIRAL_STEP_NORM

        global _latest_result, _latest_result_ts
        _latest_result = {"locations": result.get("locations", []), "yolo": result["yolo"], "capture_id": result["capture_id"]}
        _latest_result_ts = time.time()

        log.info("OCR capture_id=%s class=%s clinics=%s", result["capture_id"], final_cls, clinics_in_order)
        return result

    except Exception as e:
        log.exception(f"OCR processing error: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# Real-time streaming with ARMED TIMER + BLUR/STABILITY/EXPOSURE gates
# ──────────────────────────────────────────────────────────────────────────────
_last_boxes = []
_frame_idx  = 0

# Timer + stability state
_ocr_pending_since = None     # when we first saw a detection (arms the timer)
_last_best_bbox    = None     # (x1,y1,x2,y2) of last best det
_stable_frames     = 0        # consecutive frames box stayed similar
_det_miss_frames   = 0        # consecutive processed frames with no detection

def _render_stream_frame():
    global _last_boxes, _frame_idx, _last_ocr_time, _show_blur_ema
    global _ocr_pending_since, _last_best_bbox, _stable_frames, _det_miss_frames

    if not CAMERA_ENABLED:
        raise RuntimeError("Camera disabled")

    # Short-lived lock ONLY during capture
    frame = _capture_frame_array("main")
    frame = normalize_frame_color(frame)

    if ROTATE_STREAM_90 and ROTATE_STREAM_180:
        log.warning("Both ROTATE_STREAM_90 and ROTATE_STREAM_180 enabled; applying single 90-degree rotation.")
    if ROTATE_STREAM_90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif ROTATE_STREAM_180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)

    # Keep a plain copy for exposure/metrics (no overlays)
    plain_frame = frame.copy()

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

    # Pick best det (drawing guarded by overlay flag)
    if _last_boxes:
        best_det = max(_last_boxes, key=lambda x: x[1])
        best_conf = best_det[1]
        if STREAM_DEBUG_OVERLAY:
            for (poly, c, cls) in _last_boxes:
                _draw_obb_poly(frame, poly, f"{cls} {c:.2f}")
            # NEW: draw template boxes for the current best detection
            _draw_template_boxes_on_frame(frame, best_det)

    # Blur measurement + EMA (used for gating regardless of overlay)
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

    # Exposure gating: compute on the detection ROI from plain frame
    expo_ok = True
    expo_p95 = None
    expo_white = None
    if best_det is not None:
        roi_gray = _roi_gray_from_det(plain_frame, best_det)
        if roi_gray is not None:
            expo_p95, expo_white = _exposure_metrics_gray(roi_gray)
            expo_ok = (expo_p95 <= EXPO_P95_MAX) and (expo_white <= EXPO_MAX_WHITE_FRAC)

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
        _det_miss_frames += 1
        if _det_miss_frames >= DET_MISS_RESET_FRAMES:
            _ocr_pending_since = None
            _last_best_bbox = None
            _stable_frames = 0

    # HUD (draw only if overlay enabled)
    if STREAM_DEBUG_OVERLAY:
        hud_text = f"frm:{_frame_idx} det:{len(_last_boxes)} conf:{best_conf*100:.1f}%  blur:{format_blur_txt(_show_blur_ema)} {BLUR_METHOD[0].upper()}"
        cv2.putText(frame, hud_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHT, 2)
        blur_color = (0, 200, 0) if blur_ok else (0, 0, 255)
        cv2.putText(frame, f"BLUR{'' if blur_ok else ' LOW'} (thr {blur_thresh_txt})",
                    (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.6, blur_color, 2)

        expo_color = (0, 200, 0) if expo_ok else (0, 0, 255)
        cv2.putText(frame, f"EXPO{' OK' if expo_ok else ' HIGH'}",
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, expo_color, 2)

        if _ocr_pending_since is not None:
            time_waited = now - _ocr_pending_since
            time_left = max(0.0, OCR_ARM_DELAY_SEC - time_waited)
            cv2.putText(frame, f"OCR ARM: {time_left:.1f}s",
                        (10, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.6, YEL, 2)

    # Conditions for OCR (do NOT affect timer)
    conditions_ok = (
        best_det is not None and
        (best_conf >= OCR_MIN_CONF) and
        blur_ok and
        (_stable_frames >= STABILITY_MIN_FRAMES) and
        ((not USE_EXPO_GATE) or expo_ok)
    )
    ready_by_timer = (_ocr_pending_since is not None) and ((now - _ocr_pending_since) >= OCR_ARM_DELAY_SEC)

    # FIRE OCR when delay elapsed AND gates satisfied
    if ready_by_timer and conditions_ok:
        try:
            result = _run_ocr_on_detection(frame.copy(), best_det, best_det[2])
            if result:
                if expo_p95 is not None and expo_white is not None:
                    result.setdefault("metrics", {})["exposure"] = {
                        "p95": float(expo_p95),
                        "white_frac": float(expo_white),
                        "p95_max": EXPO_P95_MAX,
                        "white_frac_max": EXPO_MAX_WHITE_FRAC
                    }

                _last_ocr_time = now
                if STREAM_DEBUG_OVERLAY:
                    cv2.putText(frame, "OCR OK", (10, 114),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                _ocr_pending_since = None
                _stable_frames = 0
                _last_best_bbox = None
                _det_miss_frames = 0
        except Exception as e:
            if STREAM_DEBUG_OVERLAY:
                cv2.putText(frame, "OCR ERR", (10, 114), cv2.FONT_HERSHEY_SIMPLEX, 0.7, RED, 2)
            log.error(f"OCR error: {e}")
    else:
        if STREAM_DEBUG_OVERLAY and _ocr_pending_since is not None:
            reasons = []
            if not ready_by_timer: reasons.append("TIMER")
            if best_det is None: reasons.append("NO DET")
            else:
                if best_conf < OCR_MIN_CONF: reasons.append("CONF")
                if not blur_ok: reasons.append("BLUR")
                if _stable_frames < STABILITY_MIN_FRAMES: reasons.append("STABLE")
                if USE_EXPO_GATE and not expo_ok: reasons.append("EXPO")
            if reasons:
                cv2.putText(frame, "WAIT " + "/".join(reasons),
                            (10, 114), cv2.FONT_HERSHEY_SIMPLEX, 0.6, YEL, 2)

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

# ── Minimal spiral OCR helpers (no debug)
import math

def _order_quad_tl_tr_br_bl(pts4x2: np.ndarray) -> np.ndarray:
    pts = np.array(pts4x2, dtype=np.float32).reshape(4,2)
    s = pts.sum(axis=1); d = np.diff(pts, axis=1).ravel()
    tl = np.argmin(s); br = np.argmax(s); tr = np.argmin(d); bl = np.argmax(d)
    return np.array([pts[tl], pts[tr], pts[br], pts[bl]], dtype=np.float32)

def _rectified_from_detection(img_bgr: np.ndarray, det):
    """Return (rect_img, Minv, (rect_w, rect_h))."""
    H, W = img_bgr.shape[:2]
    if isinstance(det[0], np.ndarray):  # OBB
        poly, _, _ = det
        quad = _order_quad_tl_tr_br_bl(poly.astype(np.float32))
        w = int(max(np.linalg.norm(quad[1]-quad[0]), np.linalg.norm(quad[2]-quad[3])))
        h = int(max(np.linalg.norm(quad[3]-quad[0]), np.linalg.norm(quad[2]-quad[1])))
        w = max(w, 10); h = max(h, 10)
        dst = np.array([[0,0],[w,0],[w,h],[0,h]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(quad, dst)
        Minv = np.linalg.inv(M)
        rect_img = cv2.warpPerspective(img_bgr, M, (w, h))
        return rect_img, Minv, (w, h)
    else:                                  # AABB
        x1,y1,x2,y2, *_ = det
        x1,y1,x2,y2 = map(int, [x1,y1,x2,y2])
        x1,y1 = max(0,x1), max(0,y1); x2,y2 = min(W,x2), min(H,y2)
        rect_img = img_bgr[y1:y2, x1:x2].copy()
        Minv = np.array([[1,0,x1],[0,1,y1],[0,0,1]], dtype=np.float32)
        return rect_img, Minv, (x2-x1, y2-y1)

def _load_template_boxes(path: Path):
    js = json.loads(path.read_text(encoding="utf-8"))
    return {it["name"]: {"x":float(it["x"]), "y":float(it["y"]), "w":float(it["w"]), "h":float(it["h"])} for it in js}

def _to_float(field_name: str, value, file_path: Path, entry_name: str) -> float:
    try:
        return float(value)
    except Exception:
        raise ValueError(
            f"ROI parse error in {file_path}: entry '{entry_name}' has non-numeric "
            f"'{field_name}'={value!r}"
        )

def _load_big_roi(path: Path) -> Dict[str, Dict[str, float]]:
    # Read JSON
    try:
        js = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to read ROI JSON: {path}: {e}") from e

    out: Dict[str, Dict[str, float]] = {}

    def clamp01(v: float) -> float:
        return max(0.0, min(1.0, v))

    for i, it in enumerate(js):
        if "name" not in it:
            raise ValueError(f"{path}: ROI item #{i} missing 'name'")
        nm = str(it["name"])

        # Accept either corner box or center/size
        if all(k in it for k in ("x1", "y1", "x2", "y2")):
            x1 = _to_float("x1", it["x1"], path, nm)
            y1 = _to_float("y1", it["y1"], path, nm)
            x2 = _to_float("x2", it["x2"], path, nm)
            y2 = _to_float("y2", it["y2"], path, nm)
        elif all(k in it for k in ("x", "y", "w", "h")):
            cx = _to_float("x", it["x"], path, nm)
            cy = _to_float("y", it["y"], path, nm)
            w  = _to_float("w", it["w"], path, nm)
            h  = _to_float("h", it["h"], path, nm)
            x1, y1, x2, y2 = cx - w/2.0, cy - h/2.0, cx + w/2.0, cy + h/2.0
        else:
            raise ValueError(
                f"{path}: ROI '{nm}' must have either (x1,y1,x2,y2) or (x,y,w,h)"
            )

        # Clamp and validate
        x1 = clamp01(float(x1)); y1 = clamp01(float(y1))
        x2 = clamp01(float(x2)); y2 = clamp01(float(y2))
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"{path}: ROI '{nm}' has invalid box after clamping: {(x1,y1,x2,y2)}")

        out[nm] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

    return out

def _start_center_no_shrink(tpl, roi, eps=1e-6):
    cx,cy,w,h = tpl["x"], tpl["y"], tpl["w"], tpl["h"]
    rx1,ry1,rx2,ry2 = roi["x1"], roi["y1"], roi["x2"], roi["y2"]
    if w > (rx2-rx1)+eps or h > (ry2-ry1)+eps:
        raise ValueError("Template larger than ROI.")
    x_min = rx1 + w/2; x_max = rx2 - w/2
    y_min = ry1 + h/2; y_max = ry2 - h/2
    cx = min(max(cx, x_min), x_max); cy = min(max(cy, y_min), y_max)
    return {"x":cx,"y":cy,"w":w,"h":h}, (x_min,x_max,y_min,y_max)

def _grid_in_spiral_order(cx, cy, x_min, x_max, y_min, y_max, step):
    def rdown(v): return np.floor(v/step)*step
    def rup(v):   return np.ceil(v/step)*step
    xs = np.arange(rup(x_min), rdown(x_max)+step/2, step)
    ys = np.arange(rup(y_min), rdown(y_max)+step/2, step)
    grid = np.array([(x,y) for y in ys for x in xs], dtype=np.float32)
    if grid.size == 0: return []
    idx = np.argsort((grid[:,0]-cx)**2 + (grid[:,1]-cy)**2)
    return [tuple(grid[i]) for i in idx]

def _ocr_text_and_conf(img_bgr, upscale=2.0):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale > 1.0:
        gray = cv2.resize(gray, (int(img_bgr.shape[1]*upscale), int(img_bgr.shape[0]*upscale)), interpolation=cv2.INTER_CUBIC)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5)
    d = pytesseract.image_to_data(bw, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT)
    confs = [float(c) for c in d.get("conf", []) if c not in ("-1", -1)]
    avg = float(np.mean(confs)) if confs else 0.0
    txt = " ".join([w for w in d.get("text", []) if w and w.strip()])
    return sanitize_ocr_text(txt), avg

def select_bigroi_path_from_class(cls_name: str) -> Path:
    variant = CLASS_TO_VARIANT.get(str(cls_name))
    if not variant:
        raise FileNotFoundError(f"No Big-ROI mapping for class '{cls_name}'")
    p = OCR_ROI_DIR / f"registration_{variant}.json"
    if not p.exists():
        raise FileNotFoundError(f"Big-ROI not found: {p}")
    return p

# ---------- Y-only sweep building blocks ----------
def _start_center_no_shrink_y(tpl_norm: dict, roi_norm: dict, eps: float = 1e-6):
    cx, cy, w, h = float(tpl_norm["x"]), float(tpl_norm["y"]), float(tpl_norm["w"]), float(tpl_norm["h"])
    rx1, ry1, rx2, ry2 = float(roi_norm["x1"]), float(roi_norm["y1"]), float(roi_norm["x2"]), float(roi_norm["y2"])
    rw, rh = (rx2 - rx1), (ry2 - ry1)
    if w > rw + eps or h > rh + eps:
        raise ValueError(f"Template (w={w:.4f}, h={h:.4f}) larger than ROI (w={rw:.4f}, h={rh:.4f}).")
    x_min = rx1 + w/2.0; x_max = rx2 - w/2.0
    y_min = ry1 + h/2.0; y_max = ry2 - h/2.0
    cx = min(max(cx, x_min), x_max)
    cy = min(max(cy, y_min), y_max)
    return {"x": cx, "y": cy, "w": w, "h": h}, (x_min, x_max, y_min, y_max)

def _y_only_sweep_order(cy0: float, y_min: float, y_max: float, step_norm: float):
    import numpy as _np
    def rdown(v):  return np.floor(v/step_norm)*step_norm
    def rup(v):    return np.ceil(v/step_norm)*step_norm
    ys = _np.arange(rup(y_min), rdown(y_max)+step_norm/2.0, step_norm, dtype=_np.float32)
    if ys.size == 0:
        return []
    order = _np.argsort(_np.abs(ys - cy0))
    return ys[order].tolist()

def _ocr_fields_template_only(rect_img: np.ndarray, rect_specs: list, rect_w: int, rect_h: int, pad: int = 4):
    out = []
    for spec in rect_specs:
        name, x, y, w, h = spec["name"], spec["x"], spec["y"], spec["w"], spec["h"]
        xx1 = max(0, x - pad); yy1 = max(0, y - pad)
        xx2 = min(rect_w, x + w + pad); yy2 = min(rect_h, y + h + pad)
        if xx2 <= xx1 or yy2 <= yy1: 
            continue
        crop = rect_img[yy1:yy2, xx1:xx2]
        text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)

        log.info(
            "OCR(template) field=%s box=[%d,%d,%d,%d] avg_conf=%.2f text=%r",
            name, xx1, yy1, xx2 - xx1, yy2 - yy1, float(conf), text
        )

        match, score = fuzzy_match_location(text)
        out.append({
            "field": name, "raw": text, "text": text, "ocr_conf": round(float(conf),2),
            "fuzzy_match": match, "fuzzy_score": round(float(score or 0.0),4), "ysweep": False
        })
    return out

def _ocr_fields_y_sweep(rect_img: np.ndarray, rect_specs: list, rect_w: int, rect_h: int, bigrois_norm: dict):
    out = []
    for spec in rect_specs:
        name, x, y, w, h = spec["name"], spec["x"], spec["y"], spec["w"], spec["h"]
        roi = bigrois_norm.get(name)
        tpl_norm = {
            "x": (x + w/2.0) / rect_w,
            "y": (y + h/2.0) / rect_h,
            "w": w / rect_w,
            "h": h / rect_h,
        }

        if roi is None:
            xx1 = max(0, x); yy1 = max(0, y)
            xx2 = min(rect_w, x + w); yy2 = min(rect_h, y + h)
            if xx2 <= xx1 or yy2 <= yy1:
                continue
            crop = rect_img[yy1:yy2, xx1:xx2]
            text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)
            match, score = fuzzy_match_location(text)
            out.append({
                "field": name, "raw": text, "text": text, "ocr_conf": round(float(conf),2),
                "fuzzy_match": match, "fuzzy_score": round(float(score or 0.0),4), "ysweep": False
            })
            continue

        try:
            tpl_adj, (x_min, x_max, y_min, y_max) = _start_center_no_shrink_y(tpl_norm, roi)
        except Exception:
            xx1 = max(0, x); yy1 = max(0, y)
            xx2 = min(rect_w, x + w); yy2 = min(rect_h, y + h)
            if xx2 <= xx1 or yy2 <= yy1:
                continue
            crop = rect_img[yy1:yy2, xx1:xx2]
            text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)
            match, score = fuzzy_match_location(text)
            out.append({
                "field": name, "raw": text, "text": text, "ocr_conf": round(float(conf),2),
                "fuzzy_match": match, "fuzzy_score": round(float(score or 0.0),4), "ysweep": False
            })
            continue

        cx_fixed = tpl_adj["x"]
        ys = _y_only_sweep_order(tpl_adj["y"], y_min, y_max, SPIRAL_STEP_NORM)
        w_px = int(round(tpl_adj["w"] * rect_w))
        h_px = int(round(tpl_adj["h"] * rect_h))
        x_px = int(round(cx_fixed * rect_w - w_px/2.0))
        x_px = max(0, min(x_px, rect_w - 1))

        best = None
        for cy in ys:
            y_px = int(round(cy * rect_h - h_px/2.0))
            y_px = max(0, min(y_px, rect_h - 1))
            x2 = min(rect_w, x_px + w_px)
            y2 = min(rect_h, y_px + h_px)
            if x2 <= x_px or y2 <= y_px:
                continue

            crop = rect_img[y_px:y2, x_px:x2]
            text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)
            match, score = fuzzy_match_location(text)
            score = float(score or 0.0); conf = float(conf or 0.0)
            key = (score, conf)
            if (best is None) or (key > (best[0], best[1])):
                best = (score, conf, {
                    "field": name, "raw": text, "text": text, "ocr_conf": round(conf,2),
                    "fuzzy_match": match, "fuzzy_score": round(score,4), "ysweep": True,
                    "chosen_center_norm": {"x": round(cx_fixed,4), "y": round(float(cy),4)}
                })
                if score >= EARLY_STOP_FUZZY:
                    break

        if best is not None:
            out.append(best[2])
        else:
            xx1 = max(0, x); yy1 = max(0, y)
            xx2 = min(rect_w, x + w); yy2 = min(rect_h, y + h)
            if xx2 <= xx1 or yy2 <= yy1:
                continue
            crop = rect_img[yy1:yy2, xx1:xx2]
            text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)
            match, score = fuzzy_match_location(text)
            out.append({
                "field": name, "raw": text, "text": text, "ocr_conf": round(float(conf or 0.0),2),
                "fuzzy_match": match, "fuzzy_score": round(float(score or 0.0),4), "ysweep": False
            })
    return out

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
async def run_ocr(image_path: Optional[str] = None):
    # 1) get image (file or camera)
    if image_path:
        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail=f"Cannot read image_path: {image_path}")
    else:
        if not CAMERA_ENABLED:
            raise HTTPException(status_code=503, detail="Camera disabled; provide image_path")
        frame = _capture_frame_array("main")
        img_bgr = normalize_frame_color(frame)
        if ROTATE_STREAM_90 and ROTATE_STREAM_180:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif ROTATE_STREAM_90:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif ROTATE_STREAM_180:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)

    # 2) detect slips with existing model
    res = yolo_model.predict(img_bgr, imgsz=STREAM_IMG_SIZE, conf=STREAM_CONF, iou=STREAM_IOU, verbose=False)[0]
    dets = []
    if hasattr(res, "obb") and res.obb is not None and getattr(res.obb, "xyxyxyxy", None) is not None:
        xy8 = res.obb.xyxyxyxy.cpu().numpy()
        confs = res.obb.conf.cpu().numpy()
        clsi  = res.obb.cls.cpu().numpy().astype(int)
        for i in range(len(xy8)):
            poly = xy8[i].reshape(4,2).astype(np.float32)
            c = float(confs[i]); ci = int(clsi[i])
            cls_name = yolo_model.names.get(ci, str(ci)) if isinstance(yolo_model.names, dict) else (
                yolo_model.names[ci] if 0 <= ci < len(yolo_model.names) else str(ci)
            )
            dets.append((poly, c, cls_name))
    if not dets and hasattr(res, "boxes") and res.boxes is not None and len(res.boxes):
        xyxy = res.boxes.xyxy.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        clsi  = res.boxes.cls.cpu().numpy().astype(int)
        for i in range(len(xyxy)):
            x1,y1,x2,y2 = xyxy[i].tolist()
            c = float(confs[i]); ci = int(clsi[i])
            cls_name = yolo_model.names.get(ci, str(ci)) if isinstance(yolo_model.names, dict) else (
                yolo_model.names[ci] if 0 <= ci < len(yolo_model.names) else str(ci)
            )
            dets.append((x1,y1,x2,y2, c, cls_name))
    if not dets:
        raise HTTPException(status_code=422, detail="No slips detected")

    best_det = max(dets, key=lambda d: d[1] if isinstance(d[0], np.ndarray) else d[4])
    det_cls  = best_det[2] if isinstance(best_det[0], np.ndarray) else best_det[5]

    # 3) rectify best detection
    rect_img, Minv, (rect_w, rect_h) = _rectified_from_detection(img_bgr, best_det)

    # 4) choose class: by aspect ratio if enabled, else use detector class
    if USE_ASPECT_RATIO_CLASS:
        try:
            cls_key = classify_by_aspect_ratio(rect_h, rect_w)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Aspect ratio classification failed: {e}")
    else:
        cls_key = str(det_cls)
        if cls_key in {"slip1","slip2","slip3"}:
            cls_key = cls_key[-1]

    # 5) load template & big ROI by class
    variant = CLASS_TO_VARIANT.get(cls_key)
    if not variant:
        raise HTTPException(status_code=422, detail=f"No template mapping for class '{cls_key}'")
    tpl_path = TEMPLATE_DIR / f"registration_{variant}.json"
    roi_path = OCR_ROI_DIR   / f"registration_{variant}.json"
    if not tpl_path.exists(): raise HTTPException(status_code=500, detail=f"Template not found: {tpl_path}")
    if not roi_path.exists(): raise HTTPException(status_code=500, detail=f"Big ROI not found: {roi_path}")

    templates = _load_template_boxes(tpl_path)
    bigrois   = _load_big_roi(roi_path)
    names = [n for n in templates.keys() if n in bigrois]
    if not names:
        raise HTTPException(status_code=500, detail="No matching names between template and ROI JSON")

    # 6) spiral scan per field; pick best (fuzzy then OCR conf)
    best_by_name = {}
    for name in names:
        tpl_raw = templates[name]; roi = bigrois[name]
        tpl, (x_min, x_max, y_min, y_max) = _start_center_no_shrink(tpl_raw, roi)
        centers = _grid_in_spiral_order(tpl["x"], tpl["y"], x_min, x_max, y_min, y_max, SPIRAL_STEP_NORM)
        w_px = int(round(tpl["w"] * rect_w)); h_px = int(round(tpl["h"] * rect_h))

        for (cx, cy) in centers:
            x = int(round(cx * rect_w - w_px/2)); y = int(round(cy * rect_h - h_px/2))
            x = max(0, min(x, rect_w - 1)); y = max(0, min(y, rect_h - 1))
            x2 = min(rect_w, x + w_px); y2 = min(rect_h, y + h_px)
            if x2 <= x or y2 <= y: continue
            crop = rect_img[y:y2, x:x2]
            text, conf = _ocr_text_and_conf(crop, upscale=UPSCALE_FOR_OCR)
            match, score = fuzzy_match_location(text)

            row = {"name": name, "x": x, "y": y, "w": x2-x, "h": y2-y,
                   "ocr_text": text, "ocr_conf": float(round(conf,2)),
                   "match": match or "", "fuzzy": float(round(score,4))}
            key = (row["fuzzy"], row["ocr_conf"])
            cur = best_by_name.get(name)
            if (cur is None) or (key > (cur["fuzzy"], cur["ocr_conf"])):
                best_by_name[name] = row

    if not best_by_name:
        raise HTTPException(status_code=422, detail="OCR produced no text")

    # 7) assemble response + update latest_result cache
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ordered = [best_by_name[k] for k in sorted(best_by_name.keys())]
    locations = [b["match"] or b["ocr_text"] for b in ordered]

    result = {
        "capture_id": ts,
        "yolo": {"class": str(cls_key)},
        "best_by_name": best_by_name,
        "locations": locations,
    }

    global _latest_result, _latest_result_ts
    _latest_result = {"capture_id": ts, "yolo": result["yolo"], "locations": locations}
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

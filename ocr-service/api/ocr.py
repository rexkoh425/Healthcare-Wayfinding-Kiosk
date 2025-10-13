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
ROTATE_STREAM_180 = os.environ.get("ROTATE_STREAM_180", "0") == "1"
ROTATE_STREAM_90  = os.environ.get("ROTATE_STREAM_90",  "1") == "1"  # default True

# OCR gating
OCR_MIN_CONF      = 0.80     # 90%
OCR_COOLDOWN_SEC  = 5
_last_ocr_time    = 0.0

FUZZY_MATCH_THRESHOLD = float(os.environ.get("OCR_FUZZY_MATCH_THRESHOLD", "0.1"))

STABILITY_WINDOW_SEC       = float(os.environ.get("OCR_STABILITY_WINDOW_SEC", "1.2"))
STABILITY_MIN_FRAMES       = int(os.environ.get("OCR_STABILITY_MIN_FRAMES", "3"))
STABILITY_CENTER_JITTER    = float(os.environ.get("OCR_STABILITY_CENTER_JITTER", "0.05"))
STABILITY_AREA_JITTER      = float(os.environ.get("OCR_STABILITY_AREA_JITTER", "0.25"))
STABILITY_CONF_THRESHOLD   = float(os.environ.get("OCR_STABILITY_CONF_THRESHOLD", str(OCR_MIN_CONF)))
STABILITY_CONF_SPREAD      = float(os.environ.get("OCR_STABILITY_CONF_SPREAD", "0.05"))

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
STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "90"))

INTENSITY_MASK_CFG = {
    "enabled": False,
    "thresh": 215,
    "invert": False,
    "min_ratio": 0.15,
}

SLIP_EXTRACT_CFG = {
    "thr": 190,
    "use_adaptive": False,
    "adaptive_block": 37,
    "adaptive_C": -10,
    "morph_kernel": 10,
    "fill_kernel": 7,
    "open_kernel": 15,
    "min_keep_area": 4000,
    "use_white_filter": True,
    "v_min": 130,
    "s_max": 100,
    "post_white_margin": 10,
    "target_white_ratio": 0.85,
    "crop_margin": 0.03,
    "quad_expand_frac": 0.02,
    "prefer_pad_on_white_fail": True,
    "inner_band_frac": 0.0,
}

HEIGHT_CLASSIFIER = [
    {"name": "1", "min_h": 565, "max_h": 615},
    {"name": "2", "min_h": 615, "max_h": 700},
    {"name": "3", "min_h": 700, "max_h": 820},
]

CANONICAL_SIZES = {}

OVERLAY_MODE = os.environ.get("OCR_OVERLAY_MODE", "rectified").lower()
if OVERLAY_MODE not in {"rectified", "original"}:
    OVERLAY_MODE = "rectified"

TEMPLATE_CROP_PAD = int(os.environ.get("TEMPLATE_CROP_PAD", "4"))

TESSERACT_WIN_PATH = os.environ.get("TESSERACT_WIN_PATH", "")

DEBUG_DUMP_DIR_ENV = os.environ.get("OCR_DEBUG_DUMP_DIR")
if DEBUG_DUMP_DIR_ENV:
    DEBUG_DUMP_DIR = Path(DEBUG_DUMP_DIR_ENV)
    DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
else:
    DEBUG_DUMP_DIR = None

def configure_tesseract(win_path: str, logger: logging.Logger):
    if pytesseract is None:
        logger.warning("pytesseract not available; OCR will be skipped.")
        return
    if os.name == "nt" and win_path:
        p = Path(win_path)
        if p.exists():
            pytesseract.pytesseract.tesseract_cmd = str(p)
            logger.info("Using Windows Tesseract at: %s", win_path)
        else:
            logger.warning("Tesseract path not found: %s", win_path)

log = logging.getLogger(__name__)
configure_tesseract(TESSERACT_WIN_PATH, log)

# ──────────────────────────────────────────────────────────────────────────────
# Location matching helpers
# ──────────────────────────────────────────────────────────────────────────────
LOCATION_CANDIDATES = (
    [f"Clinic {chr(ord('A') + i)}" for i in range(26)]
    + [f"Ward {i}" for i in range(1, 16)]
    + [
        "Cocoon Clinic",
        "Diagnostic Imaging 2",
        "X-ray",
        "Eye Center",
    ]
)

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

_detection_history = deque(maxlen=64)

def _update_detection_stability(det, frame_shape, timestamp: float):
    """
    Track recent detections to ensure the target stays still and confidence remains high
    before triggering OCR.
    Returns (is_stable, sample_count, metrics)
    """
    if det is None or frame_shape is None or len(frame_shape) < 2:
        _detection_history.clear()
        return False, 0, {"samples": 0, "center_jitter": None, "area_spread": None, "min_conf": None}

    h, w = frame_shape[:2]
    if h <= 0 or w <= 0:
        return False, 0, {"samples": 0, "center_jitter": None, "area_spread": None, "min_conf": None}

    diag = float((w ** 2 + h ** 2) ** 0.5) or 1.0
    x1, y1, x2, y2, conf, cls_name = det
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    width = max(x2 - x1, 1.0)
    height = max(y2 - y1, 1.0)
    area = width * height

    entry = {
        "ts": timestamp,
        "cls": cls_name,
        "conf": float(conf),
        "cx": cx,
        "cy": cy,
        "area": area,
    }
    _detection_history.append(entry)

    while _detection_history and (timestamp - _detection_history[0]["ts"]) > STABILITY_WINDOW_SEC:
        _detection_history.popleft()

    relevant = [
        d for d in _detection_history
        if d["cls"] == cls_name and (timestamp - d["ts"]) <= STABILITY_WINDOW_SEC
    ]

    metrics = {
        "samples": len(relevant),
        "center_jitter": None,
        "area_spread": None,
        "min_conf": None,
        "conf_spread": None,
    }

    if not relevant:
        return False, 0, metrics

    min_conf = min(d["conf"] for d in relevant)
    metrics["min_conf"] = min_conf

    max_conf = max(d["conf"] for d in relevant)
    conf_spread = max_conf - min_conf
    metrics["conf_spread"] = conf_spread

    spread_limit = STABILITY_CONF_SPREAD if STABILITY_CONF_SPREAD > 0 else None

    if (
        len(relevant) < STABILITY_MIN_FRAMES
        or min_conf < STABILITY_CONF_THRESHOLD
        or (spread_limit is not None and conf_spread > spread_limit)
    ):
        return False, len(relevant), metrics

    avg_cx = sum(d["cx"] for d in relevant) / len(relevant)
    avg_cy = sum(d["cy"] for d in relevant) / len(relevant)
    avg_area = sum(d["area"] for d in relevant) / len(relevant)

    if avg_area <= 0:
        avg_area = 1.0

    center_jitter = max(
        (((d["cx"] - avg_cx) ** 2 + (d["cy"] - avg_cy) ** 2) ** 0.5) / diag
        for d in relevant
    )
    area_spread = max(
        abs(d["area"] - avg_area) / avg_area
        for d in relevant
    )

    metrics["center_jitter"] = center_jitter
    metrics["area_spread"] = area_spread

    stable = (
        center_jitter <= STABILITY_CENTER_JITTER and
        area_spread <= STABILITY_AREA_JITTER
    )

    if not stable:
        return False, len(relevant), metrics

    return True, len(relevant), metrics

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
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def clip_box(box, w, h):
    x1, y1, x2, y2 = box
    x1 = _clamp(int(x1), 0, max(0, w - 1))
    y1 = _clamp(int(y1), 0, max(0, h - 1))
    x2 = _clamp(int(x2), 0, max(0, w - 1))
    y2 = _clamp(int(y2), 0, max(0, h - 1))
    if x2 <= x1:
        x2 = min(w - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(h - 1, y1 + 1)
    return [x1, y1, x2, y2]


def enlarge_box_by_scale(box, W, H, scale_w=1.25, scale_h=1.35):
    """
    Expand a box by given width/height scales (e.g., 1.25 = +25%).
    box: (x1, y1, x2, y2), image size: W,H.
    Returns integer, clamped (x1, y1, x2, y2).
    """
    x1, y1, x2, y2 = map(float, box)
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    bw = (x2 - x1)
    bh = (y2 - y1)

    new_w = bw * scale_w
    new_h = bh * scale_h

    nx1 = int(round(cx - new_w * 0.5))
    ny1 = int(round(cy - new_h * 0.5))
    nx2 = int(round(cx + new_w * 0.5))
    ny2 = int(round(cy + new_h * 0.5))

    nx1 = _clamp(nx1, 0, W - 1)
    ny1 = _clamp(ny1, 0, H - 1)
    nx2 = _clamp(nx2, 0, W - 1)
    ny2 = _clamp(ny2, 0, H - 1)

    if nx2 <= nx1:
        nx2 = min(W - 1, nx1 + 1)
    if ny2 <= ny1:
        ny2 = min(H - 1, ny1 + 1)
    return nx1, ny1, nx2, ny2


def _largest_component_mask(mask: np.ndarray, min_keep_area: int) -> np.ndarray:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return np.zeros_like(mask)
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    if stats[largest_label, cv2.CC_STAT_AREA] < min_keep_area:
        return np.zeros_like(mask)
    out = np.zeros_like(mask)
    out[labels == largest_label] = 255
    return out


def classify_height(height_px: int, ranges):
    if not ranges:
        return None
    for spec in ranges:
        try:
            name = str(spec.get("name"))
            min_h = spec.get("min_h")
            max_h = spec.get("max_h")
        except AttributeError:
            continue
        if min_h is None or max_h is None:
            continue
        if min_h <= height_px <= max_h:
            return name
    return None


def _order_box_points(pts):
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]; br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]; bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")


def find_minrect_and_crop(
    upright_bgr: np.ndarray,
    debug_prefix: Path | None = None,
    intensity_cfg=None,
    extract_cfg=None,
):
    dbg = []

    debug_dir: Optional[Path] = None

    def _noop_debug_write(name: str, img: np.ndarray | None):
        return

    _debug_write = _noop_debug_write

    def _write_debug_summary():
        if debug_dir is None:
            return
        try:
            summary = [[str(k), repr(v)] for (k, v) in dbg]
            (debug_dir / "debug.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception:
            pass

    if debug_prefix is not None:
        try:
            debug_dir = Path(debug_prefix)
            debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            debug_dir = None
        else:
            def _debug_write(name: str, img: np.ndarray | None):
                if img is None:
                    return
                try:
                    arr = np.asarray(img)
                    if arr.size == 0:
                        return
                    out_path = debug_dir / f"{name}.png"
                    if arr.ndim == 2:
                        cv2.imwrite(str(out_path), arr)
                    else:
                        cv2.imwrite(str(out_path), arr)
                except Exception:
                    pass

    if upright_bgr is None or upright_bgr.size == 0:
        dbg.append(("empty_input", True))
        _debug_write("input_empty", upright_bgr)
        _write_debug_summary()
        return None, dbg, None

    _debug_write("input", upright_bgr)

    cfg = extract_cfg or {}
    thr = int(cfg.get("thr", 200))
    use_adaptive = bool(cfg.get("use_adaptive", False))
    adaptive_block = int(cfg.get("adaptive_block", 25)) | 1
    adaptive_C = int(cfg.get("adaptive_C", -10))
    morph_kernel = int(max(1, cfg.get("morph_kernel", 5)))
    fill_kernel = int(max(1, cfg.get("fill_kernel", 7)))
    open_kernel = int(max(1, cfg.get("open_kernel", 15)))
    min_keep_area = int(max(1, cfg.get("min_keep_area", 8000)))
    use_white_filter = bool(cfg.get("use_white_filter", True))
    v_min = int(cfg.get("v_min", 160))
    s_max = int(cfg.get("s_max", 70))
    post_white_margin  = int(cfg.get("post_white_margin", 15))
    target_white_ratio = float(cfg.get("target_white_ratio", 0.6))
    crop_margin        = float(cfg.get("crop_margin", 0.0))
    quad_expand_frac   = float(cfg.get("quad_expand_frac", 0.0))
    prefer_pad         = bool(cfg.get("prefer_pad_on_white_fail", False))
    inner_band_frac    = float(cfg.get("inner_band_frac", 0.0))

    h, w = upright_bgr.shape[:2]
    gray = cv2.cvtColor(upright_bgr, cv2.COLOR_BGR2GRAY)

    white_pref = None
    if use_white_filter:
        hsv = cv2.cvtColor(upright_bgr, cv2.COLOR_BGR2HSV)
        lower = np.array([0, 0, v_min], dtype=np.uint8)
        upper = np.array([179, s_max, 255], dtype=np.uint8)
        white_pref = cv2.inRange(hsv, lower, upper)

    if use_adaptive:
        mask_raw = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
            max(3, adaptive_block),
            adaptive_C
        )
    else:
        _, mask_raw = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)

    if white_pref is not None:
        mask_raw = cv2.bitwise_and(mask_raw, white_pref)

    if intensity_cfg and intensity_cfg.get("enabled"):
        thresh = int(intensity_cfg.get("thresh", 160))
        invert = bool(intensity_cfg.get("invert"))
        flat = np.where(gray <= thresh, 255, 0).astype(np.uint8) if invert else np.where(gray > thresh, 255, 0).astype(np.uint8)
        mask_raw = cv2.bitwise_and(mask_raw, flat)
        min_ratio = float(intensity_cfg.get("min_ratio", 0.1))
        if cv2.countNonZero(mask_raw) < max(100, int(min_ratio * h * w)):
            dbg.append(("intensity_skip", cv2.countNonZero(mask_raw)))

    _debug_write("mask_raw", mask_raw)
    if white_pref is not None:
        _debug_write("mask_white_pref", white_pref)

    k = np.ones((morph_kernel, morph_kernel), np.uint8)
    mask = cv2.morphologyEx(mask_raw, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)

    ki = np.ones((fill_kernel, fill_kernel), np.uint8)
    inv = cv2.bitwise_not(mask)
    inv = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, ki)
    mask = cv2.bitwise_not(inv)

    ko = np.ones((open_kernel, open_kernel), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ko)

    mask_clean = _largest_component_mask(mask, min_keep_area=min_keep_area)
    if mask_clean.max() == 0:
        dbg.append(("no_component", True))
        _debug_write("mask_clean", mask_clean)
        _write_debug_summary()
        return None, dbg, None

    _debug_write("mask_clean", mask_clean)

    cnts, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dbg.append(("contours", len(cnts)))
    if not cnts:
        _write_debug_summary()
        return None, dbg, None

    img_area = float(h * w)
    min_rect_area = 0.1 * img_area
    best_rect, best_score, best_cnt = None, -1.0, None

    for c in cnts:
        if len(c) < 4:
            continue
        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        rect_area = float(max(rw * rh, 1.0))
        if rect_area < min_rect_area:
            continue
        aspect = max(rw, rh) / (min(rw, rh) + 1e-6)
        if aspect > 6.0:
            continue
        cnt_area = cv2.contourArea(c)
        extent = float(cnt_area) / rect_area
        hull_area = float(cv2.contourArea(cv2.convexHull(c))) or 1.0
        hull_extent = float(cnt_area) / hull_area
        coverage = rect_area / img_area
        (cx, cy) = rect[0]
        dx = (cx - w / 2.0) / w
        dy = (cy - h / 2.0) / h
        center_bonus = 1.0 - min(1.0, (dx * dx + dy * dy) ** 0.5 * 2.0)
        slender_penalty = max(0.0, coverage - 0.82) * 2.2
        score = (1.2 * extent) + (0.3 * center_bonus) + (0.2 * hull_extent) - 0.02 * abs(aspect - 1.4) - slender_penalty
        if score > best_score:
            best_score, best_rect, best_cnt = score, rect, c

    if best_rect is None:
        dbg.append(("rect_none", True))
        _write_debug_summary()
        return None, dbg, None

    box = cv2.boxPoints(best_rect).astype('float32')
    ordered = _order_box_points(box)

    if best_cnt is not None:
        axis_x = ordered[1] - ordered[0]
        axis_y = ordered[3] - ordered[0]
        width_len = float(np.linalg.norm(axis_x))
        height_len = float(np.linalg.norm(axis_y))
        if width_len > 1e-3 and height_len > 1e-3:
            axis_x_unit = axis_x / width_len
            axis_y_unit = axis_y / height_len
            pts = best_cnt.reshape(-1, 2).astype(np.float32)
            rel = pts - ordered[0]
            x_coords = rel @ axis_x_unit
            y_coords = rel @ axis_y_unit
            x_lo, x_hi = np.quantile(x_coords, [0.02, 0.98])
            y_lo, y_hi = np.quantile(y_coords, [0.02, 0.98])
            x_lo = float(np.clip(x_lo, 0.0, width_len))
            x_hi = float(np.clip(x_hi, 0.0, width_len))
            y_lo = float(np.clip(y_lo, 0.0, height_len))
            y_hi = float(np.clip(y_hi, 0.0, height_len))
            if x_hi - x_lo < 0.4 * width_len:
                pad = (width_len - (x_hi - x_lo)) * 0.5
                x_lo = max(0.0, x_lo - pad)
                x_hi = min(width_len, x_hi + pad)
            if y_hi - y_lo < 0.4 * height_len:
                pad = (height_len - (y_hi - y_lo)) * 0.5
                y_lo = max(0.0, y_lo - pad)
                y_hi = min(height_len, y_hi + pad)
            pad_frac = 0.02
            x_lo = max(0.0, x_lo - pad_frac * width_len)
            x_hi = min(width_len, x_hi + pad_frac * width_len)
            y_lo = max(0.0, y_lo - pad_frac * height_len)
            y_hi = min(height_len, y_hi + pad_frac * height_len)
            ordered = np.array([
                ordered[0] + axis_x_unit * x_lo + axis_y_unit * y_lo,
                ordered[0] + axis_x_unit * x_hi + axis_y_unit * y_lo,
                ordered[0] + axis_x_unit * x_hi + axis_y_unit * y_hi,
                ordered[0] + axis_x_unit * x_lo + axis_y_unit * y_hi,
            ], dtype=np.float32)

    axis_x = ordered[1] - ordered[0]
    axis_y = ordered[3] - ordered[0]
    width_len = float(np.linalg.norm(axis_x))
    height_len = float(np.linalg.norm(axis_y))
    if quad_expand_frac > 0 and width_len > 1e-3 and height_len > 1e-3:
        axis_x_u = axis_x / width_len
        axis_y_u = axis_y / height_len
        grow_x = quad_expand_frac * width_len
        grow_y = quad_expand_frac * height_len
        ordered = np.array([
            ordered[0] - axis_x_u*grow_x - axis_y_u*grow_y,
            ordered[1] + axis_x_u*grow_x - axis_y_u*grow_y,
            ordered[2] + axis_x_u*grow_x + axis_y_u*grow_y,
            ordered[3] - axis_x_u*grow_x + axis_y_u*grow_y,
        ], dtype=np.float32)

    widthA = np.linalg.norm(ordered[2] - ordered[3])
    widthB = np.linalg.norm(ordered[1] - ordered[0])
    heightA = np.linalg.norm(ordered[1] - ordered[2])
    heightB = np.linalg.norm(ordered[0] - ordered[3])
    W = int(round(max(widthA, widthB)))
    H = int(round(max(heightA, heightB)))
    W = max(W, 1)
    H = max(H, 1)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype='float32')
    P = cv2.getPerspectiveTransform(ordered, dst)
    roi = cv2.warpPerspective(
        upright_bgr, P, (W, H),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0)
    )

    if roi.size == 0:
        _debug_write("roi_empty", roi)
        _write_debug_summary()
        return None, dbg, None

    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    H2, W2 = gray_roi.shape[:2]
    band = int(round(min(H2, W2) * inner_band_frac))
    if band > 0 and (H2 - 2*band) > 4 and (W2 - 2*band) > 4:
        gray_eval = gray_roi[band:-band, band:-band]
    else:
        gray_eval = gray_roi

    dynamic_thresh = max(0, int(gray_eval.max()) - post_white_margin)
    th_eval = cv2.threshold(gray_eval, dynamic_thresh, 255, cv2.THRESH_BINARY)[1]
    white_ratio = float(cv2.countNonZero(th_eval)) / float(max(th_eval.size, 1))

    if target_white_ratio > 0.0 and white_ratio < target_white_ratio:
        if prefer_pad:
            diag = int(round(np.hypot(W2, H2)))
            pad  = max(10, diag // 30)
            roi = cv2.copyMakeBorder(
                roi, pad, pad, pad, pad,
                cv2.BORDER_CONSTANT,
                value=(0, 0, 0)
            )
        else:
            dynamic_full = max(0, int(gray_roi.max()) - post_white_margin)
            thr_full = cv2.threshold(gray_roi, dynamic_full, 255, cv2.THRESH_BINARY)[1]
            col_ratio = thr_full.mean(axis=0) / 255.0
            row_ratio = thr_full.mean(axis=1) / 255.0
            cols = np.where(col_ratio >= target_white_ratio)[0]
            rows = np.where(row_ratio >= target_white_ratio)[0]
            if cols.size >= 2 and rows.size >= 2:
                left = int(cols[0]); right = int(cols[-1]) + 1
                top  = int(rows[0]); bottom = int(rows[-1]) + 1
                margin_x = int(round(crop_margin * W2))
                margin_y = int(round(crop_margin * H2))
                left   = max(0, left - margin_x)
                top    = max(0, top - margin_y)
                right  = min(W2, right + margin_x)
                bottom = min(H2, bottom + margin_y)
                if right - left >= 2 and bottom - top >= 2:
                    roi = roi[top:bottom, left:right]

    dbg.append(("rect_size", (int(W), int(H))))
    dbg.append(("crop_wh", (roi.shape[1], roi.shape[0])))
    _debug_write("roi", roi)
    _write_debug_summary()
    return roi, dbg, dict(ordered=ordered, transform=P)
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


def draw_single_overlay_on_rectified(rect_img: np.ndarray, rect_specs: List[Dict[str, Any]], out_path: Path) -> Path:
    vis = rect_img.copy()
    H, W = vis.shape[:2]
    cv2.rectangle(vis, (0, 0), (W - 1, H - 1), (0, 0, 255), 2)
    for spec in rect_specs:
        x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
        x2, y2 = x + w, y + h
        cv2.rectangle(vis, (int(x), int(y)), (int(x2), int(y2)), (0, 255, 0), 2)
        cv2.putText(vis, spec["name"], (int(x), max(12, int(y) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.imwrite(str(out_path), vis)
    return out_path


def draw_single_overlay_on_original(
    original_bgr: np.ndarray,
    yolo_xyxy: tuple,
    crop_offset_xy: tuple,
    ordered_quad_in_crop: np.ndarray,
    rect_specs: List[Dict[str, Any]],
    Pinv: np.ndarray,
    out_path: Path,
) -> Path:
    vis = original_bgr.copy()
    x1, y1, x2, y2 = map(int, yolo_xyxy)
    cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 0, 0), 2)
    offx, offy = crop_offset_xy
    ordered_shifted = (ordered_quad_in_crop + np.array([offx, offy], dtype=np.float32)).astype(int)
    cv2.polylines(vis, [ordered_shifted], True, (0, 0, 255), 2)
    for spec in rect_specs:
        x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
        rect_pts = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32).reshape(-1, 1, 2)
        crop_pts = cv2.perspectiveTransform(rect_pts, Pinv).reshape(-1, 2)
        crop_pts[:, 0] += offx
        crop_pts[:, 1] += offy
        poly = crop_pts.astype(int)
        cv2.polylines(vis, [poly], True, (0, 255, 0), 2)
        label_pt = poly[0]
        cv2.putText(vis, spec["name"], (int(label_pt[0]), max(12, int(label_pt[1]) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.imwrite(str(out_path), vis)
    return out_path


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
    cls_name = str(cls_name)
    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = det[:4]

    debug_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")

    x1c, y1c, x2c, y2c = clip_box((x1, y1, x2, y2), W, H)
    ex1, ey1, ex2, ey2 = enlarge_box_by_scale((x1c, y1c, x2c, y2c), W, H)
    extra_top = int(0.05 * max(1, ey2 - ey1))
    if extra_top > 0:
        ey1 = max(0, ey1 - extra_top)
    crop = frame_bgr[ey1:ey2, ex1:ex2].copy()
    if crop.size == 0:
        if DEBUG_DUMP_DIR is not None:
            try:
                dump_dir = DEBUG_DUMP_DIR / f"frame{_frame_idx:06d}_empty_crop_{debug_stamp}"
                dump_dir.mkdir(parents=True, exist_ok=True)
                info = {
                    "stage": "empty_crop",
                    "frame_index": _frame_idx,
                    "det_original": [float(v) for v in det[:4]],
                    "det_conf": float(det[4]) if len(det) > 4 else None,
                    "det_class": cls_name,
                    "clip_box": [int(x1c), int(y1c), int(x2c), int(y2c)],
                    "expanded_box": [int(ex1), int(ey1), int(ex2), int(ey2)],
                }
                (dump_dir / "meta.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
            except Exception as dump_err:
                log.warning("Failed to write OCR empty-crop debug dump: %s", dump_err)
        raise RuntimeError("Scaled crop for OCR is empty")

    def _dump_rect_failure(stage: str, dbg_payload):
        if DEBUG_DUMP_DIR is None:
            return
        try:
            dump_dir = DEBUG_DUMP_DIR / f"frame{_frame_idx:06d}_{stage}_{debug_stamp}"
            dump_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dump_dir / "crop.png"), crop)
            try:
                find_minrect_and_crop(
                    crop,
                    debug_prefix=dump_dir / "rect",
                    intensity_cfg=INTENSITY_MASK_CFG,
                    extract_cfg=SLIP_EXTRACT_CFG,
                )
            except Exception:
                pass
            info = {
                "stage": stage,
                "frame_index": _frame_idx,
                "det_original": [float(v) for v in det[:4]],
                "det_conf": float(det[4]) if len(det) > 4 else None,
                "det_class": cls_name,
                "clip_box": [int(x1c), int(y1c), int(x2c), int(y2c)],
                "expanded_box": [int(ex1), int(ey1), int(ex2), int(ey2)],
                "dbg": [[str(k), repr(v)] for (k, v) in (dbg_payload or [])],
            }
            (dump_dir / "meta.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        except Exception as dump_err:
            log.warning("Failed to write OCR rect debug dump: %s", dump_err)

    rect_img, dbg, geom = find_minrect_and_crop(
        crop,
        intensity_cfg=INTENSITY_MASK_CFG,
        extract_cfg=SLIP_EXTRACT_CFG,
    )
    if rect_img is None or rect_img.size == 0:
        _dump_rect_failure("rect_not_found", dbg)
        raise RuntimeError("Rectified slip region not found in detection crop.")

    rect_w, rect_h = rect_img.shape[1], rect_img.shape[0]
    height_label = classify_height(rect_h, HEIGHT_CLASSIFIER)
    final_cls = height_label or cls_name

    if CANONICAL_SIZES and final_cls in CANONICAL_SIZES:
        Wc, Hc = CANONICAL_SIZES[final_cls]
        rect_img = cv2.resize(rect_img, (Wc, Hc), interpolation=cv2.INTER_LINEAR)
        rect_w, rect_h = Wc, Hc

    tpl_path = select_template_path_from_class(final_cls)
    rect_specs = load_template_rects(tpl_path, rect_w, rect_h)
    crops_by_name = crop_by_specs(rect_img, rect_specs, pad=TEMPLATE_CROP_PAD)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    stem = f"slip_{ts}"
    overlay_path = OUT_DIR / f"{stem}.template_overlay.jpg"

    overlay_done = False
    if OVERLAY_MODE == "rectified":
        draw_single_overlay_on_rectified(rect_img, rect_specs, overlay_path)
        overlay_done = True
    else:
        ordered = geom.get("ordered") if geom else None
        transform = geom.get("transform") if geom else None
        if ordered is not None and transform is not None:
            try:
                Pinv = np.linalg.inv(transform)
                draw_single_overlay_on_original(
                    original_bgr=frame_bgr,
                    yolo_xyxy=(x1c, y1c, x2c, y2c),
                    crop_offset_xy=(ex1, ey1),
                    ordered_quad_in_crop=ordered,
                    rect_specs=rect_specs,
                    Pinv=Pinv,
                    out_path=overlay_path,
                )
                overlay_done = True
            except np.linalg.LinAlgError:
                pass
    if not overlay_done:
        draw_single_overlay_on_rectified(rect_img, rect_specs, overlay_path)

    fields = {}
    clinics_in_order: List[str] = []
    for name, roi in crops_by_name.items():
        if roi is None or roi.size == 0:
            continue
        crop_path = OUT_DIR / f"{stem}_{name}.jpg"
        cv2.imwrite(str(crop_path), roi)

    ocr_results = ocr_clinic_fields_for_crops(crops_by_name)
    results_by_name = {item["field"]: item for item in ocr_results}
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

    yolo_box = [int(v) for v in (x1c, y1c, x2c, y2c)]
    result = {
        "capture_id": ts,
        "yolo": {
            "class": final_cls,
            "conf": float(det[4]),
            "box": yolo_box,
            "height_px": rect_h,
            "height_override": height_label,
        },
        "locations": clinics_in_order,
        "clinics": clinics_in_order,
        "fields": fields,
        "outputs": {
            "overlay": str(overlay_path.as_posix()),
            "crops_dir": str(OUT_DIR.as_posix()),
        },
    }
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2))

    global _latest_result, _latest_result_ts
    _latest_result = {
        "locations": result.get("locations", []),
        "yolo": result["yolo"],
        "capture_id": result["capture_id"],
    }
    _latest_result_ts = time.time()
    summary_fields = {name: data.get("clean") for name, data in fields.items()}
    log.info(
        "OCR capture_id=%s class=%s clinics=%s fields=%s",
        result["capture_id"],
        final_cls,
        clinics_in_order,
        summary_fields,
    )

    return result
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

    if ROTATE_STREAM_90 and ROTATE_STREAM_180:
        log.warning("Both ROTATE_STREAM_90 and ROTATE_STREAM_180 enabled; applying single 90-degree rotation.")
    if ROTATE_STREAM_90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif ROTATE_STREAM_180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)

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

    now = time.time()
    best_conf = 0.0
    best_det = None
    is_stable = False
    stability_metrics = {"samples": 0, "center_jitter": None, "area_spread": None, "min_conf": None}

    if _last_boxes:
        best_det = max(_last_boxes, key=lambda b: b[4])
        best_conf = best_det[4]
        frame = _draw_boxes(frame, _last_boxes, (0, 255, 0))
        is_stable, _, stability_metrics = _update_detection_stability(best_det, frame.shape, now)
    else:
        is_stable, _, stability_metrics = _update_detection_stability(None, None, now)

    cv2.putText(
        frame,
        f"frm:{_frame_idx} det:{len(_last_boxes)} conf:{best_conf*100:.1f}%",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
    )

    stab_parts = [f"stb:{stability_metrics.get('samples', 0)}/{STABILITY_MIN_FRAMES}"]
    if stability_metrics.get("min_conf") is not None:
        stab_parts.append(f"mc:{stability_metrics['min_conf']*100:.0f}%")
    if stability_metrics.get("conf_spread") is not None:
        stab_parts.append(f"cs:{stability_metrics['conf_spread']*100:.1f}%")
    if stability_metrics.get("center_jitter") is not None:
        stab_parts.append(f"jit:{stability_metrics['center_jitter']*100:.1f}%")
    if stability_metrics.get("area_spread") is not None:
        stab_parts.append(f"area:{stability_metrics['area_spread']*100:.1f}%")
    if is_stable:
        stab_parts.append("OK")
    cv2.putText(
        frame,
        " ".join(stab_parts),
        (10, 50),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 255, 0) if is_stable else (255, 255, 0), 2,
    )

    # Time-gated OCR (by seconds), not every frame
    can_run_ocr = (
        best_det
        and best_conf >= OCR_MIN_CONF
        and is_stable
        and (now - _last_ocr_time) >= OCR_COOLDOWN_SEC
    )

    if can_run_ocr:
        try:
            _ = _run_ocr_on_detection(frame.copy(), best_det, best_det[5])
            _last_ocr_time = now
            cv2.putText(frame, "OCR OK", (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        except Exception as e:
            cv2.putText(frame, f"OCR ERR: {str(e)[:28]}", (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    elif best_det and best_conf >= OCR_MIN_CONF:
        wait_reasons = []
        if not is_stable:
            wait_reasons.append("stabilising")
        cooldown_remaining = OCR_COOLDOWN_SEC - (now - _last_ocr_time)
        if cooldown_remaining > 0:
            wait_reasons.append(f"cooldown:{cooldown_remaining:.1f}s")
        if wait_reasons:
            cv2.putText(
                frame,
                f"OCR WAIT ({', '.join(wait_reasons)})",
                (10, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 215, 255),
                2,
            )

    # Pace the stream output to a fixed FPS to avoid burstiness
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

@router.post("/latest_result/reset")
def reset_latest_result():
    global _latest_result, _latest_result_ts
    _latest_result = None
    _latest_result_ts = time.time()
    return {"ok": True}

@router.get("/health")
def health():
    return {"ok": True}

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
# this is for Pi camera
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

# Pi camera settings (fixed configuration)
PICAM_VIDEO_SIZE = (640, 480)
PICAM_FRAME_RATE = 30
PICAM_STILL_SIZE = (640, 480)
PICAM_AF_MODE    = controls.AfModeEnum.Continuous
PICAM_AF_RANGE   = controls.AfRangeEnum.Full
PICAM_AF_SPEED   = controls.AfSpeedEnum.Normal

# Stream pacing (prevents fast/slow bursts)
TARGET_STREAM_FPS = int(os.environ.get("TARGET_STREAM_FPS", "8"))
_FRAME_PERIOD     = 1.0 / max(1, TARGET_STREAM_FPS)
STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "85"))

CANONICAL_SIZES = {}

OVERLAY_MODE = os.environ.get("OCR_OVERLAY_MODE", "rectified").lower()
if OVERLAY_MODE not in {"rectified", "original"}:
    OVERLAY_MODE = "rectified"

TESSERACT_WIN_PATH = os.environ.get("TESSERACT_WIN_PATH", "")

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
LOCATION_CANDIDATES = [
    "Diagnostic Imaging 2",
    "Urgent Care Centre",
    "Ward 8",
    "Ward 9",
    "Diagnostic Imaging 3",
    "Major Operating Theatres 1 & 2",
    "Ward 10",
    "Ward 11",
    "Intensive Care Unit 1",
    "Major Operating Theatres 3 & 4",
    "Ward 12",
    "Ward 13",
    "Clinical Measurement Centre",
    "Pharmacy",
    "Clinic J",
    "Clinic K",
    "Ward 7",
    "Care and Counselling",
    "Ear, Nose and Throat Centre",
    "Eye Surgery Centre",
    "Surgery Centre",
    "Ambulatory Surgery Centre",
    "Endoscopy Centre",
    "NUCOHS Dental Clinic",
    "Orthopaedic Centre"
    "Rehabilitation 1",
    "Ward 2",
    "Ward 3",
    "Day Surgery Operating Theatre",
    "Ward 4",
    "Ward 5",
    "Dialysis Centre",
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
# FastAPI router + Camera (Pi camera)
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter()
_camera_init_lock = Lock()
_capture_lock     = Lock()

picam: Optional[Picamera2] = None
_picam_video_config = None
_picam_still_config = None
_camera_started = False

def _ensure_camera_started():
    """Initialise and start the Pi camera lazily, retrying once on failure."""
    global picam, _picam_video_config, _picam_still_config, _camera_started
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
            still_cfg = cam.create_still_configuration(
                main={"size": PICAM_STILL_SIZE},
                controls={
                    "AfMode": PICAM_AF_MODE,
                    "AfRange": PICAM_AF_RANGE,
                    "AfSpeed": PICAM_AF_SPEED,
                },
            )
            return cam, video_cfg, still_cfg

        if picam is None or _picam_video_config is None:
            picam, _picam_video_config, _picam_still_config = _init_camera()

        if not _camera_started:
            try:
                picam.configure(_picam_video_config)
                picam.start()
                _camera_started = True
                log.info(
                    "Pi camera started (%dx%d@%d)",
                    PICAM_VIDEO_SIZE[0],
                    PICAM_VIDEO_SIZE[1],
                    PICAM_FRAME_RATE,
                )
            except RuntimeError as exc:
                log.error("Primary Pi camera start failed: %s", exc)
                try:
                    picam.close()
                except Exception:
                    pass
                picam = None
                _picam_video_config = None
                _picam_still_config = None

                picam, _picam_video_config, _picam_still_config = _init_camera()
                try:
                    picam.configure(_picam_video_config)
                    picam.start()
                    _camera_started = True
                    log.info(
                        "Pi camera restarted after recovery (%dx%d@%d)",
                        PICAM_VIDEO_SIZE[0],
                        PICAM_VIDEO_SIZE[1],
                        PICAM_FRAME_RATE,
                    )
                except RuntimeError as exc2:
                    log.error("Recovery start failed: %s", exc2)
                    try:
                        picam.close()
                    except Exception:
                        pass
                    picam = None
                    _picam_video_config = None
                    _picam_still_config = None
                    raise HTTPException(status_code=500, detail="Pi camera unavailable") from exc2

        return picam

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





def _order_box_points(pts):
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]; br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]; bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")


def _iou_xyxy(box_a, box_b) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in box_a]
    bx1, by1, bx2, by2 = [float(v) for v in box_b]
    if ax2 <= ax1 or ay2 <= ay1 or bx2 <= bx1 or by2 <= by1:
        return 0.0
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    if inter_w == 0.0 or inter_h == 0.0:
        return 0.0
    inter_area = inter_w * inter_h
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    denom = area_a + area_b - inter_area
    if denom <= 0.0:
        return 0.0
    return float(inter_area / denom)


def _quad_from_box(box_xyxy) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in box_xyxy]
    return np.array(
        [
            [x1, y1],
            [x2, y1],
            [x2, y2],
            [x1, y2],
        ],
        dtype=np.float32,
    )


def _rectify_from_quad(image_bgr: np.ndarray, quad_pts: np.ndarray):
    if image_bgr is None or image_bgr.size == 0:
        return None, None, None
    if quad_pts is None or len(quad_pts) != 4:
        return None, None, None
    H, W = image_bgr.shape[:2]
    quad = np.asarray(quad_pts, dtype=np.float32).copy()
    quad[:, 0] = np.clip(quad[:, 0], 0, max(0, W - 1))
    quad[:, 1] = np.clip(quad[:, 1], 0, max(0, H - 1))
    ordered = _order_box_points(quad)
    widthA = np.linalg.norm(ordered[2] - ordered[3])
    widthB = np.linalg.norm(ordered[1] - ordered[0])
    heightA = np.linalg.norm(ordered[1] - ordered[2])
    heightB = np.linalg.norm(ordered[0] - ordered[3])
    rect_w = max(int(round(max(widthA, widthB))), 1)
    rect_h = max(int(round(max(heightA, heightB))), 1)
    if rect_w < 2 or rect_h < 2:
        return None, None, None
    dst = np.array(
        [
            [0, 0],
            [rect_w - 1, 0],
            [rect_w - 1, rect_h - 1],
            [0, rect_h - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(ordered, dst)
    rect_img = cv2.warpPerspective(
        image_bgr,
        transform,
        (rect_w, rect_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return rect_img, ordered, transform


def _resolve_obb_for_detection(frame_bgr: np.ndarray, target_box, expected_cls: str | None):
    if yolo_model is None:
        return None
    try:
        results = yolo_model.predict(
            frame_bgr,
            imgsz=CAPTURE_IMG_SIZE,
            conf=CAPTURE_CONF,
            verbose=False,
        )
    except Exception as exc:
        log.warning("YOLO OBB predict failed during OCR pipeline: %s", exc)
        return None
    if not results:
        return None
    pred = results[0]
    names = getattr(yolo_model, "names", {})
    best = None
    best_score = 0.0
    target = [float(v) for v in target_box]
    obb = getattr(pred, "obb", None)

    def _cls_name_from_id(idx: int) -> str:
        if isinstance(names, dict) and idx in names:
            return str(names[idx])
        return str(idx)

    if obb is not None and len(obb) > 0:
        quads = obb.xyxyxyxy.detach().cpu().numpy()
        confs = obb.conf.detach().cpu().numpy() if obb.conf is not None else np.ones(len(quads), dtype=np.float32)
        cls_ids = obb.cls.detach().cpu().numpy().astype(int) if obb.cls is not None else np.zeros(len(quads), dtype=int)
        for idx, quad_flat in enumerate(quads):
            quad = quad_flat.reshape(4, 2)
            xs = quad[:, 0]
            ys = quad[:, 1]
            box = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
            iou = _iou_xyxy(box, target)
            if iou <= 0.0:
                continue
            cls_name = _cls_name_from_id(cls_ids[idx])
            score = iou
            if expected_cls is not None and cls_name == expected_cls:
                score += 0.05  # small preference for matching class
            if score > best_score:
                best_score = score
                best = {
                    "quad": quad.astype(np.float32),
                    "box": box,
                    "conf": float(confs[idx]),
                    "cls_name": cls_name,
                    "iou": float(iou),
                    "source": "obb",
                }
    if best is None and getattr(pred, "boxes", None) is not None and len(pred.boxes) > 0:
        boxes_xyxy = pred.boxes.xyxy.detach().cpu().numpy()
        confs = pred.boxes.conf.detach().cpu().numpy() if pred.boxes.conf is not None else np.ones(len(boxes_xyxy), dtype=np.float32)
        cls_ids = pred.boxes.cls.detach().cpu().numpy().astype(int) if pred.boxes.cls is not None else np.zeros(len(boxes_xyxy), dtype=int)
        for idx, box in enumerate(boxes_xyxy):
            iou = _iou_xyxy(box, target)
            if iou <= 0.0:
                continue
            cls_name = _cls_name_from_id(cls_ids[idx])
            score = iou
            if expected_cls is not None and cls_name == expected_cls:
                score += 0.05
            if score > best_score:
                best_score = score
                best = {
                    "quad": _quad_from_box(box),
                    "box": [float(v) for v in box],
                    "conf": float(confs[idx]),
                    "cls_name": cls_name,
                    "iou": float(iou),
                    "source": "aabb",
                }
    return best


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


def crop_by_specs(rect_img: np.ndarray, rect_specs: List[Dict[str, Any]]) -> Dict[str, np.ndarray]:
    H, W = rect_img.shape[:2]
    out: Dict[str, np.ndarray] = {}
    for spec in rect_specs:
        x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
        x2, y2 = x + w, y + h
        if x < 0 or y < 0:
            continue
        xx1 = min(W, x)
        yy1 = min(H, y)
        xx2 = min(W, x2)
        yy2 = min(H, y2)
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

    raw_det_conf = None
    if len(det) > 4 and det[4] is not None:
        try:
            raw_det_conf = float(det[4])
        except (TypeError, ValueError):
            raw_det_conf = None
    det_conf_value = raw_det_conf if raw_det_conf is not None else 0.0

    x1c, y1c, x2c, y2c = clip_box((x1, y1, x2, y2), W, H)

    template_cls = cls_name

    quad_global: np.ndarray | None = None
    obb_match = _resolve_obb_for_detection(frame_bgr, (x1c, y1c, x2c, y2c), cls_name)
    if obb_match:
        quad_global = np.asarray(obb_match.get('quad'), dtype=np.float32)
        try:
            det_conf_value = float(obb_match.get('conf', det_conf_value))
        except (TypeError, ValueError):
            pass
        candidate_cls = str(obb_match.get('cls_name'))
        if candidate_cls in CLASS_TO_VARIANT:
            template_cls = candidate_cls

    if quad_global is None:
        quad_global = _quad_from_box((x1c, y1c, x2c, y2c))

    rect_img, ordered, transform = _rectify_from_quad(frame_bgr, quad_global)
    if rect_img is None or transform is None:
        raise RuntimeError('Rectified slip region could not be generated.')
    try:
        Pinv = np.linalg.inv(transform)
    except np.linalg.LinAlgError as exc:
        raise RuntimeError('Rectified slip transform is not invertible.') from exc

    _draw_poly(frame_bgr, quad_global, (0, 0, 255), 2)

    rect_w, rect_h = rect_img.shape[1], rect_img.shape[0]
    final_cls = template_cls
    if CANONICAL_SIZES and final_cls in CANONICAL_SIZES:
        Wc, Hc = CANONICAL_SIZES[final_cls]
        rect_img = cv2.resize(rect_img, (Wc, Hc), interpolation=cv2.INTER_LINEAR)
        rect_w, rect_h = Wc, Hc

    tpl_path = select_template_path_from_class(final_cls)
    rect_specs = load_template_rects(tpl_path, rect_w, rect_h)
    crops_by_name = crop_by_specs(rect_img, rect_specs)

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    stem = f'slip_{ts}'
    overlay_path = OUT_DIR / f'{stem}.template_overlay.jpg'

    for name, roi in crops_by_name.items():
        if roi is None or roi.size == 0:
            continue
        crop_path = OUT_DIR / f'{stem}_{name}.jpg'
        cv2.imwrite(str(crop_path), roi)

    ocr_results = ocr_clinic_fields_for_crops(crops_by_name)
    results_by_name = {item['field']: item for item in ocr_results}

    fields: Dict[str, Dict[str, Any]] = {}
    clinics_in_order: List[str] = []
    overlay_labels: Dict[str, str] = {}

    for spec in rect_specs:
        name = spec['name']
        entry = results_by_name.get(name)
        if not entry:
            continue
        raw_text = entry.get('raw') or ''
        clean_text = entry.get('text') or ''
        matched = entry.get('fuzzy_match')
        score = entry.get('fuzzy_score')
        fields[name] = {
            'raw': raw_text,
            'clean': clean_text,
            'match': matched,
            'match_score': score,
        }
        label_text = ''
        if matched:
            clinics_in_order.append(matched)
            if isinstance(score, (int, float)):
                label_text = f"{matched} ({score:.2f})"
            else:
                label_text = matched
        elif clean_text:
            clinics_in_order.append(clean_text)
            label_text = clean_text
        overlay_labels[name] = label_text

    if overlay_labels:
        _draw_template_rects_on_original(frame_bgr, rect_specs, Pinv, label_texts=overlay_labels)
    else:
        _draw_template_rects_on_original(frame_bgr, rect_specs, Pinv)

    _put_label(frame_bgr, ordered[0], f"{final_cls} {det_conf_value:.2f}")

    overlay_done = False
    if OVERLAY_MODE == 'rectified':
        draw_single_overlay_on_rectified(rect_img, rect_specs, overlay_path)
        overlay_done = True
    else:
        try:
            draw_single_overlay_on_original(
                original_bgr=frame_bgr,
                yolo_xyxy=(x1c, y1c, x2c, y2c),
                crop_offset_xy=(0, 0),
                ordered_quad_in_crop=ordered,
                rect_specs=rect_specs,
                Pinv=Pinv,
                out_path=overlay_path,
            )
            overlay_done = True
        except Exception:
            pass
    if not overlay_done:
        draw_single_overlay_on_rectified(rect_img, rect_specs, overlay_path)

    yolo_box = [int(v) for v in (x1c, y1c, x2c, y2c)]
    result = {
        'capture_id': ts,
        'yolo': {
            'class': final_cls,
            'conf': float(det_conf_value),
            'box': yolo_box,
            'height_px': rect_h,
            'height_override': None,
        },
        'locations': clinics_in_order,
        'clinics': clinics_in_order,
        'fields': fields,
        'outputs': {
            'overlay': str(overlay_path.as_posix()),
            'crops_dir': str(OUT_DIR.as_posix()),
        },
    }

    (OUT_DIR / f'{stem}.json').write_text(json.dumps(result, indent=2))

    global _latest_result, _latest_result_ts
    _latest_result = {
        'locations': result.get('locations', []),
        'yolo': result['yolo'],
        'capture_id': result['capture_id'],
    }
    _latest_result_ts = time.time()
    summary_fields = {name: data.get('clean') for name, data in fields.items()}
    log.info(
        'OCR capture_id=%s class=%s clinics=%s fields=%s',
        result['capture_id'],
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
    Capture, annotate, and encode a single frame for the MJPEG stream (Pi camera).
    Includes:
      - PiCamera2 video stream configured for low latency
      - Pacing to TARGET_STREAM_FPS to avoid burstiness
      - YOLO on a downsized copy; boxes rescaled to original frame
    """
    global _last_boxes, _frame_idx, _last_ocr_time

    if not CAMERA_ENABLED:
        raise RuntimeError("Camera disabled")

    cam_handle = _ensure_camera_started()

    with _capture_lock:
        frame = cam_handle.capture_array("main")
        if frame is None or frame.size == 0:
            raise RuntimeError("Failed to capture frame from Pi camera")
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

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

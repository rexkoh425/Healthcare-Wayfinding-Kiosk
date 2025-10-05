from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
import subprocess
from threading import Lock
import json
from picamera2 import Picamera2
from libcamera import controls
from .ocr_v3 import extract
import cv2, glob, os
import numpy as np
from PIL import Image
import pytesseract
import time
import re, os
import traceback
from .helpers import extract_clinic_locations, match
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Image as RLImage, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
import shutil
from pathlib import Path


cam_lock = Lock()
seg_offset = 40

if os.environ.get('PICAMERA2_TEST_ENV') == '1':
    os.environ['PICAMERA2_USE_V4L2'] = '1'

router = APIRouter()
picam = Picamera2()

vid_config = picam.create_video_configuration(
    main={"size": (640, 480)},
    controls={"FrameRate": 30}
)

pic_config = picam.create_still_configuration(
    main={"size": (4608, 2592)},
    controls={"AfMode": 1}
)

with cam_lock:
    picam.configure(pic_config)
    picam.start()
    picam.set_controls({"AfTrigger": 0})
    timeout = time.time() + 10
    while time.time() < timeout:
        if picam.capture_metadata().get("AfState", 0) == 2:
            break
        time.sleep(0.2)
    time.sleep(1)
    picam.stop()
    picam.configure(vid_config)
    picam.start()
    time.sleep(0.5)

# Keep only the latest set of 4 images (and one PDF) in this folder
OCR_SAVE_DIR = os.environ.get("OCR_SAVE_DIR", "/data/ocr_latest")
os.makedirs(OCR_SAVE_DIR, exist_ok=True)

def _clear_dir(path: str):
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
        except Exception as e:
            print(f"[DEBUG] Failed to remove {p}: {e}")

def _atomic_write_image(path: str, img: np.ndarray):
    # ensure uint8 format for OpenCV writers
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)

    base, ext = os.path.splitext(path)   # ext like ".jpg" / ".png"
    tmp = f"{base}.tmp{ext}"             # e.g., "full.tmp.jpg" => encoder is jpg
    ok = cv2.imwrite(tmp, img)
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed for {tmp}")
    os.replace(tmp, path)                # atomic-ish rename


def _save_latest_set(proc_full, proc_top, proc_middle, proc_bottom, make_pdf: bool = True):
    """
    Overwrite the latest set in OCR_SAVE_DIR:
      - full.jpg, top.jpg, middle.jpg, bottom.jpg
      - ocr_postprocessed.pdf (optional)
    """
    os.makedirs(OCR_SAVE_DIR, exist_ok=True)
    _clear_dir(OCR_SAVE_DIR)

    full_p   = os.path.join(OCR_SAVE_DIR, "full.jpg")
    top_p    = os.path.join(OCR_SAVE_DIR, "top.jpg")
    middle_p = os.path.join(OCR_SAVE_DIR, "middle.jpg")
    bottom_p = os.path.join(OCR_SAVE_DIR, "bottom.jpg")

    _atomic_write_image(full_p,   proc_full)
    _atomic_write_image(top_p,    proc_top)
    _atomic_write_image(middle_p, proc_middle)
    _atomic_write_image(bottom_p, proc_bottom)

    if make_pdf:
        try:
            from reportlab.platypus import SimpleDocTemplate, Image as RLImage, Spacer
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import inch
            from reportlab.lib.utils import ImageReader

            pdf_p = os.path.join(OCR_SAVE_DIR, "ocr_postprocessed.pdf")
            doc = SimpleDocTemplate(
                pdf_p, pagesize=A4,
                leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
            )
            page_w, page_h = A4
            frame_w = page_w - doc.leftMargin - doc.rightMargin
            frame_h = page_h - doc.topMargin - doc.bottomMargin

            elements = []
            for p in [full_p, top_p, middle_p, bottom_p]:
                iw, ih = ImageReader(p).getSize()
                s = min(frame_w/iw, frame_h/ih)
                elements.append(RLImage(p, width=iw*s, height=ih*s))
                elements.append(Spacer(1, 0.25*inch))
            doc.build(elements)
            print(f"[DEBUG] Saved latest PDF: {pdf_p}")
        except Exception as e:
            try:
                from PIL import Image as PILImage
                pdf_p = os.path.join(OCR_SAVE_DIR, "ocr_postprocessed.pdf")
                imgs = [full_p, top_p, middle_p, bottom_p]
                pil = [PILImage.open(p).convert("RGB") for p in imgs]
                pil[0].save(pdf_p, "PDF", resolution=200.0, save_all=True, append_images=pil[1:])
                print(f"[DEBUG] Saved latest PDF (Pillow): {pdf_p}")
            except Exception as e2:
                print(f"[DEBUG] PDF save failed (both methods): {e} / {e2}")



def split_positions(height: int, offset_ratio: float = 0.05):
    """Return (y1, y2) for top/mid/bot split, shifted down by offset_ratio of height."""
    offset = int(height * offset_ratio)           # e.g., 5% downward shift
    y1 = height // 3 + offset
    y2 = (2 * height) // 3 + offset
    # clamp to valid range (avoid going past the image)
    y1 = max(0, min(height - 1, y1))
    y2 = max(0, min(height - 1, y2))
    if y2 <= y1:  # ensure proper order if clamped hard
        y2 = min(height - 1, y1 + max(1, height // 10))
    return y1, y2

def preprocess_pipeline(frame_bgr: np.ndarray, gamma: float = 1.5) -> np.ndarray:
    # 1) Grayscale
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    # 1b) Illumination correction
    bg   = cv2.medianBlur(gray, 31)
    norm = cv2.divide(gray, bg, scale=255)

    # 2) CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(norm)

    # 2b) Deskew
    thr   = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    edges = cv2.Canny(thr, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi/180, 200)
    angle = 0.0
    if lines is not None:
        angs = []
        for rho, theta in lines[:, 0]:
            deg = (theta * 180 / np.pi) - 90
            if -10 < deg < 10:
                angs.append(deg)
        if angs:
            angle = float(np.median(angs))
    M = cv2.getRotationMatrix2D((contrast.shape[1]//2, contrast.shape[0]//2), angle, 1.0)
    deskew = cv2.warpAffine(
        contrast, M, (contrast.shape[1], contrast.shape[0]),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )

    # 2c) Remove lines
    binv = cv2.threshold(deskew, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    mask = np.zeros_like(binv); mask[5:-5, 5:-5] = 255
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, deskew.shape[1]//12), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, deskew.shape[0]//18)))
    h_lines = cv2.bitwise_and(cv2.morphologyEx(binv, cv2.MORPH_OPEN, h_kernel), mask)
    v_lines = cv2.bitwise_and(cv2.morphologyEx(binv, cv2.MORPH_OPEN, v_kernel), mask)
    lines_union   = cv2.bitwise_or(h_lines, v_lines)
    binv_nolines  = cv2.bitwise_and(binv, cv2.bitwise_not(lines_union))
    line_removed  = cv2.bitwise_not(binv_nolines)

    # 3) Denoise
    denoised = cv2.bilateralFilter(line_removed, d=9, sigmaColor=75, sigmaSpace=75)

    # 4) Sharpen
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    sharpened = cv2.filter2D(denoised, -1, kernel)

    # 5) Gamma
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
    gamma_corrected = cv2.LUT(sharpened, table)
    gamma_corrected = crop_black_margins(gamma_corrected, black_thresh=30, percent=0.5)

    return gamma_corrected


def _ocr_best_location(bgr_img: np.ndarray, return_proc: bool = False):
    proc = preprocess_pipeline(bgr_img)
    text = pytesseract.image_to_string(proc, config="--psm 6", lang="eng")
    print("[DEBUG] OCR raw text:\n" + text.replace("\n", "⏎\n"))
    locs = match(text)
    return (locs, text, proc) if return_proc else (locs, text)


def crop_black_margins(img: np.ndarray, black_thresh: int = 30, percent: float = 0.5):
    """
    Crop left/right columns where the fraction of black pixels > percent.
    - img: grayscale or binary (0=black, 255=white)
    - black_thresh: pixel intensity threshold for "black"
    - percent: fraction of black pixels per column to trigger crop
    """
    # Ensure grayscale
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    # Binary threshold (black=1, white=0)
    black_mask = (gray < black_thresh).astype(np.uint8)

    H, W = black_mask.shape
    col_black_frac = black_mask.sum(axis=0) / H  # fraction per column

    # Find left bound
    left = 0
    for i, frac in enumerate(col_black_frac):
        if frac < percent:
            left = i
            break

    # Find right bound
    right = W - 1
    for i in range(W-1, -1, -1):
        if col_black_frac[i] < percent:
            right = i
            break

    # Crop safely
    if right > left:
        return img[:, left:right]
    return img  # no crop if bounds invalid


@router.post("/ocr")
async def run_ocr():
    with cam_lock:
        try:
            # autofocus
            picam.stop()
            picam.configure(pic_config)
            picam.start()
            picam.set_controls({"AfTrigger": 0})
            timeout = time.time() + 10
            while time.time() < timeout:
                if picam.capture_metadata().get("AfState", 0) == 2:
                    break
                time.sleep(0.2)
            time.sleep(1)

            # capture + rotate
            frame = cv2.rotate(picam.capture_array(), cv2.ROTATE_180)

            # crop
            H, W = frame.shape[:2]
            x, y, w, h = 1210, 536, 1994, 2021
            pad = 4
            x = max(0, x - pad); y = max(0, y - pad)
            w = min(W - x, w + 2*pad); h = min(H - y, h + 2*pad)
            roi = frame[y:y+h, x:x+w]
            proc_full = preprocess_pipeline(roi)

            # split into thirds
            rH, rW = roi.shape[:2]
            y1, y2 = split_positions(rH, offset_ratio=-0.04)  # same value as stream

            top    = roi[0:y1, :]
            middle = roi[y1:y2, :]
            bottom = roi[y2:rH, :]
            # OCR each
            dest_top,    text_top,    proc_top    = _ocr_best_location(top,    return_proc=True)
            dest_middle, text_middle, proc_middle = _ocr_best_location(middle, return_proc=True)
            dest_bottom, text_bottom, proc_bottom = _ocr_best_location(bottom, return_proc=True)
            print(
    f"[DEBUG] dest_top={dest_top!r}, dest_middle={dest_middle!r}, dest_bottom={dest_bottom!r}",
    flush=True
) 
            try:
                _save_latest_set(proc_full, proc_top, proc_middle, proc_bottom, make_pdf=True)
            except Exception as e:
                print(f"[DEBUG] Saving latest set failed: {e}")


            # restore video stream
            picam.stop()
            picam.configure(vid_config)
            picam.start()
            ''' use this if want a fix return
            return JSONResponse(content={
                "locations": [
                    "Clinic A",
                    "Cocoon Clinic"
                ]
            })
            '''
            return JSONResponse(content={
                "locations": [
                    dest_top,
                    dest_middle,
                    dest_bottom
                ]
            })

        except Exception as e:
            try:
                picam.stop()
                picam.configure(vid_config)
                picam.start()
            except:
                pass
            raise HTTPException(status_code=500, detail=str(e))

# MJPEG Stream Route
@router.get("/stream.mjpg")
def stream():
    def generate():
        while True:
            with cam_lock:

                frame = picam.capture_array()
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                frame = cv2.rotate(frame, cv2.ROTATE_180)

                H, W = frame.shape[:2]
                y1, y2 = split_positions(H, offset_ratio=0.08)

                # red in BGR = (0, 0, 255)
                cv2.line(frame, (0, y1), (W - 1, y1), (0, 0, 255), thickness=3, lineType=cv2.LINE_AA)
                cv2.line(frame, (0, y2), (W - 1, y2), (0, 0, 255), thickness=3, lineType=cv2.LINE_AA)
                _, jpeg = cv2.imencode('.jpg', frame)
            yield (b'--FRAME\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    return StreamingResponse(generate(), media_type='multipart/x-mixed-replace; boundary=FRAME')

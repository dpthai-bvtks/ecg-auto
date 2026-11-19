"""ECG Image Preprocessing: EXIF, rotation, paper crop, deskew, panel split, ink extraction."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class PreprocessedECG:
    paper_img: np.ndarray
    waveform_img: np.ndarray
    report_img: Optional[np.ndarray]
    ink_map: np.ndarray
    ink_map_raw: np.ndarray
    has_right_report_panel: bool
    is_colored_grid: bool
    deskew_angle_deg: float
    split_x_ratio: Optional[float]


def _apply_rotation_bgr(img: np.ndarray, rotation_deg: int) -> np.ndarray:
    rot = int(rotation_deg or 0) % 360
    if rot == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if rot == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if rot == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _apply_crop_box(img: np.ndarray, crop_box: Optional[dict]) -> np.ndarray:
    if not crop_box:
        return img
    h, w = img.shape[:2]
    try:
        x = max(0.0, min(1.0, float(crop_box.get("x", 0.0))))
        y = max(0.0, min(1.0, float(crop_box.get("y", 0.0))))
        cw = max(0.05, min(1.0 - x, float(crop_box.get("w", 1.0))))
        ch = max(0.05, min(1.0 - y, float(crop_box.get("h", 1.0))))
    except (TypeError, ValueError):
        return img

    x1 = int(round(x * w))
    y1 = int(round(y * h))
    x2 = int(round((x + cw) * w))
    y2 = int(round((y + ch) * h))
    if x2 - x1 >= 64 and y2 - y1 >= 64:
        return img[y1:y2, x1:x2].copy()
    return img


def _auto_crop_paper(img: np.ndarray) -> np.ndarray:
    """Crop dark desk/table margin around bright ECG paper without clipping waveforms."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    p75 = float(np.percentile(gray, 75))
    if p75 < 110:
        return img

    bright_thr = max(110, min(175, int(p75 * 0.68)))
    bright_mask = gray > bright_thr

    row_frac = bright_mask.mean(axis=1)
    col_frac = bright_mask.mean(axis=0)

    good_rows = np.where(row_frac > 0.30)[0]
    good_cols = np.where(col_frac > 0.30)[0]
    if len(good_rows) < 30 or len(good_cols) < 50:
        return img

    y1 = max(0, int(good_rows[0]) - 2)
    y2 = min(h, int(good_rows[-1]) + 3)
    x1 = max(0, int(good_cols[0]) - 2)
    x2 = min(w, int(good_cols[-1]) + 3)

    area_ratio = ((x2 - x1) * (y2 - y1)) / float(max(1, w * h))
    if 0.30 <= area_ratio < 0.985 and (x2 - x1) > 100 and (y2 - y1) > 60:
        return img[y1:y2, x1:x2].copy()
    return img


def _estimate_deskew_angle(img: np.ndarray) -> float:
    """Estimate small paper tilt (-6..+6 deg) from near-horizontal edges."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120, apertureSize=3)
    min_len = max(40, int(w * 0.08))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=60,
        minLineLength=min_len,
        maxLineGap=12,
    )
    if lines is None or len(lines) == 0:
        return 0.0

    angles = []
    weights = []
    for line in lines.reshape(-1, 4):
        x1, y1, x2, y2 = line
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        length = float(np.hypot(dx, dy))
        if abs(dx) < 1e-3:
            continue
        ang = float(np.degrees(np.arctan2(dy, dx)))
        if -6.0 <= ang <= 6.0:
            angles.append(ang)
            weights.append(length)

    if len(angles) < 3 or sum(weights) < w * 0.25:
        return 0.0

    # Weighted median
    order = np.argsort(angles)
    ang_sorted = np.array(angles)[order]
    w_sorted = np.array(weights)[order]
    cum = np.cumsum(w_sorted) / np.sum(w_sorted)
    med_angle = float(ang_sorted[np.searchsorted(cum, 0.5)])

    if 0.4 < abs(med_angle) < 6.0:
        return med_angle
    return 0.0


def _deskew_image(img: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(angle_deg) <= 0.4:
        return img
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(
        img,
        mat,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _split_waveform_and_report(paper_img: np.ndarray) -> tuple[np.ndarray, Optional[np.ndarray], bool, Optional[float]]:
    """Detect wide dual-panel ECG sheet (waveform left + text report right) and split cleanly."""
    h, w = paper_img.shape[:2]
    aspect = w / float(max(1, h))
    if aspect < 2.15:
        return paper_img, None, False, None

    gray = cv2.cvtColor(paper_img, cv2.COLOR_BGR2GRAY)
    k = max(15, min(51, (h // 10) | 1))
    bg = cv2.medianBlur(gray, k)
    diff = cv2.subtract(bg, gray)

    y_top = int(0.18 * h)
    y_bot = int(0.88 * h)
    band = diff[y_top:y_bot, :]
    col_density = (band > 20).mean(axis=0)

    win = max(9, min(31, (w // 70) | 1))
    kernel = np.ones(win, dtype=np.float32) / win
    smooth = np.convolve(col_density.astype(np.float32), kernel, mode="same")

    x_start = int(0.55 * w)
    x_end = int(0.80 * w)
    roi = smooth[x_start:x_end]
    if len(roi) == 0:
        return paper_img, None, False, None

    # Find widest contiguous valley where ink density is near zero
    low_mask = roi < 0.008
    best_len = 0
    best_span = None
    cur_start = None
    for idx, is_low in enumerate(low_mask):
        if is_low and cur_start is None:
            cur_start = idx
        elif not is_low and cur_start is not None:
            length = idx - cur_start
            if length > best_len:
                best_len = length
                best_span = (cur_start, idx - 1)
            cur_start = None
    if cur_start is not None:
        length = len(low_mask) - cur_start
        if length > best_len:
            best_len = length
            best_span = (cur_start, len(low_mask) - 1)

    if best_span is None or best_len < max(10, int(0.015 * w)):
        return paper_img, None, False, None

    split_x = x_start + (best_span[0] + best_span[1]) // 2
    left_density = float(col_density[int(0.05 * w):split_x].mean()) if split_x > int(0.1 * w) else 0.0
    right_density = float(col_density[split_x:int(0.95 * w)].mean()) if split_x < int(0.9 * w) else 0.0

    # Verify both left (waveforms) and right (report text) have real ink content
    if left_density < 0.006 or right_density < 0.004:
        return paper_img, None, False, None

    waveform_img = paper_img[:, :split_x].copy()
    report_img = paper_img[:, split_x:].copy()
    return waveform_img, report_img, True, round(split_x / float(w), 4)


def _extract_ink_map(waveform_img: np.ndarray) -> tuple[np.ndarray, np.ndarray, bool]:
    """Produce clean ink probability/intensity maps robust to shadows and pink/gray grids."""
    h, w = waveform_img.shape[:2]
    b, g, r = cv2.split(waveform_img)
    gray = cv2.cvtColor(waveform_img, cv2.COLOR_BGR2GRAY)

    rg_map = r.astype(np.float32) - g.astype(np.float32)
    rb_map = r.astype(np.float32) - b.astype(np.float32)
    # Use 95th percentile so thin 1px pink/red grid lines (~8% area) are still detected cleanly
    is_colored_grid = (float(np.percentile(rg_map, 95)) > 12.0) or (float(np.percentile(rb_map, 95)) > 14.0)

    k = max(15, min(51, (h // 10) | 1))
    bg_gray = cv2.medianBlur(gray, k)
    diff_gray = cv2.subtract(bg_gray, gray)

    if is_colored_grid:
        # Red/pink grid stays bright in Red channel while dark trace drops sharply in Red
        bg_r = cv2.medianBlur(r, k)
        diff_r = cv2.subtract(bg_r, r)
        ink_raw = np.maximum(diff_r, cv2.scaleAdd(diff_gray, 0.35, np.zeros_like(diff_gray)))
        # Keep strictly dark trace pixels strong
        ink_raw = np.where(diff_gray > 25, np.maximum(diff_r, diff_gray), diff_r).astype(np.uint8)
    else:
        ink_raw = diff_gray

    # Suppress subtle paper grain / faint grid floor cleanly while preserving trace strokes
    p85 = float(np.percentile(ink_raw, 85))
    floor = max(10.0, min(26.0, p85 + 6.0))
    clean = np.clip((ink_raw.astype(np.float32) - floor) * (255.0 / max(40.0, 255.0 - floor)), 0, 255).astype(np.uint8)

    return clean, ink_raw, is_colored_grid


def preprocess_ecg_image(
    image_bytes: bytes,
    rotation_deg: int = 0,
    crop_box: Optional[dict] = None,
) -> PreprocessedECG:
    """Decode, orient, crop paper, gently deskew, split panels, and extract waveform ink map."""
    pil_img = Image.open(io.BytesIO(image_bytes))
    pil_img = ImageOps.exif_transpose(pil_img)
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    bgr = _apply_rotation_bgr(bgr, rotation_deg)
    bgr = _apply_crop_box(bgr, crop_box)

    paper_img = _auto_crop_paper(bgr)
    angle = _estimate_deskew_angle(paper_img)
    if abs(angle) > 0.4:
        paper_img = _deskew_image(paper_img, angle)

    waveform_img, report_img, has_report, split_ratio = _split_waveform_and_report(paper_img)
    ink_map, ink_raw, is_colored = _extract_ink_map(waveform_img)

    return PreprocessedECG(
        paper_img=paper_img,
        waveform_img=waveform_img,
        report_img=report_img,
        ink_map=ink_map,
        ink_map_raw=ink_raw,
        has_right_report_panel=has_report,
        is_colored_grid=is_colored,
        deskew_angle_deg=round(angle, 2),
        split_x_ratio=split_ratio,
    )


def encode_cropped_waveform_jpeg(waveform_img: np.ndarray, max_side: int = 1800, quality: int = 88) -> str:
    """Enhance contrast subtly on cropped waveform sheet and return base64 JPEG."""
    h, w = waveform_img.shape[:2]
    img = waveform_img
    longest = max(h, w)
    if longest > max_side:
        scale = max_side / float(longest)
        img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
    elif longest < 1100:
        # Mild upscale helps Vision models read small J-point details on low-res crops
        scale = min(2.0, 1400.0 / float(longest))
        img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_CUBIC)

    # Mild CLAHE on luminance for crisp trace visibility without washing out grid
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_ch)
    enhanced = cv2.cvtColor(cv2.merge((l_eq, a_ch, b_ch)), cv2.COLOR_LAB2BGR)

    ok, buf = cv2.imencode(".jpg", enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("Failed to encode waveform JPEG")
    return base64.b64encode(buf.tobytes()).decode("ascii")

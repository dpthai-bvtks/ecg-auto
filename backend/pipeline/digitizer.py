"""12-Lead ECG Waveform Digitizer: DP/Viterbi trace tracker + calibration pulse & gain calibration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import GRID_4X3, LEAD_NAMES
from .ocr_parser import OCRResult, STANDARD_GAINS

TARGET_FS = 500
TARGET_LEN_10S = 5000
TARGET_LEN_25S = 1250  # 2.5 seconds @ 500 Hz


@dataclass
class RawTraces:
    row_traces_px: List[np.ndarray]  # 3 rows of shape (x_span,) in image Y coordinates
    rhythm_trace_px: Optional[np.ndarray]
    row_bands: List[Tuple[int, int]]
    rhythm_band: Optional[Tuple[int, int]]
    x_left: int
    x_right: int
    col_bounds: List[Tuple[int, int]]  # 4 columns (inclusive-exclusive in waveform_img X)
    pulse_heights_px: List[Optional[float]]  # detected 1mV pulse height per column (col1..col4)
    pulse_trim_ranges: List[Tuple[int, int]]  # (trim_left_px, trim_right_px) per column
    px_per_mm_x: float
    px_per_mm_y: float
    px_per_mm: float
    lead_qualities: Dict[str, float]


@dataclass
class DigitizedECG:
    leads_mv_raw: Dict[str, np.ndarray]  # 12 leads @ 500 Hz in true mV (unnormalized)
    rhythm_mv_raw: Optional[np.ndarray]  # ~10s rhythm strip @ 500 Hz in true mV
    tensor_12x5000: np.ndarray           # float32 (12, 5000) @ 500 Hz for ECGFounder
    digitized_preview: Dict[str, List[float]]
    column_gains_mm_per_mv: Dict[str, float]
    px_per_mm: float
    lead_qualities: Dict[str, float]


def _find_trace_bands(ink_map: np.ndarray) -> Tuple[List[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Locate 3 lead rows (+ optional bottom rhythm strip) from horizontal ink projections."""
    wh, ww = ink_map.shape
    y_min = int(0.16 * wh)
    y_max = int(0.95 * wh)
    roi = ink_map[y_min:y_max, :]

    # Split width into 8 bins; a real ECG trace spans >= 5 bins horizontally
    x0 = int(0.04 * ww)
    x1 = int(0.96 * ww)
    edges = np.linspace(x0, x1, 9, dtype=int)
    bin_hits = np.zeros(roi.shape[0], dtype=np.int32)
    for b in range(8):
        sub = roi[:, edges[b] : edges[b + 1]]
        frac = (sub > 20).mean(axis=1)
        bin_hits += (frac > 0.012).astype(np.int32)

    row_cov = (roi[:, x0:x1] > 20).mean(axis=1)
    # Smooth slightly vertically
    k3 = np.ones(3, dtype=np.float32) / 3.0
    cov_sm = np.convolve(row_cov.astype(np.float32), k3, mode="same")
    active = (cov_sm > 0.012) & (bin_hits >= 5)

    # Group contiguous active y rows, bridging tiny 1-3px gaps
    bands: List[Tuple[int, int]] = []
    in_b = False
    start = 0
    gap = 0
    for idx, flag in enumerate(active):
        if flag:
            if not in_b:
                start = idx
                in_b = True
            gap = 0
        else:
            if in_b:
                gap += 1
                if gap > 3:
                    end = idx - gap
                    if end - start >= max(8, int(0.03 * wh)):
                        bands.append((y_min + start, y_min + end + 1))
                    in_b = False
                    gap = 0
    if in_b:
        end = len(active) - 1 - gap
        if end - start >= max(8, int(0.03 * wh)):
            bands.append((y_min + start, y_min + end + 1))

    # Filter out any header/footer stray band if > 4 bands detected
    if len(bands) > 4:
        # Remove bottom-most footer band if near bottom edge (> 91% height)
        while len(bands) > 4 and bands[-1][0] > int(0.90 * wh):
            bands.pop()
        # Remove top-most header text band if < 20% height
        while len(bands) > 4 and bands[0][1] < int(0.21 * wh):
            bands.pop(0)
        if len(bands) > 4:
            # Keep 4 tallest bands in vertical order
            top4 = sorted(bands, key=lambda b: b[1] - b[0], reverse=True)[:4]
            bands = sorted(top4, key=lambda b: b[0])

    if len(bands) < 3:
        # Geometric fallback
        has_rhythm = wh > 220
        wf_top = int(0.20 * wh)
        wf_bot = int(0.72 * wh) if has_rhythm else int(0.90 * wh)
        step = (wf_bot - wf_top) / 3.0
        lead_bands = [
            (int(wf_top + r * step), int(wf_top + (r + 1) * step)) for r in range(3)
        ]
        rhythm_band = (int(0.75 * wh), int(0.92 * wh)) if has_rhythm else None
        return lead_bands, rhythm_band

    lead_bands = bands[:3]
    rhythm_band = bands[3] if len(bands) >= 4 else None

    # Expand each band generously up to halfway to adjacent band so tall R/S peaks aren't clipped
    all_bands = lead_bands + ([rhythm_band] if rhythm_band is not None else [])
    expanded: List[Tuple[int, int]] = []
    for i, (b0, b1) in enumerate(all_bands):
        prev_end = all_bands[i - 1][1] if i > 0 else int(0.16 * wh)
        next_start = all_bands[i + 1][0] if i + 1 < len(all_bands) else int(0.94 * wh)
        pad_top = min(max(6, (b0 - prev_end) // 2), 16)
        pad_bot = min(max(6, (next_start - b1) // 2), 14)
        expanded.append((max(0, b0 - pad_top), min(wh, b1 + pad_bot)))

    return expanded[:3], (expanded[3] if len(expanded) >= 4 else None)


def _find_active_x_span(ink_map: np.ndarray, lead_bands: List[Tuple[int, int]]) -> Tuple[int, int]:
    """Find [x_left, x_right) spanning the 4 columns across the 3 lead rows using clean ink_map."""
    _wh, ww = ink_map.shape
    row_active = np.zeros(ww, dtype=np.int32)
    for y0, y1 in lead_bands:
        band = ink_map[y0:y1, :]
        has_ink = (band.max(axis=0) > 16).astype(np.int32)
        row_active += has_ink

    # At least 2 of 3 rows active; smooth small breaks (1-3px) via morphological closing in 1D
    mask = (row_active >= 2).astype(np.uint8)
    k_close = np.ones(7, dtype=np.uint8)
    closed = np.convolve(mask, k_close, mode="same") > 0

    # Find longest contiguous span (or bounding span of significant segments >= 20px)
    segs: List[Tuple[int, int]] = []
    in_s = False
    s0 = 0
    for x, v in enumerate(closed):
        if v and not in_s:
            s0 = x
            in_s = True
        elif not v and in_s:
            if x - s0 >= max(20, int(0.05 * ww)):
                segs.append((s0, x))
            in_s = False
    if in_s and ww - s0 >= max(20, int(0.05 * ww)):
        segs.append((s0, ww))

    if not segs:
        return int(0.06 * ww), int(0.95 * ww)
    return int(segs[0][0]), int(segs[-1][1])


def _dp_track_band(
    ink_band: np.ndarray,
    ink_raw_band: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """
    Track continuous horizontal ECG waveform across columns using Viterbi/Dynamic Programming
    with Huber jump penalty + sub-pixel centroid refinement.
    Returns (y_coords_in_band, baseline_y_in_band).
    """
    h, w = ink_band.shape
    if h < 4 or w < 10:
        return np.full(w, h * 0.5, dtype=np.float32), h * 0.5

    # Estimate trace baseline Y from interior columns [15%..85%] via histogram mode (2px bins)
    # (the baseline occupies the vast majority of columns, unlike corner labels or brief R peaks)
    strong = np.maximum(ink_band.astype(np.float32), ink_raw_band.astype(np.float32) * 0.65)
    ia = int(0.15 * w)
    ib = max(ia + 6, int(0.85 * w))
    core_strong = strong[:, ia:ib]
    col_peaks = np.argmax(core_strong, axis=0)
    valid_cols = core_strong.max(axis=0) > 20.0
    if np.sum(valid_cols) >= 6:
        ys_valid = col_peaks[valid_cols]
        # Mode in 2px bins breaks ties toward true flat baseline better than median when huge ST/T exists
        bins = np.arange(0, h + 3, 2, dtype=np.float32)
        hist, _ = np.histogram(ys_valid, bins=bins)
        best_bin = int(np.argmax(hist))
        y_base = float(best_bin * 2 + 1)
    else:
        y_base = h * 0.55

    # Build cost volume C[y, x] where strong ink (including tall thin R spikes) is strongly rewarded
    norm_ink = np.clip(strong / 75.0, 0.0, 1.8)
    col_has_ink = strong.max(axis=0) > 20.0

    ys = np.arange(h, dtype=np.float32)[:, None]
    dist_base = np.abs(ys - y_base)
    base_pull = np.where(col_has_ink[None, :], 0.010 * dist_base, 0.12 * dist_base)
    node_cost = (1.8 - 1.5 * norm_ink) + base_pull  # shape (h, w)

    # Vectorized DP forward pass: smooth on slopes, capped jump cost so tall R/S peaks are never skipped
    max_jump = min(h - 1, max(14, int(h * 0.72)))
    dy_offsets = np.arange(-max_jump, max_jump + 1, dtype=np.int32)
    abs_dy = np.abs(dy_offsets).astype(np.float32)
    trans_pen = np.where(
        abs_dy <= 4.0,
        0.12 * abs_dy,
        np.minimum(0.75, 0.48 + 0.025 * (abs_dy - 4.0)),
    ).astype(np.float32)

    dp = np.zeros((h, w), dtype=np.float32)
    back = np.zeros((h, w), dtype=np.int32)
    dp[:, 0] = node_cost[:, 0] + 0.12 * np.abs(np.arange(h, dtype=np.float32) - y_base)

    pad_buf = np.full(h + 2 * max_jump, np.inf, dtype=np.float32)
    y_arange = np.arange(h, dtype=np.int32) - max_jump
    win_size = 2 * max_jump + 1
    pen_row = trans_pen[None, :]

    for x in range(1, w):
        pad_buf[max_jump : max_jump + h] = dp[:, x - 1]
        win = np.lib.stride_tricks.sliding_window_view(pad_buf, win_size)
        costs = win + pen_row
        best_j = np.argmin(costs, axis=1)
        dp[:, x] = costs[np.arange(h), best_j] + node_cost[:, x]
        back[:, x] = np.clip(y_arange + best_j, 0, h - 1)

    # Backtrack
    path = np.zeros(w, dtype=np.int32)
    path[-1] = int(np.argmin(dp[:, -1]))
    for x in range(w - 1, 0, -1):
        path[x - 1] = back[path[x], x]

    # Connected-stroke tip refinement: captures narrow vertical R/S peaks that DP might shortcut at baseline
    # (only follows pixels strictly connected vertically without white gap, so floating text is never hit)
    refined = path.copy()
    for x in range(w):
        yc = int(path[x])
        col_ink = strong[:, x]
        if col_ink[yc] < 20.0:
            continue
        y_top = yc
        gap = 0
        while y_top > 0:
            if col_ink[y_top - 1] >= 22.0:
                y_top -= 1
                gap = 0
            elif gap == 0 and y_top > 1 and col_ink[y_top - 2] >= 28.0:
                y_top -= 2
                gap = 1
            else:
                break
        y_bot = yc
        gap = 0
        while y_bot < h - 1:
            if col_ink[y_bot + 1] >= 22.0:
                y_bot += 1
                gap = 0
            elif gap == 0 and y_bot < h - 2 and col_ink[y_bot + 2] >= 28.0:
                y_bot += 2
                gap = 1
            else:
                break
        if (y_bot - y_top) >= 5:
            up_dist = abs(float(y_top) - y_base)
            dn_dist = abs(float(y_bot) - y_base)
            # If both upward and downward legs exist in neighboring columns, alternate or pick stronger excursion
            if (yc - y_top) >= 4 and (y_bot - yc) >= 4:
                refined[x] = y_top if (x % 2 == 0 or up_dist >= dn_dist * 1.2) else y_bot
            elif (yc - y_top) >= 4 and up_dist > abs(float(yc) - y_base) + 2.0:
                refined[x] = y_top
            elif (y_bot - yc) >= 4 and dn_dist > abs(float(yc) - y_base) + 2.0:
                refined[x] = y_bot

    # Sub-pixel centroid refinement in window [y-2 .. y+2] using raw ink intensity
    y_sub = refined.astype(np.float32)
    for x in range(w):
        yc = int(refined[x])
        ya = max(0, yc - 2)
        yb = min(h, yc + 3)
        weights = np.maximum(0.0, ink_raw_band[ya:yb, x].astype(np.float32) - 10.0)
        wsum = float(weights.sum())
        if wsum > 15.0:
            coords = np.arange(ya, yb, dtype=np.float32)
            y_sub[x] = float((coords * weights).sum() / wsum)

    return y_sub, y_base


def _detect_calibration_pulse_in_cell(
    trace_px: np.ndarray,
    search_left: int,
    search_right: int,
) -> Optional[Tuple[int, int, float]]:
    """
    Look for a flat-top rectangular 1 mV calibration step inside [search_left, search_right].
    Returns (pulse_x_start, pulse_x_end, height_px) or None.
    """
    n = len(trace_px)
    a = max(2, search_left)
    b = min(n - 2, search_right)
    if b - a < 8:
        return None

    seg = trace_px[a:b]
    # Baseline is the highest-Y (lowest voltage) stable level in neighborhood
    base_y = float(np.percentile(seg, 78))
    step = base_y - seg  # positive upward in pixels

    # Try candidate plateau widths w_p in 3..14 px
    best_score = 0.0
    best_res = None
    for s in range(1, len(seg) - 4):
        for w_p in range(3, min(14, len(seg) - s)):
            plat = step[s : s + w_p]
            h_mean = float(np.mean(plat))
            if h_mean < 3.5:
                continue
            plat_std = float(np.std(plat))
            if plat_std > max(1.2, 0.18 * h_mean):
                continue
            # Check drop back down before and after plateau (allowing 1-2px steep edge transition)
            left_drop = float(np.min(step[max(0, s - 2) : s]))
            right_seg = step[s + w_p : min(len(step), s + w_p + 2)]
            right_drop = float(np.min(right_seg)) if len(right_seg) > 0 else 0.0
            sharp_edges = (h_mean - left_drop > 0.55 * h_mean) and (h_mean - right_drop > 0.55 * h_mean)
            if not sharp_edges:
                continue
            score = h_mean * np.sqrt(w_p) / (1.0 + plat_std)
            if score > best_score:
                best_score = score
                best_res = (a + s, a + s + w_p, h_mean)
    return best_res


def extract_raw_traces(ink_map: np.ndarray, ink_map_raw: np.ndarray) -> RawTraces:
    """Extract continuous pixel-space traces across 4x3 cells (+ rhythm strip) and detect cal pulses."""
    wh, ww = ink_map.shape
    lead_bands, rhythm_band = _find_trace_bands(ink_map)
    x_left, x_right = _find_active_x_span(ink_map, lead_bands)
    span_w = max(40, x_right - x_left)

    # 4 equal columns spanning [x_left, x_right)
    col_edges = np.linspace(0, span_w, 5, dtype=int)
    col_bounds = [(x_left + int(col_edges[c]), x_left + int(col_edges[c + 1])) for c in range(4)]

    # Track EACH cell (r, c) independently so per-cell baseline y_base never jumps at boundaries!
    row_traces_px: List[np.ndarray] = []
    for y0, y1 in lead_bands:
        cell_segs = []
        for c in range(4):
            cx0 = x_left + int(col_edges[c])
            cx1 = x_left + int(col_edges[c + 1])
            y_sub, _ = _dp_track_band(ink_map[y0:y1, cx0:cx1], ink_map_raw[y0:y1, cx0:cx1])
            cell_segs.append(y_sub + float(y0))
        row_traces_px.append(np.concatenate(cell_segs))

    rhythm_trace_px: Optional[np.ndarray] = None
    if rhythm_band is not None:
        ry0, ry1 = rhythm_band
        r_sub, _ = _dp_track_band(ink_map[ry0:ry1, x_left:x_right], ink_map_raw[ry0:ry1, x_left:x_right])
        rhythm_trace_px = r_sub + float(ry0)

    # Detect square 1 mV calibration pulses at right tail (or left head) of each column
    pulse_heights: List[Optional[float]] = []
    pulse_trims: List[Tuple[int, int]] = []
    pulse_widths_px: List[int] = []
    detected_tail_trims: List[int] = []

    for c in range(4):
        c0 = int(col_edges[c])
        c1 = int(col_edges[c + 1])
        cw = c1 - c0
        tail_margin = max(18, int(round(0.16 * cw)))
        head_margin = max(18, int(round(0.16 * cw)))

        # Aggregate candidate pulse detections across all 3 rows inside cell boundaries
        tail_hits: List[Tuple[int, int, float]] = []
        head_hits: List[Tuple[int, int, float]] = []
        for r in range(3):
            th = _detect_calibration_pulse_in_cell(row_traces_px[r], c1 - tail_margin, min(len(row_traces_px[r]), c1 + 4))
            if th is not None:
                tail_hits.append(th)
            hh = _detect_calibration_pulse_in_cell(row_traces_px[r], c0, c0 + head_margin)
            if hh is not None:
                head_hits.append(hh)

        trim_l = 0
        trim_r = 0
        detected_h: Optional[float] = None

        if len(tail_hits) >= 2:
            xs_min = min(h[0] for h in tail_hits)
            trim_r = max(4, (c1 - xs_min) + 2)
            detected_h = float(np.median([h[2] for h in tail_hits]))
            pulse_widths_px.append(int(np.median([h[1] - h[0] for h in tail_hits])))
            detected_tail_trims.append(trim_r)
        elif len(tail_hits) == 1 and tail_hits[0][2] >= 5.0:
            trim_r = max(4, (c1 - tail_hits[0][0]) + 2)
            detected_h = float(tail_hits[0][2])
            pulse_widths_px.append(int(tail_hits[0][1] - tail_hits[0][0]))
            detected_tail_trims.append(trim_r)
        elif len(head_hits) >= 2:
            xe_max = max(h[1] for h in head_hits)
            trim_l = max(4, (xe_max - c0) + 2)
            detected_h = float(np.median([h[2] for h in head_hits]))
            pulse_widths_px.append(int(np.median([h[1] - h[0] for h in head_hits])))

        trim_l = max(trim_l, 2)
        trim_r = max(trim_r, 3)
        pulse_heights.append(detected_h)
        pulse_trims.append((trim_l, trim_r))

    # Share consistent tail trim across columns if pulses were detected at end of columns
    if detected_tail_trims:
        shared_tail = int(np.median(detected_tail_trims))
        for c in range(4):
            tl, tr = pulse_trims[c]
            if tr < shared_tail - 2:
                pulse_trims[c] = (tl, shared_tail)

    # Estimate px_per_mm_x: 4 columns * 2.5s @ 25mm/s = 250mm (minus ~1 cal pulse width if at end)
    avg_pulse_w = float(np.median(pulse_widths_px)) if pulse_widths_px else 0.0
    effective_span = float(span_w) - avg_pulse_w
    px_per_mm_x = max(1.0, effective_span / 250.0)

    # Estimate px_per_mm_y from detected 10 mm/mV calibration pulses if available (assume col1/col2 are 10 mm/mV unless overridden)
    tall_pulses = [h for h in pulse_heights if h is not None and h >= 1.6 * 10.0 * 0.55 * px_per_mm_x / 1.0]
    px_per_mm_y = px_per_mm_x
    # Refine in apply_gains_and_build_signals once OCR gains are known!
    if tall_pulses:
        cand_y = float(np.median(tall_pulses)) / 10.0
        if 0.80 * px_per_mm_x <= cand_y <= 1.25 * px_per_mm_x:
            px_per_mm_y = cand_y

    # Compute per-lead ink quality score (fraction of columns with visible ink)
    lead_qualities: Dict[str, float] = {}
    for r in range(3):
        y0, y1 = lead_bands[r]
        for c in range(4):
            lead_name = GRID_4X3[r][c]
            cx0 = x_left + int(col_edges[c]) + pulse_trims[c][0]
            cx1 = x_left + int(col_edges[c + 1]) - pulse_trims[c][1]
            if cx1 > cx0 + 10:
                col_max = ink_map_raw[y0:y1, cx0:cx1].max(axis=0)
                q = float((col_max > 18).mean())
            else:
                q = 0.0
            lead_qualities[lead_name] = round(q, 3)

    return RawTraces(
        row_traces_px=row_traces_px,
        rhythm_trace_px=rhythm_trace_px,
        row_bands=lead_bands,
        rhythm_band=rhythm_band,
        x_left=x_left,
        x_right=x_right,
        col_bounds=col_bounds,
        pulse_heights_px=pulse_heights,
        pulse_trim_ranges=pulse_trims,
        px_per_mm_x=round(px_per_mm_x, 4),
        px_per_mm_y=round(px_per_mm_y, 4),
        px_per_mm=round(0.5 * (px_per_mm_x + px_per_mm_y), 4),
        lead_qualities=lead_qualities,
    )


def _remove_baseline_drift_robust(sig_px: np.ndarray) -> np.ndarray:
    """Remove slow fold/paper baseline drift while preserving ST elevation/depression."""
    if len(sig_px) < 16:
        return sig_px
    # Use very wide low-order linear tilt fit ONLY if paper has gentle linear slant,
    # keeping constant baseline at histogram median of quiet segments
    x = np.arange(len(sig_px), dtype=np.float32)
    # Estimate baseline in left third & right third medians to remove pure linear tilt
    k = max(5, len(sig_px) // 4)
    y_l = float(np.median(sig_px[:k]))
    y_r = float(np.median(sig_px[-k:]))
    # Correct linear paper fold tilt up to 16px across a 2.5s cell using endpoint medians
    tilt = y_r - y_l
    if abs(tilt) <= 16.0:
        slope = tilt / max(1.0, float(len(sig_px) - k))
        corrected = sig_px - (y_l + slope * (x - k * 0.5))
    else:
        corrected = sig_px - float(np.median(sig_px))
    return corrected.astype(np.float32)


def _resample_to_len(sig: np.ndarray, out_len: int) -> np.ndarray:
    if len(sig) == out_len:
        return sig.astype(np.float32)
    if len(sig) < 2:
        return np.zeros(out_len, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, len(sig))
    x_new = np.linspace(0.0, 1.0, out_len)
    return np.interp(x_new, x_old, sig).astype(np.float32)


def _tile_smooth_to_5000(sig_25s: np.ndarray) -> np.ndarray:
    """Tile a 2.5s (1250 samples) lead trace to 10s (5000 samples) cleanly at quiet endpoints."""
    n = len(sig_25s)
    if n >= TARGET_LEN_10S:
        return sig_25s[:TARGET_LEN_10S].astype(np.float32)
    if n < 20:
        return np.zeros(TARGET_LEN_10S, dtype=np.float32)

    # Trim ends to near-isoelectric points to avoid step artifact at loop seam
    energy = np.abs(np.diff(sig_25s, prepend=sig_25s[0]))
    win = max(15, n // 12)
    left_idx = int(np.argmin(energy[:win]))
    right_idx = n - win + int(np.argmin(energy[-win:]))
    seg = sig_25s[left_idx:right_idx] if right_idx - left_idx >= n // 2 else sig_25s

    # Crossfade 20 samples at seam
    fade = min(20, len(seg) // 6)
    reps = int(np.ceil(TARGET_LEN_10S / float(max(1, len(seg) - fade))))
    out = seg.copy()
    for _ in range(reps):
        if len(out) >= TARGET_LEN_10S:
            break
        if fade > 2:
            w = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            seam = out[-fade:] * (1.0 - w) + seg[:fade] * w
            out = np.concatenate([out[:-fade], seam, seg[fade:]])
        else:
            out = np.concatenate([out, seg])
    return out[:TARGET_LEN_10S].astype(np.float32)


def apply_gains_and_build_signals(raw: RawTraces, ocr_res: OCRResult) -> DigitizedECG:
    """Calibrate pixel traces using OCR + calibration pulse gains and produce mV + 12x5000 tensor."""
    speed_scale = 25.0 / max(10.0, float(ocr_res.paper_speed_mm_s or 25.0))
    px_per_mm_x = raw.px_per_mm_x * (1.0 / speed_scale)  # at 50mm/s, 10s=500mm so px/mm halves

    # Combine OCR gains with physical square calibration pulse heights
    gains = dict(ocr_res.column_gains_mm_per_mv)
    col_keys = ["col1", "col2", "col3", "col4"]

    # Check if we have a reference column whose pulse height matches OCR gain (prefer >= 8 mm/mV pulses for accuracy)
    px_per_mm_candidates = []
    for idx, k in enumerate(col_keys):
        ph = raw.pulse_heights_px[idx]
        g_ocr = float(gains.get(k, 10.0))
        if ph is not None and ph > 3.0 and g_ocr >= 8.0:
            est = ph / g_ocr
            if 0.55 * px_per_mm_x <= est <= 1.25 * px_per_mm_x:
                px_per_mm_candidates.append(est)

    if px_per_mm_candidates:
        px_per_mm_y = float(np.median(px_per_mm_candidates))
    else:
        px_per_mm_y = px_per_mm_x

    # Use physical calibration pulse vertical scale px_per_mm_y for voltage conversion when available
    px_per_mm = px_per_mm_y

    # Cross-check each column gain against physical calibration pulse height
    # If OCR didn't explicitly see a box for col_c, or pulse clearly contradicts OCR (>35% off):
    gain_box_xs = [gb[0] for gb in ocr_res.gain_boxes]
    for idx, k in enumerate(col_keys):
        ph = raw.pulse_heights_px[idx]
        if ph is None or ph < 3.0:
            continue
        inferred_g = ph / max(0.5, px_per_mm)
        snapped = min(STANDARD_GAINS, key=lambda g: abs(g - inferred_g))
        # Check if OCR explicitly detected a gain label near this column
        col_mid = 0.5 * (raw.col_bounds[idx][0] + raw.col_bounds[idx][1])
        has_explicit_ocr = any(abs(gx - col_mid) <= 0.14 * (raw.x_right - raw.x_left) for gx in gain_box_xs)
        if not has_explicit_ocr and abs(snapped - inferred_g) <= 0.30 * snapped:
            gains[k] = float(snapped)

    leads_mv_raw: Dict[str, np.ndarray] = {}
    lead_preview: Dict[str, List[float]] = {}

    for r in range(3):
        trace_full = raw.row_traces_px[r]
        for c in range(4):
            lead_name = GRID_4X3[r][c]
            col_key = col_keys[c]
            gain_mm_mv = float(gains.get(col_key, 10.0))

            c0_rel = raw.col_bounds[c][0] - raw.x_left + raw.pulse_trim_ranges[c][0]
            c1_rel = raw.col_bounds[c][1] - raw.x_left - raw.pulse_trim_ranges[c][1]
            c0_rel = max(0, c0_rel)
            c1_rel = min(len(trace_full), c1_rel)
            if c1_rel <= c0_rel + 8:
                leads_mv_raw[lead_name] = np.zeros(TARGET_LEN_25S, dtype=np.float32)
                lead_preview[lead_name] = [0.0] * 120
                continue

            seg_px = trace_full[c0_rel:c1_rel]
            # Invert Y so upward = positive signal
            sig_up_px = -seg_px
            sig_detrended_px = _remove_baseline_drift_robust(sig_up_px)
            # Convert px -> mm -> mV
            sig_mv = sig_detrended_px / (px_per_mm * gain_mm_mv)
            sig_500 = _resample_to_len(sig_mv, TARGET_LEN_25S)
            leads_mv_raw[lead_name] = sig_500

            # Preview (125 points @ 50Hz for lightweight UI canvas)
            prev_pts = _resample_to_len(sig_500, 125)
            lead_preview[lead_name] = [round(float(v), 3) for v in prev_pts]

    rhythm_mv_raw: Optional[np.ndarray] = None
    if raw.rhythm_trace_px is not None and len(raw.rhythm_trace_px) > 20:
        r_trim_r = raw.pulse_trim_ranges[3][1]
        r_seg = raw.rhythm_trace_px[2 : max(10, len(raw.rhythm_trace_px) - r_trim_r)]
        r_gain = float(gains.get("rhythm", 10.0))
        r_detrend = _remove_baseline_drift_robust(-r_seg)
        r_mv = r_detrend / (px_per_mm * r_gain)
        rhythm_mv_raw = _resample_to_len(r_mv, TARGET_LEN_10S)

    # Build (12, 5000) tensor for ECGFounder
    tensor_rows: List[np.ndarray] = []
    for name in LEAD_NAMES:
        if name == "II" and rhythm_mv_raw is not None:
            tensor_rows.append(rhythm_mv_raw)
        else:
            tensor_rows.append(_tile_smooth_to_5000(leads_mv_raw[name]))
    tensor_12x5000 = np.stack(tensor_rows, axis=0).astype(np.float32)

    return DigitizedECG(
        leads_mv_raw=leads_mv_raw,
        rhythm_mv_raw=rhythm_mv_raw,
        tensor_12x5000=tensor_12x5000,
        digitized_preview=lead_preview,
        column_gains_mm_per_mv=gains,
        px_per_mm=round(px_per_mm, 4),
        lead_qualities=raw.lead_qualities,
    )


def digitize_12_leads(
    ink_map: np.ndarray,
    ink_map_raw: np.ndarray,
    ocr_res: OCRResult,
) -> DigitizedECG:
    raw = extract_raw_traces(ink_map, ink_map_raw)
    return apply_gains_and_build_signals(raw, ocr_res)

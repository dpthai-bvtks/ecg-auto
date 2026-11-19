"""RapidOCR wrapper and ECG machine measurement / gain / lead-label parser."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from rapidocr import RapidOCR

_ocr_lock = threading.Lock()
_ocr_engine: Optional[RapidOCR] = None

STANDARD_GAINS = [2.5, 5.0, 10.0, 20.0]


@dataclass
class TextBox:
    text: str
    score: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return 0.5 * (self.x1 + self.x2)

    @property
    def cy(self) -> float:
        return 0.5 * (self.y1 + self.y2)

    @property
    def height(self) -> float:
        return max(1.0, self.y2 - self.y1)


@dataclass
class OCRResult:
    hr: Optional[int] = None
    pr: Optional[int] = None
    qrs: Optional[int] = None
    qt: Optional[int] = None
    qtc: Optional[int] = None
    axis: Optional[int] = None
    axis_p: Optional[int] = None
    axis_t: Optional[int] = None
    sex: Optional[str] = None
    rv5_mv: Optional[float] = None
    sv1_mv: Optional[float] = None
    rv5_plus_sv1_mv: Optional[float] = None
    paper_speed_mm_s: float = 25.0
    column_gains_mm_per_mv: Dict[str, float] = field(
        default_factory=lambda: {"col1": 10.0, "col2": 10.0, "col3": 10.0, "col4": 10.0, "rhythm": 10.0}
    )
    gain_boxes: List[Tuple[float, float, float]] = field(default_factory=list)
    statements: List[str] = field(default_factory=list)
    raw_lines: List[str] = field(default_factory=list)
    wf_text_boxes: List[TextBox] = field(default_factory=list)


def get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_lock:
        if _ocr_engine is not None:
            return _ocr_engine
        _ocr_engine = RapidOCR(
            params={
                "Global.use_cls": False,
                "Global.log_level": "warning",
                "Det.limit_type": "max",
                "Det.limit_side_len": 800,
                "Rec.rec_batch_num": 8,
                "EngineConfig.onnxruntime.intra_op_num_threads": -1,
            }
        )
        return _ocr_engine


def warm_up_ocr() -> bool:
    """Warm up both detection and recognition ONNX sessions using synthetic black text."""
    eng = get_ocr_engine()
    warm = np.full((64, 240, 3), 255, dtype=np.uint8)
    cv2.putText(warm, "10 mm/mV 56 bpm", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    with _ocr_lock:
        eng(warm)
    return True


def _snap_gain(val: float) -> Optional[float]:
    if val <= 0:
        return None
    best = min(STANDARD_GAINS, key=lambda g: abs(g - val))
    if abs(best - val) <= 1.2 or val in {2.5, 5.0, 10.0, 20.0}:
        return best
    return None


def _run_ocr_on_crop(
    img: np.ndarray,
    target_min_h: int = 160,
    fixed_scale: Optional[float] = None,
    max_scale: float = 1.65,
) -> List[TextBox]:
    if img is None or img.size == 0:
        return []
    h, _w = img.shape[:2]
    if fixed_scale is not None:
        scale = float(fixed_scale)
    else:
        scale = 1.0
        if h < target_min_h:
            scale = min(max_scale, max(1.25, target_min_h / float(max(1, h))))

    inp = (
        cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        if abs(scale - 1.0) > 0.05
        else img
    )
    eng = get_ocr_engine()
    with _ocr_lock:
        res = eng(inp)

    boxes = getattr(res, "boxes", None)
    txts = getattr(res, "txts", None)
    scores = getattr(res, "scores", None)
    out: List[TextBox] = []
    if txts is None or boxes is None:
        return out
    if scores is None:
        scores = [1.0] * len(txts)

    for b, t, s in zip(boxes, txts, scores):
        xs = [float(p[0]) / scale for p in b]
        ys = [float(p[1]) / scale for p in b]
        out.append(
            TextBox(
                text=str(t).strip(),
                score=float(s),
                x1=min(xs),
                y1=min(ys),
                x2=max(xs),
                y2=max(ys),
            )
        )
    return out


def _group_boxes_into_rows(boxes: List[TextBox], y_tol: Optional[float] = None) -> List[List[TextBox]]:
    if not boxes:
        return []
    if y_tol is None:
        med_h = float(np.median([b.height for b in boxes]))
        y_tol = max(3.2, min(8.0, med_h * 0.42))

    sorted_boxes = sorted(boxes, key=lambda b: (b.cy, b.x1))
    rows: List[List[TextBox]] = []
    for b in sorted_boxes:
        if not rows or abs(b.cy - float(np.mean([x.cy for x in rows[-1]]))) > y_tol:
            rows.append([b])
        else:
            rows[-1].append(b)
    for r in rows:
        r.sort(key=lambda b: b.x1)
    return rows


def _extract_gain_matches(text: str, x1: float, x2: float, cy: float) -> List[Tuple[float, float, float]]:
    """Extract (cx, cy, gain_mm_per_mv) occurrences from an OCR string."""
    found: List[Tuple[float, float, float]] = []
    pattern = re.compile(
        r"(2\.5|10|20|5)\s*(?:mm|um|un|u|m|rn)?\s*/\s*(?:mv|av|nv|v|a|\)|[a-z]{0,2})",
        re.IGNORECASE,
    )
    width = max(1.0, x2 - x1)
    tlen = max(1, len(text))
    for m in pattern.finditer(text):
        snippet = m.group(0).lower()
        if "/s" in snippet or "hz" in snippet:
            continue
        raw_num = m.group(1)
        after = text[m.end(1) : min(len(text), m.end(1) + 9)].lower()
        if "/" not in after and "mv" not in after and "av" not in after and "nv" not in after:
            continue
        if "/s" in after or "ax/s" in after or "mm/s" in after:
            continue
        g = _snap_gain(float(raw_num))
        if g is None:
            continue
        rel = (m.start() + m.end()) * 0.5 / float(tlen)
        cx = x1 + rel * width
        found.append((cx, cy, g))
    return found


def _parse_report_rows(rows: List[List[TextBox]], result: OCRResult) -> None:
    lines = [" ".join(b.text for b in r) for r in rows]
    result.raw_lines.extend(lines)
    full_text = "\n".join(lines)

    # Sex
    if re.search(r"\b(?:female|nữ)\b", full_text, re.I):
        result.sex = "nu"
    elif re.search(r"\b(?:male|nam|sex\s*:\s*[mn]a[lt]e)\b", full_text, re.I):
        result.sex = "nam"

    for r_boxes, line in zip(rows, lines):
        low = line.lower()

        # Vent. rate / HR
        if result.hr is None and (
            re.search(r"(?:vent|veat|heart)\s*\.?\s*rate|\bhr\b", low) or "bpm" in low or "bpa" in low
        ):
            m_kw = re.search(r"(?:(?:vent|veat|heart)\s*\.?\s*rate|\bhr)\s*[:=]?\s*(\d{2,3})\b|\b(\d{2,3})\s*(?:bpm|bpa)\b", low)
            if m_kw:
                val = int(m_kw.group(1) or m_kw.group(2))
                if 20 <= val <= 280:
                    result.hr = val
            else:
                for b in r_boxes:
                    m = re.search(r"\b(\d{2,3})\b", b.text)
                    if m and 20 <= int(m.group(1)) <= 280:
                        result.hr = int(m.group(1))
                        break

        # PR / PQ (match directly after PR/PQ keyword first so single-line headers never grab HR)
        if result.pr is None and re.search(r"\b(?:pr|pq|ph)\s*(?:int|interval)?\b", low):
            m_kw = re.search(r"\b(?:pr|pq|ph)\s*(?:int|interval)?\s*[:=]?\s*(\d{2,3})(?=\D|$)", low)
            if m_kw and 50 <= int(m_kw.group(1)) <= 600:
                result.pr = int(m_kw.group(1))
            elif len(r_boxes) <= 4:
                kw_pat = re.compile(r"\b(?:pr|pq|ph)\s*(?:int|interval)?\b")
                kw_box = next((b for b in r_boxes if kw_pat.search(b.text.lower())), None)
                for b in r_boxes:
                    if kw_box is not None and b.x2 < kw_box.x1:
                        continue
                    txt = b.text
                    if b is kw_box:
                        km = kw_pat.search(txt.lower())
                        txt = txt[km.end():] if km else ""
                    m = re.search(r"(?<!\d)(\d{2,3})(?!\d)", txt)
                    if m and 50 <= int(m.group(1)) <= 600:
                        result.pr = int(m.group(1))
                        break

        # QRS dur (match directly after QRS keyword first; otherwise first valid number on short table row)
        if result.qrs is None and re.search(r"\b(?:qrs|qns|ons)\s*(?:dur|d[uo]r)?\b", low):
            m_kw = re.search(r"\b(?:qrs|qns|ons)\s*(?:dur|d[uo]r)?\s*[:=]?\s*(\d{2,3})(?=\D|$)", low)
            if m_kw and 40 <= int(m_kw.group(1)) <= 280:
                result.qrs = int(m_kw.group(1))
            elif len(r_boxes) <= 4:
                kw_pat = re.compile(r"\b(?:qrs|qns|ons)\s*(?:dur|d[uo]r)?\b")
                kw_box = next((b for b in r_boxes if kw_pat.search(b.text.lower())), None)
                for b in r_boxes:
                    if kw_box is not None and b.x2 < kw_box.x1:
                        continue
                    txt = b.text
                    if b is kw_box:
                        km = kw_pat.search(txt.lower())
                        txt = txt[km.end():] if km else ""
                    m = re.search(r"(?<!\d)(\d{2,3})(?!\d)", txt)
                    if m and 40 <= int(m.group(1)) <= 280:
                        result.qrs = int(m.group(1))
                        break

        # QT / QTc (handles '454/445' or split '454/' + '445')
        if result.qt is None and re.search(r"\bqt\s*/\s*qt[ce]|\bqt[ce]?\s*(?:int|lat|lnt)?\b", low):
            m = re.search(r"\b(\d{3})\s*[/\\]\s*(\d{3})\b", line)
            if m:
                qt_v, qtc_v = int(m.group(1)), int(m.group(2))
                if 200 <= qt_v <= 750:
                    result.qt = qt_v
                if 250 <= qtc_v <= 750:
                    result.qtc = qtc_v
            else:
                m_kw = re.search(r"\bqt[ce]?\s*(?:int|lat|lnt)?\s*[:=]?\s*(\d{3})\b", low)
                if m_kw and 200 <= int(m_kw.group(1)) <= 750:
                    result.qt = int(m_kw.group(1))
                else:
                    nums = [int(x) for x in re.findall(r"\b(\d{3})\b", line) if 200 <= int(x) <= 750]
                    if nums:
                        result.qt = nums[0]
                        if len(nums) >= 2:
                            result.qtc = nums[1]

        # P/QRS/T axis (match directly after 'axis'/'axes' keyword)
        if result.axis is None and re.search(r"axis|axes", low):
            m3 = re.search(r"(-?\d{1,3})\s*[/\\ ]\s*(-?\d{1,3})\s*[/\\]\s*(-?\d{1,3})", line)
            if m3:
                p_ax, qrs_ax, t_ax = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
                if -180 <= qrs_ax <= 180:
                    result.axis_p = p_ax
                    result.axis = qrs_ax
                    result.axis_t = t_ax
            else:
                m2 = re.search(r"(-?\d{1,3})\s*[/\\]\s*(-?\d{1,3})", line)
                if m2 and -180 <= int(m2.group(1)) <= 180:
                    result.axis = int(m2.group(1))
                else:
                    m_kw = re.search(r"(?:axis|axes)\s*[:=]?\s*(-?\d{1,3})\b", low)
                    if m_kw and -180 <= int(m_kw.group(1)) <= 180:
                        result.axis = int(m_kw.group(1))

        # RV5 / SV1 amplitude
        if "rv5" in low or "sv1" in low:
            m_pair = re.search(r"(\d+\.\d{2,3})\s*[/\\]\s*(\d+\.\d{2,3})", line)
            if m_pair:
                result.rv5_mv = float(m_pair.group(1))
                result.sv1_mv = float(m_pair.group(2))
            else:
                m_sum = re.search(r"\b(\d+\.\d{2,3})\b", line)
                if m_sum and "+" in low:
                    result.rv5_plus_sv1_mv = float(m_sum.group(1))

        # Machine printed statement lines if present
        if re.match(r"^\s*\d{4}\b", line) or any(
            kw in low
            for kw in (
                "rhythm", "rhyth", "block", "infarct", "injury", "ischemi",
                "depression", "elevation", "abnormal", "normal", "delay",
                "hypertrophy", "fibrillation", "flutter", "tachy", "brady",
            )
        ):
            result.statements.append(line.strip())


def parse_ecg_ocr(
    paper_img: np.ndarray,
    waveform_img: np.ndarray,
    report_img: Optional[np.ndarray],
) -> OCRResult:
    """Fast ROI-focused RapidOCR extraction for machine measurements, gains, and waveform header."""
    result = OCRResult()
    wh, ww = waveform_img.shape[:2]

    if report_img is not None:
        rh, rw = report_img.shape[:2]
        # Compact gain-only strip on waveform_img (y=11%..21%) + numeric report block (y=12%..56%)
        wf_y0, wf_y1 = int(0.11 * wh), int(0.21 * wh)
        rep_y0, rep_y1 = int(0.12 * rh), int(0.56 * rh)
        rep_x1 = int(0.76 * rw)

        g_strip = waveform_img[wf_y0:wf_y1, :]
        num_rep = report_img[rep_y0:rep_y1, :rep_x1]

        sc_wf = 1.45 if (wf_y1 - wf_y0) < 60 else 1.0
        sc_rep = 1.6 if (rep_y1 - rep_y0) < 220 else 1.0

        wf_boxes = _run_ocr_on_crop(g_strip, fixed_scale=sc_wf)
        rep_boxes = _run_ocr_on_crop(num_rep, fixed_scale=sc_rep)

        for b in wf_boxes:
            b.y1 += wf_y0
            b.y2 += wf_y0
        for b in rep_boxes:
            b.y1 += rep_y0
            b.y2 += rep_y0

        result.wf_text_boxes = wf_boxes
        _parse_report_rows(_group_boxes_into_rows(rep_boxes), result)

        # Fallback to wider report crop only if key intervals weren't found
        if result.hr is None and result.pr is None and result.qrs is None:
            fb_y0, fb_y1 = int(0.06 * rh), int(0.84 * rh)
            fb_boxes = _run_ocr_on_crop(report_img[fb_y0:fb_y1, :], target_min_h=280, max_scale=1.5)
            for b in fb_boxes:
                b.y1 += fb_y0
                b.y2 += fb_y0
            _parse_report_rows(_group_boxes_into_rows(fb_boxes), result)
    else:
        # Single-sheet ECG: header is at top ~24%
        wf_y0, wf_y1 = int(0.03 * wh), int(0.24 * wh)
        wf_header = waveform_img[wf_y0:wf_y1, :]
        wf_boxes = _run_ocr_on_crop(wf_header, target_min_h=140, max_scale=1.65)
        for b in wf_boxes:
            b.y1 += wf_y0
            b.y2 += wf_y0
        result.wf_text_boxes = wf_boxes
        _parse_report_rows(_group_boxes_into_rows(wf_boxes), result)

    # Parse gain, paper speed, HR, sex from waveform header boxes
    wf_rows = _group_boxes_into_rows(result.wf_text_boxes)
    for line_boxes in wf_rows:
        line_str = " ".join(b.text for b in line_boxes)
        result.raw_lines.append("[WF] " + line_str)
        low = line_str.lower()

        if result.hr is None:
            m_hr = re.search(r"\b(\d{2,3})\s*(?:bpm|bpa|bp)\b", low)
            if m_hr and 20 <= int(m_hr.group(1)) <= 280:
                result.hr = int(m_hr.group(1))

        if result.sex is None:
            if re.search(r"\bfemale\b|\bnữ\b", low):
                result.sex = "nu"
            elif re.search(r"\bmale\b|\bnam\b", low):
                result.sex = "nam"

        if "50" in low and ("/s" in low or "mm/s" in low):
            if re.search(r"\b50\s*(?:mm|ax|am|m)?\s*/\s*s\b", low):
                result.paper_speed_mm_s = 50.0

        for b in line_boxes:
            result.gain_boxes.extend(_extract_gain_matches(b.text, b.x1, b.x2, b.cy))

    if result.gain_boxes:
        sorted_g = sorted(result.gain_boxes, key=lambda g: g[0])
        col_centers = [0.15 * ww, 0.38 * ww, 0.62 * ww, 0.85 * ww]
        col_keys = ["col1", "col2", "col3", "col4"]
        assigned: Dict[str, Optional[float]] = {k: None for k in col_keys}
        for cx, _cy, g in sorted_g:
            best_idx = int(np.argmin([abs(cx - cc) for cc in col_centers]))
            if abs(cx - col_centers[best_idx]) <= 0.22 * ww:
                assigned[col_keys[best_idx]] = g

        last_g = 10.0
        for k in col_keys:
            if assigned[k] is not None:
                last_g = float(assigned[k])
            result.column_gains_mm_per_mv[k] = last_g

    return result

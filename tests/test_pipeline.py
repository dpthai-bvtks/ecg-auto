"""End-to-end verification tests for PM-ECG Hybrid Pipeline (Real photo + Synthetic Normal + Digital JSON)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.pipeline import GRID_4X3, LEAD_NAMES
from backend.pipeline.clinical_fusion import fuse_clinical_diagnosis
from backend.pipeline.digital_input import parse_digital_ecg
from backend.pipeline.digitizer import apply_gains_and_build_signals, extract_raw_traces
from backend.pipeline.ecgfounder_infer import run_ecgfounder, warm_up_ecgfounder
from backend.pipeline.ocr_parser import OCRResult, parse_ecg_ocr, warm_up_ocr
from backend.pipeline.preprocessor import preprocess_ecg_image
from backend.pipeline.signal_metrics import evaluate_signal_metrics

REAL_ECG_PATH = Path(
    r"C:\Users\Administrator\.gemini\antigravity\brain\3b32d419-bfdf-4d0a-89c3-924c960573c2\.user_uploaded\media_1795045851378_d85b42bd.jpg"
)


def _generate_normal_beat(t_ms: np.ndarray, amp_r: float = 1.0, amp_t: float = 0.25) -> np.ndarray:
    """Create a realistic synthetic normal P-QRS-T complex centered at t_ms=0 (in mV)."""
    # P wave at -160ms, R at 0ms, S at +22ms, flat ST (0 mV), T wave at +220ms
    p = 0.10 * np.exp(-0.5 * ((t_ms + 160.0) / 22.0) ** 2)
    q = -0.06 * amp_r * np.exp(-0.5 * ((t_ms + 20.0) / 7.0) ** 2)
    r = amp_r * np.exp(-0.5 * (t_ms / 11.0) ** 2)
    s = -0.22 * amp_r * np.exp(-0.5 * ((t_ms - 24.0) / 9.0) ** 2)
    t = amp_t * np.exp(-0.5 * ((t_ms - 220.0) / 42.0) ** 2)
    return (p + q + r + s + t).astype(np.float32)


def _build_synthetic_normal_signals(hr: int = 72, duration_s: float = 10.0, fs: int = 500) -> dict:
    """Generate clean 12-lead normal sinus signals @ 500 Hz in mV."""
    n = int(round(duration_s * fs))
    t = np.arange(n, dtype=np.float32) * (1000.0 / fs)
    rr_ms = 60000.0 / hr
    beat_centers = np.arange(350.0, duration_s * 1000.0 - 200.0, rr_ms)

    lead_amps = {
        "I": (0.8, 0.20),
        "II": (1.2, 0.30),
        "III": (0.4, 0.10),
        "aVR": (-0.9, -0.22),
        "aVL": (0.3, 0.08),
        "aVF": (0.8, 0.20),
        "V1": (-0.7, -0.05),
        "V2": (0.5, 0.25),
        "V3": (1.0, 0.30),
        "V4": (1.4, 0.35),
        "V5": (1.3, 0.30),
        "V6": (1.0, 0.25),
    }

    out = {}
    for ln, (ar, at) in lead_amps.items():
        sig = np.zeros(n, dtype=np.float32)
        for c in beat_centers:
            sig += _generate_normal_beat(t - c, amp_r=ar, amp_t=at)
        out[ln] = sig
    return out


def _render_synthetic_normal_ecg_image() -> bytes:
    """Render a realistic 4x3 + rhythm strip normal sinus ECG printout with pink grid & header."""
    w, h = 1100, 760
    img = np.full((h, w, 3), 248, dtype=np.uint8)
    # Pink ECG grid (2.5 px/mm -> 1mm=2.5px, 5mm=12.5px)
    px_per_mm = 2.5
    for x in range(40, w - 30, 12):
        cv2.line(img, (x, 120), (x, h - 40), (220, 215, 245), 1)
    for y in range(120, h - 40, 12):
        cv2.line(img, (40, y), (w - 30, y), (220, 215, 245), 1)

    # Machine printed header
    cv2.putText(img, "Sex: Male   Vent. rate: 72 bpm   PR: 160 ms   QRS: 84 ms   QT/QTc: 380/416 ms   Axis: 45", (50, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.putText(img, "10 mm/mV   25 mm/s", (50, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)

    sigs = _build_synthetic_normal_signals(hr=72, duration_s=10.0, fs=500)
    x_left, x_right = 80, 1020
    span_w = x_right - x_left
    col_w = span_w / 4.0
    row_ys = [210, 340, 470]
    rhythm_y = 620

    for r in range(3):
        for c in range(4):
            ln = GRID_4X3[r][c]
            seg = sigs[ln][:1250]  # 2.5s
            x0 = int(x_left + c * col_w)
            x1 = int(x_left + (c + 1) * col_w) - 16
            xs = np.linspace(x0, x1, len(seg)).astype(np.int32)
            ys = np.clip(np.round(row_ys[r] - seg * 10.0 * px_per_mm), 0, h - 1).astype(np.int32)
            pts = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, (18, 18, 18), 2, cv2.LINE_AA)
            # Calibration pulse at right end of column
            px0 = x1 + 2
            py_base = row_ys[r]
            py_top = int(round(py_base - 10.0 * px_per_mm))
            cal = np.array([[px0, py_base], [px0 + 2, py_base], [px0 + 2, py_top], [px0 + 10, py_top], [px0 + 10, py_base], [px0 + 13, py_base]], dtype=np.int32)
            cv2.polylines(img, [cal.reshape(-1, 1, 2)], False, (18, 18, 18), 2)

    # Rhythm strip Lead II (10s)
    r_seg = sigs["II"]
    xs_r = np.linspace(x_left, x_right - 16, len(r_seg)).astype(np.int32)
    ys_r = np.clip(np.round(rhythm_y - r_seg * 10.0 * px_per_mm), 0, h - 1).astype(np.int32)
    cv2.polylines(img, [np.stack([xs_r, ys_r], axis=1).reshape(-1, 1, 2)], False, (18, 18, 18), 2, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert ok
    return buf.tobytes()


async def run_tests() -> None:
    print("Warming up RapidOCR + ECGFounder ONNX...", flush=True)
    warm_up_ocr()
    warm_up_ecgfounder()

    # ---------------------------------------------------------
    # TEST 1: REAL USER PHOTO (INFERIOR STEMI + GAIN 2.5 / 5.0)
    # ---------------------------------------------------------
    assert REAL_ECG_PATH.exists(), f"Missing sample photo: {REAL_ECG_PATH}"
    raw_bytes = REAL_ECG_PATH.read_bytes()

    t0 = time.perf_counter()
    prep = preprocess_ecg_image(raw_bytes)
    raw_tr = extract_raw_traces(prep.ink_map, prep.ink_map_raw)
    ocr_res = parse_ecg_ocr(prep.paper_img, prep.waveform_img, prep.report_img)
    dig = apply_gains_and_build_signals(raw_tr, ocr_res)
    metrics = evaluate_signal_metrics(
        dig.leads_mv_raw, dig.rhythm_mv_raw, ocr_res, dig.column_gains_mm_per_mv, dig.lead_qualities
    )
    t_ef0 = time.perf_counter()
    ef = run_ecgfounder(dig.tensor_12x5000)
    ef_ms = (time.perf_counter() - t_ef0) * 1000.0
    fused_offline, meta_offline = await fuse_clinical_diagnosis(
        ocr_res=ocr_res,
        metrics=metrics,
        ecgfounder_res=ef,
        clinical_context="Đau ngực trái dữ dội < 2h, vã mồ hôi",
        mode="offline",
    )
    total_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[TEST 1 - REAL PHOTO] total={total_ms:.0f}ms, ef={ef_ms:.0f}ms")
    print("  OCR:", ocr_res.hr, ocr_res.pr, ocr_res.qrs, ocr_res.qt, ocr_res.qtc, ocr_res.axis, ocr_res.sex, dig.column_gains_mm_per_mv)
    print("  ST (II,III,aVF,I,aVL,V1,V2,V3):", {k: round(metrics.lead_measurements[k].st_mm, 2) for k in ["II","III","aVF","I","aVL","V1","V2","V3"]})
    print("  Primary:", fused_offline["clinical_diagnosis"]["primary"])

    assert prep.has_right_report_panel is True
    assert ocr_res.hr == 56
    assert ocr_res.pr == 210
    assert ocr_res.qrs == 112
    assert ocr_res.qt == 454
    assert ocr_res.qtc == 445
    assert ocr_res.axis == 43
    assert ocr_res.sex == "nam"
    assert dig.column_gains_mm_per_mv["col3"] == 2.5
    assert dig.column_gains_mm_per_mv["col4"] == 5.0

    # Inferior STEMI & reciprocal high lateral & posterior depression
    assert metrics.lead_measurements["II"].st_mm >= 1.0
    assert metrics.lead_measurements["III"].st_mm >= 1.5
    assert metrics.lead_measurements["aVF"].st_mm >= 1.5
    assert metrics.lead_measurements["aVL"].st_mm <= -1.0
    assert metrics.lead_measurements["V2"].st_mm <= -0.8
    assert metrics.lead_measurements["V3"].st_mm <= -1.0

    # ECGFounder sanity
    assert ef["loaded"] is True
    assert ef_ms < 1000.0
    assert all(not np.isnan(v) for v in ef["all_probs"].values())
    assert ef["superclasses"]["MI"] >= 0.70

    # Diagnosis & treatment assertions
    prim_low = fused_offline["clinical_diagnosis"]["primary"].lower()
    assert ("stemi" in prim_low or "nhồi máu cơ tim cấp" in prim_low) and "thành dưới" in prim_low
    assert fused_offline["clinical_diagnosis"]["risk_level"] == "Nguy cơ rất cao"
    assert fused_offline["regions"]["inf"]["st"] == "elevation"
    plan_txt = json.dumps(fused_offline["treatment_plan"], ensure_ascii=False).lower()
    assert "pci" in plan_txt and "v3r" in plan_txt and "nitroglycerin" in plan_txt
    assert total_ms < 6000.0, f"Pipeline too slow: {total_ms:.0f}ms"
    print("  [PASS] Test 1 passed!")

    # ---------------------------------------------------------
    # TEST 2: SYNTHETIC NORMAL SINUS ECG IMAGE (NO FALSE STEMI)
    # ---------------------------------------------------------
    norm_jpg = _render_synthetic_normal_ecg_image()
    t1 = time.perf_counter()
    prep2 = preprocess_ecg_image(norm_jpg)
    raw_tr2 = extract_raw_traces(prep2.ink_map, prep2.ink_map_raw)
    ocr_res2 = parse_ecg_ocr(prep2.paper_img, prep2.waveform_img, prep2.report_img)
    dig2 = apply_gains_and_build_signals(raw_tr2, ocr_res2)
    metrics2 = evaluate_signal_metrics(
        dig2.leads_mv_raw, dig2.rhythm_mv_raw, ocr_res2, dig2.column_gains_mm_per_mv, dig2.lead_qualities
    )
    ef2 = run_ecgfounder(dig2.tensor_12x5000)
    fused2, _ = await fuse_clinical_diagnosis(
        ocr_res=ocr_res2, metrics=metrics2, ecgfounder_res=ef2, clinical_context="", mode="offline"
    )
    t2_ms = (time.perf_counter() - t1) * 1000.0
    print(f"\n[TEST 2 - SYNTHETIC NORMAL] total={t2_ms:.0f}ms")
    print("  ST (II,III,aVF,V2,V3):", {k: round(metrics2.lead_measurements[k].st_mm, 2) for k in ["II","III","aVF","V2","V3"]})
    print("  Primary:", fused2["clinical_diagnosis"]["primary"], "| Risk:", fused2["clinical_diagnosis"]["risk_level"])

    assert fused2["clinical_diagnosis"]["risk_level"] == "Nguy cơ thấp"
    for rk in ("inf", "sept", "ant", "lat"):
        assert fused2["regions"][rk]["st"] == "none", f"False ST in {rk}: {fused2['regions']}"
    assert "nhồi máu" not in fused2["clinical_diagnosis"]["primary"].lower()
    print("  [PASS] Test 2 passed!")

    # ---------------------------------------------------------
    # TEST 3: DIGITAL 12-LEAD JSON INPUT
    # ---------------------------------------------------------
    dig_sigs = _build_synthetic_normal_signals(hr=72, duration_s=10.0, fs=500)
    payload_json = json.dumps(
        {
            "fs": 500,
            "hr": 72,
            "pr": 160,
            "qrs": 84,
            "qt": 380,
            "axis": 45,
            "sex": "nam",
            "leads": {k: v.tolist() for k, v in dig_sigs.items()},
        }
    ).encode("utf-8")

    t3 = time.perf_counter()
    parsed_dig = parse_digital_ecg(payload_json, "sample_normal.json")
    ocr3 = OCRResult(hr=72, pr=160, qrs=84, qt=380, axis=45, sex="nam")
    gains3 = {"col1": 10.0, "col2": 10.0, "col3": 10.0, "col4": 10.0, "rhythm": 10.0}
    metrics3 = evaluate_signal_metrics(parsed_dig.leads_mv, parsed_dig.tensor_12x5000[1], ocr3, gains3)
    ef3 = run_ecgfounder(parsed_dig.tensor_12x5000)
    fused3, _ = await fuse_clinical_diagnosis(ocr_res=ocr3, metrics=metrics3, ecgfounder_res=ef3, mode="offline")
    t3_ms = (time.perf_counter() - t3) * 1000.0
    print(f"\n[TEST 3 - DIGITAL JSON] total={t3_ms:.0f}ms")
    print("  Primary:", fused3["clinical_diagnosis"]["primary"], "| Risk:", fused3["clinical_diagnosis"]["risk_level"])

    assert t3_ms < 1000.0
    assert fused3["clinical_diagnosis"]["risk_level"] == "Nguy cơ thấp"
    assert fused3["hr"] == 72
    print("  [PASS] Test 3 passed!")
    print("\nALL PIPELINE TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_tests())

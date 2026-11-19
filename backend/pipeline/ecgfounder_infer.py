"""ECGFounder-all71 ONNX Inference (Pure NumPy + ONNXRuntime, no scipy)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import onnxruntime as ort

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
ONNX_PATH = MODELS_DIR / "ecg_founder_all71.onnx"
LABELS_PATH = MODELS_DIR / "labels_all71.json"

# Mapping 71 SCP-ECG classes (PTB-XL) -> Vietnamese clinical labels & 5 PTB-XL superclasses
SCP_INFO: Dict[str, tuple[str, str]] = {
    "1AVB": ("Block nhĩ – thất độ I", "CD"),
    "2AVB": ("Block nhĩ – thất độ II", "CD"),
    "3AVB": ("Block nhĩ – thất độ III (phân ly nhĩ thất)", "CD"),
    "ABQRS": ("Phức bộ QRS bất thường", "STTC"),
    "AFIB": ("Rung nhĩ (Atrial Fibrillation)", "CD"),
    "AFLT": ("Cuồng nhĩ (Atrial Flutter)", "CD"),
    "ALMI": ("Nhồi máu cơ tim trước – bên (Anterolateral MI)", "MI"),
    "AMI": ("Nhồi máu cơ tim thành trước (Anterior MI)", "MI"),
    "ANEUR": ("Phình thành thất sau nhồi máu", "STTC"),
    "ASMI": ("Nhồi máu cơ tim trước – vách (Anteroseptal MI)", "MI"),
    "BIGU": ("Nhịp đôi (Bigeminy)", "CD"),
    "CLBBB": ("Block nhánh trái hoàn toàn (Complete LBBB)", "CD"),
    "CRBBB": ("Block nhánh phải hoàn toàn (Complete RBBB)", "CD"),
    "DIG": ("Dấu hiệu ngấm Digitalis / Digoxin", "STTC"),
    "EL": ("Bất thường điện giải", "STTC"),
    "HVOLT": ("Điện thế QRS cao", "HYP"),
    "ILBBB": ("Block nhánh trái không hoàn toàn", "CD"),
    "ILMI": ("Nhồi máu cơ tim dưới – bên (Inferolateral MI)", "MI"),
    "IMI": ("Nhồi máu cơ tim thành dưới (Inferior MI)", "MI"),
    "INJAL": ("Tổn thương cơ tim trước – bên (ST chênh vùng trước bên)", "MI"),
    "INJAS": ("Tổn thương cơ tim trước – vách (ST chênh vùng V1–V3)", "MI"),
    "INJIL": ("Tổn thương cơ tim dưới – bên (ST chênh II, III, aVF, V5–V6)", "MI"),
    "INJIN": ("Tổn thương cơ tim thành dưới cấp (Inferior injury / STEMI thành dưới)", "MI"),
    "INJLA": ("Tổn thương cơ tim thành bên (Lateral injury)", "MI"),
    "INVT": ("Sóng T đảo ngược âm", "STTC"),
    "IPLMI": ("Nhồi máu cơ tim dưới – sau – bên", "MI"),
    "IPMI": ("Nhồi máu cơ tim dưới – thành sau (Inferoposterior MI)", "MI"),
    "IRBBB": ("Block nhánh phải không hoàn toàn", "CD"),
    "ISCAL": ("Thiếu máu cơ tim trước – bên", "STTC"),
    "ISCAN": ("Thiếu máu cơ tim thành trước", "STTC"),
    "ISCAS": ("Thiếu máu cơ tim trước – vách", "STTC"),
    "ISCIL": ("Thiếu máu cơ tim dưới – bên", "STTC"),
    "ISCIN": ("Thiếu máu cơ tim thành dưới", "STTC"),
    "ISCLA": ("Thiếu máu cơ tim thành bên", "STTC"),
    "ISC_": ("Biến đổi thiếu máu cơ tim (ST-T)", "STTC"),
    "IVCD": ("Rối loạn dẫn truyền trong thất không đặc hiệu", "CD"),
    "LAFB": ("Block phân nhánh trái trước (LAFB)", "CD"),
    "LAO/LAE": ("Lớn nhĩ trái (LAE)", "HYP"),
    "LMI": ("Nhồi máu cơ tim thành bên (Lateral MI)", "MI"),
    "LNGQT": ("Khoảng QT kéo dài", "STTC"),
    "LOWT": ("Sóng T dẹt / biên độ thấp", "STTC"),
    "LPFB": ("Block phân nhánh trái sau (LPFB)", "CD"),
    "LPR": ("Khoảng PR ngắn", "CD"),
    "LVH": ("Dày thất trái (LVH)", "HYP"),
    "LVOLT": ("Điện thế ngoại biên thấp", "STTC"),
    "NDT": ("Biến đổi sóng T không đặc hiệu", "STTC"),
    "NORM": ("Điện tâm đồ bình thường (Normal ECG)", "NORM"),
    "NST_": ("Biến đổi đoạn ST không đặc hiệu", "STTC"),
    "NT_": ("Biến đổi sóng T không đặc hiệu", "STTC"),
    "PAC": ("Ngoại tâm thu nhĩ (PAC)", "CD"),
    "PACE": ("Nhịp máy tạo nhịp (Pacemaker)", "CD"),
    "PMI": ("Nhồi máu cơ tim thành sau (Posterior MI)", "MI"),
    "PRC(S)": ("Ngoại tâm thu trên thất", "CD"),
    "PSVT": ("Nhịp nhanh kịch phát trên thất (PSVT)", "CD"),
    "PVC": ("Ngoại tâm thu thất (PVC)", "CD"),
    "QWAVE": ("Sóng Q bệnh lý", "MI"),
    "RAO/RAE": ("Lớn nhĩ phải (RAE)", "HYP"),
    "RVH": ("Dày thất phải (RVH)", "HYP"),
    "SARRH": ("Loạn nhịp xoang", "NORM"),
    "SBRAD": ("Nhịp chậm xoang", "NORM"),
    "SEHYP": ("Phì đại vách liên thất", "HYP"),
    "SR": ("Nhịp xoang (Sinus Rhythm)", "NORM"),
    "STACH": ("Nhịp nhanh xoang", "NORM"),
    "STD_": ("ST chênh xuống", "STTC"),
    "STE_": ("ST chênh lên", "STTC"),
    "SVARR": ("Loạn nhịp trên thất", "CD"),
    "SVTAC": ("Nhịp nhanh trên thất", "CD"),
    "TAB_": ("Sóng T bất thường", "STTC"),
    "TRIGU": ("Nhịp ba (Trigeminy)", "CD"),
    "VCLVH": ("Tiêu chuẩn điện thế dày thất trái", "HYP"),
    "WPW": ("Hội chứng Wolff–Parkinson–White (WPW)", "CD"),
}

_lock = threading.Lock()
_session: Optional[ort.InferenceSession] = None
_labels: Optional[List[str]] = None
_load_error: Optional[str] = None


def _load_model() -> tuple[Optional[ort.InferenceSession], List[str], Optional[str]]:
    global _session, _labels, _load_error
    if _session is not None and _labels is not None:
        return _session, _labels, None

    with _lock:
        if _session is not None and _labels is not None:
            return _session, _labels, None
        if not ONNX_PATH.exists():
            _load_error = f"Chua co file model ONNX: {ONNX_PATH}"
            return None, [], _load_error
        if not LABELS_PATH.exists():
            _load_error = f"Chua co file labels: {LABELS_PATH}"
            return None, [], _load_error

        try:
            with open(LABELS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            labels = list(data["labels"])

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            sess = ort.InferenceSession(
                str(ONNX_PATH),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            _session = sess
            _labels = labels
            _load_error = None
            return _session, _labels, None
        except Exception as exc:
            _load_error = str(exc)
            return None, [], _load_error


def warm_up_ecgfounder() -> bool:
    sess, _, _ = _load_model()
    if sess is None:
        return False
    dummy = np.zeros((1, 12, 5000), dtype=np.float32)
    input_name = sess.get_inputs()[0].name
    sess.run(None, {input_name: dummy})
    return True


def is_ecgfounder_loaded() -> bool:
    return _session is not None or ONNX_PATH.exists()


def bandpass_zero_phase_fft(
    x: np.ndarray,
    fs: float = 500.0,
    low_hz: float = 0.5,
    high_hz: float = 50.0,
) -> np.ndarray:
    """Pure NumPy smooth zero-phase FFT bandpass filter matching 0.5-50 Hz contract."""
    n = x.shape[-1]
    if n < 16:
        return x.astype(np.float32)

    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    mask = np.ones_like(freqs, dtype=np.float32)

    # Smooth raised-cosine high-pass transition around 0.5 Hz (0.2..0.8 Hz)
    hp_lo = max(0.05, low_hz * 0.4)
    hp_hi = low_hz * 1.6
    mask[freqs <= hp_lo] = 0.0
    hp_band = (freqs > hp_lo) & (freqs < hp_hi)
    if np.any(hp_band):
        t = (freqs[hp_band] - hp_lo) / (hp_hi - hp_lo)
        mask[hp_band] = 0.5 * (1.0 - np.cos(np.pi * t))

    # Smooth raised-cosine low-pass transition around 50 Hz (45..55 Hz)
    lp_lo = high_hz * 0.90
    lp_hi = high_hz * 1.10
    mask[freqs >= lp_hi] = 0.0
    lp_band = (freqs > lp_lo) & (freqs < lp_hi)
    if np.any(lp_band):
        t = (freqs[lp_band] - lp_lo) / (lp_hi - lp_lo)
        mask[lp_band] = 0.5 * (1.0 + np.cos(np.pi * t))

    spec = np.fft.rfft(x.astype(np.float32), axis=-1)
    filtered = np.fft.irfft(spec * mask[None, :], n=n, axis=-1)
    return filtered.astype(np.float32)


def preprocess_for_ecgfounder(tensor_12x5000: np.ndarray, fs: float = 500.0) -> np.ndarray:
    """Apply 0.5-50 Hz bandpass + per-lead Z-score normalization."""
    x = np.asarray(tensor_12x5000, dtype=np.float32)
    if x.shape != (12, 5000):
        raise ValueError(f"Expected (12, 5000), got {x.shape}")

    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    x = bandpass_zero_phase_fft(x, fs=fs, low_hz=0.5, high_hz=50.0)

    mu = x.mean(axis=1, keepdims=True)
    sd = x.std(axis=1, keepdims=True)
    # Avoid amplifying pure zero channels (missing leads)
    x = np.where(sd > 1e-6, (x - mu) / (sd + 1e-8), 0.0)
    return x[None, :, :].astype(np.float32)


def run_ecgfounder(tensor_12x5000: np.ndarray, fs: float = 500.0) -> dict:
    """Run ECGFounder-all71 ONNX inference and return 71-class probabilities & 5 superclasses."""
    sess, labels, err = _load_model()
    if sess is None:
        return {
            "loaded": False,
            "reason": err or "Model chua san sang",
            "superclasses": {},
            "top_predictions": [],
            "all_probs": {},
        }

    inp = preprocess_for_ecgfounder(tensor_12x5000, fs=fs)
    input_name = sess.get_inputs()[0].name
    logits = sess.run(None, {input_name: inp})[0][0]
    logits = np.clip(logits.astype(np.float32), -30.0, 30.0)
    probs = 1.0 / (1.0 + np.exp(-logits))

    all_probs: Dict[str, float] = {}
    super_probs: Dict[str, float] = {"NORM": 0.0, "MI": 0.0, "STTC": 0.0, "CD": 0.0, "HYP": 0.0}

    items = []
    for code, p in zip(labels, probs):
        prob = round(float(p), 4)
        all_probs[code] = prob
        vi_name, sc = SCP_INFO.get(code, (code, "STTC"))
        if sc in super_probs and prob > super_probs[sc]:
            super_probs[sc] = prob
        items.append({"code": code, "name_vi": vi_name, "superclass": sc, "prob": prob})

    items.sort(key=lambda d: d["prob"], reverse=True)
    # Filter out generic SR/NORM noise if pathology is prominent when returning top list
    top_predictions = [it for it in items[:12] if it["prob"] >= 0.05] or items[:5]

    return {
        "loaded": True,
        "reason": None,
        "superclasses": super_probs,
        "top_predictions": top_predictions,
        "all_probs": all_probs,
    }

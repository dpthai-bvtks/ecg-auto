"""Direct digital ECG signal parsers (JSON, CSV, XML) bypassing image digitization."""
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from . import LEAD_NAMES

TARGET_FS = 500
TARGET_LEN = 5000

LEAD_ALIASES = {
    "i": "I", "di": "I", "lead_i": "I", "mdc_ecg_lead_i": "I",
    "ii": "II", "dii": "II", "lead_ii": "II", "mdc_ecg_lead_ii": "II",
    "iii": "III", "diii": "III", "lead_iii": "III", "mdc_ecg_lead_iii": "III",
    "avr": "aVR", "lead_avr": "aVR", "mdc_ecg_lead_avr": "aVR",
    "avl": "aVL", "lead_avl": "aVL", "mdc_ecg_lead_avl": "aVL",
    "avf": "aVF", "lead_avf": "aVF", "mdc_ecg_lead_avf": "aVF",
    "v1": "V1", "lead_v1": "V1", "mdc_ecg_lead_v1": "V1",
    "v2": "V2", "lead_v2": "V2", "mdc_ecg_lead_v2": "V2",
    "v3": "V3", "lead_v3": "V3", "mdc_ecg_lead_v3": "V3",
    "v4": "V4", "lead_v4": "V4", "mdc_ecg_lead_v4": "V4",
    "v5": "V5", "lead_v5": "V5", "mdc_ecg_lead_v5": "V5",
    "v6": "V6", "lead_v6": "V6", "mdc_ecg_lead_v6": "V6",
}


@dataclass
class DigitalECGData:
    leads_mv: Dict[str, np.ndarray]
    tensor_12x5000: np.ndarray
    fs: int
    metadata: dict


def _canonical_lead(name: str) -> Optional[str]:
    key = name.strip().lower().replace("-", "_").replace(" ", "")
    return LEAD_ALIASES.get(key)


def _resample_1d(arr: np.ndarray, src_fs: float, dst_fs: int = TARGET_FS) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if len(arr) < 2 or abs(src_fs - dst_fs) < 1e-3:
        return arr
    dur = len(arr) / float(src_fs)
    new_len = max(10, int(round(dur * dst_fs)))
    x_old = np.linspace(0.0, 1.0, len(arr))
    x_new = np.linspace(0.0, 1.0, new_len)
    return np.interp(x_new, x_old, arr).astype(np.float32)


def _fit_5000(arr: np.ndarray) -> np.ndarray:
    if len(arr) >= TARGET_LEN:
        return arr[:TARGET_LEN].astype(np.float32)
    if len(arr) < 10:
        return np.zeros(TARGET_LEN, dtype=np.float32)
    # Seamless tile to 5000 samples
    reps = int(np.ceil(TARGET_LEN / float(len(arr))))
    tiled = np.tile(arr, reps)[:TARGET_LEN]
    return tiled.astype(np.float32)


def _normalize_mv_units(arr: np.ndarray, units: str = "") -> np.ndarray:
    u = (units or "").strip().lower()
    if u in {"uv", "microvolt", "microvolts"}:
        return arr / 1000.0
    if not u:
        # Heuristic: raw ADC / uV values are typically hundreds to thousands
        p99 = float(np.percentile(np.abs(arr), 99)) if len(arr) else 0.0
        if p99 > 25.0:
            return arr / 1000.0
    return arr


def _build_digital_result(raw_leads: Dict[str, np.ndarray], fs: float, metadata: dict, units: str = "") -> DigitalECGData:
    leads_mv: Dict[str, np.ndarray] = {}
    for name in LEAD_NAMES:
        if name in raw_leads and len(raw_leads[name]) > 0:
            sig = _normalize_mv_units(np.asarray(raw_leads[name], dtype=np.float32), units)
            sig = _resample_1d(sig, fs, TARGET_FS)
            leads_mv[name] = sig
        else:
            leads_mv[name] = np.zeros(1250, dtype=np.float32)

    # Compute missing derived limb leads if I and II exist
    if np.allclose(leads_mv["III"], 0) and not np.allclose(leads_mv["I"], 0) and not np.allclose(leads_mv["II"], 0):
        leads_mv["III"] = leads_mv["II"] - leads_mv["I"]
    if np.allclose(leads_mv["aVR"], 0) and not np.allclose(leads_mv["I"], 0) and not np.allclose(leads_mv["II"], 0):
        leads_mv["aVR"] = -0.5 * (leads_mv["I"] + leads_mv["II"])
    if np.allclose(leads_mv["aVL"], 0) and not np.allclose(leads_mv["I"], 0) and not np.allclose(leads_mv["II"], 0):
        leads_mv["aVL"] = leads_mv["I"] - 0.5 * leads_mv["II"]
    if np.allclose(leads_mv["aVF"], 0) and not np.allclose(leads_mv["I"], 0) and not np.allclose(leads_mv["II"], 0):
        leads_mv["aVF"] = leads_mv["II"] - 0.5 * leads_mv["I"]

    tensor = np.stack([_fit_5000(leads_mv[n]) for n in LEAD_NAMES], axis=0).astype(np.float32)
    return DigitalECGData(leads_mv=leads_mv, tensor_12x5000=tensor, fs=TARGET_FS, metadata=metadata)


def parse_digital_ecg(file_bytes: bytes, filename: str) -> DigitalECGData:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    text = file_bytes.decode("utf-8", errors="ignore")

    if ext == "json" or text.lstrip().startswith("{"):
        data = json.loads(text)
        fs = float(data.get("fs") or data.get("sampling_rate") or 500)
        units = str(data.get("units", ""))
        src = data.get("leads") if isinstance(data.get("leads"), dict) else data
        raw: Dict[str, np.ndarray] = {}
        for k, v in src.items():
            c = _canonical_lead(str(k))
            if c and isinstance(v, list):
                raw[c] = np.asarray(v, dtype=np.float32)
        if len(raw) < 3:
            raise ValueError("File JSON khong du du lieu cac chuyen dao ECG (I..V6).")
        meta = {k: data[k] for k in ("hr", "pr", "qrs", "qt", "qtc", "axis", "sex") if k in data}
        return _build_digital_result(raw, fs, meta, units=units)

    if ext == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("File CSV khong co tieu de cot.")
        col_map = {}
        time_col = None
        for f in reader.fieldnames:
            cf = _canonical_lead(f)
            if cf:
                col_map[f] = cf
            elif f.strip().lower() in {"time", "t", "ms", "sec", "seconds"}:
                time_col = f
        if len(col_map) < 3:
            raise ValueError("Khong tim thay cac cot chuyen dao ECG trong file CSV.")

        cols: Dict[str, list[float]] = {v: [] for v in col_map.values()}
        times: list[float] = []
        for row in reader:
            for orig, canon in col_map.items():
                try:
                    cols[canon].append(float(row[orig]))
                except (TypeError, ValueError):
                    cols[canon].append(0.0)
            if time_col:
                try:
                    times.append(float(row[time_col]))
                except (TypeError, ValueError):
                    pass

        fs = 500.0
        if len(times) >= 5:
            dt = float(np.median(np.diff(times)))
            if dt > 0:
                fs = 1000.0 / dt if dt > 0.2 else 1.0 / dt
        raw = {k: np.asarray(v, dtype=np.float32) for k, v in cols.items()}
        return _build_digital_result(raw, fs, {})

    if ext == "xml" or text.lstrip().startswith("<"):
        root = ET.fromstring(text)
        raw: Dict[str, np.ndarray] = {}
        fs = 500.0
        scale_uv = 1.0
        meta: dict = {}

        # Extract sampling rate / scale hints if present
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()
            txt = (elem.text or "").strip()
            if not txt:
                continue
            if tag in {"samplerate", "samplingrate", "sample_rate"}:
                try:
                    fs = float(txt)
                except ValueError:
                    pass
            elif tag in {"ventrate", "ventricularrate", "heartrate"}:
                try:
                    meta["hr"] = int(float(txt))
                except ValueError:
                    pass
            elif tag in {"printerval"}:
                try:
                    meta["pr"] = int(float(txt))
                except ValueError:
                    pass
            elif tag in {"qrsduration"}:
                try:
                    meta["qrs"] = int(float(txt))
                except ValueError:
                    pass
            elif tag in {"qtinterval"}:
                try:
                    meta["qt"] = int(float(txt))
                except ValueError:
                    pass
            elif tag in {"qtcorrected", "qtc"}:
                try:
                    meta["qtc"] = int(float(txt))
                except ValueError:
                    pass

        # HL7 aECG / generic XML digits
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()
            if tag == "digits" and elem.text:
                # Find lead code near parent/sibling
                lead_found = None
                for attr_v in elem.attrib.values():
                    lead_found = _canonical_lead(attr_v) or lead_found
                if lead_found is None:
                    # Try parent attributes/children
                    for cand in root.iter():
                        if elem in list(cand):
                            for sub in cand.iter():
                                c = sub.attrib.get("code") or sub.attrib.get("lead") or (sub.text or "")
                                lead_found = _canonical_lead(c)
                                if lead_found:
                                    break
                vals = [float(x) for x in elem.text.replace(",", " ").split() if x.lstrip("+-").replace(".", "", 1).isdigit()]
                if lead_found and len(vals) > 20:
                    raw[lead_found] = np.asarray(vals, dtype=np.float32) * scale_uv

        # GE / Nihon Kohden WaveFormData with LeadID
        if len(raw) < 3:
            for wf in root.iter():
                if wf.tag.split("}")[-1].lower() in {"lead", "waveform", "channel"}:
                    lid = wf.attrib.get("id") or wf.attrib.get("lead") or wf.attrib.get("name") or ""
                    canon = _canonical_lead(lid)
                    if not canon:
                        for child in wf:
                            if child.tag.split("}")[-1].lower() in {"leadid", "id", "name", "code"} and child.text:
                                canon = _canonical_lead(child.text)
                                if canon:
                                    break
                    if not canon:
                        continue
                    for child in wf.iter():
                        if child.tag.split("}")[-1].lower() in {"waveformdata", "digits", "data", "samples"} and child.text:
                            toks = child.text.replace(",", " ").split()
                            try:
                                arr = np.asarray([float(t) for t in toks], dtype=np.float32)
                                if len(arr) > 20:
                                    raw[canon] = arr
                                    break
                            except ValueError:
                                pass

        if len(raw) < 3:
            raise ValueError("Khong trich xuat duoc du lieu song tho tu file XML (co the XML da ma hoa Base64/doc quyen).")
        return _build_digital_result(raw, fs, meta)

    raise ValueError(f"Dinh dang file so khong ho tro: {ext}")

"""Quantitative 12-lead ECG electrophysiological measurement & ESC 2023 / OMI criteria evaluator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import GRID_4X3, LEAD_NAMES
from .ocr_parser import OCRResult

FS = 500.0
SAMPLES_PER_MS = 0.5  # 500 Hz -> 2 ms/sample -> 0.5 samples/ms


@dataclass
class LeadMeasurement:
    lead: str
    gain_mm_per_mv: float
    st_j_mm: float
    st_mm: float
    st_60_mm: float
    st_morphology: str  # elevation_convex | elevation_concave | depression | isoelectric
    t_mm: float
    r_mm: float
    s_mm: float
    q_mm: float
    q_pathologic: bool
    quality: float

    def to_dict(self) -> dict:
        return {
            "lead": self.lead,
            "gain_mm_per_mv": self.gain_mm_per_mv,
            "st_j_mm": round(self.st_j_mm, 2),
            "st_mm": round(self.st_mm, 2),
            "st_60_mm": round(self.st_60_mm, 2),
            "st_morphology": self.st_morphology,
            "t_mm": round(self.t_mm, 2),
            "r_mm": round(self.r_mm, 2),
            "s_mm": round(self.s_mm, 2),
            "q_mm": round(self.q_mm, 2),
            "q_pathologic": self.q_pathologic,
            "quality": round(self.quality, 3),
        }


@dataclass
class SignalMetricsResult:
    lead_measurements: Dict[str, LeadMeasurement]
    hr_measured: Optional[int]
    rr_irregularity_cv: Optional[float]
    is_irregular_rhythm: bool
    qrs_measured_ms: Optional[int]
    sokolow_lyon_mm: Optional[float]
    cornell_mm: Optional[float]
    r_v1_mm: Optional[float]
    regions: Dict[str, dict]
    detected_patterns: List[str] = field(default_factory=list)
    culprit_artery_hint: Optional[str] = None
    stemi_territory: Optional[str] = None
    has_reciprocal_changes: bool = False
    has_posterior_extension: bool = False
    special_code: str = "none"


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(x) < win:
        return x.astype(np.float32)
    kernel = np.ones(win, dtype=np.float32) / float(win)
    return np.convolve(x.astype(np.float32), kernel, mode="same")


def _highpass_for_qrs(x: np.ndarray, win: int = 40) -> np.ndarray:
    # Subtract 80ms moving average (40 samples @ 500Hz) so broad ST-T waves are suppressed vs sharp QRS
    base = _moving_average(x, win)
    return (x - base).astype(np.float32)


def _detect_qrs_peaks_group(signals: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Simultaneously detect QRS centers across a group of time-aligned leads."""
    min_len = min(len(s) for s in signals)
    if min_len < 100:
        return np.array([], dtype=np.int32), np.zeros(min_len, dtype=np.float32)

    energy = np.zeros(min_len, dtype=np.float32)
    for s in signals:
        seg = s[:min_len]
        hp = _highpass_for_qrs(seg, win=40)
        dv = np.diff(hp, prepend=hp[0])
        energy += dv * dv

    inst_energy = _moving_average(energy, 5)   # 10ms sharp QRS peak locator
    sm_energy = _moving_average(energy, 26)    # 52ms integration window
    edge = 35
    core = sm_energy[edge:-edge] if min_len > 2 * edge + 20 else sm_energy
    if len(core) == 0 or float(core.max()) <= 1e-8:
        return np.array([], dtype=np.int32), sm_energy

    med_e = float(np.median(core))
    max_e = float(np.percentile(core, 98))
    thr = max(0.30 * max_e, 4.5 * med_e, 1e-5)

    min_dist = 155  # 310ms refractory
    candidates = np.where(sm_energy > thr)[0]
    if len(candidates) == 0:
        return np.array([], dtype=np.int32), sm_energy

    groups: List[Tuple[int, int]] = []
    g0 = int(candidates[0])
    prev = g0
    for idx in candidates[1:]:
        idx_i = int(idx)
        if idx_i - prev <= 25:
            prev = idx_i
        else:
            groups.append((g0, prev))
            g0 = idx_i
            prev = idx_i
    groups.append((g0, prev))

    raw_peaks: List[Tuple[int, float]] = []
    for a, b in groups:
        if b - a < 3:
            continue
        center_e = a + int(np.argmax(sm_energy[a : b + 1]))
        ra = max(0, center_e - 20)
        rb = min(min_len, center_e + 21)
        peak_idx = ra + int(np.argmax(inst_energy[ra:rb]))
        peak_e = float(sm_energy[center_e])
        if not raw_peaks or (peak_idx - raw_peaks[-1][0]) >= min_dist:
            raw_peaks.append((peak_idx, peak_e))
        elif peak_e > raw_peaks[-1][1]:
            raw_peaks[-1] = (peak_idx, peak_e)

    # Suppress false T-wave double-counts (< 35% of neighboring major QRS peak within 440ms)
    filtered: List[Tuple[int, float]] = []
    for pk, pe in raw_peaks:
        if filtered and (pk - filtered[-1][0]) < 220:
            if pe < 0.35 * filtered[-1][1]:
                continue
            elif filtered[-1][1] < 0.35 * pe:
                filtered[-1] = (pk, pe)
                continue
        filtered.append((pk, pe))

    return np.asarray([p[0] for p in filtered], dtype=np.int32), sm_energy


def _build_median_beats_for_column(
    col_signals: List[np.ndarray],
    qrs_peaks: np.ndarray,
) -> Tuple[List[np.ndarray], int, np.ndarray]:
    """Build synchronized median beats [qrs - 260ms .. qrs + 440ms] (350 samples) for 3 column leads."""
    pre = 130   # 260ms
    post = 220  # 440ms
    win_len = pre + post
    min_len = min(len(s) for s in col_signals)

    valid_peaks = [int(p) for p in qrs_peaks if pre <= p <= (min_len - post)]
    if not valid_peaks and len(qrs_peaks) > 0:
        # Fallback if beat is slightly close to edge: pad signal edges by reflection/edge value
        valid_peaks = [int(p) for p in qrs_peaks if 40 <= p <= (min_len - 80)]

    medians: List[np.ndarray] = []
    for s in col_signals:
        if not valid_peaks:
            medians.append(np.zeros(win_len, dtype=np.float32))
            continue
        beats = []
        for p in valid_peaks:
            a = p - pre
            b = p + post
            if a >= 0 and b <= len(s):
                beats.append(s[a:b])
            else:
                # Edge-pad only when no fully interior beat exists
                pad_l = max(0, -a)
                pad_r = max(0, b - len(s))
                seg = s[max(0, a) : min(len(s), b)]
                seg = np.pad(seg, (pad_l, pad_r), mode="edge")
                beats.append(seg[:win_len])
        if len(beats) >= 2:
            # Drop single beats corrupted by severe pre-QRS fold/baseline artifact when a flat beat exists
            pre_a = max(0, pre - 110)
            pre_b = max(pre_a + 10, pre - 22)
            pre_stds = [float(np.std(bt[pre_a:pre_b])) for bt in beats]
            min_std = min(pre_stds)
            if min_std < 0.14:
                thr_std = max(0.20, 3.0 * min_std)
                clean_beats = [bt for bt, st in zip(beats, pre_stds) if st <= thr_std]
                if clean_beats:
                    beats = clean_beats
        med = np.median(np.stack(beats, axis=0), axis=0).astype(np.float32)
        medians.append(med)

    # Combined QRS energy (derivative + high-pass amplitude so R-tip never has a zero dip)
    col_energy = np.zeros(win_len, dtype=np.float32)
    for m in medians:
        hp = _highpass_for_qrs(m, win=30)
        dv = np.diff(hp, prepend=hp[0])
        col_energy += dv * dv + 0.0625 * (hp * hp)
    col_energy = _moving_average(col_energy, 9)  # 18ms smoothing
    return medians, pre, col_energy


def _find_isoelectric_baseline(beat: np.ndarray, q_onset: int) -> float:
    """Find flattest 24ms segment in the PR segment anchored toward the global quiet baseline."""
    win = 12  # 24ms
    if len(beat) >= win:
        all_wins = np.lib.stride_tricks.sliding_window_view(beat, win)
        all_vars = np.var(all_wins, axis=1)
        k_quiet = max(1, int(np.ceil(0.30 * len(all_vars))))
        quiet_idx = np.argpartition(all_vars, k_quiet - 1)[:k_quiet]
        v_quiet = float(np.median(np.median(all_wins[quiet_idx], axis=1)))
    else:
        v_quiet = float(np.median(beat)) if len(beat) > 0 else 0.0

    a = max(0, q_onset - 45)
    b = min(len(beat), max(14, q_onset - 3))
    seg = beat[a:b]
    if len(seg) <= win:
        return float(np.median(seg)) if len(seg) > 0 else v_quiet

    best_score = np.inf
    best_val = float(np.median(seg))
    for i in range(0, len(seg) - win + 1):
        w = seg[i : i + win]
        var = float(np.var(w))
        slope = abs(float(w[-1] - w[0]))
        w_med = float(np.median(w))
        score = var + 0.08 * (slope * slope) + 0.25 * ((w_med - v_quiet) ** 2)
        if score < best_score:
            best_score = score
            best_val = w_med
    return best_val


def _find_q_onset_and_j_point(
    col_energy: np.ndarray,
    qrs_center: int,
    ocr_qrs_ms: Optional[int],
) -> Tuple[int, int, int]:
    """Locate Q_onset and J_point robustly across 3 simultaneous column leads."""
    n = len(col_energy)
    pk_win_a = max(0, qrs_center - 28)
    pk_win_b = min(n, qrs_center + 29)
    e_slice = col_energy[pk_win_a:pk_win_b]
    peak_e = float(np.max(e_slice)) if len(e_slice) > 0 else 1.0
    true_center = pk_win_a + int(np.argmax(e_slice)) if len(e_slice) > 0 else qrs_center
    thr = max(1e-6, 0.08 * peak_e)

    # Q onset: walk backward from left side of QRS energy burst (up to -76ms before true_center)
    q_onset = max(12, true_center - 24)
    start_back = max(12, true_center - 4)
    for idx in range(start_back, max(12, true_center - 38), -1):
        if col_energy[idx] <= thr:
            q_onset = idx
            break

    # J point: if machine OCR QRS duration exists, anchor tightly around q_onset + qrs_dur/2
    if ocr_qrs_ms is not None and 50 <= ocr_qrs_ms <= 220:
        expected_j = min(n - 40, max(true_center + 6, q_onset + int(round(ocr_qrs_ms * SAMPLES_PER_MS))))
        ja = max(true_center + 4, expected_j - 10)
        jb = min(n - 35, expected_j + 11)
        if jb > ja:
            local_e = col_energy[ja:jb]
            dist = np.abs(np.arange(ja, jb) - expected_j).astype(np.float32)
            score = local_e + 0.015 * peak_e * dist
            j_point = ja + int(np.argmin(score))
        else:
            j_point = expected_j
    else:
        j_point = min(n - 35, true_center + 24)
        for idx in range(true_center + 8, min(n - 35, true_center + 46)):
            if col_energy[idx] <= thr:
                j_point = idx
                break

    qrs_est_ms = int(round((j_point - q_onset) / SAMPLES_PER_MS))
    return q_onset, j_point, qrs_est_ms


def _measure_single_lead(
    lead_name: str,
    beat: np.ndarray,
    qrs_center: int,
    q_onset: int,
    j_point: int,
    gain_mm_per_mv: float,
    quality: float,
) -> LeadMeasurement:
    v_iso = _find_isoelectric_baseline(beat, q_onset)
    n = len(beat)

    # Convert mV -> standard mm @ 10 mm/mV (1 mV = 10 mm regardless of display gain)
    st_j_mm = float((beat[min(n - 1, j_point + 10)] - v_iso) * 10.0)   # J + 20ms
    st_mm = float((beat[min(n - 1, j_point + 20)] - v_iso) * 10.0)     # J + 40ms
    st_60_mm = float((beat[min(n - 1, j_point + 30)] - v_iso) * 10.0)  # J + 60ms

    # Use median over a tight 16ms window around J+30ms..J+50ms for noise immunity,
    # keeping st_j_mm and st_60_mm explicit too
    st_band = beat[min(n - 1, j_point + 12) : min(n, j_point + 28)]
    if len(st_band) >= 3:
        st_rep_mm = float((np.median(st_band) - v_iso) * 10.0)
    else:
        st_rep_mm = st_mm

    # T wave amplitude in [J + 70ms .. J + 320ms]
    ta = min(n - 2, j_point + 35)
    tb = min(n, j_point + 160)
    if tb > ta + 4:
        t_seg = (beat[ta:tb] - v_iso) * 10.0
        t_max = float(np.max(t_seg))
        t_min = float(np.min(t_seg))
        t_mm = t_max if abs(t_max) >= abs(t_min) else t_min
        t_peak_idx = ta + (int(np.argmax(t_seg)) if abs(t_max) >= abs(t_min) else int(np.argmin(t_seg)))
    else:
        t_mm = 0.0
        t_peak_idx = min(n - 1, j_point + 70)

    # QRS waves inside [q_onset .. j_point]
    qrs_seg = (beat[q_onset : j_point + 1] - v_iso) * 10.0
    if len(qrs_seg) >= 3:
        r_mm = max(0.0, float(np.max(qrs_seg)))
        r_rel_idx = int(np.argmax(qrs_seg))
        # Q wave: negative deflection strictly before R peak
        pre_r = qrs_seg[:r_rel_idx] if r_rel_idx > 0 else np.array([], dtype=np.float32)
        q_mm = max(0.0, float(-np.min(pre_r))) if len(pre_r) > 0 else 0.0
        q_samples_below = int(np.sum(pre_r < -0.5)) if len(pre_r) > 0 else 0
        q_dur_ms = q_samples_below / SAMPLES_PER_MS
        q_pathologic = (q_mm >= 1.0) and (q_dur_ms >= 36.0 or (r_mm >= 2.0 and q_mm >= 0.25 * r_mm))
        # S wave: negative deflection after R peak (or total negative depth if QS)
        post_r = qrs_seg[r_rel_idx:]
        s_mm = max(0.0, float(-np.min(post_r))) if len(post_r) > 0 else 0.0
    else:
        r_mm, s_mm, q_mm, q_pathologic = 0.0, 0.0, 0.0, False

    # ST morphology classification
    if st_rep_mm >= 0.7:
        # Check convexity vs concavity relative to chord from J+10ms to T_peak
        j10 = min(n - 1, j_point + 5)
        if t_peak_idx > j10 + 10:
            mid = (j10 + t_peak_idx) // 2
            chord_mid = 0.5 * (beat[j10] + beat[t_peak_idx])
            st_morphology = "elevation_convex" if beat[mid] >= chord_mid - 0.015 else "elevation_concave"
        else:
            st_morphology = "elevation_convex"
    elif st_rep_mm <= -0.6:
        st_morphology = "depression"
    else:
        st_morphology = "isoelectric"

    return LeadMeasurement(
        lead=lead_name,
        gain_mm_per_mv=gain_mm_per_mv,
        st_j_mm=st_j_mm,
        st_mm=st_rep_mm,
        st_60_mm=st_60_mm,
        st_morphology=st_morphology,
        t_mm=t_mm,
        r_mm=r_mm,
        s_mm=s_mm,
        q_mm=q_mm,
        q_pathologic=q_pathologic,
        quality=quality,
    )


def evaluate_signal_metrics(
    leads_mv: Dict[str, np.ndarray],
    rhythm_mv: Optional[np.ndarray],
    ocr_res: OCRResult,
    column_gains: Dict[str, float],
    lead_qualities: Optional[Dict[str, float]] = None,
) -> SignalMetricsResult:
    """Compute quantitative 12-lead ECG measurements and apply ESC 2023 / OMI criteria."""
    qualities = lead_qualities or {k: 1.0 for k in LEAD_NAMES}
    col_keys = ["col1", "col2", "col3", "col4"]

    lead_measurements: Dict[str, LeadMeasurement] = {}
    qrs_durs: List[int] = []
    col_rr_lists: List[np.ndarray] = []

    for c_idx in range(4):
        col_leads = [GRID_4X3[r][c_idx] for r in range(3)]
        col_sigs = [leads_mv.get(ln, np.zeros(1250, dtype=np.float32)) for ln in col_leads]
        peaks, _ = _detect_qrs_peaks_group(col_sigs)
        if len(peaks) >= 2:
            col_rr_lists.append(np.diff(peaks) * 2.0)

        medians, qrs_c, col_e = _build_median_beats_for_column(col_sigs, peaks)
        q_on, j_pt, qrs_ms = _find_q_onset_and_j_point(col_e, qrs_c, ocr_res.qrs)
        if 50 <= qrs_ms <= 220:
            qrs_durs.append(qrs_ms)

        gain_c = float(column_gains.get(col_keys[c_idx], 10.0))
        for r_idx, ln in enumerate(col_leads):
            lm = _measure_single_lead(
                lead_name=ln,
                beat=medians[r_idx],
                qrs_center=qrs_c,
                q_onset=q_on,
                j_point=j_pt,
                gain_mm_per_mv=gain_c,
                quality=float(qualities.get(ln, 1.0)),
            )
            lead_measurements[ln] = lm

    # Measure HR & RR irregularity from 10s rhythm strip if available
    hr_measured: Optional[int] = None
    rr_cv: Optional[float] = None
    is_irregular = False

    if rhythm_mv is not None and len(rhythm_mv) >= 1500:
        r_peaks, _ = _detect_qrs_peaks_group([rhythm_mv])
        if len(r_peaks) >= 3:
            rrs = np.diff(r_peaks) * 2.0  # ms @ 500 Hz
            rrs_valid = rrs[(rrs >= 240.0) & (rrs <= 2400.0)]
            if len(rrs_valid) >= 2:
                med_rr = float(np.median(rrs_valid))
                hr_measured = int(round(60000.0 / med_rr))
                rr_cv = round(float(np.std(rrs_valid) / max(1.0, float(np.mean(rrs_valid)))), 3)
                is_irregular = rr_cv > 0.14
    elif col_rr_lists:
        all_rr = np.concatenate(col_rr_lists)
        all_rr = all_rr[(all_rr >= 240.0) & (all_rr <= 2400.0)]
        if len(all_rr) >= 2:
            hr_measured = int(round(60000.0 / float(np.median(all_rr))))
            rr_cv = round(float(np.std(all_rr) / max(1.0, float(np.mean(all_rr)))), 3)
            is_irregular = rr_cv > 0.16

    qrs_measured_ms = int(round(float(np.median(qrs_durs)))) if qrs_durs else None

    # Voltage indices
    s_v1 = (ocr_res.sv1_mv * 10.0) if ocr_res.sv1_mv is not None else lead_measurements["V1"].s_mm
    r_v56 = (ocr_res.rv5_mv * 10.0) if ocr_res.rv5_mv is not None else max(lead_measurements["V5"].r_mm, lead_measurements["V6"].r_mm)
    sokolow = round(s_v1 + r_v56, 1)
    cornell = round(lead_measurements["aVL"].r_mm + lead_measurements["V3"].s_mm, 1)
    r_v1 = round(lead_measurements["V1"].r_mm, 1)

    # Helper to summarize ST/T/Q across a list of leads
    def _st_val(ln: str) -> float:
        m = lead_measurements[ln]
        return max(m.st_mm, m.st_j_mm * 0.85) if m.st_mm > 0 else m.st_mm

    inf_elev = [ln for ln in ("II", "III", "aVF") if _st_val(ln) >= 0.85]
    inf_strong = [ln for ln in ("II", "III", "aVF") if _st_val(ln) >= 1.0]
    sept_elev = [ln for ln in ("V1", "V2") if _st_val(ln) >= (1.5 if ln == "V2" else 1.0)]
    ant_elev = [ln for ln in ("V3", "V4") if _st_val(ln) >= (1.5 if ln == "V3" else 1.0)]
    lat_high_elev = [ln for ln in ("I", "aVL") if _st_val(ln) >= 0.9]
    lat_low_elev = [ln for ln in ("V5", "V6") if _st_val(ln) >= 0.9]

    # Reciprocal depression checks
    inf_recip_dep = any(lead_measurements[ln].st_mm <= -0.65 for ln in ("I", "aVL"))
    ant_post_dep = [ln for ln in ("V1", "V2", "V3") if lead_measurements[ln].st_mm <= -0.75]
    lat_dep = [ln for ln in ("I", "aVL", "V5", "V6") if lead_measurements[ln].st_mm <= -0.65]
    inf_dep = [ln for ln in ("II", "III", "aVF") if lead_measurements[ln].st_mm <= -0.65]

    patterns: List[str] = []
    stemi_territory: Optional[str] = None
    culprit_hint: Optional[str] = None
    has_reciprocal = False
    has_posterior = False
    special_code = "none"

    # 1. Check Inferior STEMI (ESC 2023: >= 1.0mm in >=2 of II, III, aVF; or >=0.85mm when backed by reciprocal I/aVL depression)
    if len(inf_strong) >= 2 or (len(inf_elev) >= 2 and inf_recip_dep):
        patterns.append("STEMI_INFERIOR")
        stemi_territory = "thành dưới (DII, DIII, aVF)"
        has_reciprocal = inf_recip_dep
        st_iii = lead_measurements["III"].st_mm
        st_ii = lead_measurements["II"].st_mm
        if st_iii > st_ii + 0.15 or lead_measurements["I"].st_mm <= -0.5:
            culprit_hint = "Động mạch vành phải (RCA) — do ST chênh lên DIII > DII và/hoặc soi gương sâu ở DI, aVL"
        else:
            culprit_hint = "Động mạch mũ (LCx) hoặc ĐM vành phải (RCA)"
        if len(ant_post_dep) >= 2 or (lead_measurements["V2"].st_mm <= -0.8 and lead_measurements["V3"].st_mm <= -0.8):
            has_posterior = True
            patterns.append("POSTERIOR_EXTENSION")

    # 2. Anterior / Anteroseptal STEMI
    elif len(sept_elev) >= 2 or len(ant_elev) >= 2 or (len(sept_elev) >= 1 and len(ant_elev) >= 1):
        # Differentiate BER vs true anterior STEMI
        convex_cnt = sum(1 for ln in ("V1", "V2", "V3", "V4") if lead_measurements[ln].st_morphology == "elevation_convex")
        if inf_dep or convex_cnt >= 2 or max(lead_measurements[ln].st_mm for ln in ("V2", "V3", "V4")) >= 2.2:
            patterns.append("STEMI_ANTERIOR")
            stemi_territory = "thành trước / trước vách (V1–V4)"
            culprit_hint = "Động mạch liên thất trước (LAD)"
            has_reciprocal = len(inf_dep) > 0
        else:
            patterns.append("POSSIBLE_BER")
            special_code = "ber"

    # 3. High lateral / Lateral STEMI
    elif len(lat_high_elev) >= 2 or len(lat_low_elev) >= 2:
        patterns.append("STEMI_LATERAL")
        stemi_territory = "thành bên (DI, aVL / V5, V6)"
        culprit_hint = "Động mạch mũ (LCx) hoặc nhánh chéo D1"
        has_reciprocal = len(inf_dep) > 0

    # 4. Special OMI equivalents
    elif lead_measurements["III"].st_mm >= 0.9 and lead_measurements["II"].st_mm < 0.7 and len([ln for ln in ("V4", "V5", "V6") if lead_measurements[ln].st_mm <= -0.6]) >= 2:
        patterns.append("ASLANGER")
        special_code = "aslanger"
        stemi_territory = "thành dưới đa thân mạch vành (Aslanger)"
    elif lead_measurements["I"].st_mm >= 0.8 and lead_measurements["aVL"].st_mm >= 0.8 and lead_measurements["V2"].st_mm >= 1.2 and lead_measurements["III"].st_mm <= -0.6:
        patterns.append("SA_FLAG")
        special_code = "sa_flag"
        stemi_territory = "thành bên cao / nhánh chéo D1 (South African Flag)"
    elif lead_measurements["aVR"].st_mm >= 1.0 and sum(1 for ln in LEAD_NAMES if ln != "aVR" and lead_measurements[ln].st_mm <= -0.8) >= 5:
        patterns.append("LMCA")
        special_code = "lmca"
    elif len(ant_post_dep) >= 2 and lead_measurements["V2"].st_mm <= -1.0 and not inf_elev:
        patterns.append("POSTERIOR_STEMI_ISOLATED")
        has_posterior = True

    # Build 4-region summary aligned with frontend card 5
    def _region_summary(elev_list: list, all_leads: tuple, region_key: str) -> dict:
        st_state = "none"
        elev_in_reg = [ln for ln in elev_list if ln in all_leads]
        if (len(elev_in_reg) >= 2) or (region_key == "inf" and "STEMI_INFERIOR" in patterns) or (region_key in ("sept", "ant") and "STEMI_ANTERIOR" in patterns) or (region_key == "lat" and "STEMI_LATERAL" in patterns):
            st_state = "elevation"
        elif sum(1 for ln in all_leads if lead_measurements[ln].st_mm <= -0.65) >= 1:
            st_state = "depression"

        t_inv = sum(1 for ln in all_leads if lead_measurements[ln].t_mm <= -1.0)
        t_pk = sum(1 for ln in all_leads if lead_measurements[ln].t_mm >= 5.5)
        t_state = "inverted" if t_inv >= 1 else ("peaked" if t_pk >= 1 else "none")
        if region_key == "sept":
            # In V1, low-gain QS/rS is normal unless V2 also has pathologic Q or sept ST elevation
            q_flag = lead_measurements["V2"].q_pathologic or (lead_measurements["V1"].q_pathologic and st_state == "elevation")
        else:
            q_flag = any(lead_measurements[ln].q_pathologic for ln in all_leads)
        return {"st": st_state, "t": t_state, "q": q_flag}

    regions = {
        "inf": _region_summary(inf_elev, ("II", "III", "aVF"), "inf"),
        "sept": _region_summary(sept_elev, ("V1", "V2"), "sept"),
        "ant": _region_summary(ant_elev, ("V3", "V4"), "ant"),
        "lat": _region_summary(lat_high_elev + lat_low_elev, ("I", "aVL", "V5", "V6"), "lat"),
    }
    # Ensure inferior elevation is marked if STEMI_INFERIOR triggered
    if "STEMI_INFERIOR" in patterns:
        regions["inf"]["st"] = "elevation"
    if "STEMI_ANTERIOR" in patterns:
        if sept_elev:
            regions["sept"]["st"] = "elevation"
        if ant_elev:
            regions["ant"]["st"] = "elevation"
    if "STEMI_LATERAL" in patterns:
        regions["lat"]["st"] = "elevation"

    # Hypertrophy flags
    if sokolow >= 35.0 or lead_measurements["aVL"].r_mm > 11.0:
        patterns.append("LVH")
    if r_v1 >= 7.0 and lead_measurements["V1"].r_mm > lead_measurements["V1"].s_mm:
        patterns.append("RVH")

    return SignalMetricsResult(
        lead_measurements=lead_measurements,
        hr_measured=hr_measured,
        rr_irregularity_cv=rr_cv,
        is_irregular_rhythm=is_irregular,
        qrs_measured_ms=qrs_measured_ms,
        sokolow_lyon_mm=sokolow,
        cornell_mm=cornell,
        r_v1_mm=r_v1,
        regions=regions,
        detected_patterns=patterns,
        culprit_artery_hint=culprit_hint,
        stemi_territory=stemi_territory,
        has_reciprocal_changes=has_reciprocal,
        has_posterior_extension=has_posterior,
        special_code=special_code,
    )

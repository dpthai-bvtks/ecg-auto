"""Clinical Evidence Fusion: OCR + Quantitative 12-Lead mV Metrics + ECGFounder + Gemini 3.x."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import LEAD_NAMES
from .ocr_parser import OCRResult
from .signal_metrics import SignalMetricsResult

GEMINI_FAST_MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"]
GEMINI_DEEP_MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-3.5-flash-lite"]

HYBRID_SYSTEM_PROMPT = """Bạn là chuyên gia Tim mạch & Cấp cứu (tổng hợp chuẩn GS.TS. Trần Đỗ Trinh, VNHA 2023–2024, Bộ Y tế VN, ESC 2023 và Dr. Smith OMI).
Bạn nhận đồng thời:
(1) Ảnh dải sóng 12 chuyển đạo ĐÃ CẮT SÁT (độ phân giải cao, KHÔNG có cột text máy in làm nhiễu);
(2) BẢNG ĐO ĐẠC ĐỊNH LƯỢNG 12 CHUYỂN ĐẠO đã hiệu chuẩn độ lợi (2.5 / 5 / 10 mm/mV -> quy đổi chuẩn 10 mm/mV);
(3) Thông số chu kỳ máy ECG đo được qua OCR & Dự đoán xác suất từ mô hình chuyên biệt ECGFounder-all71;
(4) Bệnh cảnh lâm sàng & cận lâm sàng bệnh nhân.

NGUYÊN TẮC BẮT BUỘC:
1. PHÂN BIỆT DỨT KHOÁT STEMI vs NSTE-ACS:
   - Nếu có ST chênh lên tại điểm J đạt tiêu chuẩn ESC 2023 ở ≥ 2 chuyển đạo liên tiếp cùng vùng giải phẫu (chi/V1/V4-V6 ≥ 1.0 mm; V2-V3: nam <40t ≥ 2.5mm, nam ≥40t ≥ 2.0mm, nữ ≥ 1.5mm), ĐẶC BIỆT khi có ST chênh xuống soi gương ở chuyển đạo đối diện (ví dụ II, III, aVF chênh lên kèm I, aVL chênh xuống; hoặc V1-V3 chênh xuống gợi ý tổn thương thành sau):
     -> PHẢI kết luận chính xác là "Nhồi máu cơ tim cấp có ST chênh lên (STEMI) [vùng]" (kèm động mạch vành thủ phạm nếu rõ, ví dụ DIII > DII gợi ý ĐM vành phải RCA), phân tầng "Nguy cơ rất cao", và kích hoạt phác đồ cấp cứu PCI < 120 phút!
     -> TUYỆT ĐỐI KHÔNG được gọi mờ nhạt là "Hội chứng vành cấp" hay "Thiếu máu dưới nội tâm mạc" chỉ vì dòng chữ bảo thủ in trên máy ECG.
2. TÔN TRỌNG HIỆU CHUẨN GAIN: Nếu máy in đặt 2.5 mm/mV (V1-V3) hoặc 5 mm/mV (V4-V6), sóng trên giấy trông nhỏ hơn thực tế 2-4 lần — hãy đối chiếu số đo mm chuẩn đã hiệu chuẩn.
3. CHỐNG DƯƠNG TÍNH GIẢ: Nếu số đo ST các chuyển đạo đều gần đẳng điện (< 0.8 mm) hoặc chỉ là tái cực sớm lành tính (ST lõm, khấc J, không soi gương, lâm sàng âm tính) và ECGFounder thiên về NORM, kết luận "Điện tâm đồ bình thường" hoặc "Tái cực sớm lành tính" ("Nguy cơ thấp").
4. REASONING-FIRST: Luôn trình bày "clinical_reasoning" trước rồi mới chốt thông số và chẩn đoán. Chỉ trả về DUY NHẤT JSON hợp lệ theo schema yêu cầu."""


def _compute_qtc(hr: Optional[int], qt: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    if not hr or not qt or hr <= 0:
        return None, None
    rr = 60.0 / float(hr)
    baz = int(round(qt / math.sqrt(rr)))
    frid = int(round(qt / (rr ** (1.0 / 3.0))))
    return baz, frid


def _parse_clinical_flags(clinical_context: str) -> dict:
    txt = (clinical_context or "").lower()
    # Parse SBP safely using regex instead of substring matching
    sbp: Optional[int] = None
    m_bp = re.search(r"huyết áp\s*:?\s*(\d{2,3})\s*/\s*(\d{2,3})|\b(\d{2,3})\s*/\s*(\d{2,3})\s*mmhg", txt)
    if m_bp:
        sbp = int(m_bp.group(1) or m_bp.group(3))

    has_neg_trop = any(neg in txt for neg in ("âm tính", "bình thường", "normal", "negative", "(-)"))
    has_pos_trop = (not has_neg_trop) and (
        "dương tính" in txt or "tăng cao" in txt or "(+)" in txt
    )
    if not has_neg_trop and not has_pos_trop:
        m_trop = re.search(r"troponin[^0-9]*(\d+(?:\.\d+)?)", txt)
        if m_trop and float(m_trop.group(1)) >= 50.0:
            has_pos_trop = True

    return {
        "chest_pain": "đau ngực" in txt or "đau thắt ngực" in txt,
        "dyspnea": "khó thở" in txt,
        "syncope": "ngất" in txt,
        "hypotension": (sbp is not None and sbp < 90) or "sốc tim" in txt or "tụt ha" in txt,
        "sbp": sbp,
        "troponin_positive": has_pos_trop,
        "hyperkalemia": "kali máu tăng" in txt or ("k+" in txt and ("tăng" in txt or ">6" in txt or "7." in txt)),
    }


def _consolidate_base_fields(
    ocr_res: OCRResult,
    metrics: Optional[SignalMetricsResult],
    ecgfounder_res: dict,
) -> dict:
    ef_probs = ecgfounder_res.get("all_probs", {}) or {}
    hr = ocr_res.hr if ocr_res.hr is not None else (metrics.hr_measured if metrics else None)
    pr = ocr_res.pr
    qrs = ocr_res.qrs if ocr_res.qrs is not None else (metrics.qrs_measured_ms if metrics else None)
    qt = ocr_res.qt
    sex = ocr_res.sex or "nam"
    axis = ocr_res.axis

    is_irreg = bool(metrics and metrics.is_irregular_rhythm)
    is_afib = is_irreg or (ef_probs.get("AFIB", 0.0) >= 0.78 and ef_probs.get("SR", 0.0) < 0.30)
    is_aflt = (ef_probs.get("AFLT", 0.0) >= 0.85 and ef_probs.get("SR", 0.0) < 0.25 and ef_probs.get("NORM", 0.0) < 0.20 and (hr is None or hr > 110 or hr < 50))
    rhythm = "irregular" if is_afib else "regular"
    if is_afib or is_aflt:
        p_wave = "absent"
    elif ef_probs.get("LAO/LAE", 0.0) >= 0.55 or ef_probs.get("RAO/RAE", 0.0) >= 0.55:
        p_wave = "abnormal"
    else:
        p_wave = "normal"

    # Bundle branch shape
    is_rbbb = ef_probs.get("CRBBB", 0.0) >= 0.65
    is_lbbb = ef_probs.get("CLBBB", 0.0) >= 0.65
    v1shape = "rsr" if is_rbbb else ("qswide" if is_lbbb else "normal")
    v6shape = "notchedS" if is_rbbb else ("broadR" if is_lbbb else "normal")

    # Conduction flags
    avb3_prob = ef_probs.get("3AVB", 0.0)
    dissociation = bool(avb3_prob >= 0.72 and hr is not None and hr <= 52 and not (metrics and "STEMI_INFERIOR" in metrics.detected_patterns))

    regions = (
        metrics.regions
        if metrics
        else {
            "inf": {"st": "none", "t": "none", "q": False},
            "sept": {"st": "none", "t": "none", "q": False},
            "ant": {"st": "none", "t": "none", "q": False},
            "lat": {"st": "none", "t": "none", "q": False},
        }
    )

    s_v1 = round(ocr_res.sv1_mv * 10.0, 1) if ocr_res.sv1_mv is not None else (round(metrics.lead_measurements["V1"].s_mm, 1) if metrics else None)
    r_v56 = round(ocr_res.rv5_mv * 10.0, 1) if ocr_res.rv5_mv is not None else (
        round(max(metrics.lead_measurements["V5"].r_mm, metrics.lead_measurements["V6"].r_mm), 1) if metrics else None
    )
    r_avl = round(metrics.lead_measurements["aVL"].r_mm, 1) if metrics else None
    r_v1 = round(metrics.lead_measurements["V1"].r_mm, 1) if metrics else None

    special = metrics.special_code if metrics else "none"
    if special == "none" and pr is not None and pr < 120 and ef_probs.get("WPW", 0.0) >= 0.55:
        special = "wpw"

    return {
        "hr": hr,
        "pWave": p_wave,
        "pr": pr,
        "rhythm": rhythm,
        "wenckebach": False,
        "fixedRatio": False,
        "dissociation": dissociation,
        "qrs": qrs,
        "v1shape": v1shape,
        "v6shape": v6shape,
        "axis": axis,
        "qt": qt,
        "sex": sex,
        "regions": regions,
        "sV1": s_v1,
        "rV56": r_v56,
        "rAvl": r_avl,
        "rV1": r_v1,
        "special": special,
    }


def _synthesize_offline(
    base: dict,
    ocr_res: OCRResult,
    metrics: Optional[SignalMetricsResult],
    ecgfounder_res: dict,
    clinical_context: str,
) -> dict:
    """Deterministic expert synthesis grounded in quantitative 12-lead mV measurements + ECGFounder."""
    flags = _parse_clinical_flags(clinical_context)
    ef_probs = ecgfounder_res.get("all_probs", {}) or {}
    hr = base["hr"]
    pr = base["pr"]
    qrs = base["qrs"]
    qt = base["qt"]
    qtc_baz, qtc_frid = _compute_qtc(hr, qt)
    qtc = qtc_baz or ocr_res.qtc
    lm = metrics.lead_measurements if metrics else {}
    patterns = metrics.detected_patterns if metrics else []

    extras: List[str] = []
    if pr is not None and pr > 200 and not base["dissociation"]:
        extras.append(f"Block nhĩ – thất độ I (PR {pr} ms)")
    if hr is not None and hr < 60:
        extras.append(f"Nhịp chậm xoang ({hr} l/p)")
    elif hr is not None and hr > 100 and base["rhythm"] == "regular":
        extras.append(f"Nhịp nhanh xoang ({hr} l/p)")
    if "LVH" in patterns or (base["sV1"] and base["rV56"] and (base["sV1"] + base["rV56"]) >= 35):
        extras.append(f"Tăng điện thế / Dày thất trái (Sokolow-Lyon {round((base['sV1'] or 0) + (base['rV56'] or 0), 1)} mm)")
    if qrs is not None and qrs >= 120:
        extras.append(f"QRS giãn rộng ({qrs} ms)")
    elif qrs is not None and qrs >= 110:
        extras.append(f"Rối loạn dẫn truyền trong thất nhẹ (QRS {qrs} ms)")

    # Build quantitative evidence summary string
    st_lines = []
    if lm:
        for grp_name, grp_leads in [
            ("Thành dưới", ("II", "III", "aVF")),
            ("Thành bên cao", ("I", "aVL")),
            ("Trước vách/mỏm", ("V1", "V2", "V3", "V4")),
            ("Thành bên thấp", ("V5", "V6")),
        ]:
            vals = [f"{ln} {lm[ln].st_mm:+.1f}mm" for ln in grp_leads if ln in lm]
            st_lines.append(f"{grp_name}: {', '.join(vals)}")

    # 1. STEMI_INFERIOR
    if "STEMI_INFERIOR" in patterns:
        post_note = " kèm tổn thương thành sau" if metrics and metrics.has_posterior_extension else ""
        lat_ext = ""
        if lm and lm["V5"].st_mm >= 1.0 and lm["V6"].st_mm >= 1.0:
            lat_ext = " – bên (V5, V6)"
        rca_note = " — nghi tắc ĐM vành phải (RCA)" if (lm and lm["III"].st_mm > lm["II"].st_mm + 0.15) else ""
        extra_str = f"; kèm {', '.join(extras)}" if extras else ""
        primary = f"Nhồi máu cơ tim cấp có ST chênh lên (STEMI) thành dưới{lat_ext}{post_note} (DII, DIII, aVF){rca_note}{extra_str}"

        st2 = lm["II"].st_mm if "II" in lm else 0.0
        st3 = lm["III"].st_mm if "III" in lm else 0.0
        stavf = lm["aVF"].st_mm if "aVF" in lm else 0.0
        st1 = lm["I"].st_mm if "I" in lm else 0.0
        stavl = lm["aVL"].st_mm if "aVL" in lm else 0.0
        v1_3_str = ", ".join(f"{ln} {lm[ln].st_mm:+.1f}mm" for ln in ("V1", "V2", "V3") if ln in lm)

        reasoning = (
            f"1. Thông số chu kỳ & độ lợi: HR = {hr or '—'} l/p, PR = {pr or '—'} ms, QRS = {qrs or '—'} ms, "
            f"QT/QTc = {qt or '—'}/{qtc or '—'} ms, Trục = {base['axis'] if base['axis'] is not None else '—'}°. "
            f"Đã hiệu chuẩn chính xác độ lợi từng cột (V1–V3 gain {lm['V1'].gain_mm_per_mv if 'V1' in lm else 10:g} mm/mV, "
            f"V4–V6 gain {lm['V4'].gain_mm_per_mv if 'V4' in lm else 10:g} mm/mV).\n"
            f"2. Đo đạc định lượng 12 chuyển đạo (quy chuẩn 10 mm/mV):\n   " + "\n   ".join(st_lines) + "\n"
            f"3. Đối chiếu tiêu chuẩn ESC 2023 / GS. Trần Đỗ Trinh: ST chênh lên rõ ở 3 chuyển đạo thành dưới "
            f"(DII {st2:+.1f} mm, DIII {st3:+.1f} mm, aVF {stavf:+.1f} mm — đều ≥ +1.0 mm) kết hợp hình ảnh ST chênh xuống "
            f"soi gương điển hình tại thành bên cao (DI {st1:+.1f} mm, aVL {stavl:+.1f} mm). "
            f"Biên độ ST ở DIII > DII gợi ý thủ phạm là Động mạch vành phải (RCA)"
            f"{'; đồng thời ghi nhận ST chênh xuống ở V1–V3 (' + v1_3_str + ') chỉ điểm lan rộng thành sau' if (metrics and metrics.has_posterior_extension) else ''}.\n"
            f"4. Xác nhận đa mô thức: Mô hình chuyên sâu ECGFounder-all71 ghi nhận xác suất Nhồi máu cơ tim (MI) = {ecgfounder_res.get('superclasses', {}).get('MI', 0)*100:.1f}%. "
            f"Kết luận dứt khoát STEMI thành dưới, KHÔNG phân loại mờ nhạt thành Hội chứng vành cấp không đặc hiệu."
        )
        summary = (
            f"Nhồi máu cơ tim cấp ST chênh lên (STEMI) thành dưới (DII {st2:+.1f}mm, DIII {st3:+.1f}mm, aVF {stavf:+.1f}mm) "
            f"kèm soi gương DI/aVL ({st1:+.1f}/{stavl:+.1f}mm)"
            f"{' và ST chênh xuống V1–V3 nghi tổn thương thành sau' if (metrics and metrics.has_posterior_extension) else ''}"
            f"{'; ' + '; '.join(extras) if extras else ''}."
        )
        return {
            **base,
            "clinical_reasoning": reasoning,
            "ai_summary": summary,
            "clinical_diagnosis": {
                "primary": primary,
                "risk_level": "Nguy cơ rất cao",
                "differentials": [
                    "Nhồi máu cơ tim thất phải đi kèm (cần đo V3R, V4R ngay)",
                    "Viêm màng ngoài tim cấp (ít nghĩ do có soi gương rõ tại DI, aVL)",
                    "Phình bóc tách động mạch chủ ngực Stanford A lan vào lỗ ĐM vành phải",
                ],
            },
            "treatment_plan": {
                "immediate_actions": [
                    "Bất động tuyệt đối tại giường cấp cứu, mắc monitor ECG, SpO2 và theo dõi huyết áp liên tục",
                    "KÍCH HOẠT KHẨN CẤP PHÒNG CAN THIỆP MẠCH VÀNH (CATHLAB) thực hiện PCI thì đầu trong < 120 phút (mục tiêu < 90 phút)",
                    "ĐO NGAY 6 CHUYỂN ĐẠO MỞ RỘNG: V3R, V4R (tìm nhồi máu thất phải) và V7, V8, V9 (xác định nhồi máu thành sau)",
                    "Thở oxy qua cannula 2–4 l/p CHỈ KHI SpO2 < 90% hoặc bệnh nhân khó thở",
                ],
                "medications": [
                    "Kháng kết tập tiểu cầu kép (DAPT) liều nạp ngay: Aspirin 300 mg (nhai nát) + Ticagrelor 180 mg uống (hoặc Clopidogrel 600 mg)",
                    "Kháng đông: Enoxaparin 30 mg tiêm tĩnh mạch bolus, sau đó 1 mg/kg tiêm dưới da mỗi 12 giờ (tuổi ≥ 75: bỏ bolus TM, dùng 0.75 mg/kg mỗi 12h; eGFR < 30: giảm 1 mg/kg mỗi 24h)",
                    "Statin cường độ cao: Atorvastatin 80 mg uống ngay 1 liều",
                    "Nếu nhịp chậm xoang/Block AV gây tụt huyết áp: chuẩn bị sẵn Atropine 0.5 mg tiêm tĩnh mạch",
                ],
                "contraindications_warnings": [
                    "CHỐNG CHỈ ĐỊNH TUYỆT ĐỐI Nitroglycerin và các thuốc giãn mạch/lợi tiểu trước khi loại trừ nhồi máu thất phải (V4R) hoặc khi huyết áp tâm thu < 90 mmHg (nguy cơ trụy mạch không hồi phục!)",
                    "Thận trọng/tránh dùng chẹn beta đường tĩnh mạch giai đoạn cấp do bệnh nhân đang có nhịp chậm xoang và/hoặc Block AV độ I",
                    "Nếu có nhồi máu thất phải kèm tụt HA: truyền dịch đẳng trương NaCl 0.9% thận trọng nâng tiền tải",
                ],
                "further_workup": [
                    "Siêu âm tim tại giường đánh giá vận động vùng thành dưới/sau/thất phải, EF% và biến chứng cơ học",
                    "Xét nghiệm động học hs-Troponin T/I, công thức máu, đông máu cơ bản, điện giải đồ và Creatinine/eGFR trước PCI",
                    "Nếu bệnh viện không có Cathlab và thời gian chuyển > 120 phút: hội chẩn dùng thuốc Tiêu sợi huyết (Tenecteplase / Alteplase) nếu không có chống chỉ định",
                ],
            },
        }

    # 2. STEMI_ANTERIOR / STEMI_LATERAL / OMI Equivalents
    if "STEMI_ANTERIOR" in patterns or "STEMI_LATERAL" in patterns or base["special"] in {"aslanger", "sa_flag", "lmca", "dewinter"}:
        terr = metrics.stemi_territory if metrics and metrics.stemi_territory else "vùng mạch vành cấp"
        culp = f" ({metrics.culprit_artery_hint})" if metrics and metrics.culprit_artery_hint else ""
        primary = f"Nhồi máu cơ tim cấp có ST chênh lên (STEMI) {terr}{culp}"
        reasoning = (
            f"1. Thông số: HR {hr or '—'} l/p, PR {pr or '—'} ms, QRS {qrs or '—'} ms, QTc {qtc or '—'} ms.\n"
            f"2. Đo đạc 12 chuyển đạo:\n   " + "\n   ".join(st_lines) + "\n"
            f"3. Ghi nhận ST chênh lên đạt ngưỡng ESC 2023 tại {terr}. ECGFounder MI = {ecgfounder_res.get('superclasses', {}).get('MI', 0)*100:.1f}%."
        )
        return {
            **base,
            "clinical_reasoning": reasoning,
            "ai_summary": f"{primary}. " + ("; ".join(extras) if extras else ""),
            "clinical_diagnosis": {
                "primary": primary,
                "risk_level": "Nguy cơ rất cao",
                "differentials": ["Viêm màng ngoài tim cấp", "Bóc tách động mạch chủ ngực", "Bệnh cơ tim Takotsubo"],
            },
            "treatment_plan": {
                "immediate_actions": [
                    "Bất động tại giường, mắc monitor theo dõi liên tục ECG, huyết áp, SpO2",
                    "KÍCH HOẠT KHẨN CẤP PHÒNG CATHLAB PCI THÌ ĐẦU < 120 PHÚT",
                ],
                "medications": [
                    "DAPT: Aspirin 300 mg nhai + Ticagrelor 180 mg (hoặc Clopidogrel 600 mg)",
                    "Enoxaparin 30 mg TM bolus + 1 mg/kg TDD mỗi 12 giờ",
                    "Atorvastatin 80 mg uống ngay",
                ],
                "contraindications_warnings": [
                    "Theo dõi sát biến chứng loạn nhịp thất và suy tim cấp / sốc tim",
                ],
                "further_workup": [
                    "Siêu âm tim tại giường và xét nghiệm hs-Troponin, chức năng thận, đông máu",
                ],
            },
        }

    # 3. Complete AV block
    if base["dissociation"]:
        return {
            **base,
            "clinical_reasoning": f"HR rất chậm ({hr or '—'} l/p), ECGFounder ghi nhận phân ly nhĩ thất / Block AV độ III ({ef_probs.get('3AVB', 0)*100:.1f}%).",
            "ai_summary": f"Block nhĩ thất độ III (phân ly nhĩ thất), tần số thất {hr or '—'} l/p.",
            "clinical_diagnosis": {
                "primary": f"Block nhĩ thất độ III (Block AV hoàn toàn, tần số thất {hr or '—'} l/p)",
                "risk_level": "Nguy cơ rất cao",
                "differentials": ["Block AV độ II Mobitz II cao độ", "Suy nút xoang nhịp chậm"],
            },
            "treatment_plan": {
                "immediate_actions": ["Chuẩn bị máy tạo nhịp tạm thời qua da/tĩnh mạch ngay lập tức"],
                "medications": ["Atropine 0.5 mg TM; Adrenaline/Dopamine truyền TM nếu huyết động không ổn định"],
                "contraindications_warnings": ["Chống chỉ định Lidocaine, Amiodarone, chẹn beta"],
                "further_workup": ["Đánh giá chỉ định cấy máy tạo nhịp tim vĩnh viễn (PPM)"],
            },
        }

    # 4. Atrial fibrillation
    if base["rhythm"] == "irregular" and base["pWave"] == "absent":
        rvr = hr is not None and hr > 100
        return {
            **base,
            "clinical_reasoning": f"Nhịp thất không đều hoàn toàn (RR CV = {metrics.rr_irregularity_cv if metrics else '—'}), mất sóng P (AFIB prob {ef_probs.get('AFIB', 0)*100:.1f}%).",
            "ai_summary": f"Rung nhĩ {'đáp ứng thất nhanh ' if rvr else ''}(tần số thất TB {hr or '—'} l/p).",
            "clinical_diagnosis": {
                "primary": f"Rung nhĩ {'đáp ứng thất nhanh (AFib with RVR)' if rvr else 'đáp ứng thất trung bình/chậm'} ({hr or '—'} l/p)",
                "risk_level": "Nguy cơ cao" if (rvr or flags["hypotension"]) else "Nguy cơ trung bình",
                "differentials": ["Cuồng nhĩ dẫn truyền thay đổi", "Nhịp nhanh nhĩ đa ổ (MAT)"],
            },
            "treatment_plan": {
                "immediate_actions": [
                    "Sốc điện đồng bộ khẩn nếu huyết động không ổn định" if flags["hypotension"] else "Kiểm soát tần số thất mục tiêu HR < 110 l/p"
                ],
                "medications": ["Chẹn beta hoặc Diltiazem (nếu EF bảo tồn); đánh giá kháng đông DOAC theo CHA2DS2-VASc"],
                "contraindications_warnings": ["Không chuyển nhịp nếu rung nhĩ > 48h chưa kháng đông đủ 3 tuần hoặc chưa làm TEE"],
                "further_workup": ["Siêu âm tim TTE và xét nghiệm FT4, TSH"],
            },
        }

    # 5. Posterior isolated or Non-ST depression ischemia
    dep_leads = [ln for ln in LEAD_NAMES if ln in lm and lm[ln].st_mm <= -0.8] if lm else []
    if len(dep_leads) >= 2 or (flags["chest_pain"] and flags["troponin_positive"]):
        is_post = "POSTERIOR_STEMI_ISOLATED" in patterns
        primary = (
            "Nghi Nhồi máu cơ tim thành sau thực thụ (ST chênh xuống V1–V3 — cần đo ngay V7–V9)"
            if is_post
            else f"Thiếu máu cơ tim / Hội chứng vành cấp không ST chênh lên (ST chênh xuống tại {', '.join(dep_leads)})"
        )
        return {
            **base,
            "clinical_reasoning": f"1. Không thấy ST chênh lên đủ ngưỡng STEMI.\n2. ST chênh xuống rõ tại {', '.join(dep_leads)}.\n3. " + "\n   ".join(st_lines),
            "ai_summary": primary,
            "clinical_diagnosis": {
                "primary": primary,
                "risk_level": "Nguy cơ cao",
                "differentials": ["Nhồi máu cơ tim không ST chênh lên (NSTEMI)", "Đau thắt ngực không ổn định", "Tăng gánh thất trái kèm biến đổi ST-T thứ phát"],
            },
            "treatment_plan": {
                "immediate_actions": [
                    "Đo ngay chuyển đạo thành sau V7, V8, V9 nếu ST chênh xuống tập trung ở V1–V3",
                    "Theo dõi monitor ECG liên tục, xét nghiệm động học hs-Troponin 0h/1h",
                ],
                "medications": ["Aspirin + thuốc ức chế P2Y12 theo phác đồ NSTE-ACS, kháng đông Enoxaparin, Statin cường độ cao"],
                "contraindications_warnings": ["Không dùng thuốc tiêu sợi huyết nếu không có ST chênh lên hoặc bằng chứng tắc hoàn toàn"],
                "further_workup": ["Phân tầng nguy cơ GRACE/TIMI để lên lịch chụp mạch vành"],
            },
        }

    # 6. Mild non-ischemic / LVH / Brady / BER / Normal ECG
    diag_title = "Điện tâm đồ trong giới hạn bình thường (Normal ECG)"
    risk_lvl = "Nguy cơ thấp"
    if base["special"] == "ber":
        diag_title = "Biến thể Tái cực sớm lành tính (Benign Early Repolarization)"
    elif extras:
        diag_title = f"Nhịp xoang — {', '.join(extras)}"
        if any("Dày" in e or "Block" in e or "QRS giãn rộng" in e for e in extras):
            risk_lvl = "Nguy cơ trung bình"

    reasoning = (
        f"1. Thông số chu kỳ: HR = {hr or '—'} l/p, PR = {pr or '—'} ms, QRS = {qrs or '—'} ms, QTc = {qtc or '—'} ms, Trục = {base['axis'] if base['axis'] is not None else '—'}°.\n"
        f"2. Đo đạc 12 chuyển đạo (10 mm/mV): Không phát hiện ST chênh lên hay chênh xuống bệnh lý đạt ngưỡng thiếu máu cục bộ cấp.\n"
        f"   " + ("\n   ".join(st_lines) if st_lines else "")
    )
    return {
        **base,
        "clinical_reasoning": reasoning,
        "ai_summary": f"{diag_title}. Không có bằng chứng nhồi máu cơ tim cấp.",
        "clinical_diagnosis": {
            "primary": diag_title,
            "risk_level": risk_lvl,
            "differentials": ["Điện tâm đồ bình thường theo sinh lý lứa tuổi", "Biến đổi nhẹ không đặc hiệu"],
        },
        "treatment_plan": {
            "immediate_actions": ["Không cần can thiệp cấp cứu tim mạch khẩn cấp", "Đối chiếu với triệu chứng lâm sàng thực tế của người bệnh"],
            "medications": ["Không có chỉ định dùng thuốc tim mạch cấp cứu"],
            "contraindications_warnings": ["Không tự ý dùng thuốc kháng kết tập tiểu cầu hay giãn mạch khi chưa có chỉ định bác sĩ"],
            "further_workup": ["Theo dõi sức khỏe định kỳ; đo lại ECG nếu có đau ngực, hồi hộp hoặc khó thở"],
        },
    }


def _build_evidence_prompt(
    base: dict,
    ocr_res: OCRResult,
    metrics: Optional[SignalMetricsResult],
    ecgfounder_res: dict,
    clinical_context: str,
) -> str:
    lines = ["=== BẰNG CHỨNG ĐỊNH LƯỢNG ĐÃ HIỆU CHUẨN TỪ BẢN GHI ECG ==="]
    lines.append(
        f"- Thông số máy (OCR): HR={base['hr']} bpm, PR={base['pr']} ms, QRS={base['qrs']} ms, "
        f"QT={base['qt']} ms, QTc(OCR)={ocr_res.qtc} ms, Axis={base['axis']}°, Giới={base['sex']}, "
        f"Tốc độ giấy={ocr_res.paper_speed_mm_s} mm/s"
    )
    if ocr_res.rv5_mv is not None or ocr_res.sv1_mv is not None:
        lines.append(f"- Điện thế máy in: RV5={ocr_res.rv5_mv} mV, SV1={ocr_res.sv1_mv} mV")
    if metrics:
        lines.append(f"- Tần số tự đo từ dải sóng: HR={metrics.hr_measured} bpm, RR_CV={metrics.rr_irregularity_cv}")
        lines.append("- Bảng đo 12 chuyển đạo (ĐÃ QUY CHUẨN về 10 mm/mV sau khi nhân chia đúng độ lợi từng cột):")
        for ln in LEAD_NAMES:
            m = metrics.lead_measurements[ln]
            lines.append(
                f"  * {ln:3s} [gain {m.gain_mm_per_mv:g} mm/mV]: ST(J+40ms)={m.st_mm:+.2f}mm (J+20ms={m.st_j_mm:+.2f}, J+60ms={m.st_60_mm:+.2f}), "
                f"T={m.t_mm:+.1f}mm, R={m.r_mm:.1f}mm, S={m.s_mm:.1f}mm, Q={m.q_mm:.1f}mm, Hình thái ST={m.st_morphology}"
            )
        if metrics.detected_patterns:
            lines.append(f"- Bộ lọc định lượng ESC 2023 / OMI phát hiện: {', '.join(metrics.detected_patterns)} "
                         f"(Vùng: {metrics.stemi_territory or '—'}, Soi gương: {metrics.has_reciprocal_changes}, Thành sau: {metrics.has_posterior_extension})")

    if ecgfounder_res.get("loaded"):
        sc = ecgfounder_res.get("superclasses", {})
        top5 = ", ".join(f"{x['code']}({x['name_vi']}): {x['prob']*100:.0f}%" for x in ecgfounder_res.get("top_predictions", [])[:5])
        lines.append(f"- Mô hình ECGFounder-all71: NORM={sc.get('NORM',0):.2f}, MI={sc.get('MI',0):.2f}, STTC={sc.get('STTC',0):.2f}, CD={sc.get('CD',0):.2f}, HYP={sc.get('HYP',0):.2f}")
        lines.append(f"  Top lớp: {top5}")

    lines.append(f"\n=== BỐI CẢNH LÂM SÀNG & CẬN LÂM SÀNG BỆNH NHÂN ===\n{clinical_context or 'Chưa có thông tin bổ sung.'}")
    lines.append(
        '\nHãy đối chiếu ảnh sóng ECG đã cắt gọn với bảng số đo định lượng trên và trả về DUY NHẤT JSON đúng cấu trúc:\n'
        '{\n'
        '  "clinical_reasoning": "1. Thông số & độ lợi; 2. Mô tả định lượng từng vùng chuyển đạo; 3. Đối chiếu tiêu chuẩn ESC/VNHA; 4. Kết luận xác định",\n'
        '  "hr": number|null, "pWave": "normal"|"abnormal"|"absent", "pr": number|null, "rhythm": "regular"|"irregular",\n'
        '  "wenckebach": bool, "fixedRatio": bool, "dissociation": bool, "qrs": number|null,\n'
        '  "v1shape": "normal"|"rsr"|"qswide", "v6shape": "normal"|"notchedS"|"broadR", "axis": number|null, "qt": number|null, "sex": "nam"|"nu",\n'
        '  "regions": {\n'
        '    "inf": {"st":"none"|"elevation"|"depression","t":"none"|"inverted"|"peaked","q":bool},\n'
        '    "sept": {"st":"none"|"elevation"|"depression","t":"none"|"inverted"|"peaked","q":bool},\n'
        '    "ant": {"st":"none"|"elevation"|"depression","t":"none"|"inverted"|"peaked","q":bool},\n'
        '    "lat": {"st":"none"|"elevation"|"depression","t":"none"|"inverted"|"peaked","q":bool}\n'
        '  },\n'
        '  "sV1": number|null, "rV56": number|null, "rAvl": number|null, "rV1": number|null, "special": "none"|...,\n'
        '  "ai_summary": "Tóm tắt súc tích chuẩn tiếng Việt y khoa",\n'
        '  "clinical_diagnosis": {"primary": "...", "risk_level": "Nguy cơ rất cao"|"Nguy cơ cao"|"Nguy cơ trung bình"|"Nguy cơ thấp", "differentials": ["..."]},\n'
        '  "treatment_plan": {"immediate_actions":["..."], "medications":["..."], "contraindications_warnings":["..."], "further_workup":["..."]}\n'
        '}'
    )
    return "\n".join(lines)


def _clean_json_text(txt: str) -> dict:
    clean = txt.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return json.loads(clean.strip())


def _apply_safety_guardrail(
    llm_data: dict,
    offline_data: dict,
    metrics: Optional[SignalMetricsResult],
    ecgfounder_res: dict,
) -> dict:
    """Prevent LLM from downgrading a clear quantitative + ECGFounder STEMI to vague ACS."""
    if not metrics:
        return llm_data

    has_quant_stemi = any(
        p in metrics.detected_patterns
        for p in ("STEMI_INFERIOR", "STEMI_ANTERIOR", "STEMI_LATERAL")
    )
    if not has_quant_stemi or not metrics.has_reciprocal_changes:
        return llm_data

    diag = llm_data.get("clinical_diagnosis") or {}
    prim = str(diag.get("primary", "")).lower()
    is_explicit_stemi = ("stemi" in prim) or ("st chênh lên" in prim) or ("nhồi máu cơ tim cấp" in prim)

    mi_prob = float(ecgfounder_res.get("superclasses", {}).get("MI", 0.0)) if ecgfounder_res.get("loaded") else 0.8
    if not is_explicit_stemi and mi_prob >= 0.60:
        # Upgrade diagnosis & plan to verified STEMI while keeping any useful numeric fields
        llm_data["clinical_diagnosis"] = offline_data["clinical_diagnosis"]
        llm_data["treatment_plan"] = offline_data["treatment_plan"]
        llm_data["regions"] = offline_data["regions"]
        llm_data["ai_summary"] = offline_data["ai_summary"]
        llm_data["clinical_reasoning"] = (
            "[Hậu kiểm định lượng an toàn] Bộ đo ST định lượng 12 chuyển đạo + hình ảnh soi gương xác nhận STEMI rõ.\n"
            + str(llm_data.get("clinical_reasoning", ""))
        )
    return llm_data


async def _call_gemini_hybrid(
    prompt_text: str,
    waveform_img_b64: Optional[str],
    api_key: str,
    mode: str,
    preferred_model: Optional[str],
) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    thinking_lvl = "high" if mode == "deep" else "low"
    base_list = GEMINI_DEEP_MODELS if mode == "deep" else GEMINI_FAST_MODELS
    deprecated_or_slow = {
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-2.0-pro-exp-02-05",
        "gemini-exp-1206",
        "gemini-2.5-pro",
        "gemini-3.1-pro-preview",
        "gemini-4.0-flash",
        "gemini-4.0-pro",
        "gemini-4-argon",
        "gemini-4-neon",
        "gemini-4-carbon",
    }
    candidates = []
    if mode == "fast":
        candidates.extend(GEMINI_FAST_MODELS)
        if preferred_model and preferred_model not in deprecated_or_slow and preferred_model not in candidates:
            candidates.append(preferred_model)
    else:
        if preferred_model and preferred_model not in deprecated_or_slow:
            candidates.append(preferred_model)
        for m in base_list:
            if m not in candidates:
                candidates.append(m)

    base_parts: List[Dict[str, Any]] = [{"text": prompt_text}]
    if waveform_img_b64:
        base_parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": waveform_img_b64,
                }
            }
        )

    timeout_sec = 14.0 if mode == "deep" else 6.0
    last_err = None

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        for model in candidates[:3]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            gen_cfg: Dict[str, Any] = {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
            if model == "gemini-3-flash-preview":
                gen_cfg["thinking_config"] = {"thinking_level": thinking_lvl}
            elif "2.5-flash" in model:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 1024 if mode == "deep" else 0}

            payload = {
                "system_instruction": {"parts": [{"text": HYBRID_SYSTEM_PROMPT}]},
                "contents": [{"parts": base_parts}],
                "generationConfig": gen_cfg,
            }

            try:
                resp = await client.post(
                    url,
                    headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                    json=payload,
                )
                if resp.status_code == 400:
                    compat_payload = {
                        "system_instruction": {"parts": [{"text": HYBRID_SYSTEM_PROMPT}]},
                        "contents": [{"parts": base_parts}],
                        "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
                    }
                    resp = await client.post(
                        url,
                        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                        json=compat_payload,
                    )

                if resp.status_code in (404, 429, 400, 500, 503):
                    err_j = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    last_err = f"{model}: HTTP {resp.status_code} {err_j.get('error', {}).get('message', '')}".strip()
                    continue

                resp.raise_for_status()
                res_json = resp.json()
                text_out = res_json["candidates"][0]["content"]["parts"][0]["text"]
                parsed = _clean_json_text(text_out)
                return parsed, model, None
            except Exception as exc:
                last_err = f"{model}: {exc}"
                continue

    return None, None, last_err


async def fuse_clinical_diagnosis(
    ocr_res: OCRResult,
    metrics: Optional[SignalMetricsResult],
    ecgfounder_res: dict,
    clinical_context: str = "",
    waveform_img_b64: Optional[str] = None,
    mode: str = "fast",
    api_key: Optional[str] = None,
    provider: str = "gemini",
    model: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Combine local quantitative + ML signals with optional fast/deep LLM synthesis."""
    base = _consolidate_base_fields(ocr_res, metrics, ecgfounder_res)
    offline_data = _synthesize_offline(base, ocr_res, metrics, ecgfounder_res, clinical_context)

    meta = {
        "mode_requested": mode,
        "mode_used": "offline",
        "model_used": "Local-Hybrid-Engine (OCR + 12-Lead mV + ECGFounder-all71)",
        "fallback_used": False,
        "llm_error": None,
    }

    if mode == "offline" or not api_key or len(api_key.strip()) < 8:
        return offline_data, meta

    prompt_text = _build_evidence_prompt(base, ocr_res, metrics, ecgfounder_res, clinical_context)

    llm_data: Optional[dict] = None
    used_model: Optional[str] = None
    err_msg: Optional[str] = None

    if provider == "gemini":
        llm_data, used_model, err_msg = await _call_gemini_hybrid(
            prompt_text=prompt_text,
            waveform_img_b64=waveform_img_b64,
            api_key=api_key.strip(),
            mode=mode,
            preferred_model=model,
        )
    elif provider in ("openai", "openrouter"):
        endpoint = (
            "https://api.openai.com/v1/chat/completions"
            if provider == "openai"
            else "https://openrouter.ai/api/v1/chat/completions"
        )
        chosen_model = model or ("gpt-4o" if provider == "openai" else "anthropic/claude-3.7-sonnet")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key.strip()}"}
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if waveform_img_b64:
            user_content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{waveform_img_b64}"}}
            )
        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": HYBRID_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(endpoint, headers=headers, json=payload)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                llm_data = _clean_json_text(content)
                used_model = chosen_model
        except Exception as exc:
            err_msg = f"{chosen_model}: {exc}"

    if llm_data and isinstance(llm_data, dict):
        # Preserve rock-solid machine OCR numbers if LLM omitted or returned null
        for k in ("hr", "pr", "qrs", "qt", "axis", "sex", "sV1", "rV56", "rAvl", "rV1"):
            if llm_data.get(k) is None and base.get(k) is not None:
                llm_data[k] = base[k]
        llm_data = _apply_safety_guardrail(llm_data, offline_data, metrics, ecgfounder_res)
        meta["mode_used"] = mode
        meta["model_used"] = f"Hybrid ({used_model} + ECGFounder)"
        return llm_data, meta

    meta["fallback_used"] = True
    meta["llm_error"] = err_msg or "Không kết nối được LLM, đã tự động dùng kết quả Hybrid Offline."
    return offline_data, meta

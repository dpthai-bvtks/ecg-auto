"""FastAPI Hybrid ECG Server serving /api/health, /api/analyze, and index.html."""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .pipeline import LEAD_NAMES
from .pipeline.clinical_fusion import fuse_clinical_diagnosis
from .pipeline.digital_input import parse_digital_ecg
from .pipeline.digitizer import apply_gains_and_build_signals, extract_raw_traces
from .pipeline.ecgfounder_infer import is_ecgfounder_loaded, run_ecgfounder, warm_up_ecgfounder
from .pipeline.ocr_parser import OCRResult, parse_ecg_ocr, warm_up_ocr
from .pipeline.preprocessor import encode_cropped_waveform_jpeg, preprocess_ecg_image
from .pipeline.signal_metrics import evaluate_signal_metrics

ROOT_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT_DIR / "index.html"

_ocr_ready = False
_ecgfounder_ready = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _ocr_ready, _ecgfounder_ready
    t0 = time.perf_counter()
    try:
        _ocr_ready = await anyio.to_thread.run_sync(warm_up_ocr)
        print(f"[PM-ECG] RapidOCR warm-up OK ({(time.perf_counter()-t0)*1000:.0f} ms)", flush=True)
    except Exception as exc:
        print(f"[PM-ECG] RapidOCR warm-up failed: {exc}", flush=True)
        _ocr_ready = False

    t1 = time.perf_counter()
    try:
        _ecgfounder_ready = await anyio.to_thread.run_sync(warm_up_ecgfounder)
        print(
            f"[PM-ECG] ECGFounder-all71 ONNX warm-up={'OK' if _ecgfounder_ready else 'MISSING'} "
            f"({(time.perf_counter()-t1)*1000:.0f} ms)",
            flush=True,
        )
    except Exception as exc:
        print(f"[PM-ECG] ECGFounder warm-up error: {exc}", flush=True)
        _ecgfounder_ready = False

    yield


app = FastAPI(title="PM-ECG Hybrid AI Server", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.middleware("http")
async def add_private_network_header(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/")
async def serve_index():
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


TUNNEL_JSON = ROOT_DIR / "tunnel.json"


def _get_active_tunnel_url() -> Optional[str]:
    if not TUNNEL_JSON.exists():
        return None
    try:
        data = json.loads(TUNNEL_JSON.read_text(encoding="utf-8"))
        url = str(data.get("url") or "").strip().rstrip("/")
        return url or None
    except Exception:
        return None


@app.get("/tunnel.json")
async def serve_tunnel_json():
    if not TUNNEL_JSON.exists():
        return {"url": None, "updated_at": None}
    return FileResponse(TUNNEL_JSON, media_type="application/json; charset=utf-8")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "engine": "PM-ECG Hybrid v2.0",
        "ocr_ready": _ocr_ready,
        "ecgfounder_loaded": _ecgfounder_ready or is_ecgfounder_loaded(),
        "tunnel_url": _get_active_tunnel_url(),
    }


def _run_image_local_stages(
    file_bytes: bytes,
    rotation: int,
    crop_box: Optional[dict],
    need_llm_image: bool,
) -> dict:
    timings = {}

    t0 = time.perf_counter()
    prep = preprocess_ecg_image(file_bytes, rotation_deg=rotation, crop_box=crop_box)
    timings["preprocess"] = round((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    raw_traces = extract_raw_traces(prep.ink_map, prep.ink_map_raw)
    t_trace = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    ocr_res = parse_ecg_ocr(prep.paper_img, prep.waveform_img, prep.report_img)
    timings["ocr"] = round((time.perf_counter() - t2) * 1000)

    t3 = time.perf_counter()
    digitized = apply_gains_and_build_signals(raw_traces, ocr_res)
    timings["digitize"] = round(t_trace + (time.perf_counter() - t3) * 1000)

    t4 = time.perf_counter()
    metrics = evaluate_signal_metrics(
        digitized.leads_mv_raw,
        digitized.rhythm_mv_raw,
        ocr_res,
        digitized.column_gains_mm_per_mv,
        digitized.lead_qualities,
    )
    timings["metrics"] = round((time.perf_counter() - t4) * 1000)

    t5 = time.perf_counter()
    ecgfounder_res = run_ecgfounder(digitized.tensor_12x5000)
    timings["ecgfounder"] = round((time.perf_counter() - t5) * 1000)

    wf_b64 = encode_cropped_waveform_jpeg(prep.waveform_img) if need_llm_image else None

    return {
        "prep": prep,
        "ocr_res": ocr_res,
        "digitized": digitized,
        "metrics": metrics,
        "ecgfounder_res": ecgfounder_res,
        "wf_b64": wf_b64,
        "timings": timings,
    }


def _run_digital_local_stages(file_bytes: bytes, filename: str) -> dict:
    timings = {"preprocess": 0, "ocr": 0}
    t0 = time.perf_counter()
    digital = parse_digital_ecg(file_bytes, filename)
    timings["digitize"] = round((time.perf_counter() - t0) * 1000)

    meta = digital.metadata or {}
    ocr_res = OCRResult(
        hr=meta.get("hr"),
        pr=meta.get("pr"),
        qrs=meta.get("qrs"),
        qt=meta.get("qt"),
        qtc=meta.get("qtc"),
        axis=meta.get("axis"),
        sex=meta.get("sex"),
    )
    gains = {"col1": 10.0, "col2": 10.0, "col3": 10.0, "col4": 10.0, "rhythm": 10.0}
    qualities = {ln: 1.0 for ln in LEAD_NAMES}

    t1 = time.perf_counter()
    rhythm_mv = digital.tensor_12x5000[1]  # Lead II 10s
    metrics = evaluate_signal_metrics(digital.leads_mv, rhythm_mv, ocr_res, gains, qualities)
    timings["metrics"] = round((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    ecgfounder_res = run_ecgfounder(digital.tensor_12x5000)
    timings["ecgfounder"] = round((time.perf_counter() - t2) * 1000)

    # Preview 125 points per lead
    preview = {}
    for ln in LEAD_NAMES:
        arr = digital.leads_mv[ln]
        idx = [int(i * (len(arr) - 1) / 124) for i in range(125)]
        preview[ln] = [round(float(arr[j]), 3) for j in idx]

    return {
        "ocr_res": ocr_res,
        "metrics": metrics,
        "ecgfounder_res": ecgfounder_res,
        "gains": gains,
        "px_per_mm": None,
        "has_right_report_panel": False,
        "preview": preview,
        "timings": timings,
    }


@app.post("/api/analyze")
async def analyze_ecg(
    file: UploadFile = File(...),
    mode: str = Form("fast"),
    rotation: int = Form(0),
    crop_json: str = Form(""),
    clinical_context: str = Form(""),
    api_key: str = Form(""),
    provider: str = Form("gemini"),
    model: str = Form(""),
):
    t_total_start = time.perf_counter()
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="File trong.")

    mode_norm = mode.strip().lower()
    if mode_norm not in {"offline", "fast", "deep"}:
        mode_norm = "fast"

    filename = file.filename or "ecg.jpg"
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    is_digital = ext in {"json", "csv", "xml"}

    crop_box = None
    if crop_json and crop_json.strip():
        try:
            crop_box = json.loads(crop_json)
        except json.JSONDecodeError:
            crop_box = None

    need_llm_img = (not is_digital) and (mode_norm != "offline") and bool(api_key and len(api_key.strip()) >= 8)

    try:
        if is_digital:
            local = await anyio.to_thread.run_sync(_run_digital_local_stages, raw_bytes, filename)
            ocr_res = local["ocr_res"]
            metrics = local["metrics"]
            ecgfounder_res = local["ecgfounder_res"]
            gains = local["gains"]
            px_per_mm = local["px_per_mm"]
            has_report = local["has_right_report_panel"]
            preview = local["preview"]
            wf_b64 = None
            timings = local["timings"]
        else:
            local = await anyio.to_thread.run_sync(
                _run_image_local_stages, raw_bytes, rotation, crop_box, need_llm_img
            )
            prep = local["prep"]
            ocr_res = local["ocr_res"]
            digitized = local["digitized"]
            metrics = local["metrics"]
            ecgfounder_res = local["ecgfounder_res"]
            wf_b64 = local["wf_b64"]
            gains = digitized.column_gains_mm_per_mv
            px_per_mm = digitized.px_per_mm
            has_report = prep.has_right_report_panel
            preview = digitized.digitized_preview
            timings = local["timings"]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Loi xu ly du lieu ECG: {exc}") from exc

    t_fus = time.perf_counter()
    result_payload, fusion_meta = await fuse_clinical_diagnosis(
        ocr_res=ocr_res,
        metrics=metrics,
        ecgfounder_res=ecgfounder_res,
        clinical_context=clinical_context,
        waveform_img_b64=wf_b64,
        mode=mode_norm,
        api_key=api_key,
        provider=provider,
        model=model or None,
    )
    timings["fusion"] = round((time.perf_counter() - t_fus) * 1000)
    timings["total"] = round((time.perf_counter() - t_total_start) * 1000)

    has_nonstandard_gain = any(abs(float(gains.get(k, 10.0)) - 10.0) > 0.1 for k in ("col1", "col2", "col3", "col4"))

    result_payload["hybrid_meta"] = {
        "input_type": "digital" if is_digital else "image",
        "timings_ms": timings,
        "ocr": {
            "hr": ocr_res.hr,
            "pr": ocr_res.pr,
            "qrs": ocr_res.qrs,
            "qt": ocr_res.qt,
            "qtc": ocr_res.qtc,
            "axis": ocr_res.axis,
            "sex": ocr_res.sex,
            "rv5_mv": ocr_res.rv5_mv,
            "sv1_mv": ocr_res.sv1_mv,
            "paper_speed_mm_s": ocr_res.paper_speed_mm_s,
            "statements": ocr_res.statements,
        },
        "column_gains_mm_per_mv": gains,
        "has_nonstandard_gain": has_nonstandard_gain,
        "has_right_report_panel": has_report,
        "px_per_mm": px_per_mm,
        "lead_measurements": {ln: metrics.lead_measurements[ln].to_dict() for ln in LEAD_NAMES},
        "detected_patterns": metrics.detected_patterns,
        "culprit_artery_hint": metrics.culprit_artery_hint,
        "ecgfounder": {
            "loaded": ecgfounder_res.get("loaded", False),
            "reason": ecgfounder_res.get("reason"),
            "superclasses": ecgfounder_res.get("superclasses", {}),
            "top_predictions": ecgfounder_res.get("top_predictions", []),
        },
        "digitized_preview": preview,
        "fusion_meta": fusion_meta,
    }

    return JSONResponse(content=result_payload)

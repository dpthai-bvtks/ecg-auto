"""Silent background launcher for PM-ECG Hybrid AI Server (pythonw.exe safe)."""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8785
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"
MAX_LOG_BYTES = 2 * 1024 * 1024  # 2 MB


def is_server_alive() -> bool:
    """Return True if PM-ECG backend is already healthy on port 8785."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                return "PM-ECG" in body
    except Exception:
        return False
    return False


def _open_log_stream(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
        log_path.write_text("", encoding="utf-8")
    return open(log_path, mode="a", encoding="utf-8", errors="replace", buffering=1)


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    os.chdir(root_dir)
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    os.environ["PYTHONUTF8"] = "1"

    if is_server_alive():
        return 0

    log_path = root_dir / "backend" / "server.log"
    log_fp = _open_log_stream(log_path)
    # pythonw.exe sets stdout/stderr to None; uvicorn crashes on isatty() without real streams
    sys.stdout = log_fp
    sys.stderr = log_fp

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(log_fp)],
        force=True,
    )

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n===== PM-ECG Background Server Starting [{stamp}] =====", flush=True)

    try:
        model_path = root_dir / "backend" / "models" / "ecg_founder_all71.onnx"
        labels_path = root_dir / "backend" / "models" / "labels_all71.json"
        if not model_path.exists() or not labels_path.exists():
            print("[PM-ECG] Downloading missing ECGFounder model files...", flush=True)
            from backend.download_models import ensure_models

            ensure_models()

        if is_server_alive():
            print("[PM-ECG] Server already running; exiting duplicate instance.", flush=True)
            return 0

        import uvicorn

        uvicorn.run(
            "backend.server:app",
            host=HOST,
            port=PORT,
            use_colors=False,
            log_level="info",
        )
    except SystemExit as exc:
        # Handle race where another startup instance bound 8785 right before uvicorn.run
        if is_server_alive():
            print("[PM-ECG] Another instance already bound port 8785; exiting cleanly.", flush=True)
            return 0
        print(f"[PM-ECG] Server exited with code {exc.code}", flush=True)
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception:
        print("[PM-ECG] Fatal error in background server:", flush=True)
        traceback.print_exc(file=log_fp)
        return 1
    finally:
        try:
            log_fp.flush()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

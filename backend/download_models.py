"""Download ECGFounder ONNX model and 71-class labels from HuggingFace using httpx."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "https://huggingface.co/ghirani33/ecgfounder-onnx/resolve/main"
MODELS_DIR = Path(__file__).resolve().parent / "models"

FILES = [
    {
        "remote": f"{BASE_URL}/onnx_models/ecg_founder_all71.onnx",
        "local": MODELS_DIR / "ecg_founder_all71.onnx",
        "min_bytes": 100 * 1024 * 1024,  # ~118 MB
    },
    {
        "remote": f"{BASE_URL}/labels_all71.json",
        "local": MODELS_DIR / "labels_all71.json",
        "min_bytes": 500,
    },
]


def download_file(url: str, dest: Path, min_bytes: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"[OK] Da ton tai: {dest.name} ({dest.stat().st_size:,} bytes)", flush=True)
        return

    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    print(f"[Downloading] {url} -> {dest}", flush=True)
    t0 = time.time()
    downloaded = 0

    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=120.0)) as client:
            with client.stream("GET", url, headers={"User-Agent": "PM-ECG/2.0"}) as resp:
                resp.raise_for_status()
                total = resp.headers.get("content-length")
                total_int = int(total) if total else 0
                last_report = 0.0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=512 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_report >= 2.0 or (total_int and downloaded == total_int):
                            if total_int:
                                pct = downloaded * 100.0 / total_int
                                print(
                                    f"  ... {downloaded / (1024*1024):.1f} / {total_int / (1024*1024):.1f} MB ({pct:.1f}%)",
                                    flush=True,
                                )
                            else:
                                print(f"  ... {downloaded / (1024*1024):.1f} MB", flush=True)
                            last_report = now

        size = tmp_path.stat().st_size
        if size < min_bytes:
            raise RuntimeError(f"File tai ve qua nho ({size} bytes < {min_bytes} bytes)")

        os.replace(tmp_path, dest)
        elapsed = time.time() - t0
        print(f"[OK] Hoan tat {dest.name} ({size:,} bytes) trong {elapsed:.1f}s", flush=True)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def ensure_models() -> bool:
    for item in FILES:
        download_file(item["remote"], item["local"], item["min_bytes"])
    return True


if __name__ == "__main__":
    try:
        ensure_models()
    except Exception as exc:
        print(f"[ERROR] Khong the tai model: {exc}", file=sys.stderr)
        sys.exit(1)

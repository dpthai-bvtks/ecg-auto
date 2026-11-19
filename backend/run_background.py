"""Silent background launcher for PM-ECG Hybrid AI Server + Cloudflare Tunnel (pythonw.exe safe)."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8785
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"
MAX_LOG_BYTES = 2 * 1024 * 1024  # 2 MB
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
TUNNEL_REGEX = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


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


def _ensure_cloudflared_binary(root_dir: Path) -> Path:
    bin_path = root_dir / "backend" / "bin" / "cloudflared.exe"
    if bin_path.exists() and bin_path.stat().st_size > 10_000_000:
        return bin_path

    bin_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = bin_path.with_suffix(".exe.tmp")
    print("[PM-ECG] Downloading cloudflared.exe for mobile HTTPS tunnel...", flush=True)
    import httpx

    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        with client.stream("GET", CLOUDFLARED_URL) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=512 * 1024):
                    if chunk:
                        f.write(chunk)
    os.replace(tmp_path, bin_path)
    print(f"[PM-ECG] cloudflared.exe ready ({bin_path.stat().st_size:,} bytes)", flush=True)
    return bin_path


def _kill_stale_cloudflared() -> None:
    if sys.platform != "win32":
        return
    cmd = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -ieq 'cloudflared.exe') -and ($_.CommandLine -match '8785') "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            creationflags=CREATE_NO_WINDOW,
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass


def _sync_tunnel_json_to_github(root_dir: Path, tunnel_url: str) -> None:
    """Commit and push tunnel.json to origin/main so mobile devices auto-discover the tunnel."""
    tunnel_file = root_dir / "tunnel.json"
    payload = {
        "url": tunnel_url,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    tunnel_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[PM-ECG] Saved tunnel.json -> {tunnel_url}", flush=True)

    def _run_git(args: list[str], timeout: int = 25) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(root_dir),
            creationflags=CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    try:
        _run_git(["add", "tunnel.json"])
        commit_res = _run_git(
            ["commit", "-m", "chore: update active hybrid cloudflare tunnel url", "--only", "tunnel.json"]
        )
        if commit_res.returncode != 0 and "nothing to commit" in (commit_res.stdout + commit_res.stderr).lower():
            return
        push_res = _run_git(["push", "origin", "main"], timeout=35)
        if push_res.returncode != 0:
            _run_git(["pull", "--rebase", "--autostash", "origin", "main"], timeout=35)
            push_res = _run_git(["push", "origin", "main"], timeout=35)
        if push_res.returncode == 0:
            print(f"[PM-ECG] Synced tunnel.json to GitHub (mobile ready): {tunnel_url}", flush=True)
        else:
            print(f"[PM-ECG] Git push tunnel.json warning: {push_res.stderr.strip()}", flush=True)
    except Exception as exc:
        print(f"[PM-ECG] Git sync tunnel.json error: {exc}", flush=True)


def _tunnel_worker(root_dir: Path) -> None:
    """Background daemon that starts and supervises cloudflared quick tunnel for port 8785."""
    for _ in range(90):
        if is_server_alive():
            break
        time.sleep(0.5)
    else:
        print("[PM-ECG] Tunnel worker stopped: local server did not become healthy.", flush=True)
        return

    try:
        cf_bin = _ensure_cloudflared_binary(root_dir)
    except Exception as exc:
        print(f"[PM-ECG] Failed to prepare cloudflared.exe: {exc}", flush=True)
        return

    _kill_stale_cloudflared()

    while True:
        try:
            print("[PM-ECG] Starting Cloudflare HTTPS Tunnel for http://127.0.0.1:8785 ...", flush=True)
            proc = subprocess.Popen(
                [
                    str(cf_bin),
                    "tunnel",
                    "--url",
                    f"http://{HOST}:{PORT}",
                    "--no-autoupdate",
                ],
                cwd=str(root_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )

            captured_url = None
            assert proc.stdout is not None
            for line in proc.stdout:
                m = TUNNEL_REGEX.search(line)
                if m and not captured_url:
                    cand = m.group(0).rstrip("/")
                    if "api.trycloudflare.com" not in cand.lower():
                        captured_url = cand
                        print(f"[PM-ECG] Cloudflare Tunnel READY: {captured_url}", flush=True)
                        threading.Thread(
                            target=_sync_tunnel_json_to_github,
                            args=(root_dir, captured_url),
                            daemon=True,
                        ).start()

            rc = proc.wait()
            print(f"[PM-ECG] cloudflared exited with code {rc}; restarting in 5s...", flush=True)
        except Exception as exc:
            print(f"[PM-ECG] Tunnel supervisor error: {exc}; retrying in 8s...", flush=True)
        time.sleep(5.0)


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

        threading.Thread(target=_tunnel_worker, args=(root_dir,), daemon=True).start()

        import uvicorn

        uvicorn.run(
            "backend.server:app",
            host=HOST,
            port=PORT,
            use_colors=False,
            log_level="info",
        )
    except SystemExit as exc:
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

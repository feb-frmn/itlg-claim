"""System metrics for the monitoring page."""

import os
import time

import psutil

_start_time = time.time()


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def metrics() -> dict:
    disk_path = "/app/data" if os.path.isdir("/app/data") else "/"
    try:
        disk = psutil.disk_usage(disk_path)
    except Exception:
        disk = psutil.disk_usage("/")

    mem = psutil.virtual_memory()
    return {
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "memory_percent": round(mem.percent, 1),
        "memory_used": mem.used,
        "memory_total": mem.total,
        "memory_used_h": _human_bytes(mem.used),
        "memory_total_h": _human_bytes(mem.total),
        "disk_percent": round(disk.percent, 1),
        "disk_used": disk.used,
        "disk_total": disk.total,
        "disk_used_h": _human_bytes(disk.used),
        "disk_total_h": _human_bytes(disk.total),
        "uptime": int(time.time() - _start_time),
    }

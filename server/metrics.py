"""Collect host metrics for /health snapshots."""

from __future__ import annotations

import platform
import time
from typing import Any

import psutil


def collect_metrics() -> dict[str, Any]:
    """Snapshot CPU, memory, disk, uptime; safe to call on each health request."""
    boot = psutil.boot_time()
    uptime_sec = int(time.time() - boot)

    vm = psutil.virtual_memory()
    mem: dict[str, Any] = {
        "percent": round(vm.percent, 1),
        "used_gb": round(vm.used / (1024**3), 2),
        "total_gb": round(vm.total / (1024**3), 2),
    }

    disks: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype == "":
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "mount": part.mountpoint,
                "percent_used": round(usage.percent, 1),
                "free_gb": round(usage.free / (1024**3), 2),
            }
        )

    load_avg: list[float] | None = None
    try:
        load_avg = [round(x, 2) for x in psutil.getloadavg()]
    except (AttributeError, OSError):
        pass

    return {
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
        "memory": mem,
        "disks": disks,
        "uptime_sec": uptime_sec,
        "boot_time_unix": int(boot),
        "process_count": len(psutil.pids()),
        "load_avg": load_avg,
        "platform": platform.system(),
        "platform_release": platform.release(),
    }

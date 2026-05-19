"""Poll a health HTTP endpoint and log last_ok, first_fail, and recovered transitions."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _configure_logging(log_path: Path | None) -> None:
    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fmt.converter = time.gmtime  # UTC timestamps in log lines
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def _load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _resolve_settings(config_path: Path | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "health_url": os.environ.get("HEALTH_URL", "http://127.0.0.1:8000/health"),
        "interval_sec": _env_int("INTERVAL_SEC", 30),
        "timeout_sec": _env_int("TIMEOUT_SEC", 10),
        "log_path": os.environ.get("LOG_PATH", "watcher.log"),
        "bearer_token": os.environ.get("HEALTHCHECK_BEARER", "") or None,
        "snapshot_path": os.environ.get("SNAPSHOT_PATH", "snapshots.jsonl"),
        "log_snapshot": os.environ.get("LOG_SNAPSHOT", "1").strip().lower()
        not in ("0", "false", "no", "off"),
    }
    if config_path and config_path.is_file():
        file_cfg = _load_config(config_path)
        for key in (
            "health_url",
            "interval_sec",
            "timeout_sec",
            "log_path",
            "bearer_token",
            "snapshot_path",
            "log_snapshot",
        ):
            if key in file_cfg and file_cfg[key] is not None:
                base[key] = file_cfg[key]
    # Env wins for ops override
    if os.environ.get("HEALTH_URL"):
        base["health_url"] = os.environ["HEALTH_URL"]
    if os.environ.get("INTERVAL_SEC"):
        base["interval_sec"] = _env_int("INTERVAL_SEC", base["interval_sec"])
    if os.environ.get("TIMEOUT_SEC"):
        base["timeout_sec"] = _env_int("TIMEOUT_SEC", base["timeout_sec"])
    if os.environ.get("LOG_PATH"):
        base["log_path"] = os.environ["LOG_PATH"]
    if os.environ.get("HEALTHCHECK_BEARER"):
        base["bearer_token"] = os.environ["HEALTHCHECK_BEARER"]
    if os.environ.get("SNAPSHOT_PATH"):
        base["snapshot_path"] = os.environ["SNAPSHOT_PATH"]
    if os.environ.get("LOG_SNAPSHOT"):
        base["log_snapshot"] = os.environ["LOG_SNAPSHOT"].strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
    return base


def _snapshot_summary(payload: dict[str, Any]) -> str:
    m = payload.get("metrics")
    if not isinstance(m, dict):
        return json.dumps(payload, ensure_ascii=False)[:500]
    disks = m.get("disks") or []
    disk_hint = ""
    if disks and isinstance(disks[0], dict):
        disk_hint = f" disk0={disks[0].get('mount')} used={disks[0].get('percent_used')}%"
    mem = m.get("memory") if isinstance(m.get("memory"), dict) else {}
    return (
        f"cpu={m.get('cpu_percent')}% mem={mem.get('percent')}% "
        f"uptime_sec={m.get('uptime_sec')}{disk_hint}"
    )


def _append_snapshot(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _headers(bearer_token: str | None) -> dict[str, str]:
    if not bearer_token:
        return {}
    return {"Authorization": f"Bearer {bearer_token}"}


def run_loop(settings: dict[str, Any]) -> int:
    url = str(settings["health_url"])
    interval = int(settings["interval_sec"])
    timeout = float(settings["timeout_sec"])
    log_path_raw = settings.get("log_path")
    log_path = Path(log_path_raw) if log_path_raw else None

    _configure_logging(log_path)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("watcher")

    healthy = True
    last_ok_at: str | None = None
    last_snapshot: dict[str, Any] | None = None

    snapshot_raw = settings.get("snapshot_path")
    snapshot_path = Path(snapshot_raw) if snapshot_raw else None
    log_snapshot = bool(settings.get("log_snapshot", True))

    log.info("watcher_start url=%s interval_sec=%s timeout_sec=%s", url, interval, timeout)

    headers = _headers(settings.get("bearer_token"))

    while True:
        err: str | None = None
        payload: dict[str, Any] | None = None
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(url, headers=headers)
            if r.status_code >= 400:
                err = f"http_{r.status_code}"
            else:
                try:
                    body = r.json()
                    if isinstance(body, dict):
                        payload = body
                except json.JSONDecodeError:
                    payload = {"raw": r.text[:2000]}
        except httpx.TimeoutException:
            err = "timeout"
        except httpx.RequestError as e:
            err = type(e).__name__

        now = _utc_iso_z()

        if err is None:
            last_snapshot = payload
            if log_snapshot and payload is not None:
                log.info("last_ok at=%s %s", now, _snapshot_summary(payload))
            else:
                log.info("last_ok at=%s", now)
            if snapshot_path is not None:
                _append_snapshot(
                    snapshot_path,
                    {"watcher_at": now, "health": payload},
                )
            if not healthy:
                log.warning("recovered at=%s (was_down_since previous first_fail)", now)
            healthy = True
            last_ok_at = now
        else:
            if healthy:
                snap_msg = "no_prior_snapshot"
                if last_snapshot is not None:
                    snap_msg = _snapshot_summary(last_snapshot)
                log.warning(
                    "first_fail at=%s err=%s last_ok_at=%s last_snapshot=%s",
                    now,
                    err,
                    last_ok_at or "no_prior_ok",
                    snap_msg,
                )
                healthy = False
            else:
                log.warning("still_down at=%s err=%s", now, err)

        time.sleep(max(1, interval))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Poll /health and log uptime transitions.")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML config (see watcher/config.yaml); env still overrides.",
    )
    args = p.parse_args(argv)
    try:
        settings = _resolve_settings(args.config)
    except (OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    try:
        run_loop(settings)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

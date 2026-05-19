"""Minimal FastAPI health endpoint for uptime probing."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from server.metrics import collect_metrics

VERSION = "0.1.0"

app = FastAPI(title="Healthcheck", version=VERSION)


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _metrics_enabled() -> bool:
    return os.environ.get("HEALTH_METRICS", "1").strip().lower() not in ("0", "false", "no", "off")


def _require_bearer(authorization: str | None) -> None:
    expected = os.environ.get("HEALTHCHECK_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid_token")


def _health_body() -> dict:
    body: dict = {
        "status": "ok",
        "time": _utc_iso_z(),
        "hostname": socket.gethostname(),
        "version": VERSION,
    }
    if _metrics_enabled():
        try:
            body["metrics"] = collect_metrics()
        except Exception as exc:  # noqa: BLE001 — still return ok with error detail
            body["metrics_error"] = type(exc).__name__
    return body


@app.get("/health")
def health(authorization: str | None = Header(default=None)) -> JSONResponse:
    _require_bearer(authorization)
    return JSONResponse(content=_health_body(), status_code=200)


@app.get("/health/ready")
def ready(authorization: str | None = Header(default=None)) -> JSONResponse:
    """Readiness probe; extend with DB checks when needed."""
    _require_bearer(authorization)
    return JSONResponse(content=_health_body(), status_code=200)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server.app:app", host=host, port=port, factory=False, reload=False)

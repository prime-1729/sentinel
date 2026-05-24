from datetime import datetime
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Allow `uvicorn src.api:app` while keeping bare imports in sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv()

from anomaly import run_all_detectors
import live_feed
import live_state
from report import generate_intelligence_report
from telemetry import extract_telemetry_from_file

app = FastAPI(
    title="SENTINEL",
    description="Mission Intelligence System for Autonomous Drone Operations",
    version="0.1.0",
)

_cors_origins = os.getenv(
    "SENTINEL_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


@app.get("/")
def root():
    return {
        "system": "SENTINEL",
        "status": "operational",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    snapshot = live_state.snapshot()
    return {
        "status": "operational",
        "live_monitor_running": live_feed.is_running(),
        "live_connected": snapshot["connected"],
    }


@app.post("/analyze")
async def analyze_mission(file: UploadFile = File(...)):
    """Upload a drone log file (.tlog or .bin) and return mission intelligence."""
    suffix = os.path.splitext(file.filename or "")[1] or ".tlog"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        telemetry = extract_telemetry_from_file(tmp_path)
        anomalies = run_all_detectors(telemetry)
        report = generate_intelligence_report(telemetry, anomalies)

        duration_seconds = 0.0
        max_altitude = 0.0
        if len(telemetry["positions"]) > 0:
            positions = telemetry["positions"]
            duration_seconds = float(
                positions["timestamp"].max() - positions["timestamp"].min()
            )
            max_altitude = float(positions["relative_alt"].max())

        return JSONResponse(
            {
                "status": "success",
                "mission_stats": {
                    "duration_seconds": round(duration_seconds, 1),
                    "duration": _format_duration(duration_seconds),
                    "max_altitude_metres": round(max_altitude, 1),
                    "max_altitude": round(max_altitude, 1),
                    "anomalies_detected": len(anomalies),
                },
                "anomalies": [
                    {
                        "id": f"ANM-{index:03d}",
                        "timestamp": _format_timestamp(a.timestamp),
                        "type": a.event_type,
                        "severity": a.severity,
                        "description": a.detail,
                        "detail": a.detail,
                        "recommendation": a.recommendation,
                    }
                    for index, a in enumerate(anomalies, start=1)
                ],
                "intelligence_report": report,
                "flight_path": (
                    telemetry["positions"][
                        ["timestamp", "lat", "lon", "relative_alt"]
                    ].to_dict("records")
                    if len(telemetry["positions"]) > 0
                    else []
                ),
            }
        )

    finally:
        os.unlink(tmp_path)


@app.get("/telemetry/live")
def telemetry_live():
    """Latest live telemetry snapshot from the MAVLink monitor."""
    snapshot = live_state.snapshot()
    return {
        "connected": snapshot["connected"],
        "connection_error": snapshot["connection_error"],
        "monitor_running": live_feed.is_running(),
        "telemetry": snapshot["telemetry"],
        "anomalies": snapshot["anomalies"],
        "mission_elapsed_seconds": snapshot["mission_elapsed_seconds"],
    }


@app.post("/monitor/start")
def monitor_start(
    connection: str = os.getenv(
        "SENTINEL_MAVLINK_CONNECTION", "udpin:127.0.0.1:14551"
    ),
):
    """Start background live MAVLink monitoring for the dashboard."""
    live_feed.start(connection_string=connection)
    return {"status": "started", "connection": connection}


@app.post("/monitor/stop")
def monitor_stop():
    """Stop background live MAVLink monitoring."""
    live_feed.stop()
    return {"status": "stopped"}

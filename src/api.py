from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import sys
import tempfile
import os
from pathlib import Path
from dotenv import load_dotenv

# Allow `uvicorn src.api:app` while keeping bare imports in sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv()

from telemetry import extract_telemetry_from_file
from anomaly import run_all_detectors
from report import generate_intelligence_report

app = FastAPI(
    title="SENTINEL",
    description="Mission Intelligence System for Autonomous Drone Operations",
    version="0.1.0"
)

@app.get("/")
def root():
    return {
        "system": "SENTINEL",
        "status": "operational",
        "version": "0.1.0"
    }

@app.post("/analyze")
async def analyze_mission(file: UploadFile = File(...)):
    """
    Upload a drone log file (.tlog or .bin).
    Returns structured mission intelligence report.
    """
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=os.path.splitext(file.filename)[1]
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        telemetry = extract_telemetry_from_file(tmp_path)
        anomalies = run_all_detectors(telemetry)
        report = generate_intelligence_report(telemetry, anomalies)

        return JSONResponse({
            "status": "success",
            "mission_stats": {
                "duration_seconds": round(
                    telemetry['positions']['timestamp'].max() -
                    telemetry['positions']['timestamp'].min(), 1
                ) if len(telemetry['positions']) > 0 else 0,
                "max_altitude_metres": round(
                    telemetry['positions']['relative_alt'].max(), 1
                ) if len(telemetry['positions']) > 0 else 0,
                "anomalies_detected": len(anomalies),
            },
            "anomalies": [
                {
                    "type": a.event_type,
                    "severity": a.severity,
                    "detail": a.detail,
                    "recommendation": a.recommendation
                }
                for a in anomalies
            ],
            "intelligence_report": report,
            "flight_path": telemetry['positions'][
                ['timestamp', 'lat', 'lon', 'relative_alt']
            ].to_dict('records') if len(telemetry['positions']) > 0 else []
        })

    finally:
        os.unlink(tmp_path)


@app.get("/health")
def health():
    return {"status": "operational"}
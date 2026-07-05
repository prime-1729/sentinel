"""
SENTINEL Intelligence Sidecar
Central orchestrator for all intelligence on the edge node.
Subscribes to NATS telemetry, runs detection/perception pipelines, and publishes results.
"""

import threading
import time
import logging
import asyncio
import json
import base64
import pandas as pd
import collections
from typing import Dict, Any

from .domains.anomaly import AnomalyPipeline
from .perception.detector import ObjectDetector, CV2_AVAILABLE
from .tracking.tracker import MultiObjectTracker
from .threat.behavior_analyzer import BehaviorAnalyzer
from .threat.threat_scorer import ThreatScorer
from .autonomy.reaction_rules import ReactionEngine

try:
    import nats
except ImportError:
    nats = None

try:
    from .pb.threat_pb2 import ThreatAlert
    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

logger = logging.getLogger("sentinel.intelligence.sidecar")

class IntelligenceSidecar:
    def __init__(self, nats_url: str = "nats://localhost:4222", drone_id: str = "drone_0"):
        self.nats_url = nats_url
        self.drone_id = drone_id
        
        self.nc = None
        self.stop_event = threading.Event()
        self.loop = None
        self.thread = None
        
        # Initialize Pipelines
        logger.info("Initializing Intelligence Pipelines...")
        
        # 1. Anomaly Pipeline (IF -> LSTM-AE -> Domain Classifier)
        self.anomaly_pipeline = AnomalyPipeline()
        
        # 2. Perception & Tracking Pipeline (CV)
        self.perception_pipeline = ObjectDetector()
        self.perception_pipeline.load() # Tries to load ONNX model
        self.tracker = MultiObjectTracker()
        
        # 3. Threat Assessment
        self.behavior_analyzer = BehaviorAnalyzer()
        self.threat_scorer = ThreatScorer()
        
        # 4. Reaction Engine
        self.reaction_engine = ReactionEngine()
        
        # State
        self.telemetry_history: Dict[str, collections.deque] = {
            "positions": collections.deque(maxlen=2000),
            "battery": collections.deque(maxlen=2000),
            "attitude": collections.deque(maxlen=2000),
            "hud": collections.deque(maxlen=2000),
            "motors": collections.deque(maxlen=2000),
            "vibration": collections.deque(maxlen=2000),
            "comms": collections.deque(maxlen=2000)
        }
        self.history_lock = threading.Lock()
        self.max_history_seconds = 60
        self.latest_telemetry_dict = {}
        self.latest_telemetry_lock = threading.Lock()
        
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()

    def start(self):
        """Start the sidecar daemon."""
        if self.thread and self.thread.is_alive():
            return False
            
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run_async_loop,
            daemon=True,
            name="IntelligenceSidecar"
        )
        self.thread.start()
        return True
        
    def stop(self):
        """Stop the sidecar daemon."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
            
    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main_loop())
        except Exception as e:
            logger.error(f"Sidecar crashed: {e}")
        finally:
            self.loop.close()
            
    async def _main_loop(self):
        if not nats:
            logger.error("nats-py not installed. Cannot run sidecar.")
            return
            
        try:
            self.nc = await nats.connect(self.nats_url)
            logger.info(f"Sidecar connected to NATS mesh at {self.nats_url}")
            
            # Subscribe to all telemetry from bridge
            await self.nc.subscribe(f"sentinel.telemetry.{self.drone_id}.>", cb=self._on_telemetry)
            
            # Subscribe to camera topic
            await self.nc.subscribe(f"sentinel.telemetry.{self.drone_id}.camera", cb=self._on_camera_frame)
            
            # Start background tasks
            anomaly_task = asyncio.create_task(self._anomaly_loop())
            perception_task = asyncio.create_task(self._perception_loop())
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            while not self.stop_event.is_set():
                await asyncio.sleep(0.5)
                
            anomaly_task.cancel()
            perception_task.cancel()
            heartbeat_task.cancel()
            await self.nc.close()
            logger.info("Sidecar disconnected from NATS.")
            
        except Exception as e:
            logger.error(f"NATS connection failed: {e}")
            
    async def _on_telemetry(self, msg):
        """Buffer incoming telemetry."""
        subject = msg.subject
        try:
            data = json.loads(msg.data.decode())
        except json.JSONDecodeError:
            return
            
        # Update flat dictionary for quick reaction access
        with self.latest_telemetry_lock:
            self.latest_telemetry_dict.update(data)
        
        current_time = data.get("timestamp", time.time())
        new_row = {"timestamp": current_time}
        
        with self.history_lock:
            if "position" in subject or "odom" in subject:
                # Merge odom/global into position buffer for anomalies
                new_pos = {**new_row, "lat": data.get("lat", 0), "lon": data.get("lon", 0), 
                           "relative_alt": data.get("alt", data.get("z", 0)), 
                           "vx": data.get("vx", 0), "vy": data.get("vy", 0), "vz": data.get("vz", 0)}
                self.telemetry_history["positions"].append(new_pos)
                
            elif "battery" in subject:
                new_bat = {**new_row, "voltage": data.get("voltage", 0), "current": data.get("current", 0), "remaining_pct": data.get("remaining_pct", 0)}
                self.telemetry_history["battery"].append(new_bat)
                
            elif "imu" in subject or "attitude" in subject:
                new_att = {**new_row, "roll_deg": data.get("roll_deg", 0), "pitch_deg": data.get("pitch_deg", 0), "yaw_deg": data.get("yaw_deg", 0)}
                self.telemetry_history["attitude"].append(new_att)
                
            elif "hud" in subject:
                new_hud = {**new_row, "airspeed": data.get("airspeed", 0), "groundspeed": data.get("groundspeed", 0), 
                           "climb_rate": data.get("climb_rate", 0), "throttle_pct": data.get("throttle_pct", 0)}
                self.telemetry_history["hud"].append(new_hud)
                
            elif "motor" in subject or "esc" in subject:
                new_motors = {**new_row, "rpm_1": data.get("rpm_1", 0), "rpm_2": data.get("rpm_2", 0),
                              "rpm_3": data.get("rpm_3", 0), "rpm_4": data.get("rpm_4", 0),
                              "cur_1": data.get("cur_1", 0), "cur_2": data.get("cur_2", 0),
                              "cur_3": data.get("cur_3", 0), "cur_4": data.get("cur_4", 0)}
                self.telemetry_history["motors"].append(new_motors)
                
            elif "vibration" in subject or "vibe" in subject:
                new_vibe = {**new_row, "vibration_x": data.get("vibration_x", 0), 
                            "vibration_y": data.get("vibration_y", 0), 
                            "vibration_z": data.get("vibration_z", 0)}
                self.telemetry_history["vibration"].append(new_vibe)
                
            elif "comms" in subject or "link" in subject or "radio" in subject:
                new_comms = {**new_row, "rssi": data.get("rssi", 0), "remrssi": data.get("remrssi", 0),
                             "noise": data.get("noise", 0), "rxerrors": data.get("rxerrors", 0)}
                self.telemetry_history["comms"].append(new_comms)
                
    async def _on_camera_frame(self, msg):
        """Buffer incoming camera frames."""
        try:
            data = json.loads(msg.data.decode())
            if "frame" in data and CV2_AVAILABLE:
                import cv2
                import numpy as np
                img_data = base64.b64decode(data["frame"])
                np_arr = np.frombuffer(img_data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    with self.latest_frame_lock:
                        self.latest_frame = frame
        except Exception as e:
            logger.error(f"Error decoding camera frame: {e}")
                    
    async def _heartbeat_loop(self):
        """Publish health heartbeat to NATS."""
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            if self.nc and self.nc.is_connected:
                with self.history_lock:
                    buffer_sizes = {k: len(v) for k, v in self.telemetry_history.items()}
                
                heartbeat = {
                    "timestamp": time.time(),
                    "sidecar_status": "alive",
                    "anomaly_pipeline_active": self.anomaly_pipeline.if_model is not None,
                    "perception_active": True,
                    "telemetry_buffer_sizes": buffer_sizes
                }
                await self.nc.publish(f"sentinel.fleet.health.{self.drone_id}", json.dumps(heartbeat).encode())

    async def _anomaly_loop(self):
        """Periodically run anomaly detection on the buffered telemetry."""
        detect_interval = 2.0  # Production target <500ms, 2s is MVP acceptable
        while not self.stop_event.is_set():
            await asyncio.sleep(detect_interval)
            
            with self.history_lock:
                has_positions = len(self.telemetry_history["positions"]) > 0
                has_other = any(len(self.telemetry_history[k]) > 0 for k in self.telemetry_history if k != "positions")
                
                if not (has_positions and has_other):
                    continue
                
                # Trim old history
                current_time = time.time()
                for key in self.telemetry_history:
                    while self.telemetry_history[key] and self.telemetry_history[key][0]["timestamp"] < current_time - self.max_history_seconds:
                        self.telemetry_history[key].popleft()
                        
                history_copy = {k: pd.DataFrame(list(v)) for k, v in self.telemetry_history.items() if len(v) > 0}
                
            # 1. Run Anomaly Pipeline
            anomalies = self.anomaly_pipeline.run(history_copy)
            
            if anomalies:
                # 2. Check Reaction Engine for safety overrides
                with self.latest_telemetry_lock:
                    telemetry = self.latest_telemetry_dict.copy()
                reaction = self.reaction_engine.evaluate(threats=[], anomalies=anomalies, telemetry=telemetry)
                
                for a in anomalies:
                    alert_payload = {
                        "id": f"{a.event_type}_{a.timestamp}",
                        "timestamp": a.timestamp,
                        "type": a.event_type,
                        "severity": a.severity,
                        "detail": a.detail,
                        "recommendation": a.recommendation,
                        "domain": a.domain
                    }
                    
                    if PROTOBUF_AVAILABLE:
                        alert = ThreatAlert()
                        alert.threat_id = f"{a.event_type}_{a.timestamp}"
                        alert.detector_node_id = self.drone_id
                        alert.timestamp = int(a.timestamp * 1000)
                        alert.threat_type = a.event_type
                        alert.confidence = 1.0 # default for anomalies
                        # get lat/lon from latest telemetry if available
                        with self.latest_telemetry_lock:
                            pos = self.latest_telemetry_dict.copy()
                        alert.lat = pos.get('lat', 0.0)
                        alert.lon = pos.get('lon', 0.0)
                        alert.alt = pos.get('alt', pos.get('z', 0.0))
                        payload = alert.SerializeToString()
                    else:
                        payload = json.dumps(alert_payload).encode()
                        
                    if self.nc and self.nc.is_connected:
                        await self.nc.publish("sentinel.threats.alert", payload)
                        
                if reaction and self.nc and self.nc.is_connected:
                    # Publish reaction command
                    cmd = {
                        "command": reaction["action"],
                        "reason": reaction["reason"],
                        "tier": reaction["tier"]
                    }
                    await self.nc.publish(f"sentinel.command.{self.drone_id}", json.dumps(cmd).encode())

    async def _perception_loop(self):
        """Run perception loop extracting objects from video stream."""
        import numpy as np
        frame_id = 0
        while not self.stop_event.is_set():
            await asyncio.sleep(0.1) # ~10 FPS
            if not CV2_AVAILABLE:
                continue
                
            # Get latest frame
            with self.latest_frame_lock:
                frame = self.latest_frame
                
            if frame is None:
                continue
            
            # Detect
            detections = self.perception_pipeline.detect(frame, frame_id)
            
            # Track
            tracks = self.tracker.update(detections, frame_id)
            
            threats = []
            for track in tracks:
                behavior = self.behavior_analyzer.analyze(track)
                threat = self.threat_scorer.score(track, behavior)
                threats.append(threat)
                
                if self.nc and self.nc.is_connected:
                    if PROTOBUF_AVAILABLE:
                        alert = ThreatAlert()
                        alert.threat_id = f"threat_{track.track_id}_{frame_id}"
                        alert.detector_node_id = self.drone_id
                        alert.timestamp = int(time.time() * 1000)
                        alert.threat_type = track.class_name
                        alert.confidence = float(threat["threat_score"])
                        with self.latest_telemetry_lock:
                            pos = self.latest_telemetry_dict.copy()
                        alert.lat = pos.get('lat', 0.0)
                        alert.lon = pos.get('lon', 0.0)
                        alert.alt = pos.get('alt', pos.get('z', 0.0))
                        payload = alert.SerializeToString()
                    else:
                        threat_payload = {
                            "id": f"threat_{track.track_id}_{frame_id}",
                            "timestamp": time.time(),
                            "type": track.class_name,
                            "threat_score": threat["threat_score"],
                            "priority": threat["priority"],
                            "recommended_action": threat["recommended_action"],
                            "track_id": track.track_id,
                            "bbox": track.bbox
                        }
                        payload = json.dumps(threat_payload).encode()
                    await self.nc.publish("sentinel.threats.alert", payload)
                
            if threats and self.nc and self.nc.is_connected:
                with self.latest_telemetry_lock:
                    telemetry = self.latest_telemetry_dict.copy()
                    
                reaction = self.reaction_engine.evaluate(threats=threats, anomalies=[], telemetry=telemetry)
                if reaction:
                    cmd = {
                        "command": reaction["action"],
                        "reason": reaction["reason"],
                        "tier": reaction["tier"]
                    }
                    await self.nc.publish(f"sentinel.command.{self.drone_id}", json.dumps(cmd).encode())
                    
            # Cleanup dead track histories
            active_ids = [t.track_id for t in tracks]
            self.behavior_analyzer.cleanup(active_ids)
            
            frame_id += 1
    
# Compatibility functions for older code
_instance = None

def start(connection_string: str = "nats://localhost:4222", window_seconds: int = 10) -> bool:
    global _instance
    if _instance is None:
        _instance = IntelligenceSidecar(nats_url=connection_string)
    return _instance.start()
    
def stop():
    global _instance
    if _instance:
        _instance.stop()
        
def is_running() -> bool:
    global _instance
    return _instance is not None and _instance.thread is not None and _instance.thread.is_alive()

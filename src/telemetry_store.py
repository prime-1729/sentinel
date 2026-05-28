import sqlite3
import math
import os
import time
import pandas as pd
from pymavlink import mavutil
from typing import List, Dict, Any, Optional

class TelemetryStore:
    def __init__(self, db_path: str = "data/sentinel.db"):
        """
        Initializes the TelemetryStore.
        Creates parent directories if necessary and sets up connection.
        Enables WAL mode and foreign key constraints.
        """
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """
        Creates schema tables and performance indexes.
        """
        with self.conn:
            # missions table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    drone_id TEXT NOT NULL,
                    start_time REAL,
                    end_time REAL,
                    status TEXT,
                    planned_route TEXT
                );
            """)
            
            # positions table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    drone_id TEXT,
                    mission_id TEXT,
                    timestamp REAL,
                    lat REAL,
                    lon REAL,
                    alt_metres REAL,
                    relative_alt REAL,
                    vx REAL,
                    vy REAL,
                    vz REAL,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
                );
            """)
            
            # battery table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS battery (
                    drone_id TEXT,
                    mission_id TEXT,
                    timestamp REAL,
                    voltage REAL,
                    current REAL,
                    remaining_pct REAL,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
                );
            """)
            
            # attitude table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS attitude (
                    drone_id TEXT,
                    mission_id TEXT,
                    timestamp REAL,
                    roll_deg REAL,
                    pitch_deg REAL,
                    yaw_deg REAL,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
                );
            """)
            
            # hud table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS hud (
                    drone_id TEXT,
                    mission_id TEXT,
                    timestamp REAL,
                    airspeed REAL,
                    groundspeed REAL,
                    altitude REAL,
                    climb_rate REAL,
                    throttle_pct REAL,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
                );
            """)
            
            # anomaly_events table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS anomaly_events (
                    drone_id TEXT,
                    mission_id TEXT,
                    timestamp REAL,
                    event_type TEXT,
                    severity TEXT,
                    detail TEXT,
                    recommendation TEXT,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
                );
            """)
            
            # Composite indexes for querying by drone and time window
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_drone_ts ON positions (drone_id, timestamp);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_battery_drone_ts ON battery (drone_id, timestamp);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_attitude_drone_ts ON attitude (drone_id, timestamp);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_hud_drone_ts ON hud (drone_id, timestamp);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_anomaly_events_drone_ts ON anomaly_events (drone_id, timestamp);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_anomaly_events_type ON anomaly_events (event_type);")

    def create_mission(self, mission_id: str, drone_id: str) -> None:
        """
        Creates a new mission entry if it doesn't already exist.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO missions (mission_id, drone_id, start_time, status)
                VALUES (?, ?, ?, ?)
                """,
                (mission_id, drone_id, time.time(), "ACTIVE")
            )

    def complete_mission(self, mission_id: str) -> None:
        """
        Updates the mission status to COMPLETED and sets the end time.
        """
        with self.conn:
            self.conn.execute(
                """
                UPDATE missions
                SET end_time = ?, status = ?
                WHERE mission_id = ?
                """,
                (time.time(), "COMPLETED", mission_id)
            )

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns mission details as a dictionary, or None if not found.
        """
        cursor = self.conn.execute(
            "SELECT * FROM missions WHERE mission_id = ?",
            (mission_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def ingest_dataframes(self, telemetry: Dict[str, pd.DataFrame], drone_id: str, mission_id: str) -> Dict[str, int]:
        """
        Ingests a dictionary of telemetry DataFrames.
        Returns a dictionary mapping table name to number of rows inserted.
        """
        self.create_mission(mission_id, drone_id)
        counts = {}
        with self.conn:
            for key in ['positions', 'battery', 'attitude', 'hud']:
                counts[key] = 0
                if key in telemetry and telemetry[key] is not None:
                    df = telemetry[key]
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        df_to_insert = df.copy()
                        df_to_insert['drone_id'] = drone_id
                        df_to_insert['mission_id'] = mission_id
                        
                        # Filter to columns that exist in the database table to avoid errors
                        cursor = self.conn.execute(f"PRAGMA table_info({key})")
                        valid_cols = [r[1] for r in cursor.fetchall()]
                        df_to_insert = df_to_insert[[c for c in df_to_insert.columns if c in valid_cols]]
                        
                        df_to_insert.to_sql(key, self.conn, if_exists='append', index=False)
                        counts[key] = len(df_to_insert)
        return counts

    def ingest_tlog(self, filepath: str, drone_id: str = "drone_0", mission_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Directly parses a MAVLink .tlog file and streams it into the database.
        Optimized via batch inserts and transaction wrapping.
        """
        if mission_id is None:
            base = os.path.splitext(os.path.basename(filepath))[0]
            mission_id = f"mission_{base}_{int(time.time())}"
            
        self.create_mission(mission_id, drone_id)
        
        mlog = mavutil.mavlink_connection(filepath)
        
        positions = []
        battery = []
        attitude = []
        hud = []
        
        counts = {'positions': 0, 'battery': 0, 'attitude': 0, 'hud': 0, 'mission_id': mission_id}
        batch_size = 5000
        
        def flush_batch(table: str, data: list) -> None:
            if not data:
                return
            placeholders = ", ".join(["?"] * len(data[0]))
            cols = {
                'positions': 'drone_id, mission_id, timestamp, lat, lon, alt_metres, relative_alt, vx, vy, vz',
                'battery': 'drone_id, mission_id, timestamp, voltage, current, remaining_pct',
                'attitude': 'drone_id, mission_id, timestamp, roll_deg, pitch_deg, yaw_deg',
                'hud': 'drone_id, mission_id, timestamp, airspeed, groundspeed, altitude, climb_rate, throttle_pct'
            }[table]
            query = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
            self.conn.executemany(query, data)
            counts[table] += len(data)
            data.clear()

        # Wrap in single transaction for maximum execution speed
        with self.conn:
            while True:
                msg = mlog.recv_match(blocking=False)
                if msg is None:
                    break
                    
                msg_type = msg.get_type()
                ts = getattr(msg, '_timestamp', 0.0)
                
                if msg_type == 'GLOBAL_POSITION_INT':
                    positions.append((
                        drone_id, mission_id, ts,
                        msg.lat / 1e7,
                        msg.lon / 1e7,
                        msg.alt / 1000,
                        msg.relative_alt / 1000,
                        msg.vx / 100,
                        msg.vy / 100,
                        msg.vz / 100
                    ))
                    if len(positions) >= batch_size:
                        flush_batch('positions', positions)
                        
                elif msg_type == 'BATTERY_STATUS':
                    battery.append((
                        drone_id, mission_id, ts,
                        msg.voltages[0] / 1000 if (msg.voltages and len(msg.voltages) > 0) else 0.0,
                        msg.current_battery / 100 if msg.current_battery is not None else 0.0,
                        msg.battery_remaining if msg.battery_remaining is not None else 0.0
                    ))
                    if len(battery) >= batch_size:
                        flush_batch('battery', battery)
                        
                elif msg_type == 'ATTITUDE':
                    attitude.append((
                        drone_id, mission_id, ts,
                        math.degrees(msg.roll),
                        math.degrees(msg.pitch),
                        math.degrees(msg.yaw)
                    ))
                    if len(attitude) >= batch_size:
                        flush_batch('attitude', attitude)
                        
                elif msg_type == 'VFR_HUD':
                    hud.append((
                        drone_id, mission_id, ts,
                        msg.airspeed,
                        msg.groundspeed,
                        msg.alt,
                        msg.climb,
                        msg.throttle
                    ))
                    if len(hud) >= batch_size:
                        flush_batch('hud', hud)
            
            # Flush any remaining items in batches
            flush_batch('positions', positions)
            flush_batch('battery', battery)
            flush_batch('attitude', attitude)
            flush_batch('hud', hud)
            
        self.complete_mission(mission_id)
        return counts

    def ingest_anomalies(self, anomalies: List[Dict[str, Any]], drone_id: str, mission_id: str) -> int:
        """
        Ingests a list of detected anomalies.
        Returns the number of rows inserted.
        """
        self.create_mission(mission_id, drone_id)
        count = 0
        with self.conn:
            data = []
            for a in anomalies:
                data.append((
                    drone_id,
                    mission_id,
                    a.get('timestamp', time.time()),
                    a.get('event_type'),
                    a.get('severity'),
                    a.get('detail'),
                    a.get('recommendation')
                ))
            if data:
                self.conn.executemany(
                    """
                    INSERT INTO anomaly_events (
                        drone_id, mission_id, timestamp, event_type, severity, detail, recommendation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    data
                )
                count = len(data)
        return count

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Executes a custom SQL query and returns rows as list of dicts.
        """
        cursor = self.conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def close(self) -> None:
        """
        Closes the database connection.
        """
        if self.conn:
            self.conn.close()
            self.conn = None

#!/usr/bin/env python3
"""
Generate training data using ArduPilot SITL fault injection.
This script launches ArduPilot SITL, flies scripted missions, and injects faults
at known timestamps to generate labeled .tlog datasets for training ML models.
"""

import os
import sys
import time
import csv
import argparse
import subprocess
import shutil
from typing import Dict, Any, List

def run_mission_with_fault(
    mission_id: str,
    fault_config: Dict[str, Any],
    output_dir: str,
    sitl_path: str = "sim_vehicle.py",
    duration_s: int = 300,
    inject_time_s: int = 120
) -> Dict[str, Any]:
    """
    Run a single SITL mission, injecting a specific fault.
    (Mock implementation for plan setup - would normally use dronekit/pymavlink)
    """
    print(f"Starting mission {mission_id}...")
    tlog_path = os.path.join(output_dir, f"{mission_id}.tlog")
    labels_path = os.path.join(output_dir, f"{mission_id}.labels.csv")
    
    # Mock generation of labels file
    print(f"  Simulating flight for {duration_s}s. Injecting fault at {inject_time_s}s.")
    time.sleep(1) # simulate some work
    
    with open(labels_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'label', 'fault_type', 'injected_param'])
        
        start_time = time.time()
        for i in range(duration_s):
            ts = start_time + i
            if i < inject_time_s or not fault_config:
                writer.writerow([ts, 'normal', 'none', 'none'])
            else:
                writer.writerow([ts, 'anomaly', fault_config['name'], fault_config['param']])
                
    # Create a dummy tlog file
    with open(tlog_path, 'w') as f:
        f.write("DUMMY TLOG DATA\n")
        
    print(f"  Mission {mission_id} complete. Data saved to {output_dir}")
    
    return {
        "mission_id": mission_id,
        "total_rows": duration_s,
        "fault_rows": duration_s - inject_time_s if fault_config else 0,
        "normal_rows": inject_time_s if fault_config else duration_s
    }

def generate_dataset(
    output_dir: str,
    num_normal: int = 3,
    sitl_path: str = "sim_vehicle.py"
) -> Dict[str, Any]:
    """Generate the full dataset."""
    os.makedirs(output_dir, exist_ok=True)
    
    fault_scenarios = [
        {"name": "motor_fail", "param": "SIM_ENGINE_FAIL=1"},
        {"name": "battery_degrade", "param": "SIM_BATT_VOLTAGE=3.2"},
        {"name": "gps_jam", "param": "SIM_GPS_DISABLE=1"},
        {"name": "gps_spoof", "param": "SIM_GPS_GLITCH_X=0.001"},
        {"name": "wind_gust", "param": "SIM_WIND_SPD=15"},
        {"name": "vibration", "param": "SIM_VIB_MOT_MAX=30"}
    ]
    
    stats = {"total_rows": 0, "normal_rows": 0, "fault_rows": 0}
    
    print("=== Generating Normal Flights ===")
    for i in range(num_normal):
        mission_id = f"normal_flight_{i:03d}"
        res = run_mission_with_fault(mission_id, {}, output_dir, sitl_path)
        stats["total_rows"] += res["total_rows"]
        stats["normal_rows"] += res["normal_rows"]
        
    print("\n=== Generating Fault Flights ===")
    for i, fault in enumerate(fault_scenarios):
        mission_id = f"fault_{fault['name']}_{i:03d}"
        res = run_mission_with_fault(mission_id, fault, output_dir, sitl_path)
        stats["total_rows"] += res["total_rows"]
        stats["normal_rows"] += res["normal_rows"]
        stats["fault_rows"] += res["fault_rows"]
        
    return stats

def main():
    parser = argparse.ArgumentParser(description="Generate SITL Training Data")
    parser.add_argument("--output", default="data/training", help="Output directory")
    parser.add_argument("--normal", type=int, default=3, help="Number of normal flights")
    args = parser.parse_args()
    
    stats = generate_dataset(args.output, args.normal)
    print("\n=== Generation Complete ===")
    print(f"Total rows:  {stats['total_rows']}")
    print(f"Normal rows: {stats['normal_rows']}")
    print(f"Fault rows:  {stats['fault_rows']}")

if __name__ == "__main__":
    main()

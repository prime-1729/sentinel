import os
import sys
import time

# Ensure src is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.telemetry_store import TelemetryStore

def main():
    tlog_path = "data/test_mission.tlog"
    db_path = "data/temp_verify.db"
    
    if not os.path.exists(tlog_path):
        print(f"Error: {tlog_path} not found. Please ensure it is present in the workspace.")
        return
        
    # Clean up previous temp db if any
    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                print(f"Warning: Could not remove {path}: {e}")
        
    print(f"Initializing TelemetryStore at {db_path}...")
    store = TelemetryStore(db_path=db_path)
    
    print(f"Ingesting {tlog_path}...")
    start_time = time.time()
    
    # Perform ingestion
    stats = store.ingest_tlog(tlog_path, drone_id="drone_0")
    
    elapsed = time.time() - start_time
    print(f"Ingestion completed in {elapsed:.2f} seconds.")
    print("Ingestion statistics returned from ingest_tlog:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
        
    # Query database to show record counts from the tables
    print("Verifying via SQL queries:")
    tables = ['positions', 'battery', 'attitude', 'hud', 'missions']
    for t in tables:
        count_res = store.query(f"SELECT COUNT(*) as cnt FROM {t}")
        print(f"  {t} row count: {count_res[0]['cnt']}")
        
    # Verify performance target
    if elapsed < 30.0:
        print(f"SUCCESS: Ingestion met performance target of < 30 seconds (took {elapsed:.2f}s).")
    else:
        print(f"WARNING: Ingestion took {elapsed:.2f}s, which is longer than the 30-second target.")
        
    store.close()
    
    # Clean up temp db files
    print("Cleaning up temporary database files...")
    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                print(f"Warning: Could not clean up {path}: {e}")
            
    print("Verification completed successfully.")

if __name__ == "__main__":
    main()

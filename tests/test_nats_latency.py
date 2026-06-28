import asyncio
import time
import uuid
import sys
import os

# Add pb directory to python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'pb'))

import nats
import threat_pb2

async def main():
    # Connect to NATS
    nc = await nats.connect("nats://localhost:4222")
    print("Connected to NATS")
    
    latency_ms = []
    reply_received = asyncio.Event()

    async def message_handler(msg):
        try:
            confirm = threat_pb2.ThreatConfirm()
            confirm.ParseFromString(msg.data)
            if confirm.is_authorized:
                reply_received.set()
        except Exception as e:
            print(f"Error parsing message: {e}")

    # Subscribe to confirm topic
    sub = await nc.subscribe("sentinel.threats.confirm", cb=message_handler)
    print("Starting latency test (100 iterations)...")
    
    for i in range(100):
        reply_received.clear()
        
        # Create a mock ThreatAlert
        alert = threat_pb2.ThreatAlert(
            threat_id=f"test-{uuid.uuid4()}",
            detector_node_id="python-test-node",
            timestamp=int(time.time() * 1000),
            threat_type="PING_TEST",
            confidence=0.99
        )
        
        start_time = time.perf_counter()
        
        # Publish
        await nc.publish("sentinel.threats.alert", alert.SerializeToString())
        
        # Wait for reply
        try:
            await asyncio.wait_for(reply_received.wait(), timeout=1.0)
            end_time = time.perf_counter()
            latency = (end_time - start_time) * 1000 # ms
            latency_ms.append(latency)
        except asyncio.TimeoutError:
            print(f"Iteration {i} timed out")

    if latency_ms:
        avg_latency = sum(latency_ms) / len(latency_ms)
        min_latency = min(latency_ms)
        max_latency = max(latency_ms)
        print("\n--- Latency Results ---")
        print(f"Packets: {len(latency_ms)}/100")
        print(f"Average Latency: {avg_latency:.3f} ms")
        print(f"Min Latency: {min_latency:.3f} ms")
        print(f"Max Latency: {max_latency:.3f} ms")
        
        if avg_latency < 1.0:
            print("\nSUCCESS: Sub-millisecond latency achieved!")
        else:
            print("\nWARNING: Latency is above 1 millisecond.")

    await sub.unsubscribe()
    await nc.close()

if __name__ == '__main__':
    asyncio.run(main())

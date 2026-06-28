package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"sentinel-edge-agent/internal/mesh"
	"sentinel-edge-agent/internal/mesh/pb"

	"github.com/nats-io/nats.go"
	"google.golang.org/protobuf/proto"
)

func main() {
	natsURL := nats.DefaultURL
	if url := os.Getenv("NATS_URL"); url != "" {
		natsURL = url
	}

	client, err := mesh.Connect(natsURL)
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer client.Close()

	// Subscribe to threat alerts
	_, err = client.Subscribe("sentinel.threats.>", func(m *nats.Msg) {
		var alert pb.ThreatAlert
		if err := proto.Unmarshal(m.Data, &alert); err != nil {
			// May not be a ThreatAlert, could be a ThreatConfirm
			// We just ignore unmarshal errors here for simplicity in testing
			return
		}
		
		log.Printf("Received ThreatAlert on %s: [%s] Confidence: %.2f from Node: %s", 
			m.Subject, alert.ThreatType, alert.Confidence, alert.DetectorNodeId)

		// Echoing back a ThreatConfirm for test_nats_latency.py to measure round-trip time
		if alert.ThreatType == "PING_TEST" {
			confirm := &pb.ThreatConfirm{
				ThreatId:          alert.ThreatId,
				ConfirmedByNodeId: "go-edge-agent",
				Timestamp:         alert.Timestamp,
				IsAuthorized:      true,
			}
			data, _ := proto.Marshal(confirm)
			client.Publish("sentinel.threats.confirm", data)
			log.Printf("Sent ThreatConfirm for PING_TEST: %s", alert.ThreatId)
		}
	})

	if err != nil {
		log.Fatalf("Failed to subscribe: %v", err)
	}

	log.Println("Go Edge Agent is running. Listening on sentinel.threats.>")

	// Wait for termination signal
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
	log.Println("Shutting down Edge Agent")
}

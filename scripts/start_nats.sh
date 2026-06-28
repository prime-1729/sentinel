#!/bin/bash
set -e

PROJECT_ROOT=$(pwd)
BIN_DIR="$PROJECT_ROOT/.tools/bin"

if [ ! -f "$BIN_DIR/nats-server" ]; then
    echo "Error: nats-server not found. Please run scripts/setup_deps.sh first."
    exit 1
fi

echo "Starting NATS Server for testing..."
"$BIN_DIR/nats-server" &
NATS_PID=$!
echo "NATS Server started with PID: $NATS_PID"
echo $NATS_PID > .nats.pid
wait $NATS_PID

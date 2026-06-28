#!/bin/bash
set -e

PROJECT_ROOT=$(pwd)
TOOLS_DIR="$PROJECT_ROOT/.tools"
BIN_DIR="$TOOLS_DIR/bin"

mkdir -p "$BIN_DIR"
mkdir -p "$TOOLS_DIR/tmp"

cd "$TOOLS_DIR/tmp"

echo "=== Installing Go 1.21.6 ==="
if [ ! -f "$BIN_DIR/go" ]; then
    wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz -O go.tar.gz
    tar -xzf go.tar.gz
    mv go "$TOOLS_DIR/"
    ln -s "$TOOLS_DIR/go/bin/go" "$BIN_DIR/go"
    ln -s "$TOOLS_DIR/go/bin/gofmt" "$BIN_DIR/gofmt"
else
    echo "Go already installed."
fi

echo "=== Installing Protoc 25.2 ==="
if [ ! -f "$BIN_DIR/protoc" ]; then
    wget -q https://github.com/protocolbuffers/protobuf/releases/download/v25.2/protoc-25.2-linux-x86_64.zip -O protoc.zip
    unzip -q protoc.zip -d protoc
    mv protoc/bin/protoc "$BIN_DIR/"
    mv protoc/include "$TOOLS_DIR/"
else
    echo "Protoc already installed."
fi

echo "=== Installing NATS Server 2.10.9 ==="
if [ ! -f "$BIN_DIR/nats-server" ]; then
    wget -q https://github.com/nats-io/nats-server/releases/download/v2.10.9/nats-server-v2.10.9-linux-amd64.tar.gz -O nats.tar.gz
    tar -xzf nats.tar.gz
    mv nats-server-v2.10.9-linux-amd64/nats-server "$BIN_DIR/"
else
    echo "NATS Server already installed."
fi

# Cleanup
cd "$PROJECT_ROOT"
rm -rf "$TOOLS_DIR/tmp"

echo "=== Installing protoc-gen-go ==="
export GOPATH="$TOOLS_DIR/gopath"
export PATH="$BIN_DIR:$PATH"
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
ln -sf "$GOPATH/bin/protoc-gen-go" "$BIN_DIR/protoc-gen-go"

echo "=== Setup Complete ==="
echo "Please run: export PATH=\"$BIN_DIR:\$PATH\""

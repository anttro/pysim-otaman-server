#!/usr/bin/env bash
set -e

# pysim-otaman-server start script
# Starts the server, preferring the venv if it exists.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ -f "$VENV_DIR/bin/pysim-otaman-server" ]; then
    echo "Starting pysim-otaman-server from venv on http://127.0.0.1:8080"
    "$VENV_DIR/bin/pysim-otaman-server" --http-port 8080
elif command -v pysim-otaman-server &> /dev/null; then
    echo "Starting pysim-otaman-server on http://127.0.0.1:8080"
    pysim-otaman-server --http-port 8080
elif [ -f "$SCRIPT_DIR/pysim_otaman_server/__main__.py" ]; then
    echo "Starting pysim-otaman-server from source on http://127.0.0.1:8080"
    cd "$SCRIPT_DIR" && python3 -m pysim_otaman_server --http-port 8080
else
    echo "Error: pysim-otaman-server not installed."
    echo "Run setup.sh first or install manually:"
    echo "  pip install pysim-otaman-server"
    exit 1
fi
#!/bin/bash
set -e

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    if [ -n "$PID_XVFB" ]; then
        kill $PID_XVFB || true
    fi
}

# Trap exit/interrupt signals
trap cleanup EXIT INT TERM

# Clean stale lock files if any (container restart case)
rm -f /tmp/.X0-lock

echo "Starting Xvfb on :0..."
Xvfb :0 -screen 0 ${RESOLUTION:-1280x800x24} &
PID_XVFB=$!
sleep 2

echo "Starting Fluxbox..."
fluxbox &

echo "Starting x11vnc..."
x11vnc -display :0 -forever -nopw -shared -bg

echo "Starting websockify (NoVNC)..."
# Proxy localhost:6080 -> localhost:5900 (VNC)
websockify --web /usr/share/novnc/ 6080 localhost:5900 &

echo "Starting Qt Application..."
# Add /app to PYTHONPATH to find services module
export PYTHONPATH=$PYTHONPATH:/app
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --ignore-gpu-blocklist"
python services/qt-client/main.py

# Cleanup handled by trap

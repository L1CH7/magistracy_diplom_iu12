#!/bin/bash
set -e

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
python services/qt-client/main.py --no-sandbox --ignore-gpu-blocklist

# Cleanup
kill $PID_XVFB

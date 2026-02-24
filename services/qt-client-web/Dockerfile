FROM python:3.11-slim

# Install system dependencies
# xvfb: Virtual Framebuffer (X11 display)
# x11vnc: VNC server
# fluxbox: Minimal Window Manager
# novnc: Web-based VNC viewer
# net-tools: for netstat/debugging
# libx11-6, libxext6: X11 libraries
# qt dependencies: minimal libs for PyQt5
RUN apt-get update && apt-get install -y \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    net-tools \
    libx11-6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    python3-pyqt5 \
    python3-pyqt5.qtwebengine \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Setup NoVNC (link to standard location if needed, usually /usr/share/novnc)
# websockify is usually installed as a dependency of novnc package in Debian/Ubuntu

WORKDIR /app

# Copy requirements from the correct location (context is root)
COPY services/qt-client/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code to match repo structure
COPY services/qt-client /app/services/qt-client
COPY services/common /app/services/common
COPY configs /app/configs

# Setup entrypoint script
COPY services/qt-client-web/start.sh /start.sh
RUN chmod +x /start.sh

ENV DISPLAY=:0
ENV RESOLUTION=1280x800x24

EXPOSE 6080

CMD ["/start.sh"]

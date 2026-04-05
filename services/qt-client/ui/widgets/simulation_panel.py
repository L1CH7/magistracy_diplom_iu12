"""
Simulation control panel widget.

Provides controls for agent simulation:
- Simulation speed control
- Agent lifecycle buttons (start, stop, restart, delete)
- Route management buttons (clear routes, clear points)
- Agent status display (speed, ETA, state)
- FPS control
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QDoubleSpinBox, QGroupBox
)
from PyQt5.QtCore import pyqtSignal, Qt

from loguru import logger as log
from services.common.config import config_loader


class SimulationPanel(QWidget):
    """
    Panel for simulation control.

    Signals:
        start_agent_clicked: User clicked "Start Agent" button
        stop_agent_clicked: User clicked "Stop Agent" button
        restart_agent_clicked: User clicked "Restart Agent" button
        delete_agent_clicked: User clicked "Delete Agent" button
        clear_routes_clicked: User clicked "Clear Routes" button
        clear_points_clicked: User clicked "Clear All Points" button
        sim_speed_changed: Simulation speed changed (float value)
        fps_changed: FPS changed (int value)
    """

    # Signals
    start_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    step_clicked = pyqtSignal()
    apply_clicked = pyqtSignal(dict) # params: accel, fps, chaos
    clear_routes_clicked = pyqtSignal()
    clear_points_clicked = pyqtSignal()

    def __init__(self, parent: QWidget = None):
        """Initialize simulation panel."""
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        """Initialize UI components."""
        # Load config
        config = config_loader.load('client/simulation.yaml')
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # 1. Simulation Parameters Group (Config for START)
        param_group = QGroupBox(self.tr("Simulation Parameters"))
        param_layout = QVBoxLayout(param_group)
        
        # Agents Count
        agents_layout = QHBoxLayout()
        agents_layout.addWidget(QLabel(self.tr("Agents:")))
        self.agents_spin = QSpinBox()
        self.agents_spin.setRange(1, 1000000)
        self.agents_spin.setValue(50000)
        agents_layout.addWidget(self.agents_spin)
        param_layout.addLayout(agents_layout)

        # ASF (Availability Search Factor)
        asf_layout = QHBoxLayout()
        asf_layout.addWidget(QLabel(self.tr("ASF:")))
        self.asf_spin = QSpinBox()
        self.asf_spin.setRange(1, 1000)
        self.asf_spin.setValue(50)
        asf_layout.addWidget(self.asf_spin)
        param_layout.addLayout(asf_layout)

        # Duration (0 = inf)
        dur_layout = QHBoxLayout()
        dur_layout.addWidget(QLabel(self.tr("Duration (s):")))
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(0, 86400)
        self.dur_spin.setValue(0)
        dur_layout.addWidget(self.dur_spin)
        param_layout.addLayout(dur_layout)

        # Chaos Factor (%)
        chaos_layout = QHBoxLayout()
        chaos_layout.addWidget(QLabel(self.tr("Chaos (%):")))
        self.chaos_spin = QDoubleSpinBox()
        self.chaos_spin.setRange(0.0, 100.0)
        self.chaos_spin.setValue(0.0)
        self.chaos_spin.setSingleStep(1.0)
        chaos_layout.addWidget(self.chaos_spin)
        param_layout.addLayout(chaos_layout)

        layout.addWidget(param_group)

        # 2. Simulation Control Group (Live Actions)
        sim_group = QGroupBox(self.tr("Simulation Control"))
        sim_layout = QVBoxLayout(sim_group)

        # Speed and FPS row
        speed_fps_layout = QHBoxLayout()
        
        # Speed
        speed_fps_layout.addWidget(QLabel(self.tr("Speed (x):")))
        self.sim_speed_spin = QDoubleSpinBox()
        self.sim_speed_spin.setRange(0.1, 3000.0)
        self.sim_speed_spin.setValue(100.0)
        self.sim_speed_spin.setDecimals(1)
        speed_fps_layout.addWidget(self.sim_speed_spin)

        # FPS (float support)
        speed_fps_layout.addWidget(QLabel(self.tr("FPS:")))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 60.0)
        self.fps_spin.setValue(25.0)
        self.fps_spin.setDecimals(1)
        speed_fps_layout.addWidget(self.fps_spin)
        
        sim_layout.addLayout(speed_fps_layout)

        # Apply Button
        self.apply_btn = QPushButton(self.tr("Apply Settings"))
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        sim_layout.addWidget(self.apply_btn)

        # Lifecycle Buttons
        lifecycle_layout = QHBoxLayout()
        
        self.start_pause_btn = QPushButton(self.tr("Start"))
        self.start_pause_btn.setCheckable(True)
        self.start_pause_btn.clicked.connect(self._on_start_pause_clicked)
        lifecycle_layout.addWidget(self.start_pause_btn)

        self.stop_btn = QPushButton(self.tr("Stop"))
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        lifecycle_layout.addWidget(self.stop_btn)

        self.step_btn = QPushButton(self.tr("Step"))
        self.step_btn.clicked.connect(self._on_step_clicked)
        lifecycle_layout.addWidget(self.step_btn)

        sim_layout.addLayout(lifecycle_layout)
        layout.addWidget(sim_group)

        # 3. Route Management
        route_group = QGroupBox(self.tr("Route Management"))
        route_layout = QVBoxLayout(route_group)

        self.clear_routes_btn = QPushButton(self.tr("Clear Routes"))
        self.clear_routes_btn.clicked.connect(self.clear_routes_clicked.emit)
        route_layout.addWidget(self.clear_routes_btn)

        self.clear_points_btn = QPushButton(self.tr("Clear All Points"))
        self.clear_points_btn.clicked.connect(self.clear_points_clicked.emit)
        route_layout.addWidget(self.clear_points_btn)

        layout.addWidget(route_group)

        # 4. Status
        status_group = QGroupBox(self.tr("Simulation Status"))
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel(self.tr("Ready"))
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_group)

        layout.addStretch()

    def _on_start_pause_clicked(self, checked):
        """Handle Start/Pause toggle."""
        if checked:
            self.start_pause_btn.setText(self.tr("Pause"))
            self.start_clicked.emit()
        else:
            self.start_pause_btn.setText(self.tr("Start"))
            self.pause_clicked.emit()

    def _on_stop_clicked(self):
        """Handle Stop."""
        self.start_pause_btn.setChecked(False)
        self.start_pause_btn.setText(self.tr("Start"))
        self.stop_clicked.emit()

    def _on_step_clicked(self):
        """Handle Step."""
        self.step_clicked.emit()

    def _on_apply_clicked(self):
        """Handle Apply button click."""
        params = {
            "accel": self.sim_speed_spin.value(),
            "fps": self.fps_spin.value(),
            "chaos": self.chaos_spin.value()
        }
        log.info(f"Apply sim settings: {params}")
        self.apply_clicked.emit(params)

    def get_sim_params(self) -> dict:
        """Get current parameters from UI for START command."""
        return {
            "num_agents": self.agents_spin.value(),
            "asf": self.asf_spin.value(),
            "duration": self.dur_spin.value(),
            "chaos": self.chaos_spin.value(),
            "accel": self.sim_speed_spin.value(),
            "fps": self.fps_spin.value()
        }

    def update_agent_status(
        self,
        speed_kmh: float,
        eta_seconds: float,
        state: str
    ):
        """
        Update agent status display.

        Args:
            speed_kmh: Current speed in km/h
            eta_seconds: Estimated time to arrival in seconds
            state: Agent state (moving, stopped, waiting, etc)
        """
        # Format ETA as HH:MM:SS
        hours = int(eta_seconds // 3600)
        minutes = int((eta_seconds % 3600) // 60)
        seconds = int(eta_seconds % 60)
        eta_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Format status text (no emojis)
        status_text = self.tr("State:") + f" {state}\n"
        status_text += self.tr("Speed:") + f" {speed_kmh:.1f} km/h\n"
        status_text += self.tr("ETA:") + f" {eta_str}"

        self.status_label.setText(status_text)

    def clear_agent_status(self):
        """Clear agent status display."""
        self.status_label.setText(self.tr("No active agent"))

    def set_agent_active(self, active: bool):
        """
        Update button states based on agent active status.

        Args:
            active: True if agent is active, False otherwise
        """
        self.start_btn.setEnabled(not active)
        self.stop_btn.setEnabled(active)
        self.restart_btn.setEnabled(active)
        self.delete_btn.setEnabled(active)

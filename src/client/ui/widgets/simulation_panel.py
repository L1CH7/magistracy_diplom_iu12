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
from src.utils.config_loader import config_loader


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
    start_agent_clicked = pyqtSignal()
    stop_agent_clicked = pyqtSignal()
    restart_agent_clicked = pyqtSignal()
    delete_agent_clicked = pyqtSignal()
    clear_routes_clicked = pyqtSignal()
    clear_points_clicked = pyqtSignal()
    sim_speed_changed = pyqtSignal(float)
    fps_changed = pyqtSignal(int)

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
        layout.setSpacing(10)

        # Simulation controls group
        sim_group = QGroupBox("Simulation Controls")
        sim_layout = QVBoxLayout(sim_group)

        # Simulation speed control
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Sim Speed (x):"))
        
        self.sim_speed_spinbox = QDoubleSpinBox()
        self.sim_speed_spinbox.setRange(
            config['speed']['min'],
            config['speed']['max']
        )
        self.sim_speed_spinbox.setSingleStep(
            config['speed']['step']
        )
        self.sim_speed_spinbox.setValue(
            config['speed']['default']
        )
        self.sim_speed_spinbox.setDecimals(1)
        self.sim_speed_spinbox.valueChanged.connect(
            self._on_sim_speed_changed
        )
        speed_layout.addWidget(self.sim_speed_spinbox)
        speed_layout.addStretch()
        sim_layout.addLayout(speed_layout)

        # FPS control
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS:"))
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(
            config['fps']['min'],
            config['fps']['max']
        )
        self.fps_spinbox.setValue(config['fps']['default'])
        self.fps_spinbox.valueChanged.connect(self._on_fps_changed)
        fps_layout.addWidget(self.fps_spinbox)
        fps_layout.addStretch()
        sim_layout.addLayout(fps_layout)

        layout.addWidget(sim_group)

        # Agent control group
        agent_group = QGroupBox("Agent Control")
        agent_layout = QVBoxLayout(agent_group)

        # Agent buttons row 1
        btn_row1 = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Agent")
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row1.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        btn_row1.addWidget(self.stop_btn)
        
        agent_layout.addLayout(btn_row1)

        # Agent buttons row 2
        btn_row2 = QHBoxLayout()
        
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self._on_restart_clicked)
        self.restart_btn.setEnabled(False)
        btn_row2.addWidget(self.restart_btn)
        
        self.delete_btn = QPushButton("Delete Agent")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        btn_row2.addWidget(self.delete_btn)
        
        agent_layout.addLayout(btn_row2)

        layout.addWidget(agent_group)

        # Route management group
        route_group = QGroupBox("Route Management")
        route_layout = QVBoxLayout(route_group)

        self.clear_routes_btn = QPushButton("Clear Routes")
        self.clear_routes_btn.clicked.connect(self._on_clear_routes_clicked)
        route_layout.addWidget(self.clear_routes_btn)

        self.clear_points_btn = QPushButton("Clear All Points")
        self.clear_points_btn.clicked.connect(self._on_clear_points_clicked)
        route_layout.addWidget(self.clear_points_btn)

        layout.addWidget(route_group)

        # Agent status group
        status_group = QGroupBox("Agent Status")
        status_layout = QVBoxLayout(status_group)

        self.status_label = QLabel("No active agent")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        status_layout.addWidget(self.status_label)

        layout.addWidget(status_group)

        layout.addStretch()

    def _on_start_clicked(self):
        """Handle Start Agent button click."""
        log.info("start_agent_clicked")
        self.start_agent_clicked.emit()

    def _on_stop_clicked(self):
        """Handle Stop button click."""
        log.info("stop_agent_clicked")
        self.stop_agent_clicked.emit()

    def _on_restart_clicked(self):
        """Handle Restart button click."""
        log.info("restart_agent_clicked")
        self.restart_agent_clicked.emit()

    def _on_delete_clicked(self):
        """Handle Delete Agent button click."""
        log.info("delete_agent_clicked")
        self.delete_agent_clicked.emit()

    def _on_clear_routes_clicked(self):
        """Handle Clear Routes button click."""
        log.info("clear_routes_clicked")
        self.clear_routes_clicked.emit()

    def _on_clear_points_clicked(self):
        """Handle Clear All Points button click."""
        log.info("clear_points_clicked")
        self.clear_points_clicked.emit()

    def _on_sim_speed_changed(self, value: float):
        """Handle simulation speed change."""
        log.info("sim_speed_changed", value=value)
        self.sim_speed_changed.emit(value)

    def _on_fps_changed(self, value: int):
        """Handle FPS change."""
        log.info("fps_changed", value=value)
        self.fps_changed.emit(value)

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
        status_text = f"State: {state}\n"
        status_text += f"Speed: {speed_kmh:.1f} km/h\n"
        status_text += f"ETA: {eta_str}"

        self.status_label.setText(status_text)

    def clear_agent_status(self):
        """Clear agent status display."""
        self.status_label.setText("No active agent")

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

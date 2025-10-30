from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget

class SelectedPointsWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background-color: #f9fafb; border-radius: 6px; border: 1px solid #e5e7eb; }"
        )
        self.setMaximumHeight(200)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(6)
        self.points_list = QWidget()
        self.layout.addWidget(self.points_list)
        self.layout.addStretch()

    def update_points(self, points):
        # Очищаем points_list
        for i in reversed(range(self.layout.count())):
            item = self.layout.itemAt(i)
            widget = item.widget()
            if widget and widget != self.points_list:
                widget.deleteLater()
        # Добавляем QLabel для каждой точки
        from PyQt5.QtWidgets import QLabel
        self.points_list = QWidget()
        points_layout = QVBoxLayout(self.points_list)
        for idx, point in enumerate(points):
            label = QLabel(f"{idx+1}: {point['lat']:.6f}, {point['lon']:.6f}")
            points_layout.addWidget(label)
        self.layout.insertWidget(0, self.points_list)
        self.layout.addStretch()

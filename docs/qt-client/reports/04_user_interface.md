# Пользовательский интерфейс

## Введение

Пользовательский интерфейс построен по принципу "карта превыше всего": полноэкранная карта с оверлейной боковой панелью, содержащей элементы управления. Архитектура UI разделена на три слоя:
- **MainWindow** — корневое окно, управление WebView и layout.
- **MainWindowUI** — setup UI-компонентов (sidebar, widgets).
- **MainWindowHandlers** — обработка событий (клики, горячие клавиши, сигналы).

Все кастомные виджеты вынесены в `ui/widgets/` для переиспользования и тестирования.

## Архитектура UI

### Структура окна

```{.mermaid}
graph TB
    subgraph "MainWindow (QMainWindow)"
        WebView[QWebEngineView<br/>Fullscreen Map]
        
        subgraph "Overlay Widgets"
            Sidebar[Sidebar<br/>Right Panel]
            ZoomCtrl[ZoomControl<br/>Bottom Right]
        end
        
        subgraph "Sidebar Components"
            PointsPanel[PointsPanel<br/>Route Points]
            RoutesPanel[RoutesPanel<br/>K-Routes List]
            SimPanel[SimulationPanel<br/>Agent Control]
            StatusPanel[StatusPanel<br/>System Info]
        end
    end
    
    WebView -.overlay.-> Sidebar
    WebView -.overlay.-> ZoomCtrl
    
    Sidebar --> PointsPanel
    Sidebar --> RoutesPanel
    Sidebar --> SimPanel
    Sidebar --> StatusPanel
    
    style WebView fill:#3b82f6,color:#fff
    style Sidebar fill:#22c55e,color:#fff
```

### Разделение ответственности

**Таблица: UI-компоненты**

| Компонент | Файл | Ответственность |
|-----------|------|----------------|
| `MainWindow` | `ui/main_window.py` | Жизненный цикл окна, setup WebView, HTTP-сервер для assets |
| `MainWindowUI` | `ui/main_window_ui.py` | Создание и позиционирование виджетов |
| `MainWindowHandlers` | `ui/main_window_handlers.py` | Обработка событий (клики, сигналы, горячие клавиши) |
| `SidebarWidget` | `ui/widgets/sidebar_widget.py` | Контейнер для панелей |
| `PointsPanel` | `ui/widgets/points_panel.py` | Отображение выбранных точек маршрута |
| `RoutesPanel` | `ui/widgets/route_panel.py` | Список K-маршрутов с кнопками выбора |
| `SimulationPanel` | `ui/widgets/simulation_panel.py` | Управление симуляцией агента (заглушка) |
| `StatusPanel` | `ui/widgets/status_panel.py` | Статус подключения, метрики |
| `ZoomControl` | `ui/widgets/zoom_control.py` | Слайдер зума + кнопки +/- |

## Компоненты интерфейса

### Sidebar: Боковая панель

Контейнер для всех панелей управления. Реализован как `QWidget` с вертикальным layout.

```{.python caption="ui/widgets/sidebar_widget.py (фрагмент)"}
class SidebarWidget(QWidget):
    """Right sidebar with collapsible sections."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setStyleSheet("""
            #sidebar {
                background-color: rgba(255, 255, 255, 0.95);
                border-left: 1px solid #d1d5db;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Add panels
        self.points_panel = PointsPanel()
        self.routes_panel = RoutesPanel()
        self.simulation_panel = SimulationPanel()
        self.status_panel = StatusPanel()
        
        layout.addWidget(self.points_panel)
        layout.addWidget(self.routes_panel)
        layout.addWidget(self.simulation_panel)
        layout.addWidget(self.status_panel)
        layout.addStretch()
```

### PointsPanel: Панель точек маршрута

Отображает выбранные точки (From, Via, To) с кнопками управления.

**Функции:**
- Отображение координат точек.
- Кнопки "Get K Routes" (K=1, 3, 5).
- Кнопка "Clear Points".

```{.python caption="ui/widgets/points_panel.py (фрагмент)"}
class PointsPanel(QWidget):
    """Panel for displaying selected route points."""
    
    get_routes_clicked = pyqtSignal(int)  # K value
    clear_points_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Route Points")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Points display
        self.points_label = QLabel("No points selected")
        self.points_label.setWordWrap(True)
        layout.addWidget(self.points_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_get_1 = QPushButton("Get Route")
        self.btn_get_3 = QPushButton("Get 3")
        self.btn_get_5 = QPushButton("Get 5")
        self.btn_clear = QPushButton("Clear")
        
        self.btn_get_1.clicked.connect(lambda: self.get_routes_clicked.emit(1))
        self.btn_get_3.clicked.connect(lambda: self.get_routes_clicked.emit(3))
        self.btn_get_5.clicked.connect(lambda: self.get_routes_clicked.emit(5))
        self.btn_clear.clicked.connect(self.clear_points_clicked.emit)
        
        btn_layout.addWidget(self.btn_get_1)
        btn_layout.addWidget(self.btn_get_3)
        btn_layout.addWidget(self.btn_get_5)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)
    
    def update_points(self, points: list):
        """Update displayed points."""
        if not points:
            self.points_label.setText("No points selected")
            return
        
        text = ""
        for i, point in enumerate(points):
            label = "From" if i == 0 else ("To" if i == len(points)-1 else f"Via {i}")
            text += f"{label}: {point['lat']:.4f}, {point['lon']:.4f}\n"
        
        self.points_label.setText(text.strip())
```

### RoutesPanel: Панель маршрутов

Отображает список K-маршрутов с метриками (длина, время) и кнопками выбора.

```{.python caption="ui/widgets/route_panel.py (фрагмент)"}
class RoutesPanel(QWidget):
    """Panel for displaying K-routes with selection."""
    
    route_selected = pyqtSignal(int)  # route_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.routes = []
    
    def update_routes(self, routes: list):
        """Update displayed routes."""
        self.routes = routes
        self._clear_buttons()
        
        if not routes:
            self.routes_label.setText("No routes")
            return
        
        # Create button for each route
        for i, route in enumerate(routes):
            route_id = route.get('route_id', i)
            distance_m = route.get('distance_m', 0)
            time_s = route.get('time_s', 0)
            
            btn = QPushButton(f"Route {i+1}: {distance_m/1000:.1f} km, {time_s/60:.0f} min")
            btn.clicked.connect(lambda checked, rid=route_id: self.route_selected.emit(rid))
            
            self.routes_layout.addWidget(btn)
```

### ZoomControl: Управление зумом

Слайдер зума + кнопки +/- для изменения масштаба карты.

**Проблема:** Синхронизация зума между слайдером и картой без циклических обновлений (см. Главу 1).

**Решение:** Флаг `_skip_next_zoom_update` в `MainWindowHandlers`.

```{.python caption="ui/widgets/zoom_control.py (концептуально)"}
class ZoomControl(QWidget):
    """Zoom slider + buttons."""
    
    zoom_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Zoom in button
        self.btn_in = QPushButton("+")
        self.btn_in.clicked.connect(lambda: self.zoom_changed.emit(self.slider.value() + 1))
        
        # Slider
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 19)
        self.slider.setValue(12)
        self.slider.valueChanged.connect(self.zoom_changed.emit)
        
        # Zoom out button
        self.btn_out = QPushButton("-")
        self.btn_out.clicked.connect(lambda: self.zoom_changed.emit(self.slider.value() - 1))
        
        layout.addWidget(self.btn_in)
        layout.addWidget(self.slider)
        layout.addWidget(self.btn_out)
```

## Обработка событий

### Горячие клавиши

**Таблица: Горячие клавиши**

| Клавиша | Действие |
|---------|----------|
| `Ctrl+1` | Установить точку "From" в позиции курсора |
| `Ctrl+2` | Установить точку "To" в позиции курсора |
| `Ctrl+3` | Добавить точку "Via" в позиции курсора |
| `Ctrl+Shift+D` | Переключить отладочную сетку (debug mode) |
| `Ctrl+Shift+V` | Вывести bbox видимой области в лог |
| `Ctrl+Q` | Закрыть приложение |

### Реализация

```{.python caption="ui/main_window.py: Setup Shortcuts"}
def _setup_shortcuts(self):
    """Setup keyboard shortcuts."""
    # Ctrl+1: Set From point
    QShortcut(QKeySequence("Ctrl+1"), self, self._on_ctrl_1)
    
    # Ctrl+2: Set To point
    QShortcut(QKeySequence("Ctrl+2"), self, self._on_ctrl_2)
    
    # Ctrl+3: Add Via point
    QShortcut(QKeySequence("Ctrl+3"), self, self._on_ctrl_3)
    
    # Ctrl+Q: Quit
    QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
```

### Обработчики

```{.python caption="ui/main_window_handlers.py: Ctrl+1 Handler"}
def _on_ctrl_1(self):
    """Ctrl+1: Set From point at cursor position."""
    js_code = "window.app.getCursorPosition();"
    
    def callback(result):
        if result and 'lat' in result and 'lon' in result:
            log.info(f"Setting From point: {result}")
            
            # Set in JavaScript
            js_set = f"window.app.setStart({result});"
            self.web_view.page().runJavaScript(js_set)
            
            # Update UI
            self._update_selected_points()
        else:
            log.warning("No cursor position available")
    
    self.web_view.page().runJavaScript(js_code, callback)
```

## Интернационализация

Приложение поддерживает локализацию через Qt Linguist. Переводы хранятся в `translations/`.

### Процесс локализации

1. **Извлечение строк:** `pylupdate5` сканирует Python-код и извлекает строки, обёрнутые в `self.tr()`.
2. **Перевод:** Редактирование `.ts` файлов в Qt Linguist.
3. **Компиляция:** `lrelease` компилирует `.ts` → `.qm` (бинарный формат).
4. **Загрузка:** `QTranslator` загружает `.qm` при старте приложения.

```{.python caption="ui/main_window.py: Загрузка переводов"}
def _setup_translation(self):
    """Load translations based on config."""
    try:
        gui_config = config_loader.load('client/gui.yaml')
        locale = gui_config.get('locale', 'en')
        
        if locale != 'en':
            translator = QTranslator()
            qm_file = os.path.join(
                os.path.dirname(__file__), 
                '..', 
                'translations', 
                f'app_{locale}.qm'
            )
            
            if translator.load(qm_file):
                QApplication.instance().installTranslator(translator)
                log.info(f"Loaded translation: {locale}")
            else:
                log.warning(f"Translation file not found: {qm_file}")
    except Exception as e:
        log.error(f"Failed to load translation: {e}")
```

### Makefile: Автоматизация

```{.makefile caption="Makefile: Translation Workflow"}
# Update .ts files from source code
update-ts: install
	$(PYLUPDATE) $(UI_SOURCES) -ts $(TS_FILES)

# Compile .ts to .qm
compile: install
	$(eval LRELEASE := $(shell find $(VENV_DIR) -type f -name lrelease | head -n 1))
	$(LRELEASE) translations/*.ts
```

## Стилизация

### Изоляция от системной темы

Для консистентного отображения на разных платформах (KDE, GNOME, Windows) используется стиль Fusion с кастомной палитрой:

```{.python caption="main.py: Fusion Style"}
os.environ["QT_QPA_PLATFORMTHEME"] = ""
os.environ["QT_STYLE_OVERRIDE"] = "Fusion"

app = QApplication(sys.argv)
app.setStyle("Fusion")

palette = QPalette()
palette.setColor(QPalette.Window, QColor(240, 240, 240))
palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
palette.setColor(QPalette.Base, QColor(255, 255, 255))
palette.setColor(QPalette.Button, QColor(240, 240, 240))
palette.setColor(QPalette.Highlight, QColor(76, 163, 224))
app.setPalette(palette)
```

### Кастомные стили

Виджеты используют `setStyleSheet()` для кастомизации:

```{.python caption="ui/widgets/sidebar_widget.py: Стили"}
self.setStyleSheet("""
    #sidebar {
        background-color: rgba(255, 255, 255, 0.95);
        border-left: 1px solid #d1d5db;
    }
    QPushButton {
        background-color: #3b82f6;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #2563eb;
    }
    QPushButton:pressed {
        background-color: #1d4ed8;
    }
""")
```

## Выводы

Архитектура UI обеспечила:
- **Модульность:** Кастомные виджеты переиспользуются и тестируются независимо.
- **Отзывчивость:** Разделение обработчиков событий (`MainWindowHandlers`) от setup UI (`MainWindowUI`).
- **Консистентность:** Изоляция от системной темы через Fusion style.
- **Локализация:** Поддержка переводов через Qt Linguist.

**Компромиссы:**
- **Сложность стилизации:** Qt StyleSheets менее гибкие, чем CSS.
- **Производительность:** Оверлейные виджеты добавляют накладные расходы на композитинг.

**Метрики:**
- Количество кастомных виджетов: 8.
- Поддерживаемые языки: 2 (en, ru).
- Время инициализации UI: ~100 мс.

---

## Приложение: Структура виджетов

```
ui/
├── main_window.py          # MainWindow class
├── main_window_handlers.py # Event handlers
├── main_window_ui.py       # UI setup
└── widgets/
    ├── sidebar_widget.py   # Sidebar container
    ├── points_panel.py     # Route points panel
    ├── route_panel.py      # K-routes panel
    ├── simulation_panel.py # Agent control (stub)
    ├── status_panel.py     # Status display
    └── zoom_control.py     # Zoom slider
```

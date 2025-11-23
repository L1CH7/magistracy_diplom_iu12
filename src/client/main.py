"""Main entry point for Navigation MAS client."""
import sys
import os
os.environ['QTWEBENGINE_REMOTE_DEBUGGING_PORT'] = '9222'  # remote debugging for web engine

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.loguru_config import configure_loguru
from PyQt5.QtWidgets import QApplication
from src.client.ui.main_window import MainWindow


def main():
    """Main entry point - minimal configuration."""
    # Monkey-patch print to capture Qt WebEngine errors
    import builtins
    import traceback
    original_print = builtins.print

    def traced_print(*args, **kwargs):
        msg = ' '.join(str(a) for a in args)
        if 'js:' in msg.lower() and 'syntax' in msg.lower():
            stack = '\n'.join(traceback.format_stack()[:-1])
            original_print(f"[TRACED] {msg}\nStack:\n{stack}", **kwargs)
        else:
            original_print(*args, **kwargs)

    builtins.print = traced_print
    
    # Initialize logging
    configure_loguru(
        service_name="gui",
        log_level="TRACE",
        log_to_file=True,
        stdout=True
    )
    
    # Изоляция от системной темы (не зависит от KDE/GNOME)
    os.environ["QT_QPA_PLATFORMTHEME"] = ""  # Disable platform theme
    os.environ["QT_STYLE_OVERRIDE"] = "Fusion"  # Use Qt's Fusion style

    app = QApplication(sys.argv)
    
    # Явно устанавливаем Fusion style и светлую палитру
    app.setStyle("Fusion")
    
    from PyQt5.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.Link, QColor(0, 0, 255))
    palette.setColor(QPalette.Highlight, QColor(76, 163, 224))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    
    # Server URL from environment or default (localhost для локального запуска)
    server_url = os.getenv("SERVER_URL", "http://localhost:8000")
    
    # Create and show main window
    window = MainWindow(server_url)
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

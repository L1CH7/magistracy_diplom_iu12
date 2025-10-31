"""Main entry point for Navigation MAS client."""
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from PyQt5.QtWidgets import QApplication
from src.client.ui.main_window import MainWindow


def main():
    """Main entry point - minimal configuration."""
    app = QApplication(sys.argv)
    
    # Server URL from environment or default
    server_url = "http://server:8000"
    
    # Create and show main window
    window = MainWindow(server_url)
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

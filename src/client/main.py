"""Main entry point for Navigation MAS client."""
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.loguru_config import configure_loguru
from PyQt5.QtWidgets import QApplication
from src.client.ui.main_window import MainWindow


def main():
    """Main entry point - minimal configuration."""
    # Initialize logging (JSON files in .agent_dir/logs/)
    configure_loguru(log_level="INFO", log_to_file=True)
    
    app = QApplication(sys.argv)
    
    # Server URL from environment or default
    server_url = "http://server:8000"
    
    # Create and show main window
    window = MainWindow(server_url)
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

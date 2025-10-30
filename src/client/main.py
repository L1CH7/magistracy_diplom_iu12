"""Main entry point for Navigation MAS client."""
import sys
from PyQt5.QtWidgets import QApplication
from main_window import NavigationGUI


def main():
    """Main entry point - minimal configuration."""
    app = QApplication(sys.argv)
    
    # Server URL from environment or default
    server_url = "http://server:8000"
    
    # Create and show main window
    gui = NavigationGUI(server_url)
    gui.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

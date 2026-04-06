import sys
from PySide6.QtWidgets import QApplication

from utils import apply_dark_theme
from main_window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = MainWindow()
    window.show()
    app.exec()

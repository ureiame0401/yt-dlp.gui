from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(230, 230, 230))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(230, 230, 230))
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    palette.setColor(QPalette.BrightText, QColor(255, 80, 80))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    app.setStyleSheet(
        """
        QToolTip {
            color: #ffffff;
            background-color: #2a2a2a;
            border: 1px solid #555555;
        }
        QLineEdit, QPlainTextEdit, QListWidget, QTableWidget, QComboBox {
            border: 1px solid #555555;
            border-radius: 6px;
            padding: 6px;
            background: #1e1e1e;
            gridline-color: #555555;
        }
        QPushButton {
            border: 1px solid #666666;
            border-radius: 6px;
            padding: 8px 12px;
            background: #353535;
        }
        QPushButton:hover {
            background: #404040;
        }
        QTabWidget::pane {
            border: 1px solid #555555;
            border-radius: 6px;
        }
        QTabBar::tab {
            padding: 8px 14px;
            margin: 2px;
        }
        QHeaderView::section {
            background: #353535;
            padding: 6px;
            border: 1px solid #555555;
        }
        QGroupBox {
            border: 1px solid #555555;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px 0 4px;
        }
        """
    )


def format_seconds(seconds):
    if seconds is None:
        return "未知"

    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "未知"

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_bytes(size):
    if size is None:
        return "-"
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "-"

    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"

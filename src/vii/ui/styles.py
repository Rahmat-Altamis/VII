"""Dark Qt stylesheet."""
DARK_QSS = """
QMainWindow, QWidget { background: #14161c; color: #e8eaf0; font-size: 13px; }
QListWidget, QTreeWidget, QTableWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #1d2029; border: 1px solid #2e3342; border-radius: 6px; padding: 6px; }
QPushButton { background: #2f6fed; color: white; border: none; border-radius: 8px; padding: 9px 16px; }
QPushButton:hover { background: #3d7ef5; }
QPushButton:disabled { background: #3a3f4d; color: #9aa0b0; }
QPushButton#danger { background: #b33636; }
QPushButton#ghost { background: #242832; border: 1px solid #394050; }
QLabel#h1 { font-size: 20px; font-weight: 700; }
QLabel#h2 { font-size: 15px; font-weight: 700; color: #bcd0ff; }
QLabel#dim { color: #9aa0b0; }
QTabWidget::pane { border: 1px solid #2e3342; border-radius: 8px; }
QTabBar::tab { background: #1d2029; padding: 8px 14px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #2f6fed; color: white; }
QProgressBar { border: 1px solid #2e3342; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #2f6fed; border-radius: 6px; }
QStatusBar { background: #101218; }
"""

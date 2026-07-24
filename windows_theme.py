"""Qt stylesheet inspired by Process Lasso's compact Windows dark interface."""

WINDOWS_DARK_THEME = """
/* Process Lasso Windows-style dark theme */
QWidget {
    background-color: #202225;
    color: #d9dde3;
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog {
    background-color: #202225;
}
QMainWindow > QWidget {
    background-color: #202225;
}

QTabWidget::pane {
    background-color: #202225;
    border: 1px solid #454a50;
    top: -1px;
}
QTabBar::tab {
    min-width: 72px;
    padding: 5px 12px;
    margin-right: 1px;
    background-color: #292c30;
    color: #b9bec5;
    border: 1px solid #454a50;
    border-bottom: 1px solid #454a50;
}
QTabBar::tab:selected {
    background-color: #202225;
    color: #ffffff;
    border-top: 2px solid #3d8fd1;
    border-bottom-color: #202225;
    padding-top: 4px;
}
QTabBar::tab:hover:!selected {
    background-color: #34383d;
    color: #ffffff;
}

QPushButton {
    min-height: 20px;
    padding: 2px 10px;
    background-color: #30343a;
    color: #e1e4e8;
    border: 1px solid #555b63;
    border-radius: 2px;
}
QPushButton:hover {
    background-color: #39424b;
    border-color: #6c9dc4;
}
QPushButton:pressed {
    background-color: #245d89;
    border-color: #4d9bd3;
}
QPushButton:disabled {
    background-color: #27292c;
    color: #6f747a;
    border-color: #3b3e42;
}

QGroupBox {
    margin-top: 8px;
    padding: 12px 7px 7px 7px;
    background-color: #24272a;
    border: 1px solid #454a50;
    border-radius: 2px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 7px;
    padding: 0 4px;
    color: #cfd4da;
    background-color: #24272a;
}

QTableWidget, QTreeView, QListWidget {
    background-color: #181a1c;
    alternate-background-color: #202326;
    color: #d8dce1;
    border: 1px solid #454a50;
    border-radius: 0;
    gridline-color: #33373c;
    selection-background-color: #225f91;
    selection-color: #ffffff;
    outline: none;
}
QTableWidget::item, QTreeView::item, QListWidget::item {
    padding: 2px 5px;
    border: 0;
}
QTableWidget::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background-color: #293844;
}
QTableWidget::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    background-color: #225f91;
    color: #ffffff;
}
QHeaderView {
    background-color: #292c30;
}
QHeaderView::section {
    padding: 3px 6px;
    background-color: #292c30;
    color: #d4d8dd;
    border: 0;
    border-right: 1px solid #454a50;
    border-bottom: 1px solid #555b63;
    font-weight: 600;
}
QHeaderView::section:hover {
    background-color: #34383d;
}
QTableCornerButton::section {
    background-color: #292c30;
    border: 0;
    border-right: 1px solid #454a50;
    border-bottom: 1px solid #555b63;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    min-height: 20px;
    padding: 1px 5px;
    background-color: #17191b;
    color: #e2e5e9;
    border: 1px solid #50555c;
    border-radius: 1px;
    selection-background-color: #225f91;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #3d8fd1;
}
QComboBox:hover {
    border-color: #6c9dc4;
}
QComboBox::drop-down {
    width: 18px;
    border-left: 1px solid #454a50;
    background-color: #30343a;
}
QComboBox QAbstractItemView {
    background-color: #202326;
    color: #d8dce1;
    border: 1px solid #555b63;
    selection-background-color: #225f91;
    selection-color: #ffffff;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 16px;
    background-color: #30343a;
    border-left: 1px solid #454a50;
}

QTextEdit, QPlainTextEdit {
    background-color: #151719;
    color: #d4d9df;
    border: 1px solid #454a50;
    border-radius: 0;
    padding: 3px;
    selection-background-color: #225f91;
    font-family: "Cascadia Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
}

QCheckBox, QRadioButton {
    spacing: 6px;
    background-color: transparent;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 13px;
    height: 13px;
    background-color: #17191b;
    border: 1px solid #626870;
}
QCheckBox::indicator {
    border-radius: 1px;
}
QRadioButton::indicator {
    border-radius: 7px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #2877b2;
    border-color: #65a9db;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #7db7df;
}

QMenu {
    background-color: #25282c;
    color: #e0e3e7;
    border: 1px solid #555b63;
    padding: 2px;
}
QMenu::item {
    padding: 4px 24px 4px 8px;
}
QMenu::item:selected {
    background-color: #225f91;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #73787e;
}
QMenu::separator {
    height: 1px;
    margin: 3px 5px;
    background-color: #454a50;
}

QScrollBar:vertical {
    width: 13px;
    margin: 13px 0;
    background-color: #202326;
    border-left: 1px solid #383c41;
}
QScrollBar::handle:vertical {
    min-height: 24px;
    background-color: #535960;
    border: 2px solid #202326;
}
QScrollBar::handle:vertical:hover {
    background-color: #707780;
}
QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
    height: 13px;
    background-color: #30343a;
}
QScrollBar:horizontal {
    height: 13px;
    margin: 0 13px;
    background-color: #202326;
    border-top: 1px solid #383c41;
}
QScrollBar::handle:horizontal {
    min-width: 24px;
    background-color: #535960;
    border: 2px solid #202326;
}
QScrollBar::handle:horizontal:hover {
    background-color: #707780;
}
QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal {
    width: 13px;
    background-color: #30343a;
}

QToolTip {
    padding: 3px 5px;
    background-color: #ffffe1;
    color: #111111;
    border: 1px solid #767676;
}
QSplitter::handle {
    background-color: #454a50;
}
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #454a50;
}
QStatusBar {
    background-color: #292c30;
    color: #c9cdd2;
    border-top: 1px solid #454a50;
}
QDialogButtonBox QPushButton {
    min-width: 76px;
}
"""

"""Native Qt design system inspired by the supplied macOS references."""
from pathlib import Path
from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QLabel, QFrame, QVBoxLayout, QHBoxLayout

ICONS = {
    "book": '<path d="M3 4h6a4 4 0 0 1 3 1.4A4 4 0 0 1 15 4h6v16h-6a4 4 0 0 0-3 1 4 4 0 0 0-3-1H3zM12 5.4V21"/>',
    "library": '<path d="M4 4v16M8 4v16M12 4v16M16 5l4 14"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "settings": '<path d="m9 3-.7 3-2.7 1L3 6l-1 3 2 2v3l-2 2 1 3 3-1 2 1 1 3h4l1-3 2-1 3 1 1-3-2-2v-3l2-2-1-3-3 1-2-1-1-3z"/><circle cx="10.5" cy="12" r="3"/>',
    "folder": '<path d="M3 6h7l2 3h9v11H3z"/>',
    "spark": '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6z"/>',
    "arrow": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    "back": '<path d="M19 12H5m6-6-6 6 6 6"/>',
    "send": '<path d="m3 3 18 9-18 9 3-9zM6 12h15"/>',
    "file": '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6"/>',
    "note": '<path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "key": '<circle cx="8" cy="9" r="5"/><path d="m12 13 8 8m-5-5 3-3m-1 5 3-3"/>',
}


def icon(name, color="#777b85", size=20):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{ICONS.get(name, ICONS["file"])}</svg>'
    pix = QPixmap(size * 2, size * 2); pix.fill(Qt.transparent)
    painter = QPainter(pix); QSvgRenderer(QByteArray(svg.encode())).render(painter); painter.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


def button(text="", name=None, primary=False, callback=None, quiet=False):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setObjectName("primary" if primary else "quiet" if quiet else "button")
    if name: b.setIcon(icon(name, "#ffffff" if primary else "#737780")); b.setIconSize(QSize(18, 18))
    if callback: b.clicked.connect(callback)
    return b


def label(text, name="", wrap=False):
    w = QLabel(text); w.setObjectName(name); w.setWordWrap(wrap)
    w.setTextFormat(Qt.PlainText)
    return w


def row(*widgets, margins=0, spacing=8):
    w = QFrame(); layout = QHBoxLayout(w); layout.setContentsMargins(margins, margins, margins, margins); layout.setSpacing(spacing)
    for item in widgets:
        if item is None: layout.addStretch()
        else: layout.addWidget(item)
    return w


LIGHT = """
QDialog { background: #ffffff; }
QMenu { background: #ffffff; color: #25262b; border: 1px solid #dedfe5; }
QMenu::item { background: #ffffff; color: #25262b; padding: 7px 16px; }
QMenu::item:selected { background: #e5edfd; color: #245fc2; }
QMenu::separator { background: #e3e3e8; height: 1px; }
QWidget { color: #25262b; font-family: 'Noto Sans'; font-size: 13px; }
QFrame#window { background: #fff; border: 1px solid #cdd0d6; border-radius: 14px; }
QFrame#titlebar { background: #f5f5f7; border-top-left-radius: 14px; border-top-right-radius: 14px; border-bottom: 1px solid #e3e3e8; }
QFrame#sidebar { background: #f3f3f6; border-right: 1px solid #e5e5e9; }
QFrame#assistant { background: #fafafb; border-left: 1px solid #e9e9ed; }
QFrame#toolbar { border-bottom: 1px solid #ededf0; background: #fff; }
QFrame#card { background: #fff; border: 1px solid #e8e8ee; border-radius: 13px; }
QFrame#subtle { background: #f5f6f9; border: 1px solid #ededf2; border-radius: 12px; }
QFrame#composer { background: #fff; border: 1px solid #dedfe5; border-radius: 13px; }
QFrame#jobbar { background: #f8f8fa; border-top: 1px solid #e8e8ed; border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }
QLabel#brand { font-size: 18px; font-weight: 700; letter-spacing: -0.4px; }
QLabel#heading { font-size: 30px; font-weight: 700; letter-spacing: -1px; }
QLabel#subheading { font-size: 18px; font-weight: 600; letter-spacing: -0.3px; }
QLabel#muted { color: #85858f; font-size: 12px; }
QLabel#eyebrow { color: #8c8c96; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#blue { color: #3478ed; }
QLabel#context { color: #4c647f; background: #edf2fa; border-radius: 8px; padding: 9px 11px; font-size: 11px; }
QPushButton { min-height: 20px; padding: 7px 12px; border: 1px solid #dfdfe5; border-radius: 7px; background: #fff; }
QPushButton:hover { background: #f4f5f8; border-color: #c9cbd4; }
QPushButton:pressed { background: #e9edf5; }
QPushButton:disabled { color: #aaa; background: #f4f4f6; border-color: #eee; }
QPushButton#primary { color: #fff; background: #4785f5; border: 1px solid #3779ee; font-weight: 600; }
QPushButton#primary:hover { background: #3478ed; }
QPushButton#primary:disabled { background: #a6bfeb; border-color: #a6bfeb; }
QPushButton#quiet { border: none; background: transparent; padding: 6px 8px; }
QPushButton#quiet:hover { background: #e9eaf0; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 9px 12px; border-radius: 7px; }
QPushButton#nav:checked { background: #dedfe6; color: #222; }
QPushButton#nav:hover { background: #e7e7ed; }
QLineEdit, QComboBox { padding: 8px 10px; border: 1px solid #dedee5; background: #fff; border-radius: 7px; selection-background-color: #cddffe; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #80a9f0; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 14px; height: 14px; background: #fff; border: 1px solid #bfc4ce; border-radius: 4px; }
QCheckBox::indicator:checked { background: #4785f5; border-color: #3779ee; }
QCheckBox::indicator:disabled { background: #e8e9ef; border-color: #d9dbe1; }
QLineEdit#search { background: #e9e9ee; border: none; padding: 8px 10px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #dbe8ff; color: #222; }
QComboBox { combobox-popup: 0; }
QComboBox QAbstractItemView::item { background: #ffffff; color: #25262b; min-height: 28px; }
QComboBox QAbstractItemView::item:selected { background: #dbe8ff; color: #245fc2; }
QTreeWidget, QListWidget { border: none; outline: none; background: transparent; padding: 0; }
QHeaderView::section { background: #f3f4f7; color: #74747e; border: none; border-bottom: 1px solid #e1e3e9; padding: 9px 8px; text-align: left; font-size: 11px; }
QTreeWidget::item, QListWidget::item { min-height: 30px; padding: 3px 6px; border-radius: 6px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #e0e6f2; color: #262b35; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #e9ecf3; }
QTextEdit, QPlainTextEdit, QTextBrowser { border: 1px solid #e2e3e9; border-radius: 8px; padding: 10px; background: #fff; selection-background-color: #cddffe; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { border: none; background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #c9cbd3; min-height: 32px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: #e9e9ed; width: 1px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #f0f0f4; padding: 8px 18px; margin: 0 2px 8px 0; border-radius: 6px; color: #74747e; }
QTabBar::tab:selected { background: #e5edfd; color: #2e6bd4; }
QProgressBar { background: #e6eaf1; border: none; height: 5px; border-radius: 2px; }
QProgressBar::chunk { background: #4785f5; border-radius: 2px; }
QToolTip { background: #28282b; color: white; border: none; padding: 7px; }
QMenu#libraryMenu { background-color: #ffffff; color: #25262b; border-color: #dedfe5; }
QMenu#libraryMenu::item { background-color: #ffffff; color: #25262b; }
QMenu#libraryMenu::item:selected { background-color: #e5edfd; color: #245fc2; }
QMenu#libraryMenu::item:disabled { color: #85858f; }
QMenu#libraryMenu::separator { background-color: #e3e3e8; }
"""

DARK = """
QDialog { background: transparent; border: none; }
QFrame#settingsShell { background: #262626; color: #f5f5f5; border: 1px solid #565656; border-radius: 20px; }
QWidget { color: #efefef; font-family: 'Noto Sans'; font-size: 13px; }
QFrame#settingsGroup { background: #303030; border-radius: 17px; }
QLabel { background: transparent; }
QLabel#heading { font-size: 23px; font-weight: 600; }
QLabel#muted { color: #a7a7a7; font-size: 11px; }
QLineEdit, QComboBox, QSpinBox { color: #eee; background: #424242; border: 1px solid #555; border-radius: 7px; min-height: 20px; padding: 8px 10px; selection-background-color: #4785f5; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #4785f5; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #363636; color: #fff; selection-background-color: #4785f5; }
QPushButton { color: #eee; background: #424242; border: 1px solid #5b5b5b; border-radius: 8px; padding: 10px 14px; }
QPushButton:hover { background: #505050; }
QPushButton#preset { padding: 12px 7px; font-size: 12px; }
QPushButton#preset:checked { background: #354b70; border: 1px solid #76a3f5; color: #fff; }
QPushButton:disabled { color: #888; border-color: #484848; background: #333; }
QPushButton#primary { background: #4885f4; border: 1px solid #699cf9; font-size: 15px; font-weight: 600; padding: 13px; border-radius: 12px; }
QPushButton#primary:hover { background: #3678ec; }
QPushButton#primary:disabled { background: #365279; color: #abb7c9; border-color: #456082; }
QPushButton#quiet { background: transparent; border: none; padding: 5px; color: #aaa; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px; background: #585858; border: 1px solid #606060; }
QCheckBox::indicator:checked { background: #4785f5; border: 1px solid #76a3f5; }
"""

ASSETS = Path(__file__).parent / "static"
CONTROL_ICONS = f'''QComboBox::down-arrow {{ image: url("{(ASSETS / 'chevron.svg').as_posix()}"); width: 12px; height: 12px; }}
QCheckBox::indicator:checked {{ image: url("{(ASSETS / 'check.svg').as_posix()}"); }}'''
LIGHT += CONTROL_ICONS
DARK += CONTROL_ICONS

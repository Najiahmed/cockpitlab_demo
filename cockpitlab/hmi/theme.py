"""Thème graphique propre au projet (aucun élément repris d'une marque existante)."""
from PySide6.QtGui import QColor, QFont

BG = "#05070A"
PANEL = "#0D131C"
CARD = "#111823"
BORDER = "#1D2735"
TEXT = "#E6EDF5"
MUTED = "#7C8899"
ACCENT = "#3DD6C6"
ACCENT_DIM = "#1F6F68"
GREEN = "#4ADE80"
BLUE = "#60A5FA"
ORANGE = "#FBBF24"
RED = "#F87171"

FONT_FAMILY = "Segoe UI"

LEVEL_COLORS = {"info": BLUE, "warning": ORANGE, "critical": RED}


def color(hex_code: str, alpha: int = 255) -> QColor:
    c = QColor(hex_code)
    c.setAlpha(alpha)
    return c


def font(pixel_size: int, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(pixel_size)
    f.setBold(bold)
    return f


STYLESHEET = f"""
QMainWindow, QWidget#dashboard {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-family: "{FONT_FAMILY}"; font-size: 13px; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#screen {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 22px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#big {{ font-size: 26px; font-weight: 600; }}
QPushButton {{
    background: #18212E; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px 12px; min-height: 22px;
}}
QPushButton:hover {{ border-color: {ACCENT_DIM}; }}
QPushButton:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QPushButton#round {{ border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; font-size: 16px; padding: 0; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QDockWidget {{ color: {MUTED}; }}
QDockWidget::title {{ background: {PANEL}; padding: 6px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {PANEL}; }}
QTabBar::tab {{ background: {BG}; padding: 7px 16px; border: 1px solid {BORDER}; border-bottom: none;
               border-top-left-radius: 8px; border-top-right-radius: 8px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; }}
QTableWidget {{ background: {BG}; gridline-color: {BORDER}; font-family: Consolas, monospace; font-size: 12px; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; padding: 4px; }}
QProgressBar {{ background: #1A2230; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 6px; background: #1A2230; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QComboBox {{ background: #18212E; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px 8px; }}
"""

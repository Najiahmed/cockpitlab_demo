"""Lance CockpitLab.

    python main.py                  # bus CAN virtuel intégré
    python main.py --bus python-can # bus virtuel python-can
"""
import argparse
import sys

from PySide6.QtWidgets import QApplication

from cockpitlab.app.runtime import CockpitRuntime
from cockpitlab.hmi import theme
from cockpitlab.hmi.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Cockpit Android Automotive simulé")
    parser.add_argument("--bus", choices=["memory", "python-can"], default="memory")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow(CockpitRuntime(backend=args.bus))
    window.resize(1600, 950)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

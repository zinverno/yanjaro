import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .api import private_logging
from .controller import Controller
from .player import Player


def main():
    private_logging()
    # Unhandled third-party exceptions may contain tokens or signed URLs.
    sys.excepthook = lambda *_: print("Внутренняя ошибка клиента; подробности скрыты для защиты данных.", file=sys.stderr)
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Yanjaro Music")
    controller = Controller(Player())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"music": controller})
    engine.load(Path(__file__).with_name("Main.qml"))
    if not engine.rootObjects():
        controller.close()
        return 1
    try:
        return app.exec()
    finally:
        controller.close()
        del engine


if __name__ == "__main__":
    sys.exit(main())

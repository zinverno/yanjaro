import sys
import argparse
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .api import private_logging
from .controller import PlaybackController
from .player import Player
from .desktop import Instance
from .storage import SecretStore


def main():
    parser = argparse.ArgumentParser(description="Yanjaro Music — неофициальный клиент Яндекс Музыки")
    parser.add_argument("--capture-ui", metavar="DIRECTORY", help="сохранить три экрана после входа и запуска музыки")
    options = parser.parse_args()
    private_logging()
    # Unhandled third-party exceptions may contain tokens or signed URLs.
    sys.excepthook = lambda *_: print("Внутренняя ошибка клиента; подробности скрыты для защиты данных.", file=sys.stderr)
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("yanjaro")
    app.setApplicationDisplayName("Yanjaro Music")
    app.setDesktopFileName("yanjaro")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icons") / "yanjaro.svg")))
    instance = Instance()
    try:
        if not instance.acquire():
            return 0
    except RuntimeError:
        print("Не удалось запустить единственный экземпляр Yanjaro. Проверьте доступ к каталогу сеанса.", file=sys.stderr)
        return 1
    controller = PlaybackController(Player(), store=SecretStore())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"music": controller})
    engine.load(Path(__file__).with_name("Main.qml"))
    if not engine.rootObjects():
        controller.close()
        instance.close()
        return 1
    window = engine.rootObjects()[0]
    def activate():
        window.showNormal()
        window.raise_()
        window.requestActivate()
    instance.activated.connect(activate)
    from .mpris import Mpris
    mpris = Mpris(controller, activate, app.quit)
    if options.capture_ui:
        from .capture import Capture
        capture = Capture(controller, window, options.capture_ui)
    controller.restore_account()
    try:
        return app.exec()
    finally:
        mpris.close()
        controller.close()
        instance.close()
        del engine


if __name__ == "__main__":
    sys.exit(main())

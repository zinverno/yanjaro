import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QTimer, QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from yanjaro.api import Page, Stream, Track
from yanjaro.controller import Controller
from yanjaro.player import Player


QQuickStyle.setStyle("Fusion")
APP = QGuiApplication.instance() or QGuiApplication([])


def until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for a desktop condition")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.player = Player(audio_output="null")
        self.assertTrue(self.player.state["ready"], self.player.error)

    def tearDown(self):
        self.player.close()

    def test_real_libmpv_play_pause_seek_resume_and_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 16000 * 65)
            failures, ended = [], []
            self.player.failed.connect(failures.append)
            self.player.ended.connect(lambda: ended.append(True))
            self.player.play(Stream(Track("test", "Synthetic test", "", 65, True), str(path)))
            until(lambda: self.player.state["position"] > 0.2)
            self.player.toggle_pause()
            until(lambda: self.player.state["paused"])
            paused_at = self.player.state["position"]
            until(lambda: self.player.state["seekable"])
            self.player.seek(63.7)
            until(lambda: self.player.state["position"] > 63.5)
            self.assertGreater(self.player.state["position"], paused_at)
            self.assertTrue(self.player.state["paused"])
            self.player.toggle_pause()
            until(lambda: bool(ended))
            self.assertFalse(failures, failures)

    def test_qml_load_and_worker_does_not_block_gui(self):
        worker_ids = []
        release = threading.Event()
        api = Mock()

        def likes(page):
            worker_ids.append(threading.get_ident())
            release.wait(2)
            return Page([])

        api.likes.side_effect = likes
        controller = Controller(self.player, api)
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"music": controller})
        engine.load(Path(__file__).parents[1] / "yanjaro/Main.qml")
        self.assertTrue(engine.rootObjects())
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        try:
            controller._state["signedIn"] = True
            controller.show("likes")
            until(lambda: len(ticks) >= 5)
            self.assertTrue(controller.state["busy"])
            self.assertNotEqual(worker_ids[0], threading.get_ident())
            release.set()
            until(lambda: not controller.state["busy"])
            self.assertEqual(controller.state["rows"], [])
        finally:
            timer.stop()
            release.set()
            engine.rootObjects()[0].close()
            controller.close()
            del engine

    def test_preview_sized_audio_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 16000 * 2)
            failures = []
            self.player.failed.connect(failures.append)
            self.player.play(Stream(Track("test", "Synthetic", "", 180, True), str(path)))
            until(lambda: bool(failures))
            self.assertIn("короче", failures[0])
            until(lambda: not self.player.engine.path)
            self.assertFalse(self.player.state["loaded"])

    def test_seek_slider_releases_user_chosen_position(self):
        controller = Controller(self.player, Mock())
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"music": controller})
        engine.load(Path(__file__).parents[1] / "yanjaro/Main.qml")
        window = engine.rootObjects()[0]
        try:
            APP.processEvents()
            self.player.state.update(loaded=True, seekable=True, duration=100, position=10)
            self.player.seek = Mock()
            controller.changed.emit()
            QTest.qWait(50)
            slider = window.findChild(QObject, "seekSlider")
            start = slider.mapToScene(QPointF(slider.width() * 0.1, slider.height() / 2)).toPoint()
            end = slider.mapToScene(QPointF(slider.width() * 0.8, slider.height() / 2)).toPoint()
            QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
            QTest.mouseMove(window, end, 50)
            QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
            APP.processEvents()
            self.player.seek.assert_called_once()
            self.assertGreater(self.player.seek.call_args.args[0], 60)
        finally:
            window.close()
            controller.close()
            del engine


if __name__ == "__main__":
    unittest.main()

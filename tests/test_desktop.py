import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_real_volume_and_mute(self):
        self.player.set_volume(23)
        until(lambda: self.player.state["volume"] == 23)
        self.player.toggle_mute()
        until(lambda: self.player.state["muted"])
        self.player.toggle_mute()
        until(lambda: not self.player.state["muted"])

    def test_instance_never_removes_a_live_owner_socket(self):
        from yanjaro.desktop import Instance
        with patch('yanjaro.desktop.QLockFile') as locks, patch('yanjaro.desktop.QLocalServer') as servers, patch('yanjaro.desktop.QLocalSocket') as sockets:
            locks.return_value.tryLock.return_value = False
            sockets.return_value.waitForConnected.return_value = True
            instance = Instance('/tmp')
            self.assertFalse(instance.acquire())
            servers.removeServer.assert_not_called()
            servers.return_value.listen.assert_not_called()
            sockets.return_value.connectToServer.assert_called_once_with('/tmp/yanjaro.socket')
            locks.return_value.tryLock.return_value = True
            servers.return_value.listen.return_value = True
            self.assertTrue(instance.acquire())
            servers.removeServer.assert_called_once_with('/tmp/yanjaro.socket')
            instance.close()
            locks.return_value.unlock.assert_called_once()

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
            self.assertEqual(controller.content["rows"], [])
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

    def test_selection_keyboard_and_scroll_do_not_restart_playback(self):
        controller = Controller(self.player, Mock())
        controller._state["signedIn"] = True
        rows = [Track(str(i), "Длинное название " * 12, "Исполнитель", 180, True).row() for i in range(500)]
        controller.pages["likes"].update(rows=rows, total=500, status="ready")
        controller.pages["stations"].update(rows=[], status="ready")
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"music": controller})
        engine.load(Path(__file__).parents[1] / "yanjaro/Main.qml")
        window = engine.rootObjects()[0]
        try:
            window.resize(1024, 700)
            QTest.qWait(100)
            controller.play = Mock()
            controller.pause = Mock()
            listing = window.findChild(QObject, "tracksList")
            point = listing.mapToScene(QPointF(140, 30)).toPoint()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            self.assertEqual(listing.property("currentIndex"), 0)
            controller.play.assert_not_called()
            QTest.mouseDClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            controller.play.assert_called_once_with("0")
            controller.play.reset_mock()
            listing.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            controller.play.assert_called_once_with("0")
            self.player.state.update(loaded=True, paused=False)
            controller.changed.emit()
            search = window.findChild(QObject, "searchField")
            search.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_A)
            QTest.keyClick(window, Qt.Key.Key_Space)
            self.assertEqual(search.property("text"), "a ")
            controller.pause.assert_not_called()
            listing.setProperty("contentY", 900)
            controller.save_scroll(900)
            controller.show("stations")
            QTest.qWait(30)
            controller.show("likes")
            QTest.qWait(50)
            self.assertAlmostEqual(listing.property("contentY"), 900, delta=1)
            self.player.changed.emit()
            APP.processEvents()
            self.assertAlmostEqual(listing.property("contentY"), 900, delta=1)
            delegates = [o for o in window.findChildren(QObject) if o.objectName().startswith("rowPlay")]
            self.assertLess(len(delegates), 70)  # A 500-row model stays virtualized.
        finally:
            window.close()
            controller.close()
            del engine


if __name__ == "__main__":
    unittest.main()

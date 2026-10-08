#!/usr/bin/env python3
"""Installed launcher smoke, only for an empty disposable container account.

Real Qt/mpv/IPC and a test session bus; no sound, account or desktop shell.
Only the audio sink and automatic window-close are supplied by the harness.
"""
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

assert os.environ.get('YANJARO_DISPOSABLE_CONTAINER') == '1'
assert Path('/.dockerenv').is_file()
assert os.getuid() != 0
assert not any(Path(p).exists() for p in ('/work/src', '/work/candidate', '/work/previous'))
assert not any(os.environ.get(k) for k in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'QML_IMPORT_PATH', 'QT_PLUGIN_PATH'))
sys.path.insert(0, '/usr/lib/yanjaro')
from PySide6.QtCore import QTimer, qVersion
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
import yanjaro
import yandex_music
from yanjaro.player import Player

assert Path(yanjaro.__file__).parent == Path('/usr/lib/yanjaro/yanjaro')
assert Path(yandex_music.__file__).parent == Path('/usr/lib/yanjaro/yandex_music')
load = QQmlApplicationEngine.load
seen = []
def checked_load(engine, source):
    assert str(source) == '/usr/lib/yanjaro/yanjaro/Main.qml'
    load(engine, source)
    assert engine.rootObjects()
    assert not QIcon('/usr/share/icons/hicolor/scalable/apps/yanjaro.svg').isNull()
    window = engine.rootObjects()[0]
    controller = window.property('music')
    assert controller.player.state['ready']
    def close():
        seen.append(True)
        window.close()
    QTimer.singleShot(500, close)

sys.argv = ['/usr/bin/yanjaro']
with patch('yanjaro.__main__.Player', lambda: Player(audio_output='null')), patch.object(QQmlApplicationEngine, 'load', checked_load):
    try:
        runpy.run_path('/usr/bin/yanjaro', run_name='__main__')
    except SystemExit as result:
        assert result.code == 0
assert seen
print('PASS installed launcher/QML/icons/libmpv/close; Qt', qVersion(), '; ao=null, no account')

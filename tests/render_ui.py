"""Credential-free layout evidence. Every capture is visibly marked SYNTHETIC."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from unittest.mock import Mock
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtTest import QTest
from test_desktop import APP
from test_wave import StubPlayer
from yanjaro.api import Track
from yanjaro.controller import Controller

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
player = StubPlayer()
c = Controller(player, Mock())
c._state.update(signedIn=True, currentId='2', current='Тестовая композиция', artist='Тестовый исполнитель', source='Мне нравится')
player.state.update(loaded=True, paused=False, position=68, duration=213)
rows = [Track(str(i), 'Тестовая композиция' + (' с очень длинным названием' * 6 if i == 3 else f' {i + 1}'),
              'Тестовый исполнитель', 213, True).row() for i in range(70)]
c.pages['likes'].update(rows=rows, total=70, status='ready', ids=tuple(str(i) for i in range(70)))
c.pages['search'].update(rows=rows[:5], total=5, status='ready')
c.query = 'Тестовая композиция'
c.pages['stations'].update(rows=[dict(id=str(i), title=name, detail='Радиостанция', kind='station', available=True)
    for i, name in enumerate(['Тестовая станция A', 'Тестовая станция B', 'Тестовая станция C', 'Тестовая станция D', 'Тестовая станция E', 'Тестовая станция F'])], status='ready')
engine = QQmlApplicationEngine()
engine.setInitialProperties({'music': c})
engine.load(Path(__file__).parents[1] / 'yanjaro/Main.qml')
assert engine.rootObjects()
window = engine.rootObjects()[0]
component = QQmlComponent(engine)
component.setData(b'''import QtQuick
Rectangle { width: 540; height: 24; color: "#c3d681"; z: 1000
Text { anchors.centerIn: parent; text: "SYNTHETIC UI TEST - NO ACCOUNT DATA"; color: "#20271a"; font.pixelSize: 12 } }
''', '')
banner = component.create()
banner.setParentItem(window.contentItem())
scale = os.environ.get('QT_SCALE_FACTOR', '1')
try:
    sizes = [(1024, 700), (1366, 768), (1920, 1080)]
    if float(scale) > 1:
        sizes += [(round(w / float(scale)), round(h / float(scale))) for w, h in sizes]
    for width, height in sizes:
        window.resize(width, height)
        for view in ('likes', 'search', 'stations'):
            c.show(view)
            QTest.qWait(80)
            for name in ('pauseButton', 'nextButton', 'muteButton', 'volumeSlider', 'queueButton', 'searchField'):
                item = window.findChild(QObject, name)
                assert item and item.width() > 20, name
                position = item.mapToScene(QPointF(0, 0))
                assert position.x() >= 0 and position.y() >= 0, name
                assert position.x() + item.width() <= width + 1, (name, width)
                assert position.y() + item.height() <= height + 1, (name, height)
            capture = window.grabWindow()
            assert not capture.isNull()
            assert capture.save(str(out / f'{view}-{width}x{height}-{scale}.png'))
    print(f'PASS: {len(sizes)} logical/physical size cases and three views at scale {scale}; primary controls in bounds')
finally:
    window.close()
    c.close()
    del engine

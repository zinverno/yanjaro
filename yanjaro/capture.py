"""Explicit --capture-ui session; no captures before login or during login codes."""
from pathlib import Path
import json
from PySide6.QtCore import QObject, QTimer


class Capture(QObject):
    def __init__(self, controller, window, directory):
        super().__init__(window)
        self.controller = controller
        self.window = window
        self.directory = Path(directory).expanduser().resolve()
        self.saved = set()
        self.max_batches_received = self.max_batches_played = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self._capture)
        self.timer.start()

    def _capture(self):
        state = self.controller.state
        view = state['view']
        if view == 'search':
            view = 'search' if state['searchType'] in ('all', 'track') else 'search-' + state['searchType']
        elif ':' in view:
            view = view.split(':')[0]
        if state['signedIn'] and not state['code']:
            self.max_batches_received = max(self.max_batches_received, self.controller.wave_batches_received)
            self.max_batches_played = max(self.max_batches_played, len(self.controller.wave_played_batches))
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / 'acceptance.json').write_text(json.dumps({
                'wave_batches_received_max': self.max_batches_received,
                'wave_distinct_batches_played_max': self.max_batches_played,
                'screens_saved': sorted(self.saved),
                'evidence': 'local capture session; contains no track IDs, account IDs, tokens or URLs',
            }, indent=2) + '\n')
        if (view in self.saved or view not in {'likes', 'search', 'stations', 'search-artist', 'search-album', 'artist', 'album', 'experiment'}
                or not state['signedIn'] or state['code'] or not state['loaded']
                or state['pageStatus'] != 'ready' or not self.controller.content['rows']):
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        image = self.window.grabWindow()
        if not image.isNull() and image.save(str(self.directory / f'{view}.png')):
            self.saved.add(view)

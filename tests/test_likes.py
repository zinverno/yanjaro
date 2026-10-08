"""Synthetic likes contract checks. Never mutate a real account."""
import unittest
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from yandex_music import Client
from yandex_music.exceptions import NetworkError

from yanjaro.api import ApiError, MusicApi, Page, Track
from yanjaro.controller import PlaybackController
from test_desktop import APP, until, visual_items
from test_wave import StubPlayer


def full_list(ids, page=0):
    return Page([Track(item.split(':')[0], 'Synthetic', 'Artist', 120, True,
                       album_id=item.split(':')[1] if ':' in item else '').row()
                 for item in ids[page * 50:(page + 1) * 50]],
                more=len(ids) > (page + 1) * 50, total=len(ids), ids=tuple(ids))


class MusicApiLikesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.api = MusicApi(self.client)
        self.api.authenticated = True
        self.api._likes = ['1:11', '2:22']

    def test_preserves_full_id_on_remove_and_add(self):
        self.client.users_likes_tracks_remove.return_value = True
        self.assertEqual(self.api.set_track_liked('1', False), ('2:22',))
        self.client.users_likes_tracks_remove.assert_called_once_with('1:11')
        self.client.users_likes_tracks_add.return_value = True
        self.assertEqual(self.api.set_track_liked('3', True, '33'), ('3:33', '2:22'))
        self.client.users_likes_tracks_add.assert_called_once_with('3:33')
        self.api.set_track_liked('3', True, '33')
        self.client.users_likes_tracks_add.assert_called_once()

    def test_rejected_mutation_does_not_change_cache(self):
        self.client.users_likes_tracks_remove.return_value = False
        with self.assertRaisesRegex(ApiError, 'не подтвердил'):
            self.api.set_track_liked('1', False, '11')
        self.assertEqual(self.api._likes, ['1:11', '2:22'])
        self.client.users_likes_tracks_add.return_value = False
        with self.assertRaisesRegex(ApiError, 'не подтвердил'):
            self.api.set_track_liked('3', True, '33')
        self.assertEqual(self.api._likes, ['1:11', '2:22'])
        for invalid in ('../no', '1:bad', '1:', ':11', '1:11:22', '١'):
            with self.subTest(id=invalid), self.assertRaisesRegex(ApiError, 'идентификатор'):
                self.api.set_track_liked(invalid, True)


class ControllerLikesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, XDG_CONFIG_HOME=directory.name, XDG_STATE_HOME=directory.name)
        env.start(); self.addCleanup(env.stop)
        self.ids = ['1:11', '2:22']
        self.api = Mock()
        self.api.likes.side_effect = lambda page=0: full_list(self.ids, page)
        self.player = StubPlayer()
        self.controller = PlaybackController(self.player, self.api)
        self.controller._state['signedIn'] = True
        self.controller.show('likes')
        until(lambda: self.controller.likes_ready and self.controller.state['pageStatus'] == 'ready')

    def tearDown(self):
        self.controller.close()

    def test_liked_state_updates_across_pages_and_keeps_queue(self):
        def change(track_id, liked, album_id):
            if liked:
                self.ids.insert(0, track_id + ':' + album_id)
            else:
                self.ids[:] = [value for value in self.ids if value.split(':')[0] != track_id]
            return tuple(self.ids)
        self.api.set_track_liked.side_effect = change
        self.controller.queue = [Track('1', 'Playing', 'Artist', 120, True).row()]
        self.controller.queue_index = 0
        self.controller._state['currentId'] = '1'
        self.controller.toggle_like('1', '11')
        self.assertFalse(self.controller.likesState['liked'].get('1'))
        self.controller.toggle_like('1', '11')  # While pending: no second request.
        until(lambda: not self.controller.like_pending and self.controller.state['pageStatus'] == 'ready')
        self.assertEqual(self.api.set_track_liked.call_count, 1)
        self.assertEqual(self.controller.state['total'], 1)
        self.assertEqual(self.controller.queue[0]['id'], '1')
        self.assertEqual(self.controller.state['currentId'], '1')
        self.assertFalse(self.controller.likesState['liked'].get('1'))
        self.controller.toggle_like('3', '33')
        until(lambda: not self.controller.like_pending and self.controller.state['pageStatus'] == 'ready')
        self.assertTrue(self.controller.likesState['liked'].get('3'))
        self.assertEqual(self.controller.state['total'], 2)

    def test_failure_rolls_back_optimistic_state(self):
        self.api.set_track_liked.side_effect = ApiError('Сервис недоступен.')
        self.controller.toggle_like('1', '11')
        until(lambda: not self.controller.like_pending)
        self.assertTrue(self.controller.likesState['liked'].get('1'))
        self.assertIn('Сервис недоступен', self.controller.state['likeError'])
        self.controller.clear_like_error()
        self.assertFalse(self.controller.state['likeError'])

    def test_logout_clears_account_likes(self):
        self.assertTrue(self.controller.likesState['liked'].get('1'))
        self.controller.logout()
        self.assertFalse(self.controller.likesState['ready'])
        self.assertEqual(self.controller.likesState['liked'], {})


    def test_full_collection_pagination_after_remove_then_add_and_empty(self):
        self.ids[:] = [f'{i}:{i + 1000}' for i in range(1, 112)]
        self.controller._load_page('likes', 0)
        until(lambda: self.controller.state['total'] == 111)
        self.assertEqual(len(self.controller.liked_ids), 111)
        self.controller.more()
        until(lambda: len(self.controller.content['rows']) == 100)
        def change(track, liked, album):
            if liked: self.ids.insert(0, f'{track}:{album}')
            else: self.ids[:] = [item for item in self.ids if item.split(':')[0] != track]
            return tuple(self.ids)
        self.api.set_track_liked.side_effect = change
        for track, album, expected in [('2', '1002', 110), ('999', '1999', 111)]:
            self.controller.toggle_like(track, album)
            until(lambda: not self.controller.like_pending and self.controller.state['pageStatus'] == 'ready')
            self.assertEqual(self.controller.state['total'], expected)
            self.assertEqual(len(self.controller.content['rows']), 50)
            while self.controller.state['more']:
                self.controller.more()
                until(lambda: self.controller.state['pageStatus'] == 'ready')
            actual = [row['id'] for row in self.controller.content['rows']]
            self.assertEqual(actual, [item.split(':')[0] for item in self.ids])
            self.assertEqual(len(set(actual)), expected)
        self.ids.clear()
        self.controller._load_page('likes', 0)
        until(lambda: self.controller.state['pageStatus'] == 'ready')
        self.assertEqual(self.controller.liked_ids, set())
        self.assertEqual(self.controller.pages['likes']['ids'], ())
        self.assertEqual(self.controller.state['total'], 0)

    def test_refresh_failure_does_not_undo_confirmed_mutation(self):
        self.api.set_track_liked.return_value = ('2:22',)
        self.api.likes.side_effect = ApiError('Сервис недоступен.')
        self.controller.toggle_like('1', '11')
        until(lambda: self.controller.state['pageStatus'] == 'error')
        self.assertNotIn('1', self.controller.liked_ids)
        self.assertEqual(self.controller.state['total'], 1)
        self.api.likes.side_effect = lambda page=0: full_list(['2:22'], page)
        self.controller._load_page('likes', 0)
        until(lambda: self.controller.state['pageStatus'] == 'ready')
        self.assertEqual([r['id'] for r in self.controller.content['rows']], ['2'])

    def test_logout_cancels_queued_mutation_and_discards_running_reply(self):
        entered, release = threading.Event(), threading.Event()
        def change(*args):
            entered.set(); release.wait(2)
            return ('2:22',)
        self.api.set_track_liked.side_effect = change
        try:
            self.controller.toggle_like('1', '11')
            until(entered.is_set)
            self.controller.toggle_like('3', '33')  # Queued behind the first request.
            self.controller.logout()
            release.set()
            until(lambda: not self.controller.state['authBusy'])
            self.api.set_track_liked.assert_called_once_with('1', False, '11')
            self.assertEqual(self.controller.likesState, dict(ready=False, liked={}, pending={}))
            self.assertFalse(self.controller.state['likeError'])
            self.assertEqual(self.controller.pages['likes']['rows'], [])
        finally:
            release.set()

    def test_close_cancels_queued_mutation(self):
        release = threading.Event()
        self.controller.pool.submit(lambda: release.wait(2))
        self.controller.toggle_like('1', '11')
        timer = threading.Timer(.05, release.set)
        timer.start()
        try:
            self.controller.close()
            self.api.set_track_liked.assert_not_called()
        finally:
            release.set(); timer.join()

    def test_pending_overlay_survives_page_response_and_other_like_failure(self):
        entered, release = threading.Event(), threading.Event()
        def change(track, *_):
            if track == '1':
                entered.set(); release.wait(2)
                raise ApiError('Сервис недоступен.')
            self.ids.insert(0, '3:33')
            return tuple(self.ids)
        self.api.set_track_liked.side_effect = change
        try:
            self.controller.toggle_like('1', '11'); until(entered.is_set)
            self.controller.toggle_like('3', '33')
            self.controller._sync_likes(self.ids)
            self.assertNotIn('1', self.controller.liked_ids)
            self.assertIn('3', self.controller.liked_ids)
            release.set()
            until(lambda: not self.controller.like_pending and self.controller.state['pageStatus'] == 'ready')
            self.assertEqual(self.controller.liked_ids, {'1', '2', '3'})
        finally:
            release.set()

    def test_qml_heart_menu_and_row_clicks_and_shared_state(self):
        c = self.controller
        rows = [Track(str(i), 'Длинное название ' * 10, 'Исполнитель', 180, True,
                      str(i * 11), '', ({'id': '9', 'title': 'Исполнитель'},), 'Альбом').row()
                for i in (1, 2)]
        c.pages['likes'].update(rows=rows, status='ready')
        c.queue, c.queue_index, c.selected_row = rows.copy(), 0, rows[0]
        c._state.update(currentId='1', current=rows[0]['title'], artist='Исполнитель', source='Мне нравится')
        self.player.state.update(loaded=True, paused=False)
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({'music': c})
        engine.load(Path(__file__).parents[1] / 'yanjaro/Main.qml')
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        entered, release = threading.Event(), threading.Event()
        def change(*_):
            entered.set(); release.wait(2)
            self.ids.remove('1:11')
            return tuple(self.ids)
        self.api.set_track_liked.side_effect = change
        c.play = Mock(); c.pause = Mock(); c.open_entity = Mock()
        def click(item, button=Qt.MouseButton.LeftButton):
            QTest.mouseClick(window, button, Qt.KeyboardModifier.NoModifier,
                            item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())
            APP.processEvents()
        try:
            window.resize(1024, 700); QTest.qWait(80)
            listing = window.findChild(QObject, 'tracksList')
            row = next(o for o in visual_items(listing) if o.objectName() == 'trackRow0')
            heart = row.findChild(QObject, 'likeButton')
            player = window.findChild(QObject, 'playerMetadata')
            player_heart = player.findChild(QObject, 'likeButton')
            self.assertTrue(heart.property('liked'))
            click(heart); until(entered.is_set)
            self.assertFalse(heart.property('liked'))
            self.assertFalse(player_heart.property('liked'))
            self.assertTrue(player_heart.property('pending'))
            self.assertFalse(player_heart.isEnabled())
            click(player_heart)
            c.play.assert_not_called(); c.pause.assert_not_called()
            release.set()
            until(lambda: not c.like_pending and c.state['pageStatus'] == 'ready')
            self.assertEqual(self.api.set_track_liked.call_count, 1)
            self.assertFalse(player_heart.property('liked'))
            self.assertEqual(player_heart.property('symbol'), 'heart')
            # A different page, including a duplicate occurrence of the same song.
            c.pages['search:track'].update(rows=rows + [rows[0]], status='ready')
            c.search_type = 'track'; c.pages['search'] = c.pages['search:track']
            c.show('search'); QTest.qWait(80)
            hearts = [o for o in visual_items(listing) if o.objectName() == 'likeButton' and o.property('key') == '1']
            self.assertGreaterEqual(len(hearts), 2)
            self.assertTrue(all(not o.property('liked') for o in hearts))
            row = next(o for o in visual_items(listing) if o.objectName() == 'trackRow0')
            menu_button = row.findChild(QObject, 'trackMenuButton')
            click(menu_button)
            menu = row.findChild(QObject, 'trackMenu')
            until(lambda: menu.property('opened'))
            c.play.assert_not_called()
            QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            until(lambda: c.open_entity.call_count == 1)
            c.open_entity.assert_called_once_with('album', '11')
            c.play.assert_not_called()
            # Keyboard heart activation must not trigger the global Space shortcut.
            c.toggle_like = Mock()
            heart = row.findChild(QObject, 'likeButton')
            heart.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Space)
            c.toggle_like.assert_called_once_with('1', '11')
            c.pause.assert_not_called(); c.play.assert_not_called()
            # Click title above the independent artist link; one launch.
            point = row.mapToScene(QPointF(140, 14)).toPoint()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            c.play.assert_called_once_with('1')
            click(window.findChild(QObject, 'queueButton'))
            until(lambda: window.findChild(QObject, 'queuePanel').property('opened'))
            click(window.findChild(QObject, 'queueButton'))
            until(lambda: not window.findChild(QObject, 'queuePanel').property('visible'))
            center = window.findChild(QObject, 'playerCenter')
            self.assertAlmostEqual(center.x() + center.width()/2, window.width()/2, delta=1)
            for item in (player_heart, window.findChild(QObject, 'queueButton')):
                pos = item.mapToScene(QPointF(0, 0))
                self.assertGreaterEqual(pos.x(), 0)
                self.assertLessEqual(pos.x() + item.width(), window.width())
            self.assertLessEqual(player_heart.mapToScene(QPointF(player_heart.width(), 0)).x(), center.x())
        finally:
            release.set(); window.close(); del engine


class SdkLikesTests(unittest.TestCase):
    def test_real_sdk_contract_and_no_retry_on_mutation_failure(self):
        request = Mock()
        client = Client(request=request)
        client.account_uid = '123'
        api = MusicApi(client); api.authenticated = True
        request.post.return_value = {'revision': 1}
        self.assertEqual(api.set_track_liked('1', True, '11'), ('1:11',))
        self.assertTrue(request.post.call_args.args[0].endswith('/users/123/likes/tracks/add-multiple'))
        self.assertEqual(request.post.call_args.args[1], {'track-ids': '1:11'})
        request.post.return_value = 'ok'  # Tracks require a revision, unlike some other SDK methods.
        with self.assertRaises(ApiError): api.set_track_liked('1', False)
        self.assertEqual(api._likes, ['1:11'])
        request.post.reset_mock(); request.post.side_effect = NetworkError('synthetic')
        with self.assertRaises(NetworkError): api.set_track_liked('1', False)
        request.post.assert_called_once()
        self.assertTrue(request.post.call_args.args[0].endswith('/users/123/likes/tracks/remove'))
        self.assertEqual(request.post.call_args.args[1], {'track-ids': '1:11'})
        self.assertEqual(api._likes, ['1:11'])


if __name__ == '__main__':
    unittest.main()

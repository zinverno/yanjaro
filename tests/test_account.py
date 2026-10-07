"""Fake store records only synthetic secrets; never access a user's keyring."""
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from yanjaro.api import ApiError, AccountRequest, InvalidAccount, Page
from yanjaro.controller import PlaybackController
from yanjaro.storage import SecretStore
from test_desktop import APP, until
from test_wave import StubPlayer


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, XDG_CONFIG_HOME=self.tmp.name, XDG_STATE_HOME=self.tmp.name)
        self.env.start()
        self.api, self.store = Mock(), Mock()
        self.api.client.token = 'synthetic-secret'
        self.api.login.return_value = 'test-account'
        self.api.likes.return_value = Page([])
        self.api.restore.return_value = 'test-account'
        self.store.read.return_value = 'synthetic-secret'
        self.c = PlaybackController(StubPlayer(), self.api, self.store)

    def tearDown(self):
        self.c.close(); self.env.stop(); self.tmp.cleanup()

    def test_login_save_restore_logout_and_no_autoplay(self):
        self.c.login(); until(lambda: not self.c.state['authBusy'])
        self.store.write.assert_called_once_with('synthetic-secret')
        self.assertTrue(self.c.saved)
        self.assertEqual(self.c.player.played, [])
        self.c.logout(); until(lambda: not self.c.state['authBusy'])
        self.store.delete.assert_called_once()
        self.c.restore_account()
        self.store.read.assert_not_called()  # Persisted explicit logout suppresses restore.
        from pathlib import Path
        self.assertNotIn('synthetic-secret', Path(self.tmp.name + '/yanjaro/settings.json').read_text())

    def test_restore_network_failure_keeps_secret_and_can_retry(self):
        self.api.restore.side_effect = ApiError('Сеть недоступна')
        self.c.restore_account(); until(lambda: not self.c.state['authBusy'])
        self.assertFalse(self.c.state['signedIn'])
        self.store.delete.assert_not_called()
        self.api.login.assert_not_called()
        self.api.restore.side_effect = None
        self.c.retry_storage(); until(lambda: not self.c.state['authBusy'])
        self.assertTrue(self.c.state['signedIn'])
        self.assertEqual(self.c.player.played, [])

    def test_store_failure_session_only_and_disabled_remember(self):
        self.store.write.side_effect = ApiError('Хранилище заблокировано')
        self.c.login(); until(lambda: not self.c.state['authBusy'])
        self.assertTrue(self.c.state['signedIn']); self.assertFalse(self.c.saved)
        self.assertEqual(self.c.storage_action, 'save')
        self.assertIn('только на этот сеанс', self.c.state['accountMessage'])
        self.c.logout(); until(lambda: not self.c.state['authBusy'])
        self.c.remember_account(False)
        self.store.write.reset_mock()
        self.c.login(); until(lambda: not self.c.state['authBusy'])
        self.store.write.assert_not_called()

    def test_restore_is_async_and_cancel_rejects_late_account(self):
        gate, started=threading.Event(),threading.Event()
        def read(**kwargs):
            started.set(); gate.wait(2); return 'synthetic-secret'
        self.store.read.side_effect=read
        try:
            self.c.restore_account(); until(started.is_set)
            self.assertTrue(self.c.state['authBusy'])
            self.c.cancel_login()
            gate.set(); until(lambda: self.api.logout.called)
            APP.processEvents()
            self.assertFalse(self.c.state['signedIn'])
        finally:
            gate.set()

    def test_401_is_distinct_from_403_and_locked_store_never_writes(self):
        request=AccountRequest(timeout=1)
        with self.assertRaises(InvalidAccount): request._handle_error_response(401,b'private')
        with self.assertRaises(ApiError) as error: request._handle_error_response(403,b'private')
        self.assertNotIsInstance(error.exception, InvalidAccount)
        with patch('yanjaro.storage.secretstorage.dbus_init') as connect, patch('yanjaro.storage.secretstorage.Collection') as collection:
            collection.return_value.is_locked.return_value=True
            store=SecretStore()
            with self.assertRaisesRegex(ApiError,'заблокировано'): store.read()
            collection.return_value.create_item.assert_not_called()
            collection.return_value.unlock.assert_not_called()
            connect.return_value.close.assert_called_once()

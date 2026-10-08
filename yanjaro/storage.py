"""XDG preferences contain no secrets; credentials use only Secret Service."""
from contextlib import closing
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import tempfile

import secretstorage

from .api import ApiError


def data_path(kind, name):
    defaults = {'config': '.config', 'state': '.local/state', 'cache': '.cache'}
    base = Path(os.environ.get(f'XDG_{kind.upper()}_HOME', str(Path.home() / defaults[kind])))
    return base / 'yanjaro' / name


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def account_path(uid, filename):
    return data_path('state', hashlib.sha256(str(uid).encode()).hexdigest()[:32]) / filename


class SecretStore:
    # Only this exact application item is touched, never the user's other keys.
    attributes = {'application': 'yanjaro', 'purpose': 'active-account-v1'}

    def __init__(self):
        self.connection = None

    def abort(self):
        if self.connection:
            self.connection.close()

    def _operate(self, operation, secret=None, unlock=False):
        try:
            with closing(secretstorage.dbus_init()) as bus:
                self.connection = bus
                # SecretStorage uses this connection for all calls; avoid unbounded waits.
                bus.send_and_get_reply = partial(bus.send_and_get_reply, timeout=8)
                bus.recv_until_filtered = partial(bus.recv_until_filtered, timeout=20)
                collection = secretstorage.Collection(bus)  # No temporary/session fallback or implicit collection creation.
                if collection.is_locked():
                    if not unlock:
                        raise secretstorage.LockedException('locked')
                    if collection.unlock(timeout=20):
                        raise secretstorage.PromptDismissedException('cancelled')
                collection.ensure_not_locked()
                items = list(collection.search_items(self.attributes))
                if operation == 'read':
                    return items[0].get_secret().decode() if items else None
                if operation == 'write':
                    collection.create_item('Yanjaro — аккаунт Яндекс Музыки', self.attributes,
                                           secret.encode(), replace=True)
                elif operation == 'delete':
                    for item in items:
                        item.delete()
        except secretstorage.LockedException:
            raise ApiError('Хранилище аккаунта заблокировано. Нажмите «Повторить доступ» или войдите только на этот сеанс.') from None
        except secretstorage.PromptDismissedException:
            raise ApiError('Разблокировка хранилища отменена. Аккаунт не сохранён; можно повторить доступ.') from None
        except secretstorage.ItemNotFoundException:
            raise ApiError('В Secret Service нет постоянного хранилища по умолчанию. Настройте его в системе или войдите на этот сеанс.') from None
        except Exception:
            raise ApiError('Secret Service недоступен или не ответил. Повторите доступ либо войдите только на этот сеанс.') from None
        finally:
            self.connection = None

    def read(self, unlock=False):
        return self._operate('read', unlock=unlock)

    def write(self, secret):
        self._operate('write', secret, unlock=True)

    def delete(self):
        self._operate('delete', unlock=True)

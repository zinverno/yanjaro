"""Desktop identity, one local player per user, and public artwork cache."""
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache
from PySide6.QtQml import QQmlNetworkAccessManagerFactory
from .storage import data_path


class ArtworkNetwork(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        manager = QNetworkAccessManager(parent)
        cache = QNetworkDiskCache(manager)
        cache.setCacheDirectory(str(data_path('cache', 'artwork')))
        cache.setMaximumCacheSize(32 * 1024 * 1024)
        manager.setCache(cache)
        return manager


class Instance(QObject):
    activated = Signal()

    def __init__(self, directory=None):
        super().__init__()
        runtime = directory or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        self.path = str(Path(runtime) / 'yanjaro.socket')
        self.lock = QLockFile(str(Path(runtime) / 'yanjaro.lock'))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._activate)
        self.primary = False

    def acquire(self):
        if not self.lock.tryLock(0):
            socket = QLocalSocket(self)
            socket.connectToServer(self.path)
            if socket.waitForConnected(300):
                socket.disconnectFromServer()
            return False
        # Holding the lock proves there is no live owner of this user's old socket.
        QLocalServer.removeServer(self.path)
        if not self.server.listen(self.path):
            self.lock.unlock()
            raise RuntimeError('Не удалось создать локальное соединение приложения.')
        self.primary = True
        return True

    def _activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
        self.activated.emit()

    def close(self):
        if self.primary:
            self.server.close()
            self.lock.unlock()
            self.primary = False

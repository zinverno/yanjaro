"""Desktop identity and one local player per user; no token persistence."""
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


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

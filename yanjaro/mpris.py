"""Typed MPRIS messages on the existing Qt event loop, using Jeepney transport.

PySide6 6.11 QDBusArgument maps Python numeric << overloads to uint16; use explicit
D-Bus signatures instead. Jeepney is already required by SecretStorage. No second
GUI/event loop and no external player process.
"""
import hashlib
from PySide6.QtCore import QObject, QSocketNotifier
from jeepney import DBusAddress, HeaderFields, MessageType, new_method_return, new_error, new_signal
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection, Proxy

SERVICE = 'org.mpris.MediaPlayer2.yanjaro'
PATH = '/org/mpris/MediaPlayer2'
ROOT = 'org.mpris.MediaPlayer2'
PLAYER = ROOT + '.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'
METHODS = {
    ROOT: {'Raise': '', 'Quit': ''},
    PLAYER: {**{name: '' for name in ('Play','Pause','PlayPause','Stop','Next','Previous')},
             'Seek': 'x', 'SetPosition': 'ox', 'OpenUri': 's'},
}
WRITABLE = {'LoopStatus', 'Shuffle', 'Volume', 'Rate'}


def track_path(id):
    return PATH + '/track_' + hashlib.sha256(id.encode()).hexdigest() if id else '/org/mpris/MediaPlayer2/TrackList/NoTrack'


class Mpris(QObject):
    def __init__(self, controller, raise_window, quit_app, connection=None):
        super().__init__()
        self.c, self.raise_window, self.quit_app = controller, raise_window, quit_app
        self.bus = connection
        self.notifier = None
        self.last = self.properties()[PLAYER]
        self.last.pop('Position')
        try:
            if not self.bus:
                self.bus = open_dbus_connection(auth_timeout=1)
                name, = Proxy(message_bus, self.bus, timeout=2).RequestName(SERVICE, 4)  # Do not queue a duplicate owner.
                if name != 1:
                    raise RuntimeError('name owned')
                self.notifier = QSocketNotifier(self.bus.sock.fileno(), QSocketNotifier.Type.Read, self)
                self.notifier.activated.connect(self.receive)
            controller._state['mprisStatus'] = 'MPRIS подключён к системному сеансу.'
            controller.changed.connect(self.update)
            controller.player.seeked.connect(self.seeked)
        except Exception:
            self.close()
            controller._state['mprisStatus'] = 'Сеансовая D-Bus недоступна. Оконное управление работает; MPRIS нужно проверить в пользовательском сеансе.'
        controller.changed.emit()

    def properties(self):
        s = self.c.state
        metadata = {}
        if s['currentId']:
            metadata = {'mpris:trackid': ('o', track_path(s['currentId'])),
                        'xesam:title': ('s', s['current']),
                        'xesam:artist': ('as', [s['artist']] if s['artist'] else [])}
            if s['duration']:
                metadata['mpris:length'] = ('x', int(s['duration'] * 1_000_000))
            if s['cover']:
                metadata['mpris:artUrl'] = ('s', s['cover'])
        status = {'playing': 'Playing', 'buffering': 'Playing', 'paused': 'Paused'}.get(s['playbackStatus'], 'Stopped')
        if s['loading'] and s['desiredPaused']:
            status = 'Paused'
        return {
            ROOT: {'CanQuit': ('b', True), 'CanRaise': ('b', True), 'HasTrackList': ('b', False),
                   'Identity': ('s', 'Yanjaro Music'), 'DesktopEntry': ('s', 'yanjaro'),
                   'SupportedUriSchemes': ('as', []), 'SupportedMimeTypes': ('as', [])},
            PLAYER: {'PlaybackStatus': ('s', status), 'LoopStatus': ('s', s['repeatMode']),
                     'Rate': ('d', 1.0), 'Shuffle': ('b', s['shuffle']), 'Metadata': ('a{sv}', metadata),
                     'Volume': ('d', 0.0 if s['muted'] else s['volume'] / 100),
                     'Position': ('x', int(s['position'] * 1_000_000)),
                     'MinimumRate': ('d', 1.0), 'MaximumRate': ('d', 1.0),
                     'CanGoNext': ('b', s['canNext']), 'CanGoPrevious': ('b', s['canPrevious']),
                     'CanPlay': ('b', bool(s['currentId']) and s['ready']),
                     'CanPause': ('b', s['canPause']), 'CanSeek': ('b', s['loaded'] and s['seekable']),
                     'CanControl': ('b', True)},
        }

    def introspect(self):
        parts = ['<node>']
        for interface, properties in self.properties().items():
            parts.append(f'<interface name="{interface}">')
            for name, signature in METHODS[interface].items():
                parts.append(f'<method name="{name}">')
                for index, type_ in enumerate(signature):
                    parts.append(f'<arg name="arg{index}" type="{type_}" direction="in"/>')
                parts.append('</method>')
            for name, (signature, _) in properties.items():
                access = 'readwrite' if interface == PLAYER and name in WRITABLE else 'read'
                parts.append(f'<property name="{name}" type="{signature}" access="{access}">')
                if name == 'Position':
                    parts.append('<annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>')
                parts.append('</property>')
            if interface == PLAYER:
                parts.append('<signal name="Seeked"><arg name="Position" type="x"/></signal>')
            parts.append('</interface>')
        parts.append('''<interface name="org.freedesktop.DBus.Properties">
          <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
          <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
          <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
          <signal name="PropertiesChanged"><arg type="s"/><arg type="a{sv}"/><arg type="as"/></signal>
        </interface><interface name="org.freedesktop.DBus.Introspectable"><method name="Introspect"><arg type="s" direction="out"/></method></interface></node>''')
        return ''.join(parts)

    def receive(self):
        try:
            while self.bus:
                message = self.bus.receive(timeout=0)
                if message.header.message_type == MessageType.method_call:
                    self.handle(message)
        except TimeoutError:
            pass
        except Exception:
            self.close()
            self.c._state['mprisStatus'] = 'Соединение MPRIS с D-Bus прервано. Перезапустите приложение после восстановления сеанса.'
            self.c.changed.emit()

    def handle(self, message):
        fields = message.header.fields
        interface, method = fields.get(HeaderFields.interface), fields.get(HeaderFields.member)
        signature = fields.get(HeaderFields.signature, '')
        args = message.body
        try:
            if fields.get(HeaderFields.path) != PATH:
                raise ValueError('UnknownObject')
            if interface == 'org.freedesktop.DBus.Introspectable' and method == 'Introspect' and not args:
                reply = new_method_return(message, 's', (self.introspect(),))
            elif interface == PROPERTIES:
                expected = {'Get':'ss', 'GetAll':'s', 'Set':'ssv'}.get(method)
                if signature != expected:
                    raise ValueError('InvalidArgs')
                properties = self.properties()
                if args[0] not in properties:
                    raise ValueError('UnknownInterface')
                if method == 'GetAll':
                    reply = new_method_return(message,'a{sv}',(properties[args[0]],))
                elif method == 'Get':
                    if args[1] not in properties[args[0]]:
                        raise ValueError('UnknownProperty')
                    reply = new_method_return(message,'v',(properties[args[0]][args[1]],))
                else:
                    self.set_property(*args)
                    reply = new_method_return(message)
            elif method in METHODS.get(interface, {}) and signature == METHODS[interface][method]:
                self.command(interface,method,args)
                reply = new_method_return(message)
            else:
                raise ValueError('UnknownMethod')
        except ValueError as exc:
            reply = new_error(message, 'org.freedesktop.DBus.Error.' + str(exc))
        self.bus.send(reply)

    def set_property(self, interface, name, value):
        if interface != PLAYER or name not in WRITABLE:
            raise ValueError('PropertyReadOnly')
        if value[0] != self.properties()[PLAYER][name][0]:
            raise ValueError('InvalidArgs')
        val = value[1]
        if name in ('Shuffle', 'LoopStatus') and not self.c.state['finiteQueue']:
            raise ValueError('NotSupported')
        if name == 'Shuffle':
            self.c.set_shuffle(val)
        elif name == 'LoopStatus':
            if val not in ('None','Playlist','Track'):
                raise ValueError('InvalidArgs')
            self.c.set_repeat(val)
        elif name == 'Volume':
            if self.c.state['muted']:
                self.c.mute()
            self.c.volume(max(0, min(val, 1)) * 100)
        elif val != 1.0:
            raise ValueError('NotSupported')

    def command(self, interface, method, args):
        if interface == ROOT:
            (self.raise_window if method == 'Raise' else self.quit_app)()
            return
        s = self.c.state
        commands = {'Play': (bool(s['currentId']), self.c.play_resume),
                    'Pause': (s['canPause'], lambda: self.c.set_paused(True)),
                    'PlayPause': (s['canPause'], self.c.pause), 'Stop': (True, self.c.stop),
                    'Next': (s['canNext'], self.c.next_track), 'Previous': (s['canPrevious'], self.c.previous_track)}
        if method in commands:
            enabled, call = commands[method]
            if enabled: call()
        elif method == 'Seek' and s['seekable'] and s['loaded']:
            target = s['position'] + args[0] / 1_000_000
            if target > s['duration']:
                self.c.next_track()
            else:
                self.c.seek(max(0, target))
        elif method == 'SetPosition' and s['seekable'] and s['loaded']:
            if args[0] == track_path(s['currentId']) and 0 <= args[1] <= s['duration'] * 1_000_000:
                self.c.seek(args[1] / 1_000_000)
        elif method == 'OpenUri':
            raise ValueError('NotSupported')

    def update(self):
        current = self.properties()[PLAYER]
        current.pop('Position')  # Position must not emit PropertiesChanged on playback ticks.
        changed = {k:v for k,v in current.items() if self.last.get(k) != v}
        self.last = current
        if changed and self.bus:
            self.bus.send(new_signal(DBusAddress(PATH, interface=PROPERTIES), 'PropertiesChanged',
                                     'sa{sv}as', (PLAYER, changed, [])))

    def seeked(self, position):
        if self.bus:
            self.bus.send(new_signal(DBusAddress(PATH, interface=PLAYER), 'Seeked', 'x', (int(position * 1_000_000),)))

    def close(self):
        if self.notifier:
            self.notifier.setEnabled(False)
        if self.bus:
            self.bus.close()
            self.bus = None

"""Actual D-Bus serialization and dispatcher, no claim of a desktop session."""
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock
from jeepney import DBusAddress, HeaderFields, new_method_call
from jeepney.low_level import Parser
from yanjaro.mpris import Mpris, PLAYER, ROOT, PATH, PROPERTIES, track_path
from yanjaro.controller import PlaybackController
from test_wave import StubPlayer


def wire(message):
    parser = Parser(); parser.add_data(message.serialise(serial=1))
    return parser.get_next_message()


class MprisTests(unittest.TestCase):
    def setUp(self):
        self.c = PlaybackController(StubPlayer(), Mock())
        self.bus = Mock()
        self.sent=[]
        self.bus.send.side_effect=lambda message: self.sent.append(wire(message))
        self.service=Mpris(self.c,Mock(),Mock(),connection=self.bus)

    def tearDown(self):
        self.service.close();self.c.close()

    def call(self,interface,member,signature='',args=()):
        msg=new_method_call(DBusAddress(PATH, bus_name="org.mpris.MediaPlayer2.yanjaro", interface=interface),member,signature,args)
        msg.header.serial=7
        msg.header.fields[HeaderFields.sender]=':1.9'
        self.service.handle(wire(msg))
        return self.sent[-1]

    def test_introspection_types_metadata_and_position_not_broadcast(self):
        xml=self.call('org.freedesktop.DBus.Introspectable','Introspect').body[0]
        root=ET.fromstring(xml)
        player=root.find(f"interface[@name='{PLAYER}']")
        self.assertEqual(player.find("property[@name='Position']").attrib['type'],'x')
        self.c._state.update(currentId='track:unsafe/path', current='Synthetic',artist='Artist', cover='')
        self.c.player.state.update(loaded=True, paused=False, duration=180, position=42)
        self.c.changed.emit()
        result=self.call(PROPERTIES,'GetAll','s',(PLAYER,)).body[0]
        self.assertEqual(result['Position'],('x',42_000_000))
        self.assertEqual(result['Metadata'][1]['mpris:length'],('x',180_000_000))
        self.assertEqual(result['Metadata'][1]['xesam:artist'],('as',['Artist']))
        self.assertEqual(result['Metadata'][1]['mpris:trackid'][0],'o')
        self.assertNotIn('unsafe',str(result['Metadata']))
        count=len(self.sent)
        self.c.player.state['position']=43;self.c.changed.emit()
        self.assertEqual(len(self.sent),count)
        self.c.player.state['paused']=True;self.c.changed.emit()
        self.assertEqual(self.sent[-1].body[1],{'PlaybackStatus':('s','Paused')})
        self.c.player.seeked.emit(4.5)
        self.assertEqual(self.sent[-1].header.fields[HeaderFields.signature],'x')
        self.assertEqual(self.sent[-1].body,(4_500_000,))

    def test_methods_share_controller_and_guard_track_position_and_radio_modes(self):
        self.c._state.update(currentId='1')
        self.c.player.state.update(loaded=True,paused=False,seekable=True,duration=180)
        self.call(PLAYER,'Pause')
        self.assertTrue(self.c.player.state['paused'])
        self.call(PLAYER,'Play')
        self.assertFalse(self.c.player.state['paused'])
        self.c.seek=Mock()
        self.call(PLAYER,'SetPosition','ox',(track_path('old'),40_000_000))
        self.c.seek.assert_not_called()
        self.call(PLAYER,'SetPosition','ox',(track_path('1'),40_000_000))
        self.c.seek.assert_called_once_with(40)
        self.c.wave_station='radio'
        reply=self.call(PROPERTIES,'Set','ssv',(PLAYER,'Shuffle',('b',True)))
        self.assertEqual(reply.header.fields[HeaderFields.error_name],'org.freedesktop.DBus.Error.NotSupported')
        self.assertEqual(self.call(PROPERTIES,'GetAll','s',(ROOT,)).body[0]['SupportedUriSchemes'],('as',[]))
        self.call(PLAYER,'Stop')
        self.assertEqual(self.c.state['playbackStatus'],'stopped')

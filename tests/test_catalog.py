import threading
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import Mock
from yanjaro.api import MusicApi, Page, Track, station_row
from yanjaro.catalog import station_groups
from yanjaro.controller import PlaybackController
from test_desktop import until
from test_wave import StubPlayer
from test_api import track


class CatalogTests(unittest.TestCase):
    def test_stations_group_by_ids_keep_unknown_and_filter_hidden_top(self):
        def station(kind, tag, parent=None):
            return station_row(Obj(id=Obj(type=kind,tag=tag),parent_id=parent,name=tag,icon=Obj(image_url=''),id_for_from=''))
        rows=[station('genre','rock'), station('genre','regional_child',Obj(type='genre',tag='children')), station('unknown','other')]
        groups=station_groups(rows,{'pins':['genre:rock'], 'hidden':['genre:regional_child']})
        self.assertEqual(groups[0]['title'],'Закреплено на этом устройстве')
        self.assertEqual(rows[1]['group'],'Для детей')
        self.assertEqual(rows[0]['fallback'],'guitar')
        self.assertEqual(groups[-1]['title'],'Другие')
        self.assertEqual(sum(len(g['rows']) for g in groups),3)
        self.assertEqual(station_groups(rows,{},'child')[0]['rows'][0]['id'],'genre:regional_child')

    def test_real_sdk_entity_shapes_all_search_multidisc_and_unavailable(self):
        client=Mock();api=MusicApi(client);api.authenticated=True
        from yandex_music import Search, Album
        client.search.return_value=Search.de_json(dict(searchRequestId='test',text='q',best={'type':'artist','result':{'id':12,'name':'Artist'}},
            artists={'results':[{'id':12,'name':'Artist'}],'total':1,'perPage':20},
            albums={'results':[{'id':13,'title':'Album','artists':[]}],'total':1,'perPage':20},
            tracks={'results':[{'id':14,'title':'Song','artists':[],'durationMs':2000,'available':True}],'total':1,'perPage':20}),None)
        result=api.search('q',type_='all')
        self.assertEqual([r['kind'] for r in result.rows],['artist','track','artist','album'])
        api.search('q',2,'artist');client.search.assert_called_with('q',type_='artist',page=2)
        client.albums_with_tracks.return_value=Album.de_json({'id':13,'title':'Album','artists':[], 'volumes':[
            [{'id':1,'title':'A','artists':[{'id':9,'name':'One'},{'id':10,'name':'Two'}],'available':True}],
            [{'id':2,'title':'B','artists':[],'available':False}]]},None)
        album=api.entity('album','13')
        self.assertEqual([r['id'] for r in album.rows],['1','2'])
        self.assertEqual([r['section'] for r in album.rows],['Диск 1','Диск 2'])
        self.assertEqual(len(album.rows[0]['artists']),2)
        self.assertFalse(album.rows[1]['available'])
        self.assertEqual(album.rows[0]['cover'],'')

    def test_tab_late_response_back_scroll_and_entity_navigation_keep_queue(self):
        api=Mock();p=StubPlayer();c=PlaybackController(p,api)
        c._state['signedIn']=True
        gate,started=threading.Event(),threading.Event()
        artist=dict(id='12',kind='artist',title='Artist',available=True,detail='Artist')
        def search(query,page,kind):
            if kind=='all': started.set();gate.wait(2)
            return Page([artist] if kind=='artist' else [])
        api.search.side_effect=search
        api.entity.return_value=Page([Track('1','Song','Artist',180,True).row()],meta={'id':'12','title':'Artist'})
        try:
            c.search('same');until(started.is_set)
            c.search_tab('artist');gate.set()
            until(lambda:c.state['pageStatus']=='ready')
            self.assertEqual(c.content['rows'][0]['id'],'12')
            self.assertEqual(c.state['searchType'],'artist')
            c.save_scroll(250)
            c.open_entity('artist','12');until(lambda:c.state['pageStatus']=='ready')
            self.assertEqual(p.played,[])
            c.back()
            self.assertEqual(c.state['searchType'],'artist');self.assertEqual(c.content['scroll'],250)
            self.assertEqual(c.state['query'],'same')
            c.search('no results')
            api.search.side_effect=None;api.search.return_value=Page([])
            c.search('empty');until(lambda:c.state['pageStatus']=='ready')
            self.assertEqual(c.content['rows'],[])
        finally:
            gate.set();c.close()

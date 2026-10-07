import threading
import time
import unittest
from unittest.mock import Mock, patch
from yanjaro.api import Page, Track
from yanjaro.controller import PlaybackController
from yanjaro.recommend import Profile, mix
from test_desktop import until, APP
from test_wave import StubPlayer


def candidate(id, artist, origin='liked'):
    return dict(Track(str(id),'Synthetic','Artist',180,True,'1','',({'id':str(artist),'title':'Artist'},)).row(),origins=[origin])


class ExperimentTests(unittest.TestCase):
    def test_deterministic_filter_diversity_rating_and_small_pool(self):
        rows=[candidate(i,i%12,'liked' if i<20 else 'artist') for i in range(60)]
        rows += [rows[1],dict(rows[2],available=False)]
        profile=Profile().data
        profile['ratings']={'3':{'value':-2,'at':100}}
        profile['events']=[dict(id='4',at=99,seconds=10,cause='finished')]
        first=mix(rows,{str(i) for i in range(20)},profile,12,now=100)
        self.assertEqual(first,mix(rows,{str(i) for i in range(20)},profile,12,now=100))
        ids=[r['id'] for r in first]
        self.assertEqual(len(ids),len(set(ids)));self.assertNotIn('3',ids);self.assertNotIn('4',ids)
        artists=[r['artists'][0]['id'] for r in first]
        self.assertTrue(all(a!=b for a,b in zip(artists,artists[1:])))
        self.assertTrue(all(artists.count(a)<=3 for a in artists))
        profile['ratings']['55']={'value':1,'at':100}
        rated=mix(rows,{str(i) for i in range(20)},profile,12,now=100)
        self.assertEqual(rated[0]['id'],'55')
        self.assertLessEqual(len(mix(rows[:2],set(),profile,1,now=100)),2)
        self.assertEqual(mix([],set(),profile,1),[])

    def test_opt_in_requests_bounded_errors_off_discards_response(self):
        api=Mock();c=PlaybackController(StubPlayer(),api)
        c._state['signedIn']=True
        c.pages['likes'].update(ids=('0','1','2'),status='ready')
        api.track_rows.return_value=[candidate(i,i) for i in range(3)]
        api.candidates.side_effect=[RuntimeError('SECRET'),[candidate(8,8,'artist')],[]]
        gate,started=threading.Event(),threading.Event()
        try:
            c.build_mix();api.track_rows.assert_not_called()
            c.enable_experiment(True);c.build_mix()
            until(lambda:c.pages['experiment']['status']=='ready')
            self.assertLessEqual(api.candidates.call_count,3)
            self.assertGreater(len(c.content['rows']),0)
            self.assertNotIn('SECRET',c.state['experimentMessage'])
            api.wave_batch.assert_not_called()
            def blocked(ids): started.set();gate.wait(2);return [candidate(9,9)]
            api.track_rows.side_effect=blocked
            c.build_mix();until(started.is_set)
            count=api.candidates.call_count
            c.enable_experiment(False);gate.set()
            drained=c.pool.submit(lambda:True)
            until(drained.done)
            APP.processEvents()
            self.assertEqual(api.candidates.call_count,count)
            self.assertEqual(c.pages['experiment']['rows'],[])
            self.assertFalse(c.state['experimentEnabled'])
        finally:
            gate.set();c.close()

    def test_observed_intervals_and_event_dedup_retention(self):
        p=StubPlayer();c=PlaybackController(p,Mock())
        c.enable_experiment(True)
        c.play_session=(Track('1','Synthetic','',180,True),'one','timestamp')
        try:
            with patch('yanjaro.controller.time.monotonic') as clock:
                clock.return_value=10;c.last_tick=10
                p.state.update(loaded=True,paused=False);p.changed.emit()
                clock.return_value=10.5;c._tick()
                self.assertEqual(c.listened,.5)
                p.state['paused']=True;p.changed.emit()
                clock.return_value=30;c._tick();self.assertEqual(c.listened,.5)
                p.state.update(paused=False,seeking=True,position=120);p.changed.emit()
                clock.return_value=31;c._tick();self.assertEqual(c.listened,.5)
                p.state.update(seeking=False,buffering=True);p.changed.emit()
                clock.return_value=32;c._tick();self.assertEqual(c.listened,.5)
                p.state['buffering']=False;p.changed.emit()
                clock.return_value=32.4;c._finish_track('skip','source-change')
                self.assertAlmostEqual(c.profile.data['events'][0]['seconds'],.9)
                self.assertEqual(c.profile.data['events'][0]['cause'],'source-change')
                c._finish_track('skip','manual-skip')
                self.assertEqual(len(c.profile.data['events']),1)
            c.profile.data['events'].append(dict(id='old',play='old',at=0,seconds=99,cause='finished'))
            c.profile.prune();self.assertEqual(len(c.profile.data['events']),1)
            c.enable_experiment(False)
            c.profile.record('off','2','source',12,'finished')
            self.assertEqual(len(c.profile.data['events']),1)
        finally:c.close()

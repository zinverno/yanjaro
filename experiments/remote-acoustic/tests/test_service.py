import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from remote_acoustic.model import train,export_model,SCHEMA
from remote_acoustic.service import create_app

KEY='THIS-IS-A-SYNTHETIC-SECRET-FOR-TESTING-ONLY-1234'

@pytest.fixture
def anyio_backend():
    return 'asyncio'

def client(tmp_path):
    rng=np.random.default_rng(1)
    X=rng.normal(0,.1,size=(150,12));val=np.array([i%5==0 for i in range(150)])
    w,metrics=train(X,val,epochs=10)
    path=tmp_path/'model.json';export_model(path,w,metrics,source='synthetic-test-only')
    return AsyncClient(transport=ASGITransport(app=create_app(path,KEY,allow_demo=True)),
                       base_url='http://test')

def body():return {'schema_id':SCHEMA,'context':[.1]*12,
                   'candidates':[{'id':'123','embedding':[.1]*12},{'id':'456','embedding':[-.1]*12}]}

@pytest.mark.anyio
async def test_reject_no_key(tmp_path):
    async with client(tmp_path) as c:
        assert (await c.get('/healthz')).status_code==200
        assert (await c.post('/v1/rank',json=body())).status_code==401
        assert (await c.post('/v1/rank',json=body(),headers={'Authorization':'Bearer wrong'})).status_code==401

@pytest.mark.anyio
async def test_authenticated_rank_and_schema_gate(tmp_path):
    async with client(tmp_path) as c:
        r=await c.post('/v1/rank',json=body(),headers={'Authorization':'Bearer '+KEY})
        assert r.status_code==200,r.text
        assert [x['id'] for x in r.json()['ranked']]==['123','456']
        p=body();p['schema_id']='acoustic.27';
        assert (await c.post('/v1/rank',json=p,headers={'Authorization':'Bearer '+KEY})).status_code==422

@pytest.mark.anyio
async def test_reject_duplicate_ids_and_bad_shapes(tmp_path):
    async with client(tmp_path) as c:
        p=body();p['candidates'][1]['id']='123'
        assert (await c.post('/v1/rank',json=p,headers={'Authorization':'Bearer '+KEY})).status_code==422
        p=body();p['context']=[1.0]*10
        assert (await c.post('/v1/rank',json=p,headers={'Authorization':'Bearer '+KEY})).status_code==422

def test_missing_key_or_model_blocks_server(tmp_path):
    X=np.ones((100,8));val=np.arange(100)%5==0
    w,m=train(X,val,epochs=5)
    p=tmp_path/'model.json';export_model(p,w,m,source='synthetic-test-only')
    with pytest.raises(ValueError,match='YANJARO_RANK_API_KEY'):
        create_app(p,'no',allow_demo=True)
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path/'missing.json',KEY)

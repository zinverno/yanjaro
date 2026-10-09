"""Stateless, authenticated remote ranker. No Yandex account, tokens or audio."""
from __future__ import annotations
import hmac
import os
from pathlib import Path
from fastapi import FastAPI,Header,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .model import Ranker

class Candidate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(min_length=1,max_length=128)
    embedding: list[float]=Field(min_length=8,max_length=2048)

class RankingRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_id: str
    context: list[float]=Field(min_length=8,max_length=2048)
    candidates: list[Candidate]=Field(min_length=1,max_length=64)


def create_app(model_path:Path|str,api_key:str,*,allow_demo:bool=False):
    """Key is set in hosting provider's secret config; never checked into Git."""
    if len(api_key)<32:
        raise ValueError('Set an unpredictable YANJARO_RANK_API_KEY (>=32 characters)')
    model=Ranker.load(Path(model_path),allow_demo=allow_demo)
    app=FastAPI(title='Yanjaro Research Acoustic Ranker',version='0.1.0',docs_url=None,redoc_url=None)

    # Bounded in-memory work only: no blocking I/O or worker-thread handoff.
    @app.get('/healthz')
    async def healthz():
        return {'status':'ok','schema':model.metadata['schema'],'source':model.metadata['source'],
                'catalog_mapping_available':False,'mood_validation':'not established'}

    @app.post('/v1/rank')
    async def rank(data:RankingRequest,authorization:str|None=Header(default=None)):
        if not authorization or not authorization.startswith('Bearer ') or \
                not hmac.compare_digest(authorization[7:],api_key):
            raise HTTPException(status_code=401,detail='Unauthorized')
        if data.schema_id != model.metadata['schema']:
            raise HTTPException(status_code=422,detail='Unsupported acoustic feature schema')
        if len({c.id for c in data.candidates}) != len(data.candidates):
            raise HTTPException(status_code=422,detail='Duplicate candidate IDs')
        try:
            rows=model.rank(data.context,[c.model_dump() for c in data.candidates])
        except (ValueError,TypeError):
            raise HTTPException(status_code=422,detail='Invalid feature vectors') from None
        # Caller MUST supply embeddings already aligned to the trained schema;
        # anonymized Yambda IDs cannot be treated as Yandex track IDs.
        return {'schema_id':model.metadata['schema'],'ranked':rows,
                'yandex_track_id_lookup_available':False}
    return app


# Uvicorn import path. Prevent serving when real model or secret is missing.
class _LazyApp:
    def __init__(self): self._app=None
    async def __call__(self,scope,receive,send):
        if self._app is None:
            self._app=create_app(os.environ.get('MODEL_PATH','/app/artifacts/model.json'),
                                 os.environ.get('YANJARO_RANK_API_KEY',''))
        await self._app(scope,receive,send)

app=_LazyApp()

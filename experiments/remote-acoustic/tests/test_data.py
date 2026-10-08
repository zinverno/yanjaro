import tempfile
from pathlib import Path
import pytest
from remote_acoustic.data import (build_pairs,required_ids,is_holdout,atomic_jsonl,
                                  load_pairs,extract_needed_embeddings,save_vectors)

def test_nearby_votes_need_strictly_earlier_context():
    likes={7:[(1,101,'like'),(2,102,'like'),(3,103,'like'),(5,104,'like')]}
    dislikes={7:[(6,900,'dislike')]}
    rows=build_pairs(likes,dislikes,window_days=1)
    assert len(rows)==1
    r=rows[0]
    assert r['positive']==104 and r['negative']==900
    assert 900 not in r['context'] and 104 not in r['context']
    assert r['context']==[101,102,103]
    assert required_ids(rows)=={101,102,103,104,900}

def test_no_negative_or_leak_returns_no_examples():
    assert build_pairs({1:[(3,44,'like'),(10,77,'like')]},{1:[(2,22,'dislike')]})==[]

def test_holdout_stable():
    assert is_holdout(100)==is_holdout(100)
    assert 0<len([u for u in range(200) if is_holdout(u)])<100

def test_pair_jsonl_atomic_roundtrip(tmp_path):
    p=tmp_path/'pairs.jsonl'
    rows=[{'uid':1,'context':[1,2],'positive':4,'negative':5}]
    atomic_jsonl(p,rows)
    assert load_pairs(p)==rows
    assert not p.with_suffix('.jsonl.tmp').exists()

def test_extract_small_real_shape_parquet(tmp_path):
    pa=pytest.importorskip('pyarrow')
    import pyarrow.parquet as pq
    path=tmp_path/'vectors.parquet'
    table=pa.table({'item_id':[4,7,11], 'normalized_embed':[[1.0]*10,[.2]*10,[.3]*10]})
    pq.write_table(table,path)
    got=extract_needed_embeddings(str(path),{7,11,90},batch_size=2)
    assert set(got)=={7,11}
    n,dim=save_vectors(tmp_path/'selected.npz',got)
    assert (n,dim)==(2,10)

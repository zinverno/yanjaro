import json
import numpy as np
import pytest
from remote_acoustic.model import (train,export_model,Ranker,pair_accuracy,SCHEMA,
                                   build_training_arrays)

def synthetic():
    rng=np.random.default_rng(123)
    X=rng.normal(0,.10,size=(300,16))
    X[:,0]=np.abs(X[:,0])+.4
    X[:,1]=-np.abs(X[:,1])-.2
    held=np.array([i%5==0 for i in range(len(X))],dtype=bool)
    return X,held

def test_model_learns_better_than_baseline_on_synthetic_example():
    X,val=synthetic()
    weights,report=train(X,val,epochs=250)
    assert report['train_pairs']==240 and report['holdout_pairs']==60
    assert report['learned_holdout_accuracy']>=report['cosine_baseline_holdout_accuracy']
    assert weights.shape==(16,) and np.all(weights>0)

def test_model_holdout_not_used_for_updates():
    X,val=synthetic()
    w1,_=train(X,val,epochs=10)
    copy=X.copy();copy[val,:]*=-100
    w2,_=train(copy,val,epochs=10)
    np.testing.assert_array_equal(w1,w2)

def test_export_refuses_production_without_real_source(tmp_path):
    X,val=synthetic();w,m=train(X,val,epochs=25)
    p=tmp_path/'model.json'
    export_model(p,w,m,source='synthetic-test-only')
    with pytest.raises(ValueError,match='Synthetic'):
        Ranker.load(p)
    model=Ranker.load(p,allow_demo=True)
    assert model.metadata['schema']==SCHEMA
    ranked=model.rank([1.0]*16,[{'id':'A','embedding':[1.0]*16},
                                    {'id':'B','embedding':[-1.0]*16}])
    assert [x['id'] for x in ranked]==['A','B']

def test_real_model_vector_validation(tmp_path):
    X,val=synthetic();w,m=train(X,val,epochs=25)
    p=tmp_path/'model.json';export_model(p,w,m,source='yandex/yambda')
    obj=Ranker.load(p)
    with pytest.raises(ValueError,match='dimension'):
        obj.rank([1.0]*8,[{'id':'A','embedding':[1.0]*16}])
    with pytest.raises(ValueError,match='Nonfinite'):
        obj.rank([1.0]*15+[float('nan')],[{'id':'A','embedding':[1.0]*16}])

def test_build_training_vectors_no_missing_and_disjoint_users():
    # Pos/negative vectors and last likes only; no other fields.
    bank={i:np.eye(12,dtype=np.float32)[i%12] for i in range(20)}
    pairs=[{'uid':u,'context':[1,2],'positive':3,'negative':4} for u in range(45)]
    matrix,valid,cov=build_training_arrays(pairs,bank)
    assert matrix.shape==(45,12)
    assert cov['pairs_with_full_audio']==45
    assert 0<valid.sum()<len(valid)

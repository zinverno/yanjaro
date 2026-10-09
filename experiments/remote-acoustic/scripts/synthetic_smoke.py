"""OFFLINE TEST ONLY: toy vectors prove training/deployment plumbing, not model quality."""
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from remote_acoustic.model import train,export_model,Ranker,SCHEMA

rng=np.random.default_rng(42)
d=16;n=320
X=rng.normal(0,.15,size=(n,d))
# hidden preference deliberately differs from cosine:
X[:,0]=np.abs(X[:,0])+.25
X[:,1]=-np.abs(X[:,1])-.22
v=np.array([i%5==0 for i in range(n)],dtype=bool)
w,metrics=train(X,v,epochs=200)
out=Path('work/synthetic-model.json');export_model(out,w,metrics,source='synthetic-test-only')
model=Ranker.load(out,allow_demo=True)
print(json.dumps({'kind':'SYNTHETIC-ONLY','metrics':metrics,'model':str(out),
 'trained_weights_first_3':[float(q) for q in w[:3]],'schema':SCHEMA},indent=2))

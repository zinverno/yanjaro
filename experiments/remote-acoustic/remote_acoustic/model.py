"""Trained diagonal acoustic-similarity model with user-disjoint validation.

This is an ACTUAL learned preference metric when fit to real Yambda examples.
It is not a BPM/meter predictor and cannot map anonymized IDs to Yandex IDs.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import numpy as np
from .data import is_holdout

MODEL_FORMAT = "yanjaro.yambda.diagonal_ranker.v1"
SCHEMA = "yambda.normalized_audio_embedding.v1"


def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.divide(v, np.maximum(norm, 1e-12))


def build_training_arrays(pairs: list[dict], vector_bank: dict[int, np.ndarray]):
    features, holdout, covered_users = [], [], set()
    train_users, holdout_users = set(), set()
    skipped = 0
    for pair in pairs:
        ids = list(pair['context']) + [pair['positive'], pair['negative']]
        if any(int(tid) not in vector_bank for tid in ids):
            skipped += 1
            continue
        ctx = unit(np.mean(unit(np.stack([vector_bank[int(t)] for t in pair['context']])),axis=0))
        pos = unit(vector_bank[int(pair['positive'])])
        neg = unit(vector_bank[int(pair['negative'])])
        if (not np.isfinite(ctx).all() or not np.isfinite(pos).all() or not np.isfinite(neg).all()
                or np.linalg.norm(ctx) < 1e-9):
            skipped += 1
            continue
        features.append(ctx * (pos-neg))
        holdout.append(is_holdout(pair['uid']))
        covered_users.add(pair['uid'])
        (holdout_users if is_holdout(pair['uid']) else train_users).add(pair['uid'])
    if not features:
        raise ValueError('No training examples have all audio embeddings')
    return np.asarray(features,dtype=np.float64), np.asarray(holdout,dtype=np.bool_), {
        'pairs_in_source':len(pairs),'pairs_with_full_audio':len(features),
        'missing_pairs':skipped,'covered_anonymized_users':len(covered_users),
        'train_users':len(train_users), 'holdout_users':len(holdout_users)}


def pair_accuracy(scores: np.ndarray) -> float:
    if len(scores)==0:
        return float('nan')
    return float(np.mean(np.where(scores>1e-9,1.0,np.where(scores < -1e-9,0.0,0.5))))


def train(features: np.ndarray, validation: np.ndarray, *, epochs=250, lr=0.035, l2=0.015):
    """BPR/logistic loss; cosine baseline is diagonal weights=1.

    Splits are fixed and feature engineering has no dataset-fitted scaler.
    Validation is NEVER used for gradients or checkpoint selection.
    """
    X = np.asarray(features,dtype=np.float64)
    val = np.asarray(validation,dtype=np.bool_)
    if X.ndim != 2 or val.shape != (len(X),) or X.shape[1] < 8:
        raise ValueError('Invalid pair feature matrix')
    if not np.isfinite(X).all():
        raise ValueError('Nonfinite pair features')
    if (len(X[~val]) < 20 or len(X[val]) < 8):
        raise ValueError('Need at least 20 real training pairs and 8 held-out pairs')
    X = X * np.sqrt(X.shape[1])
    tr = X[~val]
    te = X[val]
    w = np.ones(X.shape[1],dtype=np.float64)
    m=np.zeros_like(w);v=np.zeros_like(w)
    for step in range(1, epochs+1):
        diff = tr @ w
        p = np.exp(-np.logaddexp(0,diff))  # stable sigmoid(-score)
        g = -(tr.T @ p) / len(tr) + l2*(w-1)
        m=.9*m+.1*g; v=.999*v+.001*g*g
        w -= lr*(m/(1-.9**step))/(np.sqrt(v/(1-.999**step))+1e-8)
        w=np.clip(w,.05,5.0)
    btr=tr @ np.ones(len(w)); bte=te @ np.ones(len(w))
    ptr=tr @ w; pte=te @ w
    metrics={
      'train_pairs':int(len(tr)), 'holdout_pairs':int(len(te)),
      'cosine_baseline_train_accuracy':pair_accuracy(btr),
      'learned_train_accuracy':pair_accuracy(ptr),
      'cosine_baseline_holdout_accuracy':pair_accuracy(bte),
      'learned_holdout_accuracy':pair_accuracy(pte),
      'training_epochs':epochs, 'regularization_l2':l2,
    }
    return w.astype(np.float32),metrics


@dataclass(frozen=True)
class Ranker:
    weights: np.ndarray
    metadata: dict

    @classmethod
    def load(cls,path:Path, *, allow_demo:bool=False):
        raw=json.loads(path.read_text(encoding='utf-8'))
        if raw.get('format') != MODEL_FORMAT or raw.get('schema') != SCHEMA:
            raise ValueError('Unsupported model/schema')
        if raw.get('source') != 'yandex/yambda' and not allow_demo:
            raise ValueError('Synthetic or unidentified model cannot be served publicly')
        weights=np.asarray(raw.get('weights'),dtype=np.float64)
        if weights.ndim!=1 or not 8<=len(weights)<=2048 or not np.isfinite(weights).all() or np.any(weights<=0):
            raise ValueError('Invalid trained weights')
        if raw.get('source') == 'yandex/yambda' and raw.get('train_pairs',0)<20:
            raise ValueError('Insufficient observed training pairs')
        return cls(weights.astype(np.float32),raw)

    def rank(self,context, candidates):
        """ID plus AUDIO VECTOR inputs; IDs alone are NOT enough."""
        ctx=np.asarray(context,dtype=np.float32)
        arr=np.asarray([c['embedding'] for c in candidates],dtype=np.float32)
        d=len(self.weights)
        if ctx.shape!=(d,) or arr.shape!=(len(candidates),d):
            raise ValueError(f'Expected vectors of dimension {d}')
        if not np.isfinite(ctx).all() or not np.isfinite(arr).all():
            raise ValueError('Nonfinite vectors')
        c=unit(ctx)
        xs=unit(arr)
        scores=np.sqrt(d)*(xs @ (self.weights * c))
        results=[{'id':str(item['id']), 'score':float(score)}
                 for item,score in zip(candidates,scores)]
        return sorted(results,key=lambda x:(-x['score'],x['id']))


def export_model(path:Path,weights, metrics:dict, *,source:str,extra=None):
    if source not in ('yandex/yambda','synthetic-test-only'):
        raise ValueError('Invalid provenance')
    data={'format':MODEL_FORMAT,'schema':SCHEMA,'source':source,'weights':np.asarray(weights).tolist(),
          'dimension':len(weights),**metrics}
    if extra: data.update(extra)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Prevent exporting invalid artifacts that would fail loading.
    if any(not math.isfinite(float(x)) for x in data['weights']):
        raise ValueError('Nonfinite weights')
    tmp=path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return data

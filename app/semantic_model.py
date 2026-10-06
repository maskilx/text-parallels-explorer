"""Shared semantic windowing and retrieval, independent of the evaluation harness."""
import numpy as np
from .engine import tokenize, overlap

MODEL = 'sentence-transformers/paraphrase-MiniLM-L6-v2'
REVISION = 'c9a2bfebc254878aee8c3aca9e6844d5bbb102d1'
THRESHOLD = .65
TOP_K = 1
PIPELINE_VERSION = 'semantic-runtime-1'

def windows(doc):
    """One and two adjacent verses, within a chapter; exact original offsets."""
    refs=doc['references']; out=[]
    for i,r in enumerate(refs):
        for n in (1,2):
            end=i+n-1
            if end>=len(refs) or refs[end]['label'].split(':')[0]!=r['label'].split(':')[0]:continue
            a,b=r['start'],refs[end]['end'];text=doc['text'][a:b]
            if 8<=len(tokenize(text))<=90:
                out.append(dict(start=a,end=b,reference=r['label'] if n==1 else r['label']+'–'+refs[end]['label'],text=text))
    return out

def retrieve(left,right,a,b,threshold,top_k=3):
    """Score the small corpus matrix; retain mutual top-k above threshold."""
    scores=a@b.T
    ka=min(top_k,len(right));kb=min(top_k,len(left))
    best_b=np.argsort(-scores,axis=1,kind='stable')[:,:ka]
    best_a=np.argsort(-scores,axis=0,kind='stable')[:kb,:]
    out=[]
    for i,targets in enumerate(best_b):
        for j in targets:
            s=float(np.clip(scores[i,j], -1, 1))
            if s<threshold or i not in best_a[:,j]:continue
            x,y=left[i],right[j]
            out.append(dict(start_a=x['start'],end_a=x['end'],start_b=y['start'],end_b=y['end'],score=s,
                            reference_a=x['reference'],reference_b=y['reference'],text_a=x['text'],text_b=y['text']))
    kept=[]
    for m in sorted(out,key=lambda m:(-m['score'],m['start_a'],m['start_b'])):
        if any(overlap((m['start_a'],m['end_a']),(p['start_a'],p['end_a']))>=.85 and
               overlap((m['start_b'],m['end_b']),(p['start_b'],p['end_b']))>=.85 for p in kept):continue
        kept.append(m)
    return kept


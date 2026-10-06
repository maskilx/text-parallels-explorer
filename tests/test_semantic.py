import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app import main, semantic
from app.engine import fingerprint
from app.store import Store
from scripts.semantic_retrieval import windows, retrieve
from tests.test_store_api import store

def cache(store,path):
    with store.connect() as c:docs={r['id']:dict(r) for r in c.execute('SELECT * FROM documents')}
    a,b=sorted(docs)[:2];x,y=docs[a]['content'],docs[b]['content']
    identity=f"semantic:{a}:{docs[a]['content_hash']}:{b}:{docs[b]['content_hash']}:0:{len(x)}:0:{len(y)}"
    item=dict(id=fingerprint(identity),document_a=a,document_b=b,start_a=0,end_a=len(x),start_b=0,end_b=len(y),text_a=x,text_b=y,score=.75,reference_a='1:1',reference_b='1:1')
    data=dict(corpus_hashes={k:d['content_hash'] for k,d in docs.items()},model='test',revision='fixed',threshold=.6,items=[item])
    path.write_text(json.dumps(data));return data,item

def test_semantic_import_idempotent_review_restart_and_lexical_rerun(store,tmp_path,monkeypatch):
    path=tmp_path/'semantic.json';data,item=cache(store,path);semantic.initialize(store,path)
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        semantic.initialize(store,path)
        result=client.get('/api/semantic').json();assert result['total']==1
        assert result['items'][0]['text_a']==item['text_a']
        url='/api/semantic/'+item['id']+'/review'
        assert client.patch(url,json={'status':'accepted','note':'Independent review'}).status_code==200
        semantic.initialize(store,path);store.analyze();semantic.initialize(Store(store.path,store.corpus),path)
        assert client.get('/api/semantic?status=accepted').json()['items'][0]['note']=='Independent review'
        assert client.get('/api/semantic?min_score=.8').json()['total']==0
        assert client.get('/api/semantic?status=rejected').json()['total']==0
        assert client.get('/api/semantic?pair=doc0,doc1').json()['total']==1
        assert client.get('/api/semantic?pair=doc1,doc0').json()['total']==1
        assert client.get('/api/semantic?pair=doc0,doc0').status_code==422
        assert client.get('/api/semantic?offset=1').json()['items']==[]
        assert client.get('/api/semantic?q=%25').json()['total']==0
        assert client.get('/api/semantic?min_score=1.1').status_code==422
        assert client.get('/api/semantic?limit=101').status_code==422
        assert client.patch(url,json={'status':'bad'}).status_code==422
        assert client.patch('/api/semantic/missing/review',json={'status':'pending'}).status_code==404

def test_corrupt_cache_never_partially_publishes(store,tmp_path):
    path=tmp_path/'semantic.json';data,item=cache(store,path);semantic.initialize(store,path)
    item['text_a']='Corrupted source';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='offsets'):semantic.initialize(store,path)
    with store.connect() as c:assert c.execute('SELECT count(*) FROM semantic_suggestions WHERE active=1').fetchone()[0]==1

def test_invalid_cache_identity_rejected(store,tmp_path):
    path=tmp_path/'semantic.json';data,item=cache(store,path);item['id']='invalid';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='identity'):semantic.initialize(store,path)

def test_windows_keep_unicode_offsets_and_do_not_cross_chapters():
    parts=['🌿 One two three four five six seven eight nine.','Second verse has eight words with extra text here.','Third verse begins a different chapter with enough words.']
    text='\n'.join(parts);refs=[];start=0
    for label,p in zip(['1:1','1:2','2:1'],parts):refs.append(dict(label=label,start=start,end=start+len(p)));start+=len(p)+1
    found=windows(dict(text=text,references=refs))
    assert [w['reference'] for w in found]==['1:1','1:1–1:2','1:2','2:1']
    assert all(text[w['start']:w['end']]==w['text'] for w in found)
    assert found[0]['start']==0

def test_mutual_top_one_rejects_one_sided_match_and_threshold():
    left=[dict(start=i*100,end=i*100+50,text=str(i),reference=str(i)) for i in range(2)]
    right=[dict(start=0,end=50,text='target',reference='target')]
    a=np.array([[1.,0.],[.8,.6]]);b=np.array([[1.,0.]])
    found=retrieve(left,right,a,b,.6,1)
    assert len(found)==1 and found[0]['start_a']==0
    assert retrieve(left,right,a,b,1.01,1)==[]

def test_overlap_dedup_requires_overlap_in_both_sources():
    left=[dict(start=0,end=50,text='x',reference='x'),dict(start=100,end=150,text='y',reference='y')]
    right=[dict(start=0,end=50,text='z',reference='z')]
    a=np.array([[1.,0.],[1.,0.]]);b=np.array([[1.,0.]])
    assert len(retrieve(left,right,a,b,.6,3))==2

def test_changed_corpus_cache_cannot_expose_stale_results(store,tmp_path):
    path=tmp_path/'semantic.json';data,item=cache(store,path);semantic.initialize(store,path)
    data['corpus_hashes']['doc0']='different';path.write_text(json.dumps(data));semantic.initialize(store,path)
    with store.connect() as c:assert c.execute('SELECT count(*) FROM semantic_suggestions WHERE active=1').fetchone()[0]==0

def test_bundled_cache_all_ranges_unique_and_exact_source_substrings(tmp_path):
    real=Store(tmp_path/'real.sqlite');real.initialize();semantic.initialize(real)
    with real.connect() as c:
        docs={r['id']:r['content'] for r in c.execute('SELECT * FROM documents')}
        rows=list(c.execute('SELECT * FROM semantic_suggestions WHERE active=1'));assert len(rows)>0
        ranges=[]
        for row in rows:
            m=json.loads(row['payload']);assert m['score']>=m['threshold']
            for side in ('a','b'):assert docs[m['document_'+side]][m['start_'+side]:m['end_'+side]]==m['text_'+side]
            ranges.append(tuple(m[k] for k in ['document_a','document_b','start_a','end_a','start_b','end_b']))
        assert len(ranges)==len(set(ranges))

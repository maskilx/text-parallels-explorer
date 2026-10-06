import csv, io, json, threading
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import main
from app.store import Store
from app.engine import fingerprint
from tests.test_engine import PASSAGE

@pytest.fixture
def store(tmp_path):
    corpus=tmp_path/'corpus'; corpus.mkdir();manifest=[]
    for i,text in enumerate([PASSAGE,PASSAGE.replace('wooden','stone'),PASSAGE]):
        name=f'doc{i}';(corpus/f'{name}.txt').write_text(text)
        (corpus/f'{name}.refs.json').write_text(json.dumps([{'label':'1:1','start':0,'end':len(text)}]))
        manifest.append(dict(id=name,title=name,edition='Test',file=f'{name}.txt',refs=f'{name}.refs.json',source_url='https://example.org',license='Public domain',sha256=fingerprint(text)))
    (corpus/'manifest.json').write_text(json.dumps(manifest))
    s=Store(tmp_path/'test.sqlite',corpus);s.initialize();s.analyze();return s

@pytest.fixture
def client(store,monkeypatch):
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client: yield client

def test_all_pairs_and_review_idempotency(store):
    with store.connect() as c:
        ids=[r[0] for r in c.execute('SELECT id FROM parallels ORDER BY id')]
        assert len(ids)==3
        c.execute("UPDATE reviews SET status='accepted',note='Research note' WHERE parallel_id=?",(ids[0],))
    store.analyze();store.analyze()
    with store.connect() as c:
        assert ids==[r[0] for r in c.execute('SELECT id FROM parallels ORDER BY id')]
        assert c.execute('SELECT count(*) FROM reviews').fetchone()[0]==3
        assert tuple(c.execute('SELECT status,note FROM reviews WHERE parallel_id=?',(ids[0],)).fetchone())==('accepted','Research note')
    restarted=Store(store.path,store.corpus);restarted.initialize()
    with restarted.connect() as c: assert c.execute("SELECT count(*) FROM reviews WHERE status='accepted'").fetchone()[0]==1

def test_failed_analysis_does_not_publish_partial_results(store):
    with patch('app.store.detect_pair',side_effect=RuntimeError('Injected failure')):
        with pytest.raises(RuntimeError): store.analyze()
    with store.connect() as c:
        assert c.execute('SELECT count(*) FROM parallels WHERE active=1').fetchone()[0]==3
        assert c.execute('SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1').fetchone()[0]=='failed'
    assert not store.lock.locked()

def test_concurrency_guard(store):
    store.lock.acquire()
    try:
        with pytest.raises(RuntimeError,match='already running'): store.analyze()
    finally:store.lock.release()

def test_api_filters_pagination_detail_review_export(client):
    assert client.get('/api/health').status_code==200
    assert len(client.get('/api/documents').json())==3
    rows=client.get('/api/parallels').json();assert rows['total']==3
    assert client.get('/api/parallels?kind=exact').json()['total']==1
    assert client.get('/api/parallels?kind=near').json()['total']==2
    assert client.get('/api/parallels?pair=doc0,doc1').json()['total']==1
    assert client.get('/api/parallels?document=doc0').json()['total']==2
    assert client.get('/api/parallels?min_score=1').json()['total']==1
    assert client.get('/api/parallels?min_words=9999').json()['total']==0
    assert client.get('/api/parallels?q=wooden').json()['total']>=1
    first=client.get('/api/parallels?limit=1').json()['items'][0]
    second=client.get('/api/parallels?limit=1&offset=1').json()['items'][0]
    assert first['id']!=second['id']
    d=client.get('/api/parallels/'+first['id']).json()
    assert d['passages'][0]['reference']=='1:1' and d['diff']
    response=client.patch('/api/parallels/'+first['id']+'/review',json={'status':'accepted','note':'=HYPERLINK("evil")'})
    assert response.status_code==200
    assert client.get('/api/parallels?status=accepted').json()['total']==1
    exported=list(csv.DictReader(io.StringIO(client.get('/api/export.csv?status=accepted').text)))
    assert len(exported)==1 and exported[0]['note'].startswith("'=")
    assert client.get('/api/stats').json()['counts']['accepted']==1

@pytest.mark.parametrize('path',[
    '/api/parallels?min_score=2','/api/parallels?offset=-1','/api/parallels?limit=101',
    '/api/parallels?kind=semantic','/api/parallels?sort=DROP%20TABLE','/api/parallels?pair=doc0',
])
def test_invalid_inputs(client,path): assert client.get(path).status_code==422

def test_missing_review_and_invalid_status(client):
    assert client.get('/api/parallels/missing').status_code==404
    assert client.patch('/api/parallels/missing/review',json={'status':'accepted'}).status_code==404
    parallel=client.get('/api/parallels').json()['items'][0]['id']
    assert client.patch(f'/api/parallels/{parallel}/review',json={'status':'invalid'}).status_code==422
    assert client.patch(f'/api/parallels/{parallel}/review',json={'status':'pending','note':'x'*5001}).status_code==422

def test_query_injection_and_literal_wildcards(client):
    assert client.get('/api/parallels',params={'q':"' OR 1=1 --"}).json()['total']==0
    assert client.get('/api/parallels',params={'q':'%'}).json()['total']==0

def test_interrupted_run_marked_failed(store):
    with store.connect() as c:c.execute("INSERT INTO analysis_runs(started_at,status,algorithm_version,config) VALUES('now','running','test','{}')")
    store.initialize()
    with store.connect() as c:assert c.execute('SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1').fetchone()[0]=='failed'

def test_publish_transaction_rolls_back_after_deactivation(store):
    import sqlite3
    with store.connect() as c:
        original=dict(c.execute('SELECT * FROM parallels LIMIT 1').fetchone())
        before=[tuple(r) for r in c.execute('SELECT id,active FROM parallels ORDER BY id')]
    # Invalid offsets cause the DB write to fail AFTER active rows were deactivated.
    fake={k:v for k,v in original.items() if k not in ['id','document_a','document_b','run_id','active']}
    fake['start_a']=-1
    with patch('app.store.detect_pair',return_value=[fake]):
        with pytest.raises(sqlite3.IntegrityError):store.analyze()
    with store.connect() as c:
        assert before==[tuple(r) for r in c.execute('SELECT id,active FROM parallels ORDER BY id')]
        assert c.execute('SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1').fetchone()[0]=='failed'

def test_database_rejects_same_ranges_with_different_id(store):
    import sqlite3
    with store.connect() as c:row=dict(c.execute('SELECT * FROM parallels LIMIT 1').fetchone())
    row['id']='different-id-same-ranges'
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as c:
            c.execute(f"INSERT INTO parallels({','.join(row)}) VALUES({','.join('?' for _ in row)})",list(row.values()))

def test_api_analysis_conflict(client,store):
    store.lock.acquire()
    try:assert client.post('/api/analysis').status_code==409
    finally:store.lock.release()

def test_checksum_corruption_is_rejected(store):
    path=store.corpus/'doc0.txt';path.write_text(path.read_text()+' corrupted')
    with pytest.raises(ValueError,match='checksum mismatch'):store.initialize()

def test_new_algorithm_version_requires_analysis_but_preserves_reviews(store):
    from app.engine import VERSION
    assert store.has_results()
    with store.connect() as c:
        first=c.execute('SELECT id FROM parallels ORDER BY id LIMIT 1').fetchone()[0]
        c.execute("UPDATE reviews SET status='accepted',note='Preserve across upgrade' WHERE parallel_id=?",(first,))
        c.execute("UPDATE analysis_runs SET algorithm_version='old-version'")
    assert not store.has_results()
    store.analyze();assert store.has_results()
    with store.connect() as c:
        assert c.execute('SELECT algorithm_version FROM analysis_runs ORDER BY id DESC LIMIT 1').fetchone()[0]==VERSION
        assert tuple(c.execute('SELECT status,note FROM reviews WHERE parallel_id=?',(first,)).fetchone())==('accepted','Preserve across upgrade')

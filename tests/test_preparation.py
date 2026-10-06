import json
import threading
from unittest.mock import Mock
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app import main, preparation
from app.preparation import Preparation, compute, inputs, cached
from tests.test_store_api import store


class TinyModel:
    max_seq_length = 128
    def tokenizer(self, text, truncation=False):
        return {'input_ids': list(range(len(text.split())))}
    def encode(self, texts, **kwargs):
        return np.tile(np.array([1., 0.], dtype=np.float32), (len(texts), 1))


def prepare(store, model_factory=TinyModel):
    controller=Preparation(store, model_factory)
    controller.start()
    controller.thread.join(timeout=10)
    assert not controller.thread.is_alive()
    return controller


def test_first_run_computes_and_second_run_never_loads_model(store):
    # Leave lexical run metadata intact but expose these tiny windows as new candidates.
    with store.connect() as c:c.execute('UPDATE parallels SET active=0')
    first=prepare(store)
    assert first.snapshot()['status']=='ready' and not first.snapshot()['cache_hit']
    data=json.loads(first.path.read_text());assert data['generated_by']=='local-model'
    assert len(data['items'])==3
    identifier=data['items'][0]['id']
    with store.connect() as c:
        c.execute("UPDATE semantic_suggestions SET status='accepted',note='Keep this review' WHERE id=?",(identifier,))
    factory=Mock(side_effect=AssertionError('Warm startup must not load a model'))
    second=prepare(store,factory)
    assert second.snapshot()['status']=='ready' and second.snapshot()['cache_hit']
    factory.assert_not_called()
    with store.connect() as c:
        assert tuple(c.execute('SELECT status,note FROM semantic_suggestions WHERE id=?',(identifier,)).fetchone())==('accepted','Keep this review')


@pytest.mark.parametrize('field', ['cache_key','revision','model','pipeline'])
def test_stale_cache_metadata_triggers_generation(store,field):
    first=prepare(store);data=json.loads(first.path.read_text());data[field]='stale';first.path.write_text(json.dumps(data))
    factory=Mock(return_value=TinyModel());second=prepare(store,factory)
    assert second.snapshot()['status']=='ready' and not second.snapshot()['cache_hit']
    factory.assert_called_once()


def test_corrupted_cache_and_changed_lexical_ranges_invalidate(store):
    first=prepare(store);docs,lexical,key=inputs(store)
    assert cached(first.path,key,docs)
    first.path.write_text('{interrupted')
    assert not cached(first.path,key,docs)
    second=prepare(store);assert second.snapshot()['status']=='ready'
    with store.connect() as c:c.execute('UPDATE parallels SET active=0')
    assert inputs(store)[2]!=key


def test_reference_and_model_revision_changes_invalidate_key(store,monkeypatch):
    original=inputs(store)[2]
    with store.connect() as c:
        refs=json.loads(c.execute('SELECT refs FROM documents LIMIT 1').fetchone()[0]);refs[0]['label']='2:1'
        c.execute('UPDATE documents SET refs=? WHERE id=(SELECT id FROM documents LIMIT 1)',(json.dumps(refs),))
    updated=inputs(store)[2];assert updated!=original
    monkeypatch.setattr(preparation,'REVISION','new-model-revision')
    assert inputs(store)[2]!=updated


def test_model_failure_keeps_prior_results_and_can_retry(store):
    first=prepare(store);original=first.path.read_bytes()
    docs,lexical,key=inputs(store)
    with store.connect() as c:
        before=[tuple(r) for r in c.execute('SELECT id,status,note FROM semantic_suggestions ORDER BY id')]
    first.model_factory=Mock(side_effect=OSError('Injected download failure'))
    # Mark the cache stale without touching its bytes.
    with store.connect() as c:c.execute('UPDATE parallels SET active=0')
    first.start();first.thread.join(10)
    assert first.snapshot()['status']=='failed' and first.snapshot()['error']
    assert first.path.read_bytes()==original
    with store.connect() as c:
        assert before==[tuple(r) for r in c.execute('SELECT id,status,note FROM semantic_suggestions ORDER BY id')]
    first.model_factory=TinyModel;first.start();first.thread.join(10)
    assert first.snapshot()['status']=='ready'


def test_no_concurrent_preparation_and_readiness_retry_api(store,monkeypatch):
    entered=threading.Event();release=threading.Event()
    def factory():
        entered.set();assert release.wait(10);raise RuntimeError('Injected model failure')
    controller=Preparation(store,factory);controller.start();assert entered.wait(5)
    assert not controller.start()
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        monkeypatch.setattr(main,'preparation',controller)
        assert client.get('/api/health').status_code==200
        assert client.get('/api/ready').status_code==503
        assert client.get('/api/startup').json()['percent'] is None
        assert client.post('/api/analysis').status_code==409
        assert client.post('/api/startup/retry').status_code==409
        release.set();controller.thread.join(10)
        assert client.get('/api/startup').json()['status']=='failed'
        controller.model_factory=TinyModel
        assert client.post('/api/startup/retry').status_code==202
        controller.thread.join(10)
        assert client.get('/api/ready').status_code==200
        assert client.post('/api/startup/retry').status_code==409


def test_encoding_reports_actual_completion_and_rejects_truncation(store):
    docs,lexical,key=inputs(store);updates=[]
    compute(docs,[],key,lambda **change:updates.append(change),TinyModel)
    encoded=[u for u in updates if u['phase']=='encoding']
    assert encoded[-1]['completed']==encoded[-1]['total']==3
    assert encoded[-1]['percent']==85
    assert [u['percent'] for u in encoded]==sorted(u['percent'] for u in encoded)
    class ShortModel(TinyModel):max_seq_length=2
    with pytest.raises(ValueError,match='token limit'):
        compute(docs,[],key,lambda **change:None,ShortModel)


def test_failed_atomic_save_preserves_previous_cache(store,monkeypatch):
    first=prepare(store);original=first.path.read_bytes()
    with store.connect() as c:c.execute('UPDATE parallels SET active=0')
    monkeypatch.setattr(preparation.os,'replace',Mock(side_effect=OSError('Injected disk failure')))
    first.start();first.thread.join(10)
    assert first.snapshot()['status']=='failed'
    assert first.path.read_bytes()==original
    assert not first.path.with_suffix('.tmp').exists()


def test_lexical_rerun_rechecks_semantic_cache_without_reencoding(store):
    factory=Mock(return_value=TinyModel())
    controller=prepare(store,factory);assert controller.snapshot()['status']=='ready'
    original=controller.path.read_bytes()
    assert controller.start(force_lexical=True)
    controller.thread.join(10)
    assert controller.snapshot()['status']=='ready' and controller.snapshot()['cache_hit']
    assert controller.path.read_bytes()==original
    factory.assert_called_once()
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM analysis_runs WHERE status='completed'").fetchone()[0]==2

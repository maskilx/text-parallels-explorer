"""Background first-run preparation with validated cache reuse and observable progress."""
from itertools import combinations
import json
import logging
import math
import os
import threading
import time

from . import semantic
from .engine import Config, VERSION, fingerprint, overlap
from .semantic_model import MODEL, REVISION, THRESHOLD, TOP_K, PIPELINE_VERSION, windows, retrieve


def inputs(store):
    with store.connect() as c:
        docs = {r['id']: dict(r) for r in c.execute('SELECT * FROM documents ORDER BY id')}
        lexical = [dict(r) for r in c.execute('SELECT * FROM parallels WHERE active=1 ORDER BY id')]
    for d in docs.values():
        d['text'] = d['content']
        d['references'] = json.loads(d['refs'])
    specification = dict(
        pipeline=PIPELINE_VERSION, model=MODEL, revision=REVISION,
        threshold=THRESHOLD, top_k=TOP_K, lexical_version=VERSION,
        lexical_config=Config().__dict__,
        corpus={k: d['content_hash'] for k, d in docs.items()},
        references={k: fingerprint(d['refs']) for k, d in docs.items()},
        lexical_ranges=fingerprint(json.dumps([r['id'] for r in lexical])),
    )
    return docs, lexical, fingerprint(json.dumps(specification, sort_keys=True))


def cached(path, key, docs):
    try:
        data = json.loads(path.read_text())
        expected = dict(model=MODEL, revision=REVISION, threshold=THRESHOLD, top_k=TOP_K, lexical_version=VERSION, pipeline=PIPELINE_VERSION)
        if any(data.get(k) != v for k, v in expected.items()):
            return False
        if data.get('cache_key') != key or data.get('generated_by') != 'local-model':
            return False
        if data['corpus_hashes'] != {k: d['content_hash'] for k, d in docs.items()}:
            return False
        semantic.validate(data, docs)
        identities = [m['id'] for m in data['items']]
        if len(identities) != len(set(identities)):
            return False
        return all(math.isfinite(m['score']) and THRESHOLD <= m['score'] <= 1 for m in data['items'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def load_model():
    # Imported only on a cache miss; a warm restart does not load model weights.
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    return SentenceTransformer(MODEL, revision=REVISION, device='cpu')


def compute(docs, lexical, key, update, model_factory=load_model):
    sections = {k: windows(d) for k, d in docs.items()}
    total = sum(len(v) for v in sections.values())
    if not total or any(not v for v in sections.values()):
        raise ValueError('The corpus has no usable verse windows for semantic retrieval')
    update(phase='model', message='Loading the local model. First use downloads public model weights.', percent=None)
    model = model_factory()
    embeddings = {}
    completed = 0
    for doc, rows in sections.items():
        batches = []
        for start in range(0, len(rows), 64):
            texts = [w['text'] for w in rows[start:start + 64]]
            if any(len(model.tokenizer(t, truncation=False)['input_ids']) > model.max_seq_length for t in texts):
                raise ValueError('A verse window exceeds the model token limit; shorten the windows')
            batches.append(model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False))
            completed += len(texts)
            update(phase='encoding', message=f'Encoding passages: {completed:,} of {total:,}',
                   percent=35 + 50 * completed / total, completed=completed, total=total)
        import numpy as np
        embeddings[doc] = np.concatenate(batches)
    suggestions = []
    pairs = list(combinations(sorted(docs), 2))
    for i, (a, b) in enumerate(pairs):
        relevant = [p for p in lexical if p['document_a'] == a and p['document_b'] == b]
        for m in retrieve(sections[a], sections[b], embeddings[a], embeddings[b], THRESHOLD, TOP_K):
            if any(overlap((m['start_a'], m['end_a']), (p['start_a'], p['end_a'])) >= .6 and
                   overlap((m['start_b'], m['end_b']), (p['start_b'], p['end_b'])) >= .6 for p in relevant):
                continue
            identity = f"semantic:{a}:{docs[a]['content_hash']}:{b}:{docs[b]['content_hash']}:{m['start_a']}:{m['end_a']}:{m['start_b']}:{m['end_b']}"
            suggestions.append(dict(id=fingerprint(identity), document_a=a, document_b=b, **m))
        update(phase='matching', message=f'Comparing semantic document pairs: {i + 1} of {len(pairs)}',
               percent=85 + 10 * (i + 1) / len(pairs), completed=i + 1, total=len(pairs))
    return dict(model=MODEL, revision=REVISION, lexical_version=VERSION, threshold=THRESHOLD,
                top_k=TOP_K, corpus_hashes={k: d['content_hash'] for k, d in docs.items()},
                generated_by='local-model', cache_key=key, pipeline=PIPELINE_VERSION, items=suggestions)


class Preparation:
    def __init__(self, store, model_factory=load_model):
        self.store = store
        self.model_factory = model_factory
        self.path = store.path.parent / 'semantic-cache.json'
        self.lock = threading.Lock()
        self.thread = None
        self.state = dict(status='preparing', phase='checking', message='Checking the workspace',
                          percent=0, completed=0, total=0, cache_hit=False, error=None)

    def update(self, **changes):
        with self.lock:
            self.state.update(changes)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, force_lexical=False):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.state.update(status='preparing', phase='checking', message='Checking the workspace',
                              percent=0, completed=0, total=0, cache_hit=False, error=None)
            self.thread = threading.Thread(target=self.run, args=(force_lexical,), daemon=True)
            self.thread.start()
        return True

    def run(self, force_lexical=False):
        started = time.perf_counter()
        try:
            if force_lexical or not self.store.has_results():
                self.update(phase='lexical', message='Finding exact and near matches', percent=5)
                self.store.analyze(on_progress=lambda done, total: self.update(
                    phase='lexical', message=f'Analyzing document pairs: {done} of {total}',
                    percent=5 + 25 * done / total, completed=done, total=total))
            docs, lexical, key = inputs(self.store)
            self.update(phase='cache', message='Checking saved semantic results', percent=35)
            if cached(self.path, key, docs):
                self.update(cache_hit=True)
            else:
                payload = compute(docs, lexical, key, self.update, self.model_factory)
                semantic.validate(payload, docs)
                self.update(phase='saving', message='Saving semantic suggestions', percent=98)
                temporary = self.path.with_suffix('.tmp')
                try:
                    temporary.write_text(json.dumps(payload, indent=2) + '\n')
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            semantic.initialize(self.store, self.path)
            self.update(status='ready', phase='ready', message='Your workspace is ready', percent=100,
                        duration_seconds=round(time.perf_counter() - started, 2))
        except Exception:
            logging.exception('Workspace preparation failed')
            self.update(status='failed', phase='failed', percent=None,
                        message='Workspace preparation could not finish.',
                        error='Check the internet connection and available disk space, then retry. '
                              'Details are recorded in the server log.')

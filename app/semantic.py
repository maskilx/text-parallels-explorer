"""Validate and atomically import locally computed semantic suggestions."""
import json, math
from .engine import fingerprint
from .store import ROOT

SCHEMA='''CREATE TABLE IF NOT EXISTS semantic_suggestions (
 id TEXT PRIMARY KEY, document_a TEXT NOT NULL REFERENCES documents(id),
 document_b TEXT NOT NULL REFERENCES documents(id), score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
 payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
 CHECK(document_a < document_b)
);'''

def initialize(store,path=None):
    path=path or ROOT/'app'/'assets'/'semantic.json'
    with store.connect() as c:
        c.executescript(SCHEMA)
        if not path.exists():
            c.execute('UPDATE semantic_suggestions SET active=0')
            return
        data=json.loads(path.read_text())
        docs={r['id']:dict(r) for r in c.execute('SELECT * FROM documents')}
        if data['corpus_hashes']!={k:d['content_hash'] for k,d in docs.items()}:
            c.execute('UPDATE semantic_suggestions SET active=0')
            return
        validate(data,docs)
        c.execute('UPDATE semantic_suggestions SET active=0')
        for m in data['items']:
            payload=dict(m,model=data['model'],model_revision=data['revision'],threshold=data['threshold'],lexical_version=data.get('lexical_version','lexical-1.0.0'))
            c.execute('''INSERT INTO semantic_suggestions(id,document_a,document_b,score,payload) VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,score=excluded.score,active=1''',
                (m['id'],m['document_a'],m['document_b'],m['score'],json.dumps(payload)))


def validate(data,docs):
    # Validate the complete batch before publishing; preserve notes on re-import.
    seen=set()
    for m in data['items']:
        if m['id'] in seen: raise ValueError('Duplicate semantic cache identity')
        seen.add(m['id'])
        if not math.isfinite(m['score']) or not 0<=m['score']<=1: raise ValueError('Invalid semantic cache score')
        if m['document_a']>=m['document_b']:raise ValueError('Semantic cache pair is not canonical')
        for side in ('a','b'):
            content=docs[m['document_'+side]]['content'];start,end=m['start_'+side],m['end_'+side]
            if not 0<=start<end<=len(content) or content[start:end]!=m['text_'+side]:
                raise ValueError('Semantic cache source offsets do not match the corpus')
        a,b=m['document_a'],m['document_b']
        identity=f"semantic:{a}:{docs[a]['content_hash']}:{b}:{docs[b]['content_hash']}:{m['start_a']}:{m['end_a']}:{m['start_b']}:{m['end_b']}"
        if fingerprint(identity)!=m['id']:raise ValueError('Semantic cache identity mismatch')


def initialize_schema(store):
    with store.connect() as c:
        c.executescript(SCHEMA)

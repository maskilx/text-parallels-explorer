"""SQLite persistence: atomic analyses, stable passage identities, durable reviews."""
from contextlib import contextmanager
from itertools import combinations
from pathlib import Path
import json, os, sqlite3, threading, time
from datetime import datetime, timezone
from .engine import Config, VERSION, detect_pair, fingerprint, tokenize

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, edition TEXT NOT NULL,
 source_url TEXT NOT NULL, license TEXT NOT NULL, content TEXT NOT NULL,
 content_hash TEXT NOT NULL, refs TEXT NOT NULL, word_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
 algorithm_version TEXT NOT NULL, config TEXT NOT NULL,
 duration_seconds REAL, match_count INTEGER, pairs TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS parallels (
 id TEXT PRIMARY KEY, document_a TEXT NOT NULL REFERENCES documents(id),
 document_b TEXT NOT NULL REFERENCES documents(id),
 start_a INTEGER NOT NULL, end_a INTEGER NOT NULL, start_b INTEGER NOT NULL, end_b INTEGER NOT NULL,
 score REAL NOT NULL CHECK(score BETWEEN 0 AND 1), kind TEXT NOT NULL CHECK(kind IN ('exact','near')),
 words_a INTEGER NOT NULL, words_b INTEGER NOT NULL, edit_distance INTEGER NOT NULL,
 raw_exact INTEGER NOT NULL, method TEXT NOT NULL, alignment_score REAL, seed_words INTEGER NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, run_id INTEGER NOT NULL REFERENCES analysis_runs(id),
 CHECK(document_a < document_b), CHECK(start_a>=0 AND end_a>start_a), CHECK(start_b>=0 AND end_b>start_b),
 UNIQUE(document_a,document_b,start_a,end_a,start_b,end_b)
);
CREATE TABLE IF NOT EXISTS reviews (
 parallel_id TEXT PRIMARY KEY REFERENCES parallels(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS parallels_active_score ON parallels(active,score DESC);
CREATE INDEX IF NOT EXISTS parallels_pair ON parallels(document_a,document_b);
CREATE INDEX IF NOT EXISTS reviews_status ON reviews(status);
'''

def now(): return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self,path=None,corpus=None):
        self.path=Path(path or os.environ.get('DATABASE_PATH',str(ROOT/'data'/'explorer.sqlite')))
        self.corpus=Path(corpus or ROOT/'corpus')
        self.lock=threading.Lock()
        self.progress={'running':False,'completed_pairs':0,'total_pairs':0}
        self.path.parent.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()

    def initialize(self):
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
            # A killed process cannot leave the UI in a permanently running state.
            c.execute("UPDATE analysis_runs SET status='failed',error='Process stopped before analysis completed',finished_at=? WHERE status='running'",(now(),))
            manifest=json.loads((self.corpus/'manifest.json').read_text())
            for d in manifest:
                text=(self.corpus/d['file']).read_text(encoding='utf-8')
                if fingerprint(text)!=d['sha256']: raise ValueError(f"Corpus checksum mismatch: {d['id']}")
                existing=c.execute('SELECT content_hash FROM documents WHERE id=?',(d['id'],)).fetchone()
                if existing and existing['content_hash']!=d['sha256']:
                    raise ValueError('Corpus changed: use a new database to preserve existing review coordinates.')
                refs=(self.corpus/d['refs']).read_text()
                c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                          (d['id'],d['title'],d['edition'],d['source_url'],d['license'],text,d['sha256'],refs,len(tokenize(text))))

    def has_results(self):
        with self.connect() as c: return bool(c.execute("SELECT 1 FROM analysis_runs WHERE status='completed' AND algorithm_version=? LIMIT 1",(VERSION,)).fetchone())

    def analyze(self,config=Config(),claimed=False):
        if not claimed and not self.lock.acquire(blocking=False): raise RuntimeError('An analysis is already running')
        started=time.perf_counter(); run_id=None
        self.progress={'running':True,'completed_pairs':0,'total_pairs':0}
        try:
            with self.connect() as c:
                docs=[dict(d) for d in c.execute('SELECT * FROM documents ORDER BY id')]
                run_id=c.execute("INSERT INTO analysis_runs(started_at,status,algorithm_version,config) VALUES(?,'running',?,?)",
                                 (now(),VERSION,json.dumps(config.__dict__,sort_keys=True))).lastrowid
            pairs=list(combinations(docs,2)); self.progress['total_pairs']=len(pairs)
            output=[]; pair_stats=[]
            for a,b in pairs:
                stats={'document_a':a['id'],'document_b':b['id']}
                tick=time.perf_counter()
                for m in detect_pair(a['content'],b['content'],config,stats):
                    identity=f"{a['id']}:{a['content_hash']}:{b['id']}:{b['content_hash']}:{m['start_a']}:{m['end_a']}:{m['start_b']}:{m['end_b']}"
                    output.append(dict(id=fingerprint(identity),document_a=a['id'],document_b=b['id'],run_id=run_id,**m))
                stats['duration_seconds']=round(time.perf_counter()-tick,3)
                pair_stats.append(stats); self.progress['completed_pairs']+=1
            with self.connect() as c:
                # One transaction publishes the complete new result set. Reviews are untouched.
                c.execute('UPDATE parallels SET active=0')
                for m in output:
                    keys=list(m)+['active']; values=list(m.values())+[1]
                    update=','.join(f'{k}=excluded.{k}' for k in keys if k!='id')
                    c.execute(f"INSERT INTO parallels({','.join(keys)}) VALUES({','.join('?' for _ in keys)}) ON CONFLICT(id) DO UPDATE SET {update}",values)
                    c.execute("INSERT INTO reviews(parallel_id,status,note,updated_at) VALUES(?,'pending','',?) ON CONFLICT(parallel_id) DO NOTHING",(m['id'],now()))
                c.execute("UPDATE analysis_runs SET status='completed',finished_at=?,duration_seconds=?,match_count=?,pairs=? WHERE id=?",
                          (now(),round(time.perf_counter()-started,3),len(output),json.dumps(pair_stats),run_id))
            return dict(run_id=run_id,matches=len(output),pairs=pair_stats,duration_seconds=round(time.perf_counter()-started,3))
        except Exception:
            if run_id:
                with self.connect() as c:
                    c.execute("UPDATE analysis_runs SET status='failed',finished_at=?,error='Analysis failed; previous results were preserved' WHERE id=?",(now(),run_id))
            raise
        finally:
            self.progress['running']=False
            self.lock.release()

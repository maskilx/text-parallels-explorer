from contextlib import asynccontextmanager
import csv, io, json, logging, threading
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .store import Store, now, ROOT
from .engine import Config, VERSION, diff_blocks
from . import semantic

store=Store()

@asynccontextmanager
async def lifespan(app):
    store.initialize()
    semantic.initialize(store)
    if not store.has_results(): store.analyze()
    yield

app=FastAPI(title='Text Parallels Explorer',version='1.0.0',lifespan=lifespan)

@app.get('/api/health')
def health(): return {'status':'ok','algorithm':VERSION}

@app.get('/api/documents')
def documents():
    with store.connect() as c:
        return [dict(d) for d in c.execute('SELECT id,title,edition,source_url,license,word_count,length(content) AS characters FROM documents ORDER BY title')]

@app.get('/api/stats')
def stats():
    with store.connect() as c:
        counts=dict(c.execute("SELECT count(*) AS total,sum(kind='exact') AS exact,sum(kind='near') AS near,sum(status='accepted') AS accepted,sum(status='rejected') AS rejected,sum(status='pending') AS pending FROM parallels p JOIN reviews r ON r.parallel_id=p.id WHERE active=1").fetchone())
        run=c.execute('SELECT * FROM analysis_runs ORDER BY id DESC LIMIT 1').fetchone()
        if run:
            run=dict(run); run['config']=json.loads(run['config']); run['pairs']=json.loads(run['pairs'] or '[]')
        return {'counts':{k:v or 0 for k,v in counts.items()},'run':run,'progress':store.progress,'algorithm':VERSION}

def query_results(document='',pair='',kind='',status='',min_score=0.,min_words=0,q='',sort='score',limit=50,offset=0):
    where=['p.active=1']; args=[]
    if document: where.append('(p.document_a=? OR p.document_b=?)'); args += [document,document]
    if pair:
        ids=sorted(pair.split(','))
        if len(ids)!=2 or ids[0]==ids[1]: raise HTTPException(422,'Pair must contain two different document IDs')
        where.append('p.document_a=? AND p.document_b=?'); args+=ids
    if kind: where.append('p.kind=?'); args.append(kind)
    if status: where.append('r.status=?'); args.append(status)
    where.append('p.score>=? AND min(p.words_a,p.words_b)>=?'); args += [min_score,min_words]
    if q:
        escaped=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        where.append("(substr(a.content,p.start_a+1,p.end_a-p.start_a) LIKE ? ESCAPE '\\' OR substr(b.content,p.start_b+1,p.end_b-p.start_b) LIKE ? ESCAPE '\\')")
        args += ['%'+escaped+'%']*2
    order={'score':'p.score DESC,min(p.words_a,p.words_b) DESC,p.id','length':'min(p.words_a,p.words_b) DESC,p.score DESC,p.id','position':'p.document_a,p.start_a,p.document_b,p.start_b,p.id'}[sort]
    base=' FROM parallels p JOIN reviews r ON r.parallel_id=p.id JOIN documents a ON a.id=p.document_a JOIN documents b ON b.id=p.document_b WHERE '+' AND '.join(where)
    with store.connect() as c:
        total=c.execute('SELECT count(*)'+base,args).fetchone()[0]
        rows=c.execute('SELECT p.*,r.status,r.note,r.updated_at,a.title AS title_a,b.title AS title_b,substr(a.content,p.start_a+1,min(p.end_a-p.start_a,180)) AS excerpt_a,substr(b.content,p.start_b+1,min(p.end_b-p.start_b,180)) AS excerpt_b'+base+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[limit,offset])
        return {'items':[dict(r) for r in rows],'total':total,'limit':limit,'offset':offset}

@app.get('/api/parallels')
def parallels(document:str='',pair:str='',kind:Literal['','exact','near']='',status:Literal['','pending','accepted','rejected']='',
              min_score:float=Query(0,ge=0,le=1),min_words:int=Query(0,ge=0),q:str=Query('',max_length=300),
              sort:Literal['score','length','position']='score',limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0)):
    return query_results(document,pair,kind,status,min_score,min_words,q,sort,limit,offset)

@app.get('/api/parallels/{parallel_id}')
def detail(parallel_id:str):
    with store.connect() as c:
        row=c.execute('SELECT p.*,r.status,r.note,r.updated_at FROM parallels p JOIN reviews r ON r.parallel_id=p.id WHERE p.id=?',(parallel_id,)).fetchone()
        if not row: raise HTTPException(404,'Parallel not found')
        m=dict(row); passages=[]
        for side in ('a','b'):
            d=dict(c.execute('SELECT * FROM documents WHERE id=?',(m['document_'+side],)).fetchone())
            start,end=m['start_'+side],m['end_'+side]
            lo,hi=max(0,start-180),min(len(d['content']),end+180)
            refs=[r['label'] for r in json.loads(d['refs']) if r['start']<end and r['end']>start]
            passages.append(dict(title=d['title'],document_id=d['id'],source_url=d['source_url'],
                text=d['content'][start:end],before=d['content'][lo:start],after=d['content'][end:hi],
                start=start,end=end,reference=' – '.join([refs[0],refs[-1]]) if len(refs)>1 else (refs[0] if refs else '')))
        m['passages']=passages
        m['diff']=diff_blocks(passages[0]['text'],passages[1]['text'])
        return m

class Review(BaseModel):
    status:Literal['pending','accepted','rejected']
    note:str=Field('',max_length=5000)

@app.patch('/api/parallels/{parallel_id}/review')
def review(parallel_id:str,body:Review):
    with store.connect() as c:
        if not c.execute('SELECT 1 FROM parallels WHERE id=?',(parallel_id,)).fetchone(): raise HTTPException(404,'Parallel not found')
        c.execute('UPDATE reviews SET status=?,note=?,updated_at=? WHERE parallel_id=?',(body.status,body.note,now(),parallel_id))
    return {'status':body.status,'note':body.note}

@app.get('/api/semantic')
def semantic_suggestions(pair:str='',status:Literal['','pending','accepted','rejected']='',
                         min_score:float=Query(.6,ge=0,le=1),q:str=Query('',max_length=300),
                         limit:int=Query(24,ge=1,le=100),offset:int=Query(0,ge=0)):
    where=['active=1','score>=?'];args=[min_score]
    if pair:
        ids=sorted(pair.split(','))
        if len(ids)!=2 or ids[0]==ids[1]:raise HTTPException(422,'Pair must contain two different document IDs')
        where+=['document_a=?','document_b=?'];args+=ids
    if status:where.append('status=?');args.append(status)
    if q:
        # Literal substring search avoids SQL wildcard surprises.
        where.append("(instr(lower(json_extract(payload,'$.text_a')),lower(?))>0 OR instr(lower(json_extract(payload,'$.text_b')),lower(?))>0)");args += [q,q]
    sql=' FROM semantic_suggestions WHERE '+' AND '.join(where)
    with store.connect() as c:
        total=c.execute('SELECT count(*)'+sql,args).fetchone()[0]
        rows=c.execute('SELECT *'+sql+' ORDER BY score DESC,id LIMIT ? OFFSET ?',args+[limit,offset])
        items=[dict(json.loads(r['payload']),status=r['status'],note=r['note']) for r in rows]
    return dict(items=items,total=total,limit=limit,offset=offset)

@app.patch('/api/semantic/{suggestion_id}/review')
def semantic_review(suggestion_id:str,body:Review):
    with store.connect() as c:
        if not c.execute('SELECT 1 FROM semantic_suggestions WHERE id=? AND active=1',(suggestion_id,)).fetchone():
            raise HTTPException(404,'Semantic suggestion not found')
        c.execute('UPDATE semantic_suggestions SET status=?,note=? WHERE id=?',(body.status,body.note,suggestion_id))
    return dict(status=body.status,note=body.note)

@app.post('/api/analysis',status_code=202)
def analyze():
    if not store.lock.acquire(blocking=False): raise HTTPException(409,'An analysis is already running')
    store.progress={'running':True,'completed_pairs':0,'total_pairs':3}
    def work():
        try: store.analyze(claimed=True)
        except Exception: logging.exception('Analysis failed')
    threading.Thread(target=work,daemon=True).start()
    return {'status':'running'}

@app.get('/api/export.csv')
def export(document:str='',pair:str='',kind:Literal['','exact','near']='',status:Literal['','pending','accepted','rejected']='',
           min_score:float=Query(0,ge=0,le=1),min_words:int=Query(0,ge=0),q:str=Query('',max_length=300),sort:Literal['score','length','position']='score'):
    rows=query_results(document,pair,kind,status,min_score,min_words,q,sort,100000,0)['items']
    keys=['id','title_a','title_b','start_a','end_a','start_b','end_b','kind','score','words_a','words_b','status','note','excerpt_a','excerpt_b']
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=keys,extrasaction='ignore'); writer.writeheader()
    for row in rows:
        # Avoid spreadsheet formula execution when researcher notes are exported.
        safe={k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="parallels.csv"'})

DIST=ROOT/'frontend'/'dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
    @app.get('/')
    def index(): return FileResponse(DIST/'index.html')

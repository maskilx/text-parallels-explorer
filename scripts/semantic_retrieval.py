"""Reproducible local semantic retrieval study; no vector database or paid API."""
import argparse, hashlib, json, sys, time
from itertools import combinations
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate import load_docs, GOLD, span, coverage
from scripts.embedding_experiment import SEMANTIC, measure
from app.engine import VERSION, tokenize, detect_pair, overlap

# Written before running either model. Calibration and challenge use different topics.
CHALLENGE=[
 ('paraphrase','The farmer sold his last cow to pay the rent.','To cover the cost of his home, the agricultural worker traded away his only remaining cattle.',True),
 ('paraphrase','Passengers waited at the station because the train was delayed.','A late railway service left travelers standing on the platform.',True),
 ('paraphrase','The librarian locked the doors after every visitor had left.','Once the building was empty, the library worker secured its entrances.',True),
 ('paraphrase','The fire forced the families to leave their homes.','Residents had to evacuate their houses because of the blaze.',True),
 ('paraphrase','The traveler could not buy food because he had lost his purse.','Having misplaced his wallet, the visitor had no money for a meal.',True),
 ('paraphrase','The judge released the prisoner because there was no evidence.','Without proof against the accused, the court ordered him to go free.',True),
 ('same-topic','The farmer sold his last cow to pay the rent.','The farmer bought a cow and built a larger barn.',False),
 ('same-topic','Passengers waited at the station because the train was delayed.','Passengers bought train tickets online for a journey next week.',False),
 ('same-topic','The librarian locked the doors after every visitor had left.','The librarian ordered new books for the children.',False),
 ('same-topic','The fire forced the families to leave their homes.','The families lit a fire to cook dinner at their campsite.',False),
 ('unrelated','The judge released the prisoner because there was no evidence.','A gardener planted roses beside a wooden fence.',False),
 ('unrelated','The traveler could not buy food because he had lost his purse.','The telescope revealed a distant galaxy.',False),
 # Hard negatives are reported separately: related wording may be a valid text parallel.
 ('contradiction','The judge released the prisoner because there was no evidence.','The judge did not release the prisoner despite the lack of evidence.',False),
 ('contradiction','The fire forced the families to leave their homes.','The families stayed in their homes despite the fire.',False),
 ('role-reversal','The farmer sold a cow to the merchant.','The merchant sold a cow to the farmer.',False),
 ('role-reversal','The teacher praised the student.','The student praised the teacher.',False),
]
MODELS=['sentence-transformers/all-MiniLM-L6-v2','sentence-transformers/paraphrase-MiniLM-L6-v2']

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
            s=float(scores[i,j])
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

def main():
    from sentence_transformers import SentenceTransformer
    from huggingface_hub import model_info
    parser=argparse.ArgumentParser();parser.add_argument('--models',nargs='+',default=MODELS);parser.add_argument('--export',action='store_true');args=parser.parse_args()
    docs=load_docs();ws={k:windows(d) for k,d in docs.items()};reports=[]
    lexical={(a,b):detect_pair(docs[a]['text'],docs[b]['text']) for a,b in combinations(sorted(docs),2)}
    for name in args.models:
        revision={'sentence-transformers/all-MiniLM-L6-v2':'1110a243fdf4706b3f48f1d95db1a4f5529b4d41','sentence-transformers/paraphrase-MiniLM-L6-v2':'c9a2bfebc254878aee8c3aca9e6844d5bbb102d1'}.get(name) or model_info(name).sha;tick=time.perf_counter()
        model=SentenceTransformer(name,revision=revision,device='cpu')
        def pair_scores(rows):
            x=model.encode([r[1] for r in rows],normalize_embeddings=True,show_progress_bar=False)
            y=model.encode([r[2] for r in rows],normalize_embeddings=True,show_progress_bar=False)
            return (x*y).sum(axis=1).tolist()
        cal=pair_scores(SEMANTIC);labels=[r[3] for r in SEMANTIC]
        # Highest recall with zero calibration false positives; prefer lower threshold in ties.
        candidates=[measure(labels,cal,t/100) for t in range(40,96)]
        chosen=max((r for r in candidates if r['fp']==0),key=lambda r:(r['tp'],-r['threshold']))
        threshold=chosen['threshold'];scores=pair_scores(CHALLENGE)
        rows=[dict(kind=r[0],a=r[1],b=r[2],label=r[3],score=s,detected=s>=threshold) for r,s in zip(CHALLENGE,scores)]
        # Encode corpus windows only once per model; no known-passage boundary oracle.
        embeddings={k:model.encode([w['text'] for w in v],normalize_embeddings=True,batch_size=64,show_progress_bar=False) for k,v in ws.items()}
        truncation={k:sum(len(model.tokenizer(w['text'],truncation=False)['input_ids'])>model.max_seq_length for w in v) for k,v in ws.items()}
        if any(truncation.values()):raise ValueError('Shorten verse windows: model token limit would truncate source text')
        results={};pairs=[]
        for a,b in combinations(sorted(docs),2):
            found=retrieve(ws[a],ws[b],embeddings[a],embeddings[b],threshold)
            for m in found:
                m['covered_by_lexical']=any(overlap((m['start_a'],m['end_a']),(p['start_a'],p['end_a']))>=.6 and overlap((m['start_b'],m['end_b']),(p['start_b'],p['end_b']))>=.6 for p in lexical[(a,b)])
                assert docs[a]['text'][m['start_a']:m['end_a']]==m['text_a']
                assert docs[b]['text'][m['start_b']:m['end_b']]==m['text_b']
            results[(a,b)]=found
            pairs.append(dict(a=a,b=b,total=len(found),additional=sum(not m['covered_by_lexical'] for m in found),examples=[m for m in found if not m['covered_by_lexical']][:20]))
        gold=[]
        for a,sa,ea,b,sb,eb,title in GOLD:
            ra,rb=span(docs[a],sa,ea),span(docs[b],sb,eb)
            if a>b:a,b=b,a;ra,rb=rb,ra
            hit=max((min(coverage([m['start_a'],m['end_a']],ra),coverage([m['start_b'],m['end_b']],rb)) for m in results[(a,b)]),default=0)
            gold.append(dict(name=title,detected=hit>=.4,coverage=hit))
        ordinary=rows[:12];hard=rows[12:]
        report=dict(model=name,revision=revision,license='Apache-2.0',dimensions=int(next(iter(embeddings.values())).shape[1]),max_tokens=model.max_seq_length,
            threshold=threshold,calibration=chosen,challenge=measure([r['label'] for r in ordinary],[r['score'] for r in ordinary],threshold),
            threshold_sensitivity=[measure([r['label'] for r in rows[:12]],[r['score'] for r in rows[:12]],t) for t in [.5,.55,.6,.65,.7,.8]],hard_negative_sensitivity=[measure([r['label'] for r in rows[12:]],[r['score'] for r in rows[12:]],t) for t in [.5,.55,.6,.65,.7,.8]],hard_negatives=measure([r['label'] for r in hard],[r['score'] for r in hard],threshold),challenge_rows=rows,
            windows={k:len(v) for k,v in ws.items()},truncated_windows=truncation,pairs=pairs,gold=gold,
            gold_detected=sum(r['detected'] for r in gold),duration_seconds=round(time.perf_counter()-tick,2))
        if args.export and name=='sentence-transformers/paraphrase-MiniLM-L6-v2':
            suggestions=[]
            for a,b in combinations(sorted(docs),2):
                for m in retrieve(ws[a],ws[b],embeddings[a],embeddings[b],.65,top_k=1):
                    if any(overlap((m['start_a'],m['end_a']),(p['start_a'],p['end_a']))>=.6 and overlap((m['start_b'],m['end_b']),(p['start_b'],p['end_b']))>=.6 for p in lexical[(a,b)]):continue
                    identity=f"semantic:{a}:{docs[a]['sha256']}:{b}:{docs[b]['sha256']}:{m['start_a']}:{m['end_a']}:{m['start_b']}:{m['end_b']}"
                    suggestions.append(dict(id=hashlib.sha256(identity.encode()).hexdigest(),document_a=a,document_b=b,**m))
            destination=ROOT/'app'/'assets';destination.mkdir(exist_ok=True)
            payload=dict(model=name,revision=revision,lexical_version=VERSION,threshold=.65,top_k=1,corpus_hashes={k:d['sha256'] for k,d in docs.items()},items=suggestions)
            (destination/'semantic.json').write_text(json.dumps(payload,indent=2)+'\n')
            print('Exported semantic suggestions:',len(suggestions),flush=True)
        reports.append(report);print(json.dumps({k:v for k,v in report.items() if k not in ['pairs','gold','challenge_rows']},indent=2),flush=True)
    output=dict(models=reports,corpus_hashes={k:hashlib.sha256(d['text'].encode()).hexdigest() for k,d in docs.items()},
        caveats=['Author-written 8-pair calibration and 16-pair challenge are small development diagnostics, not an external benchmark.',
                 'Challenge labels were fixed before the first run; selecting a model after viewing them makes them development data for subsequent changes.',
                 'Contradictions and role reversals test same-event meaning, not whether wording itself constitutes a text parallel.',
                 'Known corpus passages were previously used for lexical tuning; corpus coverage is not independent recall.',
                 'Unannotated additional candidates require human review; candidate count is not precision.',
                 'Verse windows provide coarse boundaries, not an alignment of corresponding semantic phrases.'])
    (ROOT/'docs'/'semantic-retrieval-results.json').write_text(json.dumps(output,indent=2)+'\n')
if __name__=='__main__':main()

"""Compare contiguous-only retrieval with bounded skip seeds on fixed fixtures."""
import json, random, sys, time
from dataclasses import replace
from itertools import combinations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.engine import Config,VERSION,detect_pair,tokenize,index_ngrams
from scripts.evaluate import load_docs,make_synthetic,evaluate_synthetic,GOLD,span,coverage


def challenge(docs):
    rng=random.Random(9173);tokens=tokenize(docs['luke']['text']);cases=[]
    for i in range(12):
        start=rng.randrange(100,len(tokens)-100)
        original=[t.value for t in tokens[start:start+48]]
        a=' '.join(original)
        for kind in ('insertion','deletion','substitution'):
            if kind=='insertion':
                changed=[]
                for j,w in enumerate(original):
                    changed.append(w)
                    if j%2==1 and j<len(original)-1:changed.append('additional')
            elif kind=='deletion':changed=[w for j,w in enumerate(original) if j%3!=2]
            else:changed=[w if j%3!=2 else f'changed{j}' for j,w in enumerate(original)]
            b=' '.join(changed)
            shared=bool(index_ngrams(tokenize(a),3).keys() & index_ngrams(tokenize(b),3).keys())
            cases.append(dict(id=f'{i}-{kind}',kind=kind,label=True,a=a,b=b,expected_a=[0,len(a)],expected_b=[0,len(b)],has_contiguous_seed=shared))
    for i in range(12):
        # Natural-token negatives with the same word bag but reversed unique order.
        a=' '.join(f'word{i}number{j}' for j in range(48))
        cases.append(dict(id=f'reversed-{i}',kind='reversed-order',label=False,a=a,b=' '.join(reversed(a.split()))))
    return cases


def main():
    docs=load_docs();cases=challenge(docs);legacy=make_synthetic(docs)
    variants={'contiguous_only':replace(Config(),use_skip_seeds=False),'with_skip_seeds':Config()}
    results={};full={}
    for name,config in variants.items():
        tick=time.perf_counter();pairs=[];matches={}
        for a,b in combinations(sorted(docs),2):
            stats=dict(document_a=a,document_b=b);pt=time.perf_counter()
            found=detect_pair(docs[a]['text'],docs[b]['text'],config,stats)
            stats['duration_seconds']=round(time.perf_counter()-pt,3);pairs.append(stats);matches[(a,b)]=found
            ranges=[]
            for m in found:
                for side,doc in [('a',a),('b',b)]:
                    start,end=m['start_'+side],m['end_'+side]
                    assert 0<=start<end<=len(docs[doc]['text'])
                    assert len(tokenize(docs[doc]['text'][start:end]))==m['words_'+side]
                if m['kind']=='exact':
                    assert [t.value for t in tokenize(docs[a]['text'][m['start_a']:m['end_a']])]==[t.value for t in tokenize(docs[b]['text'][m['start_b']:m['end_b']])]
                ranges.append(tuple(m[k] for k in ['start_a','end_a','start_b','end_b']))
            assert len(ranges)==len(set(ranges))
        duration=time.perf_counter()-tick;gold=[]
        for a,sa,ea,b,sb,eb,title in GOLD:
            ra,rb=span(docs[a],sa,ea),span(docs[b],sb,eb)
            if a>b:a,b=b,a;ra,rb=rb,ra
            best=max((min(coverage([m['start_a'],m['end_a']],ra),coverage([m['start_b'],m['end_b']],rb)) for m in matches[(a,b)]),default=0)
            gold.append(dict(name=title,detected=best>=.4,coverage=best))
        all_matches=[m for rows in matches.values() for m in rows]
        results[name]=dict(config=config.__dict__,skip_challenge=evaluate_synthetic(cases,config),original_synthetic=evaluate_synthetic(legacy,config),
            corpus=dict(total=len(all_matches),exact=sum(m['kind']=='exact' for m in all_matches),near=sum(m['kind']=='near' for m in all_matches),duration_seconds=round(duration,3),pairs=pairs,gold=gold,gold_detected=sum(g['detected'] for g in gold),offsets_verified=True,duplicate_ranges=0))
        full[name]=matches
        print(name,json.dumps(results[name]),flush=True)
    added=[];retained=lost=0
    for pair,old in full['contiguous_only'].items():
        new=full['with_skip_seeds'][pair];old_ranges={tuple(m[k] for k in ['start_a','end_a','start_b','end_b']) for m in old}
        new_ranges={tuple(m[k] for k in ['start_a','end_a','start_b','end_b']) for m in new}
        retained+=len(old_ranges & new_ranges);lost+=len(old_ranges-new_ranges)
        for m in new:
            if tuple(m[k] for k in ['start_a','end_a','start_b','end_b']) not in old_ranges:
                a,b=pair;added.append(dict(document_a=a,document_b=b,**m,text_a=docs[a]['text'][m['start_a']:m['end_a']],text_b=docs[b]['text'][m['start_b']:m['end_b']]))
    report=dict(algorithm=VERSION,variants=results,exact_range_retention=dict(retained=retained,replaced_or_suppressed=lost),
        contiguous_seedless_challenge_count=sum(not c.get('has_contiguous_seed',True) for c in cases if c['label']),
        additional_or_changed_results=added,caveats=['Deterministic artificial edits are development stress tests, not estimates of corpus precision.',
        'Known passages were previously used for threshold tuning; coverage is not held-out recall.',
        'Longer new matches may suppress older shorter ranges; range retention is not passage recall.',
        'Skip anchors improve retrieval only. They do not bypass minimum lengths, lexical similarity, frequency guards, or local alignment limitations.'])
    (ROOT/'docs'/'skip-seed-evaluation.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'docs'/'skip-seed-cases.json').write_text(json.dumps(cases,indent=2)+'\n')
if __name__=='__main__':main()

"""Deterministic stress tests and real-corpus coverage audit; no global precision claim."""
from pathlib import Path
import json,random,statistics,sys,time
from dataclasses import replace
from itertools import combinations
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.engine import VERSION,Config,detect_pair,tokenize

def load_docs():
    return {d['id']:dict(d,text=(ROOT/'corpus'/d['file']).read_text(),references=json.loads((ROOT/'corpus'/d['refs']).read_text())) for d in json.loads((ROOT/'corpus'/'manifest.json').read_text())}

def span(doc,first,last):
    refs=doc['references'];lo=next(i for i,r in enumerate(refs) if r['label']==first);hi=next(i for i,r in enumerate(refs) if r['label']==last)
    return [refs[lo]['start'],refs[hi]['end']]

def coverage(found,expected):return max(0,min(found[1],expected[1])-max(found[0],expected[0]))/(expected[1]-expected[0])
def iou(a,b):return max(0,min(a[1],b[1])-max(a[0],b[0]))/(max(a[1],b[1])-min(a[0],b[0]))

def make_synthetic(docs):
    rng=random.Random(4721);source=docs['luke']['text'];tokens=tokenize(source);cases=[]
    for i in range(24):
        start=rng.randrange(100,len(tokens)-150);a=source[tokens[start].start:tokens[start+47].end]
        for kind in ['exact','case-punctuation','substitution','insertion','deletion','mixed']:
            words=[t.value for t in tokenize(a)]
            if kind=='exact':b=a
            elif kind=='case-punctuation':b=' , '.join(words).upper()
            elif kind=='substitution':
                for j in [10,22,34]:words[j]=f'changed{j}'
                b=' '.join(words)
            elif kind=='insertion':words[18:18]=['unexpected','additional','words'];b=' '.join(words)
            elif kind=='deletion':del words[18:21];b=' '.join(words)
            else:
                words[10]='altered';words[24]='modified';del words[18:20];words[30:30]=['added'];b=' '.join(words)
            pa='🌿 Unrelated preface alpha. ';pb='🌞 Different preface beta. '
            cases.append(dict(id=f'{i}-{kind}',kind=kind,label=True,a=pa+a+'\nDistinct suffix omega.',b=pb+b+'\nAlternative suffix delta.',expected_a=[len(pa),len(pa)+len(a)],expected_b=[len(pb),len(pb)+len(b)]))
    for i in range(24):cases.append(dict(id=f'negative-{i}',kind='disjoint-vocabulary',label=False,a=' '.join(f'alpha{i}word{j}' for j in range(48)),b=' '.join(f'beta{i}word{j}' for j in range(48))))
    for i,(a,b) in enumerate([
        ('The captain guided the small ship through the narrow harbor while the tired crew prepared for a long journey across the sea.','A sailor repaired a damaged boat near the coast as other workers waited for the next fishing expedition to begin in the morning.'),
        ('The king entered the large city before sunrise and ordered his soldiers to guard the northern gate throughout the entire night.','A monarch arrived in town at dawn, instructing troops to protect its north entrance until morning.')]):
        cases.append(dict(id=f'topic-{i}',kind='same-topic-different-wording',label=False,a=a,b=b))
    for rate in [.1,.2,.3,.4]:
        for i in range(12):
            start=rng.randrange(100,len(tokens)-150);a=source[tokens[start].start:tokens[start+59].end]
            words=[t.value for t in tokenize(a)]
            for j in rng.sample(range(3,len(words)-3),round(len(words)*rate)):words[j]=f'novel{j}'
            b=' '.join(words);cases.append(dict(id=f'noise-{rate}-{i}',kind=f'noise-{rate:.0%}',label=True,a=a,b=b,expected_a=[0,len(a)],expected_b=[0,len(b)]))
    return cases

def evaluate_synthetic(cases,config):
    tp=fp=fn=tn=0;boundaries=[];by_type={};misses=[];tick=time.perf_counter()
    for case in cases:
        matches=detect_pair(case['a'],case['b'],config)
        if case['label']:
            best=max((min(iou([m['start_a'],m['end_a']],case['expected_a']),iou([m['start_b'],m['end_b']],case['expected_b'])) for m in matches),default=0)
            hit=best>=.6;tp+=hit;fn+=not hit;boundaries.append(best)
            group=by_type.setdefault(case['kind'],{'detected':0,'total':0});group['detected']+=hit;group['total']+=1
            if not hit:misses.append(case['id'])
        else:fp+=bool(matches);tn+=not bool(matches)
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,precision=tp/max(1,tp+fp),recall=tp/max(1,tp+fn),mean_boundary_iou=statistics.mean(boundaries),by_type=by_type,misses=misses,duration_seconds=round(time.perf_counter()-tick,3))

GOLD=[
 ('matthew','3:3','3:3','mark','1:3','1:3','Voice in the wilderness'),
 ('matthew','3:11','3:11','luke','3:16','3:16','Baptism with water'),
 ('matthew','4:4','4:4','luke','4:4','4:4','Bread alone'),
 ('matthew','4:7','4:7','luke','4:12','4:12','Do not test'),
 ('matthew','6:24','6:24','luke','16:13','16:13','Two masters'),
 ('matthew','7:7','7:8','luke','11:9','11:10','Ask seek knock'),
 ('matthew','7:9','7:11','luke','11:11','11:13','Good gifts'),
 ('matthew','8:2','8:3','mark','1:40','1:42','Cleansing a leper'),
 ('matthew','9:6','9:6','luke','5:24','5:24','Authority to forgive'),
 ('matthew','9:16','9:17','mark','2:21','2:22','Cloth and wineskins'),
 ('matthew','12:25','12:26','luke','11:17','11:18','Divided kingdom'),
 ('matthew','12:41','12:41','luke','11:32','11:32','Nineveh'),
 ('matthew','12:42','12:42','luke','11:31','11:31','Queen of the south'),
 ('matthew','13:3','13:8','mark','4:3','4:8','The sower'),
 ('matthew','16:26','16:26','mark','8:36','8:37','Gain the world'),
 ('matthew','19:24','19:24','mark','10:25','10:25','Camel and needle'),
 ('matthew','24:35','24:35','luke','21:33','21:33','Words will not pass'),
 ('matthew','26:26','26:28','mark','14:22','14:24','Bread and cup'),
]

def main():
    docs=load_docs();config=Config();cases=make_synthetic(docs)
    (ROOT/'docs'/'synthetic-cases.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False)+'\n')
    variants={'default':config,'longer-seeds':replace(config,seed_words=5),'stricter-score':replace(config,min_similarity=.85)}
    synthetic={name:evaluate_synthetic(cases,c) for name,c in variants.items()}
    full={};pair_stats=[];tick=time.perf_counter()
    for a,b in combinations(sorted(docs),2):
        stats={'a':a,'b':b};full[(a,b)]=detect_pair(docs[a]['text'],docs[b]['text'],config,stats);pair_stats.append(stats)
    duration=time.perf_counter()-tick;gold=[]
    for a,sa,ea,b,sb,eb,name in GOLD:
        ra,rb=span(docs[a],sa,ea),span(docs[b],sb,eb)
        if a>b:a,b=b,a;ra,rb=rb,ra
        score=max((min(coverage([m['start_a'],m['end_a']],ra),coverage([m['start_b'],m['end_b']],rb)) for m in full[(a,b)]),default=0)
        gold.append(dict(name=name,a=a,b=b,range_a=ra,range_b=rb,minimum_span_coverage=round(score,4),detected=score>=.4))
    ranges=[]
    for (a,b),matches in full.items():
        for m in matches:
            pa=docs[a]['text'][m['start_a']:m['end_a']];pb=docs[b]['text'][m['start_b']:m['end_b']]
            assert len(tokenize(pa))==m['words_a'] and len(tokenize(pb))==m['words_b']
            assert 0<=m['start_a']<m['end_a']<=len(docs[a]['text']) and 0<=m['start_b']<m['end_b']<=len(docs[b]['text'])
            assert m['kind']!='exact' or [t.value for t in tokenize(pa)]==[t.value for t in tokenize(pb)]
            ranges.append((a,b,m['start_a'],m['end_a'],m['start_b'],m['end_b']))
    assert len(ranges)==len(set(ranges))
    report=dict(algorithm=VERSION,corpus_hashes={k:d['sha256'] for k,d in docs.items()},config=config.__dict__,synthetic=synthetic,real_corpus=dict(total_matches=len(ranges),duration_seconds=round(duration,3),pairs=pair_stats,exact=sum(m['kind']=='exact' for v in full.values() for m in v),near=sum(m['kind']=='near' for v in full.values() for m in v),known_passages_detected=sum(g['detected'] for g in gold),known_passages_total=len(gold),gold=gold,all_offsets_verified=True,duplicate_ranges=0),caveats=['Synthetic controls are not representative corpus precision.','Known locations were chosen by the project author, not external experts; this is a small coverage audit, not exhaustive recall.','A known passage is detected when one result covers at least 40% of both annotated spans.','This report evaluates lexical detection only; offline semantic suggestions are evaluated separately.'])
    sensitivity=[]
    for threshold in [.60,.62,.65,.68,.75,.85]:
        cfg=replace(config,min_similarity=threshold);variants_full={}
        for a,b in combinations(sorted(docs),2):variants_full[(a,b)]=detect_pair(docs[a]['text'],docs[b]['text'],cfg)
        hits=0
        for a,sa,ea,b,sb,eb,name in GOLD:
            ra,rb=span(docs[a],sa,ea),span(docs[b],sb,eb)
            if a>b:a,b=b,a;ra,rb=rb,ra
            score=max((min(coverage([m['start_a'],m['end_a']],ra),coverage([m['start_b'],m['end_b']],rb)) for m in variants_full[(a,b)]),default=0)
            hits+=score>=.4
        sensitivity.append(dict(threshold=threshold,total_matches=sum(len(v) for v in variants_full.values()),known_passages_detected=hits))
    report['threshold_sensitivity']=sensitivity
    report['caveats'].append('The 18 known locations were used for threshold selection: report them as development-set coverage, not held-out recall.')
    (ROOT/'docs'/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()

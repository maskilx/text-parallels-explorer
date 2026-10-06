"""Optional local semantic baseline. Not part of the application runtime."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate import load_docs,make_synthetic,GOLD,span
from app.engine import detect_pair

# Small author-authored English challenge set, not a semantic benchmark.
SEMANTIC=[
 ('paraphrase','The king entered the large city before sunrise and ordered his soldiers to guard the northern gate throughout the entire night.','A monarch arrived in town at dawn, instructing troops to protect its north entrance until morning.',True),
 ('paraphrase','The doctor gave the sick child medicine and told his mother that he needed to rest at home until the fever had gone.','A physician treated the ill boy and advised his parent to keep him indoors until his temperature returned to normal.',True),
 ('paraphrase','A storm destroyed the old bridge across the river, leaving the village without a way to reach the market on the opposite bank.','Severe weather wrecked the crossing over the water, cutting the settlement off from the shops on the far side.',True),
 ('paraphrase','The teacher asked her students to finish their writing before the end of the day and leave their papers on the table.','The instructor told the class to complete the assignment by evening and place their work on her desk.',True),
 ('same-topic','The doctor gave the sick child medicine and told his mother that he needed to rest at home until the fever had gone.','The doctor painted the clinic walls and ordered new chairs for the waiting room before the next patients arrived for their appointments.',False),
 ('same-topic','The king entered the large city before sunrise and ordered his soldiers to guard the northern gate throughout the entire night.','The king remained in his palace during the winter while merchants sold grain in the city market and children played near the southern wall.',False),
 ('same-topic','A storm destroyed the old bridge across the river, leaving the village without a way to reach the market on the opposite bank.','The village held a festival near the river, where visitors crossed a new bridge to buy vegetables and listen to the local musicians.',False),
 ('unrelated','The teacher asked her students to finish their writing before the end of the day and leave their papers on the table.','The fishing boat returned to the harbor with a large catch after spending three days at sea during a period of unusually calm weather.',False),
]

def measure(labels,scores,threshold):
    tp=sum(y and s>=threshold for y,s in zip(labels,scores));fp=sum(not y and s>=threshold for y,s in zip(labels,scores))
    fn=sum(y and s<threshold for y,s in zip(labels,scores));tn=sum(not y and s<threshold for y,s in zip(labels,scores))
    return dict(threshold=threshold,tp=tp,fp=fp,fn=fn,tn=tn,precision=tp/max(1,tp+fp),recall=tp/max(1,tp+fn))

def main():
    import sentence_transformers
    from sentence_transformers import SentenceTransformer
    from huggingface_hub import model_info
    parser=argparse.ArgumentParser();parser.add_argument('--model',default='sentence-transformers/all-MiniLM-L6-v2');parser.add_argument('--threshold',type=float,default=.8);args=parser.parse_args()
    docs=load_docs();cases=make_synthetic(docs)
    # Pin the exact model revision resolved for this recorded run.
    revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41' if args.model=='sentence-transformers/all-MiniLM-L6-v2' else model_info(args.model).sha
    model=SentenceTransformer(args.model,revision=revision,device='cpu')
    sanity=model.encode(['The cat sits on the mat.','The cat sits on the mat.'],normalize_embeddings=True)
    sanity_score=float((sanity[0]*sanity[1]).sum());assert abs(sanity_score-1)<1e-4
    def similarities(left,right):
        a=model.encode(left,normalize_embeddings=True);b=model.encode(right,normalize_embeddings=True)
        return [float(s) for s in (a*b).sum(axis=1)]
    scores=similarities([c['a'] for c in cases],[c['b'] for c in cases])
    localized=similarities([c['a'][slice(*c['expected_a'])] if c['label'] else c['a'] for c in cases],
                          [c['b'][slice(*c['expected_b'])] if c['label'] else c['b'] for c in cases])
    labels=[c['label'] for c in cases]
    natural=list(SEMANTIC)
    for a,sa,ea,b,sb,eb,name in GOLD:
        natural.append(('known-lexical',docs[a]['text'][slice(*span(docs[a],sa,ea))],docs[b]['text'][slice(*span(docs[b],sb,eb))],True))
    natural_scores=similarities([n[1] for n in natural],[n[2] for n in natural])
    natural_rows=[dict(kind=n[0],a=n[1],b=n[2],label=n[3],embedding_score=s,lexical_detected=bool(detect_pair(n[1],n[2]))) for n,s in zip(natural,natural_scores)]
    report=dict(model=args.model,revision=revision,library_version=sentence_transformers.__version__,device='cpu',sanity_identical_score=sanity_score,
        synthetic_with_context=measure(labels,scores,args.threshold),synthetic_with_gold_boundaries=measure(labels,localized,args.threshold),
        synthetic_rows=[dict(id=c['id'],kind=c['kind'],label=c['label'],score=s,localized_score=l) for c,s,l in zip(cases,scores,localized)],
        natural_challenge=dict(rows=natural_rows,threshold_sensitivity=[measure([n[3] for n in natural],natural_scores,t) for t in [.5,.6,.7,.8,.9]]),
        caveats=['Synthetic disjoint-vocabulary controls use artificial alphanumeric tokens and are unsuitable for estimating semantic precision.',
                 'Gold-boundary inputs assume an oracle already localized the correct spans; they are not a retrieval result.',
                 'Context-window scores and lexical localization solve different tasks; these scores are not directly comparable.',
                 'The natural challenge contains only 26 author-selected pairs, not an independent benchmark. No corpus-wide semantic retrieval was evaluated.',
                 'No embedding threshold was calibrated on held-out data; the app does not use this model.'])
    (ROOT/'docs'/'embedding-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['synthetic_rows','natural_challenge']},indent=2))
    print('Natural challenge',report['natural_challenge']['threshold_sensitivity'])
if __name__=='__main__':main()

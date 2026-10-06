"""Deterministic, offset-preserving seed-and-extend text reuse detector."""
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import product
import hashlib
import re
import unicodedata
import numpy as np
from Bio.Align import PairwiseAligner
from rapidfuzz.distance import Levenshtein

VERSION = 'lexical-1.1.0'
TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)

@dataclass(frozen=True)
class Config:
    seed_words: int = 3
    use_skip_seeds: bool = True
    min_exact_words: int = 12
    min_near_words: int = 16
    min_similarity: float = .62
    max_seed_occurrences: int = 60
    context_words: int = 32
    max_candidate_words: int = 220
    match_reward: float = 2.0
    mismatch_penalty: float = -1.0
    gap_open_penalty: float = -2.0
    gap_extend_penalty: float = -.6

@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int

def tokenize(text):
    return [Token(unicodedata.normalize('NFKC', m.group()).casefold().replace('’', "'"), m.start(), m.end())
            for m in TOKEN_RE.finditer(text)]

def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def index_ngrams(tokens, k):
    index = defaultdict(list)
    values = [t.value for t in tokens]
    for i in range(len(values)-k+1):
        index[tuple(values[i:i+k])].append(i)
    return index

def index_skipgrams(tokens, k):
    """Keep word order, allowing zero or one intervening word per step.

    Store complete source spans, not just starts: skipped words stay in alignment.
    Contiguous patterns are included so a gapped triple can match a plain triple.
    Multiple choices with the same words and source span are deduplicated.
    """
    index = defaultdict(set)
    values = [t.value for t in tokens]
    steps = list(product((1, 2), repeat=k-1))
    for start in range(len(values)):
        for pattern in steps:
            positions = [start]
            for step in pattern:
                positions.append(positions[-1]+step)
            if positions[-1] < len(values):
                key = tuple(values[i] for i in positions)
                index[key].add((start, positions[-1]+1))
    return index


def skip_candidate_windows(seeds, size_a, size_b, config):
    """Chain ordered skip anchors while retaining their full source spans."""
    chains = []
    by_diagonal = defaultdict(list)
    for a, b, end_a, end_b in sorted(seeds):
        bucket = (b-a)//8
        eligible = []
        for d in (bucket-1, bucket, bucket+1):
            for idx in by_diagonal[d][-8:]:
                c = chains[idx]
                if (0 <= a-c[2] <= 40 and 0 <= b-c[3] <= 40
                    and abs((b-a)-(c[3]-c[2])) <= 12
                    and max(max(c[4],end_a)-c[0], max(c[5],end_b)-c[1])
                        + 2*config.context_words <= config.max_candidate_words):
                    eligible.append(idx)
        if eligible:
            idx = max(eligible, key=lambda i: chains[i][2]+chains[i][3])
            c = chains[idx]
            c[2:4] = [a,b]
            c[4:6] = [max(c[4],end_a),max(c[5],end_b)]
        else:
            idx = len(chains)
            chains.append([a,b,a,b,end_a,end_b])
            by_diagonal[bucket].append(idx)
    return {(max(0,a-config.context_words),min(size_a,ea+config.context_words),
             max(0,b-config.context_words),min(size_b,eb+config.context_words))
            for a,b,_,_,ea,eb in chains}


def overlap(a, b):
    return max(0, min(a[1], b[1])-max(a[0], b[0])) / max(1, min(a[1]-a[0], b[1]-b[0]))

def suppress(matches):
    """Remove redundant overlapping alternatives in BOTH documents; preserve repeats."""
    kept = []
    for m in sorted(matches, key=lambda x: (-min(x['words_a'], x['words_b']), -x['score'], x['start_a'], x['start_b'])):
        if any(overlap((m['start_a'],m['end_a']), (p['start_a'],p['end_a'])) >= .85 and
               overlap((m['start_b'],m['end_b']), (p['start_b'],p['end_b'])) >= .85 for p in kept):
            continue
        kept.append(m)
    return sorted(kept, key=lambda x:(x['start_a'],x['start_b'],x['end_a'],x['end_b']))

def detect_pair(text_a, text_b, config=Config(), stats=None):
    ta, tb = tokenize(text_a), tokenize(text_b)
    va, vb = [t.value for t in ta], [t.value for t in tb]
    ia, ib = index_ngrams(ta, config.seed_words), index_ngrams(tb, config.seed_words)
    seeds, skipped = [], 0
    for key in sorted(ia.keys() & ib.keys()):
        if max(len(ia[key]),len(ib[key])) > config.max_seed_occurrences:
            skipped += 1
            continue
        seeds.extend((a,b) for a in ia[key] for b in ib[key])
    seeds.sort()
    aligner = PairwiseAligner(mode='local', match_score=config.match_reward,
        mismatch_score=config.mismatch_penalty, open_gap_score=config.gap_open_penalty,
        extend_gap_score=config.gap_extend_penalty)
    vocabulary = {v:i for i,v in enumerate(sorted(set(va+vb)))}
    aa = np.array([vocabulary[v] for v in va], dtype=np.int32)
    ab = np.array([vocabulary[v] for v in vb], dtype=np.int32)
    matches = {}

    def emit(a0,a1,b0,b1,method,alignment_score=None):
        if a1<=a0 or b1<=b0: return
        left,right = va[a0:a1],vb[b0:b1]
        exact = left==right
        minimum = config.min_exact_words if exact else config.min_near_words
        if min(len(left),len(right)) < minimum: return
        distance = Levenshtein.distance(left,right)
        score = 1-distance/max(len(left),len(right))
        if score < config.min_similarity: return
        m = dict(start_a=ta[a0].start,end_a=ta[a1-1].end,start_b=tb[b0].start,end_b=tb[b1-1].end,
            words_a=len(left),words_b=len(right),score=round(score,6),edit_distance=distance,
            kind='exact' if exact else 'near',raw_exact=text_a[ta[a0].start:ta[a1-1].end]==text_b[tb[b0].start:tb[b1-1].end],
            method=method,alignment_score=alignment_score,seed_words=config.seed_words)
        matches.setdefault((a0,a1,b0,b1), m)

    # Maximal exact runs from every indexed seed, independent of local alignment.
    exact_runs = defaultdict(list)
    for a,b in seeds:
        diagonal=b-a
        if any(lo<=a<hi for lo,hi in exact_runs[diagonal]): continue
        a0,b0,a1,b1=a,b,a+config.seed_words,b+config.seed_words
        while a0>0 and b0>0 and va[a0-1]==vb[b0-1]: a0-=1; b0-=1
        while a1<len(va) and b1<len(vb) and va[a1]==vb[b1]: a1+=1; b1+=1
        exact_runs[diagonal].append((a0,a1))
        emit(a0,a1,b0,b1,'exact-extension')

    # Chain nearby seeds in the same order and with limited displacement.
    # Split long chains so local DP is bounded; windows overlap at split points.
    chains = []
    by_diagonal = defaultdict(list)
    for a,b in seeds:
        bucket=(b-a)//8
        eligible=[]
        for d in (bucket-1,bucket,bucket+1):
            for idx in by_diagonal[d][-8:]:
                c=chains[idx]
                if 0<=a-c[2]<=40 and 0<=b-c[3]<=40 and abs((b-a)-(c[3]-c[2]))<=12 and max(a-c[0],b-c[1])<config.max_candidate_words-2*config.context_words:
                    eligible.append(idx)
        if eligible:
            idx=max(eligible,key=lambda i:chains[i][2]+chains[i][3])
            chains[idx][2:4]=[a,b]
        else:
            idx=len(chains); chains.append([a,b,a,b]); by_diagonal[bucket].append(idx)
    windows=set()
    for a,b,ae,be in chains:
        windows.add((max(0,a-config.context_words),min(len(ta),ae+config.seed_words+config.context_words),
                     max(0,b-config.context_words),min(len(tb),be+config.seed_words+config.context_words)))
    # Add a second retrieval route without changing contiguous exact extension
    # or the original candidate chains. A skip anchor never asserts exact text.
    contiguous_windows = set(windows)
    skip_seeds, skipped_skip = set(), 0
    if config.use_skip_seeds:
        sa, sb = index_skipgrams(ta, config.seed_words), index_skipgrams(tb, config.seed_words)
        for key in sorted(sa.keys() & sb.keys()):
            if max(len(sa[key]),len(sb[key])) > config.max_seed_occurrences:
                skipped_skip += 1
                continue
            for a,ea in sa[key]:
                for b,eb in sb[key]:
                    if ea-a > config.seed_words or eb-b > config.seed_words:
                        skip_seeds.add((a,b,ea,eb))
        windows.update(skip_candidate_windows(skip_seeds,len(ta),len(tb),config))
    baseline_matches = {}
    for candidate_set, method in ((contiguous_windows, 'seed-local-alignment'),
                                   (windows-contiguous_windows, 'skip-seed-local-alignment')):
        for a0,a1,b0,b1 in sorted(candidate_set):
            # One best local region per window; gaps remain in original source spans.
            result = aligner.align(aa[a0:a1],ab[b0:b1])
            try: best = next(iter(result))
            except StopIteration: continue
            coords = best.coordinates
            emit(a0+int(coords[0,0]),a0+int(coords[0,-1]),b0+int(coords[1,0]),b0+int(coords[1,-1]),
                 method,round(best.score,3))
        if method == 'seed-local-alignment':
            baseline_matches = dict(matches)
    # Keep the established contiguous results (and their review identities).
    # Additional skip results must not crowd out an existing reviewed passage.
    output = suppress(list(baseline_matches.values()))
    additional = suppress([m for key,m in matches.items() if key not in baseline_matches])
    for m in additional:
        if any(overlap((m['start_a'],m['end_a']),(p['start_a'],p['end_a'])) >= .85 and
               overlap((m['start_b'],m['end_b']),(p['start_b'],p['end_b'])) >= .85 for p in output):
            continue
        output.append(m)
    output.sort(key=lambda m:(m['start_a'],m['start_b'],m['end_a'],m['end_b']))
    if stats is not None:
        stats.update(tokens_a=len(ta),tokens_b=len(tb),seeds=len(seeds)+len(skip_seeds),contiguous_seeds=len(seeds),skip_seeds=len(skip_seeds),
                     skip_candidate_windows=len(windows-contiguous_windows),candidate_windows=len(windows),
                     skipped_frequent_seeds=skipped,skipped_frequent_skip_seeds=skipped_skip,raw_matches=len(matches),matches=len(output))
    return output

def diff_blocks(text_a,text_b):
    """Token diff translated back to code-point offsets, relative to the passages."""
    a,b=tokenize(text_a),tokenize(text_b)
    result=[]
    for op in Levenshtein.opcodes([t.value for t in a],[t.value for t in b]):
        def span(tokens,start,end,text):
            if start==end:
                p=tokens[start].start if start<len(tokens) else len(text)
                return [p,p]
            return [tokens[start].start,tokens[end-1].end]
        result.append(dict(kind=op.tag,a=span(a,op.src_start,op.src_end,text_a),b=span(b,op.dest_start,op.dest_end,text_b)))
    return result

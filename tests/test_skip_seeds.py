from dataclasses import replace
import pytest
from app.engine import Config,detect_pair,index_ngrams,index_skipgrams,tokenize,skip_candidate_windows
from tests.test_engine import PASSAGE

BASE=Config(use_skip_seeds=False)

def words(text):return [t.value for t in tokenize(text)]

def test_plain_triple_matches_gapped_triple_and_keeps_full_span():
    a=index_skipgrams(tokenize('king entered city'),3)
    b=index_skipgrams(tokenize('king young entered quickly city'),3)
    assert a[('king','entered','city')]=={(0,3)}
    assert b[('king','entered','city')]=={(0,5)}
    assert not (index_ngrams(tokenize('king entered city'),3).keys() & index_ngrams(tokenize('king young entered quickly city'),3).keys())

def test_gap_larger_than_one_is_not_an_anchor():
    idx=index_skipgrams(tokenize('king very unusually young entered city'),3)
    assert ('king','entered','city') not in idx

@pytest.mark.parametrize('kind',['insertion','deletion','substitution'])
def test_seedless_changes_recovered_without_lowering_score_threshold(kind):
    original=words(PASSAGE)
    if kind=='insertion':
        changed=[]
        for i,w in enumerate(original):
            changed.append(w)
            if i%2==1 and i<len(original)-1:changed.append('additional')
    elif kind=='deletion':changed=[w for i,w in enumerate(original) if i%3!=2]
    else:changed=[w if i%3!=2 else f'changed{i}' for i,w in enumerate(original)]
    a=' '.join(original);b=' '.join(changed)
    assert not (index_ngrams(tokenize(a),3).keys() & index_ngrams(tokenize(b),3).keys())
    assert detect_pair(a,b,BASE)==[]
    stats={};found=detect_pair(a,b,stats=stats)
    assert found and stats['skip_seeds']>0
    assert any(m['kind']=='near' and m['score']>=.62 and m['method']=='skip-seed-local-alignment' for m in found)
    assert all(len(tokenize(a[m['start_a']:m['end_a']]))==m['words_a'] and len(tokenize(b[m['start_b']:m['end_b']]))==m['words_b'] for m in found)

def test_many_insertions_can_still_fail_score_gate():
    original=[f'word{i}' for i in range(30)]
    a=' '.join(original);b=' '.join(x for w in original for x in (w,'extra'))
    stats={};assert detect_pair(a,b,stats=stats)==[]
    assert stats['skip_seeds']>0

def test_skip_seed_is_never_treated_as_contiguous_exact_run():
    a=' '.join(f'word{i}' for i in range(25))
    b=' '.join(w+' extra' if i%2 else w for i,w in enumerate(a.split()))
    assert all(m['kind']!='exact' for m in detect_pair(a,b))

def test_source_offsets_unicode_and_repeated_matches():
    a=' '.join(words(PASSAGE));changed=' '.join(w+' added' if i%2 else w for i,w in enumerate(a.split()))
    left='🌿 '+a+' '+' '.join(f'alpha{i}' for i in range(90))+' '+a
    right='🌞 '+changed
    found=detect_pair(left,right)
    assert len(found)==2 and len({m['start_a'] for m in found})==2
    assert found==detect_pair(left,right)
    for m in found:assert left[m['start_a']:m['end_a']] and right[m['start_b']:m['end_b']]

def test_reversed_words_are_not_a_shared_ordered_passage():
    a=' '.join(f'word{i}' for i in range(40))
    assert detect_pair(a,' '.join(reversed(a.split())))==[]

def test_skip_windows_include_anchor_ends_and_remain_bounded():
    cfg=replace(Config(),context_words=4,max_candidate_words=30)
    windows=skip_candidate_windows([(10,20,15,25),(18,28,23,33),(40,50,45,55)],100,100,cfg)
    assert any(lo<=10 and hi>=23 and lb<=20 and hb>=33 for lo,hi,lb,hb in windows)
    assert all(hi-lo<=30 and hb-lb<=30 for lo,hi,lb,hb in windows)

def test_common_skip_seeds_are_guarded():
    stats={};assert detect_pair('a b c '*100,'a b c '*100,stats=stats)==[]
    assert stats['skipped_frequent_skip_seeds']>0

def test_skip_additions_preserve_contiguous_result_ranges():
    a=PASSAGE+' '+' '.join(f'alpha{i}' for i in range(80))+' '+PASSAGE
    b=PASSAGE.replace('wooden','ancient wooden')+' '+' '.join(f'beta{i}' for i in range(85))+' '+PASSAGE
    def ranges(matches):return {tuple(m[k] for k in ['start_a','end_a','start_b','end_b']) for m in matches}
    original=detect_pair(a,b,BASE);assert original
    assert ranges(original)<=ranges(detect_pair(a,b))

import random
import pytest
from app.engine import Config, detect_pair, tokenize, diff_blocks, overlap

PASSAGE='The travelers crossed the narrow wooden bridge before sunrise and reached the quiet village where the old keeper welcomed them with warm bread and fresh water.'

def test_exact_offsets_and_score():
    a='Preface unrelated. '+PASSAGE+'\nAfterword unrelated.'
    b='🌿 Different opening. '+PASSAGE+'\nAnother closing.'
    found=detect_pair(a,b)
    assert any(a[m['start_a']:m['end_a']]==PASSAGE.rstrip('.') and b[m['start_b']:m['end_b']]==PASSAGE.rstrip('.') and m['score']==1 and m['kind']=='exact' for m in found)

@pytest.mark.parametrize('changed',[
    PASSAGE.replace('wooden','stone'),
    PASSAGE.replace('wooden bridge','wooden ancient bridge'),
    PASSAGE.replace('narrow wooden','wooden'),
    PASSAGE.replace('wooden','stone').replace('quiet','small').replace('warm','fresh'),
])
def test_near_edits(changed):
    found=detect_pair('Opening. '+PASSAGE,'Unrelated. '+changed)
    assert any(m['kind']=='near' and m['score']>=.8 for m in found)

def test_normalization_and_unicode_offsets():
    a='🌿 '+PASSAGE
    b='🌞 '+PASSAGE.upper().replace(' ', '\n')
    found=detect_pair(a,b)
    exact=next(m for m in found if m['kind']=='exact')
    assert exact['score']==1 and not exact['raw_exact']
    assert a[exact['start_a']:exact['end_a']]==PASSAGE.rstrip('.')
    assert tokenize("Straße ﬂower keeper’s")[0].value=='strasse'

def test_no_shared_content_and_short_formula():
    assert detect_pair(' '.join(f'alpha{i}' for i in range(50)), ' '.join(f'beta{i}' for i in range(50)))==[]
    assert detect_pair('And he said to them.', 'And he said to them.')==[]

def test_repeated_passage_locations_preserved():
    a=PASSAGE+' '+' '.join(f'alpha{i}' for i in range(70))+' '+PASSAGE
    b='Introduction. '+PASSAGE
    result=detect_pair(a,b)
    assert len([m for m in result if m['kind']=='exact'])==2
    assert len({m['start_a'] for m in result})==2

def test_separated_matches_not_just_best():
    second='The sailors repaired their damaged vessel beside the harbor while a patient carpenter prepared new boards and the captain inspected the ropes before the evening voyage.'
    a=PASSAGE+' '+' '.join(f'alpha{i}' for i in range(90))+' '+second
    b=second+' '+' '.join(f'beta{i}' for i in range(100))+' '+PASSAGE
    result=detect_pair(a,b)
    assert len([m for m in result if m['kind']=='exact'])==2

def test_determinism_and_empty():
    assert detect_pair(PASSAGE,PASSAGE)==detect_pair(PASSAGE,PASSAGE)
    assert detect_pair('',PASSAGE)==[]
    assert detect_pair('','')==[]

def test_diff_ranges_reconstruct_and_stay_in_bounds():
    b=PASSAGE.replace('wooden','ancient stone').replace('quiet ','')
    blocks=diff_blocks(PASSAGE,b)
    assert any(x['kind']!='equal' for x in blocks)
    for block in blocks:
        for side,text in [('a',PASSAGE),('b',b)]:
            lo,hi=block[side]
            assert 0<=lo<=hi<=len(text)
        if block['kind']=='equal':
            assert [t.value for t in tokenize(PASSAGE[slice(*block['a'])])]==[t.value for t in tokenize(b[slice(*block['b'])])]

@pytest.mark.parametrize('seed',range(12))
def test_randomized_edits_maintain_source_ranges(seed):
    rng=random.Random(seed)
    words=PASSAGE.split()
    for i in sorted(rng.sample(range(4,len(words)-4),3),reverse=True):
        words[i]=f'changed{seed}{i}'
    b=' '.join(words)
    found=detect_pair(PASSAGE,b)
    assert found
    for m in found:
        a_part=PASSAGE[m['start_a']:m['end_a']];b_part=b[m['start_b']:m['end_b']]
        assert len(tokenize(a_part))==m['words_a'] and len(tokenize(b_part))==m['words_b']
        assert 0<=m['score']<=1

def test_seedless_paraphrase_is_documented_limitation():
    a='The king entered the large city before sunrise and ordered his soldiers to guard the northern gate throughout the entire night.'
    b='A monarch arrived in town at dawn, instructing troops to protect its north entrance until morning.'
    assert detect_pair(a,b)==[]

def test_low_similarity_is_filtered():
    a=' '.join(f'token{i}' for i in range(50))
    b=' '.join(f'token{i}' if i<4 else f'other{i}' for i in range(50))
    assert detect_pair(a,b)==[]

def test_frequent_seed_guard():
    stats={}
    assert detect_pair('a b c '*100,'a b c '*100,stats=stats)==[]
    assert stats['skipped_frequent_seeds']>0

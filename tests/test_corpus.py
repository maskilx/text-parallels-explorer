import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from scripts.fetch_corpus import extract_verses
from app.engine import fingerprint
ROOT=Path(__file__).resolve().parents[1]

def test_chapter_navigation_is_excluded_without_losing_final_verse():
    soup=BeautifulSoup('<div class="main"><div class="p"><span class="verse">80</span>The child was growing.</div><ul class="tnav"><li><a href="index.htm">Luke</a></li><li>&lt;</li><li>1</li><li>&gt;</li></ul></div>','html.parser')
    assert extract_verses(soup)==[('80','The child was growing.')]

def test_poetry_and_quotation_continuations_are_preserved():
    soup=BeautifulSoup('<div class="main"><div class="chapterlabel">3</div><div class="p"><span class="verse">3</span>He said:</div><div class="q1">A voice in the wilderness,</div><div class="q2">prepare the way.</div><div class="s">Heading excluded</div><div class="p"><span class="verse">4</span>The next verse.<span class="notemark">a</span><span class="footnote">Excluded note</span></div></div>','html.parser')
    assert extract_verses(soup)==[('3','He said: A voice in the wilderness, prepare the way.'),('4','The next verse.')]

def test_bundled_checksums_references_and_completeness():
    manifest=json.loads((ROOT/'corpus'/'manifest.json').read_text())
    assert len(manifest)==3
    for d in manifest:
        text=(ROOT/'corpus'/d['file']).read_text();refs=json.loads((ROOT/'corpus'/d['refs']).read_text())
        assert fingerprint(text)==d['sha256']
        assert len(refs)==d['verses']
        assert len({r['label'] for r in refs})==len(refs)
        previous=0
        for r in refs:
            assert previous<=r['start']<r['end']<=len(text)
            assert text[r['start']:r['end']].strip()
            previous=r['end']
        assert 'HTML generated' not in text and 'Public Domain' not in text
        assert not re.search(r'(?:Matthew|Mark|Luke)\s*<\s*\d+\s*>',text)
    matthew=(ROOT/'corpus'/'matthew.txt').read_text()
    assert 'voice of one crying in the wilderness' in matthew

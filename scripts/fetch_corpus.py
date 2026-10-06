"""Rebuild the bundled corpus from eBible's public-domain HTML archive."""
import hashlib, io, json, re, zipfile
from pathlib import Path
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
ROOT=Path(__file__).resolve().parents[1]
URL='https://ebible.org/Scriptures/eng-web_html.zip'

def extract_verses(soup):
    """Keep continuation paragraphs; exclude verse labels and non-text metadata."""
    main_text=soup.select_one('div.main')
    if main_text is None: raise ValueError('Missing main text')
    output=[];current=None;chunks=[]
    ignored={'verse','chapterlabel','s','s1','s2','s3','mt','mt1','mt2','ms','r','d','toc','copyright','footnote','notemark','xref'}
    def flush():
        text=re.sub(r'\s+',' ',' '.join(chunks)).strip()
        if current is not None and text:output.append((current,text))
    for node in main_text.descendants:
        if isinstance(node,Tag) and node.name=='span' and 'verse' in node.get('class',[]):
            flush();current=node.get_text(strip=True);chunks=[]
        elif isinstance(node,NavigableString) and current is not None:
            if not any(set(parent.get('class',[])) & ignored for parent in node.parents if isinstance(parent,Tag)):
                chunks.append(str(node))
    flush();return output

def main():
    response=requests.get(URL,timeout=90); response.raise_for_status()
    archive=zipfile.ZipFile(io.BytesIO(response.content))
    manifest=[]
    for code,title in [('MAT','Matthew'),('MRK','Mark'),('LUK','Luke')]:
        files=sorted(n for n in archive.namelist() if re.search(rf'{code}\d{{2,3}}\.htm$',n))
        parts=[]; refs=[]; cursor=0
        for filename in files:
            soup=BeautifulSoup(archive.read(filename),'html.parser')
            for unwanted in soup.select('.footnote, .xref, .notemark, .footnotehr, .f, .x'):
                unwanted.decompose()
            chapter=re.search(rf'{code}(\d+)\.htm',filename).group(1)
            for verse,text in extract_verses(soup):
                refs.append(dict(label=f'{int(chapter)}:{verse}',start=cursor,end=cursor+len(text)))
                parts.append(text);cursor+=len(text)+1
        if not parts: raise RuntimeError(f'No verses found for {code}: {files[:3]}')
        text='\n'.join(parts)+'\n'
        dest=ROOT/'corpus'/f'{title.lower()}.txt'; dest.write_text(text,encoding='utf-8')
        (ROOT/'corpus'/f'{title.lower()}.refs.json').write_text(json.dumps(refs,indent=2),encoding='utf-8')
        manifest.append(dict(id=title.lower(),title=title,edition='World English Bible Classic',file=dest.name,
            refs=f'{title.lower()}.refs.json',source_url=f'https://ebible.org/eng-web/{code}01.htm',
            rights_url='https://ebible.org/eng-web/copyright.htm',license='Public domain',
            retrieved='2026-10-05',sha256=hashlib.sha256(text.encode()).hexdigest(),verses=len(refs)))
        print(title,len(text),len(refs))
    (ROOT/'corpus'/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
if __name__=='__main__': main()

"""Build a self-contained HTML version of the pitch deck (slides, styles and screenshots embedded).

    python deck/build_standalone.py [--out signalcore-deck.html]

Arrow keys / space / click to navigate, F for full screen, N to toggle speaker notes.
Images referenced as /_blob/<id> are resolved through deck/assets/blobs.json to local PNG files.
"""
import argparse
import base64
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE / "project"


def main(out):
    deck = json.loads((PROJ / "deck.json").read_text())
    css = (PROJ / "deck.css").read_text()
    blobs = {}
    mp = HERE / "assets" / "blobs.json"
    if mp.exists():
        for url, f in json.loads(mp.read_text()).items():
            blobs[url] = "data:image/png;base64," + base64.b64encode((HERE / "assets" / f).read_bytes()).decode()
    slides = []
    for n, sid in enumerate(deck["order"]):
        h = (PROJ / "slides" / f"{sid}.html").read_text()
        for url, data in blobs.items():
            h = h.replace(f'src="{url}"', f'src="{data}"')
        notes = re.search(r"<aside>(.*?)</aside>", h, re.S)
        h = re.sub(r"<aside>.*?</aside>", "", h, flags=re.S)
        note = (notes.group(1) if notes else "").replace("&", "&amp;").replace(chr(34), "&quot;")
        # one slide is visible at a time, so pin the page counter per slide
        h = h.replace("<section ", f'<section data-notes="{note}" data-n="{n}" ', 1)
        h = h.replace(f'data-n="{n}" ', f'data-n="{n}" style="counter-reset:page {n}" ', 1) if 'style="' not in h.split(">", 1)[0] else \
            h.replace('style="', f'style="counter-reset:page {n};', 1)
        slides.append(h)
    fonts = sorted({f["href"] for f in deck["faces"].values() if f.get("href")})
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{deck['title']}</title>{''.join(f'<link rel="stylesheet" href="{h}">' for h in fonts)}
<style>
html,body{{margin:0;height:100%;background:#05070A;overflow:hidden}}
#stage{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}}
#deck{{width:1920px;height:1080px;position:relative;transform-origin:center center;flex:none}}
#deck>section{{position:absolute;inset:0;width:1920px;height:1080px;box-sizing:border-box;display:none;overflow:hidden}}
#deck>section.on{{display:flex}}
#hud{{position:fixed;bottom:12px;right:16px;font:13px/1.4 system-ui,sans-serif;color:#8B97A9;display:flex;gap:10px;align-items:center;z-index:5}}
#hud button{{background:#161D29;border:1px solid #2D3849;color:#E6EBF2;border-radius:6px;padding:4px 10px;cursor:pointer;font:inherit}}
#notes{{position:fixed;left:16px;right:16px;bottom:52px;max-height:30vh;overflow:auto;background:#11161FEE;border:1px solid #2D3849;color:#E6EBF2;
  font:15px/1.5 system-ui,sans-serif;padding:12px 16px;border-radius:8px;display:none;z-index:5}}
@media print{{html,body{{overflow:visible;height:auto}}#stage{{position:static;display:block}}#deck{{transform:none!important}}
  #deck>section{{position:relative;display:flex!important;page-break-after:always}}#hud,#notes{{display:none!important}}@page{{size:1920px 1080px;margin:0}}}}
{css}
</style></head><body><div id="stage"><div id="deck">{''.join(slides)}</div></div>
<div id="notes"></div><div id="hud"><button id="prev" aria-label="Previous slide">‹</button><span id="pos"></span><button id="next" aria-label="Next slide">›</button>
<button id="nb">Notes</button><button id="fs">Full screen</button></div>
<script>
const S=[...document.querySelectorAll('#deck>section')];let i=Math.max(0,Math.min(S.length-1,(parseInt(location.hash.slice(1))||1)-1));
const deck=document.getElementById('deck'),notes=document.getElementById('notes');
function fit(){{const k=Math.min(innerWidth/1920,innerHeight/1080);deck.style.transform=`scale(${{k}})`;}}
function show(n){{i=Math.max(0,Math.min(S.length-1,n));S.forEach((s,j)=>s.classList.toggle('on',j===i));
  document.getElementById('pos').textContent=`${{i+1}} / ${{S.length}}`;notes.textContent=S[i].dataset.notes||'';history.replaceState(null,'','#'+(i+1));}}
addEventListener('keydown',e=>{{if(['ArrowRight','PageDown',' '].includes(e.key)){{e.preventDefault();show(i+1)}}else if(['ArrowLeft','PageUp'].includes(e.key)){{e.preventDefault();show(i-1)}}
  else if(e.key==='Home')show(0);else if(e.key==='End')show(S.length-1);else if(e.key==='n'||e.key==='N')togN();else if(e.key==='f'||e.key==='F')togF();}});
function togN(){{notes.style.display=notes.style.display==='block'?'none':'block'}}
function togF(){{document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen().catch(()=>{{}})}}
document.getElementById('prev').onclick=()=>show(i-1);document.getElementById('next').onclick=()=>show(i+1);
document.getElementById('nb').onclick=togN;document.getElementById('fs').onclick=togF;
document.getElementById('stage').onclick=e=>{{if(e.target.closest('a'))return;show(e.clientX>innerWidth/2?i+1:i-1)}};
addEventListener('resize',fit);addEventListener('hashchange',()=>{{const n=parseInt(location.hash.slice(1));if(n&&n-1!==i)show(n-1)}});fit();show(i);
</script></body></html>"""
    Path(out).write_text(html)
    return out, len(html)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "signalcore-deck.html"))
    p, n = main(ap.parse_args().out)
    print(f"wrote {p} ({n // 1024} KB)")

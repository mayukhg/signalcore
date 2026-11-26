// Records the SignalCore walkthrough: drives the live app (replay mode) scene by scene, paced by the voiceover,
// and captures high-quality frames through the Chrome DevTools screencast.
//   node video/record.js <outdir>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
const BASE = 'http://localhost:8000/';
const DUR = Object.fromEntries(JSON.parse(fs.readFileSync(path.join(__dirname, 'durations.json'))).map(d => [d.id, d.dur]));
fs.mkdirSync(path.join(OUT, 'frames'), { recursive: true });

const CURSOR = `
(() => {
  if (window.__cursor) return; window.__cursor = 1;
  const add = () => {
    const c = document.createElement('div'); c.id = '__c';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-3px 0 0 -3px;z-index:2147483647;pointer-events:none;transition:transform .05s linear';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.8 L10.5 20 L13 18.8 L10.2 12.8 L16 12.8 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;border-radius:50%;border:3px solid #45C1E6;left:' + (e.clientX - 18) + 'px;top:' + (e.clientY - 18) + 'px;width:36px;height:36px;opacity:.9;transition:all .45s ease-out';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 500);
    }, true);
  };
  document.readyState === 'loading' ? addEventListener('DOMContentLoaded', add) : add();
})();`;

function card(kind) {
  const t = kind === 'title'
    ? `<div class="e">Product walkthrough</div><h1>SignalCore</h1><p class="s">Evidence-backed prioritization for Product Ops</p>
       <p class="b">Say · Do · Pay triangulation &nbsp;·&nbsp; Cost of Delay &amp; CD3 &nbsp;·&nbsp; Claude agents with a skeptic and a grounding judge</p>`
    : `<div class="e">Recap</div><h1>SignalCore</h1><ul>
       <li>Cross-examines what customers <b style="color:#B39CFF">say</b> against what they <b style="color:#45C1E6">do</b> and <b style="color:#F0B445">pay</b></li>
       <li>Prices the cost of waiting, ranks the backlog by CD3</li>
       <li>Real Claude agents · deterministic, auditable scoring · graded against ground truth</li>
       <li>Next: a 90-day pilot on your own exports</li></ul><p class="b">Synthetic demo tenant · run it yourself with <code>make demo</code></p>`;
  return `data:text/html;charset=utf-8,` + encodeURIComponent(`<!doctype html><html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500&display=swap">
  <style>html,body{margin:0;height:100%;background:#0A0D12;color:#E6EBF2;font-family:'IBM Plex Sans',sans-serif}
  body{display:flex;align-items:center;padding:0 140px;box-sizing:border-box;gap:80px}
  .w{flex:1}.e{font-family:'IBM Plex Sans';letter-spacing:.16em;text-transform:uppercase;color:#45C1E6;font-size:20px;font-weight:500}
  h1{font-family:'Space Grotesk',sans-serif;font-size:120px;margin:10px 0 6px;letter-spacing:-2px}
  .s{font-size:36px;margin:0 0 26px}.b{font-size:22px;color:#8B97A9;margin:28px 0 0}ul{font-size:30px;line-height:1.6;padding-left:30px;margin:10px 0}
  code{font-family:monospace;color:#45C1E6} @keyframes in{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}} .w{animation:in .9s ease-out both}
  svg{animation:in 1.2s .3s ease-out both}</style></head><body><div class="w">${t}</div>
  <svg width="420" height="400" viewBox="0 0 520 480"><circle cx="180" cy="170" r="150" fill="none" stroke="#B39CFF" stroke-width="10"/><circle cx="340" cy="170" r="150" fill="none" stroke="#45C1E6" stroke-width="10"/><circle cx="260" cy="310" r="150" fill="none" stroke="#F0B445" stroke-width="10"/></svg></body></html>`);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1536, height: 864 }, deviceScaleFactor: 1.25 });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const cdp = await ctx.newCDPSession(page);
  const frames = []; let n = 0;
  cdp.on('Page.screencastFrame', async f => {
    const file = `f${String(++n).padStart(6, '0')}.jpg`;
    fs.writeFileSync(path.join(OUT, 'frames', file), Buffer.from(f.data, 'base64'));
    frames.push({ file, t: f.metadata.timestamp });
    try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch (e) {}
  });
  const marks = [];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let mx = 768, my = 432;
  async function moveTo(x, y, ms = 700) {
    const steps = Math.max(8, Math.round(ms / 16));
    for (let i = 1; i <= steps; i++) { const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; await page.mouse.move(mx + (x - mx) * e, my + (y - my) * e); await sleep(ms / steps); }
    mx = x; my = y;
  }
  async function box(sel) { const el = await page.waitForSelector(sel, { timeout: 15000 }); await el.scrollIntoViewIfNeeded(); return el.boundingBox(); }
  async function hover(sel, ms = 700, dx = .5, dy = .5) { const b = await box(sel); await moveTo(b.x + b.width * dx, b.y + b.height * dy, ms); return b; }
  async function click(sel, ms = 700) { await hover(sel, ms); await sleep(150); await page.mouse.down(); await sleep(80); await page.mouse.up(); await sleep(250); }
  async function scrollTo(y, ms = 1200) {
    await page.evaluate(([y, ms]) => new Promise(res => { const s = scrollY, t0 = performance.now(); const f = t => { const k = Math.min(1, (t - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; scrollTo(0, s + (y - s) * e); k < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); }), [y, ms]);
  }
  async function scrollToEl(sel, offset = 90, ms = 1200) { const y = await page.evaluate(([s, o]) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top + scrollY - o : 0; }, [sel, offset]); await scrollTo(y, ms); }
  async function scrollInside(sel, top, ms = 1400) {
    await page.evaluate(([s, top, ms]) => new Promise(res => { const el = document.querySelector(s); const s0 = el.scrollTop, t0 = performance.now(); const f = t => { const k = Math.min(1, (t - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; el.scrollTop = s0 + (top - s0) * e; k < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); }), [sel, top, ms]);
  }
  async function nav(view) { await click(`nav.tabs a[href="#${view}"]`, 600); await sleep(700); await scrollTo(0, 300); }
  async function typeInto(sel, text) { await click(sel, 500); await page.keyboard.press('Control+A'); await page.keyboard.type(text, { delay: 28 }); }
  async function scene(id, fn) {
    const t0 = Date.now(); marks.push({ id, t: t0 / 1000 });
    console.log('scene', id, DUR[id]);
    await fn();
    const left = DUR[id] * 1000 - (Date.now() - t0);
    if (left > 0) await sleep(left); else console.log('  overran by', -left, 'ms');
  }

  await page.goto(card('title')); await page.waitForTimeout(800);
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  await sleep(300);

  await scene('title', async () => { await page.mouse.move(1500, 800); await sleep(1500); });

  await scene('overview', async () => {
    await page.goto(BASE + '#prioritize'); await page.waitForSelector('#matrix svg'); await sleep(1200);
    await hover('.kpis .kpi:nth-child(1)', 900); await sleep(3500);
    await hover('header.top .runinfo', 1200); await sleep(6000);
    await hover('nav.tabs a[href="#triangulation"]', 900); await sleep(3000);
    await hover('nav.tabs a[href="#method"]', 1200); await sleep(2500);
  });

  await scene('engine', async () => {
    await nav('run'); await sleep(2000);
    await click('#runbtn', 800); await sleep(1500);
    await hover('#live', 900);
    // follow the live log as it streams
    for (let i = 0; i < 12; i++) { await sleep(4200); await page.evaluate(() => { const l = document.querySelector('#live'); if (l && !l.hidden) scrollTo({ top: Math.max(0, l.getBoundingClientRect().bottom + scrollY - innerHeight + 40), behavior: 'smooth' }); }); }
    await page.waitForFunction(() => document.querySelector('#live') && document.querySelector('#live').hidden === false, null, { timeout: 5000 }).catch(() => {});
  });

  await scene('evals', async () => {
    await page.waitForFunction(() => !document.querySelector('#runbtn') || !document.querySelector('#runbtn').disabled, null, { timeout: 60000 }).catch(() => {});
    await sleep(800); await scrollTo(0, 600);
    await scrollToEl('.evals', 120, 1200); await hover('.evals .ev:nth-child(14)', 900); await sleep(2200);
    await hover('.evals .ev:nth-child(4)', 800); await sleep(1800);
    await hover('.evals .ev:nth-child(12)', 800); await sleep(2000);
    await hover('.evals .ev:nth-child(2)', 800); await sleep(2500);
    await hover('.evals .ev:nth-child(1)', 800); await sleep(2500);
    await hover('[data-view="run"] .steps .step:nth-child(9)', 1100); await sleep(2500);
    await scrollTo(1400, 3000); await sleep(1500);
    await hover('.evals .ev:nth-child(13)', 900);
  });

  await scene('matrix', async () => {
    await nav('prioritize'); await scrollToEl('#matrix', 150, 900);
    const b = await box('#matrix svg');
    await moveTo(b.x + b.width * .5, b.y + b.height * .97, 1000); await sleep(3500);           // x axis
    await moveTo(b.x + b.width * .03, b.y + b.height * .45, 1000); await sleep(4500);          // y axis
    await moveTo(b.x + b.width * .9, b.y + b.height * .1, 1000); await sleep(3200);            // do now
    await moveTo(b.x + b.width * .2, b.y + b.height * .1, 1000); await sleep(5000);            // validate fast
    await hover('.bub[data-id="TH-14"]', 900); await sleep(2500);
    await scrollToEl('[data-view="prioritize"] table', 140, 1500); await sleep(1500);
  });

  await scene('patch', async () => {
    await click('tr[data-id="TH-14"]', 800); await sleep(700);
    await scrollToEl('#detail', 80, 900);
    await hover('#detail h2', 700); await sleep(3000);
    await hover('#detail .pillar.p-do', 900); await sleep(5500);
    await hover('#detail .chain .n:nth-child(1)', 900); await sleep(2500);
    await hover('#detail .chain .n:nth-child(3)', 600); await sleep(2500);
    await hover('#detail .chain .n:nth-child(5)', 600); await sleep(2300);
    await hover('#detail .chain .n:nth-child(7)', 600); await sleep(3000);
    await hover('#detail .chain .n.final', 600); await sleep(2500);
    await scrollInside('#detail', 520, 1600); await sleep(1500);
    await scrollInside('#detail', 880, 1600); await hover('#detail .callout >> nth=1', 800); await sleep(6000);
  });

  await scene('globex', async () => {
    await scrollInside('#detail', 0, 600);
    await click('tr[data-id="TH-18"]', 900); await sleep(800);
    await hover('#detail h2', 600); await sleep(4500);
    await scrollInside('#detail', 760, 1600); await sleep(800);
    await hover('#detail .callout', 700); await sleep(4000);
    await scrollInside('#detail', 900, 1000); await hover('#detail .callout >> nth=1', 700); await sleep(5000);
  });

  await scene('override', async () => {
    await scrollInside('#detail', 0, 400);
    await click('tr[data-id="TH-02"]', 900); await sleep(600);
    await page.evaluate(() => { const d = document.querySelector('#detail'); const f = document.querySelector('#ovr'); d.scrollTop = f.offsetTop - 160; });
    await sleep(500);
    await click('#ovr-w', 600); await page.keyboard.press('Control+A'); await page.keyboard.type('6', { delay: 120 });
    await typeInto('#ovr-r', 'Eng spike: reuse the policy engine scopes model');
    await sleep(400); await click('#ovr button[type=submit]', 700); await sleep(2500);
    await scrollTo(0, 800); await scrollToEl('[data-view="prioritize"] table', 140, 1200);
    await hover('tr[data-id="TH-02"]', 900);
  });

  await scene('triangulation', async () => {
    await nav('triangulation'); await sleep(800);
    await hover('[data-view="triangulation"] .bub[data-id="TH-02"]', 900); await sleep(8000);
    await hover('[data-view="triangulation"] .rows .row:nth-child(2)', 1100); await sleep(4000);
    await hover('[data-view="triangulation"] .rows .row:nth-child(3)', 800); await sleep(4000);
  });

  await scene('risks', async () => {
    await nav('risks'); await sleep(600);
    await hover('[data-view="risks"] .kpis', 800); await sleep(3500);
    await hover('[data-view="risks"] .rows .row:nth-child(1)', 800); await sleep(3000);
    await hover('[data-view="risks"] .rows .row:nth-child(3)', 800); await sleep(2500);
    await scrollTo(700, 2500); await sleep(2000);
  });

  await scene('deps', async () => {
    await nav('dependencies'); await sleep(700);
    const b = await box('.depgraph svg');
    await moveTo(b.x + 120, b.y + 45, 900); await sleep(6000);
    await moveTo(b.x + 420, b.y + 45, 900); await moveTo(b.x + 720, b.y + 45, 900); await sleep(5000);
    await moveTo(b.x + 120, b.y + 140, 900); await sleep(4000);
    await scrollToEl('[data-view="dependencies"] table', 140, 1800); await hover('[data-view="dependencies"] tbody tr:nth-child(1)', 800);
  });

  await scene('cab', async () => {
    await nav('cab'); await sleep(600);
    await hover('[data-view="cab"] .doc .ln.k-pain', 900); await sleep(3500);
    await hover('[data-view="cab"] .doc .ln.k-ask', 700); await sleep(2000);
    await hover('[data-view="cab"] .doc .ln.k-commitment', 900); await sleep(2500);
    await click('[data-view="cab"] .seg button:nth-child(3)', 800); await sleep(1500);
  });

  await scene('pbr', async () => {
    await nav('pbr'); await sleep(600);
    await hover('[data-view="pbr"] .panel h2', 800); await sleep(4500);
    await click('[data-view="pbr"] details.facts summary', 800); await sleep(3500);
    await hover('[data-view="pbr"] .kpis .kpi:nth-child(3)', 900); await sleep(4000);
    await scrollTo(900, 2500); await sleep(1500);
    const d = await page.$('[data-view="pbr"] .panel > details summary');
    if (d) { await click('[data-view="pbr"] .panel > details summary', 900); await sleep(1500); }
  });

  await scene('executive', async () => {
    await nav('executive'); await sleep(700);
    await hover('[data-view="executive"] .lc .col:nth-child(1) .mod', 900); await sleep(6000);
    await scrollToEl('.alloc', 160, 1400);
    await hover('.alloc .ar:nth-child(1)', 800); await sleep(5000);
    await hover('.alloc .ar:last-child', 900); await sleep(3000);
  });

  await scene('ask', async () => {
    await nav('ask'); await sleep(500);
    await typeInto('#askq', 'Which roadmap commitments depend on a single account?');
    await click('#askf button[type=submit]', 600);
    await page.waitForSelector('#askout .answer', { timeout: 60000 }); await sleep(1200);
    await hover('#askout .answer', 800); await sleep(3500);
    await scrollToEl('#askout .quote', 220, 1600); await sleep(2500);
    const s = await page.$('#askout > details summary'); if (s) { await click('#askout > details summary', 800); await sleep(600); await scrollToEl('#askout pre.code', 200, 1400); }
  });

  await scene('method', async () => { await nav('method'); await sleep(800); await scrollTo(500, 3000); await sleep(1500); await scrollTo(1100, 3000); });

  await scene('close', async () => { await page.goto(card('close')); await page.mouse.move(1500, 820); await sleep(2000); });

  marks.push({ id: 'end', t: Date.now() / 1000 });
  await cdp.send('Page.stopScreencast');
  await sleep(300);
  fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify({ frames, marks }, null, 0));
  console.log('frames', frames.length, 'errors', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });

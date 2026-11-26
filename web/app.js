/* SignalCore web client. Talks to the FastAPI backend, or reads window.SNAPSHOT in the standalone build. */
(() => {
'use strict';
const SNAP = window.SNAPSHOT || null;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const money = v => { v = +v || 0; const a = Math.abs(v); return a >= 1e6 ? '$' + (v / 1e6).toFixed(a >= 1e7 ? 1 : 2) + 'M' : a >= 1e3 ? '$' + Math.round(v / 1e3) + 'K' : '$' + Math.round(v); };
const pct = v => Math.round((+v || 0) * 100) + '%';
const num = v => (+v || 0).toLocaleString('en-US', {maximumFractionDigits: 0});
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const ARCH = {high_signal: 'High signal', silent_churn: 'Silent churn risk', commercial_mirage: 'Commercial mirage', vocal_minority: 'Vocal minority', emerging: 'Emerging'};
const ACOL = {high_signal: '--hs', silent_churn: '--sc', commercial_mirage: '--cm', vocal_minority: '--vm', emerging: '--em'};
const PROFILE = {expedite: 'Expedite: cost is being incurred now', fixed_date: 'Fixed date: one dated renewal or deal dominates', standard: 'Standard: cost accrues steadily', intangible: 'Intangible: little measurable cost today'};
const SRC = {gong: 'Gong', zendesk: 'Zendesk', jira: 'Jira', idea_portal: 'Idea portal', cab: 'CAB', cab_note: 'CAB note'};
const chip = a => `<span class="chip a-${a}">${ARCH[a] || a}</span>`;
let S = null, selected = null, cabSel = null, pbrSel = 'portfolio', polling = null;

function toast(msg, err) { const t = $('#toast'); t.textContent = msg; t.className = 'toast on' + (err ? ' err' : ''); clearTimeout(toast.t); toast.t = setTimeout(() => t.className = 'toast', 2600); }
function copy(text, msg) {
  const fallback = () => { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); toast(msg); } catch (e) { toast('Select the text to copy', true); } ta.remove(); };
  try { navigator.clipboard.writeText(text).then(() => toast(msg), fallback); } catch (e) { fallback(); }
}

// ------------------------------------------------------------------ API
const api = {
  async state() { if (SNAP) return SNAP.state; const r = await fetch('/api/state'); if (!r.ok) throw new Error(await r.text()); return r.json(); },
  async ask(q) {
    if (SNAP) { const a = SNAP.state.asks.find(x => x.question.trim().toLowerCase() === q.trim().toLowerCase()); if (!a) throw new Error('This standalone copy replays recorded questions only. Pick one of the suggestions, or run the live app to ask anything.'); return a; }
    const r = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question: q})});
    if (!r.ok) throw new Error((await r.json()).detail || 'Ask failed'); return r.json();
  },
  async run(mode) { const r = await fetch('/api/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode})}); if (!r.ok) throw new Error((await r.json()).detail); return r.json(); },
  async events(id, after) { return (await fetch(`/api/runs/${id}/events?after=${after}`)).json(); },
  async override(body) { const r = await fetch('/api/overrides', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); if (!r.ok) throw new Error(JSON.stringify((await r.json()).detail)); return r.json(); },
};

// ------------------------------------------------------------------ shared bits
const TH = () => Object.fromEntries(S.themes.map(t => [t.id, t]));
const MOD = () => Object.fromEntries(S.modules.map(m => [m.id, m]));
const codThreshold = () => { const v = S.themes.map(t => t.cod).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : 0; };
const EV_T = 60;
function quadrant(t) { const hi = t.cod >= codThreshold(); return t.evidence >= EV_T ? (hi ? 'Do now' : 'Schedule') : (hi ? 'Validate fast' : 'Park'); }
const QDESC = {'Do now': 'Strong evidence and high Cost of Delay. Staff it.', 'Validate fast': 'High Cost of Delay but weak evidence. Run a cheap test before building.',
  'Schedule': 'Strong evidence, lower Cost of Delay. Plan it in.', 'Park': 'Weak evidence and low Cost of Delay. Acknowledge and revisit.'};
function kpis(items) { return `<div class="kpis">${items.map(([v, l, s]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`).join('')}</div>`; }
function head(eyebrow, title, lede, right = '') { return `<div class="viewhead"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${lede ? `<p class="lede">${lede}</p>` : ''}</div>${right}</div>`; }
// minimal markdown for agent answers: paragraphs, bullet lists, pipe tables, **bold**; escapes first
function mdAnswer(text) {
  const inline = t => citeChips(t).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const lines = String(text).split('\n'), out = [];
  for (let i = 0; i < lines.length;) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {
      const rows = []; while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const body = rows.filter(r => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      const [h, ...rest] = body;
      out.push(`<div class="tablewrap"><table><thead><tr>${cells(h).map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rest.map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
    } else if (/^\s*[-*] /.test(l)) {
      const items = []; while (i < lines.length && /^\s*[-*] /.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*] /, ''));
      out.push(`<ul>${items.map(x => `<li>${inline(x)}</li>`).join('')}</ul>`);
    } else if (l.trim()) { out.push(`<p>${inline(l)}</p>`); i++; }
    else i++;
  }
  return out.join('');
}
function citeChips(text) { return esc(text).replace(/\[((?:FB-\d+|CAB-M\d+-L\d+)(?:,\s*(?:FB-\d+|CAB-M\d+-L\d+))*)\]/g, (_, ids) => ids.split(/,\s*/).map(i => `<span class="cid" title="Cited source">${i}</span>`).join(' ')); }

// label placement: greedy, avoids overlaps
function placeLabels(points, W, H, m) {
  const boxes = points.map(p => ({x: p.x - p.r, y: p.y - p.r, w: 2 * p.r, h: 2 * p.r}));
  const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  return points.map(p => {
    const w = p.label.length * 6.4 + 4, h = 14;
    const cands = [[p.x + p.r + 4, p.y - 7, 'start'], [p.x - p.r - 4 - w, p.y - 7, 'end'], [p.x - w / 2, p.y - p.r - 16, 'middle'], [p.x - w / 2, p.y + p.r + 3, 'middle'],
      [p.x + p.r + 4, p.y - 22, 'start'], [p.x + p.r + 4, p.y + 8, 'start'], [p.x - p.r - 4 - w, p.y - 22, 'end'], [p.x - p.r - 4 - w, p.y + 8, 'end']];
    for (const [x, y, anchor] of cands) {
      const b = {x, y, w, h};
      if (x < m.l || x + w > W - 4 || y < 2 || y + h > H - m.b) continue;
      if (boxes.some(o => hit(b, o))) continue;
      boxes.push(b);
      return {x: anchor === 'start' ? x : anchor === 'end' ? x + w : x + w / 2, y: y + 11, anchor};
    }
    return null;
  });
}

// ------------------------------------------------------------------ PRIORITIZE
function matrixSVG() {
  const W = 760, H = 440, m = {l: 64, r: 16, t: 16, b: 46};
  const cods = S.themes.map(t => Math.max(t.cod, 100));
  const y0 = Math.floor(Math.log10(Math.min(...cods)) * 2) / 2, y1 = Math.ceil(Math.log10(Math.max(...cods)) * 2) / 2;
  const x = v => m.l + v / 100 * (W - m.l - m.r), y = v => m.t + (1 - (Math.log10(Math.max(v, 100)) - y0) / (y1 - y0)) * (H - m.t - m.b);
  const thr = codThreshold(), maxcd3 = Math.max(...S.themes.map(t => t.cd3), 1);
  const line = css('--line'), muted = css('--muted');
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Themes by Evidence Score and Cost of Delay">`;
  const qx = x(EV_T), qy = y(thr);
  s += `<rect x="${qx}" y="${m.t}" width="${W - m.r - qx}" height="${qy - m.t}" fill="${css('--hs')}" opacity=".07"/>`;
  s += `<rect x="${m.l}" y="${m.t}" width="${qx - m.l}" height="${qy - m.t}" fill="${css('--sc')}" opacity=".06"/>`;
  [0, 20, 40, 60, 80, 100].forEach(v => s += `<line x1="${x(v)}" x2="${x(v)}" y1="${m.t}" y2="${H - m.b}" stroke="${line}"/><text x="${x(v)}" y="${H - m.b + 16}" fill="${muted}" font-size="11" text-anchor="middle" font-family="IBM Plex Mono,monospace">${v}</text>`);
  for (let e = Math.ceil(y0); e <= y1; e += 0.5) { const v = 10 ** e; if (e % 1 && (y1 - y0) > 3) continue; s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${line}"/><text x="${m.l - 8}" y="${y(v) + 4}" fill="${muted}" font-size="11" text-anchor="end" font-family="IBM Plex Mono,monospace">${money(v)}</text>`; }
  s += `<line x1="${qx}" x2="${qx}" y1="${m.t}" y2="${H - m.b}" stroke="${css('--line2')}" stroke-dasharray="4 4"/><line x1="${m.l}" x2="${W - m.r}" y1="${qy}" y2="${qy}" stroke="${css('--line2')}" stroke-dasharray="4 4"/>`;
  const ql = (tx, ty, t, anchor, col) => s += `<text x="${tx}" y="${ty}" fill="${col}" font-size="11.5" font-weight="600" text-anchor="${anchor}" font-family="Space Grotesk,sans-serif" opacity=".9">${t}</text>`;
  ql(W - m.r - 6, m.t + 14, 'DO NOW', 'end', css('--hs')); ql(m.l + 6, m.t + 14, 'VALIDATE FAST', 'start', css('--sc'));
  ql(W - m.r - 6, H - m.b - 8, 'SCHEDULE', 'end', muted); ql(m.l + 6, H - m.b - 8, 'PARK', 'start', css('--faint'));
  s += `<text x="${(m.l + W - m.r) / 2}" y="${H - 8}" fill="${muted}" font-size="11.5" text-anchor="middle">Evidence Score (confidence the theme is real and material) →</text>`;
  s += `<text x="14" y="${(m.t + H - m.b) / 2}" fill="${muted}" font-size="11.5" text-anchor="middle" transform="rotate(-90 14 ${(m.t + H - m.b) / 2})">Cost of Delay per week (log) →</text>`;
  const pts = [...S.themes].sort((a, b) => b.cd3 - a.cd3).map(t => ({t, x: x(t.evidence), y: y(t.cod), r: 6 + Math.sqrt(t.cd3 / maxcd3) * 20, label: shortTitle(t)}));
  const labels = placeLabels(pts, W, H, m);
  [...pts].reverse().forEach((p, i) => { const col = css(ACOL[p.t.archetype]); s += `<g class="bub${p.t.id === selected ? ' sel' : ''}" data-id="${p.t.id}" tabindex="0" role="button" aria-label="${esc(p.t.title)}"><circle cx="${p.x}" cy="${p.y}" r="${p.r}" fill="${col}" fill-opacity=".25" stroke="${col}" stroke-width="1.3"/><text x="${p.x}" y="${p.y + 4}" fill="${css('--fg')}" font-size="10" text-anchor="middle" font-family="IBM Plex Mono,monospace">${p.t.rank}</text></g>`; });
  pts.forEach((p, i) => { const l = labels[i]; if (l) s += `<text x="${l.x}" y="${l.y}" font-size="11" fill="${css('--fg')}" text-anchor="${l.anchor}" pointer-events="none">${esc(p.label)}</text>`; });
  return s + '</svg>';
}
function shortTitle(t) { return t.title.length > 30 ? t.title.slice(0, 28) + '…' : t.title; }

function renderPrioritize() {
  const v = $('[data-view="prioritize"]');
  const tot = S.themes.reduce((a, t) => a + t.cod, 0), adj = S.themes.reduce((a, t) => a + t.cod_adj, 0);
  const doNow = S.themes.filter(t => quadrant(t) === 'Do now'), val = S.themes.filter(t => quadrant(t) === 'Validate fast');
  const blocked = S.themes.filter(t => t.blocked_weeks > 0);
  v.innerHTML = head('Prioritize · Cost of Delay × Evidence', 'What to build next, and why',
    'Each theme’s Cost of Delay (what one more week of waiting costs) is discounted by its Evidence Score, then divided by the weeks to deliver it, including weeks blocked by other teams. That is CD3, and the backlog is ranked by it.') +
    kpis([[S.themes.length, 'Themes scored', `${S.counts.feedback.toLocaleString()} voices · ${S.counts.cab_meetings} CAB notes`], [money(tot), 'Cost of Delay per week', 'before confidence'],
      [money(adj), 'Confidence-adjusted CoD per week', 'what the evidence supports'], [doNow.length, 'Do now', doNow.map(t => t.id).join(' · ')],
      [val.length, 'Validate fast', 'high CoD, weak evidence'], [blocked.length, 'Blocked by other teams', blocked.map(t => t.deps.epic).join(' · ')]]) +
    `<div class="grid g-main"><div class="grid" style="align-content:start">
      <div class="panel chart"><header><h2>Evidence × Cost of Delay</h2><p>Bubble size = CD3 · number = priority rank</p></header><div id="matrix">${matrixSVG()}</div>
        <div class="legend">${Object.keys(ARCH).map(a => `<span><i style="background:var(${ACOL[a]})"></i>${ARCH[a]}</span>`).join('')}<span class="faint">Quadrant lines: evidence ${EV_T}, CoD median ${money(codThreshold())}/wk</span></div></div>
      <div class="panel"><header><h2>Backlog ranked by CD3</h2><p>CD3 = confidence-adjusted CoD ÷ weeks to deliver</p></header>
        <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>Theme</th><th>Evidence</th><th>Pattern</th><th class="num">CoD/wk</th><th class="num">× conf.</th><th class="num">Weeks</th><th class="num">CD3</th><th>Profile</th></tr></thead><tbody>
        ${S.themes.map(t => `<tr class="click${t.id === selected ? ' sel' : ''}" data-id="${t.id}" tabindex="0"><td class="num">${t.rank}</td>
          <td><div style="font-weight:500">${esc(t.title)}</div><div class="mono faint" style="font-size:11px">${t.id} · ${esc((MOD()[t.module] || {}).name || '')} · ${quadrant(t)}</div></td>
          <td><div class="score"><b>${t.evidence}</b><span class="bar"><i style="width:${t.evidence}%;background:var(${ACOL[t.archetype]})"></i></span></div></td>
          <td>${chip(t.archetype)}</td><td class="num">${money(t.cod)}</td><td class="num">${money(t.cod_adj)}</td>
          <td class="num">${t.effort}${t.blocked_weeks ? `<span class="faint">+${Math.round(t.blocked_weeks)}</span>` : ''}</td><td class="num"><b>${num(t.cd3)}</b></td>
          <td><span class="tag">${t.profile.replace('_', ' ')}</span></td></tr>`).join('')}</tbody></table></div></div>
    </div><div class="panel sticky" id="detail" aria-live="polite"></div></div>`;
  $$('.bub', v).forEach(g => { g.onclick = () => select(g.dataset.id); g.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(g.dataset.id); } }; });
  $$('tr.click', v).forEach(r => { r.onclick = () => select(r.dataset.id); r.onkeydown = e => { if (e.key === 'Enter') select(r.dataset.id); }; });
  renderDetail();
}

function renderDetail() {
  const t = TH()[selected]; if (!t) return;
  const d = $('#detail'); const mod = MOD()[t.module] || {};
  const sk = t.skeptic; const skOk = !sk || sk.verdict === 'stands';
  const cp = t.cod_parts;
  d.innerHTML = `<div class="eyebrow">${t.id} · ${esc(mod.name || '')} · <span class="mono">${esc(t.feature || '')}</span></div>
    <h2 style="font-size:20px;margin-top:4px">${esc(t.title)}</h2><p class="muted" style="margin:6px 0 0">${esc(t.stmt)}</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">${chip(t.archetype)}<span class="tag">${quadrant(t)}</span><span class="tag">${t.profile.replace('_', ' ')}</span></div>
    <p class="muted" style="margin:8px 0 0;font-size:12.5px">${QDESC[quadrant(t)]}</p>
    <div class="chain">
      <div class="n"><small>Evidence</small><b>${t.evidence}</b></div><span class="op">×</span>
      <div class="n"><small>CoD / week</small><b>${money(t.cod)}</b></div><span class="op">=</span>
      <div class="n"><small>Adjusted</small><b>${money(t.cod_adj)}</b></div><span class="op">÷</span>
      <div class="n"><small>Weeks</small><b>${t.effort}${t.blocked_weeks ? '+' + Math.round(t.blocked_weeks) : ''}</b></div><span class="op">=</span>
      <div class="n final"><small>CD3 · rank</small><b>${num(t.cd3)} · #${t.rank}</b></div></div>
    <h3>Cost of Delay breakdown</h3>
    <div class="tablewrap"><table><tbody>
      <tr><td>Retention risk</td><td class="muted">ARR × ${pct(cp.p_churn)} churn uplift ÷ weeks to renewal</td><td class="num">${money(cp.retention)}</td></tr>
      <tr><td>Deals waiting</td><td class="muted">open deals × 25% win uplift ÷ weeks to close; lost deals echo</td><td class="num">${money(cp.pipeline)}</td></tr>
      <tr><td>Urgency profile</td><td class="muted" colspan="2">${PROFILE[t.profile]}</td></tr></tbody></table></div>
    ${t.opps.length ? `<details style="margin-top:6px"><summary>${t.opps.length} linked deals</summary><div class="tablewrap"><table><tbody>${t.opps.map(o => `<tr><td class="mono">${o.id}</td><td>${esc(o.account_name || o.account)}</td><td>${o.type}</td><td>${o.status}</td><td class="num">${money(o.amount)}</td><td class="mono">${o.close}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
    <div class="pillars">
      <div class="pillar p-say"><div class="ph"><b>Say</b><span class="mono">${(+t.Q).toFixed(2)}</span></div><dl><dt>Mentions</dt><dd>${t.mentions}</dd><dt>Accounts</dt><dd>${t.accounts}</dd><dt>Urgency</dt><dd>${t.urgency}/5</dd><dt>Workarounds</dt><dd>${pct(t.workaround)}</dd></dl></div>
      <div class="pillar p-do"><div class="ph"><b>Do</b><span class="mono">${(+t.B).toFixed(2)}</span></div><dl><dt>Abandon (them)</dt><dd>${pct(t.abandon)}</dd><dt>Abandon (others)</dt><dd>${pct(t.abandon_base)}</dd><dt>Use feature</dt><dd>${pct(t.coverage)}</dd><dt>Cohort decline</dt><dd>${pct(t.decline)}</dd></dl></div>
      <div class="pillar p-pay"><div class="ph"><b>Pay</b><span class="mono">${(+t.C).toFixed(2)}</span></div><dl><dt>$ influenced</dt><dd>${money(t.influenced)}</dd><dt>Top account</dt><dd>${pct(t.top_share)}</dd><dt>ICP share</dt><dd>${pct(t.icp_share)}</dd><dt>Deals</dt><dd>${t.opps.length}</dd></dl></div></div>
    <div class="formula mono faint" style="font-size:11.5px">100 × (0.30·${(+t.Q).toFixed(2)} + 0.35·${(+t.B).toFixed(2)} + 0.35·${(+t.C).toFixed(2)}) × rules ${(+t.rule_penalty).toFixed(2)} × skeptic ${(+t.skeptic_penalty).toFixed(2)} = ${t.evidence}</div>
    <div class="callout ${t.rule_penalty < 1 ? '' : 'ok'}" style="margin-top:10px"><b>Rule checks:</b> ${esc(t.rule_notes)}</div>
    <div class="callout ${skOk ? 'ok' : ''}" style="margin-top:8px"><b>Skeptic Agent · ${esc(sk ? sk.verdict : 'not run')}${t.skeptic_penalty < 1 ? ` · ×${(+t.skeptic_penalty).toFixed(2)}` : ''}:</b> ${esc(sk ? sk.reason : '')}
      ${sk && sk.checks && sk.checks.length ? `<details style="margin-top:6px"><summary>${sk.checks.length} checks it ran</summary>${sk.checks.map(c => `<div style="margin-top:6px"><div class="muted">${esc(c.question)}</div><div>${esc(c.finding)}</div></div>`).join('')}</details>` : ''}
      ${t.skeptic_cited && t.skeptic_cited.length ? `<div style="margin-top:6px">${t.skeptic_cited.slice(0, 10).map(i => `<span class="cid">${esc(i)}</span>`).join(' ')}</div>` : ''}</div>
    ${t.deps && t.deps.epic ? `<h3 style="margin-top:14px">Delivery dependencies</h3><p style="margin:4px 0 0"><span class="mono">${t.deps.path.join(' → ')}</span></p>
      <p class="muted" style="margin:4px 0 0;font-size:12.5px">${t.blocked_weeks ? `Blocked by ${t.deps.blockers.join(', ')}: ${Math.round(t.blocked_weeks)} weeks of other teams’ work on the critical path, added to the duration in CD3.` : 'No unfinished blockers.'}</p>` : ''}
    ${t.gpl.length ? `<h3 style="margin-top:14px">On the roadmap</h3>${t.gpl.map(g => { const x = S.gpl.find(r => r.item_id === g); return `<div class="muted" style="font-size:13px;margin-top:4px"><span class="mono">${g}</span> ${esc(x.title)} · ${x.status} · ${x.target_quarter}</div>`; }).join('')}` : ''}
    <h3 style="margin-top:14px">PM estimate override</h3>
    <form class="inline" id="ovr" style="margin-top:6px"><label>Build weeks (${esc(t.feature)})<input class="text" id="ovr-w" type="number" min="0.5" max="104" step="0.5" value="${t.effort}" style="width:110px"></label>
      <label style="flex:1 1 200px">Reason (logged)<input class="text" id="ovr-r" type="text" placeholder="e.g. Eng re-estimated after spike" required minlength="5"></label>
      <button class="btn" type="submit" ${SNAP ? 'disabled title="Available in the live app"' : ''}>Recalculate</button></form>
    <p class="note">Estimate confidence: ${esc(t.effort_conf)}. Changing it recomputes CD3 and ranks for this run without calling a model.</p>
    <h3 style="margin-top:14px">Representative voices</h3>
    ${t.quotes.map(q => `<div class="quote"><p>${esc(q.body.length > 420 ? q.body.slice(0, 420) + '…' : q.body)}</p><footer><span class="tag">${SRC[q.source] || q.source} ${esc(q.ref)}</span><span>${esc(q.account || 'unresolved account')}${q.segment ? ' · ' + q.segment : ''}</span><span class="mono">${q.at}</span><span>urgency ${q.urgency}</span></footer></div>`).join('')}`;
  const f = $('#ovr');
  if (f) f.onsubmit = async e => {
    e.preventDefault();
    try { const r = await api.override({theme_id: t.id, feature_key: t.feature, effort_weeks: +$('#ovr-w').value, reason: $('#ovr-r').value}); S = {...S, ...r.state}; toast(`Recalculated: ${t.id} is now #${TH()[t.id].rank}`); renderAll(); }
    catch (err) { toast(err.message, true); }
  };
}
function select(id) { selected = id; renderPrioritize(); if (window.innerWidth < 1050) $('#detail').scrollIntoView({behavior: 'smooth'}); }

// ------------------------------------------------------------------ TRIANGULATION
function renderTriangulation() {
  const v = $('[data-view="triangulation"]');
  const W = 720, H = 400, m = {l: 70, r: 16, t: 16, b: 44};
  const x = b => m.l + b * (W - m.l - m.r), ly = v => Math.log10(Math.max(v, 3e4)), y0 = 4.5, y1 = 7.4, y = v => m.t + (1 - (ly(v) - y0) / (y1 - y0)) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Themes by behavioural friction and revenue influenced">`;
  const line = css('--line'), muted = css('--muted');
  [0, .25, .5, .75, 1].forEach(b => s += `<line x1="${x(b)}" x2="${x(b)}" y1="${m.t}" y2="${H - m.b}" stroke="${line}"/><text x="${x(b)}" y="${H - m.b + 16}" fill="${muted}" font-size="11" text-anchor="middle" font-family="IBM Plex Mono,monospace">${b.toFixed(2)}</text>`);
  [1e5, 1e6, 1e7].forEach(c => s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(c)}" y2="${y(c)}" stroke="${line}"/><text x="${m.l - 8}" y="${y(c) + 4}" fill="${muted}" font-size="11" text-anchor="end" font-family="IBM Plex Mono,monospace">${money(c)}</text>`);
  s += `<text x="${(m.l + W - m.r) / 2}" y="${H - 8}" fill="${muted}" font-size="11.5" text-anchor="middle">Behavioural friction (Do pillar) →</text><text x="14" y="${(m.t + H - m.b) / 2}" fill="${muted}" font-size="11.5" text-anchor="middle" transform="rotate(-90 14 ${(m.t + H - m.b) / 2})">Revenue influenced →</text>`;
  const pts = [...S.themes].sort((a, b) => b.accounts - a.accounts).map(t => ({t, x: x(t.B), y: y(t.influenced), r: 5 + Math.sqrt(t.accounts) * 2, label: shortTitle(t)}));
  const lab = placeLabels(pts, W, H, m);
  pts.forEach(p => { const c = css(ACOL[p.t.archetype]); s += `<g class="bub" data-id="${p.t.id}"><circle cx="${p.x}" cy="${p.y}" r="${p.r}" fill="${c}" fill-opacity=".25" stroke="${c}"/></g>`; });
  pts.forEach((p, i) => { if (lab[i]) s += `<text x="${lab[i].x}" y="${lab[i].y}" font-size="11" fill="${css('--fg')}" text-anchor="${lab[i].anchor}" pointer-events="none">${esc(p.label)}</text>`; });
  s += '</svg>';
  const PIL = {gong: 'Say', zendesk: 'Say', jira: 'Say', idea_portal: 'Say', cab: 'Say', pendo: 'Do', sfdc: 'Pay'};
  const th = TH();
  const audit = S.gpl.map(g => {
    const t = th[g.theme_id]; const pil = [...new Set(g.cited_sources.split(',').map(c => PIL[c]))];
    let cls = 'ok', msg;
    if (!t) { cls = 'warn'; msg = 'No matching theme found in customer evidence.'; }
    else if (g.status !== 'proposed' && t.evidence < 50) { cls = 'bad'; msg = `${g.status === 'in_build' ? 'In build' : 'Committed'} on weak evidence: ${ARCH[t.archetype].toLowerCase()}, score ${t.evidence}, CD3 rank ${t.rank} of ${S.themes.length}.`; }
    else if (pil.length < 3 && t.evidence >= 60) { cls = 'warn'; msg = `Under-cited: the PRD cites only ${pil.join(' + ')}; evidence across all three pillars scores ${t.evidence}.`; }
    else if (t.evidence < 60) { cls = 'warn'; msg = `Evidence still forming (score ${t.evidence}). Validate before committing.`; }
    else msg = `Triangulated: score ${t.evidence}, CD3 rank ${t.rank}.`;
    return `<div class="row"><div class="top"><div><span class="mono faint">${g.item_id}</span> <b>${esc(g.title)}</b></div><span class="mono muted" style="font-size:12px">${g.status} · ${g.target_quarter}</span></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="muted" style="font-size:12px">PRD cites:</span>${g.cited_sources.split(',').map(c => `<span class="tag">${c}</span>`).join('')}${t ? `<span style="margin-left:auto">${t.id} ${chip(t.archetype)}</span>` : ''}</div>
      <div><span class="tag ${cls}">${cls === 'ok' ? 'pass' : cls === 'bad' ? 'fail' : 'check'}</span> <span style="font-size:13px">${esc(msg)}</span></div></div>`;
  }).join('');
  v.innerHTML = head('Triangulation · Say, Do, Pay', 'Does behaviour and revenue back what customers say?', 'Friction comes from product telemetry; revenue from linked accounts and deals. Loud themes with no friction and concentrated revenue sit bottom-left.') +
    `<div class="grid g-2"><div class="panel chart"><header><h2>Friction vs revenue</h2><p>Bubble size = accounts</p></header>${s}<div class="legend">${Object.keys(ARCH).map(a => `<span><i style="background:var(${ACOL[a]})"></i>${ARCH[a]}</span>`).join('')}</div></div>
     <div class="panel"><header><h2>Weak-evidence detector</h2><p>The prioritization list, audited</p></header><div class="rows">${audit}</div></div></div>`;
  $$('.bub', v).forEach(g => g.onclick = () => { selected = g.dataset.id; location.hash = '#prioritize'; });
}

// ------------------------------------------------------------------ RISKS
function renderRisks() {
  const v = $('[data-view="risks"]');
  const kinds = {}; S.risks.forEach(r => kinds[r.kind] = (kinds[r.kind] || 0) + 1);
  const KN = {silent_churn: 'Silent churn', concentration: 'Revenue concentration', weak_bet: 'Weak roadmap bet', under_cited: 'Under-cited PRD', dependency: 'Dependency bottleneck', capital: 'Capital misallocation'};
  v.innerHTML = head('Automated portfolio risk detection', 'Portfolio risks', 'Detected every run from the same evidence, ranked by severity and the Cost of Delay at stake. Each has a suggested owner.') +
    kpis([[S.risks.length, 'Risks detected'], [S.risks.filter(r => r.severity === 'high').length, 'High severity'], ...Object.entries(kinds).slice(0, 4).map(([k, n]) => [n, KN[k] || k])]) +
    `<div class="rows">${S.risks.map(r => `<div class="row"><div class="top"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="sev ${r.severity}">${r.severity}</span><span class="tag">${KN[r.kind] || r.kind}</span><b>${esc(r.title)}</b></div>
      <span class="mono muted" style="font-size:12px">${r.cod_week ? money(r.cod_week) + '/wk at stake' : ''}</span></div>
      <div style="font-size:13.5px">${esc(r.detail)}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:12px" class="muted">Owner: <b style="color:var(--fg)">${esc(r.owner || '')}</b>${r.theme_id ? ` · <a href="#prioritize" data-theme="${r.theme_id}">${r.theme_id}</a>` : ''}${r.citations.length ? ' · ' + r.citations.slice(0, 8).map(c => `<span class="cid">${esc(c)}</span>`).join(' ') : ''}</div></div>`).join('')}</div>`;
  $$('[data-theme]', v).forEach(a => a.onclick = () => { selected = a.dataset.theme; });
}

// ------------------------------------------------------------------ DEPENDENCIES
function renderDependencies() {
  const v = $('[data-view="dependencies"]');
  const ep = Object.fromEntries(S.epics.map(e => [e.epic_key, e]));
  const linked = new Set(S.links.flatMap(l => [l.from_key, l.to_key]));
  const preds = {}; S.links.forEach(l => (preds[l.to_key] = preds[l.to_key] || []).push(l.from_key));
  const layer = {}; const L = k => layer[k] ?? (layer[k] = preds[k] ? 1 + Math.max(...preds[k].map(L)) : 0);
  [...linked].forEach(L);
  const cols = {}; [...linked].sort().forEach(k => (cols[layer[k]] = cols[layer[k]] || []).push(k));
  const NW = 230, NH = 70, GX = 70, GY = 22, pad = 10;
  const ncol = Object.keys(cols).length, nrow = Math.max(...Object.values(cols).map(c => c.length));
  const W = pad * 2 + ncol * NW + (ncol - 1) * GX, H = pad * 2 + nrow * NH + (nrow - 1) * GY;
  const pos = {}; Object.entries(cols).forEach(([c, ks]) => ks.sort((a, b) => (ep[b].inherited_cod + ep[b].own_cod) - (ep[a].inherited_cod + ep[a].own_cod)).forEach((k, i) => pos[k] = {x: pad + c * (NW + GX), y: pad + i * (NH + GY)}));
  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Jira epic dependency graph"><defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${css('--muted')}"/></marker></defs>`;
  S.links.forEach(l => { const a = pos[l.from_key], b = pos[l.to_key]; const x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x - 2, y2 = b.y + NH / 2, mx = (x1 + x2) / 2; s += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="${css('--line2')}" stroke-width="1.6" marker-end="url(#arr)"/>`; });
  Object.entries(pos).forEach(([k, p]) => {
    const e = ep[k]; const hot = e.status === 'not_started' && e.inherited_cod > 20000;
    const stroke = hot ? css('--bad') : e.status === 'in_progress' ? css('--warn') : css('--line2');
    s += `<rect x="${p.x}" y="${p.y}" width="${NW}" height="${NH}" rx="8" fill="${css('--panel2')}" stroke="${stroke}" stroke-width="${hot ? 2 : 1}"/>`;
    s += `<text x="${p.x + 10}" y="${p.y + 18}" font-size="11.5" fill="${css('--fg')}" font-family="IBM Plex Mono,monospace">${k} · ${e.remaining_weeks}w · ${e.status.replace('_', ' ')}</text>`;
    s += `<text x="${p.x + 10}" y="${p.y + 36}" font-size="12" fill="${css('--fg')}">${esc(e.title.length > 32 ? e.title.slice(0, 31) + '…' : e.title)}</text>`;
    s += `<text x="${p.x + 10}" y="${p.y + 56}" font-size="11" fill="${hot ? css('--bad') : css('--muted')}" font-family="IBM Plex Mono,monospace">${e.inherited_cod ? 'unblocks ' + money(e.inherited_cod) + '/wk' : e.own_cod ? 'own ' + money(e.own_cod) + '/wk' : e.team}</text>`;
  });
  s += '</svg>';
  const rows = [...S.epics].filter(e => e.status !== 'done').sort((a, b) => b.cd3 - a.cd3);
  v.innerHTML = head('Cross-portfolio Jira dependencies', 'What is blocking the valuable work', 'The Dependency Tracer follows “blocks” links across teams. A blocker inherits the confidence-adjusted Cost of Delay of everything downstream, so foundational work gets ranked by the value it releases.') +
    `<div class="panel"><header><h2>Dependency graph</h2><p>Red border = not started and holding up more than $20K/week</p></header><div class="depgraph">${s}</div></div>
     <div class="panel" style="margin-top:14px"><header><h2>Epics ranked by value released per week of work</h2><p>(own CoD + inherited CoD) ÷ remaining weeks</p></header><div class="tablewrap"><table><thead><tr><th>Epic</th><th>Team</th><th>Status</th><th class="num">Weeks</th><th class="num">Own CoD/wk</th><th class="num">Inherited CoD/wk</th><th>Unblocks</th><th class="num">Value/wk²</th></tr></thead><tbody>
     ${rows.map(e => `<tr><td><span class="mono">${e.epic_key}</span> ${esc(e.title)}${e.theme_id ? ` <span class="faint">(${e.theme_id})</span>` : ''}</td><td>${esc(e.owner_team)}</td><td><span class="tag ${e.status === 'in_progress' ? 'warn' : ''}">${e.status.replace('_', ' ')}</span></td><td class="num">${e.remaining_weeks}</td><td class="num">${money(e.own_cod)}</td><td class="num">${money(e.inherited_cod)}</td><td class="mono" style="font-size:12px">${e.unblocks.join(', ') || '—'}</td><td class="num"><b>${num(e.cd3)}</b></td></tr>`).join('')}</tbody></table></div></div>`;
}

// ------------------------------------------------------------------ CAB
function renderCab() {
  const v = $('[data-view="cab"]');
  cabSel = cabSel || (S.cab[0] || {}).meeting_id;
  const m = S.cab.find(x => x.meeting_id === cabSel) || S.cab[0];
  const byLine = {}; m.items.forEach(i => byLine[i.line_no] = i);
  const lines = m.body.split('\n').map((l, i) => { const it = byLine[i + 1]; return `<div class="ln ${it ? 'k-' + it.kind : ''}"><span>${i + 1}</span><span>${esc(l) || ' '}</span></div>`; }).join('');
  const th = TH();
  const KCOL = {pain: '--cm', ask: '--do', praise: '--hs', commitment: '--pay'};
  const total = S.cab.reduce((a, x) => a + x.items.length, 0);
  v.innerHTML = head('Parsing CAB notes', 'Customer Advisory Board notes', 'The CAB Agent reads each meeting document and extracts customer pains, asks, praise and vendor commitments, with the line they came from. Pains and asks then flow into clustering as Say evidence.') +
    kpis([[S.cab.length, 'Meetings parsed'], [total, 'Statements extracted'], [S.cab.reduce((a, x) => a + x.items.filter(i => i.kind === 'commitment').length, 0), 'Vendor commitments to track'], [S.cab.reduce((a, x) => a + x.items.filter(i => i.theme_id).length, 0), 'Linked to themes']]) +
    `<div class="seg" style="margin-bottom:12px">${S.cab.map(x => `<button type="button" data-m="${x.meeting_id}" aria-pressed="${x.meeting_id === m.meeting_id}">${x.meeting_id} · ${x.held_on}</button>`).join('')}</div>
     <div class="cabwrap"><div class="panel"><header><h2>${esc(m.title)}</h2><p>Highlighted lines were extracted</p></header><div class="doc">${lines}</div>
       <div class="legend">${Object.entries(KCOL).map(([k, c]) => `<span><i style="background:var(${c})"></i>${k}</span>`).join('')}</div></div>
     <div class="panel"><header><h2>Extracted statements</h2><p>${m.items.length} items</p></header>${m.items.sort((a, b) => a.line_no - b.line_no).map(i => `<div class="quote"><p>${esc(i.text)}</p><footer><span class="tag" style="color:var(${KCOL[i.kind]})">${i.kind}</span><span class="mono">line ${i.line_no}</span><span>${esc(i.account_name || i.speaker || '')}</span>${i.theme_id && th[i.theme_id] ? `<a href="#prioritize" data-theme="${i.theme_id}">${i.theme_id} ${esc(th[i.theme_id].title)}</a>` : ''}</footer></div>`).join('')}</div></div>`;
  $$('[data-m]', v).forEach(b => b.onclick = () => { cabSel = b.dataset.m; renderCab(); });
  $$('[data-theme]', v).forEach(a => a.onclick = () => { selected = a.dataset.theme; });
}

// ------------------------------------------------------------------ PBR
const SECTIONS = [['health', 'Health'], ['evidence', 'Customer evidence'], ['priorities', 'Priorities by CD3'], ['risks', 'Risks'], ['dependencies', 'Dependencies'], ['asks', 'Asks of leadership']];
function pbrMarkdown(d) {
  let md = `# Product Business Review · ${d.name}\n\n${d.headline}\n`;
  SECTIONS.forEach(([k, l]) => { const cs = d.claims.filter(c => c.section === k && c.status === 'grounded'); if (cs.length) md += `\n## ${l}\n` + cs.map(c => `- ${c.text}`).join('\n') + '\n'; });
  return md + `\n_Generated by SignalCore run ${S.run.run_id}; every statement verified against cited facts._\n`;
}
function renderPbr() {
  const v = $('[data-view="pbr"]');
  const docs = Object.keys(S.pbr).sort((a, b) => a === 'portfolio' ? -1 : b === 'portfolio' ? 1 : S.pbr[a].name.localeCompare(S.pbr[b].name));
  if (!docs.length) { v.innerHTML = '<div class="empty">No PBRs in this run.</div>'; return; }
  if (!S.pbr[pbrSel]) pbrSel = docs[0];
  const d = S.pbr[pbrSel];
  const all = Object.values(S.pbr).flatMap(x => x.claims), retried = all.filter(c => c.attempt > 1).length, dropped = Object.values(S.pbr).reduce((a, x) => a + x.dropped.length, 0);
  v.innerHTML = head('Crafting PBRs', 'Product Business Reviews', 'Drafted by the PBR Agent from a fixed table of computed facts. The Grounding Judge checks each claim: numbers in code, meaning with a second model. Failing claims go back for a rewrite, up to twice, then they are dropped.',
    `<button class="btn primary" id="pbrcopy" type="button">Copy as Markdown</button>`) +
    kpis([[docs.length, 'Reviews generated'], [all.length, 'Claims kept', 'every one cites facts'], [retried, 'Claims rewritten after judging'], [dropped, 'Claims dropped as unsupported']]) +
    `<div class="seg" style="margin-bottom:12px">${docs.map(k => `<button type="button" data-d="${k}" aria-pressed="${k === pbrSel}">${esc(S.pbr[k].name)}</button>`).join('')}</div>
     <div class="panel" style="max-width:980px"><div class="eyebrow">Product Business Review · ${esc(S.run.run_id)}</div><h2 style="font-size:21px;margin:4px 0 10px">${esc(d.headline)}</h2>
     ${SECTIONS.map(([k, l]) => { const cs = d.claims.filter(c => c.section === k); return cs.length ? `<h3 style="margin-top:14px">${l}</h3>` + cs.map(c => `<div class="claim"><p>${esc(c.text)}</p><span class="tag ${c.attempt > 1 ? 'warn' : 'ok'}">${c.attempt > 1 ? 'grounded on retry' : 'grounded'}</span>
        <details class="facts"><summary>${c.facts.length} cited fact${c.facts.length === 1 ? '' : 's'}</summary>${c.facts.map(f => `<div><span class="mono faint">${esc(f.fact_id.split(':')[1])}</span> ${esc(f.label)}: <b style="color:var(--fg)">${esc(f.value)}</b></div>`).join('')}</details></div>`).join('') : ''; }).join('')}
     ${d.dropped.length ? `<details style="margin-top:14px"><summary>${d.dropped.length} claims dropped by the judge</summary>${d.dropped.map(x => `<div class="quote"><p>${esc(x.text)}</p><footer>${esc(x.judge)}</footer></div>`).join('')}</details>` : ''}</div>`;
  $$('[data-d]', v).forEach(b => b.onclick = () => { pbrSel = b.dataset.d; renderPbr(); });
  $('#pbrcopy').onclick = () => copy(pbrMarkdown(d), 'PBR copied as Markdown');
}

// ------------------------------------------------------------------ EXECUTIVE
function spark(arr, col) {
  const W = 200, H = 28, mn = Math.min(...arr), mx = Math.max(...arr), sx = W / (arr.length - 1), sy = v => H - 3 - ((v - mn) / ((mx - mn) || 1)) * (H - 6);
  const pts = arr.map((v, i) => `${(i * sx).toFixed(1)},${sy(v).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><polyline points="0,${H} ${pts} ${W},${H}" fill="${col}" fill-opacity=".12"/><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
function renderExecutive() {
  const v = $('[data-view="executive"]');
  const low = S.modules.filter(m => m.demand_share < m.fte_share * .5), lowF = low.reduce((a, m) => a + m.fte, 0), totF = S.modules.reduce((a, m) => a + m.fte, 0);
  const STAGES = [['discovery', '0→1 Discovery'], ['pilot', 'Pilot → production'], ['growth', 'Growth'], ['mature', 'Mature / sunset watch']];
  const alloc = [...S.modules].sort((a, b) => (b.demand_share - b.fte_share) - (a.demand_share - a.fte_share));
  const amax = Math.max(...S.modules.map(m => Math.max(m.fte_share, m.demand_share)), .01);
  const p = S.pbr.portfolio;
  v.innerHTML = head('C-suite & board', 'Portfolio health', 'Lifecycle position, adoption velocity, and whether engineering capacity follows confidence-adjusted Cost of Delay.') +
    kpis([[money(S.counts.arr), 'Customer ARR', `${S.counts.customers} customers`], [money(S.themes.reduce((a, t) => a + t.cod_adj, 0)), 'Adjusted CoD per week', 'across all themes'],
      [pct(lowF / totF), 'Eng capacity on low-demand modules', low.map(m => m.name).join(', ') || 'none'], [S.risks.filter(r => r.severity === 'high').length, 'High-severity risks', 'see Risks']]) +
    `<div class="panel"><header><h2>Lifecycle & PMF matrix</h2><p>Weekly active accounts, 26 weeks · velocity = last 8 vs first 8 weeks</p></header><div class="lc">${STAGES.map(([k, l]) => `<div class="col"><div class="colh">${l}</div>${S.modules.filter(m => m.stage === k).map(m => { const c = m.velocity > .02 ? css('--hs') : m.velocity < -.02 ? css('--cm') : css('--muted'); return `<div class="mod"><b>${esc(m.name)}</b><div class="m"><span>${m.accounts} accts · ${money(m.arr)}</span><span class="mono ${m.velocity > .02 ? 'up' : m.velocity < -.02 ? 'down' : ''}">${m.velocity > 0 ? '+' : ''}${(m.velocity * 100).toFixed(1)}%</span></div>${spark(m.wau, c)}<div class="m"><span>${m.fte} FTE</span><span>${m.themes.join(' ') || '—'}</span></div></div>`; }).join('')}</div>`).join('')}</div></div>
    <div class="grid g-2" style="margin-top:14px"><div class="panel"><header><h2>Capital allocation vs Cost of Delay</h2><p>Share of FTE vs share of confidence-adjusted CoD</p></header>
      <div class="legend" style="margin:0 0 10px"><span><i style="background:var(--faint)"></i>FTE share</span><span><i style="background:var(--do)"></i>Adjusted CoD share</span></div>
      <div class="alloc">${alloc.map(m => { const g = m.demand_share - m.fte_share; return `<div class="ar"><span>${esc(m.name)}</span><div class="bars"><i style="width:${m.fte_share / amax * 100}%;background:var(--faint)"></i><i style="width:${m.demand_share / amax * 100}%;background:var(--do)"></i></div><span class="mono ${g > .03 ? 'up' : g < -.03 ? 'down' : 'muted'}" style="text-align:right">${g > 0 ? '+' : ''}${(g * 100).toFixed(1)}pt</span></div>`; }).join('')}</div></div>
      <div class="panel"><header><h2>Portfolio PBR</h2><p><a href="#pbr">Open full review</a></p></header>${p ? `<h3 style="font-size:16px">${esc(p.headline)}</h3>${p.claims.slice(0, 7).map(c => `<div class="claim"><p>${esc(c.text)}</p><span class="tag ok">grounded</span></div>`).join('')}` : '<p class="muted">No portfolio review in this run.</p>'}</div></div>`;
}

// ------------------------------------------------------------------ ASK
const DEFAULT_Q = ['Which mid-market customers raised AI agent permissions on Gong calls in the last 60 days, how sticky is their usage, and what ARR renews?',
  'Why are enterprise customers unhappy with conditional access?', 'Which roadmap commitments depend on a single account?', 'Where is usage falling among accounts that renew in the next 150 days?'];
function renderAsk(result) {
  const v = $('[data-view="ask"]');
  const recorded = [...new Set(S.asks.map(a => a.question))];
  const sugg = SNAP ? recorded : [...new Set([...DEFAULT_Q, ...recorded])].slice(0, 6);
  v.innerHTML = head('LLM + RAG', 'Ask the evidence', 'An agent answers with two tools: read-only SQL over CRM, telemetry and scores, and retrieval over every call, ticket, idea and CAB statement. Numbers come from queries; quotes are cited.') +
    `<div class="panel"><form class="inline" id="askf"><label style="flex:1 1 420px">Question<input class="text" id="askq" maxlength="500" value="${esc(result ? result.question : sugg[0] || '')}"></label><button class="btn primary" type="submit">Ask</button></form>
      <div class="sugg">${sugg.map(q => `<button type="button" data-q="${esc(q)}">${esc(q.length > 80 ? q.slice(0, 78) + '…' : q)}</button>`).join('')}</div><div id="askout" style="margin-top:16px"></div></div>`;
  $('#askf').onsubmit = e => { e.preventDefault(); doAsk($('#askq').value); };
  $$('[data-q]', v).forEach(b => b.onclick = () => { $('#askq').value = b.dataset.q; doAsk(b.dataset.q); });
  if (result) showAnswer(result);
}
async function doAsk(q) {
  const out = $('#askout'); out.innerHTML = '<p class="muted"><span class="dot run"></span>The agent is querying the data and searching verbatims…</p>';
  try { const r = await api.ask(q); showAnswer(r); if (!SNAP) { S.asks = [r, ...S.asks]; } }
  catch (e) { out.innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
}
function showAnswer(r) {
  $('#askout').innerHTML = `<div class="answer">${mdAnswer(r.answer)}</div>
    <p class="note">${r.steps.length} tool calls · ${r.seconds}s · $${(+r.cost_usd).toFixed(3)} · mode ${esc(r.mode)}</p>
    ${r.cited.length ? `<h3 style="margin-top:12px">Cited verbatims</h3>${r.cited.map(c => `<div class="quote"><p>${esc(c.text)}</p><footer><span class="cid">${esc(c.id)}</span><span class="tag">${SRC[c.source] || c.source} ${esc(c.ref)}</span><span>${esc(c.account || '')}${c.segment ? ' · ' + c.segment : ''}</span><span class="mono">${esc(c.date)}</span></footer></div>`).join('')}` : ''}
    <details style="margin-top:12px"><summary>How it answered (${r.steps.length} steps)</summary>${r.steps.map((s, i) => s.tool === 'run_sql' ? `<div style="margin-top:10px"><span class="tag">${i + 1} · run_sql</span><pre class="code">${esc(s.sql)}</pre>${s.result.error ? `<div class="callout">${esc(s.result.error)}</div>` : `<div class="tablewrap" style="max-height:220px;overflow:auto"><table><thead><tr>${s.result.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${s.result.rows.slice(0, 25).map(row => `<tr>${row.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}</div>` : `<div style="margin-top:10px"><span class="tag">${i + 1} · search_evidence</span> <span class="muted">“${esc(s.query)}” → ${s.hits} hits</span></div>`).join('')}</details>`;
}

// ------------------------------------------------------------------ RUN & EVALS
const EVLABEL = {identity_precision: ['Identity precision', 1], identity_coverage: ['Identity coverage', 1], cab_recall: ['CAB statement recall', 1], cab_precision: ['CAB statement precision', 1],
  cluster_precision: ['Cluster precision', 1], cluster_recall: ['Cluster recall', 1], noise_leak: ['Noise leaking into themes', 1], themes_found: ['Planted themes found', 0], deal_link_accuracy: ['Deal-linking accuracy', 1],
  pattern_recovery: ['Planted patterns recovered', 1], grounded_first_pass: ['Claims grounded first pass', 1], grounded_final: ['Claims kept after judging', 1], bottleneck_found: ['Planted bottleneck found', 2], run_cost_usd: ['Run cost', 3]};
function evalVal(e) { const [, k] = EVLABEL[e.metric] || [e.metric, 1]; return k === 1 ? pct(e.value) : k === 2 ? (e.value ? 'Yes' : 'No') : k === 3 ? '$' + (+e.value).toFixed(2) : (+e.value).toFixed(0) + ' / 12'; }
function renderRun() {
  const v = $('[data-view="run"]');
  const r = S.run;
  const tot = S.steps.reduce((a, s) => a + (s.cost_usd || 0), 0);
  const canLive = S.llm_mode === 'live';
  v.innerHTML = head('Workflow engine', 'Pipeline runs, trace and evals', 'Every node of the LangGraph run is logged with the model used, tokens, cost and what it found. Evals compare the output with ground truth planted in the synthetic data, which the agents never see.',
    SNAP ? '<span class="tag">Standalone copy · runs disabled</span>' : `<div class="btns" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="runbtn" type="button">${canLive ? 'Run pipeline (live Claude)' : 'Replay recorded run'}</button></div>`) +
    kpis([[esc(r.run_id), 'Current run', `${esc(r.mode)} · ${esc(r.status)}`], [S.steps.length, 'Steps logged'], ['$' + tot.toFixed(2), 'Model cost this run', `${num(r.tokens_in)} in / ${num(r.tokens_out)} out tokens`], [r.finished_at ? r.finished_at.slice(11) : '—', 'Finished', r.started_at ? 'started ' + r.started_at.slice(11) : '']]) +
    `<div id="live" class="panel" hidden style="margin-bottom:14px"><header><h2><span class="dot run"></span>Running</h2><p id="livemode"></p></header><div class="steps" id="liveev"></div></div>
     <div class="grid g-2"><div class="panel"><header><h2>Trace</h2><p>${esc(r.run_id)}</p></header><div class="steps">${S.steps.map(s => `<div class="step"><span class="no">${s.step_no}</span><div><b>${esc(s.label)}</b><div class="sum">${esc((s.detail || {}).summary || '')}</div>
        <details><summary>details</summary><pre class="code">${esc(JSON.stringify(s.detail, null, 2)).slice(0, 6000)}</pre></details></div><div class="meta">${(s.ms / 1000).toFixed(1)}s${s.model ? '<br>' + esc(s.model.replace(/claude-/g, '')) : ''}${s.cost_usd ? '<br>$' + (+s.cost_usd).toFixed(3) : ''}</div></div>`).join('')}</div></div>
     <div class="grid" style="align-content:start"><div class="panel"><header><h2>Evals</h2><p>vs planted ground truth</p></header><div class="evals">${S.evals.map(e => `<div class="ev"><div class="l">${esc((EVLABEL[e.metric] || [e.metric])[0])}</div><div class="v">${evalVal(e)}</div><p>${esc(e.metric === 'pattern_recovery' ? 'High signal ×2, silent churn, commercial mirage, vocal minority' : e.detail)}</p></div>`).join('')}</div></div>
     <div class="panel"><header><h2>Runs</h2></header><div class="tablewrap"><table><thead><tr><th>Run</th><th>Mode</th><th>Status</th><th class="num">Cost</th></tr></thead><tbody>${S.runs.map(x => `<tr><td class="mono">${esc(x.run_id)}</td><td>${esc(x.mode)}</td><td>${esc(x.status)}</td><td class="num">$${(+x.cost_usd || 0).toFixed(2)}</td></tr>`).join('')}</tbody></table></div></div></div></div>`;
  const b = $('#runbtn'); if (b) b.onclick = startRun;
}
async function startRun() {
  try {
    const mode = S.llm_mode === 'live' ? 'live' : 'replay';
    const {run_id} = await api.run(mode);
    $('#live').hidden = false; $('#livemode').textContent = `${run_id} · ${mode}`; $('#runbtn').disabled = true;
    let after = 0;
    clearInterval(polling);
    polling = setInterval(async () => {
      const r = await api.events(run_id, after); after = r.next;
      r.events.forEach(e => {
        if (e.type === 'step_finished') $('#liveev').insertAdjacentHTML('beforeend', `<div class="step"><span class="no">${e.step_no}</span><div><b>${esc(e.label)}</b><div class="sum">${esc(e.summary || '')}</div></div><div class="meta">${(e.ms / 1000).toFixed(1)}s${e.cost ? '<br>$' + e.cost.toFixed(3) : ''}</div></div>`);
        if (e.type === 'error') { toast(e.message, true); }
        if (e.type === 'run_finished') { clearInterval(polling); toast(`Run ${e.status}`); load(); }
      });
    }, 1000);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ METHOD
function renderMethod() {
  const v = $('[data-view="method"]'); const c = S.params.cod, w = S.params.weights;
  v.innerHTML = head('How SignalCore decides', 'Method', 'All parameters below are live inputs to the scoring code, shown so they can be challenged.') +
    `<div class="grid g-2"><div class="panel"><h2>1 · Evidence Score (confidence)</h2><pre class="code">Say  Q = 0.45·log-scaled unique accounts + 0.20·source diversity
       + 0.25·urgency + 0.10·workaround rate
Do   B = max( abandonment lift vs non-complainers × usage coverage,
              renewal-cohort usage decline / 0.45 )
Pay  C = log-scaled $ (urgency-weighted ARR + declining ARR + linked deals)
       × (0.75 + 0.25·ICP share)

Evidence = 100 × (${w.q}·Q + ${w.b}·B + ${w.c}·C) × rule penalty × skeptic penalty
  rule penalty ×0.55 one account > 60% of dollars; ×0.85 one account > 35%,
               single source, or < 50% of complainers use the feature
  skeptic penalty 0.5–1.0, only with cited SQL findings</pre>
      <h3 style="margin-top:14px">Pattern (separate from confidence)</h3><div class="tablewrap"><table><tbody>
      <tr><td>${chip('commercial_mirage')}</td><td class="muted">top account > 60% of dollars and B < 0.3</td></tr><tr><td>${chip('silent_churn')}</td><td class="muted">renewal-cohort decline ≥ 30%, and Q < 0.55 or at least twice as many accounts quietly declining as complaining</td></tr>
      <tr><td>${chip('vocal_minority')}</td><td class="muted">Q ≥ 0.45, B < 0.25, C < 0.65</td></tr><tr><td>${chip('high_signal')}</td><td class="muted">score ≥ 70 and every pillar ≥ 0.45</td></tr><tr><td>${chip('emerging')}</td><td class="muted">everything else</td></tr></tbody></table></div></div>
    <div class="panel"><h2>2 · Cost of Delay and CD3</h2><pre class="code">Retention CoD/wk = Σ affected accounts renewing ≤ ${c.horizon_weeks} wk:
    ARR × p_churn ÷ max(weeks to renewal, ${c.min_weeks})
    p_churn = ${c.churn_base} + ${c.churn_severity} × severity(urgency, friction)
Deal CoD/wk      = Σ open linked deals: amount × ${c.win_uplift} ÷ max(weeks to close, ${c.deal_min_weeks})
                 + Σ lost linked deals: amount × ${c.lost_echo} ÷ ${c.lost_echo_weeks}
CoD/wk           = retention + deals
Adjusted CoD     = CoD × Evidence / 100
Duration         = build estimate + weeks blocked on the critical path
CD3              = Adjusted CoD ÷ Duration       → backlog rank

Urgency profile: expedite (silent churn, or high friction and CoD > $50K),
fixed date (one dated renewal/deal > 35% of CoD), standard, intangible (< $2K)</pre>
      <p class="muted" style="margin-top:10px">Blocking epics inherit the adjusted CoD of everything downstream, so foundational work is ranked by the value it releases.</p></div></div>
    <div class="panel" style="margin-top:14px"><h2>3 · Workflow</h2><pre class="code">The grind it replaces                     Engine (LangGraph)                          Outputs
Manual Pendo data collation        →  Triangulation (SQL)                        →  Evidence synthesis (themes, scores, quotes)
Tracing cross-portfolio Jira deps  →  Dependency Tracer                          →  Portfolio risk detection
Parsing CAB notes, crafting PBRs   →  CAB Agent · PBR Agent · Grounding Judge    →  Grounded PBRs and board brief
                                      Identity resolver · Enrichment (Haiku) · Cluster Agent (Opus) · Skeptic (Opus + SQL) · Ask (RAG)</pre></div>`;
}

// ------------------------------------------------------------------ app
function renderAll() {
  $('#runinfo').innerHTML = `<span class="mode ${SNAP ? 'snapshot' : S.llm_mode}">${SNAP ? 'standalone' : esc(S.llm_mode)}</span><span>Run <b>${esc(S.run.run_id)}</b></span><span><b>${S.counts.feedback.toLocaleString()}</b> voices</span><span><b>${Math.round(S.counts.events / 1000)}K</b> events</span><span><b>${S.counts.opps}</b> deals</span>`;
  if (!selected || !TH()[selected]) selected = S.themes[0] && S.themes[0].id;
  renderPrioritize(); renderTriangulation(); renderRisks(); renderDependencies(); renderCab(); renderPbr(); renderExecutive(); renderAsk(); renderRun(); renderMethod();
}
const VIEWS = ['prioritize', 'triangulation', 'risks', 'dependencies', 'cab', 'pbr', 'executive', 'ask', 'run', 'method'];
function route() {
  const h = location.hash.slice(1); const v = VIEWS.includes(h) ? h : 'prioritize';
  $$('.view').forEach(s => s.hidden = s.dataset.view !== v);
  $$('nav.tabs a').forEach(a => a.getAttribute('href') === '#' + v ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  if (v === 'prioritize' && S) renderPrioritize();
}
async function load() {
  try { S = await api.state(); S.llm_mode = S.llm_mode || (SNAP ? 'snapshot' : 'replay'); $('#loading').hidden = true; renderAll(); route(); }
  catch (e) { $('#loading').textContent = 'Could not load data: ' + e.message; }
}
window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });
load();
})();

'use strict';
/* Tedarik Portalı istemcisi. Derleme yok, dış kütüphane yok (K-010). Tüm metin textContent ile yazılır;
   sunucudan gelen hiçbir değer HTML olarak yorumlanmaz. Yapı KS GRC ksgrc.js düzenini izler. */

// ------------------------------------------------------------------ DOM yardımcıları
const $ = id => document.getElementById(id);
const SVGNS = 'http://www.w3.org/2000/svg';
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'value' && 'value' in el) el.value = v;
    else if (k === 'checked' || k === 'selected' || k === 'disabled') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
  for (const c of children.flat()) if (c) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}
/** Yalnızca http(s) bağlantısı çizilir (sunucu da denetler; javascript: gibi şemalar asla bağlantı olmaz). */
function extLink(url) {
  if (!url) return null;
  return /^https?:\/\//i.test(url) ? h('a', {href: url, target: '_blank', rel: 'noopener noreferrer', text: url}) : String(url);
}
function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ------------------------------------------------------------------ biçimlendirme
const TR = 'tr-TR';
const fmt = {
  date(v) { if (!v) return '—'; const d = new Date(v.length === 10 ? v + 'T00:00:00' : v); return isNaN(d) ? v : d.toLocaleDateString(TR); },
  datetime(v) { if (!v) return '—'; const d = new Date(v); return isNaN(d) ? v : d.toLocaleString(TR, {dateStyle: 'medium', timeStyle: 'short'}); },
  num(v, digits = 1) { return v === null || v === undefined ? '—' : Number(v).toLocaleString(TR, {maximumFractionDigits: digits}); },
  pct(v) { return v === null || v === undefined ? '—' : '%' + Number(v).toLocaleString(TR, {maximumFractionDigits: 1}); },
  money(v) { return v === null || v === undefined ? '—' : Number(v).toLocaleString(TR, {minimumFractionDigits: 2, maximumFractionDigits: 2}); },
};
const today = (days = 0) => { const d = new Date(); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); };

// ------------------------------------------------------------------ durum ve API
const S = {meta: null, me: null, cache: {}, filters: {}, mySurveys: 0, renderSeq: 0, renderDone: 0, renderAgain: false};
async function api(path, {method = 'GET', body, raw} = {}) {
  const opts = {method, credentials: 'same-origin', headers: {}};
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path.startsWith('/') ? path : '/api/tdr/' + path, opts);
  if (r.status === 401) { location.assign('/login'); throw new Error('Oturum süresi doldu'); }
  const type = r.headers.get('Content-Type') || '';
  if (!r.ok) {
    let message = 'İşlem başarısız (' + r.status + ')';
    if (type.includes('json')) { try { message = (await r.json()).error || message; } catch (e) { /* boş */ } }
    if (message === 'Parolanızı değiştirmeniz gerekiyor') location.assign('/change-password');
    const err = new Error(message); err.status = r.status; throw err;
  }
  if (raw) return r;
  return type.includes('json') ? r.json() : r.text();
}
async function list(res, refresh = false) {
  if (!S.meta.resources[res]) return [];
  if (!refresh && S.cache[res]) return S.cache[res];
  S.cache[res] = await api(res + '?limit=1000');
  return S.cache[res];
}
function invalidate(...names) { for (const n of names) delete S.cache[n]; }
async function download(path, fallbackName) {
  try {
    const r = await api(path, {raw: true});
    const blob = await r.blob();
    const disposition = r.headers.get('Content-Disposition') || '';
    const match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
    const name = match ? decodeURIComponent(match[1]) : fallbackName;
    const url = URL.createObjectURL(blob);
    const a = h('a', {href: url, download: name}); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(name + ' indirildi');
  } catch (e) { toast(e.message, false); }
}

// ------------------------------------------------------------------ meta veri
const META = {
  def: res => S.meta.resources[res],
  field: (res, name) => (S.meta.resources[res]?.fields || []).find(f => f.name === name),
  label: (res, name) => META.field(res, name)?.label || name,
  option: (res, name, value) => (META.field(res, name)?.options || []).find(o => o.value === value)?.label ?? value,
  can: need => !!S.meta.permissions[need],
};
const FLAGS = new Set(['active', 'required', 'is_primary', 'anonymous', 'met', 'selected', 'disabled', 'certified', 'is_critical', 'is_primary_key', 'nullable',
  'special', 'foreign_transfer', 'profiling', 'large_scale', 'new_technology', 'identity_verified', 'dpa_signed',
  'gpai_based', 'uses_personal_data', 'uses_special_data', 'automated_decision', 'transparency_notice']);
// Kişi alanları: formda kullanıcı dizininden öneri (serbest metin de girilebilir; sahip alanları kullanıcı adı veya görünen adla eşleşir)
const PERSON = new Set(['owner', 'steward', 'custodian', 'approver', 'assignee', 'reviewer', 'facilitator', 'preparer', 'respondent', 'business_owner', 'responsible', 'technical_owner']);
async function ensurePeople() {
  if (document.getElementById('peopleList') || !META.can('write')) return;
  const people = await api('directory').catch(() => []);
  if (document.getElementById('peopleList')) return;
  document.body.append(h('datalist', {id: 'peopleList'}, people.map(p => h('option', {value: p.username, label: p.display_name || p.username}))));
}
const LONG = new Set(['value_json', 'description', 'cause', 'risk_event', 'consequence', 'treatment', 'note', 'comment', 'intro', 'outro',
  'help', 'rationale', 'resolution', 'decision_rationale', 'exception_rationale', 'text', 'details', 'method', 'expected_result',
  'audit_objective', 'scope', 'conclusion', 'root_cause', 'closure_note', 'verification_note', 'justification', 'definition', 'calculation',
  'technical_description', 'needs', 'purpose', 'security_measures', 'necessity', 'risks', 'measures', 'response_summary', 'keywords', 'weak_keywords',
  'legal_basis_note', 'summary', 'fulfillment_note', 'human_oversight', 'evaluation_summary', 'monitoring', 'affected_persons']);
const GOOD = new Set(['active', 'completed', 'published', 'answered', 'submitted', 'done', 'met', 'pass', 'current', 'effective', 'approved', 'production',
  'successful', 'green', 'resolved', 'operational', 'success']);
const BAD = new Set(['critical', 'terminated', 'expired', 'suspended', 'sla_breach', 'incident', 'high', 'cancelled', 'fail', 'ineffective',
  'failed', 'red', 'obsolete', 'retired', 'removed', 'restricted', 'special', 'table_removed', 'column_removed']);
const WARN = new Set(['open', 'in_treatment', 'pending', 'draft', 'expiring', 'medium', 'offboarding', 'prospect', 'important',
  'in_progress', 'validation', 'ending', 'planned', 'escalation', 'delivery_delay', 'inconclusive', 'partially_effective',
  'partially_successful', 'amber', 'in_review', 'partial', 'repair', 'blocked', 'deprecated', 'confidential', 'personal', 'type_changed']);
const PILLS = new Set(['status', 'tier', 'severity', 'criticality', 'priority', 'event_type', 'segment', 'beneficiary', 'kind',
  'purpose', 'subject', 'audience', 'category', 'response_strategy', 'source', 'raci', 'role', 'execution_mode', 'frequency',
  'opinion', 'confidentiality', 'nature', 'method_type', 'exercise_type', 'plan_type', 'outcome', 'process_type', 'ci_class', 'environment',
  'rule', 'impact_area', 'link_source', 'risk_type', 'last_status', 'operational_status', 'mode', 'dimension', 'platform', 'object_type', 'classification',
  'personal_data', 'change', 'module', 'legal_basis', 'request_type', 'residual_risk', 'decision', 'outcome', 'method']);
function tone(value) { return GOOD.has(value) ? 'good' : BAD.has(value) ? 'bad' : WARN.has(value) ? 'warn' : 'neutral'; }
function roleLabel(code) { return (S.meta.roles.find(r => r.value === code) || {}).label || code; }
function pill(text, cls = 'neutral') { return h('span', {class: 'pill ' + cls, text}); }
function refRecord(res, id) { return (S.cache[res] || []).find(r => r.id === id); }
function titleOf(r) { if (!r) return ''; return [r.code, r.name || r.title || r.username].filter(Boolean).join(' — ') || ('#' + r.id); }
const NAME_ONLY = new Set(['companies', 'org_units', 'processes', 'catalog_items', 'supplier_types']);   // kod yerine ad yeter
function display(res, name, value) {
  if (value === null || value === undefined || value === '') return h('span', {class: 'muted', text: '—'});
  const f = META.field(res, name);
  if (!f) return String(value);
  if (f.ref) { const r = refRecord(f.ref, value); return r ? (NAME_ONLY.has(f.ref) ? r.name || titleOf(r) : titleOf(r)) : '#' + value; }
  if (f.options) {
    const label = META.option(res, name, value);
    if (name === 'risk_level' || (res === 'bias' && name === 'criticality') || name === 'business_criticality') return pill(label, 'level-' + value);
    return PILLS.has(name) ? pill(label, tone(value)) : label;
  }
  if (FLAGS.has(name)) return value ? pill('Evet', name === 'disabled' ? 'bad' : 'good') : pill('Hayır', 'neutral');
  if (f.kind === 'DATE') return fmt.date(value);
  if (f.kind === 'TIMESTAMP') return fmt.datetime(value);
  if (f.kind === 'DECIMAL') return fmt.money(value);
  if (f.kind === 'REAL') return fmt.num(value, 2);
  const text = String(value);
  return text.length > 160 ? text.slice(0, 157) + '…' : text;
}
// Binlerce kaydı olabilen kaynaklar (ör. standart maddeleri) bütünüyle yüklenmez: formda aranarak seçilir,
// listede yalnızca görünen kimlikler istenir (ensureRefs).
const LARGE_REFS = new Set(['clauses', 'data_tables', 'data_columns', 'glossary_terms', 'evidence']);
async function loadRefs(res, fields) {
  const refs = new Set((META.def(res)?.fields || []).filter(f => f.ref && !LARGE_REFS.has(f.ref) && (!fields || fields.includes(f.name))).map(f => f.ref));
  await Promise.all([...refs].map(r => list(r).catch(() => [])));
}
async function ensureRefs(res, records) {
  const want = {};
  for (const f of META.def(res)?.fields || []) {
    if (!f.ref || !LARGE_REFS.has(f.ref)) continue;
    for (const r of records) { const v = r[f.name]; if (v && !refRecord(f.ref, v)) (want[f.ref] = want[f.ref] || new Set()).add(v); }
  }
  await Promise.all(Object.entries(want).map(async ([ref, ids]) => {
    const got = await api(`${ref}?id__in=${[...ids].slice(0, 900).join(',')}&limit=1000`).catch(() => []);
    S.cache[ref] = (S.cache[ref] || []).concat(got.filter(g => !refRecord(ref, g.id)));
  }));
}
function refSearch(f, value, id) {
  const hidden = h('input', {type: 'hidden', name: f.name, value: value ?? ''});
  const input = h('input', {id, type: 'search', placeholder: 'Kod veya başlıkla arayın…', autocomplete: 'off', 'aria-autocomplete': 'list'});
  const results = h('ul', {class: 'ref-results hidden', role: 'listbox'});
  const label = r => { const st = f.ref === 'clauses' ? (S.cache.standards || []).find(x => x.id === r.standard_id) : null; return (st ? st.code + ' ' : '') + titleOf(r); };
  if (value) api(`${f.ref}/${value}`).then(r => { input.value = label(r); }).catch(() => {});
  const choose = r => { hidden.value = r.id; input.value = label(r); results.classList.add('hidden'); };
  const search = debounce(async () => {
    const q = input.value.trim(); if (!q) { results.classList.add('hidden'); return; }
    if (f.ref === 'clauses') await list('standards').catch(() => []);
    const items = await api(`${f.ref}?q=${encodeURIComponent(q)}&limit=25`).catch(() => []);
    results.replaceChildren(...items.map(r => { const li = h('li', {tabindex: '0', role: 'option', text: label(r)}); li.addEventListener('click', () => choose(r));
      li.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); choose(r); } }); return li; }),
      items.length ? '' : h('li', {class: 'muted small', text: 'Eşleşen kayıt yok'}));
    results.classList.remove('hidden');
  }, 200);
  input.addEventListener('input', () => { hidden.value = ''; search(); });
  return h('div', {class: 'ref-search'}, input, hidden, results);
}

// ------------------------------------------------------------------ bildirim, panel, pencere
function toast(message, ok = true) {
  const t = $('toast'); t.textContent = message; t.className = 'show' + (ok ? '' : ' bad');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.className = ''; }, ok ? 3500 : 6000);
}
async function guard(button, fn) {
  if (button) { if (button.disabled) return; button.disabled = true; }
  try { return await fn(); } catch (e) { toast(e.message, false); throw e; } finally { if (button) button.disabled = false; }
}
function btn(text, onclick, variant = '', attrs = {}) {
  const b = h('button', {type: 'button', class: 'btn ' + variant, text, ...attrs});
  b.addEventListener('click', () => guard(b, () => onclick(b)).catch(() => {}));
  return b;
}
const Drawer = {
  open(title, content, buttons = [], kicker = '') {
    $('detailKicker').textContent = kicker; $('detailTitle').textContent = title;
    append(clear($('detailContent')), [content]); $('detailContent').scrollTop = 0;
    append(clear($('detailFooter')), buttons.filter(Boolean));
    $('detail').classList.add('open'); $('main').classList.add('details-open');
    $('detail').setAttribute('aria-hidden', 'false'); $('detail').inert = false;
  },
  close() {
    $('detail').classList.remove('open'); $('main').classList.remove('details-open');
    $('detail').setAttribute('aria-hidden', 'true'); $('detail').inert = true;
    document.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
    if (Drawer.onclose) { const fn = Drawer.onclose; Drawer.onclose = null; fn(); }
    // kapanış animasyonundan sonra eski form alanları DOM'da kalmasın (gizli alana yazılmasın, yinelenen kimlik olmasın)
    setTimeout(() => { if (!Drawer.isOpen()) { clear($('detailContent')); clear($('detailFooter')); } }, 300);
  },
  isOpen: () => $('detail').classList.contains('open'),
};
const Modal = {
  open(title, body, buttons = [], wide = false) {
    $('modalTitle').textContent = title; append(clear($('modalBody')), [body]);
    append(clear($('modalFooter')), buttons.filter(Boolean));
    $('modal').classList.toggle('wide', wide); $('modalBack').classList.remove('hidden');
    Modal.previous = document.activeElement;
    setTimeout(() => ($('modalBody').querySelector('input,select,textarea,button') || $('modalClose')).focus(), 30);
  },
  close() { $('modalBack').classList.add('hidden'); clear($('modalBody')); if (Modal.previous) Modal.previous.focus(); },
  isOpen: () => !$('modalBack').classList.contains('hidden'),
};
function confirmDialog(title, message, okText = 'Onayla', variant = '') {
  return new Promise(resolve => {
    Modal.open(title, h('p', {class: 'intro', text: message}), [
      h('button', {type: 'button', class: 'btn secondary', text: 'Vazgeç', onclick: () => { Modal.close(); resolve(false); }}),
      h('button', {type: 'button', class: 'btn ' + variant, text: okText, onclick: () => { Modal.close(); resolve(true); }})]);
  });
}
function setupResize() {
  const handle = $('detailResize'); const root = document.documentElement;
  const apply = w => { const width = Math.max(380, Math.min(Math.round(w), Math.max(420, innerWidth - 520))); root.style.setProperty('--detail-width', width + 'px'); return width; };
  try { const saved = Number(localStorage.getItem('tdr.detailWidth')); if (saved) apply(saved); } catch (e) { /* özel pencere */ }
  handle.addEventListener('pointerdown', e => {
    e.preventDefault(); handle.setPointerCapture(e.pointerId); document.body.classList.add('resizing');
    const move = ev => apply(innerWidth - ev.clientX);
    const up = ev => { document.body.classList.remove('resizing'); handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up);
      try { localStorage.setItem('tdr.detailWidth', String(apply(innerWidth - ev.clientX))); } catch (err) { /* boş */ } };
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up);
  });
  handle.addEventListener('dblclick', () => { apply(560); try { localStorage.removeItem('tdr.detailWidth'); } catch (e) { /* boş */ } });
  handle.addEventListener('keydown', e => {
    const cur = parseInt(getComputedStyle(root).getPropertyValue('--detail-width')) || 560;
    if (e.key === 'ArrowLeft') apply(cur + (e.shiftKey ? 80 : 24)); else if (e.key === 'ArrowRight') apply(cur - (e.shiftKey ? 80 : 24)); else return;
    e.preventDefault();
  });
}

// ------------------------------------------------------------------ grafikler (satır içi SVG)
function barChart(items, {max, format = v => fmt.num(v, 1), onclick} = {}) {
  const rows = items.filter(i => i.value !== null && i.value !== undefined);
  if (!rows.length) return h('div', {class: 'empty', text: 'Henüz veri yok'});
  const top = max || Math.max(...rows.map(i => i.value), 1); const rowH = 30; const labelW = 170; const width = 520;
  const svg = s('svg', {class: 'chart bars', viewBox: `0 0 ${width} ${rows.length * rowH + 4}`, role: 'img', 'aria-label': rows.map(i => i.label + ': ' + format(i.value)).join(', ')});
  rows.forEach((item, i) => {
    const y = i * rowH + 4; const w = Math.max(2, (width - labelW - 60) * item.value / top);
    const g = s('g', onclick ? {class: 'clickable', tabindex: '0'} : {});
    g.append(s('text', {x: 0, y: y + 15}, item.label.length > 26 ? item.label.slice(0, 25) + '…' : item.label));
    g.append(s('rect', {x: labelW, y: y + 3, width: (width - labelW - 60), height: 16, rx: 4, fill: '#f0f1f3'}));
    g.append(s('rect', {x: labelW, y: y + 3, width: w, height: 16, rx: 5, class: 'c' + (item.color ?? 0)}));
    g.append(s('text', {x: labelW + w + 6, y: y + 15, class: 'value'}, format(item.value)));
    if (onclick) { g.addEventListener('click', () => onclick(item)); g.addEventListener('keydown', e => { if (e.key === 'Enter') onclick(item); }); }
    svg.append(g);
  });
  return svg;
}
function donut(items, {center} = {}) {
  const data = items.filter(i => i.value > 0); const total = data.reduce((a, b) => a + b.value, 0);
  const wrap = h('div', {class: 'gauge'});
  const svg = s('svg', {viewBox: '0 0 42 42', role: 'img', 'aria-label': data.map(i => i.label + ': ' + i.value).join(', ')});
  svg.append(s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 6, stroke: '#eceef1'}));
  let offset = 25;
  data.forEach((item, i) => {
    const part = 100 * item.value / total;
    svg.append(s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 6, 'stroke-dasharray': `${part} ${100 - part}`,
      'stroke-dashoffset': offset, stroke: PALETTE[(item.color ?? i) % PALETTE.length]}));
    offset -= part;
  });
  svg.append(s('text', {x: 21, y: 24, 'text-anchor': 'middle', 'font-size': 8, 'font-weight': 800, fill: '#1d2026'}, center ?? String(total)));
  wrap.append(svg, h('div', {class: 'legend'}, data.map((item, i) => h('span', {}, h('i', {class: 'c' + (item.color ?? i % PALETTE.length)}), `${item.label}: ${item.value}`))));
  return wrap;
}
const PALETTE = ['#2f3b52', '#0f8a5f', '#e0a020', '#d50c2d', '#6d4bd1', '#9aa3af', '#ea6c1d'];
function gauge(value, label, {suffix = '', good = 75, mid = 50, sub = '', text = null} = {}) {
  const has = value !== null && value !== undefined; const v = has ? Math.max(0, Math.min(100, value)) : 0;
  const cls = !has ? 'g-none' : v >= good ? 'g-good' : v >= mid ? 'g-mid' : 'g-bad';
  const svg = s('svg', {viewBox: '0 0 42 42', role: 'img', 'aria-label': label + ': ' + (has ? fmt.num(value) + suffix : 'veri yok')},
    s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 5, class: 'g-track', stroke: '#eceef1'}),
    s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 5, 'stroke-dasharray': `${v} ${100 - v}`, 'stroke-dashoffset': 25,
      'stroke-linecap': v > 0 ? 'round' : 'butt', stroke: {'g-good': '#0f8a5f', 'g-mid': '#e0a020', 'g-bad': '#d50c2d', 'g-none': '#d4d7dd'}[cls]}),
    s('text', {x: 21, y: 24.5, 'text-anchor': 'middle', 'font-size': 9, 'font-weight': 800, fill: '#1d2026'}, text ?? (has ? fmt.num(value, 0) + suffix : '—')));
  return h('div', {class: 'gauge'}, svg, h('div', {}, h('div', {class: 'metric-label', text: label}), sub ? h('div', {class: 'metric-foot', text: sub}) : null));
}
function progressBar(value) {
  const v = Math.max(0, Math.min(100, value || 0));
  return s('svg', {class: 'chart', viewBox: '0 0 100 4', preserveAspectRatio: 'none', role: 'img', 'aria-label': '%' + Math.round(v)},
    s('rect', {x: 0, y: 0, width: 100, height: 4, rx: 2, fill: '#eceef1'}), s('rect', {x: 0, y: 0, width: v, height: 4, rx: 2, fill: '#d50c2d'}));
}
function metric(label, value, foot = '', cls = '', onclick = null) {
  const el = h(onclick ? 'button' : 'div', {class: 'metric ' + cls, type: onclick ? 'button' : null},
    h('span', {class: 'metric-label', text: label}), h('span', {class: 'metric-number', text: value}), foot ? h('div', {class: 'metric-foot', text: foot}) : null);
  if (onclick) el.addEventListener('click', onclick);
  return el;
}
function empty(title, text, action) { return h('div', {class: 'empty'}, h('strong', {text: title}), text ? h('div', {text}) : null, action ? h('div', {class: 'no-print'}, h('br'), action) : null); }
function kv(pairs) { return h('dl', {class: 'kv'}, pairs.filter(Boolean).map(([k, v]) => [h('dt', {text: k}), h('dd', {}, v === null || v === undefined || v === '' ? h('span', {class: 'muted', text: '—'}) : v)])); }
function section(title, content, action) { return h('div', {class: 'section'}, h('h3', {}, h('span', {text: title}), action || null), content); }
function tabs(items, initial, onchange) {
  const bar = h('div', {class: 'tabs', role: 'tablist'}); const body = h('div');
  const show = key => {
    if (onchange) onchange(key);
    bar.querySelectorAll('.tab').forEach(t => { const on = t.dataset.key === key; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
    const item = items.find(i => i.key === key); clear(body); const r = item.render(); if (r instanceof Promise) r.then(n => append(body, [n])); else append(body, [r]);
    requestAnimationFrame(() => { // seçili sekme taşan çubukta görünür kalsın
      const a = bar.querySelector('.tab.active'); if (!a || bar.scrollWidth <= bar.clientWidth) return;
      const box = bar.getBoundingClientRect(), tab = a.getBoundingClientRect();
      if (tab.right > box.right) bar.scrollLeft += tab.right - box.right + 24; else if (tab.left < box.left) bar.scrollLeft -= box.left - tab.left + 24;
    });
  };
  for (const item of items) bar.append(h('button', {type: 'button', class: 'tab', role: 'tab', dataset: {key: item.key}, onclick: () => show(item.key)},
    item.label, item.count !== undefined ? h('span', {class: 'count', text: item.count}) : null));
  show(initial || items[0].key);
  return h('div', {}, bar, body);
}

// ------------------------------------------------------------------ formlar
function inputFor(res, f, value) {
  const id = 'f_' + f.name; let control;
  if (f.options) {
    control = h('select', {id, name: f.name}, f.required ? null : h('option', {value: '', text: '— Seçin —'}),
      f.options.map(o => h('option', {value: o.value, text: o.label, selected: o.value === value})));
    if (f.required && (value === null || value === undefined)) control.value = f.options[0].value;
  } else if (f.ref && LARGE_REFS.has(f.ref)) {
    control = refSearch(f, value, id);
  } else if (f.ref) {
    const records = S.cache[f.ref] || [];
    control = h('select', {id, name: f.name}, h('option', {value: '', text: f.required ? '— Seçin —' : '— Yok —'}),
      records.slice().sort((a, b) => titleOf(a).localeCompare(titleOf(b), TR)).map(r => h('option', {value: r.id, text: titleOf(r), selected: r.id === value})));
  } else if (FLAGS.has(f.name)) {
    control = h('input', {id, name: f.name, type: 'checkbox', checked: value === undefined || value === null ? f.name === 'active' || f.name === 'required' : !!value});
    return h('label', {class: 'toggle', for: id}, control, h('span', {text: f.label}));
  } else if (LONG.has(f.name)) {
    control = h('textarea', {id, name: f.name, value: value ?? ''});
  } else if (f.kind === 'DATE') {
    control = h('input', {id, name: f.name, type: 'date', value: value ?? ''});
  } else if (f.kind === 'TIMESTAMP') {
    let local = '';
    if (value) { const d = new Date(value); local = new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
    control = h('input', {id, name: f.name, type: 'datetime-local', value: local});
  } else if (['INTEGER', 'REAL', 'DECIMAL'].includes(f.kind)) {
    control = h('input', {id, name: f.name, type: 'number', step: f.kind === 'INTEGER' ? '1' : 'any', value: value ?? ''});
  } else {
    control = h('input', {id, name: f.name, type: f.name === 'email' ? 'email' : f.name === 'website' ? 'url' : 'text', value: value ?? '', autocomplete: 'off',
      list: PERSON.has(f.name) ? 'peopleList' : null});
  }
  return h('label', {class: 'field' + (LONG.has(f.name) ? ' wide' : ''), for: id},
    h('span', {}, f.label, f.required ? h('span', {class: 'req', text: ' *'}) : null), h('div', {class: 'control'}, control));
}
function readForm(form, res, fields) {
  const data = {}; const errors = {};
  for (const f of fields) {
    const el = form.querySelector(`[name="${f.name}"]`); if (!el) continue;
    let v;
    if (el.type === 'checkbox') v = el.checked ? 1 : 0;
    else if (el.value === '') v = null;
    else if (f.ref || (f.kind === 'INTEGER' && !f.options)) v = Number(el.value);
    else if (f.kind === 'REAL' || f.kind === 'DECIMAL') v = Number(el.value);
    else if (f.kind === 'TIMESTAMP') v = new Date(el.value).toISOString();
    else v = el.value.trim() || null;
    if (f.required && (v === null || v === '')) errors[f.name] = 'Bu alan zorunlu';
    if (el.type === 'number' && el.value !== '' && Number.isNaN(Number(el.value))) errors[f.name] = 'Sayı girin';
    data[f.name] = v;
  }
  return {data, errors};
}
function showErrors(form, errors, message) {
  form.querySelectorAll('.field.invalid').forEach(x => { x.classList.remove('invalid'); x.querySelector('.error')?.remove(); });
  for (const [name, text] of Object.entries(errors)) {
    const field = form.querySelector(`[name="${name}"]`)?.closest('.field'); if (!field) continue;
    field.classList.add('invalid'); field.append(h('span', {class: 'error', text}));
  }
  const box = form.querySelector('.form-error'); if (box) { box.textContent = message || ''; box.classList.toggle('hidden', !message); }
  const first = form.querySelector('.field.invalid input,.field.invalid select,.field.invalid textarea'); if (first) first.focus();
}
const AUTO = new Set(['created_at', 'updated_at', 'id']);
function editableFields(res, {only, skip = []} = {}) {
  const fields = (META.def(res).fields || []).filter(f => !f.readonly && !AUTO.has(f.name) && (!f.name.endsWith('_json') || res === 'policies') && !skip.includes(f.name) && (!only || only.includes(f.name)));
  return only ? fields.sort((a, b) => only.indexOf(a.name) - only.indexOf(b.name)) : fields;      // form sırası `only` listesindeki sıradır
}
/** Kayıt formu: oluşturma ve düzenleme. Yalnızca değişen alanlar gönderilir. */
async function recordForm(res, record = null, {defaults = {}, only, skip, title, onsaved, extra} = {}) {
  const def = META.def(res); const fields = editableFields(res, {only, skip});
  await Promise.all([loadRefs(res, fields.map(f => f.name)), fields.some(f => PERSON.has(f.name)) ? ensurePeople() : null]);
  const form = h('form', {class: 'formgrid', novalidate: true});
  form.append(h('div', {class: 'notice bad wide form-error hidden', role: 'alert'}));
  if (def.unit_scoped && S.me.role === 'UNIT_USER') form.append(h('div', {class: 'notice wide', text: 'Yalnızca kendi biriminizin kayıtlarını değiştirebilirsiniz.'}));
  for (const f of fields) form.append(inputFor(res, f, record ? record[f.name] : defaults[f.name]));
  if (extra) form.append(extra);
  const save = async button => {
    const {data, errors} = readForm(form, res, fields);
    if (Object.keys(errors).length) { showErrors(form, errors, 'Eksik veya hatalı alanları düzeltin'); return; }
    let payload = data;
    if (record) { payload = {}; for (const [k, v] of Object.entries(data)) if ((record[k] ?? null) !== v) payload[k] = v; if (!Object.keys(payload).length) { toast('Değişiklik yok'); return; } }
    else {
      for (const k of Object.keys(payload)) if (payload[k] === null) delete payload[k];
      for (const [k, v] of Object.entries(defaults)) if (!(k in payload) && !fields.some(f => f.name === k) && META.field(res, k)) payload[k] = v;   // gizli bağlam (ör. şablon)
    }
    try {
      const result = record ? await api(`${res}/${record.id}`, {method: 'PATCH', body: payload}) : await api(res, {method: 'POST', body: payload});
      invalidate(res); toast(record ? 'Kaydedildi' : 'Kayıt oluşturuldu');
      if (onsaved) await onsaved(record ? result : {...payload, id: result.id});
    } catch (e) {
      const match = /alan eksik: (.+)$|^([a-z_]+)[ :]/.exec(e.message);
      const name = match && (match[1] || match[2]);
      showErrors(form, name && fields.some(f => f.name === name) ? {[name]: e.message} : {}, e.message);
      throw e;
    }
  };
  form.addEventListener('submit', e => { e.preventDefault(); save(); });
  Drawer.open(title || (record ? 'Düzenle: ' + titleOf(record) : 'Yeni: ' + def.label), form,
    [btn('Vazgeç', () => (record ? openRecord(res, record.id) : Drawer.close()), 'secondary'), btn(record ? 'Kaydet' : 'Oluştur', save)], def.label);
  setTimeout(() => form.querySelector('input:not([type=checkbox]),select,textarea')?.focus(), 50);
}

// ------------------------------------------------------------------ yönlendirici ve gezinme
const Router = {
  parse() {
    const raw = location.hash.replace(/^#\/?/, ''); const [path, query] = raw.split('?');
    return {parts: path ? path.split('/').map(decodeURIComponent) : [], params: new URLSearchParams(query || '')};
  },
  go(path) { const target = '#/' + path; if (location.hash === target) render(); else location.hash = target; },
};
function setPage(title, sub = '', actions = [], crumbs = []) {
  $('pageTitle').textContent = title; $('pageSub').textContent = sub; document.title = title + ' • ' + (S.meta?.app_name || 'GRC Platformu');
  append(clear($('topActions')), actions.filter(Boolean));
  const trail = [['Genel Bakış', '']].concat(crumbs);
  append(clear($('crumbs')), [trail.map((c, i) => [i ? ' / ' : '', h('a', {href: '#/' + c[1], text: c[0]})]), title !== 'Genel Bakış' ? [' / ', h('span', {text: title})] : []]);
}
function content(...nodes) { const c = clear($('content')); append(c, nodes); return c; }

// ------------------------------------------------------------------ menü ve ekran tanımları
// Menü: [başlık, [[rota, ikon, etiket?, gereken yetki?]]]. Etiket yoksa kaynağın Türkçe adı kullanılır.
const MENU = [
  ['Genel', [['home', 'home', 'Genel Bakış'], ['my-work', 'inbox', 'İşlerim'], ['calendar', 'calendar', 'GRC Takvimi'], ['health', 'pulse', 'GRC Sağlık Kontrolü'], ['my-surveys', 'edit', 'Anketlerim']]],
  ['Risk yönetimi', [['risk', 'gauge', 'Risk Panosu'], ['r/supplier_risks', 'alert'], ['r/risk_actions', 'trend'], ['r/kris', 'activity'], ['r/rcsa_campaigns', 'check'], ['r/loss_events', 'coin'], ['r/risk_cycles', 'repeat'], ['r/risk_catalog', 'book'], ['r/risk_appetites', 'target'], ['r/risk_criteria', 'sliders']]],
  ['Uyum', [['compliance', 'shield', 'Uyum Panosu'], ['library', 'book', 'Standart Kütüphanesi'], ['obligations', 'scale', 'Yükümlülükler'], ['r/controls', 'check'], ['r/objectives', 'target'], ['r/policy_exceptions', 'flag'], ['r/attestation_campaigns', 'edit'], ['r/certifications', 'star'], ['r/access_reviews', 'users']]],
  ['Denetim', [['audit-plan', 'calendar', 'Denetim Planı'], ['r/audits', 'search'], ['r/evidence_requests', 'inbox'], ['r/findings', 'flag'], ['r/grc_actions', 'repeat'], ['r/evidence', 'paperclip'], ['archive', 'archive', 'Denetim Arşivi']]],
  ['İş sürekliliği', [['bcm', 'lifebuoy', 'Süreklilik Panosu'], ['crisis', 'zap', 'Kriz Yönetimi'], ['r/bias', 'layers'], ['r/bc_plans', 'clipboard'], ['r/bc_exercises', 'zap']]],
  ['Dokümanlar', [['r/documents', 'file']]],
  ['Varlıklar (CMDB)', [['cmdb', 'server', 'CMDB Panosu'], ['r/cmdb_cis', 'box'], ['r/ci_exposures', 'alert']]],
  ['Veri yönetişimi', [['datagov', 'database', 'Veri Yönetişimi Paneli'], ['glossary', 'book', 'İş Sözlüğü'], ['catalog', 'layers', 'Veri Kataloğu'],
    ['r/data_sources', 'server'], ['collectors', 'plug', 'Toplayıcılar'], ['lineage', 'flow', 'Soy Kütüğü'], ['quality', 'check', 'Veri Kalitesi'], ['ai', 'cpu', 'Yapay Zekâ Envanteri'], ['r/data_domains', 'grid'], ['stewardship', 'users', 'Sahiplik Matrisi']]],
  ['Kişisel veri (KVKK)', [['privacy', 'shield', 'KVKK Panosu'], ['regulation', 'target', 'KVKK / GDPR Boşluk Analizi'], ['discovery', 'search', 'Kişisel Veri Keşfi'], ['r/processing_activities', 'clipboard'],
    ['r/subject_requests', 'mail'], ['r/data_requests', 'inbox'], ['r/privacy_breaches', 'alert'], ['r/dpias', 'scale'], ['r/retention_rules', 'clock'],
    ['r/disposal_runs', 'archive']]],
  ['Tedarikçi yönetimi', [['r/suppliers', 'building'], ['r/engagements', 'link'], ['r/contracts', 'file'], ['r/catalog_items', 'grid'], ['schedule', 'clock', 'Değerlendirme takvimi'], ['r/sla_definitions', 'clock'], ['r/sla_measurements', 'check'], ['r/performance_events', 'flag'], ['r/performance_reviews', 'star'], ['r/survey_templates', 'list'], ['r/survey_campaigns', 'mail']]],
  ['Mimari', [['process-map', 'flow', 'Süreç Haritası'], ['map', 'share', 'İlişki Haritası'], ['r/processes', 'flow'], ['r/audit_universe', 'grid']]],
  ['Kaynak bulma', [['r/needs', 'search'], ['r/quotes', 'coin']]],
  ['Yönetim', [['roadmap', 'route', 'Yol Haritası'], ['integrations', 'plug', 'Entegrasyonlar', 'admin'], ['notifications', 'bell', 'Bildirimler', 'admin'], ['users', 'users', 'Kullanıcılar', 'admin'], ['roles', 'key', 'Rol ve Yetki Matrisi'], ['r/companies', 'building'], ['r/org_units', 'home'], ['r/policies', 'sliders'], ['transfer', 'swap', 'Aktarım', 'manage'], ['r/import_batches', 'list'], ['r/cmdb_sync_runs', 'repeat'], ['r/personal_data_categories', 'list'], ['r/data_subject_groups', 'users'], ['r/supplier_types', 'grid'], ['r/review_criteria', 'star'], ['r/audit_log', 'list']]],
];
const ICONS = {
  home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z', inbox: 'M3 13l3-8h12l3 8v6H3zM3 13h5l1 3h6l1-3h5',
  calendar: 'M4 5h16v15H4zM4 10h16M8 3v4M16 3v4', pulse: 'M3 12h4l2-6 4 12 2-6h6', edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  gauge: 'M4 16a8 8 0 1 1 16 0M12 16l4-5M4 16h2M18 16h2', alert: 'M12 4l9 16H3zM12 10v4M12 17v.5', trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  activity: 'M3 12h4l3 7 4-14 3 7h4', repeat: 'M17 2l3 3-3 3M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3M20 13v2a4 4 0 0 1-4 4H4',
  book: 'M4 4h11a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3zM4 17a3 3 0 0 1 3-3h11', target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 12h.01',
  sliders: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4', shield: 'M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7zM9 12l2 2 4-4',
  check: 'M4 12l5 5L20 6', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5', flag: 'M5 21V4h11l-1.5 4L16 12H5',
  paperclip: 'M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7', lifebuoy: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5', clipboard: 'M9 4h6v3H9zM7 5H5v16h14V5h-2M8 11h8M8 15h6', zap: 'M13 2L4 14h7l-1 8 9-12h-7z',
  file: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5', server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01', box: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
  building: 'M4 21V5l8-3v19M12 9h8v12M7 8h2M7 12h2M7 16h2M15 13h2M15 17h2M2 21h20', link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 3',
  star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z', list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  mail: 'M3 5h18v14H3zM3 6l9 7 9-7', flow: 'M3 6h6v4H3zM15 14h6v4h-6zM9 8h3a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2', share: 'M18 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4',
  coin: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 9h4.5a2 2 0 0 1 0 4H9h5a2 2 0 0 1 0 4H9M11 7v2M11 17v-2', users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.5a4 4 0 0 1 0 7.5M22 21a7 7 0 0 0-4-6.3',
  swap: 'M7 4L3 8l4 4M3 8h14M17 12l4 4-4 4M21 16H7', plug: 'M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0', scale: 'M12 3v18M5 21h14M4 7h16M7 7l-3 7h6zM17 7l-3 7h6z', archive: 'M3 4h18v4H3zM5 8v12h14V8M10 12h4',
  database: 'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  key: 'M15 3a6 6 0 0 0-5.6 8.2L3 18.6V21h3v-2h2v-2h2l1.8-1.8A6 6 0 1 0 15 3zM16.5 6.5h.01', cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
  route: 'M6 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 17V9a4 4 0 0 1 4-4h6M18 7v8a4 4 0 0 1-4 4H8', chev: 'M6 9l6 6 6-6', plus: 'M12 5v14M5 12h14', download: 'M12 4v12M7 11l5 5 5-5M5 20h14',
};
function icon(name, cls = '') {
  return s('svg', {viewBox: '0 0 24 24', class: 'icon ' + cls, 'aria-hidden': 'true'}, s('path', {d: ICONS[name] || ICONS.list}));
}
const PAGES = {};   // ek sayfalar (pages.js): PAGES[rota](parçalar, parametreler)
const COLUMNS = {
  suppliers: ['code', 'name', 'tier', 'status', 'segment', 'owner', 'city'],
  engagements: ['code', 'supplier_id', 'catalog_item_id', 'org_unit_id', 'beneficiary', 'criticality', 'business_owner', 'status'],
  contracts: ['code', 'title', 'supplier_id', 'end_date', 'notice_days', 'status'],
  catalog_items: ['code', 'name', 'kind', 'category', 'active'], org_units: ['code', 'name', 'parent_id', 'manager', 'active'],
  supplier_types: ['code', 'name', 'description', 'active'], review_criteria: ['code', 'name', 'weight', 'active'],
  supplier_contacts: ['name', 'supplier_id', 'role', 'email', 'phone', 'is_primary'],
  responsibilities: ['person', 'role', 'raci', 'supplier_id', 'engagement_id'],
  source_refs: ['supplier_id', 'source_system', 'external_id', 'external_name', 'last_seen_at'],
  sla_definitions: ['code', 'name', 'engagement_id', 'target_value', 'unit', 'direction', 'period', 'active'],
  sla_measurements: ['sla_id', 'period_start', 'actual_value', 'met', 'source', 'recorded_by'],
  performance_events: ['occurred_at', 'supplier_id', 'event_type', 'severity', 'description', 'source'],
  performance_reviews: ['supplier_id', 'engagement_id', 'period_start', 'period_end', 'reviewer'],
  review_scores: ['review_id', 'criterion_id', 'score', 'note'],
  supplier_risks: ['code', 'title', 'company_id', 'category', 'risk_level', 'residual_score', 'owner', 'status', 'review_date'],
  companies: ['code', 'name', 'kind', 'parent_id', 'sector', 'active'],
  kris: ['code', 'name', 'risk_id', 'last_value', 'unit', 'last_status', 'last_measured_at', 'owner'],
  kri_values: ['kri_id', 'period', 'value', 'status', 'source', 'recorded_by'],
  risk_cycles: ['code', 'name', 'company_id', 'period_start', 'period_end', 'status', 'owner'],
  risk_appetites: ['code', 'category', 'appetite', 'tolerance', 'statement', 'review_date', 'active'],
  risk_criteria: ['dimension', 'level', 'label', 'frequency', 'financial', 'operational'],
  cmdb_cis: ['code', 'name', 'ci_class', 'company_id', 'environment', 'business_criticality', 'os', 'os_version', 'source', 'stale'],
  ci_exposures: ['ci_id', 'rule', 'status', 'detail', 'detected_at', 'risk_id'],
  cmdb_sync_runs: ['started_at', 'source', 'mode', 'status', 'created', 'updated', 'unchanged', 'stale_marked'],
  bias: ['code', 'title', 'process_id', 'company_id', 'criticality', 'mtpd_hours', 'rto_hours', 'rpo_hours', 'status', 'review_date'],
  bc_plans: ['code', 'title', 'plan_type', 'company_id', 'owner', 'version', 'status', 'review_date'],
  bc_exercises: ['code', 'title', 'exercise_type', 'plan_id', 'planned_date', 'status', 'outcome'],
  bc_plan_steps: ['plan_id', 'phase', 'position', 'action', 'responsible', 'target_minutes'],
  bia_applications: ['bia_id', 'ci_id', 'required_rto_hours', 'note'], bia_suppliers: ['bia_id', 'supplier_id', 'engagement_id', 'note'],
  bia_risks: ['bia_id', 'risk_id', 'note'], bc_plan_applications: ['plan_id', 'ci_id', 'recovery_order', 'target_rto_hours'],
  risk_actions: ['code', 'title', 'risk_id', 'owner', 'due_date', 'priority', 'status'],
  survey_templates: ['code', 'name', 'purpose', 'version', 'status', 'updated_at'],
  survey_campaigns: ['code', 'name', 'template_id', 'subject', 'audience', 'status', 'closes_on'],
  audit_log: ['occurred_at', 'actor', 'method', 'object_type', 'object_id', 'description'],
  import_batches: ['created_at', 'kind', 'source_system', 'filename', 'status', 'created_by'],
  policies: ['code', 'value_json', 'description'],
  standards: ['code', 'name', 'version', 'issuer', 'active'], clauses: ['code', 'title', 'standard_id', 'clause_type', 'applicable'],
  clause_links: ['from_clause_id', 'relation', 'to_clause_id', 'source', 'active'],
  evidence_requests: ['code', 'title', 'audit_id', 'assignee', 'due_date', 'status'], workpapers: ['code', 'title', 'audit_id', 'preparer', 'result', 'status'],
  audit_universe: ['code', 'name', 'entity_type', 'inherent_rating', 'frequency_months', 'owner'], audit_plans: ['code', 'year', 'title', 'status', 'approved_by'],
  certifications: ['code', 'title', 'certification_body', 'expires_on', 'next_surveillance', 'status'],
  obligations: ['code', 'title', 'source', 'article', 'regulator', 'applicability'], policy_exceptions: ['code', 'title', 'owner', 'end_date', 'risk_level', 'status'],
  attestation_campaigns: ['code', 'title', 'document_id', 'due_date', 'status'], attestations: ['campaign_id', 'display_name', 'status', 'acknowledged_at'],
  notifications: ['created_at', 'channel', 'recipient', 'subject', 'status'],
  loss_events: ['code', 'title', 'event_type', 'occurred_on', 'net_loss', 'status'], privacy_breaches: ['code', 'title', 'detected_at', 'notify_decision', 'status', 'owner'],
  rcsa_campaigns: ['code', 'title', 'period', 'due_date', 'status'], access_reviews: ['code', 'title', 'system', 'reviewer', 'due_date', 'status'],
  bc_incidents: ['code', 'title', 'severity', 'declared_at', 'status'],
  processes: ['code', 'name', 'process_type', 'parent_id', 'owner', 'org_unit_id', 'active'], objectives: ['code', 'name', 'process_id', 'owner'],
  documents: ['code', 'title', 'category', 'version', 'process_id', 'owner', 'status', 'effective_date', 'review_date'],
  controls: ['code', 'name', 'execution_mode', 'frequency', 'criticality', 'owner', 'active'],
  audits: ['code', 'name', 'kind', 'status', 'planned_start', 'planned_end', 'lead_auditor'],
  findings: ['code', 'title', 'source', 'severity', 'status', 'owner', 'due_date', 'recurrence'],
  grc_actions: ['code', 'title', 'owner', 'org_unit_id', 'due_date', 'priority', 'status'],
  evidence: ['code', 'title', 'source', 'confidentiality', 'status', 'expires_at', 'current_version'],
  executions: ['executed_at', 'control_id', 'status', 'source', 'audit_id', 'recorded_by'],
  risk_catalog: ['code', 'title', 'category', 'likelihood', 'impact', 'active'],
  needs: ['code', 'title', 'org_unit_id', 'requester', 'needed_by'], quotes: ['need_id', 'supplier_id', 'amount', 'currency', 'received_at'],
  data_domains: ['code', 'name', 'parent_id', 'org_unit_id', 'owner', 'steward', 'active'],
  data_sources: ['code', 'name', 'platform', 'environment', 'domain_id', 'owner', 'custodian', 'last_import_at'],
  data_tables: ['name', 'schema_name', 'source_id', 'business_name', 'object_type', 'classification', 'status'],
  data_columns: ['name', 'table_id', 'business_name', 'data_type', 'classification', 'personal_data', 'status'],
  glossary_terms: ['code', 'name', 'domain_id', 'owner', 'status', 'version'], catalog_imports: ['created_at', 'source_id', 'kind', 'format', 'filename', 'created_by'],
  catalog_changes: ['created_at', 'source_id', 'change', 'object_name', 'detail'], glossary_term_versions: ['term_id', 'version', 'approved_by', 'created_at'],
  roadmap_items: ['module', 'phase', 'title', 'status', 'target'],
  personal_data_categories: ['name', 'special', 'keywords', 'active'], data_subject_groups: ['name', 'description', 'active'],
  processing_activities: ['code', 'name', 'legal_basis', 'org_unit_id', 'owner', 'foreign_transfer', 'status'],
  retention_rules: ['code', 'name', 'period_value', 'period_unit', 'trigger_event', 'disposal_method', 'active'],
  disposal_runs: ['code', 'title', 'planned_date', 'owner', 'status', 'completed_at'],
  data_requests: ['code', 'kind', 'table_id', 'requested_by', 'status', 'access_until', 'created_at'],
  subject_requests: ['code', 'received_on', 'request_type', 'channel', 'owner', 'due_date', 'status'],
  dpias: ['code', 'title', 'activity_id', 'residual_risk', 'decision', 'status'], pii_suggestions: ['column_id', 'category_id', 'confidence', 'method', 'status'],
};
const FILTERS = {
  suppliers: ['tier', 'status', 'segment', 'type_id'], engagements: ['supplier_id', 'org_unit_id', 'beneficiary', 'criticality', 'status'],
  contracts: ['supplier_id', 'status'], catalog_items: ['kind'], supplier_risks: ['company_id', 'status', 'risk_level', 'category', 'source', 'process_id'],
  companies: ['kind'], kris: ['last_status', 'frequency'], risk_cycles: ['status', 'company_id'], cmdb_cis: ['ci_class', 'environment', 'company_id', 'business_criticality', 'source'],
  ci_exposures: ['rule', 'status'], cmdb_sync_runs: ['status', 'source'], bias: ['status', 'criticality', 'company_id'], bc_plans: ['status', 'plan_type'],
  bc_exercises: ['status', 'exercise_type', 'outcome'], processes: ['process_type'], objectives: ['process_id'],
  risk_actions: ['status', 'priority'], performance_events: ['supplier_id', 'event_type', 'severity'], sla_measurements: ['sla_id', 'met'],
  sla_definitions: ['engagement_id'], performance_reviews: ['supplier_id'], survey_campaigns: ['status', 'subject'],
  survey_templates: ['purpose', 'status'], import_batches: ['kind'],
  clauses: ['standard_id', 'applicable'], clause_links: ['relation', 'source', 'active'], evidence_requests: ['status', 'audit_id'], workpapers: ['status', 'audit_id'],
  audit_universe: ['entity_type', 'active'], certifications: ['status', 'standard_id'], obligations: ['regulator', 'source_type', 'applicability'],
  policy_exceptions: ['status', 'risk_level'], attestation_campaigns: ['status'], notifications: ['channel', 'status'],
  loss_events: ['event_type', 'status', 'company_id'], privacy_breaches: ['status', 'notify_decision'], rcsa_campaigns: ['status'], access_reviews: ['status'], controls: ['execution_mode', 'frequency', 'criticality', 'active'], audits: ['kind', 'status'],
  findings: ['source', 'severity', 'status'], grc_actions: ['status', 'priority'], evidence: ['status', 'confidentiality', 'source'],
  documents: ['category', 'status', 'process_id'], executions: ['status', 'source'], risk_catalog: ['category'],
  data_sources: ['platform', 'environment', 'domain_id', 'status'], data_domains: ['org_unit_id', 'active'], catalog_changes: ['source_id', 'change'],
  catalog_imports: ['source_id', 'kind'], roadmap_items: ['module', 'status'],
  processing_activities: ['status', 'legal_basis', 'org_unit_id'], data_requests: ['status', 'kind'], subject_requests: ['status', 'request_type', 'channel'],
  dpias: ['status'], disposal_runs: ['status'], personal_data_categories: ['special', 'active'],
};
const DESCRIPTIONS = {
  suppliers: 'Tekil tüzel kişiler. Kritiklik seviyesi değerlendirme, anket ve risk gözden geçirme sıklığını belirler.',
  engagements: 'Hangi birim, hangi ürün veya hizmeti, kimden, kimin için ve kimin sahipliğinde alıyor.',
  contracts: 'Sözleşme referansları; asıl kayıt kaynak sistemdedir.', catalog_items: 'Alınan ürün ve hizmetler.',
  sla_definitions: 'Angajman bazında hizmet seviyesi hedefleri.', sla_measurements: 'Dönemlik ölçümler; hedefin tutup tutmadığı sunucuda hesaplanır.',
  performance_events: 'SLA ihlali, kesinti, gecikme, eskalasyon ve takdir kayıtları.', performance_reviews: 'Kriter bazlı dönemlik değerlendirmeler.',
  supplier_risks: 'Kurumsal risk kaydı (ISO 31000): kendi şirketlerimizin ve müşterilerimizin riskleri; tedarikçi, CMDB ve anket kaynaklı riskler dahil. Olasılık × etki, kontrol katkısı, artık risk, iştah ve değişmez kararlar.',
  companies: 'Kendi grup şirketlerimiz ve müşterilerimiz. Her risk, BİA, plan ve CI bir şirkete bağlanır; böylece kendi risklerimizle müşteri riskleri ayrışır.',
  kris: 'Anahtar risk göstergeleri: eşik aşıldığında riskin yeniden değerlendirilmesi gerektiğini erken bildirir.',
  kri_values: 'Gösterge ölçümleri; durum (yeşil, sarı, kırmızı) eşiklere göre sunucuda hesaplanır ve değiştirilemez.',
  risk_cycles: 'Dönemsel risk değerlendirmeleri (ör. yarıyıl). İlerleme, dönem içinde değerlendirilen risklerle ölçülür.',
  risk_appetites: 'Kategori bazında risk iştahı ve toleransı; yeni riskin iştah eşiği buradan gelir.',
  risk_criteria: 'Olasılık ve etki ölçeklerinin tanımları (ISO 31000 6.3.4). Değerlendirmede ortak dil sağlar.',
  cmdb_cis: 'Konfigürasyon öğeleri: ServiceNow CMDB\'den senkronlanan veya MCP ile itilen uygulama, sunucu ve veritabanları.',
  ci_exposures: 'CMDB kurallarının bulduğu riskli öğeler: destek dışı İS ve uygulama, eksik kritik yama, uzun süre yeniden başlatılmama.',
  cmdb_sync_runs: 'CMDB senkron çalıştırmalarının değiştirilemez kaydı.',
  bias: 'İş etki analizleri (ISO 22301 8.2.2): kesintinin zamanla etkisi, MTPD, RTO, RPO ve uygulama, tedarikçi bağımlılıkları.',
  bc_plans: 'İş sürekliliği ve felaket kurtarma planları: devreye alma, müdahale, kurtarma ve normale dönüş adımları.',
  bc_exercises: 'Tatbikatlar (ISO 22301 8.5): planın sınanması, hedef ve gerçekleşen kurtarma süresi, alınan dersler ve bulgular.',
  risk_catalog: 'Yeniden kullanılabilir risk senaryoları. Bir senaryodan risk kaydı açabilirsiniz.',
  standards: 'Uyulması gereken standart ve düzenlemeler. Maddeler kontrollerle eşlenir.',
  clauses: 'Standart maddeleri. Kapsam dışı bırakılan madde gerekçe ister (uygulanabilirlik bildirimi).',
  clause_links: 'Standartlar arası madde ilişkileri (çapraz eşleme). Bir maddedeki bulgu, eşdeğer veya kapsayan maddeleri de etkiler.',
  evidence_requests: 'Denetçinin kontrol başına istediği kanıtlar (PBC). Kişi kanıtı yükler veya mevcut kanıtı gösterir; denetçi kabul eder veya iade eder.',
  workpapers: 'Denetim çalışma kâğıtları: test adımları, örneklem, sonuç ve ikinci denetçinin gözden geçirme onayı (IIA 2340).',
  audit_universe: 'Denetlenebilir birimler: süreç, şirket, tedarikçi, uygulama, yönetim sistemi. Öncelik puanı yıllık planı belirler.',
  audit_plans: 'Risk bazlı yıllık iç denetim planları ve onayları. Plan ekranı: Denetim → Denetim Planı.',
  certifications: 'Belgelendirmeler (ör. ISO/IEC 27001): kuruluş, kapsam, geçerlilik ve gözetim denetimi takvimi.',
  obligations: 'Mevzuat ve sözleşme yükümlülükleri; kontrol ve standart maddeleriyle eşlenir. Özet: Uyum → Yükümlülükler.',
  policy_exceptions: 'Politika istisnaları: gerekçe, telafi edici kontrol ve süre. Talep eden onaylayamaz; süresi dolan istisna kendiliğinden kapanır.',
  attestation_campaigns: 'Politika okundu beyanı kampanyaları; kapanınca sonuç kanıt olarak kaydedilir.',
  notifications: 'E-posta ve Teams bildirim kutusu.',
  loss_events: 'Operasyonel olay ve gerçekleşen kayıplar (brüt, geri kazanım, net); risklere bağlanır ve nicel analizi gerçek veriyle besler.',
  privacy_breaches: 'Kişisel veri ihlalleri (KVKK md. 12/5): tespitten itibaren 72 saat içinde Kurula bildirim, karar ve gerekçe.',
  rcsa_campaigns: 'Risk ve kontrol öz değerlendirmesi: süreç sahipleri risklerini ve kontrollerinin işleyişini dönemsel olarak değerlendirir.',
  access_reviews: 'Erişim gözden geçirme kampanyaları: her hesap–yetki için kalsın/kaldırılsın kararı; sonuç kanıt olarak kontrole bağlanır.',
  bc_incidents: 'Kriz kayıtları. Etkin krizi yönetmek için: İş sürekliliği → Kriz Yönetimi.',
  processes: 'Süreç haritası (ISO 9001 4.4): yönetim, ana ve destek süreçleri; riskler, kontroller, BİA ve dokümanlar sürece bağlanır.',
  objectives: 'Kontrol hedefleri: hangi riski ele aldığı ve hangi kontrollerle karşılandığı izlenir.',
  documents: 'Dokümante edilmiş bilgi (ISO 9001 7.5): taslak → onay → yayın; her yayın değiştirilemez bir revizyon ve dosya bütünlük özeti bırakır.',
  controls: 'Kontrol kütüphanesi. Manuel kontroller denetçi tarafından, otomatik kontroller MCP veya portal verisiyle test edilir.',
  audits: 'Denetim planı, kapsamı ve yürütme durumu. Tamamlanan denetimin planı dondurulur.',
  findings: 'Denetim, kontrol testi, tatbikat ve diğer kaynaklardan doğan bulgular; DÖF ile kapatılır.',
  grc_actions: 'Düzeltici ve önleyici faaliyetler (DÖF). Etkinliği faaliyet sahibinden farklı biri doğrular.',
  evidence: 'Kanıt kayıtları ve değiştirilemez dosya sürümleri (SHA-256 ile).',
  risk_actions: 'Risk işleme faaliyetleri.', survey_templates: 'Memnuniyet, risk ve bağımsız anket şablonları. Yayımlanan şablon donar.',
  survey_campaigns: 'Şablonun uygulanması: değerlendirilen tedarikçiler, davetliler, yanıtlar ve sonuçlar.',
  audit_log: 'Her yazma işleminin değiştirilemez izi.', import_batches: 'İçe aktarım geçmişi ve satır sonuçları.',
  org_units: 'İş birimleri. Birim Kullanıcıları yalnızca kendi birimlerinin kayıtlarına yazar.',
  policies: 'Süreç kuralları kodda değil burada durur: değerlendirme ve anket sıklığı, uyarı süresi, teklif sayısı. Değer JSON biçimindedir.',
  data_domains: 'İş alanına göre veri grupları (Müşteri, Satış, Finans...). Sorumlu birim, veri sahibi ve veri yöneticisi buradan alanın tablolarına ve terimlerine devralınır.',
  data_sources: 'Verinin durduğu sistemler: SAP HANA, ServiceNow, Dynamics 365, Power BI, veritabanları ve dosyalar. Tablo ve kolonlar kaynağın ekranından dosyayla içe aktarılır.',
  catalog_imports: 'Katalog içe aktarımlarının değiştirilemez geçmişi.', catalog_changes: 'İçe aktarımlarda görülen şema değişiklikleri: eklenen, kaldırılan, geri gelen ve tipi değişen tablo ve kolonlar.',
  roadmap_items: 'Yol haritası maddeleri. Sürümle gelenler her güncellemede yenilenir; kurum maddeleri buradan eklenir.',
  processing_activities: 'Kişisel veri işleme envanteri (VERBİS): amaç, hukuki sebep, kategoriler, ilgili kişiler, alıcılar, yurt dışı aktarım ve saklama süresi; kolon ve tablolara bağlıdır. Eksikler faaliyet ekranında listelenir.',
  retention_rules: 'Saklama süreleri ve imha yöntemleri. Tablolara ve işleme faaliyetlerine bağlanır; periyodik imhanın kapsamını belirler.',
  disposal_runs: 'Periyodik imha kayıtları (en çok 6 ayda bir). Tamamlanan kayıt değiştirilemez ve en az 3 yıl saklanır.',
  data_requests: 'Erişim, veri çıkarma, maskeleme, anonimleştirme ve takma adlandırma talepleri. Talep eden onaylayamaz; kişisel veri için amaç ve hukuki sebep (işleme faaliyeti) zorunludur.',
  subject_requests: 'İlgili kişi başvuruları (KVKK md. 11). Başvuru en geç 30 gün içinde sonuçlandırılır; ad yerine iç referans yazın (veri en aza indirme).',
  dpias: 'Veri koruma etki değerlendirmeleri (VKED). Özel nitelikli veri, profilleme, büyük ölçek, yeni teknoloji veya güvencesiz yurt dışı aktarımda gerekir. Hazırlayan onaylayamaz.',
  personal_data_categories: 'Kişisel veri kategorileri (VERBİS) ve keşif sözlüğü: kolon adında veya açıklamasında geçen anahtar kelimeler öneri üretir. Zayıf kelimeler yalnızca aynı tabloda güçlü bir eşleşme varsa sayılır.',
  data_subject_groups: 'İlgili kişi grupları (VERBİS): çalışan, müşteri, ziyaretçi...',
};
const RELATED = {
  engagements: [['sla_definitions', 'engagement_id'], ['responsibilities', 'engagement_id'], ['supplier_risks', 'engagement_id'],
    ['performance_events', 'engagement_id'], ['contracts', 'engagement_id']],
  sla_definitions: [['sla_measurements', 'sla_id']], performance_reviews: [['review_scores', 'review_id']],
  org_units: [['engagements', 'org_unit_id']], catalog_items: [['engagements', 'catalog_item_id']],
  import_batches: [['import_rows', 'batch_id']], supplier_types: [], contracts: [],
  standards: [['clauses', 'standard_id']],
  companies: [['supplier_risks', 'company_id'], ['bias', 'company_id'], ['bc_plans', 'company_id'], ['cmdb_cis', 'company_id'], ['risk_cycles', 'company_id']],
  risk_appetites: [], risk_criteria: [], cmdb_sync_runs: [], ci_exposures: [],
};
const EXTRA_ACTIONS = {}; // genel detay paneline kaynağa özgü düğmeler
const DETAILS = {}; // özel detay ekranları aşağıda tanımlanır
const SUPPLIER_TABS = []; // diğer dosyaların Tedarikçi 360'a eklediği sekmeler: {key, label, render(id), visible()}

DETAILS.bc_incidents = id => Router.go('crisis/' + id);
const EXTERNAL_NAV = new Set(['r/audits', 'r/findings', 'r/evidence', 'r/evidence_requests', 'r/certifications']);   // dış denetçi
function navVisible([key, , , need]) {
  if (need && !META.can(need)) return false;
  if (key === 'roles') return !!S.me && ['ADMIN', 'AUDITOR'].includes(S.me.role) && !S.me.external;
  if (key.startsWith('r/')) return !!META.def(key.slice(2));
  if (S.me && S.me.external && !EXTERNAL_NAV.has(key)) return false;
  const modules = {'my-surveys': 'surveys', compliance: 'grc', archive: 'grc', library: 'grc', obligations: 'grc', 'audit-plan': 'grc', crisis: 'continuity', risk: 'risks', bcm: 'continuity', cmdb: 'cmdb', schedule: 'dashboard',
    calendar: 'insights', 'my-work': 'insights', health: 'insights', map: 'insights', 'process-map': 'insights',
    datagov: 'datagov', glossary: 'datagov', catalog: 'datagov', stewardship: 'datagov', privacy: 'datagov', discovery: 'datagov', collectors: 'datagov', lineage: 'datagov', quality: 'datagov', regulation: 'datagov', ai: 'datagov'}[key];
  return !modules || S.meta.modules.includes(modules);
}
/** Menü bir kez kurulur; sonraki gezinmelerde yalnızca etkin öğe değişir (kaydırma konumu korunur). */
function navigation() {
  const nav = $('nav'); const current = Router.parse().parts.slice(0, 2).join('/') || 'home';
  if (!nav.dataset.built) {
    let closed = {}; try { closed = JSON.parse(localStorage.getItem('tdr.navClosed') || '{}'); } catch (e) { /* boş */ }
    for (const [title, items] of MENU) {
      const visible = items.filter(navVisible); if (!visible.length) continue;
      const group = h('div', {class: 'nav-group' + (closed[title] ? ' closed' : '')});
      const head = h('button', {type: 'button', class: 'nav-title', 'aria-expanded': closed[title] ? 'false' : 'true'}, h('span', {text: title}), icon('chev', 'chev'));
      head.addEventListener('click', () => {
        group.classList.toggle('closed'); head.setAttribute('aria-expanded', !group.classList.contains('closed'));
        closed[title] = group.classList.contains('closed'); try { localStorage.setItem('tdr.navClosed', JSON.stringify(closed)); } catch (e) { /* boş */ }
      });
      const list = h('div', {class: 'nav-items'});
      for (const [key, ico, label] of visible) {
        list.append(h('button', {type: 'button', class: 'nav-button', dataset: {nav: key}, onclick: () => { document.body.classList.remove('nav-open'); Router.go(key); }},
          h('span', {class: 'nav-icon'}, icon(ico)), h('span', {text: label || META.def(key.slice(2)).label}),
          key === 'my-surveys' ? h('span', {class: 'nav-count hidden', id: 'surveyCount', title: 'Yanıt bekleyen anket'}) : null,
          key === 'my-work' ? h('span', {class: 'nav-count hidden', id: 'workCount', title: 'Açık işleriniz'}) : null));
      }
      group.append(head, list); nav.append(group);
    }
    nav.dataset.built = '1';
  }
  let activeButton = null;
  nav.querySelectorAll('.nav-button').forEach(b => {
    const key = b.dataset.nav; const on = current === key || current.startsWith(key + '/') || (key === 'r/audits' && current.startsWith('audit/')) || (key === 'archive' && current.startsWith('archive')) || (key === 'r/data_sources' && current.startsWith('datasource/'))
      || (key === 'r/processing_activities' && current.startsWith('activity/')) || (key === 'r/disposal_runs' && current.startsWith('disposal/'));
    b.classList.toggle('active', on); if (on) { b.setAttribute('aria-current', 'page'); activeButton = b; } else b.removeAttribute('aria-current');
  });
  if (activeButton) {
    const group = activeButton.closest('.nav-group'); if (group && group.classList.contains('closed')) group.classList.remove('closed');
    const r = activeButton.getBoundingClientRect(); const box = nav.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom) activeButton.scrollIntoView({block: 'nearest'});
  }
  const sc = $('surveyCount'); if (sc) { sc.textContent = S.mySurveys; sc.classList.toggle('hidden', !S.mySurveys); }
  const wc = $('workCount'); if (wc) { wc.textContent = S.myWork || ''; wc.classList.toggle('hidden', !S.myWork); }
}

// ------------------------------------------------------------------ genel liste
function filterControl(res, name, value, onchange) {
  if (name === 'type_id') {
    const types = S.cache.supplier_types || [];
    return h('select', {class: 'compact', 'aria-label': 'Tedarikçi tipi', onchange: e => onchange(e.target.value)},
      h('option', {value: '', text: 'Tüm tipler'}), types.map(t => h('option', {value: t.id, text: t.name, selected: String(t.id) === value})));
  }
  const f = META.field(res, name); if (!f) return null;
  if (FLAGS.has(name)) return h('select', {class: 'compact', 'aria-label': f.label, onchange: e => onchange(e.target.value)},
    h('option', {value: '', text: f.label + ': tümü'}), h('option', {value: '1', text: 'Evet', selected: value === '1'}), h('option', {value: '0', text: 'Hayır', selected: value === '0'}));
  const options = f.options ? f.options.map(o => [o.value, o.label]) : f.ref ? (S.cache[f.ref] || []).map(r => [String(r.id), titleOf(r)]) : null;
  if (!options) return null;
  return h('select', {class: 'compact', 'aria-label': f.label, onchange: e => onchange(e.target.value)},
    h('option', {value: '', text: f.label + ': tümü'}), options.map(([v, l]) => h('option', {value: v, text: l, selected: String(v) === value})));
}
async function listView(res, {params} = {}) {
  const def = META.def(res);
  if (!def) return content(empty('Bu ekran kullanılamıyor', 'Modül kapalı veya görüntüleme yetkiniz yok.'));
  const state = S.filters[res] || (S.filters[res] = {q: '', values: {}, sort: null, page: 0});
  const preset = {}; for (const [k, v] of (params || new URLSearchParams()).entries()) preset[k] = v;
  const columns = (COLUMNS[res] || def.fields.filter(f => !f.name.endsWith('_json')).slice(0, 6).map(f => f.name)).filter(c => META.field(res, c));
  await Promise.all([loadRefs(res, [...columns, ...(FILTERS[res] || [])]), res === 'suppliers' ? list('supplier_types') : null]);
  const canCreate = def.can_write && (def.api.includes('create') || !!CREATE[res]);
  const createAction = canCreate ? btn('+ Yeni ' + singular(def.label), () => createRecord(res, preset)) : null;
  setPage(def.label, DESCRIPTIONS[res] || '', [
    createAction,
    META.can('manage') && def.api.includes('list') && res !== 'audit_log' ? btn('Excel', () => download(`export/${res}?format=xlsx`, res + '.xlsx'), 'secondary', {title: 'Listeyi Excel olarak indir'}) : null]);
  const search = h('input', {class: 'searchbar', type: 'search', id: 'tableSearch', placeholder: def.search.length ? 'Ara: ' + def.search.map(f => META.label(res, f).toLocaleLowerCase(TR)).join(', ') + '  ( / )' : 'Bu listede arama yok', value: state.q, disabled: !def.search.length, 'aria-label': 'Listede ara'});
  const tableHost = h('div'); const count = h('span', {class: 'muted small'});
  const filters = h('div', {class: 'filters'});
  const presetChips = Object.keys(preset).length ? h('div', {class: 'chips'}, Object.entries(preset).map(([k, v]) =>
    h('button', {type: 'button', class: 'chip on', title: 'Ön filtreyi kaldır', onclick: () => Router.go('r/' + res), text: presetLabel(res, k, v) + ' ✕'}))) : null;
  for (const name of FILTERS[res] || []) {
    const control = filterControl(res, name, state.values[name] || '', v => { state.values[name] = v; state.page = 0; load(); });
    if (control) filters.append(control);
  }
  content(h('div', {class: 'panel'}, h('div', {class: 'toolbar'}, h('div', {class: 'filters'}, search, filters), h('div', {class: 'filters'}, presetChips, count)), tableHost));
  let records = [];
  const load = async () => {
    const q = new URLSearchParams({limit: '1000', ...preset});
    for (const [k, v] of Object.entries(state.values)) if (v) q.set(k, v);
    if (state.q && def.search.length) q.set('q', state.q);
    tableHost.replaceChildren(h('div', {class: 'empty', text: 'Yükleniyor…'}));
    try { records = await api(`${res}?${q}`); await ensureRefs(res, records); } catch (e) { tableHost.replaceChildren(h('div', {class: 'notice bad', text: e.message})); return; }
    S.cache[res] = Object.keys(preset).length || Object.values(state.values).some(Boolean) || state.q ? S.cache[res] : records;
    draw();
  };
  const draw = () => {
    count.textContent = records.length === 1000 ? 'İlk 1000 kayıt (daraltmak için filtre kullanın)' : records.length + ' kayıt';
    if (!records.length) {
      const filtered = state.q || Object.values(state.values).some(Boolean) || Object.keys(preset).length;
      tableHost.replaceChildren(filtered ? empty('Eşleşen kayıt yok', 'Arama veya filtreyi değiştirin.') :
        empty('Henüz kayıt yok', canCreate ? 'İlk kaydı oluşturarak başlayın.' : '', canCreate ? btn('+ Yeni ' + singular(def.label), () => createRecord(res, preset)) : null));
      return;
    }
    let sorted = records;
    if (state.sort) {
      const [col, dir] = state.sort; const key = r => sortKey(res, col, r[col]);
      sorted = records.slice().sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * dir; });
    }
    const per = 50; const pages = Math.ceil(sorted.length / per); state.page = Math.min(state.page, pages - 1);
    const pageRows = sorted.slice(state.page * per, state.page * per + per);
    const head = h('tr', {}, columns.map(c => {
      const on = state.sort && state.sort[0] === c;
      return h('th', {class: 'sortable' + (isNumeric(res, c) ? ' num' : ''), scope: 'col', 'aria-sort': on ? (state.sort[1] > 0 ? 'ascending' : 'descending') : 'none',
        onclick: () => { state.sort = on && state.sort[1] > 0 ? [c, -1] : on ? null : [c, 1]; draw(); }},
      META.label(res, c), h('span', {class: 'arrow', text: on ? (state.sort[1] > 0 ? '▲' : '▼') : '↕'}));
    }));
    const body = h('tbody', {}, pageRows.map(r => {
      const tr = h('tr', {class: 'clickable', tabindex: '0', dataset: {row: r.id}, 'aria-label': titleOf(r) + ' kaydını aç'},
        columns.map((c, i) => h('td', {class: (i === 0 ? 'cell-primary' : '') + (isNumeric(res, c) ? ' num' : '')}, display(res, c, r[c]))));
      const open = () => { document.querySelectorAll('tr.selected').forEach(x => x.classList.remove('selected')); tr.classList.add('selected'); openRecord(res, r.id); };
      tr.addEventListener('click', e => { if (!getSelection().toString()) open(); });
      tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
      return tr;
    }));
    const pager = pages > 1 ? h('div', {class: 'pager'}, h('span', {text: `Sayfa ${state.page + 1} / ${pages}`}), h('div', {class: 'filters'},
      h('button', {type: 'button', class: 'btn secondary small', text: '‹ Önceki', disabled: state.page === 0, onclick: () => { state.page--; draw(); }}),
      h('button', {type: 'button', class: 'btn secondary small', text: 'Sonraki ›', disabled: state.page >= pages - 1, onclick: () => { state.page++; draw(); }}))) : null;
    tableHost.replaceChildren(h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, head), body)), pager || '');
  };
  search.addEventListener('input', debounce(() => { state.q = search.value.trim(); state.page = 0; load(); }, 300));
  await load();
}
function singular(label) {
  return {Tedarikçiler: 'Tedarikçi', Angajmanlar: 'Angajman', Birimler: 'Birim', Riskler: 'Risk', 'Risk Kaydı': 'Risk', 'Risk Kataloğu': 'Senaryo',
    Kontroller: 'Kontrol', Denetimler: 'Denetim', Bulgular: 'Bulgu', Kanıtlar: 'Kanıt', 'Düzeltici Faaliyetler': 'Faaliyet', Standartlar: 'Standart',
    Maddeler: 'Madde', Süreçler: 'Süreç', 'Kontrol Hedefleri': 'Hedef', Dokümanlar: 'Doküman', Şirketler: 'Şirket', 'Anahtar Risk Göstergeleri': 'Gösterge',
    'Risk Değerlendirme Dönemleri': 'Dönem', 'Risk İştahı': 'İştah beyanı', 'Risk Kriterleri': 'Kriter', 'Konfigürasyon Öğeleri': 'CI', 'İş Etki Analizleri': 'BİA',
    'İş Sürekliliği Planları': 'Plan', Tatbikatlar: 'Tatbikat', 'Risk İşleme Faaliyetleri': 'Faaliyet', 'KRİ Ölçümleri': 'Ölçüm'}[label] || 'kayıt';
}
function presetLabel(res, k, v) {
  const [name, op] = k.split('__'); const label = META.label(res, name);
  if (op === 'null') return label + (v === '1' ? ': boş' : ': dolu');
  const shown = META.field(res, name)?.options ? META.option(res, name, v) : META.field(res, name)?.kind === 'DATE' ? fmt.date(v) : v;
  return label + ({gte: ' ≥ ', lte: ' ≤ ', ne: ' ≠ '}[op] || ': ') + shown;
}
function isNumeric(res, c) { const f = META.field(res, c); return f && ['INTEGER', 'REAL', 'DECIMAL'].includes(f.kind) && !f.ref && !FLAGS.has(c) && !f.options; }
function sortKey(res, c, v) {
  if (v === null || v === undefined) return '';
  const f = META.field(res, c);
  if (f?.ref) return titleOf(refRecord(f.ref, v)).toLocaleLowerCase(TR);
  if (f?.options) return META.option(res, c, v).toLocaleLowerCase(TR);
  return typeof v === 'string' ? v.toLocaleLowerCase(TR) : v;
}
async function createRecord(res, defaults = {}) {
  const clean = {}; for (const [k, v] of Object.entries(defaults)) if (!k.includes('__')) { const f = META.field(res, k); clean[k] = f && (f.ref || f.kind === 'INTEGER') && /^\d+$/.test(v) ? Number(v) : v; }
  if (CREATE[res]) return CREATE[res](clean);
  return recordForm(res, null, {defaults: clean, onsaved: r => { refreshList(res); openRecord(res, r.id); }});
}
const CREATE = {};
function refreshList(res) { const {parts} = Router.parse(); if (parts[0] === 'r' && parts[1] === res) listView(res, {params: Router.parse().params}); }

// ------------------------------------------------------------------ genel detay
async function openRecord(res, id) {
  if (DETAILS[res]) return DETAILS[res](id);
  const def = META.def(res); await loadRefs(res);
  let record; try { record = await api(`${res}/${id}`); await ensureRefs(res, [record]); } catch (e) { toast(e.message, false); return; }
  const fields = def.fields.filter(f => (!f.name.endsWith('_json') || res === 'policies') && f.name !== 'body_hash');
  const body = h('div', {}, section('Bilgiler', kv(fields.map(f => [f.label, display(res, f.name, record[f.name])]))));
  for (const [child, key] of RELATED[res] || []) {
    if (!META.def(child)) continue;
    const items = await api(`${child}?${key}=${id}&limit=200`).catch(() => []);
    await loadRefs(child);
    const cols = (COLUMNS[child] || []).filter(c => c !== key).slice(0, 3);
    body.append(section(`${META.def(child).label} (${items.length})`,
      items.length ? h('ul', {class: 'mini'}, items.map(it => h('li', {class: 'link', tabindex: '0', onclick: () => openRecord(child, it.id)},
        h('strong', {text: titleOf(it) || '#' + it.id}), ' ', cols.map(c => [' · ', display(child, c, it[c])])))) : h('div', {class: 'muted small', text: 'Kayıt yok'}),
      META.def(child).can_write && META.def(child).api.includes('create') ? btn('+ Ekle', () => createRecord(child, {[key]: id}), 'ghost small') : null));
  }
  if (res === 'engagements' && def.can_write) body.append(section('Kullanan diğer birimler', h('div', {class: 'muted small', text: 'Angajmandan yararlanan diğer birimler raporlarda görünür.'}),
    btn('Düzenle', () => editEngagementUsers(record), 'ghost small')));
  if (res === 'audit_log' && record.changes_json) body.append(section('Değişiklik', h('pre', {class: 'small', text: JSON.stringify(JSON.parse(record.changes_json), null, 2)})));
  if (res === 'import_batches' && record.summary_json) body.append(section('Özet', importSummary(JSON.parse(record.summary_json))));
  const canEdit = def.can_write && def.api.includes('update');
  Drawer.open(titleOf(record) || def.label + ' #' + id, body, [...(EXTRA_ACTIONS[res] ? EXTRA_ACTIONS[res](record) : []),
    canEdit ? btn('Düzenle', () => recordForm(res, record, {onsaved: () => { refreshList(res); openRecord(res, id); }})) : null], def.label);
}
async function editEngagementUsers(engagement) {
  const units = await list('org_units');
  const boxes = h('div', {class: 'choices'}, units.filter(u => u.id !== engagement.org_unit_id).map(u => h('label', {}, h('input', {type: 'checkbox', value: u.id}), titleOf(u))));
  Modal.open('Kullanan birimler: ' + engagement.code, h('div', {}, h('p', {class: 'intro', text: 'Satın alan birim dışında bu angajmandan yararlanan birimleri seçin. Kayıt mevcut listenin yerine geçer.'}), boxes), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => {
      const ids = [...boxes.querySelectorAll('input:checked')].map(i => Number(i.value));
      await api(`engagements/${engagement.id}/users`, {method: 'POST', body: {org_unit_ids: ids}}); Modal.close(); toast('Kullanan birimler kaydedildi');
    })]);
}

// ------------------------------------------------------------------ genel bakış
DETAILS.suppliers = async function supplierDetail(id) {
  await Promise.all([list('org_units'), list('catalog_items'), list('supplier_types')]);
  let ctx; try { ctx = await api(`suppliers/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const has = m => S.meta.modules.includes(m);
  const [card, risks, surveys] = await Promise.all([
    has('performance') ? api(`suppliers/${id}/scorecard`).catch(() => null) : null,
    has('risks') ? api(`supplier_risks?supplier_id=${id}&limit=200`).catch(() => []) : [],
    has('surveys') ? api(`suppliers/${id}/surveys`).catch(() => []) : []]);
  const def = META.def('suppliers'); const can = def.can_write;
  const warnings = [];
  if (!ctx.owner && ctx.status === 'active') warnings.push('İlişki sahibi atanmamış.');
  if (ctx.tier === 'critical' && has('risks') && !risks.length) warnings.push('Kritik tedarikçi için kayıtlı risk yok.');
  const ending = ctx.contracts.filter(k => k.status === 'active' && k.end_date && k.end_date <= today(90));
  if (ending.length) warnings.push(`${ending.length} sözleşme 90 gün içinde bitiyor.`);
  const summary = () => h('div', {},
    h('div', {class: 'chips'}, display('suppliers', 'tier', ctx.tier), display('suppliers', 'status', ctx.status), ctx.segment ? display('suppliers', 'segment', ctx.segment) : null,
      ctx.types.map(t => h('span', {class: 'chip', text: t.name}))), h('br'),
    warnings.length ? h('div', {class: 'notice warn'}, warnings.map(w => h('div', {text: '• ' + w}))) : null,
    section('Kimlik', kv([['Kod', ctx.code], ['VKN', ctx.tax_id], ['Ülke / şehir', [ctx.country, ctx.city].filter(Boolean).join(' / ')], ['Web', ctx.website],
      ['İlişki sahibi', ctx.owner], ['Açıklama', ctx.description]])),
    section('Kaynak sistem kimlikleri', ctx.source_refs.length ? h('ul', {class: 'mini'}, ctx.source_refs.map(r => h('li', {}, h('strong', {text: META.option('source_refs', 'source_system', r.source_system)}), ' · ', r.external_id, r.external_name ? ' · ' + r.external_name : '')))
      : h('div', {class: 'muted small', text: 'Kaynak sistem eşlemesi yok'})),
    card ? section('Son 12 ay', h('div', {class: 'grid two'},
      gauge(card.sla.rate, 'SLA başarısı', {suffix: '%', good: 95, mid: 85, sub: `${card.sla.met}/${card.sla.total} ölçüm`}),
      gauge(card.review.score === null ? null : (card.review.score - 1) * 25, 'Değerlendirme puanı', {sub: card.review.score === null ? 'Değerlendirme yok' : `${fmt.num(card.review.score, 2)} / 5 · ${card.review.reviews} değerlendirme`}))) : null);
  const engagementsTab = () => h('div', {}, ctx.engagements.length ? h('ul', {class: 'mini'}, ctx.engagements.map(e => h('li', {class: 'link', tabindex: '0', onclick: () => openRecord('engagements', e.id)},
    h('strong', {text: e.code + ' · ' + e.item_name}), h('span', {class: 'cell-sub', text: `${e.unit_name} · ${META.option('engagements', 'beneficiary', e.beneficiary)}${e.customer_name ? ' (' + e.customer_name + ')' : ''} · ${e.business_owner || 'iş sahibi yok'}`}),
    h('div', {class: 'chips'}, display('engagements', 'criticality', e.criticality), display('engagements', 'status', e.status)))))
    : empty('Angajman yok', 'Hangi birimin bu tedarikçiden ne aldığını kaydedin.'),
  META.def('engagements')?.can_write ? h('p', {}, btn('+ Angajman ekle', () => createRecord('engagements', {supplier_id: id}), 'secondary small')) : null);
  const riskTab = () => h('div', {}, risks.length ? h('ul', {class: 'mini'}, risks.map(r => h('li', {class: 'link', tabindex: '0', onclick: () => openRecord('supplier_risks', r.id)},
    h('strong', {text: r.code + ' · ' + r.title}), h('div', {class: 'chips'}, display('supplier_risks', 'category', r.category), display('supplier_risks', 'status', r.status),
      r.review_date ? h('span', {class: 'chip', text: 'Gözden geçirme ' + fmt.date(r.review_date)}) : null))))
    : empty('Risk kaydı yok', ''), META.def('supplier_risks')?.can_write ? h('p', {}, btn('+ Risk aç', () => createRecord('supplier_risks', {supplier_id: id}), 'secondary small')) : null);
  const surveyTab = () => surveys.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kampanya', 'Amaç', 'Durum', 'Yanıt', 'Puan'].map((t, i) => h('th', {class: i > 2 ? 'num' : '', text: t})))),
    h('tbody', {}, surveys.map(x => h('tr', {class: 'clickable', onclick: () => Router.go('surveys/' + x.campaign_id)}, h('td', {class: 'cell-primary', text: x.name}),
      h('td', {}, META.option('survey_templates', 'purpose', x.purpose)), h('td', {}, display('survey_campaigns', 'status', x.status)),
      h('td', {class: 'num', text: x.responses}), h('td', {class: 'num'}, x.score === null ? h('span', {class: 'muted', text: x.anonymous && x.responses ? 'gizli' : '—'}) : fmt.num(x.score))))))) :
    empty('Anket yok', 'Bu tedarikçi henüz bir ankette değerlendirilmedi.');
  const contractTab = () => h('div', {}, ctx.contracts.length ? h('ul', {class: 'mini'}, ctx.contracts.map(k => h('li', {class: 'link', onclick: () => openRecord('contracts', k.id)},
    h('strong', {text: k.code + ' · ' + k.title}), h('span', {class: 'cell-sub', text: `${fmt.date(k.start_date)} – ${fmt.date(k.end_date)}${k.notice_days ? ' · ihbar ' + k.notice_days + ' gün' : ''}`}), display('contracts', 'status', k.status))))
    : empty('Sözleşme yok', ''), META.def('contracts')?.can_write ? h('p', {}, btn('+ Sözleşme ekle', () => createRecord('contracts', {supplier_id: id}), 'secondary small')) : null);
  const peopleTab = () => h('div', {}, section('İlgili kişiler', ctx.contacts.length ? h('ul', {class: 'mini'}, ctx.contacts.map(p => h('li', {class: 'link', onclick: () => openRecord('supplier_contacts', p.id)},
    h('strong', {text: p.name}), p.is_primary ? ' ' : '', p.is_primary ? pill('Birincil', 'good') : '', h('span', {class: 'cell-sub', text: [p.role, p.email, p.phone].filter(Boolean).join(' · ')}))))
    : h('div', {class: 'muted small', text: 'Kişi yok'}), META.def('supplier_contacts')?.can_write ? btn('+ Kişi', () => createRecord('supplier_contacts', {supplier_id: id}), 'ghost small') : null),
  section('Sorumluluklar', ctx.responsibilities.length ? h('ul', {class: 'mini'}, ctx.responsibilities.map(r => h('li', {class: 'link', onclick: () => openRecord('responsibilities', r.id)},
    h('strong', {text: r.person}), ' · ', META.option('responsibilities', 'role', r.role), ' · ', r.raci))) : h('div', {class: 'muted small', text: 'Sorumluluk kaydı yok'}),
  META.def('responsibilities')?.can_write ? btn('+ Sorumluluk', () => createRecord('responsibilities', {supplier_id: id}), 'ghost small') : null));
  const items = [{key: 'summary', label: 'Özet', render: summary}, {key: 'engagements', label: 'Angajmanlar', count: ctx.engagements.length, render: engagementsTab}];
  if (has('risks')) items.push({key: 'risks', label: 'Riskler', count: risks.length, render: riskTab});
  if (has('surveys')) items.push({key: 'surveys', label: 'Anketler', count: surveys.length, render: surveyTab});
  items.push({key: 'contracts', label: 'Sözleşmeler', count: ctx.contracts.length, render: contractTab}, {key: 'people', label: 'Kişiler', count: ctx.contacts.length + ctx.responsibilities.length, render: peopleTab});
  for (const t of SUPPLIER_TABS) if (!t.visible || t.visible()) items.push({key: t.key, label: t.label, render: () => t.render(id)});
  Drawer.open(ctx.name, tabs(items), [
    can ? btn('Tipler', () => editTypes(ctx), 'secondary') : null,
    can ? btn('Düzenle', () => recordForm('suppliers', ctx, {onsaved: () => { refreshList('suppliers'); DETAILS.suppliers(id); }})) : null], 'Tedarikçi 360 · ' + ctx.code);
};
async function editTypes(supplier) {
  const types = await list('supplier_types'); const chosen = new Set(supplier.types.map(t => t.id));
  const boxes = h('div', {class: 'choices'}, types.map(t => h('label', {}, h('input', {type: 'checkbox', value: t.id, checked: chosen.has(t.id)}), t.name)));
  Modal.open('Tedarikçi tipleri: ' + supplier.name, boxes, [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => {
    await api(`suppliers/${supplier.id}/types`, {method: 'POST', body: {type_ids: [...boxes.querySelectorAll('input:checked')].map(i => Number(i.value))}});
    Modal.close(); toast('Tipler kaydedildi'); DETAILS.suppliers(supplier.id);
  })]);
}

// ------------------------------------------------------------------ risk
const WEIGHT = {low: 0.2, medium: 0.4, high: 0.6};
const RISK_FIELDS = ['title', 'company_id', 'risk_type', 'category', 'process_id', 'org_unit_id', 'supplier_id', 'engagement_id', 'entity_name', 'impact_area',
  'cause', 'risk_event', 'consequence', 'likelihood', 'impact', 'target_likelihood', 'target_impact', 'appetite', 'owner', 'consulted', 'response_strategy',
  'treatment', 'review_date', 'catalog_id', 'description'];
CREATE.supplier_risks = defaults => recordForm('supplier_risks', null, {only: RISK_FIELDS, defaults: {likelihood: 3, impact: 3, appetite: 9, owner: S.me.username, ...defaults},
  onsaved: r => { refreshList('supplier_risks'); openRecord('supplier_risks', r.id); },
  extra: h('div', {class: 'notice wide', text: 'Risk ifadesi KS GRC ile aynıdır: "… nedeniyle (neden), … olabilir (olay), bu da … sonucunu doğurur (etki)". Tedarikçi riski değilse etkilenen varlık / hizmeti yazın. Kabul ve kapanış için önce değerlendirme yapılır.'})});
function assessRisk(risk, done) {
  const rows = h('div'); const preview = h('div', {class: 'score-preview'}); const rationale = h('textarea', {id: 'assessRationale', placeholder: 'Değerlendirmenin dayanağı: gözlem, kanıt, görüşme…'});
  const missing = ['owner', 'cause', 'risk_event', 'consequence', 'review_date'].filter(k => !risk[k]);
  const addRow = (m = {}) => {
    const row = h('div', {class: 'mitigation-row'},
      h('input', {placeholder: 'Önlem (ör. yedek tedarikçi sözleşmesi)', value: m.title || '', 'aria-label': 'Önlem'}),
      h('select', {'aria-label': 'Katkı ağırlığı'}, [['low', 'Düşük katkı (%20)'], ['medium', 'Orta katkı (%40)'], ['high', 'Yüksek katkı (%60)']].map(([v, l]) => h('option', {value: v, text: l, selected: v === (m.weight || 'medium')}))),
      h('select', {'aria-label': 'Etkinlik'}, h('option', {value: 'effective', text: 'Etkili'}), h('option', {value: 'partial', text: 'Kısmen etkili (yarısı)'})),
      h('button', {type: 'button', class: 'btn ghost', 'aria-label': 'Önlemi kaldır', text: '✕', onclick: () => { row.remove(); update(); }}));
    row.addEventListener('input', update); rows.append(row); update();
  };
  const read = () => [...rows.children].map(row => { const [t, w, e] = row.querySelectorAll('input,select'); return {title: t.value.trim(), weight: w.value, effectiveness: e.value}; });
  function update() {
    const total = Math.min(1, read().reduce((a, m) => a + WEIGHT[m.weight] * (m.effectiveness === 'partial' ? 0.5 : 1), 0));
    const inherent = risk.likelihood * risk.impact; const residual = inherent * (1 - total);
    preview.replaceChildren(h('span', {}, 'İçsel ', h('b', {text: inherent})), h('span', {}, 'Azaltım ', h('b', {text: '%' + Math.round(total * 100)})),
      h('span', {}, 'Artık ', h('b', {text: fmt.num(residual, 2)})), residual > risk.appetite ? pill('İştah eşiğinin (' + risk.appetite + ') üstünde', 'bad') : pill('İştah içinde', 'good'));
  }
  Modal.open('Riski değerlendir: ' + risk.code, h('div', {},
    missing.length ? h('div', {class: 'notice bad', text: 'Önce riski düzenleyip şu alanları doldurun: ' + missing.map(k => META.label('supplier_risks', k)).join(', ')}) : null,
    h('p', {class: 'intro', text: `Olasılık ${risk.likelihood} × etki ${risk.impact}. Riski azaltan önlemleri ekleyin; artık risk KS GRC formülüyle hesaplanır. Değerlendirme kaydı sonradan değiştirilemez.`}),
    h('div', {class: 'field'}, 'Azaltıcı önlemler', h('div', {class: 'control'}, rows), btn('+ Önlem ekle', () => addRow(), 'ghost small')), preview, h('br'),
    h('label', {class: 'field', for: 'assessRationale'}, h('span', {}, 'Gerekçe', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, rationale))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Değerlendirmeyi kaydet', async () => {
      if (!rationale.value.trim()) { rationale.focus(); throw new Error('Gerekçe gerekli'); }
      const result = await api(`supplier_risks/${risk.id}/assessments`, {method: 'POST', body: {rationale: rationale.value.trim(), mitigations: read()}});
      Modal.close(); toast(`Değerlendirildi: artık risk ${fmt.num(result.residual)}${result.above_appetite ? ' (iştah üstünde)' : ''}`); done();
    }, '', {disabled: missing.length > 0})], true);
  update();
}
function decision(risk, target, done) {
  const last = risk.assessments[0]; const above = target === 'accepted' && last && last.residual > last.appetite;
  const rationale = h('textarea', {id: 'decisionRationale'}); const exception = h('textarea', {id: 'exceptionRationale'});
  const review = h('input', {type: 'date', id: 'reviewDate', value: risk.review_date && risk.review_date >= today() ? risk.review_date : today(180), min: today()});
  const titles = {accepted: 'Riski kabul et', closed: 'Riski kapat', open: 'Riski yeniden aç'};
  const notes = {accepted: 'Kabul kararı en son değerlendirmeye dayanır ve değiştirilemez bir karar kaydı oluşturur.',
    closed: 'Açık işleme faaliyeti olan risk kapatılamaz.', open: 'Yeniden açılan risk için yeni değerlendirme gerekir.'};
  Modal.open(titles[target] + ': ' + risk.code, h('div', {},
    h('p', {class: 'intro', text: notes[target]}),
    above ? h('div', {class: 'notice bad', text: `Artık risk (${fmt.num(last.residual)}) iştah eşiğinin (${last.appetite}) üstünde. Bu kabulü değerlendirmeyi yapandan (${last.assessor}) farklı bir Yönetici ayrı istisna gerekçesiyle onaylar.`}) : null,
    target === 'accepted' ? h('label', {class: 'field', for: 'reviewDate'}, 'Gözden geçirme tarihi', h('div', {class: 'control'}, review)) : null,
    h('label', {class: 'field', for: 'decisionRationale'}, h('span', {}, 'Karar gerekçesi', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, rationale)),
    above ? h('label', {class: 'field', for: 'exceptionRationale'}, h('span', {}, 'İştah istisnası gerekçesi', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, exception)) : null), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn(titles[target], async () => {
      if (!rationale.value.trim()) { rationale.focus(); throw new Error('Karar gerekçesi gerekli'); }
      const body = {status: target, decision_rationale: rationale.value.trim()};
      if (target !== 'open') body.assessment_id = last.id;
      if (target === 'accepted') { body.response_strategy = 'accept'; body.review_date = review.value; }
      if (above) body.exception_rationale = exception.value.trim();
      await api(`supplier_risks/${risk.id}`, {method: 'PATCH', body}); Modal.close(); toast('Karar kaydedildi'); done();
    }, target === 'open' ? 'secondary' : '')]);
}

// ------------------------------------------------------------------ anket: ortak soru çizimi (yanıt formu ve önizleme)
const KIND_INFO = {
  scale_1_5: ['1–5 ölçek', 'Memnuniyet, kalite gibi derecelendirmeler'], nps_0_10: ['Tavsiye (0–10)', 'NPS hesaplanır'],
  yes_no: ['Evet / Hayır', 'Olumsuz soruda "Evet" düşük puan alabilir'], single_choice: ['Tek seçim', 'Seçenek başına puan verilebilir'],
  multi_choice: ['Çoklu seçim', 'Seçilenlerin puan ortalaması'], text: ['Metin', 'Puanlanmaz; yorum ve açıklama'],
  number: ['Sayı', 'Puanlanmaz; ortalama, en düşük, en yüksek'], date: ['Tarih', 'Puanlanmaz'],
};
function isVisible(q, valuesByCode) {
  const rule = q.show_if; if (!rule) return true;
  const v = valuesByCode[rule.question]; if (v === undefined || v === null || v === '') return false;
  if ('equals' in rule) return v === rule.equals || (Array.isArray(v) && v.includes(rule.equals));
  if ('in' in rule) return rule.in.includes(v) || (Array.isArray(v) && v.some(x => rule.in.includes(x)));
  if (typeof v !== 'number') return false;
  return (!('min' in rule) || v >= rule.min) && (!('max' in rule) || v <= rule.max);
}
function questionControl(q, value, onchange, readonly) {
  const set = v => { if (!readonly) onchange(v); };
  if (q.kind === 'scale_1_5' || q.kind === 'nps_0_10') {
    const [low, high] = q.kind === 'scale_1_5' ? [1, 5] : [0, 10];
    const group = h('div', {class: 'scale', role: 'radiogroup', 'aria-label': q.text});
    for (let v = low; v <= high; v++) group.append(h('button', {type: 'button', role: 'radio', 'aria-checked': value === v, class: value === v ? 'on' : '', text: v, disabled: readonly,
      onclick: () => set(value === v ? null : v)}));
    return h('div', {}, group, h('div', {class: 'scale-ends'}, h('span', {text: q.kind === 'scale_1_5' ? '1 · Çok kötü' : '0 · Hiç tavsiye etmem'}), h('span', {text: q.kind === 'scale_1_5' ? '5 · Çok iyi' : '10 · Kesinlikle ederim'})));
  }
  if (['yes_no', 'single_choice', 'multi_choice'].includes(q.kind)) {
    const multi = q.kind === 'multi_choice'; const chosen = multi ? new Set(value || []) : null;
    return h('div', {class: 'choices', role: multi ? 'group' : 'radiogroup', 'aria-label': q.text}, (q.options || []).map(o => {
      const on = multi ? chosen.has(o.value) : value === o.value;
      const input = h('input', {type: multi ? 'checkbox' : 'radio', name: 'q' + q.id, checked: on, disabled: readonly});
      input.addEventListener('change', () => {
        if (multi) { if (input.checked) chosen.add(o.value); else chosen.delete(o.value); set(chosen.size ? [...chosen] : null); } else set(o.value);
      });
      return h('label', {class: on ? 'on' : ''}, input, o.label);
    }));
  }
  if (q.kind === 'text') { const t = h('textarea', {value: value || '', disabled: readonly, 'aria-label': q.text, maxlength: '5000'}); t.addEventListener('input', debounce(() => set(t.value.trim() || null), 250)); return t; }
  if (q.kind === 'number') { const i = h('input', {type: 'number', step: 'any', value: value ?? '', disabled: readonly, 'aria-label': q.text, class: 'compact'}); i.addEventListener('input', debounce(() => set(i.value === '' ? null : Number(i.value)), 250)); return i; }
  const d = h('input', {type: 'date', value: value || '', disabled: readonly, 'aria-label': q.text, class: 'compact'}); d.addEventListener('change', () => set(d.value || null)); return d;
}
/** Anket formu. mode: 'answer' (otomatik kayıt), 'preview' (kaydetmez), 'view' (gönderilmiş, salt okunur). */
function surveyForm(form, {mode = 'answer', onSave, onSubmit} = {}) {
  const values = {}; // soru kimliği -> değer
  for (const [k, v] of Object.entries(form.answers || {})) values[Number(k)] = v;
  const byCode = () => Object.fromEntries(form.questions.filter(q => values[q.id] !== undefined).map(q => [q.code, values[q.id]]));
  const dirty = new Set(); const readonly = mode === 'view';
  const status = h('span', {class: 'save-state', text: mode === 'answer' ? 'Yanıtlarınız otomatik kaydedilir' : mode === 'preview' ? 'Önizleme: yanıtlar kaydedilmez' : 'Gönderildi'});
  const barHost = h('div'); const label = h('span');
  const progress = h('div', {class: 'progress'}, h('div', {class: 'label'}, label, status), barHost);
  const host = h('div');
  const sections = [...form.sections, {id: null, title: form.sections.length ? 'Diğer sorular' : ''}];
  const save = debounce(async () => {
    if (mode !== 'answer' || !dirty.size) return;
    const answers = [...dirty].map(id => ({question_id: id, value: values[id] ?? null})); dirty.clear();
    status.textContent = 'Kaydediliyor…'; status.className = 'save-state saving';
    try { await onSave(answers); status.textContent = 'Kaydedildi ' + new Date().toLocaleTimeString(TR, {hour: '2-digit', minute: '2-digit'}); status.className = 'save-state saved'; }
    catch (e) { status.textContent = 'Kaydedilemedi: ' + e.message; status.className = 'save-state'; for (const a of answers) dirty.add(a.question_id); }
  }, 700);
  const draw = () => {
    const codes = byCode(); const shown = form.questions.filter(q => isVisible(q, codes));
    const required = shown.filter(q => q.required); const done = required.filter(q => values[q.id] !== undefined && values[q.id] !== null);
    label.textContent = required.length ? `${done.length} / ${required.length} zorunlu soru yanıtlandı` : `${shown.filter(q => values[q.id] != null).length} soru yanıtlandı`;
    barHost.replaceChildren(progressBar(required.length ? 100 * done.length / required.length : 100));
    host.replaceChildren(...sections.map(sec => {
      const qs = shown.filter(q => (q.section_id ?? null) === sec.id); if (!qs.length) return '';
      return h('div', {}, sec.title ? h('h3', {class: 'section-title', text: sec.title}) : null, sec.description ? h('p', {class: 'intro', text: sec.description}) : null,
        qs.map(q => h('div', {class: 'question', id: 'question-' + q.id, dataset: {question: q.id}},
          h('h4', {}, h('span', {class: 'code', text: q.code}), q.text, q.required ? h('span', {class: 'req', text: ' *', 'aria-label': 'zorunlu'}) : null),
          q.help ? h('p', {class: 'help', text: q.help}) : null,
          questionControl(q, values[q.id], v => { if (v === null) delete values[q.id]; else values[q.id] = v; dirty.add(q.id); draw(); save(); }, readonly))));
    }));
  };
  const submit = async () => {
    const codes = byCode(); const missing = form.questions.filter(q => isVisible(q, codes) && q.required && (values[q.id] === undefined || values[q.id] === null));
    document.querySelectorAll('.question.missing').forEach(x => x.classList.remove('missing'));
    if (missing.length) {
      missing.forEach(q => $('question-' + q.id)?.classList.add('missing'));
      $('question-' + missing[0].id)?.scrollIntoView({behavior: 'smooth', block: 'center'});
      throw new Error(`${missing.length} zorunlu soru yanıtlanmadı`);
    }
    const answers = form.questions.map(q => ({question_id: q.id, value: values[q.id] ?? null}));
    await onSubmit(answers);
  };
  draw();
  return {node: h('div', {}, progress, host), submit};
}

// ------------------------------------------------------------------ anket: şablon kurucu
DETAILS.survey_templates = id => Router.go('templates/' + id);
DETAILS.survey_campaigns = id => Router.go('surveys/' + id);
CREATE.survey_templates = defaults => recordForm('survey_templates', null, {defaults: {purpose: 'satisfaction', ...defaults}, only: ['code', 'name', 'purpose', 'description', 'intro', 'outro'],
  title: 'Yeni anket şablonu', onsaved: r => { Drawer.close(); Router.go('templates/' + r.id); }});
async function templateBuilder(id) {
  const t = await api(`survey_templates/${id}/structure?all=1`);
  const draft = t.status === 'draft'; const can = META.def('survey_templates').can_write;
  setPage(t.name, `${t.code} · sürüm ${t.version} · ${META.option('survey_templates', 'purpose', t.purpose)}`, [
    btn('Önizle', () => previewTemplate(t), 'secondary'),
    can && draft ? btn('Ayarlar', () => recordForm('survey_templates', t, {only: ['name', 'purpose', 'description', 'intro', 'outro'], onsaved: () => { Drawer.close(); templateBuilder(id); }}), 'secondary') : null,
    can && !draft ? btn('Yeni sürüm oluştur', async () => { const copy = await api(`survey_templates/${id}/copy`, {method: 'POST', body: {}}); toast(`Sürüm ${copy.version} taslak olarak açıldı`); Router.go('templates/' + copy.id); }, 'secondary') : null,
    can && draft ? btn('Yayımla', async () => {
      if (!await confirmDialog('Şablonu yayımla', 'Yayımlanan şablon dondurulur; soru eklenemez ve değiştirilemez. Değişiklik için yeni sürüm oluşturulur.', 'Yayımla')) return;
      await api(`survey_templates/${id}/publish`, {method: 'POST', body: {}}); toast('Şablon yayımlandı'); templateBuilder(id);
    }, 'secondary') : null,
    can && t.status !== 'retired' ? btn('Kampanya başlat', () => createRecord('survey_campaigns', {template_id: id})) : null],
  [['Anket şablonları', 'r/survey_templates']]);
  const active = t.questions.filter(q => !q.disabled);
  const header = h('div', {class: 'panel'}, h('div', {class: 'chips'}, display('survey_templates', 'status', t.status), display('survey_templates', 'purpose', t.purpose),
    pill(active.length + ' soru', 'neutral'), t.parent_id ? h('a', {class: 'chip', href: '#/templates/' + t.parent_id, text: 'Önceki sürüm'}) : null),
  t.description ? h('p', {class: 'intro', text: t.description}) : null,
  !draft ? h('div', {class: 'notice', text: t.status === 'retired' ? 'Bu şablon kullanımdan kaldırıldı.' : 'Bu şablon yayımlandı ve donduruldu. Değiştirmek için "Yeni sürüm oluştur".'}) :
    h('div', {class: 'notice', text: 'Soruları ekleyin, sıralayın, koşul ve risk eşiği verin. "Önizle" ile yanıtlayan gibi görün. Kampanya açıldığında şablon kendiliğinden yayımlanır.'}));
  const move = async (q, dir) => {
    const order = active.slice(); const i = order.findIndex(x => x.id === q.id); const j = i + dir; if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    if (order[i].section_id !== order[j].section_id) { const sec = order[j].section_id; order[j] = {...order[j], section_id: order[i].section_id}; order[i] = {...order[i], section_id: sec}; }
    await api(`survey_templates/${id}/reorder`, {method: 'POST', body: {questions: order.map(x => ({id: x.id, section_id: x.section_id}))}}); templateBuilder(id);
  };
  const card = q => h('div', {class: 'builder-q' + (q.disabled ? ' muted' : ''), dataset: {question: q.id}},
    h('div', {class: 'body'}, h('div', {}, h('span', {class: 'code', text: q.code + ' '}), h('strong', {text: q.text})),
      q.help ? h('div', {class: 'small muted', text: q.help}) : null,
      h('div', {class: 'meta'}, pill(KIND_INFO[q.kind][0], 'neutral'), q.required ? pill('Zorunlu', 'warn') : pill('İsteğe bağlı', 'neutral'),
        ['text', 'number', 'date'].includes(q.kind) ? null : pill('Ağırlık ' + fmt.num(q.weight, 1), 'neutral'),
        q.show_if ? pill('Koşul: ' + ruleText(q.show_if, t.questions), 'purple') : null,
        q.risk_category ? pill(`Risk: ${META.option('survey_questions', 'risk_category', q.risk_category)} < ${q.risk_threshold ?? '—'}`, 'bad') : null,
        q.disabled ? pill('Kaldırıldı', 'bad') : null,
        (q.options || []).length && q.kind !== 'yes_no' ? h('span', {class: 'small muted', text: q.options.map(o => o.label + (o.score !== undefined && o.score !== null ? ` (${o.score})` : '')).join(' · ')}) : null)),
    draft && can ? h('div', {class: 'ops'}, q.disabled ? btn('Geri al', async () => { await api(`survey_questions/${q.id}`, {method: 'PATCH', body: {disabled: 0}}); templateBuilder(id); }, 'ghost small') : [
      h('button', {type: 'button', class: 'btn ghost small', 'aria-label': 'Yukarı taşı', text: '↑', onclick: () => guard(null, () => move(q, -1))}),
      h('button', {type: 'button', class: 'btn ghost small', 'aria-label': 'Aşağı taşı', text: '↓', onclick: () => guard(null, () => move(q, 1))}),
      btn('Düzenle', () => questionEditor(t, q), 'ghost small'),
      btn('Kaldır', async () => { await api(`survey_questions/${q.id}`, {method: 'PATCH', body: {disabled: 1}}); toast('Soru kaldırıldı; geri alınabilir'); templateBuilder(id); }, 'ghost small')]) : null);
  const groups = [...t.sections.map(sec => [sec, t.questions.filter(q => q.section_id === sec.id)]), [null, t.questions.filter(q => !q.section_id)]];
  const panels = groups.filter(([sec, qs]) => sec || qs.length).map(([sec, qs]) => h('div', {class: 'panel'},
    h('div', {class: 'panel-title'}, h('h3', {text: sec ? sec.title : 'Bölümsüz sorular'}),
      draft && can ? h('div', {class: 'filters'}, sec ? btn('Bölümü düzenle', () => recordForm('survey_sections', sec, {only: ['title', 'description', 'position'], onsaved: () => { Drawer.close(); templateBuilder(id); }}), 'ghost small') : null,
        btn('+ Soru', () => questionEditor(t, null, sec?.id), 'secondary small')) : null),
    sec?.description ? h('p', {class: 'intro', text: sec.description}) : null,
    qs.length ? qs.map(card) : h('div', {class: 'muted small', text: 'Bu bölümde soru yok.'})));
  content(header, panels, draft && can ? h('div', {class: 'filters'}, btn('+ Bölüm ekle', () => recordForm('survey_sections', null, {defaults: {template_id: id, position: t.sections.length + 1}, only: ['title', 'description', 'position'],
    title: 'Yeni bölüm', onsaved: () => { Drawer.close(); templateBuilder(id); }}), 'secondary'),
  btn('+ Soru ekle', () => questionEditor(t, null, null))) : '', !t.questions.length ? empty('Henüz soru yok', 'İlk soruyu ekleyerek başlayın.') : '');
}
function ruleText(rule, questions) {
  const source = questions.find(q => q.code === rule.question); const label = v => (source?.options || []).find(o => o.value === v)?.label ?? v;
  if ('equals' in rule) return `${rule.question} = ${label(rule.equals)}`;
  if ('in' in rule) return `${rule.question} ∈ {${rule.in.map(label).join(', ')}}`;
  return `${rule.question} ${'min' in rule ? '≥ ' + rule.min : ''}${'min' in rule && 'max' in rule ? ' ve ' : ''}${'max' in rule ? '≤ ' + rule.max : ''}`;
}
function previewTemplate(t) {
  const form = {...t, questions: t.questions.filter(q => !q.disabled), answers: {}};
  const view = surveyForm(form, {mode: 'preview'});
  Modal.open('Önizleme: ' + t.name, h('div', {class: 'survey-shell'}, t.intro ? h('div', {class: 'survey-head'}, h('p', {text: t.intro})) : null, view.node), [btn('Kapat', () => Modal.close(), 'secondary')], true);
}
function questionEditor(t, q, sectionId) {
  const isNew = !q; q = q || {kind: 'scale_1_5', required: 1, weight: 1, section_id: sectionId ?? null, options: null, show_if: null};
  const earlier = t.questions.filter(x => !x.disabled && x.id !== q.id && (isNew || x.position <= q.position || x.id < q.id));
  const text = h('textarea', {id: 'qText', value: q.text || '', placeholder: 'Soru metni'});
  const help = h('input', {id: 'qHelp', value: q.help || '', placeholder: 'İsteğe bağlı açıklama'});
  const kind = h('select', {id: 'qKind'}, Object.entries(KIND_INFO).map(([k, [l, d]]) => h('option', {value: k, text: `${l} — ${d}`, selected: k === q.kind})));
  const required = h('input', {type: 'checkbox', id: 'qRequired', checked: !!q.required});
  const weight = h('input', {type: 'number', id: 'qWeight', min: '0', max: '100', step: '0.5', value: q.weight ?? 1, class: 'compact'});
  const sectionSel = h('select', {id: 'qSection'}, h('option', {value: '', text: '— Bölümsüz —'}), t.sections.map(sec => h('option', {value: sec.id, text: sec.title, selected: sec.id === q.section_id})));
  const options = h('div'); const negative = h('input', {type: 'checkbox', id: 'qNegative'});
  const optionBox = h('div', {class: 'field wide'});
  const addOption = (o = {}) => {
    const row = h('div', {class: 'option-row'}, h('input', {placeholder: 'Seçenek', value: o.label || '', 'aria-label': 'Seçenek etiketi'}),
      h('input', {type: 'number', min: '0', max: '100', placeholder: 'Puan 0–100', value: o.score ?? '', 'aria-label': 'Seçenek puanı'}),
      h('button', {type: 'button', class: 'btn ghost', text: '✕', 'aria-label': 'Seçeneği kaldır', onclick: () => row.remove()}));
    row.dataset.value = o.value ?? ''; options.append(row);
  };
  const ruleQ = h('select', {id: 'ruleQuestion'}, h('option', {value: '', text: '— Her zaman göster —'}), earlier.map(x => h('option', {value: x.code, text: `${x.code} · ${x.text.slice(0, 60)}`, selected: q.show_if?.question === x.code})));
  const ruleOp = h('select', {id: 'ruleOp'}, [['equals', 'eşitse'], ['in', 'şunlardan biriyse'], ['min', 'en az'], ['max', 'en çok']].map(([v, l]) => h('option', {value: v, text: l, selected: q.show_if && v in q.show_if})));
  const ruleValue = h('div');
  const riskCat = h('select', {id: 'qRiskCat'}, h('option', {value: '', text: '— Risk sinyali yok —'}), (META.field('survey_questions', 'risk_category')?.options || []).map(o => h('option', {value: o.value, text: o.label, selected: o.value === q.risk_category})));
  const riskThreshold = h('input', {type: 'number', id: 'qRiskThreshold', min: '0', max: '100', value: q.risk_threshold ?? 50, class: 'compact'});
  const drawValue = () => {
    const source = earlier.find(x => x.code === ruleQ.value); ruleValue.replaceChildren();
    if (!source) { ruleOp.disabled = true; return; } ruleOp.disabled = false;
    const current = q.show_if && q.show_if.question === source.code ? q.show_if : {};
    if (source.options && (ruleOp.value === 'equals' || ruleOp.value === 'in')) {
      const chosen = new Set(current.in || (current.equals !== undefined ? [current.equals] : []));
      ruleValue.append(h('div', {class: 'choices'}, source.options.map(o => h('label', {}, h('input', {type: ruleOp.value === 'in' ? 'checkbox' : 'radio', name: 'ruleValue', value: o.value, checked: chosen.has(o.value)}), o.label))));
    } else ruleValue.append(h('input', {type: 'number', name: 'ruleValue', class: 'compact', value: current[ruleOp.value] ?? current.equals ?? '', 'aria-label': 'Koşul değeri'}));
  };
  const drawOptions = () => {
    const k = kind.value; const scored = !['text', 'number', 'date'].includes(k);
    weight.disabled = !scored; riskCat.disabled = !scored; riskThreshold.disabled = !scored;
    optionBox.replaceChildren();
    if (k === 'yes_no') {
      negative.checked = !!(q.options && q.options.find(o => o.value === 'yes')?.score === 0);
      optionBox.append(h('label', {class: 'toggle', for: 'qNegative'}, negative, 'Olumsuz soru: "Evet" düşük puan alır (ör. "Güvenlik olayı yaşandı mı?")'));
    } else if (k === 'single_choice' || k === 'multi_choice') {
      options.replaceChildren(); (q.options && q.kind === k ? q.options : [{}, {}]).forEach(addOption);
      optionBox.append(h('span', {text: 'Seçenekler (puan boş bırakılırsa seçenek puanlanmaz)'}), h('div', {class: 'control'}, options), btn('+ Seçenek', () => addOption(), 'ghost small'));
    }
  };
  kind.addEventListener('change', drawOptions); ruleQ.addEventListener('change', drawValue); ruleOp.addEventListener('change', drawValue);
  const body = h('form', {class: 'formgrid', novalidate: true},
    h('div', {class: 'notice bad wide form-error hidden', role: 'alert'}),
    h('label', {class: 'field wide', for: 'qText'}, h('span', {}, 'Soru', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, text)),
    h('label', {class: 'field wide', for: 'qHelp'}, 'Yardım metni', h('div', {class: 'control'}, help)),
    h('label', {class: 'field', for: 'qKind'}, 'Soru türü', h('div', {class: 'control'}, kind)),
    h('label', {class: 'field', for: 'qSection'}, 'Bölüm', h('div', {class: 'control'}, sectionSel)),
    h('label', {class: 'toggle', for: 'qRequired'}, required, 'Zorunlu'),
    h('label', {class: 'field', for: 'qWeight'}, 'Ağırlık', h('div', {class: 'control'}, weight), h('span', {class: 'hint', text: '0: puana katılmaz'})),
    optionBox,
    h('div', {class: 'field wide'}, 'Gösterim koşulu', h('div', {class: 'filters'}, ruleQ, ruleOp), h('div', {class: 'control'}, ruleValue),
      h('span', {class: 'hint', text: 'Koşul sağlanmazsa soru gösterilmez ve zorunlu sayılmaz.'})),
    h('div', {class: 'field wide'}, 'Risk sinyali', h('div', {class: 'filters'}, riskCat, h('span', {class: 'small', text: 'ortalama puan'}), riskThreshold, h('span', {class: 'small', text: 'altındaysa'})),
      h('span', {class: 'hint', text: 'Bir tedarikçinin bu sorudaki ortalaması eşiğin altında kalırsa sonuçlarda risk sinyali görünür; tek tıkla risk kaydı açılır.'})));
  drawOptions(); drawValue();
  const save = async () => {
    if (!text.value.trim()) { showErrors(body, {}, 'Soru metni gerekli'); text.focus(); throw new Error('Soru metni gerekli'); }
    const payload = {text: text.value.trim(), help: help.value.trim() || null, kind: kind.value, required: required.checked ? 1 : 0,
      weight: weight.disabled ? 0 : Number(weight.value || 0), section_id: sectionSel.value ? Number(sectionSel.value) : null};
    if (kind.value === 'yes_no') payload.options_json = JSON.stringify(negative.checked ? [{value: 'yes', label: 'Evet', score: 0}, {value: 'no', label: 'Hayır', score: 100}] : [{value: 'yes', label: 'Evet', score: 100}, {value: 'no', label: 'Hayır', score: 0}]);
    else if (kind.value === 'single_choice' || kind.value === 'multi_choice') {
      const opts = [...options.children].map(row => { const [l, sc] = row.querySelectorAll('input'); const o = {label: l.value.trim()}; if (row.dataset.value) o.value = row.dataset.value; if (sc.value !== '') o.score = Number(sc.value); return o; }).filter(o => o.label);
      if (!opts.length) { showErrors(body, {}, 'En az bir seçenek girin'); throw new Error('En az bir seçenek girin'); }
      payload.options_json = JSON.stringify(opts);
    } else payload.options_json = null;
    if (ruleQ.value) {
      const op = ruleOp.value; const inputs = [...ruleValue.querySelectorAll('[name=ruleValue]')];
      let v; if (inputs[0]?.type === 'number') v = inputs[0].value === '' ? null : Number(inputs[0].value);
      else { const chosen = inputs.filter(i => i.checked).map(i => i.value); v = op === 'in' ? chosen : chosen[0]; }
      if (v === null || v === undefined || (Array.isArray(v) && !v.length)) { showErrors(body, {}, 'Koşul için bir değer seçin'); throw new Error('Koşul için bir değer seçin'); }
      payload.show_if_json = JSON.stringify({question: ruleQ.value, [op]: v});
    } else payload.show_if_json = null;
    payload.risk_category = riskCat.disabled ? null : riskCat.value || null;
    payload.risk_threshold = payload.risk_category ? Number(riskThreshold.value || 50) : null;
    try {
      if (isNew) await api('survey_questions', {method: 'POST', body: {template_id: t.id, position: t.questions.length + 1, ...payload}});
      else await api(`survey_questions/${q.id}`, {method: 'PATCH', body: payload});
    } catch (e) { showErrors(body, {}, e.message); throw e; }
    Modal.close(); toast(isNew ? 'Soru eklendi' : 'Soru kaydedildi'); templateBuilder(t.id);
  };
  body.addEventListener('submit', e => { e.preventDefault(); guard(null, save).catch(() => {}); });
  Modal.open(isNew ? 'Yeni soru' : 'Soruyu düzenle · ' + q.code, body, [btn('Vazgeç', () => Modal.close(), 'secondary'), btn(isNew ? 'Ekle' : 'Kaydet', save)], true);
}

// ------------------------------------------------------------------ anket: kampanya
const CAMPAIGN_FIELDS = ['code', 'name', 'template_id', 'subject', 'audience', 'anonymous', 'min_responses', 'opens_on', 'closes_on', 'period_start', 'period_end', 'owner', 'description'];
CREATE.survey_campaigns = async defaults => {
  await list('survey_templates', true);
  S.cache.survey_templates = S.cache.survey_templates.filter(t => t.status !== 'retired');
  return recordForm('survey_campaigns', null, {only: CAMPAIGN_FIELDS, defaults: {subject: 'supplier', audience: 'invited', min_responses: 3, owner: S.me.username, ...defaults},
    title: 'Yeni anket kampanyası', extra: h('div', {class: 'notice wide'}, h('strong', {text: 'Değerlendirilen: '}), '"Yok" seçilirse tedarikçiden bağımsız bir anket olur (ör. iç memnuniyet). ',
      h('strong', {text: 'Katılım: '}), '"Tüm kullanıcılar" seçilirse davet gerekmez. ', h('strong', {text: 'Anonim: '}), 'yanıt kişiyle eşleşmez; yanıt sayısı eşiğin altındayken sonuç gösterilmez.'),
    onsaved: r => { Drawer.close(); invalidate('survey_campaigns'); Router.go('surveys/' + r.id); }});
};
async function campaignPage(id, tab) {
  const k = await api(`survey_campaigns/${id}/context`); const can = META.def('survey_campaigns').can_write;
  const submitted = k.response_counts.submitted;
  setPage(k.name, `${k.code} · ${k.template.name} (sürüm ${k.template.version})`, [
    can && k.status === 'draft' ? btn('Kampanyayı aç', async () => {
      if (!await confirmDialog('Kampanyayı aç', 'Kampanya açılınca şablon dondurulur ve davetliler anketi "Anketlerim" sayfasında görür.', 'Aç')) return;
      await api(`survey_campaigns/${id}/open`, {method: 'POST', body: {}}); toast('Kampanya açıldı'); campaignPage(id);
    }) : null,
    can && k.status === 'open' ? btn('Kampanyayı kapat', async () => {
      if (!await confirmDialog('Kampanyayı kapat', 'Kapanan kampanyaya yanıt verilemez. Sonuçlar korunur.', 'Kapat', 'danger')) return;
      await api(`survey_campaigns/${id}/close`, {method: 'POST', body: {}}); toast('Kampanya kapatıldı'); campaignPage(id);
    }, 'secondary') : null,
    h('a', {class: 'btn secondary', href: '#/templates/' + k.template_id, text: 'Şablon'})], [['Anket kampanyaları', 'r/survey_campaigns']]);
  const invited = k.invitations.length; const answered = k.invitations.filter(i => i.status === 'answered').length;
  const head = h('div', {class: 'cards'},
    metric('Durum', META.option('survey_campaigns', 'status', k.status), k.status === 'open' ? (k.closes_on ? 'Kapanış ' + fmt.date(k.closes_on) : 'Kapanış tarihi yok') : ''),
    metric('Değerlendirilen', k.subject === 'none' ? 'Bağımsız' : String(k.targets.length), META.option('survey_campaigns', 'subject', k.subject)),
    metric('Katılım', k.audience === 'all' ? 'Herkes' : `${answered} / ${invited}`, k.audience === 'all' ? 'Davet gerekmez' : 'Yanıtlanan / davet'),
    metric('Gönderilen yanıt', String(submitted), `${k.response_counts.started - submitted} taslak${k.anonymous ? ' · anonim' : ''}`));
  const items = [{key: 'results', label: 'Sonuçlar', render: () => campaignResults(k)}];
  if (k.subject !== 'none') items.push({key: 'targets', label: 'Değerlendirilenler', count: k.targets.length, render: () => campaignTargets(k)});
  if (k.audience === 'invited') items.push({key: 'invites', label: 'Davetliler', count: invited, render: () => campaignInvites(k)});
  items.push({key: 'settings', label: 'Ayarlar', render: () => campaignSettings(k)});
  const setup = k.status === 'draft' ? h('div', {class: 'notice warn'}, 'Kampanya taslak. Açmadan önce: ',
    k.subject !== 'none' ? (k.targets.length ? '✓ değerlendirilenler eklendi · ' : '• değerlendirilecek tedarikçileri ekleyin · ') : '',
    k.audience === 'invited' ? (invited ? '✓ davetliler eklendi' : '• davetlileri ekleyin') : '✓ herkes katılabilir') : null;
  content(head, setup || '', h('div', {class: 'panel'}, tabs(items, tab || (k.status === 'draft' ? (k.subject !== 'none' ? 'targets' : k.audience === 'invited' ? 'invites' : 'settings') : 'results'))));
}
function campaignSettings(k) {
  return h('div', {}, kv(CAMPAIGN_FIELDS.map(f => [META.label('survey_campaigns', f), display('survey_campaigns', f, k[f])])), h('br'),
    META.def('survey_campaigns').can_write && k.status !== 'closed' ? btn('Düzenle', () => recordForm('survey_campaigns', k,
      {only: k.status === 'draft' ? CAMPAIGN_FIELDS.filter(f => f !== 'code') : ['name', 'description', 'closes_on', 'owner', 'min_responses'],
        onsaved: () => { Drawer.close(); campaignPage(k.id, 'settings'); }}), 'secondary') : null);
}
async function campaignTargets(k) {
  const can = META.def('survey_campaigns').can_write && k.status !== 'closed';
  const add = async body => { const r = await api(`survey_campaigns/${k.id}/targets`, {method: 'POST', body}); toast(`${r.added} eklendi${r.skipped ? ', ' + r.skipped + ' zaten vardı' : ''}`); campaignPage(k.id, 'targets'); };
  const picker = async () => {
    const res = k.subject === 'engagement' ? 'engagements' : 'suppliers'; const records = (await list(res, true)).filter(r => r.status === 'active');
    const taken = new Set(k.targets.map(t => k.subject === 'engagement' ? t.engagement_id : t.supplier_id));
    const search = h('input', {type: 'search', placeholder: 'Ara…', 'aria-label': 'Ara'});
    const box = h('div', {class: 'choices'});
    const draw = () => { const q = search.value.toLocaleLowerCase(TR); box.replaceChildren(...records.filter(r => !taken.has(r.id) && titleOf(r).toLocaleLowerCase(TR).includes(q)).slice(0, 300)
      .map(r => h('label', {}, h('input', {type: 'checkbox', value: r.id}), titleOf(r), r.tier ? ' ' : '', r.tier ? display('suppliers', 'tier', r.tier) : ''))); };
    search.addEventListener('input', draw); draw();
    Modal.open('Değerlendirilecekleri seç', h('div', {}, search, h('br'), box), [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Ekle', async () => {
      const ids = [...box.querySelectorAll('input:checked')].map(i => Number(i.value)); if (!ids.length) throw new Error('En az bir kayıt seçin');
      Modal.close(); await add(k.subject === 'engagement' ? {engagement_ids: ids} : {supplier_ids: ids});
    })]);
  };
  return h('div', {}, can ? h('div', {class: 'filters'}, btn('+ Seçerek ekle', picker, 'secondary small'),
    ['critical', 'important'].map(tier => btn(`Tüm ${META.option('suppliers', 'tier', tier).toLocaleLowerCase(TR)} tedarikçiler`, () => add({tier}), 'ghost small'))) : null, h('br'),
  k.targets.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Tedarikçi', 'Kritiklik', k.subject === 'engagement' ? 'Angajman' : null].filter(Boolean).map(t => h('th', {text: t})))),
    h('tbody', {}, k.targets.map(t => h('tr', {class: 'clickable', onclick: () => openRecord('suppliers', t.supplier_id)}, h('td', {class: 'cell-primary', text: `${t.supplier_code} · ${t.supplier_name}`}),
      h('td', {}, display('suppliers', 'tier', t.tier)), k.subject === 'engagement' ? h('td', {text: t.engagement_code || ''}) : null)))))
    : empty('Değerlendirilecek tedarikçi yok', 'Kritiklik seviyesine göre toplu ekleyebilir veya tek tek seçebilirsiniz.'));
}
async function campaignInvites(k) {
  const can = META.def('survey_campaigns').can_write && k.status !== 'closed';
  const targets = Object.fromEntries(k.targets.map(t => [t.id, t.supplier_name]));
  const inviteModal = async () => {
    const people = await api('directory').catch(() => []);
    const search = h('input', {type: 'search', placeholder: 'Kişi ara…', 'aria-label': 'Kişi ara'}); const box = h('div', {class: 'choices'});
    const manual = h('textarea', {placeholder: 'Listede olmayan kullanıcı adları (virgül veya satır başıyla)', 'aria-label': 'Ek kullanıcı adları'});
    const draw = () => { const q = search.value.toLocaleLowerCase(TR); box.replaceChildren(...people.filter(p => (p.display_name + ' ' + p.username).toLocaleLowerCase(TR).includes(q)).slice(0, 300)
      .map(p => h('label', {}, h('input', {type: 'checkbox', value: p.username}), p.display_name || p.username, h('span', {class: 'muted small', text: ' ' + (p.username.startsWith('entra:') ? '' : p.username)})))); };
    search.addEventListener('input', draw); draw();
    const targetSel = k.subject !== 'none' ? h('select', {multiple: true, size: Math.min(8, k.targets.length + 1), 'aria-label': 'Değerlendirilecekler'},
      k.targets.map(t => h('option', {value: t.id, text: t.supplier_name + (t.engagement_code ? ' · ' + t.engagement_code : '')}))) : null;
    Modal.open('Davet et', h('div', {}, k.subject !== 'none' && !k.targets.length ? h('div', {class: 'notice bad', text: 'Önce değerlendirilecek tedarikçileri ekleyin.'}) : null,
      search, h('br'), box, h('br'), manual,
      targetSel ? h('div', {class: 'field'}, 'Değerlendirecekleri tedarikçiler (seçilmezse tümü)', h('div', {class: 'control'}, targetSel)) : null), [
      btn('Vazgeç', () => Modal.close(), 'secondary'),
      btn('Davet et', async () => {
        const chosen = [...box.querySelectorAll('input:checked')].map(i => i.value).concat(manual.value.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean));
        if (!chosen.length) throw new Error('En az bir kişi seçin');
        const body = {respondents: chosen}; if (targetSel) { const ids = [...targetSel.selectedOptions].map(o => Number(o.value)); body.target_ids = ids.length ? ids : 'all'; }
        const r = await api(`survey_campaigns/${k.id}/invite`, {method: 'POST', body}); Modal.close();
        toast(`${r.created} davet oluşturuldu${r.skipped ? ', ' + r.skipped + ' zaten vardı' : ''}`); campaignPage(k.id, 'invites');
      })]);
  };
  return h('div', {}, can ? btn('+ Davet et', inviteModal, 'secondary small') : null, h('br'), h('br'),
    k.anonymous ? h('div', {class: 'notice', text: 'Anonim kampanya: kimin yanıtladığı görünür, ne yanıtladığı hiçbir yerde kişiyle eşleşmez.'}) : null,
    k.invitations.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kişi', k.subject !== 'none' ? 'Değerlendirilen' : null, 'Durum', 'Yanıt zamanı'].filter(Boolean).map(t => h('th', {text: t})))),
      h('tbody', {}, k.invitations.map(i => h('tr', {}, h('td', {class: 'cell-primary', text: i.respondent}), k.subject !== 'none' ? h('td', {text: targets[i.target_id] || ''}) : null,
        h('td', {}, display('survey_invitations', 'status', i.status)), h('td', {text: fmt.datetime(i.answered_at)})))))) : empty('Davet yok', 'Anketi yanıtlayacak kişileri ekleyin.'));
}
async function campaignResults(k) {
  if (k.status === 'draft') return empty('Kampanya henüz açılmadı', 'Sonuçlar yanıtlar geldikçe burada görünür.');
  let r; try { r = await api(`survey_campaigns/${k.id}/results`); } catch (e) { return h('div', {class: 'notice bad', text: e.message}); }
  const top = h('div', {class: 'grid three'},
    gauge(r.average_score ?? null, 'Genel puan (0–100)', {sub: `${r.submitted} yanıt`}),
    gauge(r.response_rate, 'Yanıt oranı', {suffix: '%', good: 70, mid: 40, sub: r.invited ? `${r.invited} davet` : 'Herkese açık'}),
    r.questions?.find(q => q.nps) ? (n => gauge((n.score + 100) / 2, 'Tavsiye (NPS, −100…+100)', {text: (n.score > 0 ? '+' : '') + n.score, good: 60, mid: 50, sub: `${n.promoters} destekçi · ${n.passives} pasif · ${n.detractors} eleştirmen`}))(r.questions.find(q => q.nps).nps) : h('div'));
  if (r.hidden) return h('div', {}, top, h('br'), h('div', {class: 'notice', text: r.message}));
  if (!r.submitted) return h('div', {}, top, h('br'), empty('Henüz gönderilmiş yanıt yok', ''));
  const parts = [top, h('br')];
  if (r.sections.some(x => x.average_score !== null)) parts.push(section('Bölüm puanları', barChart(r.sections.map(x => ({label: x.title, value: x.average_score})), {max: 100})));
  if (r.targets.length) parts.push(section('Tedarikçi bazında', barChart(r.targets.filter(t => t.average_score !== null).sort((a, b) => a.average_score - b.average_score)
    .map(t => ({label: t.supplier_name + (t.engagement_code ? ' · ' + t.engagement_code : ''), value: t.average_score, color: t.average_score < 50 ? 3 : t.average_score < 75 ? 2 : 1, id: t.supplier_id})),
  {max: 100, onclick: item => openRecord('suppliers', item.id)})));
  if (r.risk_signals.length) {
    const canRisk = META.def('supplier_risks')?.can_write;
    const rows = r.risk_signals.map(sig => h('tr', {}, h('td', {}, sig.risk ? '' : h('input', {type: 'checkbox', value: sig.origin_ref, 'aria-label': 'Risk aç'})),
      h('td', {class: 'cell-primary', text: sig.supplier_name}), h('td', {text: sig.question}), h('td', {}, display('supplier_risks', 'category', sig.category)),
      h('td', {class: 'num', text: `${fmt.num(sig.average_score)} < ${sig.threshold}`}),
      h('td', {}, sig.risk ? h('a', {href: '#/r/supplier_risks', text: sig.risk.code, onclick: e => { e.preventDefault(); openRecord('supplier_risks', sig.risk.id); }}) : pill('Risk kaydı yok', 'warn'))));
    const table = h('table', {}, h('thead', {}, h('tr', {}, ['', 'Tedarikçi', 'Soru', 'Kategori', 'Puan / eşik', 'Risk'].map(t => h('th', {text: t})))), h('tbody', {}, rows));
    parts.push(section(`Risk sinyalleri (${r.risk_signals.length})`, h('div', {}, h('p', {class: 'intro', text: 'Risk kategorili sorularda ortalaması eşiğin altında kalan tedarikçiler. Seçip tek adımda risk kaydı açabilirsiniz; aynı sinyal ikinci kez risk açmaz.'}),
      h('div', {class: 'tablewrap'}, table)), canRisk && r.risk_signals.some(x => !x.risk) ? btn('Seçilenler için risk aç', async () => {
      const refs = [...table.querySelectorAll('input:checked')].map(i => i.value); if (!refs.length) throw new Error('En az bir sinyal seçin');
      const out = await api(`survey_campaigns/${k.id}/risk-signals`, {method: 'POST', body: {origin_refs: refs}}); toast(`${out.created.length} risk kaydı açıldı`); campaignPage(k.id, 'results');
    }, 'small') : null));
  }
  for (const q of r.questions) {
    let viz = null;
    if (q.distribution && (q.kind === 'scale_1_5' || q.kind === 'nps_0_10')) viz = barChart(q.distribution.map(d => ({label: String(d.value), value: d.count, color: q.kind === 'nps_0_10' ? (d.value >= 9 ? 1 : d.value <= 6 ? 3 : 2) : 0})), {format: v => fmt.num(v, 0)});
    else if (q.distribution) viz = barChart(q.distribution.map(d => ({label: d.label, value: d.count, color: 4})), {format: v => fmt.num(v, 0)});
    else if (q.answers) viz = q.answers.length ? h('ul', {class: 'mini'}, q.answers.map(a => h('li', {text: a}))) : h('div', {class: 'muted small', text: 'Yanıt yok'});
    else if (q.kind === 'number') viz = kv([['Ortalama', fmt.num(q.average, 2)], ['En düşük', fmt.num(q.min, 2)], ['En yüksek', fmt.num(q.max, 2)]]);
    const stats = [q.average !== undefined && q.average !== null && q.kind !== 'number' ? `Ortalama ${fmt.num(q.average, 2)}` : null, q.average_score !== null ? `Puan ${fmt.num(q.average_score)}` : null,
      q.nps ? `NPS ${q.nps.score} (${q.nps.promoters} destekçi, ${q.nps.passives} pasif, ${q.nps.detractors} eleştirmen)` : null, `${q.responses} yanıt`].filter(Boolean).join(' · ');
    parts.push(section(`${q.code} · ${q.text}`, h('div', {}, h('div', {class: 'muted small', text: stats}), viz), q.risk_category ? display('supplier_risks', 'category', q.risk_category) : null));
  }
  return h('div', {}, parts);
}

// ------------------------------------------------------------------ anket: yanıtlayan
async function mySurveys() {
  setPage('Anketlerim', 'Yanıtlamanız istenen ve herkese açık anketler. Yanıtlarınız taslak olarak otomatik kaydedilir; gönderdikten sonra değiştirilemez.');
  const items = await api('my/surveys'); S.mySurveys = items.filter(i => i.open && i.state !== 'submitted').length; navigation();
  if (!items.length) return content(h('div', {class: 'panel'}, empty('Şu anda size açık anket yok', 'Bir ankete davet edildiğinizde burada görünür.')));
  const start = async item => {
    if (item.response_id) return Router.go('respond/' + item.response_id);
    const r = await api(`survey_campaigns/${item.campaign_id}/responses`, {method: 'POST', body: item.target ? {target_id: item.target.id} : {}}); Router.go('respond/' + r.response_id);
  };
  const card = item => h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('div', {}, h('h3', {text: item.campaign}),
    h('div', {class: 'muted small', text: [item.target ? 'Değerlendirilen: ' + item.target.supplier_name + (item.target.engagement_code ? ' · ' + item.target.engagement_code : '') : 'Genel anket',
      item.closes_on ? 'Son gün ' + fmt.date(item.closes_on) : null, item.anonymous ? 'Anonim' : null].filter(Boolean).join(' · ')})),
  h('div', {class: 'filters'}, pill({new: 'Yeni', draft: 'Taslak', submitted: 'Gönderildi'}[item.state], {new: 'warn', draft: 'purple', submitted: 'good'}[item.state]),
    item.state === 'submitted' ? btn('Görüntüle', () => start(item), 'secondary small') : item.open ? btn(item.state === 'draft' ? 'Devam et' : 'Başla', () => start(item), 'small') : pill('Kapandı', 'neutral'))));
  const pending = items.filter(i => i.state !== 'submitted' && i.open); const rest = items.filter(i => !pending.includes(i));
  content(pending.length ? h('h3', {text: `Yanıt bekleyen (${pending.length})`}) : '', pending.map(card), rest.length ? h('h3', {text: 'Diğer'}) : '', rest.map(card));
}
async function respond(id) {
  const form = await api(`survey_responses/${id}/form`);
  const done = form.response.status === 'submitted';
  setPage(form.campaign.name, form.target ? 'Değerlendirilen: ' + form.target.supplier_name + (form.target.engagement_code ? ' · ' + form.target.engagement_code : '') : '', [], [['Anketlerim', 'my-surveys']]);
  const intro = h('div', {class: 'survey-head'}, h('h2', {text: form.name}), form.intro ? h('p', {text: form.intro}) : null,
    form.campaign.anonymous ? h('div', {class: 'notice success', text: 'Bu anket anonimdir: yanıtlarınız adınızla eşleşmez.'}) : null,
    done ? h('div', {class: 'notice success', text: 'Bu yanıtı ' + fmt.datetime(form.response.submitted_at) + ' tarihinde gönderdiniz. Gönderilen yanıt değiştirilemez.'}) : null);
  const view = surveyForm(form, {mode: done ? 'view' : 'answer',
    onSave: answers => api(`survey_responses/${id}/answers`, {method: 'POST', body: {answers}}),
    onSubmit: async answers => {
      await api(`survey_responses/${id}/answers`, {method: 'POST', body: {answers, submit: true}});
      S.mySurveys = Math.max(0, S.mySurveys - 1); navigation();
      content(h('div', {class: 'survey-shell'}, h('div', {class: 'panel thanks'}, h('div', {class: 'mark', text: '✓'}), h('h2', {text: 'Teşekkürler'}),
        h('p', {class: 'intro', text: form.outro || 'Yanıtınız kaydedildi.'}), h('a', {class: 'btn', href: '#/my-surveys', text: 'Anketlerime dön'}))));
      window.scrollTo(0, 0);
    }});
  content(h('div', {class: 'survey-shell'}, intro, view.node, done ? null : h('div', {class: 'filters'}, btn('Yanıtı gönder', () => view.submit()),
    h('span', {class: 'muted small', text: 'Gönderdikten sonra değiştiremezsiniz.'}))));
}

// ------------------------------------------------------------------ takvim
async function schedulePage(params) {
  const all = params.get('all') === '1';
  setPage('Takvim', 'Kritiklik seviyesine göre performans değerlendirmesi ve memnuniyet anketi takvimi, gözden geçirmesi gelen riskler. Sıklıklar Yönetim → Politika Parametreleri\'nde.',
    [h('a', {class: 'btn secondary', href: all ? '#/schedule' : '#/schedule?all=1', text: all ? 'Yalnızca geciken ve yaklaşanlar' : 'Tüm tedarikçiler'})]);
  const data = await api('schedule' + (all ? '?all=1' : '')); const sm = data.summary;
  const kindLabel = {review: 'Performans değerlendirmesi', survey: 'Memnuniyet anketi'};
  const stateCell = i => i.state === 'overdue' ? pill(`${-i.days} gün gecikti`, 'bad') : i.state === 'due_soon' ? pill(`${i.days} gün kaldı`, 'warn') : pill('Zamanında', 'good');
  const action = i => i.kind === 'review' && META.def('performance_reviews')?.can_write ? btn('Değerlendirme gir', () => createRecord('performance_reviews', {supplier_id: i.supplier_id}), 'ghost small')
    : i.kind === 'survey' && META.def('survey_campaigns')?.can_write ? h('a', {class: 'btn ghost small', href: '#/r/survey_campaigns', text: 'Kampanyalar'}) : '';
  const cards = h('div', {class: 'cards'},
    metric('Geciken değerlendirme', String(sm.review_overdue || 0), `${sm.review_due_soon || 0} tanesi ${data.warning_days} gün içinde`, sm.review_overdue ? 'bad' : 'good'),
    metric('Geciken anket', String(sm.survey_overdue || 0), `${sm.survey_due_soon || 0} tanesi ${data.warning_days} gün içinde`, sm.survey_overdue ? 'bad' : 'good'),
    metric('Gözden geçirmesi geçen risk', String(sm.risk_overdue || 0), `${sm.risk_due_soon || 0} tanesi yaklaşıyor`, sm.risk_overdue ? 'warn' : 'good'));
  const table = data.items.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Tedarikçi', 'Kritiklik', 'İş', 'Son yapılan', 'Vade', 'Durum', ''].map(t => h('th', {text: t})))),
    h('tbody', {}, data.items.map(i => h('tr', {}, h('td', {class: 'cell-primary'}, h('a', {href: '#/r/suppliers/' + i.supplier_id, text: i.name}), h('span', {class: 'cell-sub', text: i.owner ? 'Sahip: ' + i.owner : 'İlişki sahibi yok'})),
      h('td', {}, display('suppliers', 'tier', i.tier)), h('td', {text: `${kindLabel[i.kind]} · ${i.cadence_months} ayda bir`}),
      h('td', {}, i.never ? pill('Hiç yapılmadı', 'warn') : fmt.date(i.last)), h('td', {text: fmt.date(i.due)}), h('td', {}, stateCell(i)), h('td', {}, action(i)))))))
    : empty('Geciken veya yaklaşan iş yok', all ? '' : 'Tüm tedarikçileri görmek için yukarıdaki düğmeyi kullanın.');
  const risks = data.risks.length ? h('ul', {class: 'mini'}, data.risks.map(r => h('li', {class: 'link', tabindex: '0', onclick: () => openRecord('supplier_risks', r.id)},
    h('strong', {text: r.code + ' · ' + r.title}), ' ', stateCell(r), h('span', {class: 'cell-sub', text: `Gözden geçirme ${fmt.date(r.review_date)} · ${r.owner}`})))) : h('div', {class: 'muted small', text: 'Gözden geçirmesi gelen risk yok'});
  content(cards, h('div', {class: 'panel'}, h('h3', {text: 'Değerlendirme ve anket takvimi'}), table), data.risks ? h('div', {class: 'panel'}, h('h3', {text: 'Risk gözden geçirmeleri'}), risks) : '');
}

// ------------------------------------------------------------------ aktarım
function importSummary(sum) {
  const labels = {total: 'Satır', create: 'Yeni', update: 'Güncellenecek', skip: 'Değişmeyen', review: 'İnceleme', error: 'Hatalı'};
  const tones = {create: 'good', update: 'purple', skip: 'neutral', review: 'warn', error: 'bad', total: 'neutral'};
  return h('div', {}, h('div', {class: 'chips'}, Object.entries(labels).filter(([k]) => sum[k]).map(([k, l]) => pill(`${l}: ${sum[k]}`, tones[k]))),
    sum.unmapped_columns?.length ? h('div', {class: 'notice warn', text: 'Tanınmayan sütunlar (yok sayıldı): ' + sum.unmapped_columns.join(', ')}) : null);
}
const ACTION_LABEL = {create: ['Yeni', 'good'], update: ['Güncellenir', 'purple'], skip: ['Değişmez', 'neutral'], review: ['İnceleme', 'warn'], error: ['Hata', 'bad']};
function fileToBase64(file) {
  return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = () => reject(new Error('Dosya okunamadı')); r.readAsDataURL(file); });
}
async function transferPage() {
  setPage('Aktarım', 'Excel (XLSX) veya CSV ile içe ve dışa aktarma. Önce deneyin, sonucu görün, sonra uygulayın. Var olan kayıtta yalnızca boş alanlar doldurulur; portalda girilmiş değer korunur.');
  const catalog = await api('transfer/catalog');
  const state = {resource: catalog.imports[0]?.resource, file: null, source: 'manual', preview: null};
  const host = h('div');
  const steps = () => h('div', {class: 'steps'}, [['1', 'Kayıt türü'], ['2', 'Dosya'], ['3', 'Deneme sonucu'], ['4', 'Uygula']].map(([n, l], i) => {
    const stage = state.preview ? (state.preview.dry_run ? 2 : 3) : state.file ? 1 : 0;
    return h('div', {class: 'step' + (i === stage ? ' on' : i < stage ? ' done' : '')}, h('b', {text: i < stage ? '✓' : n}), l);
  }));
  const draw = () => {
    const current = catalog.imports.find(i => i.resource === state.resource);
    const types = h('div', {class: 'type-cards'}, catalog.imports.map(i => h('button', {type: 'button', class: 'type-card' + (i.resource === state.resource ? ' on' : ''),
      onclick: () => { state.resource = i.resource; state.preview = null; draw(); }}, h('strong', {text: i.label}), h('span', {class: 'small muted', text: 'Eşleşme: ' + i.key.join(' + ')}))));
    const fileInput = h('input', {type: 'file', accept: '.xlsx,.csv', class: 'hidden', id: 'importFile'});
    const zone = h('label', {class: 'dropzone', for: 'importFile'}, state.file ? h('div', {}, h('strong', {text: state.file.name}), h('div', {class: 'small', text: fmt.num(state.file.size / 1024, 0) + ' KB · değiştirmek için tıklayın'}))
      : h('div', {}, h('strong', {text: 'Dosyayı buraya bırakın veya seçmek için tıklayın'}), h('div', {class: 'small', text: '.xlsx veya .csv (UTF-8), en çok 12 MB ve 5.000 satır'})));
    const pick = f => { if (!f) return; if (!/\.(xlsx|csv)$/i.test(f.name)) { toast('Dosya .xlsx veya .csv olmalı', false); return; } state.file = f; state.preview = null; draw(); };
    fileInput.addEventListener('change', () => pick(fileInput.files[0]));
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); }); zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('over'); pick(e.dataTransfer.files[0]); });
    const source = state.resource === 'suppliers' ? h('label', {class: 'field'}, 'Kaynak sistem', h('div', {class: 'control'}, h('select', {onchange: e => { state.source = e.target.value; }},
      catalog.sources.map(s2 => h('option', {value: s2.value, text: s2.label, selected: s2.value === state.source}))))) : null;
    const run = async dry => {
      const body = {filename: state.file.name, content_base64: await fileToBase64(state.file), dry_run: dry};
      if (state.resource === 'suppliers') body.source_system = state.source;
      state.preview = await api('import/' + state.resource, {method: 'POST', body}); if (!dry) { invalidate(state.resource); toast('Aktarım uygulandı'); } draw();
    };
    const preview = state.preview ? h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: state.preview.dry_run ? 'Deneme sonucu (henüz yazılmadı)' : 'Uygulandı'}),
      state.preview.dry_run ? btn('Uygula', async () => {
        if (state.preview.error && !await confirmDialog('Hatalı satırlar var', `${state.preview.error} satır hatalı ve atlanacak. Diğer satırlar uygulansın mı?`, 'Uygula')) return;
        await run(false);
      }, 'success') : h('a', {class: 'btn secondary', href: '#/r/' + state.resource, text: 'Kayıtları aç'})),
    importSummary(state.preview), h('br'), rowsTable(state.preview.rows)) : null;
    host.replaceChildren(steps(), h('div', {class: 'panel'}, h('h3', {text: '1. Kayıt türü'}), types, h('br'),
      current ? btn('Şablonu indir: ' + current.label, () => download('import/templates/' + current.resource, `sablon-${current.resource}.xlsx`), 'ghost small') : null),
    h('div', {class: 'panel'}, h('h3', {text: '2. Dosya'}), zone, fileInput, source, h('br'),
      btn('Dene (kayıt yazmaz)', () => run(true), '', {disabled: !state.file})), preview || '');
  };
  const rowsTable = rows => {
    const filter = h('select', {class: 'compact', 'aria-label': 'Satır filtresi'}, h('option', {value: '', text: 'Tüm satırlar'}), Object.entries(ACTION_LABEL).map(([k, [l]]) => h('option', {value: k, text: l})));
    const body = h('tbody'); const fill = () => body.replaceChildren(...rows.filter(r => !filter.value || r.action === filter.value).map(r => h('tr', {},
      h('td', {class: 'num', text: r.row_no}), h('td', {}, pill(...ACTION_LABEL[r.action])), h('td', {text: Object.entries(r.values || {}).slice(0, 4).map(([k, v]) => `${META.label(state.resource, k)}: ${v}`).join(' · ')}),
      h('td', {class: r.action === 'error' ? 'small' : 'small muted', text: r.message || ''}))));
    filter.addEventListener('change', fill); fill();
    return h('div', {}, filter, h('br'), h('br'), h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Satır', 'Sonuç', 'Değerler', 'Mesaj'].map(t => h('th', {text: t})))), body)),
      rows.length >= 500 ? h('p', {class: 'muted small', text: 'İlk 500 satır gösteriliyor; tamamı aktarım kaydındadır.'}) : null);
  };
  draw();
  const exports = h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Dışa aktarma'}), btn('Tüm portal (tek Excel)', () => download('export', 'tedarik-portali.xlsx'))),
    h('div', {class: 'tablewrap'}, h('table', {}, h('tbody', {}, catalog.exports.map(e => h('tr', {}, h('td', {class: 'cell-primary', text: e.label}),
      h('td', {class: 'num'}, btn('Excel', () => download(`export/${e.resource}?format=xlsx`, e.resource + '.xlsx'), 'ghost small'), btn('CSV', () => download(`export/${e.resource}`, e.resource + '.csv'), 'ghost small'))))))));
  content(host, exports);
}

// ------------------------------------------------------------------ kullanıcılar
async function usersPage() {
  const local = S.meta.auth_mode !== 'entra';
  setPage('Kullanıcılar', local ? 'Yerel hesaplar, roller ve birim atamaları. Geçici parola yalnızca bir kez gösterilir.' :
    'Kurumsal hesaplar ilk girişte açılır; rol Entra uygulama rolünden gelir. Burada birim ataması yapılır ve hesap devre dışı bırakılır.',
  [local ? btn('+ Kullanıcı', () => userForm()) : null, btn('Rol ve yetki matrisi', () => Router.go('roles'), 'secondary')]);
  const [users] = await Promise.all([api('users'), list('org_units')]);
  const units = id => (S.cache.org_units || []).find(u => u.id === id)?.name || '#' + id;
  content(h('div', {class: 'panel'}, users.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kullanıcı', 'Tür', 'Rol', 'Birimler', 'Durum', 'Erişim', 'Son giriş'].map(t => h('th', {text: t})))),
    h('tbody', {}, users.map(u => { const tr = h('tr', {class: 'clickable', tabindex: '0', onclick: () => userForm(u)},
      h('td', {class: 'cell-primary'}, u.display_name, h('span', {class: 'cell-sub', text: u.kind === 'entra' ? 'Entra hesabı' : u.username})),
      h('td', {}, pill(u.kind === 'entra' ? 'Kurumsal' : 'Yerel', u.kind === 'entra' ? 'purple' : 'neutral')),
      h('td', {}, u.role ? roleLabel(u.role) : h('span', {class: 'muted', text: u.kind === 'entra' ? 'Entra rolü' : '—'})),
      h('td', {text: u.org_unit_ids.map(units).join(', ')}), h('td', {}, u.is_active ? pill('Aktif', 'good') : pill('Devre dışı', 'bad')),
      h('td', {}, u.external ? pill('Dış denetçi', 'purple') : null, u.access_expires ? h('span', {class: 'cell-sub ' + (u.access_expired ? 'late' : ''), text: (u.access_expired ? 'Süresi doldu ' : 'Son: ') + fmt.date(u.access_expires)}) : h('span', {class: 'muted', text: 'Süresiz'})),
      h('td', {text: fmt.datetime(u.last_login_at)}));
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') userForm(u); }); return tr; })))) : empty('Kullanıcı yok', '')));
}
function userForm(user) {
  const local = S.meta.auth_mode !== 'entra'; const isNew = !user;
  const username = h('input', {id: 'uName', value: user?.username || '', disabled: !isNew, autocomplete: 'off'});
  const display = h('input', {id: 'uDisplay', value: user?.display_name || ''});
  const email = h('input', {id: 'uEmail', type: 'email', value: user?.email || ''});
  const role = h('select', {id: 'uRole', disabled: !local || user?.kind === 'entra'}, S.meta.roles.map(r => h('option', {value: r.value, text: r.label, selected: r.value === (user?.role || 'VIEWER')})));
  const chosen = new Set(user?.org_unit_ids || []);
  const unitBox = h('div', {class: 'choices'}, (S.cache.org_units || []).map(u => h('label', {}, h('input', {type: 'checkbox', value: u.id, checked: chosen.has(u.id)}), titleOf(u))));
  const active = h('input', {type: 'checkbox', id: 'uActive', checked: user ? !!user.is_active : true});
  const body = h('div', {class: 'formgrid'},
    h('label', {class: 'field', for: 'uName'}, 'Kullanıcı adı', h('div', {class: 'control'}, username), isNew ? h('span', {class: 'hint', text: '3–60 karakter: harf, rakam, . _ -'}) : null),
    h('label', {class: 'field', for: 'uDisplay'}, 'Görünen ad', h('div', {class: 'control'}, display)),
    isNew ? null : h('label', {class: 'field', for: 'uEmail'}, 'E-posta', h('div', {class: 'control'}, email)),
    h('label', {class: 'field', for: 'uRole'}, 'Rol', h('div', {class: 'control'}, role), !local || user?.kind === 'entra' ? h('span', {class: 'hint', text: 'Kurumsal kullanıcının rolü Entra uygulama rolünden gelir.'}) : null),
    h('div', {class: 'field wide'}, 'Birimler', h('span', {class: 'hint', text: 'Birim Kullanıcısı yalnızca bu birimlerin kayıtlarına yazar.'}), h('div', {class: 'control'}, unitBox)),
    isNew ? null : h('label', {class: 'toggle', for: 'uActive'}, active, 'Hesap aktif (devre dışı bırakmak açık oturumu hemen kapatır)'));
  const showSecret = (r, title, text) => Modal.open(title, h('div', {}, h('p', {class: 'intro', text}), h('div', {class: 'secret', text: r.temporary_password})),
    [btn('Kopyala', async () => { await navigator.clipboard.writeText(r.temporary_password); toast('Kopyalandı'); }, 'secondary'), btn('Tamam', () => { Modal.close(); usersPage(); })]);
  const canReset = !isNew && local && user.kind !== 'entra' && user.username !== S.me.username;
  Modal.open(isNew ? 'Yeni kullanıcı' : user.display_name, body, [btn('Vazgeç', () => Modal.close(), 'secondary'),
    !isNew && typeof accessForm === 'function' ? btn('Erişim süresi / dış denetçi', () => accessForm(user, usersPage), 'ghost') : null,
    canReset ? btn('Geçici parola ver', async () => {
      if (!await confirmDialog('Geçici parola ver: ' + user.username, 'Kullanıcının mevcut parolası geçersiz olur ve açık oturumları kapanır. Yeni geçici parola bir kez gösterilir; ilk girişte değiştirilir.', 'Geçici parola ver')) return;
      const r = await api(`users/${user.id}/reset-password`, {method: 'POST', body: {}});
      showSecret(r, 'Geçici parola', `${r.username} için geçici parola aşağıdadır. Bir daha gösterilmez; güvenli bir kanalla iletin.`);
    }, 'secondary') : null,
    btn(isNew ? 'Oluştur' : 'Kaydet', async () => {
    const ids = [...unitBox.querySelectorAll('input:checked')].map(i => Number(i.value));
    if (isNew) {
      const r = await api('users', {method: 'POST', body: {username: username.value.trim(), display_name: display.value.trim() || null, role: role.value, org_unit_ids: ids}});
      const secret = h('div', {class: 'secret', text: r.temporary_password});
      Modal.open('Kullanıcı oluşturuldu', h('div', {}, h('p', {class: 'intro', text: `${r.username} için geçici parola aşağıdadır. Bu parola bir daha gösterilmez; güvenli bir kanalla iletin. İlk girişte değiştirilmesi zorunludur.`}), secret),
        [btn('Kopyala', async () => { await navigator.clipboard.writeText(r.temporary_password); toast('Kopyalandı'); }, 'secondary'), btn('Tamam', () => { Modal.close(); usersPage(); })]);
      return;
    }
    const body2 = {display_name: display.value.trim() || null, email: email.value.trim() || null, org_unit_ids: ids, is_active: active.checked ? 1 : 0};
    if (local && user.kind !== 'entra') body2.role = role.value;
    await api('users/' + user.id, {method: 'PATCH', body: body2}); Modal.close(); toast('Kaydedildi'); usersPage();
  })]);
}

// ------------------------------------------------------------------ uyum (GRC)
const RESULT_LABEL = {pass: 'Başarılı', fail: 'Başarısız', inconclusive: 'Belirsiz', not_applicable: 'Uygulanamaz', untested: 'Test edilmedi'};
function resultPill(status) { return pill(RESULT_LABEL[status] || status, {pass: 'good', fail: 'bad', inconclusive: 'warn'}[status] || 'neutral'); }
const TEST_STATE = {overdue: ['Testi gecikti', 'bad'], never: ['Hiç test edilmedi', 'warn'], ok: ['Güncel', 'good'], on_demand: ['İhtiyaca göre', 'neutral'], inactive: ['Pasif', 'neutral']};
function testPill(t) { const [text, cls] = TEST_STATE[t.state] || [t.state, 'neutral']; return pill(text + (t.due_on && t.state === 'ok' ? ' · sonraki ' + fmt.date(t.due_on) : ''), cls); }
const canExecute = () => !!META.def('executions')?.can_write;
function checklist(items, selected, {label = titleOf, group} = {}) {
  const chosen = new Set(selected); const filter = h('input', {type: 'search', class: 'searchbar', placeholder: 'Süz…', 'aria-label': 'Listeyi süz'});
  const box = h('div', {class: 'choices tall'});
  const draw = () => {
    const q = filter.value.toLocaleLowerCase(TR); clear(box); let last = null;
    for (const it of items) {
      const text = label(it); if (q && !text.toLocaleLowerCase(TR).includes(q) && !chosen.has(it.id)) continue;
      if (group && group(it) !== last) { last = group(it); box.append(h('div', {class: 'choice-group', text: last})); }
      box.append(h('label', {}, h('input', {type: 'checkbox', value: it.id, checked: chosen.has(it.id), onchange: e => { if (e.target.checked) chosen.add(it.id); else chosen.delete(it.id); }}), text));
    }
    if (!box.childElementCount) box.append(h('div', {class: 'muted small', text: 'Eşleşen kayıt yok'}));
  };
  filter.addEventListener('input', debounce(draw, 150)); draw();
  return {node: h('div', {}, filter, box), value: () => [...chosen]};
}

async function editControlLinks(control, done) {
  const [processes, objectives, risks, documents] = await Promise.all(['processes', 'objectives', 'supplier_risks', 'documents'].map(r => list(r)));
  const lists = {
    clauses: clausePicker(control.clauses.map(c => ({id: c.id, standard_id: c.standard_id})), {hint: 'Kontrolün karşıladığı maddeler. Aynı kontrolü birden çok standardın maddesine eşleyin: bir kez test edilir, sonucu hepsine sayılır.'}),
    processes: checklist(processes, control.processes.map(x => x.id)), objectives: checklist(objectives, control.objectives.map(x => x.id)),
    risks: checklist(risks, control.risks.map(x => x.id)), documents: checklist(documents, control.documents.map(x => x.id))};
  Modal.open('Eşlemeler: ' + control.code, tabs([
    {key: 'clauses', label: 'Maddeler', render: () => lists.clauses.node}, {key: 'processes', label: 'Süreçler', render: () => lists.processes.node},
    {key: 'objectives', label: 'Hedefler', render: () => lists.objectives.node}, {key: 'risks', label: 'Riskler', render: () => lists.risks.node},
    {key: 'documents', label: 'Dokümanlar', render: () => lists.documents.node}]), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Eşlemeleri kaydet', async () => {
      const body = Object.fromEntries(Object.entries(lists).map(([k, l]) => [k, l.value()]));
      await api(`controls/${control.id}/links`, {method: 'POST', body}); Modal.close(); toast('Eşlemeler kaydedildi'); done();
    })], true);
}

function recordResult(control, {auditId = null, done} = {}) {
  const status = h('select', {id: 'resStatus'}, Object.entries(RESULT_LABEL).filter(([k]) => k !== 'untested').map(([v, l]) => h('option', {value: v, text: l})));
  const when = h('input', {type: 'datetime-local', id: 'resWhen', value: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)});
  const details = h('textarea', {id: 'resDetails', placeholder: 'Ne test edildi, nasıl, ne bulundu? Örnek: 25 kayıttan örneklem, 2 istisna…'});
  const sample = h('input', {type: 'number', min: 0, id: 'resSample'}); const exceptions = h('input', {type: 'number', min: 0, id: 'resExc'});
  const severity = h('select', {id: 'resSeverity'}, ['', 'low', 'medium', 'high', 'critical'].map(v => h('option', {value: v, text: v ? META.option('findings', 'severity', v) : 'Kontrol kritikliğine göre'})));
  const file = h('input', {type: 'file', id: 'resFile'});
  const evidence = (control.evidence || []).map(e => h('label', {}, h('input', {type: 'checkbox', value: e.id}), `${e.code} · ${e.title}${e.current_version ? ' (s' + e.current_version + ')' : ''}`));
  const sevField = h('label', {class: 'field', for: 'resSeverity'}, 'Bulgu önemi', h('div', {class: 'control'}, severity));
  const sync = () => { sevField.classList.toggle('hidden', status.value !== 'fail'); };
  status.addEventListener('change', sync); sync();
  Modal.open('Test sonucu kaydet: ' + control.code, h('div', {class: 'formgrid'},
    h('div', {class: 'notice wide', text: (control.expected_result ? 'Beklenen sonuç: ' + control.expected_result + ' ' : '') + 'Kayıt değiştirilemez; kontrol tanımı ve eşlemeleri bu anki haliyle dondurulur. Başarısız sonuç bulgu açar.'}),
    h('label', {class: 'field', for: 'resStatus'}, h('span', {}, 'Sonuç', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, status)),
    h('label', {class: 'field', for: 'resWhen'}, 'Kontrol zamanı', h('div', {class: 'control'}, when)),
    h('label', {class: 'field', for: 'resSample'}, 'Örnek büyüklüğü', h('div', {class: 'control'}, sample)),
    h('label', {class: 'field', for: 'resExc'}, 'İstisna sayısı', h('div', {class: 'control'}, exceptions)), sevField,
    h('label', {class: 'field wide', for: 'resDetails'}, 'Test sonucu', h('div', {class: 'control'}, details)),
    evidence.length ? h('div', {class: 'field wide'}, 'Bağlı kanıtlar (güncel sürüm kayda geçer)', h('div', {class: 'choices'}, evidence)) : null,
    h('label', {class: 'field wide', for: 'resFile'}, 'Yeni kanıt dosyası (isteğe bağlı)', h('div', {class: 'control'}, file))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Sonucu kaydet', async () => {
      if (status.value === 'fail' && !details.value.trim()) { details.focus(); throw new Error('Başarısız sonuç için test sonucunu açıklayın'); }
      const ids = evidence.map(l => l.querySelector('input')).filter(i => i.checked).map(i => Number(i.value));
      if (file.files[0]) {
        const f = file.files[0];
        const up = await api('evidence/upload', {method: 'POST', body: {title: `${control.code} test kanıtı: ${f.name}`, file_name: f.name, content_base64: await fileToBase64(f),
          controls: [control.id], ...(auditId ? {audits: [auditId]} : {})}});
        ids.push(up.id);
      }
      const body = {control_id: control.id, status: status.value, details: details.value.trim(), executed_at: new Date(when.value).toISOString(), evidence_ids: ids};
      if (auditId) body.audit_id = auditId;
      if (sample.value !== '') body.sample_size = Number(sample.value);
      if (exceptions.value !== '') body.exceptions = Number(exceptions.value);
      if (status.value === 'fail' && severity.value) body.severity = severity.value;
      const result = await api('executions', {method: 'POST', body});
      Modal.close(); toast(result.finding_id ? 'Sonuç kaydedildi; bulgu açıldı' : 'Sonuç kaydedildi'); invalidate('findings'); if (done) done();
    })], true);
}

async function runAutomation(control, done, auditId = null) {
  const result = await api(`controls/${control.id}/run`, {method: 'POST', body: auditId ? {audit_id: auditId} : {}});
  toast(result.finding_id ? (result.finding_repeated ? 'Kontrol başarısız; mevcut bulgunun tekrar sayısı arttı' : 'Kontrol başarısız; bulgu açıldı') : 'Kontrol başarılı');
  if (done) done();
}

async function showExecution(id) {
  const x = await api(`executions/${id}/context`); await loadRefs('executions');
  const prov = x.provenance || {};
  const items = Array.isArray(prov.items) ? prov.items : [];
  Modal.open(`Kontrol sonucu #${x.id} · ${x.control.code}`, h('div', {},
    h('div', {class: 'chips'}, resultPill(x.status), display('executions', 'source', x.source), x.audit_id ? h('span', {class: 'chip', text: 'Denetim: ' + titleOf(refRecord('audits', x.audit_id))}) : null), h('br'),
    kv([['Kontrol zamanı', fmt.datetime(x.executed_at)], ['Kaydeden', x.recorded_by], ['Kayıt zamanı', fmt.datetime(x.recorded_at)],
      ['Örnek / istisna', x.sample_size === null ? null : `${x.sample_size} / ${x.exceptions ?? 0}`], ['Test sonucu', x.details],
      ['Bulgu', x.finding ? h('a', {href: '#/r/findings/' + x.finding.id, text: x.finding.code, onclick: () => Modal.close()}) : null]]),
    section('Kontrol tanımı (kayıt anındaki hali)', kv([['Ad', x.definition.name], ['Sıklık', META.option('controls', 'frequency', x.definition.frequency)],
      ['Maddeler', (x.definition.clauses || []).map(c => c.code).join(', ')], ['Süreçler', (x.definition.processes || []).map(c => c.code).join(', ')],
      ['Beklenen sonuç', x.definition.expected_result]])),
    x.evidence.length ? section('Kanıt sürümleri', h('ul', {class: 'mini'}, x.evidence.map(e => h('li', {}, h('strong', {text: `${e.code} · ${e.title}`}),
      e.version ? h('span', {class: 'cell-sub mono', text: `s${e.version} · SHA-256 ${e.sha256.slice(0, 16)}…`}) : h('span', {class: 'cell-sub', text: 'Dosyasız kanıt'}),
      e.version ? btn('İndir', () => download(`evidence/${e.evidence_id}/files/${e.version}`, e.file_name), 'ghost small') : null)))) : null,
    Object.keys(prov).length ? section('Kaynak bilgisi', h('div', {},
      kv([['Kural / sorgu', prov.query || prov.rule], ['Veri toplama', prov.collection_status], ['Denetlenen', prov.checked], ['İstisna', prov.exceptions],
        ['Sonuç özeti (SHA-256)', prov.result_sha256 ? h('span', {class: 'mono', text: prov.result_sha256}) : null]]),
      items.length ? h('ul', {class: 'mini'}, items.slice(0, 20).map(i => h('li', {text: Object.values(i).filter(Boolean).join(' · ')}))) : null)) : null), [btn('Kapat', () => Modal.close(), 'secondary')], true);
}

CREATE.controls = defaults => recordForm('controls', null, {defaults: {execution_mode: 'manual', frequency: 'quarterly', ...defaults},
  extra: h('div', {class: 'notice wide', text: 'İç otomatik kural yalnızca otomatik kontrollerde seçilir: kural portal verisini sorgular ve sonucu kanıtıyla kaydeder. Kurallar: supplier.owner, supplier.reviews, supplier.risk_reviews, supplier.contracts, supplier.sla, supplier.surveys.'}),
  onsaved: r => { refreshList('controls'); openRecord('controls', r.id); }});
DETAILS.controls = async function controlDetail(id) {
  await Promise.all([list('org_units'), list('audits')]);
  let c; try { c = await api(`controls/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const lib = META.def('controls').can_write; const reload = () => { refreshList('controls'); DETAILS.controls(id); };
  const chips = (arr, res) => arr.length ? h('div', {class: 'chips'}, arr.map(x => h('button', {type: 'button', class: 'chip link', text: x.code ? `${x.code} ${x.title || x.name || ''}`.trim() : titleOf(x), onclick: () => openRecord(res, x.id)}))) : h('div', {class: 'muted small', text: 'Eşleme yok'});
  const openFindings = c.findings.filter(f => ['open', 'in_progress'].includes(f.status));
  const summary = () => h('div', {},
    h('div', {class: 'chips'}, display('controls', 'execution_mode', c.execution_mode), display('controls', 'criticality', c.criticality), display('controls', 'frequency', c.frequency),
      c.active ? null : pill('Pasif', 'neutral')), h('br'),
    h('div', {class: 'grid three'},
      metric('Son sonuç', c.latest ? RESULT_LABEL[c.latest.status] : 'Test edilmedi', c.latest ? fmt.datetime(c.latest.executed_at) : '', c.latest ? {pass: 'good', fail: 'bad', inconclusive: 'warn'}[c.latest.status] || '' : 'warn'),
      metric('Test durumu', (TEST_STATE[c.test.state] || [c.test.state])[0], c.test.due_on ? 'Sonraki: ' + fmt.date(c.test.due_on) : '', (TEST_STATE[c.test.state] || [])[1] === 'bad' ? 'bad' : ''),
      metric('Açık bulgu', fmt.num(openFindings.length, 0), `${c.actions.filter(a => !['completed', 'cancelled'].includes(a.status)).length} açık DÖF`, openFindings.length ? 'warn' : 'good')),
    c.automation_info ? h('div', {class: 'notice', text: 'İç otomatik kural: ' + c.automation_info}) : null,
    section('Tanım', kv([['Açıklama', c.description], ['Kontrol / test adımları', c.method], ['Beklenen sonuç', c.expected_result], ['Yaklaşım', display('controls', 'nature', c.nature)],
      ['Test yöntemi', display('controls', 'method_type', c.method_type)], ['Sahip', c.owner], ['Birim', display('controls', 'org_unit_id', c.org_unit_id)]])),
    section('Standart maddeleri', chips(c.clauses, 'clauses')), section('Süreçler', chips(c.processes, 'processes')),
    section('Kontrol hedefleri', chips(c.objectives, 'objectives')), section('Azalttığı riskler', chips(c.risks, 'supplier_risks')),
    section('Dokümanlar', chips(c.documents, 'documents')));
  const runs = () => c.executions.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Zaman', 'Sonuç', 'Kaynak', 'Kaydeden', 'Denetim'].map(t => h('th', {text: t})))),
    h('tbody', {}, c.executions.map(x => h('tr', {class: 'clickable', tabindex: '0', onclick: () => showExecution(x.id)}, h('td', {class: 'cell-primary', text: fmt.datetime(x.executed_at)}),
      h('td', {}, resultPill(x.status)), h('td', {}, display('executions', 'source', x.source)), h('td', {text: x.recorded_by}), h('td', {}, x.audit_id ? titleOf(refRecord('audits', x.audit_id)) : '—')))))) :
    empty('Henüz test sonucu yok', canExecute() ? 'İlk test sonucunu kaydedin.' : '');
  const findingsTab = () => h('div', {}, c.findings.length ? h('ul', {class: 'mini'}, c.findings.map(f => h('li', {class: 'link', tabindex: '0', onclick: () => openRecord('findings', f.id)},
    h('strong', {text: f.code + ' · ' + f.title}), h('div', {class: 'chips'}, display('findings', 'severity', f.severity), display('findings', 'status', f.status), f.recurrence > 1 ? pill(f.recurrence + ' kez tekrarladı', 'warn') : null))))
    : empty('Bulgu yok', ''), c.actions.length ? section('Düzeltici faaliyetler', h('ul', {class: 'mini'}, c.actions.map(a => h('li', {class: 'link', onclick: () => openRecord('grc_actions', a.id)},
      h('strong', {text: a.code + ' · ' + a.title}), h('span', {class: 'cell-sub', text: `${a.owner} · ${fmt.date(a.due_date)}`}), display('grc_actions', 'status', a.status))))) : null);
  const evidenceTab = () => h('div', {}, c.evidence.length ? h('ul', {class: 'mini'}, c.evidence.map(e => h('li', {class: 'link', onclick: () => openRecord('evidence', e.id)},
    h('strong', {text: e.code + ' · ' + e.title}), h('div', {class: 'chips'}, display('evidence', 'status', e.status), e.current_version ? h('span', {class: 'chip', text: 's' + e.current_version}) : pill('Dosyasız', 'neutral'),
      e.expires_at ? h('span', {class: 'chip', text: 'Geçerlilik ' + fmt.date(e.expires_at)}) : null)))) : empty('Kanıt yok', ''),
    META.def('evidence')?.can_write ? h('p', {}, btn('+ Kanıt yükle', () => createRecord('evidence', {controls: [c.id]}), 'secondary small')) : null);
  Drawer.open(c.code + ' · ' + c.name, tabs([{key: 'summary', label: 'Özet', render: summary}, {key: 'runs', label: 'Sonuçlar', count: c.executions.length, render: runs},
    {key: 'findings', label: 'Bulgular', count: openFindings.length, render: findingsTab}, {key: 'evidence', label: 'Kanıtlar', count: c.evidence.length, render: evidenceTab}]), [
    lib ? btn('Eşlemeler', () => editControlLinks(c, reload), 'secondary') : null,
    lib ? btn('Düzenle', () => recordForm('controls', c, {onsaved: reload}), 'secondary') : null,
    canExecute() && c.automation && c.active ? btn('Şimdi çalıştır', () => runAutomation(c, reload), c.execution_mode === 'automatic' ? '' : 'secondary') : null,
    canExecute() && c.active && !c.automation ? btn('Sonuç kaydet', () => recordResult(c, {done: reload})) : null], 'Kontrol');
};
EXTRA_ACTIONS.executions = x => [btn('Ayrıntı', () => showExecution(x.id), 'secondary')];
DETAILS.executions = id => showExecution(id);

// kanıt
CREATE.evidence = defaults => {
  const links = defaults.controls ? {controls: defaults.controls} : {};
  const file = h('input', {type: 'file', id: 'evFile'});
  return recordForm('evidence', null, {skip: ['code', 'source', 'status'], defaults: Object.fromEntries(Object.entries(defaults).filter(([k]) => k !== 'controls')),
    extra: h('label', {class: 'field wide', for: 'evFile'}, 'Dosya (PDF, Office, resim, metin, ZIP; en çok 12 MB)', h('div', {class: 'control'}, file),
      h('span', {class: 'muted small', text: 'Dosya seçerseniz kayıtla birlikte ilk sürüm yüklenir ve SHA-256 özeti saklanır.'})),
    title: 'Yeni kanıt', onsaved: async r => {
      const id = r.id;
      if (file.files[0]) {      // kayıt açıldı; dosya ilk sürüm olarak eklenir (SHA-256 sunucuda hesaplanır)
        const f = file.files[0];
        await api(`evidence/${id}/files`, {method: 'POST', body: {file_name: f.name, content_base64: await fileToBase64(f)}});
      }
      if (links.controls) await api(`evidence/${id}/links`, {method: 'POST', body: links});
      refreshList('evidence'); openRecord('evidence', id);
    }});
};
DETAILS.evidence = async function evidenceDetail(id) {
  await Promise.all([list('suppliers'), list('org_units')]);
  let e; try { e = await api(`evidence/${id}/context`); } catch (err) { toast(err.message, false); return; }
  const can = META.def('evidence').can_write; const reload = () => { refreshList('evidence'); DETAILS.evidence(id); };
  const upload = h('input', {type: 'file', id: 'evNew', class: 'hidden', onchange: async () => {
    const f = upload.files[0]; if (!f) return;
    try { const r = await api(`evidence/${id}/files`, {method: 'POST', body: {file_name: f.name, content_base64: await fileToBase64(f)}}); toast(`Sürüm ${r.version} yüklendi`); reload(); }
    catch (err) { toast(err.message, false); }
  }});
  const body = h('div', {},
    h('div', {class: 'chips'}, display('evidence', 'status', e.status), display('evidence', 'confidentiality', e.confidentiality), display('evidence', 'source', e.source),
      e.expiring ? pill('Geçerlilik sonu yaklaşıyor', 'warn') : null), h('br'),
    section('Bilgiler', kv([['Açıklama', e.description], ['Dönem', e.period_start || e.period_end ? `${fmt.date(e.period_start)} – ${fmt.date(e.period_end)}` : null],
      ['Geçerlilik sonu', fmt.date(e.expires_at)], ['Tedarikçi', display('evidence', 'supplier_id', e.supplier_id)], ['Birim', display('evidence', 'org_unit_id', e.org_unit_id)],
      ['Referans', extLink(e.reference_url)], ['Oluşturan', e.created_by]])),
    section(`Dosya sürümleri (${e.files.length})`, e.files.length ? h('ul', {class: 'mini'}, e.files.map(f => h('li', {class: 'file-row'},
      h('div', {}, h('strong', {text: `Sürüm ${f.version} · ${f.file_name}`}), h('span', {class: 'cell-sub', text: `${fmt.num(f.file_size / 1024, 1)} KB · ${f.uploaded_by} · ${fmt.datetime(f.uploaded_at)}`}),
        h('span', {class: 'cell-sub mono', title: f.sha256, text: 'SHA-256 ' + f.sha256})),
      btn('İndir', () => download(`evidence/${id}/files/${f.version}`, f.file_name), 'secondary small')))) : h('div', {class: 'muted small', text: 'Dosya yok; yalnızca referans bağlantısı'}),
      can && e.status !== 'archived' ? h('span', {}, upload, btn('+ Yeni sürüm', () => upload.click(), 'ghost small')) : null),
    section('Bağlı kontroller', e.controls.length ? h('div', {class: 'chips'}, e.controls.map(x => h('button', {type: 'button', class: 'chip link', text: x.code, onclick: () => openRecord('controls', x.id)}))) : h('div', {class: 'muted small', text: 'Bağlantı yok'}),
      can ? btn('Düzenle', () => editEvidenceLinks(e, reload), 'ghost small') : null),
    section('Denetimler', e.audits.length ? h('div', {class: 'chips'}, e.audits.map(x => h('button', {type: 'button', class: 'chip link', text: x.code + ' ' + x.name, onclick: () => Router.go('audit/' + x.id)}))) : h('div', {class: 'muted small', text: 'Bağlantı yok'})),
    section(`Kullanıldığı test sonuçları (${e.executions.length})`, e.executions.length ? h('ul', {class: 'mini'}, e.executions.map(x => h('li', {class: 'link', onclick: () => showExecution(x.id)},
      h('strong', {text: `${x.control_code} · ${fmt.datetime(x.executed_at)}`}), ' ', resultPill(x.status), x.version ? h('span', {class: 'cell-sub', text: 'Sürüm ' + x.version}) : null))) : h('div', {class: 'muted small', text: 'Henüz bir teste bağlanmadı'})));
  Drawer.open(e.code + ' · ' + e.title, body, [typeof evidenceSuggestions === 'function' && can ? btn('Kontrol önerisi', () => evidenceSuggestions(e, reload), 'ghost', {title: 'Bu kanıtın hangi kontrollere uygun olduğunu öner'}) : null,
    can ? btn('Düzenle', () => recordForm('evidence', e, {skip: ['code', 'source'], onsaved: reload})) : null], 'Kanıt');
};
async function editEvidenceLinks(e, done) {
  const [controls, audits] = await Promise.all([list('controls'), list('audits')]);
  const c = checklist(controls, e.controls.map(x => x.id)); const a = checklist(audits, e.audits.map(x => x.id));
  Modal.open('Kanıt bağlantıları: ' + e.code, tabs([{key: 'c', label: 'Kontroller', render: () => c.node}, {key: 'a', label: 'Denetimler', render: () => a.node}]), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => { await api(`evidence/${e.id}/links`, {method: 'POST', body: {controls: c.value(), audits: a.value()}}); Modal.close(); toast('Bağlantılar kaydedildi'); done(); })], true);
}

// bulgu ve DÖF
function transition(title, note, field, okText, apply, {required = true} = {}) {
  const text = h('textarea', {id: 'trNote'});
  Modal.open(title, h('div', {}, h('p', {class: 'intro', text: note}), h('label', {class: 'field', for: 'trNote'}, h('span', {}, field, required ? h('span', {class: 'req', text: ' *'}) : null), h('div', {class: 'control'}, text))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn(okText, async () => { if (required && !text.value.trim()) { text.focus(); throw new Error(field + ' gerekli'); } await apply(text.value.trim()); Modal.close(); })]);
}
DETAILS.findings = async function findingDetail(id) {
  await Promise.all(['controls', 'audits', 'suppliers', 'processes', 'supplier_risks', 'companies'].map(r => list(r).catch(() => [])));
  let f; try { f = await api(`findings/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const can = META.def('findings').can_write; const reload = () => { refreshList('findings'); DETAILS.findings(id); };
  const open = ['open', 'in_progress'].includes(f.status);
  const patch = body => api(`findings/${id}`, {method: 'PATCH', body}).then(() => { toast('Kaydedildi'); reload(); });
  const pendingActions = f.actions.filter(a => !['completed', 'cancelled'].includes(a.status)).length;
  const body = h('div', {},
    h('div', {class: 'chips'}, display('findings', 'severity', f.severity), display('findings', 'status', f.status), f.recurrence > 1 ? pill(`${f.recurrence} kez tekrarladı`, 'warn') : null,
      open && f.due_date && f.due_date < today() ? pill('Hedef tarih geçti', 'bad') : null), h('br'),
    section('Bulgu', kv([['Açıklama', f.description], ['Kök neden', f.root_cause], ['Sahip', f.owner], ['Hedef tarih', fmt.date(f.due_date)],
      ['Kontrol', f.control ? h('a', {href: '#/r/controls/' + f.control.id, text: f.control.code + ' · ' + f.control.name}) : null],
      ['Denetim', f.audit_id ? h('a', {href: '#/audit/' + f.audit_id, text: titleOf(refRecord('audits', f.audit_id))}) : null],
      ['Tedarikçi', display('findings', 'supplier_id', f.supplier_id)], ['Kaynak', display('findings', 'source', f.source)],
      ['Standart maddesi', f.clause ? h('a', {href: '#', text: `${f.clause.standard_code} ${f.clause.code} · ${f.clause.title}`, onclick: e => { e.preventDefault(); DETAILS.clauses(f.clause.id); }}) : null],
      ['Süreç', f.process_id ? h('a', {href: '#/r/processes/' + f.process_id, text: titleOf(refRecord('processes', f.process_id)) || '#' + f.process_id}) : null],
      ['İlgili risk', f.risk_id ? h('a', {href: '#/r/supplier_risks/' + f.risk_id, text: titleOf(refRecord('supplier_risks', f.risk_id)) || '#' + f.risk_id}) : null],
      ['Şirket', display('findings', 'company_id', f.company_id)],
      ['Son görülme', fmt.datetime(f.last_seen_at)], ['Kapanış / kabul notu', f.closure_note]])),
    typeof responseSection === 'function' ? responseSection(f, reload) : null,
    typeof impactSection === 'function' ? impactSection(f.impact) : null,
    f.execution ? section('Kaynak test sonucu', h('div', {}, h('div', {class: 'chips'}, resultPill(f.execution.status), display('executions', 'source', f.execution.source), h('span', {class: 'chip', text: fmt.datetime(f.execution.executed_at)})),
      btn('Test ayrıntısı', () => showExecution(f.execution.id), 'ghost small'))) : null,
    section(`Düzeltici faaliyetler (${f.actions.length})`, f.actions.length ? h('ul', {class: 'mini'}, f.actions.map(a => h('li', {class: 'link', onclick: () => openRecord('grc_actions', a.id)},
      h('strong', {text: a.code + ' · ' + a.title}), h('span', {class: 'cell-sub', text: `${a.owner} · ${fmt.date(a.due_date)}`}), h('div', {class: 'chips'}, display('grc_actions', 'priority', a.priority), display('grc_actions', 'status', a.status)))))
      : h('div', {class: 'muted small', text: open ? 'Henüz faaliyet yok. Bulguyu gidermek için DÖF açın.' : 'Faaliyet yok'}),
      open && META.def('grc_actions')?.can_write ? btn('+ DÖF', () => createRecord('grc_actions', {finding_id: id, owner: f.owner || '', due_date: f.due_date || today(30)}), 'ghost small') : null));
  const buttons = !can ? [] : open ? [
    btn('Düzenle', () => recordForm('findings', f, {skip: ['code', 'status', 'closure_note'], onsaved: reload}), 'secondary'),
    f.status === 'open' ? btn('Çalışmaya başla', () => patch({status: 'in_progress'}), 'secondary') : null,
    S.me.role === 'ADMIN' ? btn('Riski kabul et', () => transition('Bulgu riskini kabul et: ' + f.code, 'Kabul, bulgunun giderilmeyeceği anlamına gelir; gerekçe değiştirilemez denetim izine yazılır.', 'Kabul gerekçesi', 'Kabul et', note => patch({status: 'accepted', closure_note: note})), 'secondary') : null,
    btn('Kapat', () => pendingActions ? toast(`${pendingActions} açık düzeltici faaliyet var; önce tamamlanmalı`, false) :
      transition('Bulguyu kapat: ' + f.code, 'Kapanış, düzeltici faaliyetlerin etkinliğinin doğrulandığını gösterir.', 'Kapanış notu', 'Kapat', note => patch({status: 'closed', closure_note: note})))] :
    [btn('Yeniden aç', () => transition('Bulguyu yeniden aç: ' + f.code, 'Yeniden açma gerekçesi kapanış notunun yerine yazılır.', 'Gerekçe', 'Yeniden aç', note => patch({status: 'open', closure_note: note})), 'secondary')];
  Drawer.open(f.code + ' · ' + f.title, body, buttons, 'Bulgu');
};
CREATE.findings = defaults => recordForm('findings', null, {skip: ['code', 'status', 'closure_note'], defaults: {severity: 'medium', due_date: today(60), ...defaults},
  onsaved: r => { refreshList('findings'); openRecord('findings', r.id); }});
CREATE.grc_actions = defaults => recordForm('grc_actions', null, {skip: ['code', 'status', 'resolution', 'verification_note'], defaults: {priority: 'medium', ...defaults},
  extra: h('div', {class: 'notice wide', text: 'Faaliyet tamamlandığında sahibi "Doğrulamaya gönder" der; etkinliği sahibinden farklı bir Yönetici veya Denetçi doğrular.'}),
  onsaved: r => { refreshList('grc_actions'); if (defaults.finding_id) DETAILS.findings(defaults.finding_id); else openRecord('grc_actions', r.id); }});
DETAILS.grc_actions = async function actionDetail(id) {
  await Promise.all([list('findings'), list('controls'), list('org_units')]);
  let a; try { a = await api(`grc_actions/${id}`); } catch (e) { toast(e.message, false); return; }
  const can = META.def('grc_actions').can_write; const assurance = ['ADMIN', 'AUDITOR'].includes(S.me.role);
  const reload = () => { refreshList('grc_actions'); DETAILS.grc_actions(id); };
  const patch = body => api(`grc_actions/${id}`, {method: 'PATCH', body}).then(() => { toast('Kaydedildi'); reload(); });
  const done = ['completed', 'cancelled'].includes(a.status);
  const steps = ['open', 'in_progress', 'validation', 'completed'];
  const body = h('div', {},
    h('div', {class: 'steps'}, steps.map((st, i) => h('span', {class: 'step' + (st === a.status ? ' on' : steps.indexOf(st) < steps.indexOf(a.status) || a.status === 'completed' ? ' done' : '')},
      h('b', {text: a.status === 'completed' || steps.indexOf(st) < steps.indexOf(a.status) ? '✓' : String(i + 1)}), META.option('grc_actions', 'status', st)))),
    a.status === 'cancelled' ? h('div', {class: 'notice', text: 'Faaliyet iptal edildi.'}) : null,
    a.status !== 'completed' && a.due_date < today() && !done ? h('div', {class: 'notice bad', text: 'Hedef tarih geçti.'}) : null,
    section('Faaliyet', kv([['Açıklama', a.description], ['Sahip', a.owner], ['Birim', display('grc_actions', 'org_unit_id', a.org_unit_id)], ['Hedef tarih', fmt.date(a.due_date)],
      ['Öncelik', display('grc_actions', 'priority', a.priority)], ['Bulgu', a.finding_id ? h('a', {href: '#/r/findings/' + a.finding_id, text: titleOf(refRecord('findings', a.finding_id))}) : null],
      ['Kontrol', a.control_id ? h('a', {href: '#/r/controls/' + a.control_id, text: titleOf(refRecord('controls', a.control_id))}) : null]])),
    section('Sonuç ve doğrulama', kv([['Yapılanlar', a.resolution], ['Doğrulayan', a.verified_by], ['Doğrulama notu', a.verification_note], ['Kapanış', fmt.datetime(a.closed_at)]])),
    typeof serviceNowSection === 'function' ? serviceNowSection(a, reload) : null);
  const buttons = !can || done ? [] : [
    btn('Düzenle', () => recordForm('grc_actions', a, {skip: ['code', 'status', 'verification_note'], onsaved: reload}), 'secondary'),
    a.status === 'open' ? btn('Başla', () => patch({status: 'in_progress'}), 'secondary') : null,
    assurance ? btn('İptal et', () => transition('Faaliyeti iptal et: ' + a.code, 'İptal gerekçesi doğrulama notuna yazılır.', 'İptal gerekçesi', 'İptal et', note => patch({status: 'cancelled', verification_note: note})), 'secondary') : null,
    ['open', 'in_progress'].includes(a.status) ? btn('Doğrulamaya gönder', () => transition('Doğrulamaya gönder: ' + a.code, 'Ne yapıldığını ve kanıtın nerede olduğunu yazın.', 'Yapılanlar', 'Gönder', note => patch({status: 'validation', resolution: note}))) : null,
    a.status === 'validation' && assurance && S.me.username !== a.owner ? btn('Etkinliği doğrula', () => transition('Etkinliği doğrula: ' + a.code, 'Faaliyetin bulguyu gerçekten giderdiğini nasıl doğruladınız? (yeniden test, örneklem, gözlem)', 'Doğrulama notu', 'Doğrula ve tamamla', note => patch({status: 'completed', verification_note: note}))) : null,
    a.status === 'validation' && assurance && S.me.username === a.owner ? h('span', {class: 'muted small', text: 'Kendi faaliyetinizi doğrulayamazsınız'}) : null];
  Drawer.open(a.code + ' · ' + a.title, body, buttons, 'Düzeltici faaliyet');
};

// risk kataloğundan risk
EXTRA_ACTIONS.risk_catalog = r => META.def('supplier_risks')?.can_write ? [btn('Bu senaryodan risk aç', () => createRecord('supplier_risks', {catalog_id: r.id, title: r.title,
  category: r.category, cause: r.cause, risk_event: r.risk_event, consequence: r.consequence, likelihood: r.likelihood, impact: r.impact}), 'secondary')] : [];

// denetim
const AUDIT_FIELDS = ['name', 'kind', 'supplier_id', 'audit_objective', 'scope', 'planned_start', 'planned_end', 'lead_auditor', 'auditors', 'auditees'];
async function auditForm(audit = null, defaults = {}) {
  const [processes] = await Promise.all([list('processes'), list('standards')]); await loadRefs('audits');
  const form = h('form', {class: 'formgrid', novalidate: true}, h('div', {class: 'notice bad wide form-error hidden', role: 'alert'}));
  const fields = AUDIT_FIELDS.map(n => META.field('audits', n));
  for (const f of fields) form.append(inputFor('audits', f, audit ? audit[f.name] : defaults[f.name]));
  const clauseList = clausePicker(audit ? audit.clauses.map(c => ({id: c.id, standard_id: c.standard_id})) : [],
    {hint: 'Birden çok standart seçebilirsiniz (entegre denetim). Ortak kontroller tek kez test edilir; ilgili maddeler test planında birlikte gösterilir.'});
  const processList = checklist(processes.filter(p => p.active !== 0), audit ? (audit.processes || []).map(p => p.id) : [], {label: p => `${p.code} ${p.name}`,
    group: p => ({management: 'Yönetim süreçleri', core: 'Ana süreçler', support: 'Destek süreçleri'}[p.process_type] || '')});
  form.append(h('div', {class: 'field wide'}, 'Kapsam: standart maddeleri', clauseList.node),
    h('div', {class: 'field wide'}, 'Denetlenen süreçler (ISO 9001 9.2 denetim programı)', processList.node));
  const save = async () => {
    const {data, errors} = readForm(form, 'audits', fields);
    if (Object.keys(errors).length) { showErrors(form, errors, 'Eksik veya hatalı alanları düzeltin'); return; }
    const clauseIds = clauseList.value(); const stdIds = clauseList.standards();
    let body;
    if (audit) { body = {}; for (const [k, v] of Object.entries(data)) if ((audit[k] ?? null) !== v) body[k] = v; body.standard_ids = stdIds; body.clause_ids = clauseIds; body.process_ids = processList.value(); body.expected_revision = audit.revision; }
    else { body = Object.fromEntries(Object.entries(data).filter(([, v]) => v !== null)); body.standard_ids = stdIds; body.clause_ids = clauseIds; body.process_ids = processList.value(); }
    try {
      const r = audit ? await api(`audits/${audit.id}`, {method: 'PATCH', body}) : await api('audits', {method: 'POST', body});
      invalidate('audits'); toast(audit ? 'Denetim kaydedildi' : 'Denetim oluşturuldu'); Drawer.close(); Router.go('audit/' + r.id);
    } catch (e) { showErrors(form, {}, e.message); throw e; }
  };
  Drawer.open(audit ? 'Düzenle: ' + audit.code : 'Yeni denetim', form, [btn('Vazgeç', () => Drawer.close(), 'secondary'), btn(audit ? 'Kaydet' : 'Oluştur', save)], 'Denetim');
}
CREATE.audits = defaults => auditForm(null, defaults);
DETAILS.audits = id => Router.go('audit/' + id);
// denetim çalışma alanı: grc.js (PAGES.audit)

// uyum panosu
async function compliancePage(params) {
  const [standards, processes, audits] = await Promise.all([list('standards'), list('processes'), list('audits')]);
  const filter = {standard_id: params.get('standard_id') || '', process_id: params.get('process_id') || '', audit_id: params.get('audit_id') || ''};
  const q = new URLSearchParams(Object.entries(filter).filter(([, v]) => v));
  const [o, d] = await Promise.all([api('grc/overview'), api('grc/compliance?' + q)]);
  const go = (k, v) => { const n = new URLSearchParams(Object.entries({...filter, [k]: v}).filter(([, x]) => x)); Router.go('compliance' + (n.toString() ? '?' + n : '')); };
  setPage('Uyum Panosu', 'Kontrol testlerine dayalı ön gösterge: kapsama, test tamamlanma ve başarı. ' + d.disclaimer,
    [canExecute() ? btn('Otomatik kontrolleri çalıştır', async () => { const r = await api('grc/run-automatic', {method: 'POST', body: {}}); toast(`${r.results.length} otomatik kontrol çalıştı`); render(); }, 'secondary') : null]);
  const sev = Object.fromEntries(o.findings_by_severity.map(x => [x.key, x.count]));
  const cards = h('div', {class: 'cards'},
    metric('Aktif kontrol', fmt.num(o.controls.total_controls, 0), `${o.controls.counts.untested} hiç test edilmedi`, '', () => Router.go('r/controls?active=1')),
    metric('Testi geciken', fmt.num(o.controls.overdue_tests, 0), 'Sıklığına göre zamanı geçmiş veya hiç test edilmemiş', o.controls.overdue_tests ? 'warn' : 'good'),
    metric('Açık bulgu', fmt.num(o.findings_open, 0), `${sev.critical || 0} kritik · ${sev.high || 0} yüksek · ${o.findings_overdue} gecikmiş`, o.findings_open ? (sev.critical || sev.high ? 'bad' : 'warn') : 'good', () => Router.go('r/findings')),
    metric('DÖF', fmt.num(o.actions_overdue, 0) + ' gecikmiş', `${o.actions_validation} doğrulama bekliyor`, o.actions_overdue ? 'bad' : 'good', () => Router.go('r/grc_actions')));
  const cards2 = h('div', {class: 'cards'},
    metric('Süresi dolan kanıt', fmt.num(o.evidence_expiring, 0), 'Geçerlilik sonu yakın veya geçmiş', o.evidence_expiring ? 'warn' : 'good', () => Router.go(`r/evidence?expires_at__lte=${today(30)}&status=current`)),
    metric('Gözden geçirilecek doküman', fmt.num(o.documents_review_due, 0), 'Gözden geçirme tarihi geldi', o.documents_review_due ? 'warn' : 'good', () => Router.go(`r/documents?status=active&review_date__lte=${today()}`)),
    metric('Süren denetim', fmt.num(o.audits_active.filter(x => x.status === 'in_progress').length, 0), `${o.audits_active.filter(x => x.status === 'planned').length} planlı`, '', () => Router.go('r/audits')),
    metric('Başarı oranı', fmt.pct(o.controls.pass_pct), `Sonuçlanan ${o.controls.completed} testte`, o.controls.pass_pct === null ? '' : o.controls.pass_pct >= 85 ? 'good' : o.controls.pass_pct >= 60 ? 'warn' : 'bad'));
  const stdTable = o.standards.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Standart', 'Kontrol', 'Madde kapsaması', 'Test tamamlanma', 'Başarı', ''].map((t, i) => h('th', {class: i && i < 5 ? 'num' : '', text: t})))),
    h('tbody', {}, o.standards.map(st => h('tr', {class: 'clickable', onclick: () => go('standard_id', String(st.id))}, h('td', {class: 'cell-primary'}, `${st.code} ${st.version || ''}`, h('span', {class: 'cell-sub', text: st.name})),
      h('td', {class: 'num', text: st.controls}), h('td', {class: 'num'}, fmt.pct(st.framework_coverage_pct), h('span', {class: 'cell-sub', text: `${st.mapped_clauses ?? 0} / ${st.clause_count ?? 0} madde`})),
      h('td', {class: 'num', text: fmt.pct(st.completion_pct)}), h('td', {class: 'num', text: fmt.pct(st.pass_pct)}), h('td', {}, progressBar(st.completion_pct)))))))
    : empty('Standart yok', 'Çerçeve menüsünden standart ve maddeleri ekleyin.');
  const sel = (name, items, label, all) => h('select', {class: 'compact', 'aria-label': label, onchange: e => go(name, e.target.value)}, h('option', {value: '', text: all}),
    items.map(i => h('option', {value: i.id, text: titleOf(i) + (i.version ? ' ' + i.version : ''), selected: String(i.id) === filter[name]})));
  const filters = h('div', {class: 'filters'}, sel('standard_id', standards, 'Standart', 'Tüm standartlar'), sel('process_id', processes, 'Süreç', 'Tüm süreçler'), sel('audit_id', audits, 'Denetim', 'Denetim seçilmedi (son sonuçlar)'));
  const gauges = h('div', {class: 'grid four'},
    gauge(d.completion_pct, 'Test tamamlanma', {suffix: '%', good: 90, mid: 60, sub: `${d.completed} / ${d.total_controls} kontrol`}),
    gauge(d.pass_pct, 'Başarı oranı', {suffix: '%', good: 85, mid: 60, sub: 'Sonuçlanan testlerde'}),
    gauge(d.indicative_pct, 'Gösterge', {suffix: '%', good: 85, mid: 60, sub: 'Başarılı / tüm kontroller'}),
    gauge(d.framework_coverage_pct, 'Madde kapsaması', {suffix: '%', good: 90, mid: 60, sub: d.clause_count === null ? 'Standart veya denetim seçin' : `${d.mapped_clauses} / ${d.clause_count} madde`}));
  const ctlRows = d.controls.map(c => h('tr', {class: 'clickable', tabindex: '0', onclick: () => Router.go('r/controls/' + c.id)}, h('td', {class: 'cell-primary', text: c.code}), h('td', {text: c.name}),
    h('td', {}, display('controls', 'criticality', c.criticality)), h('td', {}, resultPill(c.status)), h('td', {text: c.executed_at ? fmt.datetime(c.executed_at) : '—'}), h('td', {}, testPill(c.test))));
  content(cards, cards2,
    h('div', {class: 'panel'}, h('h3', {text: 'Standartlara göre'}), stdTable),
    h('div', {class: 'panel'}, h('div', {class: 'toolbar'}, h('h3', {text: d.evaluation_type}), filters), gauges,
      h('div', {class: 'chips'}, ['pass', 'fail', 'inconclusive', 'not_applicable', 'untested'].map(k => h('span', {class: 'chip', text: `${RESULT_LABEL[k]}: ${d.counts[k]}`}))), h('br'),
      d.controls.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kod', 'Kontrol', 'Kritiklik', 'Son sonuç', 'Test zamanı', 'Test durumu'].map(t => h('th', {text: t})))), h('tbody', {}, ctlRows)))
        : empty('Bu filtrede kontrol yok', '')),
    h('div', {class: 'notice', text: d.disclaimer}));
}

async function render() {
  // Yavaş ağda önceki ekranın geç gelen yanıtı yeni ekranı ezebilir: her çizim bir sıra numarası alır;
  // eski bir çizim, en yenisi bittikten sonra biterse güncel ekran yeniden çizilir.
  const mine = ++S.renderSeq;
  try { await renderPage(); } finally {
    if (mine !== S.renderSeq) {                         // eski çizim: ekranı ezmiş olabilir
      if (S.renderDone === S.renderSeq) render(); else S.renderAgain = true;
    } else {
      S.renderDone = mine;
      if (S.renderAgain) { S.renderAgain = false; render(); }
    }
  }
}
async function renderPage() {
  const {parts, params} = Router.parse(); const key = parts[0] || 'home';
  if (Modal.isOpen()) Modal.close();
  navigation(); window.scrollTo(0, 0); document.body.classList.remove('nav-open');
  const keepDrawer = key === 'r' && parts[2]; if (!keepDrawer && Drawer.isOpen()) Drawer.close();
  try {
    if (PAGES[key]) await PAGES[key](parts, params);
    else if (key === 'r' && parts[1]) { await listView(parts[1], {params}); if (parts[2]) openRecord(parts[1], Number(parts[2])); }
    else if (key === 'templates' && parts[1]) await templateBuilder(Number(parts[1]));
    else if (key === 'surveys' && parts[1]) await campaignPage(Number(parts[1]), params.get('tab'));
    else if (key === 'my-surveys') await mySurveys();
    else if (key === 'schedule') await schedulePage(params);
    else if (key === 'respond' && parts[1]) await respond(Number(parts[1]));
    else if (key === 'transfer') await transferPage();
    else if (key === 'users') await usersPage();
    else if (key === 'compliance') await compliancePage(params);
    else { setPage('Sayfa bulunamadı'); content(empty('Bu adres bulunamadı', '', h('a', {class: 'btn', href: '#/', text: 'Genel bakışa dön'}))); }
  } catch (e) {
    setPage('Bir sorun oluştu'); content(h('div', {class: 'notice bad', text: e.message}), h('a', {class: 'btn secondary', href: '#/', text: 'Genel bakışa dön'}));
  }
  $('content').focus({preventScroll: true});
}
async function start() {
  setupResize();
  $('closeDetail').addEventListener('click', () => Drawer.close());
  $('modalClose').addEventListener('click', () => Modal.close());
  $('modalBack').addEventListener('click', e => { if (e.target === $('modalBack')) Modal.close(); });
  $('signout').addEventListener('click', async () => {
    if (S.meta?.auth_mode === 'dev') { toast('Geliştirme modunda oturum kapatılmaz'); return; }
    try { await api('/api/logout', {method: 'POST', body: {}}); } finally { location.assign('/login'); }
  });
  $('menuToggle').addEventListener('click', () => document.body.classList.toggle('nav-open'));
  $('searchOpen').addEventListener('click', () => typeof openPalette === 'function' && openPalette());
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && typeof openPalette === 'function') { e.preventDefault(); openPalette(); return; }
    if (e.key === 'Escape') { if (Modal.isOpen()) Modal.close(); else if (Drawer.isOpen()) Drawer.close(); else document.body.classList.remove('nav-open'); }
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && $('tableSearch') && !$('tableSearch').disabled) { e.preventDefault(); $('tableSearch').focus(); }
  });
  try { S.meta = await api('metadata'); } catch (e) { content(h('div', {class: 'notice bad', text: e.message})); return; }
  S.me = S.meta.user;
  append(clear($('identity')), [h('strong', {text: S.me.display_name || S.me.username}), h('span', {class: 'role', text: S.me.role_label})]);
  $('avatar').textContent = (S.me.display_name || S.me.username).split(/[\s.]+/).filter(Boolean).slice(0, 2).map(w => w[0].toLocaleUpperCase(TR)).join('');
  $('brandName').textContent = S.meta.app_name || 'GRC Platformu';
  if (S.meta.modules.includes('surveys')) api('my/surveys').then(items => { S.mySurveys = items.filter(i => i.open && i.state !== 'submitted').length; navigation(); }).catch(() => {});
  if (S.meta.modules.includes('insights') && S.me.auth_type !== 'api_key') api('my-work').then(w => { S.myWork = w.total; navigation(); }).catch(() => {});
  window.addEventListener('hashchange', render);
  render();
}
document.addEventListener('DOMContentLoaded', start);

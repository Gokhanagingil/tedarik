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
const S = {meta: null, me: null, cache: {}, filters: {}, mySurveys: 0};
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
const FLAGS = new Set(['active', 'required', 'is_primary', 'anonymous', 'met', 'selected', 'disabled']);
const LONG = new Set(['value_json', 'description', 'cause', 'risk_event', 'consequence', 'treatment', 'note', 'comment', 'intro', 'outro',
  'help', 'rationale', 'resolution', 'decision_rationale', 'exception_rationale', 'text']);
const GOOD = new Set(['active', 'completed', 'published', 'answered', 'submitted', 'done', 'met']);
const BAD = new Set(['critical', 'terminated', 'expired', 'suspended', 'sla_breach', 'incident', 'high', 'cancelled']);
const WARN = new Set(['open', 'in_treatment', 'pending', 'draft', 'expiring', 'medium', 'offboarding', 'prospect', 'important',
  'in_progress', 'validation', 'ending', 'planned', 'escalation', 'delivery_delay']);
const PILLS = new Set(['status', 'tier', 'severity', 'criticality', 'priority', 'event_type', 'segment', 'beneficiary', 'kind',
  'purpose', 'subject', 'audience', 'category', 'response_strategy', 'source', 'raci', 'role']);
function tone(value) { return GOOD.has(value) ? 'good' : BAD.has(value) ? 'bad' : WARN.has(value) ? 'warn' : 'neutral'; }
function roleLabel(code) { return (S.meta.roles.find(r => r.value === code) || {}).label || code; }
function pill(text, cls = 'neutral') { return h('span', {class: 'pill ' + cls, text}); }
function refRecord(res, id) { return (S.cache[res] || []).find(r => r.id === id); }
function titleOf(r) { if (!r) return ''; return [r.code, r.name || r.title || r.username].filter(Boolean).join(' — ') || ('#' + r.id); }
function display(res, name, value) {
  if (value === null || value === undefined || value === '') return h('span', {class: 'muted', text: '—'});
  const f = META.field(res, name);
  if (!f) return String(value);
  if (f.ref) { const r = refRecord(f.ref, value); return r ? titleOf(r) : '#' + value; }
  if (f.options) { const label = META.option(res, name, value); return PILLS.has(name) ? pill(label, tone(value)) : label; }
  if (FLAGS.has(name)) return value ? pill('Evet', name === 'disabled' ? 'bad' : 'good') : pill('Hayır', 'neutral');
  if (f.kind === 'DATE') return fmt.date(value);
  if (f.kind === 'TIMESTAMP') return fmt.datetime(value);
  if (f.kind === 'DECIMAL') return fmt.money(value);
  if (f.kind === 'REAL') return fmt.num(value, 2);
  const text = String(value);
  return text.length > 160 ? text.slice(0, 157) + '…' : text;
}
async function loadRefs(res, fields) {
  const refs = new Set((META.def(res)?.fields || []).filter(f => f.ref && (!fields || fields.includes(f.name))).map(f => f.ref));
  await Promise.all([...refs].map(r => list(r).catch(() => [])));
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
    g.append(s('rect', {x: labelW, y: y + 3, width: (width - labelW - 60), height: 16, rx: 5, fill: '#eef2f7'}));
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
  svg.append(s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 6, stroke: '#e7edf5'}));
  let offset = 25;
  data.forEach((item, i) => {
    const part = 100 * item.value / total;
    svg.append(s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 6, 'stroke-dasharray': `${part} ${100 - part}`,
      'stroke-dashoffset': offset, stroke: PALETTE[(item.color ?? i) % 6]}));
    offset -= part;
  });
  svg.append(s('text', {x: 21, y: 24, 'text-anchor': 'middle', 'font-size': 8, 'font-weight': 800, fill: '#1b355a'}, center ?? String(total)));
  wrap.append(svg, h('div', {class: 'legend'}, data.map((item, i) => h('span', {}, h('i', {class: 'c' + (item.color ?? i % 6)}), `${item.label}: ${item.value}`))));
  return wrap;
}
const PALETTE = ['#2667db', '#168c86', '#e0a23a', '#d1495b', '#7a5af8', '#64748b'];
function gauge(value, label, {suffix = '', good = 75, mid = 50, sub = '', text = null} = {}) {
  const has = value !== null && value !== undefined; const v = has ? Math.max(0, Math.min(100, value)) : 0;
  const cls = !has ? 'g-none' : v >= good ? 'g-good' : v >= mid ? 'g-mid' : 'g-bad';
  const svg = s('svg', {viewBox: '0 0 42 42', role: 'img', 'aria-label': label + ': ' + (has ? fmt.num(value) + suffix : 'veri yok')},
    s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 5, class: 'g-track', stroke: '#e7edf5'}),
    s('circle', {cx: 21, cy: 21, r: 15.9, fill: 'none', 'stroke-width': 5, 'stroke-dasharray': `${v} ${100 - v}`, 'stroke-dashoffset': 25,
      'stroke-linecap': v > 0 ? 'round' : 'butt', stroke: {'g-good': '#168c86', 'g-mid': '#e0a23a', 'g-bad': '#d1495b', 'g-none': '#cbd5e1'}[cls]}),
    s('text', {x: 21, y: 24.5, 'text-anchor': 'middle', 'font-size': 9, 'font-weight': 800, fill: '#1b355a'}, text ?? (has ? fmt.num(value, 0) + suffix : '—')));
  return h('div', {class: 'gauge'}, svg, h('div', {}, h('div', {class: 'metric-label', text: label}), sub ? h('div', {class: 'metric-foot', text: sub}) : null));
}
function progressBar(value) {
  const v = Math.max(0, Math.min(100, value || 0));
  return s('svg', {class: 'chart', viewBox: '0 0 100 4', preserveAspectRatio: 'none', role: 'img', 'aria-label': '%' + Math.round(v)},
    s('rect', {x: 0, y: 0, width: 100, height: 4, rx: 2, fill: '#e9eff6'}), s('rect', {x: 0, y: 0, width: v, height: 4, rx: 2, fill: '#2667db'}));
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
function tabs(items, initial) {
  const bar = h('div', {class: 'tabs', role: 'tablist'}); const body = h('div');
  const show = key => {
    bar.querySelectorAll('.tab').forEach(t => { const on = t.dataset.key === key; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
    const item = items.find(i => i.key === key); clear(body); const r = item.render(); if (r instanceof Promise) r.then(n => append(body, [n])); else append(body, [r]);
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
    control = h('input', {id, name: f.name, type: f.name === 'email' ? 'email' : f.name === 'website' ? 'url' : 'text', value: value ?? '', autocomplete: 'off'});
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
  return (META.def(res).fields || []).filter(f => !f.readonly && !AUTO.has(f.name) && (!f.name.endsWith('_json') || res === 'policies') && !skip.includes(f.name) && (!only || only.includes(f.name)));
}
/** Kayıt formu: oluşturma ve düzenleme. Yalnızca değişen alanlar gönderilir. */
async function recordForm(res, record = null, {defaults = {}, only, skip, title, onsaved, extra} = {}) {
  const def = META.def(res); const fields = editableFields(res, {only, skip});
  await loadRefs(res, fields.map(f => f.name));
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
  $('pageTitle').textContent = title; $('pageSub').textContent = sub; document.title = title + ' • Tedarik Portalı';
  append(clear($('topActions')), actions.filter(Boolean));
  append(clear($('crumbs')), crumbs.map((c, i) => [i ? ' / ' : '', h('a', {href: '#/' + c[1], text: c[0]})]));
}
function content(...nodes) { const c = clear($('content')); append(c, nodes); return c; }

// ------------------------------------------------------------------ menü ve ekran tanımları
const MENU = [
  ['GENEL', [['home', '▦', 'Genel Bakış'], ['schedule', '◷', 'Takvim'], ['my-surveys', '✎', 'Anketlerim']]],
  ['TEDARİK', [['r/suppliers', '◉'], ['r/engagements', '⇄'], ['r/contracts', '▤'], ['r/catalog_items', '◫']]],
  ['PERFORMANS', [['r/sla_definitions', '◷'], ['r/sla_measurements', '✓'], ['r/performance_events', '⚑'], ['r/performance_reviews', '★']]],
  ['RİSK', [['r/supplier_risks', '△'], ['r/risk_actions', '↗']]],
  ['ANKET', [['r/survey_templates', '▧'], ['r/survey_campaigns', '✉']]],
  ['KAYNAK BULMA', [['r/needs', '◇'], ['r/quotes', '₺']]],
  ['VERİ', [['transfer', '⇅', 'Aktarım', 'manage'], ['r/import_batches', '☰']]],
  ['YÖNETİM', [['r/org_units', '⌂'], ['r/supplier_types', '◈'], ['r/review_criteria', '☆'], ['r/policies', '⚖'], ['users', '⚙', 'Kullanıcılar', 'admin'], ['r/audit_log', '≡']]],
];
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
  supplier_risks: ['code', 'title', 'supplier_id', 'category', 'owner', 'status', 'review_date'],
  risk_actions: ['code', 'title', 'risk_id', 'owner', 'due_date', 'priority', 'status'],
  survey_templates: ['code', 'name', 'purpose', 'version', 'status', 'updated_at'],
  survey_campaigns: ['code', 'name', 'template_id', 'subject', 'audience', 'status', 'closes_on'],
  audit_log: ['occurred_at', 'actor', 'method', 'object_type', 'object_id', 'description'],
  import_batches: ['created_at', 'kind', 'source_system', 'filename', 'status', 'created_by'],
  policies: ['code', 'value_json', 'description'],
  needs: ['code', 'title', 'org_unit_id', 'requester', 'needed_by'], quotes: ['need_id', 'supplier_id', 'amount', 'currency', 'received_at'],
};
const FILTERS = {
  suppliers: ['tier', 'status', 'segment', 'type_id'], engagements: ['supplier_id', 'org_unit_id', 'beneficiary', 'criticality', 'status'],
  contracts: ['supplier_id', 'status'], catalog_items: ['kind'], supplier_risks: ['supplier_id', 'status', 'category'],
  risk_actions: ['status', 'priority'], performance_events: ['supplier_id', 'event_type', 'severity'], sla_measurements: ['sla_id', 'met'],
  sla_definitions: ['engagement_id'], performance_reviews: ['supplier_id'], survey_campaigns: ['status', 'subject'],
  survey_templates: ['purpose', 'status'], import_batches: ['kind'],
};
const DESCRIPTIONS = {
  suppliers: 'Tekil tüzel kişiler. Kritiklik seviyesi değerlendirme, anket ve risk gözden geçirme sıklığını belirler.',
  engagements: 'Hangi birim, hangi ürün veya hizmeti, kimden, kimin için ve kimin sahipliğinde alıyor.',
  contracts: 'Sözleşme referansları; asıl kayıt kaynak sistemdedir.', catalog_items: 'Alınan ürün ve hizmetler.',
  sla_definitions: 'Angajman bazında hizmet seviyesi hedefleri.', sla_measurements: 'Dönemlik ölçümler; hedefin tutup tutmadığı sunucuda hesaplanır.',
  performance_events: 'SLA ihlali, kesinti, gecikme, eskalasyon ve takdir kayıtları.', performance_reviews: 'Kriter bazlı dönemlik değerlendirmeler.',
  supplier_risks: 'KS GRC ile aynı model: olasılık × etki, kontrol katkısı, artık risk, iştah ve değişmez kararlar.',
  risk_actions: 'Risk işleme faaliyetleri.', survey_templates: 'Memnuniyet, risk ve bağımsız anket şablonları. Yayımlanan şablon donar.',
  survey_campaigns: 'Şablonun uygulanması: değerlendirilen tedarikçiler, davetliler, yanıtlar ve sonuçlar.',
  audit_log: 'Her yazma işleminin değiştirilemez izi.', import_batches: 'İçe aktarım geçmişi ve satır sonuçları.',
  org_units: 'İş birimleri. Birim Kullanıcıları yalnızca kendi birimlerinin kayıtlarına yazar.',
  policies: 'Süreç kuralları kodda değil burada durur: değerlendirme ve anket sıklığı, uyarı süresi, teklif sayısı. Değer JSON biçimindedir.',
};
const RELATED = {
  engagements: [['sla_definitions', 'engagement_id'], ['responsibilities', 'engagement_id'], ['supplier_risks', 'engagement_id'],
    ['performance_events', 'engagement_id'], ['contracts', 'engagement_id']],
  sla_definitions: [['sla_measurements', 'sla_id']], performance_reviews: [['review_scores', 'review_id']],
  org_units: [['engagements', 'org_unit_id']], catalog_items: [['engagements', 'catalog_item_id']],
  import_batches: [['import_rows', 'batch_id']], supplier_types: [], contracts: [],
};
const DETAILS = {}; // özel detay ekranları aşağıda tanımlanır

function navigation() {
  const nav = clear($('nav')); const current = Router.parse().parts.slice(0, 2).join('/') || 'home';
  for (const [title, items] of MENU) {
    const visible = items.filter(([key, , , need]) => {
      if (need && !META.can(need)) return false;
      if (key.startsWith('r/')) return !!META.def(key.slice(2));
      if (key === 'my-surveys') return S.meta.modules.includes('surveys');
      return true;
    });
    if (!visible.length) continue;
    nav.append(h('div', {class: 'nav-title', text: title}));
    for (const [key, icon, label] of visible) {
      const text = label || META.def(key.slice(2)).label;
      const active = current === key || (key === 'home' && current === 'home') || current.startsWith(key + '/');
      nav.append(h('button', {type: 'button', class: 'nav-button' + (active ? ' active' : ''), dataset: {nav: key}, 'aria-current': active ? 'page' : null,
        onclick: () => Router.go(key)}, h('span', {class: 'nav-icon', 'aria-hidden': 'true', text: icon}), text,
        key === 'my-surveys' && S.mySurveys ? h('span', {class: 'nav-count', text: S.mySurveys, title: 'Yanıt bekleyen anket'}) : null));
    }
  }
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
  const canCreate = def.can_write && def.api.includes('create');
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
    try { records = await api(`${res}?${q}`); } catch (e) { tableHost.replaceChildren(h('div', {class: 'notice bad', text: e.message})); return; }
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
function singular(label) { return {Tedarikçiler: 'Tedarikçi', Angajmanlar: 'Angajman', Birimler: 'Birim', Riskler: 'Risk'}[label] || 'kayıt'; }
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
  let record; try { record = await api(`${res}/${id}`); } catch (e) { toast(e.message, false); return; }
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
  Drawer.open(titleOf(record) || def.label + ' #' + id, body, [canEdit ? btn('Düzenle', () => recordForm(res, record, {onsaved: () => { refreshList(res); openRecord(res, id); }})) : null], def.label);
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
async function home() {
  setPage('Genel Bakış', 'Tedarikçi portföyü, performans, risk ve anketlerin özeti. Kartlara tıklayarak ilgili listeye geçin.');
  const data = await api('dashboard/summary');
  const sup = data.suppliers; const tier = Object.fromEntries(sup.by_tier.map(x => [x.key, x.count]));
  const cards = h('div', {class: 'cards'},
    metric('Tedarikçiler', fmt.num(sup.total, 0), `${tier.critical || 0} kritik · ${tier.important || 0} önemli`, '', () => Router.go('r/suppliers')),
    metric('Sahibi olmayan aktif tedarikçi', fmt.num(sup.without_owner, 0), 'İlişki sahibi atanmalı', sup.without_owner ? 'warn' : 'good', () => Router.go('r/suppliers?owner__null=1&status=active')),
    metric('90 gün içinde biten sözleşme', fmt.num(data.contracts_ending_90d, 0), 'Yenileme veya çıkış kararı', data.contracts_ending_90d ? 'warn' : 'good',
      () => Router.go(`r/contracts?status=active&end_date__gte=${today()}&end_date__lte=${today(90)}`)),
    data.sla_90d ? metric('SLA başarısı (son 3 ay)', data.sla_90d.rate === null ? '—' : fmt.pct(data.sla_90d.rate), `${data.sla_90d.met} / ${data.sla_90d.total} ölçüm`,
      data.sla_90d.rate === null ? '' : data.sla_90d.rate >= 95 ? 'good' : data.sla_90d.rate >= 85 ? 'warn' : 'bad', () => Router.go('r/sla_measurements')) : null);
  const second = h('div', {class: 'cards'});
  if (data.risks) {
    second.append(metric('Açık risk', fmt.num(data.risks.open, 0), `${data.risks.unassessed} değerlendirilmedi`, '', () => Router.go('r/supplier_risks?status=open')),
      metric('İştah üstü risk', fmt.num(data.risks.above_appetite, 0), 'Son değerlendirmeye göre', data.risks.above_appetite ? 'bad' : 'good', () => Router.go('r/supplier_risks')),
      metric('Gözden geçirmesi geciken', fmt.num(data.risks.review_overdue, 0), 'Risk gözden geçirme tarihi geçti', data.risks.review_overdue ? 'warn' : 'good',
        () => Router.go(`r/supplier_risks?review_date__lte=${today(-1)}`)));
  }
  if (data.surveys) second.append(metric('Açık anket kampanyası', fmt.num(data.surveys.open_campaigns, 0), `${data.surveys.submitted} yanıt gönderildi`, '', () => Router.go('r/survey_campaigns?status=open')));
  const charts = h('div', {class: 'grid two'},
    h('div', {class: 'panel'}, h('h3', {text: 'Kritiklik seviyesi'}), donut(sup.by_tier.map(x => ({label: META.option('suppliers', 'tier', x.key), value: x.count,
      color: {critical: 3, important: 2, standard: 0}[x.key]})), {center: String(sup.total)})),
    h('div', {class: 'panel'}, h('h3', {text: 'Birim başına angajman'}), barChart(data.engagements.by_unit.slice(0, 8).map(x => ({label: x.key, value: x.count})), {format: v => fmt.num(v, 0)})),
    h('div', {class: 'panel'}, h('h3', {text: 'Tedarikçi tipleri'}), barChart(sup.by_type.filter(x => x.count).slice(0, 8).map(x => ({label: x.key, value: x.count, color: 1})), {format: v => fmt.num(v, 0)})),
    data.events_90d ? h('div', {class: 'panel'}, h('h3', {text: 'Performans olayları (son 3 ay)'}), barChart(data.events_90d.map(x => ({label: META.option('performance_events', 'event_type', x.key), value: x.count,
      color: x.key === 'praise' ? 1 : 3})), {format: v => fmt.num(v, 0), onclick: i => Router.go('r/performance_events')})) : null);
  const due = await api('schedule').catch(() => null);
  const attention = [];
  if (sup.without_owner) attention.push([`${sup.without_owner} aktif tedarikçinin ilişki sahibi yok`, 'r/suppliers?owner__null=1&status=active']);
  if (data.engagements.without_owner) attention.push([`${data.engagements.without_owner} aktif angajmanın iş sahibi yok`, 'r/engagements?business_owner__null=1&status=active']);
  if (data.contracts_ending_90d) attention.push([`${data.contracts_ending_90d} sözleşme 90 gün içinde bitiyor`, `r/contracts?status=active&end_date__gte=${today()}&end_date__lte=${today(90)}`]);
  if (data.risks?.above_appetite) attention.push([`${data.risks.above_appetite} risk iştah eşiğinin üstünde`, 'r/supplier_risks']);
  if (data.risks?.review_overdue) attention.push([`${data.risks.review_overdue} riskin gözden geçirmesi gecikti`, `r/supplier_risks?review_date__lte=${today(-1)}`]);
  if (data.risks?.unassessed) attention.push([`${data.risks.unassessed} açık risk henüz değerlendirilmedi`, 'r/supplier_risks?status=open']);
  if (due) {
    const sm = due.summary; const lateReviews = (sm.review_overdue || 0); const lateSurveys = (sm.survey_overdue || 0);
    if (lateReviews) attention.unshift([`${lateReviews} tedarikçinin performans değerlendirmesi gecikti`, 'schedule']);
    if (lateSurveys) attention.push([`${lateSurveys} tedarikçinin memnuniyet anketi gecikti`, 'schedule']);
    if ((sm.review_due_soon || 0) + (sm.survey_due_soon || 0)) attention.push([`${(sm.review_due_soon || 0) + (sm.survey_due_soon || 0)} değerlendirme veya anket ${due.warning_days} gün içinde`, 'schedule']);
  }
  if (S.mySurveys) attention.unshift([`Yanıtlamanızı bekleyen ${S.mySurveys} anket var`, 'my-surveys']);
  const todo = h('div', {class: 'panel'}, h('h3', {text: 'Dikkat gerektirenler'}), attention.length ? h('ul', {class: 'attention'}, attention.map(([text, link]) =>
    h('li', {}, h('span', {text}), h('a', {href: '#/' + link, class: 'btn ghost small', text: 'Aç →'})))) : h('div', {class: 'notice success', text: 'Bekleyen bir konu yok.'}));
  content(cards, second.childElementCount ? second : '', todo, charts);
}

// ------------------------------------------------------------------ tedarikçi 360
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
const RISK_FIELDS = ['code', 'title', 'supplier_id', 'engagement_id', 'category', 'description', 'cause', 'risk_event', 'consequence',
  'likelihood', 'impact', 'appetite', 'owner', 'response_strategy', 'treatment', 'review_date', 'control_risk_ref'];
CREATE.supplier_risks = defaults => recordForm('supplier_risks', null, {only: RISK_FIELDS, defaults: {likelihood: 3, impact: 3, appetite: 9, owner: S.me.username, ...defaults},
  onsaved: r => { refreshList('supplier_risks'); openRecord('supplier_risks', r.id); },
  extra: h('div', {class: 'notice wide', text: 'Risk ifadesi KS GRC ile aynıdır: "… nedeniyle (neden), … olabilir (olay), bu da … sonucunu doğurur (etki)". Kabul ve kapanış için önce değerlendirme yapılır.'})});
DETAILS.supplier_risks = async function riskDetail(id) {
  await Promise.all([list('suppliers'), list('engagements')]);
  let r; try { r = await api(`supplier_risks/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const last = r.assessments[0]; const terminal = ['accepted', 'closed'].includes(r.status);
  const above = last && last.residual > last.appetite; const can = META.def('supplier_risks').can_write;
  const scores = h('div', {class: 'grid three'},
    metric('İçsel risk', fmt.num(r.inherent_score, 0), `Olasılık ${r.likelihood} × etki ${r.impact}`),
    metric('Artık risk', last ? fmt.num(last.residual) : '—', last ? `Azaltım %${fmt.num(last.mitigation_pct)}` : 'Değerlendirme yok', !last ? '' : above ? 'bad' : 'good'),
    metric('İştah eşiği', fmt.num(r.appetite, 0), above ? 'Son değerlendirme eşiğin üstünde' : last ? 'Eşik içinde' : '', above ? 'bad' : ''));
  const body = h('div', {},
    h('div', {class: 'chips'}, display('supplier_risks', 'status', r.status), display('supplier_risks', 'category', r.category), r.origin_ref ? pill('Anket sinyalinden', 'purple') : null), h('br'),
    terminal ? h('div', {class: 'notice', text: 'Karar verilmiş risk değiştirilemez. Değişiklik için önce gerekçeyle yeniden açın.'}) : !last ? h('div', {class: 'notice warn', text: 'Bu risk henüz değerlendirilmedi.'}) : null,
    scores, h('br'),
    section('Risk ifadesi', kv([['Neden', r.cause], ['Olay', r.risk_event], ['İş etkisi', r.consequence]])),
    section('Bilgiler', kv([['Tedarikçi', display('supplier_risks', 'supplier_id', r.supplier_id)], ['Angajman', display('supplier_risks', 'engagement_id', r.engagement_id)],
      ['Sahip', r.owner], ['Yanıt stratejisi', display('supplier_risks', 'response_strategy', r.response_strategy)], ['İşleme planı', r.treatment],
      ['Gözden geçirme', fmt.date(r.review_date)], ['KS GRC risk kodu', r.control_risk_ref], ['Açıklama', r.description]])),
    section(`Değerlendirmeler (${r.assessments.length})`, r.assessments.length ? h('ul', {class: 'timeline'}, r.assessments.map(a => h('li', {},
      h('strong', {text: `${fmt.datetime(a.assessed_at)} · ${a.assessor}`}), h('div', {text: `İçsel ${a.inherent} → artık ${fmt.num(a.residual)} (iştah ${a.appetite})`}),
      h('div', {class: 'muted', text: a.rationale}), (a.snapshot.mitigations || []).length ? h('div', {class: 'chips'}, a.snapshot.mitigations.map(m =>
        h('span', {class: 'chip', text: `${m.title || 'Önlem'} · ${{low: 'düşük', medium: 'orta', high: 'yüksek'}[m.weight] || m.weight} katkı${m.effectiveness === 'partial' ? ' · kısmen etkili' : ''}`}))) : null)))
      : h('div', {class: 'muted small', text: 'Değerlendirme yok'})),
    section(`Kararlar (${r.decisions.length})`, r.decisions.length ? h('ul', {class: 'timeline'}, r.decisions.map(d => h('li', {},
      h('strong', {text: `${META.option('supplier_risks', 'status', d.from_status)} → ${META.option('supplier_risks', 'status', d.to_status)}`}),
      h('div', {class: 'muted', text: `${fmt.datetime(d.decided_at)} · ${d.actor} (${roleLabel(d.actor_role)})`}), h('div', {text: d.rationale}),
      d.exception_rationale ? h('div', {class: 'notice warn', text: 'İştah istisnası: ' + d.exception_rationale}) : null))) : h('div', {class: 'muted small', text: 'Karar yok'})),
    section(`İşleme faaliyetleri (${r.actions.length})`, r.actions.length ? h('ul', {class: 'mini'}, r.actions.map(a => h('li', {class: 'link', onclick: () => openRecord('risk_actions', a.id)},
      h('strong', {text: a.code + ' · ' + a.title}), h('span', {class: 'cell-sub', text: `${a.owner} · ${fmt.date(a.due_date)}`}), h('div', {class: 'chips'}, display('risk_actions', 'priority', a.priority), display('risk_actions', 'status', a.status)))))
      : h('div', {class: 'muted small', text: 'Faaliyet yok'}), can && !terminal ? btn('+ Faaliyet', () => createRecord('risk_actions', {risk_id: id, owner: r.owner}), 'ghost small') : null));
  const reload = () => { refreshList('supplier_risks'); DETAILS.supplier_risks(id); };
  Drawer.open(r.code + ' · ' + r.title, body, can ? (terminal ? [btn('Yeniden aç', () => decision(r, 'open', reload), 'secondary')] : [
    btn('Düzenle', () => recordForm('supplier_risks', r, {only: RISK_FIELDS.filter(f => f !== 'code'), onsaved: reload}), 'secondary'),
    last ? btn('Kapat', () => decision(r, 'closed', reload), 'secondary') : null, last ? btn('Kabul et', () => decision(r, 'accepted', reload), 'secondary') : null,
    btn('Değerlendir', () => assessRisk(r, reload))]) : [], 'Tedarikçi riski');
};
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
  [local ? btn('+ Kullanıcı', () => userForm()) : null]);
  const [users] = await Promise.all([api('users'), list('org_units')]);
  const units = id => (S.cache.org_units || []).find(u => u.id === id)?.name || '#' + id;
  content(h('div', {class: 'panel'}, users.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kullanıcı', 'Tür', 'Rol', 'Birimler', 'Durum', 'Son giriş'].map(t => h('th', {text: t})))),
    h('tbody', {}, users.map(u => { const tr = h('tr', {class: 'clickable', tabindex: '0', onclick: () => userForm(u)},
      h('td', {class: 'cell-primary'}, u.display_name, h('span', {class: 'cell-sub', text: u.kind === 'entra' ? 'Entra hesabı' : u.username})),
      h('td', {}, pill(u.kind === 'entra' ? 'Kurumsal' : 'Yerel', u.kind === 'entra' ? 'purple' : 'neutral')),
      h('td', {}, u.role ? roleLabel(u.role) : h('span', {class: 'muted', text: u.kind === 'entra' ? 'Entra rolü' : '—'})),
      h('td', {text: u.org_unit_ids.map(units).join(', ')}), h('td', {}, u.is_active ? pill('Aktif', 'good') : pill('Devre dışı', 'bad')), h('td', {text: fmt.datetime(u.last_login_at)}));
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
  Modal.open(isNew ? 'Yeni kullanıcı' : user.display_name, body, [btn('Vazgeç', () => Modal.close(), 'secondary'), btn(isNew ? 'Oluştur' : 'Kaydet', async () => {
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

// ------------------------------------------------------------------ çatı
async function render() {
  const {parts, params} = Router.parse(); const key = parts[0] || 'home';
  if (Modal.isOpen()) Modal.close();
  navigation(); window.scrollTo(0, 0);
  const keepDrawer = key === 'r' && parts[2]; if (!keepDrawer && Drawer.isOpen()) Drawer.close();
  try {
    if (key === 'home') await home();
    else if (key === 'r' && parts[1]) { await listView(parts[1], {params}); if (parts[2]) openRecord(parts[1], Number(parts[2])); }
    else if (key === 'templates' && parts[1]) await templateBuilder(Number(parts[1]));
    else if (key === 'surveys' && parts[1]) await campaignPage(Number(parts[1]), params.get('tab'));
    else if (key === 'my-surveys') await mySurveys();
    else if (key === 'schedule') await schedulePage(params);
    else if (key === 'respond' && parts[1]) await respond(Number(parts[1]));
    else if (key === 'transfer') await transferPage();
    else if (key === 'users') await usersPage();
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
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { if (Modal.isOpen()) Modal.close(); else if (Drawer.isOpen()) Drawer.close(); }
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && $('tableSearch') && !$('tableSearch').disabled) { e.preventDefault(); $('tableSearch').focus(); }
  });
  try { S.meta = await api('metadata'); } catch (e) { content(h('div', {class: 'notice bad', text: e.message})); return; }
  S.me = S.meta.user;
  append(clear($('identity')), [h('strong', {text: S.me.display_name || S.me.username}), h('span', {class: 'role', text: S.me.role_label})]);
  if (S.meta.modules.includes('surveys')) api('my/surveys').then(items => { S.mySurveys = items.filter(i => i.open && i.state !== 'submitted').length; navigation(); }).catch(() => {});
  window.addEventListener('hashchange', render);
  render();
}
document.addEventListener('DOMContentLoaded', start);

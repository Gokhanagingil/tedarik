'use strict';
/* Kişisel veri (KVKK) ekranları (K-029): KVKK panosu, kişisel veri keşfi ve yerel örnek doğrulama, işleme envanteri
   (VERBİS), periyodik imha, veri talepleri, ilgili kişi başvuruları, VKED; tablo, kolon, ihlal ve Tedarikçi 360 eklentileri.
   app.js, pages.js ve datagov.js yardımcılarını kullanır; dış kütüphane ve satır içi stil yok (CSP). */

const PV = {sev: {high: ['Yüksek', 'bad'], medium: ['Orta', 'warn'], low: ['Düşük', 'neutral']}};
const sevPill = s => pill(...(PV.sev[s] || [s, 'neutral']));
const pct = v => `%${Math.round(100 * v)}`;

// ------------------------------------------------------------------ yerel doğrulayıcılar (tedarik/pii.py ile aynı kurallar)
const PII = {
  tckn(v) {
    const s = String(v).trim(); if (!/^[1-9]\d{10}$/.test(s)) return false;
    const d = [...s].map(Number); const odd = d[0] + d[2] + d[4] + d[6] + d[8]; const even = d[1] + d[3] + d[5] + d[7];
    if ((((odd * 7 - even) % 10) + 10) % 10 !== d[9]) return false;
    return d.slice(0, 10).reduce((a, b) => a + b, 0) % 10 === d[10];
  },
  iban(v) {
    const s = String(v).replace(/\s/g, '').toUpperCase();
    if (!/^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(s) || (s.startsWith('TR') && s.length !== 26)) return false;
    let rem = 0; for (const ch of s.slice(4) + s.slice(0, 4)) { const n = parseInt(ch, 36); for (const digit of String(n)) rem = (rem * 10 + Number(digit)) % 97; }
    return rem === 1;
  },
  card(v) {
    const s = String(v).replace(/[\s-]/g, ''); if (!/^\d{13,19}$/.test(s) || new Set(s).size === 1) return false;
    let total = 0; [...s].reverse().forEach((ch, i) => { let n = Number(ch); if (i % 2 === 1) n = n > 4 ? n * 2 - 9 : n * 2; total += n; });
    return total % 10 === 0;
  },
  email: v => /^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$/.test(String(v).trim()),
  phone(v) { const s = String(v).replace(/[\s().-]/g, ''); return /^(\+90|0090|0)?5\d{9}$/.test(s) || /^(\+90|0090|0)[2-4]\d{9}$/.test(s); },
  ipv4: v => /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/.test(String(v).trim()),
};
const PII_LABEL = {tckn: 'TCKN', iban: 'IBAN', card: 'Kart', email: 'E-posta', phone: 'Telefon', ipv4: 'IP'};
function parseCsv(text, limit = 2001) {
  const first = text.split(/\r?\n/, 1)[0] || '';
  const delim = [';', ',', '\t', '|'].map(d => [d, first.split(d).length]).sort((a, b) => b[1] - a[1])[0][0];
  const out = []; let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length && out.length < limit; i++) {
    const ch = text[i];
    if (quoted) { if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false; } else cell += ch; continue; }
    if (ch === '"') quoted = true;
    else if (ch === delim) { row.push(cell); cell = ''; }
    else if (ch === '\n') { row.push(cell.replace(/\r$/, '')); out.push(row); row = []; cell = ''; }
    else cell += ch;
  }
  if (cell || row.length) { row.push(cell); out.push(row); }
  return out;
}
function scanSample(text) {
  const table = parseCsv(text.replace(/^﻿/, '')); const headers = (table[0] || []).map(x => x.trim());
  const stats = {}; for (const hd of headers) if (hd) stats[hd] = {non_empty: 0, matches: {}};
  const body = table.slice(1, 2001);
  for (const row of body) headers.forEach((hd, i) => {
    if (!hd || i >= row.length) return; const v = String(row[i]).trim(); if (!v) return;
    const st = stats[hd]; st.non_empty++;
    for (const [k, fn] of Object.entries(PII)) if (fn(v)) st.matches[k] = (st.matches[k] || 0) + 1;
  });
  return {sample_size: body.length, columns: stats};
}
function sampleDialog(t, reload) {
  const file = h('input', {type: 'file', id: 'smpFile', accept: '.csv,.txt'}); const result = h('div');
  file.addEventListener('change', async () => {
    const f = file.files[0]; if (!f) return;
    if (f.size > 20 * 1024 * 1024) { toast('Örnek dosya 20 MB\'tan küçük olmalı; ilk 2000 satır yeterli', false); return; }
    const stats = scanSample(await f.text());
    const rowsEl = Object.entries(stats.columns).map(([name, st]) => h('tr', {}, h('td', {}, h('strong', {text: name})), h('td', {class: 'num', text: st.non_empty}),
      h('td', {}, Object.entries(st.matches).length ? Object.entries(st.matches).map(([k, n]) => pill(`${PII_LABEL[k]} ${pct(n / Math.max(1, st.non_empty))}`, n / Math.max(1, st.non_empty) >= 0.6 ? 'bad' : 'neutral')) : h('span', {class: 'muted', text: '—'}))));
    result.replaceChildren(h('div', {class: 'notice'}, h('strong', {text: `${stats.sample_size} satır bu bilgisayarda tarandı. `}), 'Sunucuya yalnızca aşağıdaki sayılar gönderilecek; değerlerin kendisi tarayıcıdan çıkmaz.'),
      h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kolon', 'Dolu değer', 'Geçerli bulunan'].map(x => h('th', {text: x})))), h('tbody', {}, rowsEl))),
      h('div', {class: 'toolbar'}, btn('Sayıları gönder ve öneri üret', async () => {
        const r = await api(`data_tables/${t.id}/sample-stats`, {method: 'POST', body: stats});
        Modal.close(); toast(`${r.new} yeni, ${r.updated} güncellenen öneri${r.unknown_columns.length ? ` · katalogda olmayan kolon: ${r.unknown_columns.length}` : ''}`); reload();
      })));
  });
  Modal.open('Örnek veriyle doğrula: ' + t.name, h('div', {},
    h('p', {class: 'intro', text: 'Tablodan aldığınız örnek bir CSV (ilk 2000 satır yeterli) seçin. TCKN, IBAN, kart, e-posta, telefon ve IP doğrulaması bu tarayıcıda yapılır. Başlıklar kolon adlarıyla aynı olmalı.'}),
    h('label', {class: 'field', for: 'smpFile'}, h('span', {text: 'Örnek dosya'}), h('div', {class: 'control'}, file)),
    h('p', {class: 'small muted', text: 'Büyük tablolarda aynı tarama kaynağın yanında da çalıştırılabilir: python -m tedarik.pii dosya.csv > sayilar.json'}), result),
  [btn('Kapat', () => Modal.close(), 'secondary')], true);
}

// ------------------------------------------------------------------ KVKK panosu
PAGES.privacy = async function privacyPage() {
  const d = await api('datagov/privacy');
  const manage = META.can('manage');
  setPage('KVKK Panosu', 'Kişisel verinin nerede olduğu, hangi amaç ve hukuki sebeple işlendiği, ne kadar saklandığı; envanter açıkları ve süreli işler.', [
    manage ? btn('Keşfi çalıştır', async () => { const r = await api('datagov/discovery/run', {method: 'POST', body: {}}); toast(`${r.scanned_columns} kolon tarandı · ${r.new} yeni öneri`); render(); }, 'secondary') : null,
    btn('VERBİS envanteri (Excel)', () => download('datagov/verbis-export?format=xlsx', 'kisisel-veri-envanteri.xlsx'), 'secondary'),
    btn('KVKK / GDPR boşluk analizi', () => Router.go('regulation'), 'secondary'),
    canWrite('processing_activities') ? btn('+ İşleme faaliyeti', () => createRecord('processing_activities')) : null], [['Veri Yönetişimi', 'datagov']]);
  const cols = d.columns; const disp = d.disposal;
  const subj = d.subject_requests; const nearest = subj.length ? subj[0] : null;
  const dispText = disp.overdue ? 'Gecikti' : disp.unplanned ? 'Planlanmadı' : disp.next_due ? fmt.date(disp.next_due) : (disp.tables_in_scope ? '—' : 'Kapsam yok');
  const sources = [...new Set(d.matrix.map(m => m.source))].sort((a, b) => a.localeCompare(b, TR));
  const cats = [...new Map(d.matrix.map(m => [m.category, m.special])).entries()].sort((a, b) => a[0].localeCompare(b[0], TR));
  const cell = (cat, src) => { const m = d.matrix.find(x => x.category === cat && x.source === src); return m ? h('td', {class: 'num'}, h('button', {type: 'button', class: 'heat-cell' + (m.special ? ' special' : ''), text: m.n, onclick: () => Router.go(`catalog?s=${m.source_id}&f=personal`)})) : h('td', {class: 'num muted', text: '·'}); };
  const matrix = cats.length ? h('div', {class: 'tablewrap'}, h('table', {class: 'pdmap'}, h('thead', {}, h('tr', {}, h('th', {text: 'Kategori'}), sources.map(sname => h('th', {text: sname})))),
    h('tbody', {}, cats.map(([cat, special]) => h('tr', {}, h('td', {}, h('strong', {text: cat}), special ? pill('Özel nitelikli', 'bad') : null), sources.map(src => cell(cat, src))))))) :
    empty('Kategorilendirilmiş kolon yok', 'Kişisel veri keşfini çalıştırıp önerileri kabul edin; harita buradan oluşur.', manage ? btn('Keşfe git', () => Router.go('discovery')) : null);
  const acts = d.activities.length ? h('ul', {class: 'mini'}, d.activities.map(a => h('li', {class: 'link', onclick: () => Router.go('activity/' + a.id)},
    h('div', {class: 'chips'}, h('strong', {text: `${a.code} · ${a.name}`}), display('processing_activities', 'status', a.status),
      a.gaps.length ? pill(`${a.gaps.length} eksik${a.high ? ` (${a.high} yüksek)` : ''}`, a.high ? 'bad' : 'warn') : pill('Eksik yok', 'good'))))) :
    empty('İşleme faaliyeti yok', 'Her kişisel veri işleme faaliyetini (ör. müşteri ilişkileri, bordro) amaç ve hukuki sebebiyle tanımlayın.');
  const uncovered = d.uncovered.length ? h('ul', {class: 'mini'}, d.uncovered.slice(0, 15).map(c => h('li', {class: 'link', onclick: () => Router.go('catalog/table/' + c.table_id)},
    h('strong', {text: `${c.table_name}.${c.name}`}), h('span', {class: 'cell-sub', text: `${c.source_name} · ${META.option('data_columns', 'personal_data', c.personal_data)}`})))) :
    h('div', {class: 'muted small', text: 'Tüm kişisel veri kolonları bir işleme faaliyetine bağlı.'});
  const risks = d.risks.length ? h('ul', {class: 'mini'}, d.risks.map(r => h('li', {class: 'link', onclick: () => Router.go('catalog/table/' + r.table_id)},
    h('div', {class: 'chips'}, levelPill(r.level), h('strong', {text: `${r.table}`}), h('span', {class: 'muted small', text: `${r.score} puan · ${r.source_name}`})),
    r.gaps.length ? h('span', {class: 'cell-sub', text: r.gaps.join(' · ')}) : null))) : h('div', {class: 'muted small', text: 'Kişisel veri içeren tablo yok.'});
  const deadlines = h('ul', {class: 'mini'},
    subj.map(r => h('li', {class: 'link', onclick: () => openRecord('subject_requests', r.id)}, h('div', {class: 'chips'}, h('strong', {text: r.code}),
      pill(r.late ? `${-r.remaining_days} gün gecikti` : `${r.remaining_days} gün kaldı`, r.late ? 'bad' : r.remaining_days <= 5 ? 'warn' : 'neutral')),
      h('span', {class: 'cell-sub', text: `${META.option('subject_requests', 'request_type', r.request_type)} · ${r.owner}`}))),
    d.data_requests.map(r => h('li', {class: 'link', onclick: () => openRecord('data_requests', r.id)}, h('div', {class: 'chips'}, h('strong', {text: r.code}),
      display('data_requests', 'status', r.status)), h('span', {class: 'cell-sub', text: `${META.option('data_requests', 'kind', r.kind)} · ${r.table_name} · ${r.requested_by}`}))));
  content(
    h('div', {class: 'grid four'},
      metric('Kişisel veri kolonu', fmt.num(cols.personal), `${fmt.num(cols.special)} özel nitelikli · ${fmt.num(cols.unassessed)} değerlendirilmedi`, '', () => Router.go('catalog?f=personal')),
      metric('Envanter dışı kişisel veri', fmt.num(cols.uncovered), 'İşleme faaliyetine bağlı değil', cols.uncovered ? 'bad' : 'good'),
      metric('Karar bekleyen öneri', fmt.num(d.suggestions), 'Kişisel veri keşfi', d.suggestions ? 'warn' : '', () => Router.go('discovery')),
      metric('İlgili kişi başvurusu', fmt.num(subj.length), nearest ? (nearest.late ? 'Süresi geçen var' : `En yakın: ${nearest.remaining_days} gün`) : 'Açık başvuru yok', nearest && nearest.late ? 'bad' : '', () => Router.go('r/subject_requests'))),
    h('div', {class: 'grid two'},
      panel('Kişisel veri haritası', matrix, null, 'kategori × kaynak, kolon sayısı'),
      panel('İşleme faaliyetleri', acts, canWrite('processing_activities') ? btn('+ Faaliyet', () => createRecord('processing_activities'), 'ghost small') : null)),
    h('div', {class: 'grid three'},
      panel('Envanter dışı kişisel veri', uncovered),
      panel('En riskli veri varlıkları', risks),
      panel('Süreli işler', h('div', {},
        h('div', {class: 'notice ' + (disp.overdue || disp.unplanned ? 'warn' : '')}, h('strong', {text: 'Periyodik imha: '}), dispText,
          disp.last ? ` · son: ${disp.last.code} (${fmt.date(disp.last.completed_at)})` : '', ` · en çok ${disp.interval_months} ayda bir`),
        d.dpias_pending ? h('div', {class: 'notice'}, `${d.dpias_pending} VKED onay bekliyor`) : null,
        subj.length || d.data_requests.length ? deadlines : h('div', {class: 'muted small', text: 'Açık başvuru veya talep yok.'})),
        canWrite('disposal_runs') ? btn('+ Periyodik imha', () => createRecord('disposal_runs'), 'ghost small') : null)));
};

// ------------------------------------------------------------------ kişisel veri keşfi
PAGES.discovery = async function discoveryPage(parts, params) {
  const status = params.get('s') || 'pending', sid = params.get('src') || '', table = params.get('table') || '', strong = params.get('strong') === '1';
  const go = patch => { const p = new URLSearchParams({s: status, src: sid, table, strong: strong ? '1' : '', ...patch}); for (const [k, v] of [...p]) if (!v) p.delete(k); Router.go('discovery?' + p); };
  const qs = new URLSearchParams({status}); if (sid) qs.set('source_id', sid); if (table) qs.set('table_id', table); if (strong) qs.set('min_confidence', '0.7');
  const [d, sources] = await Promise.all([api('datagov/discovery?' + qs), list('data_sources')]);
  const manage = META.can('manage');
  setPage('Kişisel Veri Keşfi', 'Kolon adı, açıklama ve sözlük terimlerinden kişisel veri önerileri; örnek değer doğrulaması tablonun ekranından, veri bilgisayarınızdan çıkmadan yapılır. Kabul edilen kategori kolona işlenir ve sınıf en az "Gizli" (özel nitelikli için "Çok gizli") olur.', [
    manage ? btn('Keşfi çalıştır', async () => { const r = await api('datagov/discovery/run', {method: 'POST', body: sid ? {source_id: Number(sid)} : {}}); toast(`${r.scanned_columns} kolon tarandı · ${r.new} yeni, ${r.updated} güncellenen öneri`); render(); }) : null,
    btn('Sözlüğü düzenle', () => Router.go('r/personal_data_categories'), 'secondary')], [['KVKK Panosu', 'privacy']]);
  const c = d.counts;
  const chips = h('div', {class: 'chips'}, [['pending', 'Karar bekliyor', c.pending], ['accepted', 'Kabul edildi', c.accepted], ['rejected', 'Reddedildi', c.rejected], ['all', 'Tümü']].map(([k, label, n]) =>
    h('button', {type: 'button', class: 'chip' + (status === k ? ' on' : ''), text: n !== undefined ? `${label} (${n || 0})` : label, onclick: () => go({s: k})})),
    h('button', {type: 'button', class: 'chip' + (strong ? ' on' : ''), text: 'Yalnızca güçlü (≥ %70)', onclick: () => go({strong: strong ? '' : '1'})}));
  const srcSel = h('select', {'aria-label': 'Kaynak', onchange: e => go({src: e.target.value, table: ''})}, h('option', {value: '', text: 'Tüm kaynaklar'}),
    sources.map(s => h('option', {value: s.id, text: s.name, selected: String(s.id) === sid})));
  const sel = new Set(); const bar = h('div', {class: 'bulk-bar hidden'});
  const drawBar = () => { bar.classList.toggle('hidden', !sel.size); bar.replaceChildren(h('strong', {text: `${sel.size} öneri seçildi`}),
    btn('Kabul et', () => bulk('accept'), 'small'), btn('Reddet', () => bulk('reject'), 'secondary small')); };
  const bulk = async action => { const r = await api('datagov/discovery/bulk', {method: 'POST', body: {ids: [...sel], action}}); toast(`${r.done} öneri ${action === 'accept' ? 'kabul edildi' : 'reddedildi'}${r.errors.length ? `, ${r.errors.length} atlandı` : ''}`, !r.errors.length); render(); };
  const groups = new Map(); for (const it of d.items) { const k = `${it.source_name} / ${it.table_name}`; if (!groups.has(k)) groups.set(k, {table_id: it.table_id, items: []}); groups.get(k).items.push(it); }
  const decideBtns = it => it.status === 'pending' ? [btn('Kabul', async () => { await api(`pii_suggestions/${it.id}/accept`, {method: 'POST', body: {}}); toast('Kabul edildi'); render(); }, 'small'),
    btn('Reddet', async () => { await api(`pii_suggestions/${it.id}/reject`, {method: 'POST', body: {}}); toast('Reddedildi'); render(); }, 'ghost small')] : [display('pii_suggestions', 'status', it.status)];
  const listEl = groups.size ? [...groups.entries()].map(([name, g]) => panel(name, h('div', {class: 'tablewrap plain'}, h('table', {}, h('thead', {}, h('tr', {}, ['', 'Kolon', 'Kategori', 'Güven', 'Gerekçe', ''].map(x => h('th', {text: x})))),
    h('tbody', {}, g.items.map(it => h('tr', {},
      h('td', {class: 'sel-cell'}, it.status === 'pending' ? h('input', {type: 'checkbox', 'aria-label': 'Seç', onchange: e => { if (e.target.checked) sel.add(it.id); else sel.delete(it.id); drawBar(); }}) : null),
      h('td', {}, h('button', {type: 'button', class: 'linklike', text: it.column_name, onclick: () => columnPanel(it.column_id)}), it.business_name ? h('div', {class: 'cell-sub', text: it.business_name}) : null),
      h('td', {}, pill(it.category_name, it.special ? 'bad' : 'warn')),
      h('td', {}, h('div', {class: 'cover'}, progressBar(100 * it.confidence), h('span', {class: 'small muted', text: `${pct(it.confidence)} · ${META.option('pii_suggestions', 'method', it.method)}`}))),
      h('td', {class: 'small', text: it.evidence || ''}), h('td', {class: 'row-actions'}, decideBtns(it))))))),
    btn('Tabloyu aç', () => Router.go('catalog/table/' + g.table_id), 'ghost small'))) :
    [empty(status === 'pending' ? 'Karar bekleyen öneri yok' : 'Öneri yok', manage ? 'Keşfi çalıştırın veya tablo ekranından örnek veriyle doğrulayın.' : '')];
  content(h('div', {class: 'panel'}, h('div', {class: 'toolbar wrap'}, srcSel, table ? btn('Tablo süzgecini kaldır', () => go({table: ''}), 'ghost small') : null), chips, bar), ...listEl);
};

// ------------------------------------------------------------------ işleme faaliyeti
DETAILS.processing_activities = id => Router.go('activity/' + id);
const ACTIVITY_FIELDS = ['name', 'purpose', 'description', 'org_unit_id', 'owner', 'process_id', 'domain_id', 'legal_basis', 'special_legal_basis', 'legal_basis_note',
  'recipients', 'foreign_transfer', 'transfer_countries', 'transfer_mechanism', 'transfer_signed_on', 'transfer_notified_on', 'retention_rule_id', 'security_measures',
  'notice_document_id', 'profiling', 'large_scale', 'new_technology', 'review_date'];
CREATE.processing_activities = defaults => recordForm('processing_activities', null, {only: ACTIVITY_FIELDS, defaults, onsaved: r => { Drawer.close(); Router.go('activity/' + r.id); }});
PAGES.activity = async function activityPage(parts) {
  const id = Number(parts[1]); const a = await api(`processing_activities/${id}/context`); await loadRefs('processing_activities');
  const reload = () => render(); const can = a.can_edit;
  const link = body => api(`processing_activities/${id}/links`, {method: 'POST', body}).then(() => { toast('Kaydedildi'); reload(); });
  setPage(a.name, `${a.code} · ${META.option('processing_activities', 'status', a.status)}`, [
    can ? btn('Düzenle', () => recordForm('processing_activities', a, {only: ACTIVITY_FIELDS, onsaved: reload}), 'secondary') : null,
    can && a.status === 'draft' ? btn('Etkinleştir', () => api('processing_activities/' + id, {method: 'PATCH', body: {status: 'active'}}).then(() => { toast('Etkinleştirildi'); reload(); })) : null,
    canWrite('dpias') ? btn('VKED başlat', () => recordForm('dpias', null, {defaults: {activity_id: id, title: 'VKED: ' + a.name}, only: ['title', 'necessity', 'risks', 'measures', 'residual_risk', 'decision'],
      onsaved: r => { Drawer.close(); openRecord('dpias', r.id); }}), a.dpia_required && !a.dpias.some(x => x.status === 'approved') ? '' : 'ghost') : null,
    can && a.status === 'active' ? btn('Kullanımdan kaldır', () => api('processing_activities/' + id, {method: 'PATCH', body: {status: 'retired'}}).then(reload), 'ghost') : null],
  [['KVKK Panosu', 'privacy'], ['İşleme Faaliyetleri', 'r/processing_activities']]);
  const gaps = a.gaps.length ? h('div', {class: 'panel'}, h('h3', {text: `Envanter eksikleri (${a.gaps.length})`}), h('ul', {class: 'mini'}, a.gaps.map(g => h('li', {}, h('div', {class: 'chips'}, sevPill(g.severity), h('span', {text: g.text})))))) :
    h('div', {class: 'notice success', text: 'Bu faaliyette envanter eksiği yok.'});
  const t = a.transfer_mechanism;
  const verbis = kv([['Amaç', a.purpose], ['Hukuki sebep (md. 5)', display('processing_activities', 'legal_basis', a.legal_basis)],
    a.special_legal_basis || a.categories.some(k => k.special) || a.observed_categories.some(k => k.special) ? ['Özel nitelikli (md. 6)', display('processing_activities', 'special_legal_basis', a.special_legal_basis)] : null,
    a.legal_basis_note ? ['Açıklama', a.legal_basis_note] : null,
    ['Veri kategorileri', h('span', {class: 'chips'}, a.categories.length ? a.categories.map(k => pill(k.name, k.special ? 'bad' : 'neutral')) : h('span', {class: 'muted', text: 'Seçilmedi'}),
      can ? btn('Düzenle', () => editCats(a, link), 'ghost small') : null)],
    ['İlgili kişi grupları', h('span', {class: 'chips'}, a.subjects.length ? a.subjects.map(g => h('span', {class: 'chip', text: g.name})) : h('span', {class: 'muted', text: 'Seçilmedi'}),
      can ? btn('Düzenle', () => editSubjects(a, link), 'ghost small') : null)],
    ['Alıcı grupları', a.recipients], ['Yurt dışı aktarım', a.foreign_transfer ? h('span', {}, `Var · ${a.transfer_countries || 'ülke yok'} · `, display('processing_activities', 'transfer_mechanism', t),
      t === 'standard_contract' ? h('div', {class: 'small muted', text: `İmza ${fmt.date(a.transfer_signed_on) || '—'} · bildirim ${fmt.date(a.transfer_notified_on) || '—'}${a.transfer_notice_deadline ? ' · son gün ' + fmt.date(a.transfer_notice_deadline) : ''}`}) : null) : 'Yok'],
    ['Saklama süresi', a.retention_rule ? `${a.retention_rule.code} · ${a.retention_rule.period_value} ${META.option('retention_rules', 'period_unit', a.retention_rule.period_unit)} (${a.retention_rule.trigger_event})` : null],
    ['Teknik ve idari tedbirler', a.security_measures], ['Aydınlatma metni', a.notice_document ? h('a', {href: '#/r/documents/' + a.notice_document.id, text: `${a.notice_document.code} ${a.notice_document.title}`}) : null],
    ['VKED', a.dpia_required ? (a.dpias.some(x => x.status === 'approved') ? pill('Gerekli · onaylı', 'good') : pill('Gerekli', 'warn')) : 'Gerekmiyor']]);
  const right = kv([['Sorumlu birim', display('processing_activities', 'org_unit_id', a.org_unit_id)], ['Faaliyet sahibi', a.owner], ['Süreç', display('processing_activities', 'process_id', a.process_id)],
    ['Veri alanı', display('processing_activities', 'domain_id', a.domain_id)], ['Gözden geçirme', a.review_date ? fmt.date(a.review_date) : null],
    ['Profilleme / büyük ölçek / yeni teknoloji', [a.profiling ? 'profilleme' : null, a.large_scale ? 'büyük ölçek' : null, a.new_technology ? 'yeni teknoloji' : null].filter(Boolean).join(', ') || 'Yok']]);
  const assets = () => h('div', {},
    h('div', {class: 'toolbar wrap'}, can ? btn('+ Tablo bağla', async () => { const ids = await searchPicker('Tablo bağla: ' + a.name, {kind: 'tables', label: x => dgPath(x.schema_name, x.name), sub: x => [x.source_name, x.business_name].filter(Boolean).join(' · ')}); if (ids && ids.length) link({tables: [...new Set([...a.tables.map(x => x.id), ...ids])]}); }) : null,
      can ? btn('+ Kolon bağla', async () => { const ids = await searchPicker('Kolon bağla: ' + a.name, {kind: 'columns', label: x => `${dgPath(x.schema_name, x.table_name)}.${x.name}`, sub: x => [x.source_name, x.business_name].filter(Boolean).join(' · ')}); if (ids && ids.length) link({columns: [...new Set([...a.columns.map(x => x.id), ...ids])]}); }, 'secondary') : null),
    a.tables.length ? section('Tablolar (tüm kişisel veri kolonlarıyla)', h('ul', {class: 'mini'}, a.tables.map(x => h('li', {}, h('a', {href: '#/catalog/table/' + x.id, text: dgPath(x.schema_name, x.name)}),
      h('span', {class: 'cell-sub', text: [x.source_name, x.business_name, x.row_count !== null && x.row_count !== undefined ? `${fmt.num(x.row_count)} satır` : null].filter(Boolean).join(' · ')}),
      can ? btn('Kaldır', () => link({tables: a.tables.filter(y => y.id !== x.id).map(y => y.id)}), 'ghost small') : null)))) : null,
    a.columns.length ? section('Kolonlar', h('ul', {class: 'mini'}, a.columns.map(x => h('li', {}, h('button', {type: 'button', class: 'linklike', text: `${dgPath(x.schema_name, x.table_name)}.${x.name}`, onclick: () => columnPanel(x.id)}),
      h('span', {class: 'cell-sub', text: [x.source_name, x.business_name].filter(Boolean).join(' · ')}),
      can ? btn('Kaldır', () => link({columns: a.columns.filter(y => y.id !== x.id).map(y => y.id)}), 'ghost small') : null)))) : null,
    !a.tables.length && !a.columns.length ? empty('Veri varlığı bağlanmadı', 'Bu faaliyette işlenen tablo veya kolonları bağlayın; kategoriler kolonlardan önerilir ve envanter dışı veri azalır.') : null);
  const processors = () => h('div', {}, can ? h('div', {class: 'toolbar wrap'}, btn('Veri işleyenleri düzenle', () => editProcessors(a, link), 'secondary')) : null,
    a.processors.length ? h('ul', {class: 'mini'}, a.processors.map(p => h('li', {}, h('div', {class: 'chips'}, h('strong', {text: p.supplier_name}), pill(META.option('processing_processors', 'role', p.role), 'neutral'),
      p.role === 'processor' ? (p.dpa_signed ? pill('Sözleşme var', 'good') : pill('Veri işleme sözleşmesi yok', 'bad')) : null), p.note ? h('span', {class: 'cell-sub', text: p.note}) : null))) :
      h('div', {class: 'muted small', text: 'Veri işleyen veya alıcı tedarikçi yok.'}));
  const observed = () => h('div', {}, h('p', {class: 'small muted', text: 'Bağlı tablo ve kolonlarda kabul edilmiş kategoriler. Envanterde olmayanlar VERBİS kaydını eksik bırakır.'}),
    a.observed_categories.length ? h('div', {class: 'chips'}, a.observed_categories.map(k => pill(k.name + (a.categories.some(x => x.id === k.id) ? '' : ' · envanterde yok'), a.categories.some(x => x.id === k.id) ? 'good' : 'warn'))) : h('div', {class: 'muted small', text: 'Bağlı kolonlarda kategori yok.'}),
    can && a.observed_categories.some(k => !a.categories.some(x => x.id === k.id)) ? btn('Eksik kategorileri envantere ekle', () => api(`processing_activities/${id}/adopt-categories`, {method: 'POST', body: {}}).then(() => { toast('Eklendi'); reload(); })) : null);
  const dpias = () => a.dpias.length ? h('ul', {class: 'mini'}, a.dpias.map(x => h('li', {class: 'link', onclick: () => openRecord('dpias', x.id)}, h('div', {class: 'chips'}, h('strong', {text: `${x.code} · ${x.title}`}),
    display('dpias', 'status', x.status), x.residual_risk ? display('dpias', 'residual_risk', x.residual_risk) : null)))) : h('div', {class: 'muted small', text: a.dpia_required ? 'Bu faaliyet için VKED gerekli; "VKED başlat" ile açın.' : 'VKED yok.'});
  content(gaps, h('div', {class: 'grid wide-left'}, h('div', {class: 'panel'}, h('h3', {text: 'VERBİS bilgileri'}), verbis), h('div', {class: 'panel'}, h('h3', {text: 'Sorumluluk'}), right)),
    tabs([{key: 'assets', label: 'Veri varlıkları', count: a.tables.length + a.columns.length, render: assets}, {key: 'processors', label: 'Veri işleyenler', count: a.processors.length, render: processors},
      {key: 'observed', label: 'Gözlenen kategoriler', count: a.observed_categories.length, render: observed}, {key: 'dpia', label: 'VKED', count: a.dpias.length, render: dpias}]));
};
async function editCats(a, link) {
  const all = (await list('personal_data_categories', true)).filter(k => k.active);
  const chosen = await pickMany('Veri kategorileri', all, a.categories.map(k => k.id), {label: k => k.name + (k.special ? ' (özel nitelikli)' : '')});
  if (chosen) link({categories: chosen});
}
async function editSubjects(a, link) {
  const all = (await list('data_subject_groups', true)).filter(g => g.active);
  const chosen = await pickMany('İlgili kişi grupları', all, a.subjects.map(g => g.id), {label: g => g.name});
  if (chosen) link({subjects: chosen});
}
async function editProcessors(a, link) {
  const suppliers = await list('suppliers');
  const rowsEl = h('div', {class: 'proc-rows'});
  const addRow = (p = {}) => {
    const sup = h('select', {'aria-label': 'Tedarikçi'}, h('option', {value: '', text: '— Tedarikçi —'}), suppliers.slice().sort((x, y) => x.name.localeCompare(y.name, TR)).map(s => h('option', {value: s.id, text: s.name, selected: s.id === p.supplier_id})));
    const role = h('select', {'aria-label': 'Rol'}, META.field('processing_processors', 'role') ? META.field('processing_processors', 'role').options.map(o => h('option', {value: o.value, text: o.label, selected: o.value === (p.role || 'processor')}))
      : [['processor', 'Veri işleyen'], ['joint_controller', 'Ortak veri sorumlusu'], ['recipient', 'Alıcı']].map(([v, l]) => h('option', {value: v, text: l, selected: v === (p.role || 'processor')})));
    const dpa = h('input', {type: 'checkbox', checked: !!p.dpa_signed}); const note = h('input', {type: 'text', placeholder: 'Not', value: p.note || ''});
    const row = h('div', {class: 'proc-row'}, sup, role, h('label', {class: 'toggle'}, dpa, h('span', {text: 'DPA imzalı'})), note, btn('Sil', () => row.remove(), 'ghost small'));
    row.read = () => ({supplier_id: Number(sup.value), role: role.value, dpa_signed: dpa.checked, note: note.value.trim()}); rowsEl.append(row);
  };
  for (const p of a.processors) addRow(p); if (!a.processors.length) addRow();
  Modal.open('Veri işleyenler ve alıcılar', h('div', {}, h('p', {class: 'intro', text: 'Bu faaliyette kişisel veriyi işleyen veya alan tedarikçiler. Veri işleyenle veri işleme sözleşmesi (DPA) imzalanmış olmalı.'}), rowsEl,
    btn('+ Satır', () => addRow(), 'ghost small')),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => { const items = [...rowsEl.children].map(r => r.read()).filter(x => x.supplier_id); Modal.close(); await link({processors: items}); })], true);
}

// ------------------------------------------------------------------ periyodik imha
DETAILS.disposal_runs = id => Router.go('disposal/' + id);
PAGES.disposal = async function disposalPage(parts) {
  const id = Number(parts[1]); const r = await api(`disposal_runs/${id}/context`); const reload = () => render();
  const st = r.state;
  setPage(r.title, `${r.code} · ${META.option('disposal_runs', 'status', r.status)} · planlanan ${fmt.date(r.planned_date)}`, [
    r.can_edit ? btn('Kapsamı oluştur', async () => { await api(`disposal_runs/${id}/generate`, {method: 'POST', body: {}}); toast('Saklama kuralı bağlı tablolar eklendi'); reload(); }, 'secondary') : null,
    r.can_edit ? btn('Tamamla', () => {
      const sum = h('textarea', {id: 'dspSum', value: r.summary || ''});
      Modal.open('Periyodik imhayı tamamla', h('div', {}, h('p', {class: 'intro', text: 'Tamamlanan kayıt değiştirilemez ve en az 3 yıl saklanır. Ne, hangi yöntemle, kim tarafından imha edildi?'}),
        h('label', {class: 'field', for: 'dspSum'}, h('span', {text: 'İmha özeti'}), h('div', {class: 'control'}, sum))),
      [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Tamamla', async () => { await api(`disposal_runs/${id}/complete`, {method: 'POST', body: {summary: sum.value}}); Modal.close(); toast('İmha kaydı tamamlandı'); reload(); })]);
    }) : null,
    r.can_edit ? btn('Düzenle', () => recordForm('disposal_runs', r, {only: ['title', 'planned_date', 'owner', 'summary', 'evidence_id'], onsaved: reload}), 'ghost') : null],
  [['KVKK Panosu', 'privacy'], ['Periyodik İmha', 'r/disposal_runs']]);
  const pending = r.items.filter(i => i.outcome === 'pending').length;
  const rowsEl = r.items.map(i => h('tr', {class: r.can_edit ? 'link' : '', onclick: () => r.can_edit && recordForm('disposal_items', i, {only: ['outcome', 'method', 'record_count', 'note'], title: `İmha: ${i.table_name}`, onsaved: reload})},
    h('td', {}, h('strong', {text: dgPath(i.schema_name, i.table_name)}), h('div', {class: 'cell-sub', text: i.source_name})),
    h('td', {class: 'small', text: i.rule_code ? `${i.rule_code} · ${i.period_value} ${META.option('retention_rules', 'period_unit', i.period_unit)} (${i.trigger_event})` : '—'}),
    h('td', {}, display('disposal_items', 'method', i.method)), h('td', {}, display('disposal_items', 'outcome', i.outcome)),
    h('td', {class: 'num', text: i.record_count === null || i.record_count === undefined ? '—' : fmt.num(i.record_count)}), h('td', {class: 'small', text: i.note || ''})));
  content(
    h('div', {class: 'grid wide-left'},
      h('div', {class: 'panel'}, statStrip([['Kalem', fmt.num(r.items.length)], ['Bekleyen', fmt.num(pending), pending ? 'warn' : ''],
        ['İmha edilen kayıt', fmt.num(r.items.reduce((n, i) => n + (i.record_count || 0), 0))]]),
        r.summary ? h('p', {class: 'small', text: r.summary}) : null, r.status === 'completed' ? h('div', {class: 'notice success', text: `Tamamlandı: ${r.performed_by} · ${fmt.datetime(r.completed_at)}. Kayıt değiştirilemez.`}) : null),
      h('div', {class: 'panel'}, h('h3', {text: 'Periyodik imha takvimi'}), kv([['Aralık', `en çok ${st.interval_months} ay`], ['Son tamamlanan', st.last ? `${st.last.code} · ${fmt.date(st.last.completed_at)}` : 'Yok'],
        ['Sonraki son tarih', st.next_due ? h('span', {class: st.overdue ? 'late' : '', text: fmt.date(st.next_due)}) : '—'], ['Kanıt', r.evidence ? h('a', {href: '#/r/evidence/' + r.evidence.id, text: `${r.evidence.code} ${r.evidence.title}`}) : '—']]))),
    r.items.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Tablo', 'Saklama kuralı', 'Yöntem', 'Sonuç', 'Kayıt', 'Not'].map(x => h('th', {text: x})))), h('tbody', {}, rowsEl))) :
      empty('Kalem yok', 'Saklama kuralı bağlı tabloları eklemek için "Kapsamı oluştur" düğmesini kullanın. Tablolara kural, tablo ekranındaki Düzenle ile bağlanır.'));
};

// ------------------------------------------------------------------ veri talepleri
const REQUEST_FIELDS = ['kind', 'table_id', 'purpose', 'activity_id', 'environment', 'access_until', 'org_unit_id'];
CREATE.data_requests = defaults => recordForm('data_requests', null, {only: REQUEST_FIELDS, defaults, title: 'Yeni veri talebi',
  extra: h('div', {class: 'notice wide', text: 'Kişisel veri içeren tabloya erişim ve veri çıkarma için işleme faaliyeti (amaç ve hukuki sebep) zorunludur. Talebi verinin sahibi onaylar, teknik sorumlu uygular.'}),
  onsaved: r => { refreshList('data_requests'); openRecord('data_requests', r.id); }});
DETAILS.data_requests = async function requestPanel(id) {
  let r; try { r = await api(`data_requests/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const act = (action, title, label, required) => {
    const note = h('textarea', {id: 'reqNote'});
    const run = async () => { await api(`data_requests/${id}/${action}`, {method: 'POST', body: {note: note.value}}); Modal.close(); toast('Kaydedildi'); refreshList('data_requests'); DETAILS.data_requests(id); };
    if (!required) return run();
    Modal.open(title, h('label', {class: 'field', for: 'reqNote'}, h('span', {text: label}), h('div', {class: 'control'}, note)), [btn('Vazgeç', () => Modal.close(), 'secondary'), btn(title, run)]);
  };
  const body = h('div', {},
    h('div', {class: 'chips'}, display('data_requests', 'kind', r.kind), display('data_requests', 'status', r.status)),
    section('Talep', kv([['Tablo', h('a', {href: '#/catalog/table/' + r.table.id, text: `${r.table.source} / ${r.table.name}`})], ['Amaç', r.purpose],
      ['İşleme faaliyeti', r.activity ? h('a', {href: '#/activity/' + r.activity.id, text: `${r.activity.code} ${r.activity.name}`}) : null],
      ['Hedef ortam', r.environment], ['Erişim bitişi', r.access_until ? fmt.date(r.access_until) : null], ['Talep eden', r.requested_by], ['Tarih', fmt.datetime(r.created_at)]])),
    section('Kolonlar', h('div', {}, r.columns.length ? h('div', {class: 'chips'}, r.columns.map(c => pill(c.name, c.personal_data && c.personal_data !== 'none' ? 'warn' : 'neutral'))) : h('div', {class: 'muted small', text: 'Tüm tablo'}),
      r.personal_columns.length ? h('div', {class: 'small muted', text: `Tablodaki kişisel veri kolonları: ${r.personal_columns.map(c => c.name).join(', ')}`}) : null),
      r.status === 'requested' && r.can.cancel ? btn('Kolonları seç', async () => {
        const cols = (await api(`data_tables/${r.table.id}/context`)).columns.filter(c => c.status === 'active');
        const chosen = await pickMany('Talep edilen kolonlar', cols.map(c => ({...c, title: c.name})), r.columns.map(c => c.id), {label: c => c.name + (c.business_name ? ' — ' + c.business_name : '') + (c.personal_data && c.personal_data !== 'none' ? ' (kişisel)' : '')});
        if (chosen) { await api(`data_requests/${id}/columns`, {method: 'POST', body: {column_ids: chosen}}); DETAILS.data_requests(id); }
      }, 'ghost small') : null),
    section('Sorumlular', kv([['Onaylayacak (veri sahibi)', r.people.owner || 'Atanmamış — veri yönetişimi yöneticisi'], ['Uygulayacak (teknik sorumlu)', r.people.custodian || 'Atanmamış — veri yönetişimi yöneticisi']])),
    r.approver ? section('Karar', kv([['Karar veren', r.approver], ['Zaman', fmt.datetime(r.decided_at)], ['Not', r.decision_note]])) : null,
    r.fulfilled_by ? section('Uygulama', kv([['Uygulayan', r.fulfilled_by], ['Zaman', fmt.datetime(r.fulfilled_at)], ['Not', r.fulfillment_note]])) : null);
  Drawer.open(`${r.code} · ${META.option('data_requests', 'kind', r.kind)}`, body, [
    r.can.decide ? btn('Onayla', () => act('approve', 'Onayla', 'Not (isteğe bağlı)', false)) : null,
    r.can.decide ? btn('Reddet', () => act('reject', 'Reddet', 'Ret gerekçesi', true), 'secondary') : null,
    r.can.fulfill ? btn('Uygulandı', () => act('fulfill', 'Uygulandı', 'Uygulama notu (ör. maskeleme yöntemi, verilen rol)', true)) : null,
    r.can.cancel ? btn('İptal', () => act('cancel', 'İptal', 'Not', false), 'ghost') : null], 'Veri talebi');
};

// ------------------------------------------------------------------ ilgili kişi başvuruları
const SUBJECT_FIELDS = ['received_on', 'channel', 'request_type', 'subject_group_id', 'subject_reference', 'identity_verified', 'description', 'owner'];
CREATE.subject_requests = defaults => recordForm('subject_requests', null, {only: SUBJECT_FIELDS, defaults: {received_on: today(), owner: S.me.username, ...defaults}, title: 'Yeni ilgili kişi başvurusu',
  extra: h('div', {class: 'notice wide', text: 'Başvuru en geç 30 gün içinde ücretsiz sonuçlandırılır (KVKK md. 13). Veri en aza indirme için ad soyad yerine CRM kaydı veya başvuru numarası gibi bir iç referans yazın.'}),
  onsaved: r => { refreshList('subject_requests'); openRecord('subject_requests', r.id); }});
DETAILS.subject_requests = async function subjectPanel(id) {
  let r; try { r = await api(`subject_requests/${id}/context`); } catch (e) { toast(e.message, false); return; }
  await loadRefs('subject_requests');
  const reload = () => { refreshList('subject_requests'); DETAILS.subject_requests(id); };
  const open = !['answered', 'rejected'].includes(r.status); const can = canWrite('subject_requests');
  const close = status => {
    const dt = h('input', {type: 'date', id: 'srDate', value: today(), max: today()}); const sum = h('textarea', {id: 'srSum'});
    const idv = h('input', {type: 'checkbox', id: 'srId', checked: !!r.identity_verified});
    Modal.open(status === 'answered' ? 'Yanıtlandı' : 'Reddedildi', h('div', {},
      h('label', {class: 'field', for: 'srDate'}, h('span', {text: 'Yanıt tarihi'}), h('div', {class: 'control'}, dt)),
      h('label', {class: 'toggle', for: 'srId'}, idv, h('span', {text: 'Başvuru sahibinin kimliği doğrulandı'})),
      h('label', {class: 'field', for: 'srSum'}, h('span', {text: status === 'answered' ? 'Yanıt özeti (ne verildi, hangi kanalla)' : 'Ret gerekçesi'}), h('div', {class: 'control'}, sum))),
    [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => {
      await api('subject_requests/' + id, {method: 'PATCH', body: {status, response_date: dt.value, response_summary: sum.value.trim() || null, identity_verified: idv.checked ? 1 : 0}}); Modal.close(); toast('Kaydedildi'); reload();
    })]);
  };
  const clock = open ? h('div', {class: 'countdown ' + (r.late ? 'bad' : r.remaining_days <= 5 ? 'warn' : 'good')}, h('span', {class: 'big', text: r.late ? `${-r.remaining_days} gün gecikti` : `${r.remaining_days} gün kaldı`}),
    h('span', {text: `Yanıt için son gün: ${fmt.date(r.due_date)} (başvurudan itibaren 30 gün, KVKK md. 13)`})) : h('div', {class: 'notice ' + (r.late ? 'warn' : 'success'), text: `${META.option('subject_requests', 'status', r.status)} · ${fmt.date(r.response_date)}${r.late ? ' (süre aşıldı)' : ' (süresinde)'}`});
  const tablesSec = section(`İncelenen veri varlıkları (${r.tables.length})`, h('div', {}, r.tables.length ? h('ul', {class: 'mini'}, r.tables.map(t => h('li', {}, h('a', {href: '#/catalog/table/' + t.id, text: dgPath(t.schema_name, t.name)}), h('span', {class: 'cell-sub', text: t.source_name})))) :
    h('div', {class: 'muted small', text: 'Başvuru sahibinin verisinin arandığı tabloları ekleyin; ilgili kişi grubunu içeren işleme faaliyetlerinin tabloları önerilir.'})),
    can && open ? btn('Tabloları seç', async () => {
      const sug = await api(`subject_requests/${id}/suggest-tables`);
      const items = [...new Map([...r.tables, ...sug].map(t => [t.id, {...t, title: dgPath(t.schema_name, t.name)}])).values()];
      if (!items.length) { const ids = await searchPicker('İncelenen tablolar', {kind: 'tables', label: x => dgPath(x.schema_name, x.name), sub: x => x.source_name}); if (ids) { await api(`subject_requests/${id}/tables`, {method: 'POST', body: {table_ids: [...r.tables.map(t => t.id), ...ids]}}); reload(); } return; }
      const chosen = await pickMany('İncelenen tablolar', items, r.tables.map(t => t.id), {label: t => `${t.source_name} / ${dgPath(t.schema_name, t.name)}`, intro: 'Önerilenler: bu ilgili kişi grubunu içeren işleme faaliyetlerinin tabloları.'});
      if (chosen) { await api(`subject_requests/${id}/tables`, {method: 'POST', body: {table_ids: chosen}}); reload(); }
    }, 'ghost small') : null);
  const body = h('div', {}, clock,
    section('Başvuru', kv([['Tür', display('subject_requests', 'request_type', r.request_type)], ['Kanal', display('subject_requests', 'channel', r.channel)], ['Başvuru tarihi', fmt.date(r.received_on)],
      ['İlgili kişi grubu', display('subject_requests', 'subject_group_id', r.subject_group_id)], ['Referans', r.subject_reference], ['Kimlik doğrulandı', r.identity_verified ? pill('Evet', 'good') : pill('Hayır', 'warn')],
      ['İçerik', r.description], ['Sorumlu', r.owner]])),
    !open ? section('Yanıt', kv([['Yanıt tarihi', fmt.date(r.response_date)], ['Özet', r.response_summary]])) : null, tablesSec);
  Drawer.open(`${r.code} · ${META.option('subject_requests', 'request_type', r.request_type)}`, body, can && open ? [
    r.status === 'received' ? btn('İncelemeye al', () => api('subject_requests/' + id, {method: 'PATCH', body: {status: 'in_progress'}}).then(reload), 'secondary') : null,
    btn('Yanıtlandı', () => close('answered')), btn('Reddet', () => close('rejected'), 'secondary'),
    btn('Düzenle', () => recordForm('subject_requests', r, {only: SUBJECT_FIELDS, onsaved: reload}), 'ghost')] : [], 'İlgili kişi başvurusu');
};

// ------------------------------------------------------------------ VKED
DETAILS.dpias = async function dpiaPanel(id) {
  let d; try { d = await api('dpias/' + id); } catch (e) { toast(e.message, false); return; }
  await loadRefs('dpias');
  const reload = () => { refreshList('dpias'); DETAILS.dpias(id); };
  const act = async (action, note) => { await api(`dpias/${id}/${action}`, {method: 'POST', body: {note}}); toast('Kaydedildi'); reload(); };
  const mine = [S.me.username, S.me.display_name].includes(d.prepared_by); const can = canWrite('dpias');
  const body = h('div', {}, h('div', {class: 'chips'}, display('dpias', 'status', d.status), d.residual_risk ? display('dpias', 'residual_risk', d.residual_risk) : null, d.decision ? display('dpias', 'decision', d.decision) : null),
    d.review_note && d.status === 'rejected' ? h('div', {class: 'notice warn', text: 'İade: ' + d.review_note}) : null,
    section('Değerlendirme', kv([['İşleme faaliyeti', h('a', {href: '#/activity/' + d.activity_id, text: display('dpias', 'activity_id', d.activity_id)})], ['Gereklilik ve orantılılık', d.necessity],
      ['İlgili kişiler için riskler', d.risks], ['Önlemler', d.measures], ['Hazırlayan', d.prepared_by], ['Onaylayan', d.approver ? `${d.approver} · ${fmt.datetime(d.approved_at)}` : null]])));
  Drawer.open(`${d.code} · ${d.title}`, body, can ? [
    ['draft', 'rejected'].includes(d.status) ? btn('Düzenle', () => recordForm('dpias', d, {only: ['title', 'necessity', 'risks', 'measures', 'residual_risk', 'decision'], onsaved: reload}), 'secondary') : null,
    ['draft', 'rejected'].includes(d.status) ? btn('Onaya gönder', () => act('submit')) : null,
    d.status === 'in_review' && !mine ? btn('Onayla', () => act('approve')) : null,
    d.status === 'in_review' && !mine ? btn('İade et', () => { const n = h('textarea', {id: 'dpNote'}); Modal.open('İade et', h('label', {class: 'field', for: 'dpNote'}, h('span', {text: 'Gerekçe'}), h('div', {class: 'control'}, n)),
      [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('İade et', async () => { await act('reject', n.value); Modal.close(); })]); }, 'secondary') : null] : [], 'VKED');
};

// ------------------------------------------------------------------ tablo, kolon, ihlal ve Tedarikçi 360 eklentileri
TABLE_ACTIONS.push((t, reload) => canWrite('data_requests') ? btn('Veri talebi', () => CREATE.data_requests({table_id: t.id}), 'ghost') : null);
TABLE_EXTRAS.push((t, reload) => {
  const host = h('div', {class: 'panel pv-panel'}, h('div', {class: 'muted small', text: 'Kişisel veri ve risk bilgisi yükleniyor…'}));
  api(`data_tables/${t.id}/risk`).then(r => {
    const can = t.can_edit;
    const cats = [...new Map(r.column_categories.map(k => [k.id, k])).values()];
    const title = h('h3', {}, 'Kişisel veri ve risk ', levelPill(r.level), h('span', {class: 'sub', text: `  ${r.score} puan (etki ${r.impact} × olasılık ${r.likelihood})`}));
    const actions = h('div', {class: 'toolbar'},
      can ? btn('Örnek veriyle doğrula', () => sampleDialog(t, reload), 'secondary small') : null,
      hasModule('risks') && canWrite('supplier_risks') && r.personal && !r.risks.some(x => x.status !== 'closed') ? btn('Risk kaydına aktar', async () => {
        const res = await api(`data_tables/${t.id}/raise-risk`, {method: 'POST', body: {}}); toast(`${res.code} açıldı`); reload();
      }, 'ghost small') : null);
    const left = h('div', {}, h('ul', {class: 'mini plain'}, r.factors.map(f => h('li', {class: 'small', text: f}))),
      r.gaps.length ? h('div', {class: 'chips'}, r.gaps.map(g => pill(g, 'warn'))) : h('div', {class: 'small muted', text: 'Yönetişim açığı yok.'}));
    const right = kv([
      ['Kategoriler', cats.length ? h('span', {class: 'chips'}, cats.map(k => pill(k.name, k.special ? 'bad' : 'neutral'))) : 'Yok'],
      ['İşleme faaliyetleri', r.activities.length ? h('span', {class: 'chips'}, r.activities.map(a => h('a', {class: 'chip', href: '#/activity/' + a.id, text: `${a.code} ${a.name}`}))) : (r.personal ? pill('Envanterde değil', 'bad') : '—')],
      ['Saklama kuralı', r.retention_rule ? `${r.retention_rule.code} · ${r.retention_rule.period_value} ${META.option('retention_rules', 'period_unit', r.retention_rule.period_unit)} (${r.retention_rule.trigger_event})` : '—'],
      ['Karar bekleyen öneri', r.suggestions ? h('a', {href: `#/discovery?table=${t.id}`, text: `${r.suggestions} öneri`}) : 'Yok'],
      r.risks.length ? ['Risk kaydı', h('span', {class: 'chips'}, r.risks.map(x => h('a', {class: 'chip', href: '#/r/supplier_risks/' + x.id, text: x.code})))] : null]);
    host.replaceChildren(h('div', {class: 'panel-title'}, title, actions), h('div', {class: 'grid two'}, left, right));
  }).catch(() => host.remove());
  return host;
});
COLUMN_EXTRAS.push((c, reload) => {
  const host = h('div');
  api(`data_columns/${c.id}/privacy`).then(p => {
    const decide = (s, accept) => api(`pii_suggestions/${s.id}/${accept ? 'accept' : 'reject'}`, {method: 'POST', body: {}}).then(() => { toast(accept ? 'Kabul edildi' : 'Reddedildi'); reload(); });
    host.replaceChildren(section('Kişisel veri kategorileri', h('div', {},
      p.categories.length ? h('div', {class: 'chips'}, p.categories.map(k => pill(k.name, k.special ? 'bad' : 'neutral'))) : h('div', {class: 'muted small', text: 'Kategori yok'}),
      p.suggestions.map(s => h('div', {class: 'notice small'}, h('strong', {text: `Öneri: ${s.category_name} (${pct(s.confidence)}) `}), s.evidence || '',
        c.can_edit ? h('div', {class: 'toolbar'}, btn('Kabul', () => decide(s, true), 'small'), btn('Reddet', () => decide(s, false), 'ghost small')) : null)),
      p.activities.length ? h('div', {class: 'small'}, 'İşleme faaliyetleri: ', p.activities.map(a => h('a', {class: 'chip', href: '#/activity/' + a.id, text: a.code}))) : null),
    c.can_edit ? btn('Düzenle', async () => {
      const all = (await list('personal_data_categories', true)).filter(k => k.active);
      const chosen = await pickMany('Kolonun kişisel veri kategorileri: ' + c.name, all, p.categories.map(k => k.id), {label: k => k.name + (k.special ? ' (özel nitelikli)' : ''),
        intro: 'Kategori seçilince kolon kişisel veri olarak işaretlenir ve sınıfı en az "Gizli" olur.'});
      if (chosen) { await api(`data_columns/${c.id}/categories`, {method: 'POST', body: {category_ids: chosen}}); toast('Kaydedildi'); reload(); }
    }, 'ghost small') : null));
  }).catch(() => {});
  return host;
});
function breachAssetsSection(b, reload) {
  const host = h('div');
  api(`privacy_breaches/${b.id}/data-assets`).then(d => {
    const fill = () => {
      const body = {data_categories: d.categories.map(k => k.name).join(', ') || null, special_categories: d.special ? 1 : 0,
        subject_groups: d.subject_groups.map(g => g.name).join(', ') || b.subject_groups || null};
      if (!b.subjects_count && d.max_rows) body.subjects_count = d.max_rows;
      return api('privacy_breaches/' + b.id, {method: 'PATCH', body}).then(() => { toast('Kayıt güncellendi'); reload(); });
    };
    host.replaceChildren(section(`Etkilenen veri varlıkları (${d.tables.length})`, h('div', {},
      d.tables.length ? h('ul', {class: 'mini'}, d.tables.map(t => h('li', {}, h('a', {href: '#/catalog/table/' + t.id, text: `${t.source_name} / ${dgPath(t.schema_name, t.name)}`}),
        t.row_count ? h('span', {class: 'cell-sub', text: `${fmt.num(t.row_count)} satır`}) : null))) : h('div', {class: 'muted small', text: 'Katalogdan etkilenen tabloları seçin; kategoriler, özel nitelik ve ilgili kişi grupları önerilir.'}),
      d.tables.length ? h('div', {class: 'notice small'}, h('strong', {text: 'Katalogdan çıkan: '}), [d.categories.map(k => k.name).join(', ') || 'kategori yok', d.special ? 'özel nitelikli veri VAR' : null,
        d.subject_groups.length ? 'kişi grupları: ' + d.subject_groups.map(g => g.name).join(', ') : null, d.max_rows ? `en büyük tablo ${fmt.num(d.max_rows)} satır` : null].filter(Boolean).join(' · ')) : null),
    d.can_edit ? h('div', {class: 'toolbar'}, btn('Tabloları seç', async () => {
      const ids = await searchPicker('Etkilenen tablolar', {kind: 'tables', label: x => dgPath(x.schema_name, x.name), sub: x => [x.source_name, x.business_name].filter(Boolean).join(' · ')});
      if (ids && ids.length) { await api(`privacy_breaches/${b.id}/data-assets`, {method: 'POST', body: {table_ids: [...new Set([...d.tables.map(t => t.id), ...ids])]}}); reload(); }
    }, 'ghost small'), d.tables.length ? btn('Kategorileri kayda aktar', fill, 'ghost small') : null) : null));
  }).catch(() => {});
  return host;
}
SUPPLIER_TABS.push({key: 'privacy', label: 'Kişisel veri', visible: () => hasModule('datagov'), render: async id => {
  const d = await api(`suppliers/${id}/privacy`);
  return h('div', {},
    d.missing_dpa ? h('div', {class: 'notice warn', text: `${d.missing_dpa} faaliyette veri işleyen olarak yer alıyor ama veri işleme sözleşmesi (DPA) işaretli değil.`}) : null,
    section('İşleme faaliyetleri', d.activities.length ? h('ul', {class: 'mini'}, d.activities.map(a => h('li', {class: 'link', onclick: () => { Drawer.close(); Router.go('activity/' + a.id); }},
      h('div', {class: 'chips'}, h('strong', {text: `${a.code} · ${a.name}`}), pill(META.option('processing_processors', 'role', a.role), 'neutral'), a.role === 'processor' ? (a.dpa_signed ? pill('DPA var', 'good') : pill('DPA yok', 'bad')) : null),
      h('span', {class: 'cell-sub', text: [a.categories.join(', '), a.foreign_transfer ? 'yurt dışı: ' + (a.transfer_countries || '?') : null].filter(Boolean).join(' · ')})))) :
      h('div', {class: 'muted small', text: 'Bu tedarikçi bir işleme faaliyetinde veri işleyen veya alıcı olarak tanımlanmamış.'})),
    section('Barındırdığı veri kaynakları', d.sources.length ? h('ul', {class: 'mini'}, d.sources.map(s => h('li', {class: 'link', onclick: () => { Drawer.close(); Router.go('datasource/' + s.id); }}, h('strong', {text: s.name}),
      h('span', {class: 'cell-sub', text: META.option('data_sources', 'platform', s.platform)})))) : h('div', {class: 'muted small', text: 'Yok'})));
}});

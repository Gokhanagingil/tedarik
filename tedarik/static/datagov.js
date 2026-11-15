'use strict';
/* Veri yönetişimi ekranları (K-028): panel, iş sözlüğü ve terim sayfası, veri kataloğu, tablo sayfası ve kolon paneli,
   veri kaynağı sayfası ve içe aktarım sihirbazı, sahiplik matrisi. app.js ve pages.js yardımcılarını kullanır;
   dış kütüphane ve satır içi stil yok (CSP). */

const DG = {
  status: {draft: ['Taslak', 'warn'], in_review: ['Onayda', 'purple'], approved: ['Onaylı', 'good'], retired: ['Kullanım dışı', 'neutral']},
  from: {table: 'tablodan', domain: 'veri alanından', source: 'kaynaktan', column: 'kolondan'},
  letters: 'ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ',
};
const dgPct = (a, b) => (b ? Math.round(100 * (a || 0) / b) : null);
const dgPath = (...parts) => parts.filter(Boolean).join('.');
const option = (field, value) => META.option('data_columns', field, value);
function termPill(t) { const [label, cls] = DG.status[t.status] || [t.status, 'neutral']; return pill(label, cls); }
function coverBar(done, total) {
  const v = dgPct(done, total);
  return h('div', {class: 'cover'}, progressBar(v || 0), h('span', {class: 'small muted', text: total ? `${fmt.num(done || 0)}/${fmt.num(total)} · %${v}` : '—'}));
}
function personText(value, from) {
  if (!value) return h('span', {class: 'muted', text: 'Atanmamış'});
  return h('span', {}, value, from && from !== 'table' && from !== 'column' ? h('span', {class: 'muted small', text: ` (${DG.from[from]})`}) : null);
}
function classPill(value, from) {
  if (!value) return h('span', {class: 'muted', text: 'Belirlenmemiş'});
  return h('span', {}, pill(META.option('data_tables', 'classification', value), tone(value)),
    from && from !== 'column' ? h('span', {class: 'muted small', text: ` (${DG.from[from]})`}) : null);
}
function personalPill(value) {
  if (!value) return h('span', {class: 'muted', text: 'Değerlendirilmedi'});
  return value === 'none' ? h('span', {class: 'muted', text: 'Yok'}) : pill(option('personal_data', value), value === 'special' ? 'bad' : 'warn');
}
async function gzipBase64(file) {
  if (typeof CompressionStream === 'undefined' || file.size < 512 * 1024 || /\.xlsx$/i.test(file.name)) return {content_base64: await fileToBase64(file)};
  const buf = new Uint8Array(await new Response(file.stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer());
  let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {content_base64: btoa(bin), compressed: 'gzip'};
}
function copyButton(text) {
  return btn('Kopyala', async () => { try { await navigator.clipboard.writeText(text); toast('Panoya kopyalandı'); } catch (e) { toast('Kopyalanamadı; metni seçip kopyalayın', false); } }, 'ghost small');
}

// ------------------------------------------------------------------ katalog araması (panel ve katalog üstünde)
function catalogSearch({sourceId, placeholder} = {}) {
  const input = h('input', {type: 'search', class: 'searchbar big', placeholder: placeholder || 'Terim, tablo veya kolon arayın (ör. müşteri, KUNNR, TCKN)', 'aria-label': 'Katalogda ara', autocomplete: 'off'});
  const box = h('div', {class: 'dg-results hidden', role: 'listbox'});
  const group = (title, items, render) => items.length ? h('div', {class: 'dg-group'}, h('div', {class: 'choice-group', text: title}), items.map(render)) : null;
  const row = (main, sub, go) => { const b = h('button', {type: 'button', class: 'dg-hit'}, h('strong', {text: main}), sub ? h('span', {class: 'cell-sub', text: sub}) : null); b.addEventListener('click', () => { box.classList.add('hidden'); go(); }); return b; };
  const run = debounce(async () => {
    const q = input.value.trim(); if (q.length < 2) { box.classList.add('hidden'); return; }
    const r = await api(`datagov/search?q=${encodeURIComponent(q)}${sourceId ? '&source_id=' + sourceId : ''}`).catch(() => null); if (!r) return;
    const nodes = [
      group('Sözlük terimleri', r.terms, t => row(`${t.name}${t.abbreviation ? ' (' + t.abbreviation + ')' : ''}`, `${t.code} · ${(DG.status[t.status] || [t.status])[0]} · ${(t.definition || '').slice(0, 90)}`, () => Router.go('glossary/' + t.id))),
      group('Tablolar', r.tables, t => row(t.business_name ? `${t.name} — ${t.business_name}` : t.name, `${t.source_name}${t.schema_name ? ' / ' + t.schema_name : ''}`, () => Router.go('catalog/table/' + t.id))),
      group('Kolonlar', r.columns, col => row(col.business_name ? `${col.name} — ${col.business_name}` : col.name, `${col.source_name} / ${dgPath(col.schema_name, col.table_name)} · ${col.data_type || ''}`, () => columnPanel(col.id)))].filter(Boolean);
    box.replaceChildren(...(nodes.length ? nodes : [h('div', {class: 'muted small dg-none', text: 'Eşleşen terim, tablo veya kolon yok'})]));
    box.classList.remove('hidden');
  }, 220);
  input.addEventListener('input', run);
  input.addEventListener('keydown', e => { if (e.key === 'Escape') box.classList.add('hidden'); });
  return h('div', {class: 'dg-search'}, input, box);
}

// ------------------------------------------------------------------ panel
PAGES.datagov = async function datagovPage() {
  const d = await api('datagov/overview');
  setPage('Veri Yönetişimi', 'Hangi verinin ne anlama geldiği, nerede durduğu ve kimin sorumluluğunda olduğu. Kaynaklar dosyayla içeri alınır; iş sözlüğü onaylı tanımları tutar.', [
    btn('Yol haritası', () => Router.go('roadmap?m=datagov'), 'secondary'),
    canWrite('data_sources') ? btn('+ Veri kaynağı', () => createRecord('data_sources')) : null]);
  const t = d.totals, cv = d.coverage;
  if (!t.sources) {
    const step = (n, title, text, action) => h('div', {class: 'dg-step'}, h('span', {class: 'dg-num', text: n}), h('div', {}, h('strong', {text: title}), h('p', {class: 'small muted', text}), action));
    content(h('div', {class: 'panel'}, h('h3', {text: 'Veri sözlüğüne üç adımda başlayın'}),
      h('div', {class: 'dg-steps'},
        step(1, 'Veri alanlarını tanımlayın', 'Müşteri, Satış, Finans gibi alanlar; her alanın sorumlu birimi, veri sahibi ve veri yöneticisi.', canWrite('data_domains') ? btn('+ Veri alanı', () => createRecord('data_domains'), 'secondary small') : null),
        step(2, 'Kaynağı ekleyip içe aktarın', 'SAP HANA, ServiceNow, Dynamics 365 veya Power BI. Kaynağın ekranındaki hazır sorguyu çalıştırıp çıktısını yükleyin; bağlayıcı beklemeye gerek yok.', canWrite('data_sources') ? btn('+ Veri kaynağı', () => createRecord('data_sources'), 'secondary small') : null),
        step(3, 'Terimleri yazıp kolonlara bağlayın', 'Onaylı tanımlar kolonlara bağlandıkça "bu kolon ne anlama geliyor" ve "bu terim nerede kullanılıyor" soruları yanıtlanır.', btn('İş sözlüğü', () => Router.go('glossary'), 'secondary small')))));
    return;
  }
  const docPct = dgPct(cv.documented, cv.columns), ownPct = dgPct(cv.owned, cv.tables), stwPct = dgPct(cv.stewarded, cv.tables);
  const live = d.terms.draft + d.terms.in_review + d.terms.approved;
  const att = d.attention;
  const attention = [
    att.terms_to_review.length ? section(`Onay bekleyen terimler (${att.terms_to_review.length})`, recordList('glossary_terms', att.terms_to_review.map(x => ({...x, title: x.name})),
      {sub: x => x.pending_by ? `Değişiklik önerisi · ${x.pending_by}` : `Yeni terim · ${x.submitted_by || ''}`, open: x => Router.go('glossary/' + x.id)})) : null,
    att.personal_unclassified.length ? section('Gizli sınıfın altında kalan kişisel veri', recordList('data_columns', att.personal_unclassified.map(x => ({id: x.id, source_name: x.source_name, name: `${x.table_name}.${x.name}`})),
      {sub: x => x.source_name, open: x => columnPanel(x.id)})) : null,
    att.unowned_tables.length ? section('Sahibi olmayan tablolar (en büyükler)', recordList('data_tables', att.unowned_tables.map(x => ({id: x.id, source_name: x.source_name, column_count: x.column_count, name: x.name})),
      {sub: x => `${x.source_name} · ${x.column_count} kolon`, open: x => Router.go('catalog/table/' + x.id)}), btn('Tümü', () => Router.go('catalog?f=unowned'), 'ghost small')) : null,
    att.review_overdue.length ? section('Gözden geçirme tarihi geçen terimler', recordList('glossary_terms', att.review_overdue.map(x => ({...x, title: x.name})),
      {sub: x => `${x.owner || 'sahipsiz'} · ${fmt.date(x.review_date)}`, open: x => Router.go('glossary/' + x.id)})) : null].filter(Boolean);
  const sources = h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kaynak', 'Platform', 'Tablo', 'Tanımlı kolon', 'Son içe aktarım'].map(x => h('th', {text: x})))),
    h('tbody', {}, d.sources.map(s => h('tr', {class: 'link', onclick: () => Router.go('datasource/' + s.id)},
      h('td', {}, h('strong', {text: s.name}), h('div', {class: 'cell-sub', text: s.code})), h('td', {}, pill(META.option('data_sources', 'platform', s.platform), 'neutral')),
      h('td', {class: 'num', text: fmt.num(s.tables)}), h('td', {}, coverBar(s.documented, s.columns)),
      h('td', {text: s.last_import_at ? fmt.datetime(s.last_import_at) : 'İçe aktarılmadı'}))))));
  content(
    h('div', {class: 'panel dg-hero'}, catalogSearch()),
    h('div', {class: 'grid four'},
      metric('Veri kaynağı', fmt.num(t.sources), `${t.domains} veri alanı`, '', () => Router.go('r/data_sources')),
      metric('Tablo', fmt.num(t.tables), `${fmt.num(cv.certified)} onaylı veri seti`, '', () => Router.go('catalog')),
      metric('Kolon', fmt.num(t.columns), `${fmt.num(cv.personal)} kişisel · ${fmt.num(cv.critical)} kritik`, '', () => Router.go('catalog?f=personal')),
      metric('Onaylı terim', fmt.num(t.approved_terms), `${d.terms.in_review + d.terms.pending_changes} onay bekliyor`, d.terms.in_review + d.terms.pending_changes ? 'warn' : '', () => Router.go('glossary'))),
    h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Kapsama'}), h('span', {class: 'muted small', text: 'Kolon "tanımlı" sayılır: iş adı, iş açıklaması veya sözlük terimi varsa. Kaynaktaki açıklama tek başına iş tanımı değildir.'})),
      h('div', {class: 'gauges'},
        gauge(docPct, 'Tanımlı kolon', {suffix: '%', sub: `${fmt.num(cv.documented)} / ${fmt.num(cv.columns)}`}),
        gauge(ownPct, 'Sahibi belli tablo', {suffix: '%', sub: `${fmt.num(cv.owned)} / ${fmt.num(cv.tables)} (devralma dahil)`}),
        gauge(stwPct, 'Veri yöneticisi atanmış', {suffix: '%', sub: `${fmt.num(cv.stewarded)} / ${fmt.num(cv.tables)}`}),
        gauge(dgPct(d.terms.approved, live), 'Onaylı terim oranı', {suffix: '%', sub: `${d.terms.approved} onaylı · ${d.terms.draft} taslak`}))),
    h('div', {class: 'grid wide-left'},
      panel('Kaynaklar', sources, canWrite('data_sources') ? btn('+ Kaynak', () => createRecord('data_sources'), 'ghost small') : null),
      panel('Dikkat isteyenler', attention.length ? h('div', {}, attention) : empty('Bekleyen iş yok', 'Onay bekleyen terim, sahipsiz tablo veya düşük sınıflı kişisel veri bulunmuyor.'))),
    h('div', {class: 'grid two'},
      panel('Son şema değişiklikleri', d.changes.length ? h('ul', {class: 'mini'}, d.changes.map(x => h('li', {class: x.table_id ? 'link' : '', onclick: () => x.table_id && Router.go('catalog/table/' + x.table_id)},
        h('div', {class: 'chips'}, pill(META.option('catalog_changes', 'change', x.change), tone(x.change)), h('strong', {text: x.object_name})),
        h('span', {class: 'cell-sub', text: [x.source_name, x.detail, fmt.datetime(x.created_at)].filter(Boolean).join(' · ')})))) : h('div', {class: 'muted small', text: 'İlk yüklemeden sonraki içe aktarımlarda eklenen, kaldırılan ve tipi değişen tablo ve kolonlar burada görünür.'})),
      panel('Veri alanları', d.domains.length ? h('ul', {class: 'mini'}, d.domains.map(x => h('li', {class: 'link', onclick: () => Router.go('catalog?d=' + x.id)},
        h('strong', {text: x.name}), h('span', {class: 'cell-sub', text: `${x.tables} tablo · ${x.terms} onaylı terim · sahip: ${x.owner || '—'} · veri yöneticisi: ${x.steward || '—'}`})))) : empty('Veri alanı yok', 'Veri alanı tanımlayınca sahiplik alanın tablolarına devralınır.'),
        canWrite('data_domains') ? btn('+ Veri alanı', () => createRecord('data_domains'), 'ghost small') : null)));
};

// ------------------------------------------------------------------ iş sözlüğü
PAGES.glossary = async function glossaryPage(parts, params) {
  if (parts[1]) return termPage(Number(parts[1]));
  const status = params.get('s') || '', domain = params.get('d') || '', letter = params.get('l') || '', q = params.get('q') || '';
  const go = (patch) => { const p = new URLSearchParams({s: status, d: domain, l: letter, q, ...patch}); for (const [k, v] of [...p]) if (!v) p.delete(k); Router.go('glossary' + (p.toString() ? '?' + p : '')); };
  const qs = new URLSearchParams({status, domain_id: domain, letter, q}); for (const [k, v] of [...qs]) if (!v) qs.delete(k);
  const [d, domains] = await Promise.all([api('datagov/glossary?' + qs), list('data_domains')]);
  setPage('İş Sözlüğü', 'Kurumun ortak dili: her terimin onaylı tanımı, sahibi ve kullanıldığı tablo ve kolonlar. Taslak → onayda → onaylı; öneren kendi terimini onaylayamaz, onaylı terim değişiklik önerisiyle güncellenir.', [
    canWrite('glossary_terms') ? btn('+ Terim', () => recordForm('glossary_terms', null, {only: TERM_FIELDS, onsaved: r => Router.go('glossary/' + r.id)})) : null]);
  const c = d.counts;
  const tabsBar = h('div', {class: 'chips'}, [['', 'Kullanımdaki', (c.draft || 0) + (c.in_review || 0) + (c.approved || 0)], ['approved', 'Onaylı', c.approved || 0], ['in_review', 'Onayda', c.in_review || 0],
    ['pending', 'Değişiklik önerisi', c.pending || 0], ['draft', 'Taslak', c.draft || 0], ['retired', 'Kullanım dışı', c.retired || 0]].map(([k, label, n]) =>
    h('button', {type: 'button', class: 'chip' + (status === k ? ' on' : ''), 'aria-pressed': String(status === k), onclick: () => go({s: k})}, `${label} (${n})`)));
  const search = h('input', {type: 'search', class: 'searchbar', placeholder: 'Terim, kısaltma, eş anlam veya tanımda ara', value: q, 'aria-label': 'Sözlükte ara'});
  search.addEventListener('keydown', e => { if (e.key === 'Enter') go({q: search.value.trim()}); });
  const domainSel = h('select', {'aria-label': 'Veri alanı', onchange: e => go({d: e.target.value})}, h('option', {value: '', text: 'Tüm veri alanları'}), domains.map(x => h('option', {value: x.id, text: x.name, selected: String(x.id) === domain})));
  const az = h('div', {class: 'az'}, h('button', {type: 'button', class: 'az-l' + (letter ? '' : ' on'), text: 'Tümü', onclick: () => go({l: ''})}),
    [...new Set(d.letters)].map(L => h('button', {type: 'button', class: 'az-l' + (letter === L ? ' on' : ''), text: L, onclick: () => go({l: L})})));
  const cards = d.items.length ? h('div', {class: 'term-list'}, d.items.map(t => {
    const card = h('button', {type: 'button', class: 'term-card', onclick: () => Router.go('glossary/' + t.id)},
      h('div', {class: 'term-head'}, h('strong', {text: t.name}), t.abbreviation ? h('span', {class: 'chip', text: t.abbreviation}) : null, termPill(t),
        t.has_pending ? pill('Değişiklik önerisi', 'purple') : null, t.version ? h('span', {class: 'muted small', text: 's' + t.version}) : null),
      h('p', {class: 'term-def', text: t.definition}),
      h('div', {class: 'cell-sub', text: [t.code, t.domain_name, t.owner ? 'sahip: ' + t.owner : 'sahipsiz', t.column_count + t.table_count ? `${t.column_count} kolon, ${t.table_count} tabloda` : 'henüz bağlanmadı',
        t.synonyms ? 'eş anlam: ' + t.synonyms : null].filter(Boolean).join(' · ')}));
    return card;
  })) : empty(q || letter || status || domain ? 'Eşleşen terim yok' : 'Sözlük boş', q || letter || status || domain ? 'Süzgeci değiştirin.' : 'İlk terimi ekleyin; onaylandıktan sonra kolonlara bağlayın.');
  content(h('div', {class: 'panel'}, h('div', {class: 'toolbar wrap'}, search, domainSel), tabsBar, az), cards);
};
const TERM_FIELDS = ['name', 'abbreviation', 'synonyms', 'definition', 'domain_id', 'parent_id', 'owner', 'steward', 'calculation', 'format_rule', 'example',
  'source_reference', 'classification', 'personal_data', 'category_id', 'is_critical', 'review_date'];
const TERM_MATERIAL = ['name', 'abbreviation', 'synonyms', 'definition', 'domain_id', 'parent_id', 'calculation', 'format_rule', 'example', 'source_reference', 'classification', 'personal_data', 'category_id', 'is_critical'];
// Diğer dosyaların (privacy.js) tablo sayfasına ve kolon paneline eklediği bölümler: fn(kayıt, yenile) → düğüm
const TABLE_EXTRAS = []; const COLUMN_EXTRAS = []; const TABLE_ACTIONS = [];
DETAILS.glossary_terms = id => Router.go('glossary/' + id);

async function termPage(id) {
  const t = await api(`glossary_terms/${id}/context`); await list('data_domains');
  const reload = () => render();
  const act = (path, body) => api(`glossary_terms/${id}/${path}`, {method: 'POST', body: body || {}}).then(() => { toast('Kaydedildi'); reload(); });
  const noteDialog = (title, label, okText, path, extra = {}) => {
    const note = h('textarea', {id: 'termNote'});
    Modal.open(title, h('div', {}, h('label', {class: 'field wide', for: 'termNote'}, h('span', {text: label}), h('div', {class: 'control'}, note))),
      [btn('Vazgeç', () => Modal.close(), 'secondary'), btn(okText, async () => { await api(`glossary_terms/${id}/${path}`, {method: 'POST', body: {note: note.value, ...extra}}); Modal.close(); toast('Kaydedildi'); reload(); })]);
  };
  const can = t.can;
  setPage(t.name, `${t.code}${t.abbreviation ? ' · ' + t.abbreviation : ''} · ${t.domain ? t.domain.name : 'Veri alanı yok'}`, [
    can.edit ? btn('Düzenle', () => recordForm('glossary_terms', t, {only: TERM_FIELDS, onsaved: reload}), 'secondary') : null,
    can.submit ? btn('Onaya gönder', () => act('submit')) : null,
    can.approve ? btn(t.pending ? 'Değişikliği onayla' : 'Onayla', () => act('approve')) : null,
    can.approve ? btn('İade et', () => noteDialog('İade et', 'İade gerekçesi (önerene iletilir)', 'İade et', 'reject'), 'secondary') : null,
    can.withdraw && !can.approve ? btn('Onaydan geri çek', () => act('withdraw'), 'secondary') : null,
    can.propose ? btn('Değişiklik öner', () => proposeDialog(t, reload), 'secondary') : null,
    can.manage_people ? btn('Sorumlular', () => recordForm('glossary_terms', t, {only: ['owner', 'steward', 'review_date'], title: 'Sorumlular ve gözden geçirme', onsaved: reload}), 'ghost') : null,
    can.retire ? btn('Kullanım dışı bırak', () => retireDialog(t, reload), 'ghost') : null], [['Veri Yönetişimi', 'datagov'], ['İş Sözlüğü', 'glossary']]);
  const notices = [];
  if (t.status === 'in_review') notices.push(h('div', {class: 'notice'}, h('strong', {text: 'Onay bekliyor. '}), `Gönderen: ${t.submitted_by || '—'} · ${fmt.datetime(t.submitted_at)}. Onaylayabilecek: ${t.approvers.join(', ')} (gönderen dışında).`));
  if (t.status === 'draft' && t.review_note) notices.push(h('div', {class: 'notice warn'}, h('strong', {text: 'İade edildi: '}), t.review_note));
  if (t.status === 'retired') notices.push(h('div', {class: 'notice'}, h('strong', {text: 'Kullanım dışı. '}), t.review_note || '', t.replaced_by ? [' Yerine: ', h('a', {href: '#/glossary/' + t.replaced_by.id, text: `${t.replaced_by.code} ${t.replaced_by.name}`})] : null));
  if (t.pending) notices.push(h('div', {class: 'notice purple'}, h('strong', {text: `Değişiklik önerisi · ${t.pending.by} · ${fmt.datetime(t.pending.at)}`}), h('p', {class: 'small', text: t.pending.note || ''}),
    h('div', {class: 'tablewrap plain'}, h('table', {class: 'diff'}, h('thead', {}, h('tr', {}, ['Alan', 'Geçerli', 'Önerilen'].map(x => h('th', {text: x})))),
      h('tbody', {}, t.pending.fields.map(f => h('tr', {}, h('td', {text: META.label('glossary_terms', f.field)}), h('td', {class: 'old'}, display('glossary_terms', f.field, f.old)), h('td', {class: 'new'}, display('glossary_terms', f.field, f.new))))))),
    h('p', {class: 'small muted', text: `Onaylanana kadar geçerli tanım değişmez. Onaylayabilecek: ${t.approvers.join(', ')}.`})));
  const facts = kv([
    ['Durum', h('span', {class: 'chips'}, termPill(t), t.version ? h('span', {class: 'muted small', text: `Sürüm ${t.version}`}) : null)],
    t.synonyms ? ['Eş anlamlılar', t.synonyms] : null, t.calculation ? ['Hesaplama kuralı', h('pre', {class: 'calc', text: t.calculation})] : null,
    t.format_rule ? ['Biçim / standart', t.format_rule] : null, t.example ? ['Örnek', t.example] : null,
    t.source_reference ? ['Dayanak', t.source_reference] : null,
    ['Gizlilik sınıfı', classPill(t.classification)], ['Kişisel veri', personalPill(t.personal_data)], t.is_critical ? ['Kritik veri öğesi', pill('Evet', 'warn')] : null,
    t.parent ? ['Üst terim', h('a', {href: '#/glossary/' + t.parent.id, text: t.parent.name})] : null,
    t.children.length ? ['Alt terimler', h('span', {class: 'chips'}, t.children.map(x => h('a', {class: 'chip', href: '#/glossary/' + x.id, text: x.name})))] : null]);
  const people = kv([['Terim sahibi', personText(t.owner)], ['Veri yöneticisi', personText(t.steward)], ['Veri alanı', t.domain ? t.domain.name : '—'],
    ['Gözden geçirme', t.review_date ? h('span', {class: late(t.review_date) ? 'late' : '', text: fmt.date(t.review_date)}) : '—'],
    ['Son onay', t.approved_by ? `${t.approved_by} · ${fmt.datetime(t.approved_at)}` : '—'], ['Oluşturan', t.created_by || '—']]);
  const usedTab = () => {
    const groups = {};
    for (const col of t.columns) { const g = groups[col.source_id] = groups[col.source_id] || {name: col.source_name, tables: {}}; (g.tables[col.table_id] = g.tables[col.table_id] || {name: dgPath(col.schema_name, col.table_name), id: col.table_id, cols: []}).cols.push(col); }
    const unlink = (key, ids) => api(`glossary_terms/${id}/links`, {method: 'POST', body: {[key]: ids}}).then(() => { toast('Bağ kaldırıldı'); reload(); });
    return h('div', {},
      h('div', {class: 'toolbar wrap'}, can.link ? btn('+ Kolon bağla', () => pickColumns(t, reload), '') : null, can.link ? btn('+ Tablo bağla', () => pickTables(t, reload), 'secondary') : null),
      t.tables.length ? section('Tablolar', h('ul', {class: 'mini'}, t.tables.map(x => h('li', {}, h('a', {href: '#/catalog/table/' + x.id, text: dgPath(x.schema_name, x.name)}),
        h('span', {class: 'cell-sub', text: [x.source_name, x.business_name].filter(Boolean).join(' · ')}), can.link ? btn('Kaldır', () => unlink('remove_tables', [x.id]), 'ghost small') : null)))) : null,
      Object.keys(groups).length ? Object.values(groups).map(g => section(g.name, h('div', {}, Object.values(g.tables).map(tb => h('div', {class: 'used-table'},
        h('a', {href: '#/catalog/table/' + tb.id, class: 'strong', text: tb.name}),
        h('ul', {class: 'mini'}, tb.cols.map(col => h('li', {}, h('button', {type: 'button', class: 'linklike', text: col.name, onclick: () => columnPanel(col.id)}),
          h('span', {class: 'cell-sub', text: [col.business_name, col.data_type, col.status === 'removed' ? 'kaynakta kaldırıldı' : null].filter(Boolean).join(' · ')}),
          can.link ? btn('Kaldır', () => unlink('remove_columns', [col.id]), 'ghost small') : null)))))))) :
        empty('Henüz bağlanmadı', 'Terimi taşıyan kolonları bağlayın; kolon ekranında anlamı ve sınıfı bu terimden görünür.'));
  };
  const relTab = () => h('div', {},
    h('div', {class: 'toolbar'}, can.link ? btn('İlişkili terimleri düzenle', async () => {
      const all = (await api('datagov/glossary')).items.filter(x => x.id !== t.id);
      const chosen = await pickMany('İlişkili terimler', all.map(x => ({...x, title: x.name})), t.related.map(x => x.id), {label: x => `${x.name}${x.abbreviation ? ' (' + x.abbreviation + ')' : ''} · ${x.code}`});
      if (chosen) { await api(`glossary_terms/${id}/related`, {method: 'POST', body: {term_ids: chosen}}); toast('Kaydedildi'); reload(); }
    }, 'secondary') : null),
    t.related.length ? h('div', {class: 'chips'}, t.related.map(x => h('a', {class: 'chip', href: '#/glossary/' + x.id, text: x.name}))) : h('div', {class: 'muted small', text: 'İlişkili terim yok'}));
  const versionsTab = () => t.versions.length ? h('ol', {class: 'timeline'}, t.versions.map((v, i) => {
    const snap = JSON.parse(v.snapshot_json || '{}'); const prev = t.versions[i + 1] ? JSON.parse(t.versions[i + 1].snapshot_json || '{}') : null;
    const changed = prev ? Object.keys(snap).filter(k => String(snap[k] ?? '') !== String(prev[k] ?? '')) : [];
    return h('li', {}, h('strong', {text: `Sürüm ${v.version}`}), h('span', {class: 'cell-sub', text: `${fmt.datetime(v.created_at)} · onaylayan ${v.approved_by}${v.proposed_by ? ' · öneren ' + v.proposed_by : ''}`}),
      v.change_note ? h('div', {class: 'small', text: v.change_note}) : null,
      changed.length ? h('div', {class: 'small muted', text: 'Değişen: ' + changed.map(k => META.label('glossary_terms', k)).join(', ')}) : null,
      h('details', {}, h('summary', {class: 'small', text: 'Bu sürümün tanımı'}), h('p', {class: 'small', text: snap.definition || ''})));
  })) : h('div', {class: 'muted small', text: 'Terim henüz onaylanmadı; ilk onay sürüm 1 olur.'});
  content(...notices,
    h('div', {class: 'grid wide-left'},
      h('div', {class: 'panel'}, h('h3', {text: 'Tanım'}), h('p', {class: 'term-definition', text: t.definition}), facts),
      h('div', {class: 'panel'}, h('h3', {text: 'Sorumluluk'}), people,
        t.used_in.length ? section('Kullanıldığı kaynaklar', h('div', {class: 'chips'}, t.used_in.map(s => h('span', {class: 'chip', text: `${s.name} · ${s.count}`})))) : null)),
    tabs([{key: 'used', label: 'Kullanıldığı yerler', count: t.columns.length + t.tables.length, render: usedTab},
      {key: 'rel', label: 'İlişkili terimler', count: t.related.length, render: relTab},
      {key: 'versions', label: 'Sürüm geçmişi', count: t.versions.length, render: versionsTab}]));
}

function proposeDialog(t, reload) {
  const form = h('form', {class: 'formgrid', novalidate: true});
  const fields = editableFields('glossary_terms', {only: TERM_MATERIAL});
  loadRefs('glossary_terms', TERM_MATERIAL).then(() => {
    form.append(h('div', {class: 'notice wide', text: 'Onaylı tanım siz önerdiğinizde değişmez; terimin sahibi (veya veri yönetişimi yöneticisi) onaylayınca yeni sürüm olur. Yalnızca değiştirmek istediğiniz alanları değiştirin.'}));
    for (const f of fields) form.append(inputFor('glossary_terms', f, t[f.name]));
    form.append(h('label', {class: 'field wide', for: 'proposeNote'}, h('span', {}, 'Değişiklik gerekçesi', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, h('textarea', {id: 'proposeNote'}))));
  });
  Drawer.open('Değişiklik öner: ' + t.name, form, [btn('Vazgeç', () => Drawer.close(), 'secondary'), btn('Öneriyi gönder', async () => {
    const {data} = readForm(form, 'glossary_terms', fields);
    const changes = {}; for (const [k, v] of Object.entries(data)) if ((t[k] ?? null) !== v) changes[k] = v;
    if (!Object.keys(changes).length) throw new Error('Hiçbir alan değişmedi');
    await api(`glossary_terms/${t.id}/propose`, {method: 'POST', body: {changes, note: $('proposeNote').value}});
    Drawer.close(); toast('Öneri onaya gönderildi'); reload();
  })], 'İş sözlüğü');
}
async function retireDialog(t, reload) {
  const all = (await api('datagov/glossary?status=approved')).items.filter(x => x.id !== t.id);
  const note = h('textarea', {id: 'retNote'});
  const repl = h('select', {id: 'retRepl'}, h('option', {value: '', text: '— Yok —'}), all.map(x => h('option', {value: x.id, text: `${x.name} · ${x.code}`})));
  Modal.open('Kullanım dışı bırak: ' + t.name, h('div', {},
    h('p', {class: 'intro', text: 'Terim silinmez; kolon bağları ve sürüm geçmişi korunur. Yeni kolona bağlanamaz.'}),
    h('label', {class: 'field', for: 'retRepl'}, h('span', {text: 'Yerine geçen terim'}), h('div', {class: 'control'}, repl)),
    h('label', {class: 'field', for: 'retNote'}, h('span', {}, 'Gerekçe', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, note))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kullanım dışı bırak', async () => {
    await api(`glossary_terms/${t.id}/retire`, {method: 'POST', body: {note: note.value, replaced_by_id: repl.value ? Number(repl.value) : null}}); Modal.close(); toast('Kullanım dışı bırakıldı'); reload();
  }, 'danger')]);
}
/** Arayarak çoklu seçim (kolon/tablo): sonuçlar sunucudan gelir, seçilenler üstte birikir. */
function searchPicker(title, {kind, intro, label, sub}) {
  return new Promise(resolve => {
    const chosen = new Map();
    const input = h('input', {type: 'search', class: 'searchbar', placeholder: 'Kolon veya tablo adı, iş adı…', 'aria-label': 'Ara'});
    const picked = h('div', {class: 'chips'}); const results = h('ul', {class: 'mini pick-results'});
    const drawPicked = () => picked.replaceChildren(...[...chosen.values()].map(x => h('button', {type: 'button', class: 'chip on', text: label(x) + ' ✕', onclick: () => { chosen.delete(x.id); drawPicked(); }})));
    const run = debounce(async () => {
      const q = input.value.trim(); if (q.length < 2) { results.replaceChildren(); return; }
      const r = await api(`datagov/search?kind=${kind}&q=${encodeURIComponent(q)}`).catch(() => null); const items = r ? r[kind] : [];
      results.replaceChildren(...(items.length ? items.map(x => h('li', {class: 'link', onclick: () => { chosen.set(x.id, x); drawPicked(); }}, h('strong', {text: label(x)}), h('span', {class: 'cell-sub', text: sub(x)}))) : [h('li', {class: 'muted small', text: 'Eşleşen kayıt yok'})]));
    }, 220);
    input.addEventListener('input', run);
    Modal.open(title, h('div', {}, intro ? h('p', {class: 'intro', text: intro}) : null, input, picked, results),
      [btn('Vazgeç', () => { Modal.close(); resolve(null); }, 'secondary'), btn('Bağla', () => { Modal.close(); resolve([...chosen.keys()]); })], true);
  });
}
async function pickColumns(t, reload) {
  const ids = await searchPicker('Kolon bağla: ' + t.name, {kind: 'columns', intro: 'Bu terimi taşıyan kolonları arayıp seçin (ör. KUNNR, musteri_no, customer).',
    label: x => `${dgPath(x.schema_name, x.table_name)}.${x.name}`, sub: x => [x.source_name, x.business_name, x.data_type].filter(Boolean).join(' · ')});
  if (ids && ids.length) { await api(`glossary_terms/${t.id}/links`, {method: 'POST', body: {add_columns: ids}}); toast(`${ids.length} kolon bağlandı`); reload(); }
}
async function pickTables(t, reload) {
  const ids = await searchPicker('Tablo bağla: ' + t.name, {kind: 'tables', label: x => dgPath(x.schema_name, x.name), sub: x => [x.source_name, x.business_name].filter(Boolean).join(' · ')});
  if (ids && ids.length) { await api(`glossary_terms/${t.id}/links`, {method: 'POST', body: {add_tables: ids}}); toast(`${ids.length} tablo bağlandı`); reload(); }
}

// ------------------------------------------------------------------ kolon paneli ("bu kolon ne anlama geliyor?")
async function columnPanel(id) {
  let c; try { c = await api(`data_columns/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const e = c.effective;
  const meaning = c.meaning.text ? h('div', {class: 'meaning'}, h('div', {class: 'meaning-label', text: {column: 'İş açıklaması', term: 'Sözlük tanımı', source: 'Kaynaktaki açıklama (iş tanımı henüz yok)'}[c.meaning.from]}),
    c.meaning.name ? h('strong', {text: c.meaning.name}) : null, h('p', {text: c.meaning.text})) : h('div', {class: 'notice warn small', text: 'Bu kolonun iş anlamı tanımlanmamış: iş adı ve açıklama yazın veya bir sözlük terimine bağlayın.'});
  const body = h('div', {}, meaning,
    section('Teknik', kv([['Yol', h('span', {}, h('a', {href: '#/datasource/' + c.source.id, text: c.source.name}), ' / ', h('a', {href: '#/catalog/table/' + c.table.id, text: dgPath(c.table.schema_name, c.table.name)}))],
      ['Veri tipi', [c.data_type, c.data_length ? `(${c.data_length})` : ''].filter(Boolean).join(' ') || '—'], ['Birincil anahtar', c.is_primary_key ? 'Evet' : 'Hayır'],
      ['Boş olabilir', c.nullable === null ? '—' : c.nullable ? 'Evet' : 'Hayır'], c.previous_type ? ['Önceki tip', c.previous_type] : null,
      c.references_to ? ['Referans', h('span', {}, c.references.length ? c.references.map(r => h('a', {class: 'chip', href: '#/catalog/table/' + r.table_id, text: r.column ? `${r.table}.${r.column}` : r.table})) : c.references_to)] : null,
      c.technical_description && c.meaning.from !== 'source' ? ['Kaynaktaki açıklama', c.technical_description] : null,
      c.status === 'removed' ? ['Durum', pill('Kaynakta kaldırıldı', 'bad')] : null])),
    section('Yönetişim', kv([['Gizlilik sınıfı', classPill(e.classification, e.classification_from)], ['Kişisel veri', personalPill(c.personal_data)],
      ['Kritik veri öğesi', c.is_critical ? pill('Evet', 'warn') : 'Hayır'], ['Veri sahibi', personText(e.owner, e.owner_from)],
      ['Veri yöneticisi', personText(e.steward, e.steward_from)], ['Teknik sorumlu', personText(e.custodian, e.custodian_from)], ['Veri alanı', e.domain ? e.domain.name : '—']])),
    section(`Sözlük terimleri (${c.terms.length})`, c.terms.length ? h('ul', {class: 'mini'}, c.terms.map(g => h('li', {class: 'link', onclick: () => { Drawer.close(); Router.go('glossary/' + g.id); }},
      h('div', {class: 'chips'}, h('strong', {text: g.name}), termPill(g)), h('span', {class: 'cell-sub', text: g.definition}), g.format_rule ? h('span', {class: 'cell-sub', text: 'Biçim: ' + g.format_rule}) : null))) :
      h('div', {class: 'muted small', text: 'Bağlı terim yok'}), c.can_edit ? btn('Terim seç', () => columnTerms(c), 'ghost small') : null),
    ...COLUMN_EXTRAS.map(fn => fn(c, () => columnPanel(id))),
    c.referenced_by.length ? section(`Bu kolona referans verenler (${c.referenced_by.length})`, h('ul', {class: 'mini'}, c.referenced_by.map(r => h('li', {class: 'link', onclick: () => columnPanel(r.id)},
      h('strong', {text: `${dgPath(r.schema_name, r.table_name)}.${r.name}`}))))) : null,
    c.changes.length ? section('Değişiklik geçmişi', h('ul', {class: 'mini'}, c.changes.map(x => h('li', {}, pill(META.option('catalog_changes', 'change', x.change), tone(x.change)), ' ',
      h('span', {class: 'small', text: [x.detail, fmt.datetime(x.created_at)].filter(Boolean).join(' · ')}))))) : null);
  Drawer.open(c.business_name ? `${c.name} — ${c.business_name}` : c.name, body, [
    c.can_edit ? btn('Düzenle', () => recordForm('data_columns', c, {only: ['business_name', 'description', 'classification', 'personal_data', 'is_critical'], title: 'Kolon: ' + c.name,
      onsaved: () => { columnPanel(id); if (Router.parse().parts[0] === 'catalog') render(); }})) : null], 'Kolon');
}
DETAILS.data_columns = columnPanel;
async function columnTerms(c) {
  const all = (await api('datagov/glossary')).items.filter(x => x.status !== 'retired' || c.terms.some(t => t.id === x.id));
  const chosen = await pickMany('Kolonun terimleri: ' + c.name, all.map(x => ({...x, title: x.name})), c.terms.map(x => x.id),
    {label: x => `${x.name}${x.abbreviation ? ' (' + x.abbreviation + ')' : ''} · ${(DG.status[x.status] || [x.status])[0]}`, intro: 'Bu kolonun taşıdığı iş terimlerini işaretleyin.'});
  if (!chosen) return;
  await api(`data_columns/${c.id}/terms`, {method: 'POST', body: {term_ids: chosen}}); toast('Kaydedildi'); columnPanel(c.id);
}

// ------------------------------------------------------------------ katalog
DETAILS.data_tables = id => Router.go('catalog/table/' + id);
const CATALOG_FILTERS = [['', 'Tümü'], ['undocumented', 'Eksik tanımlı'], ['unowned', 'Sahipsiz'], ['personal', 'Kişisel veri'], ['critical', 'Kritik veri'],
  ['certified', 'Onaylı veri seti'], ['changed', 'Değişen'], ['removed', 'Kaynakta kaldırılan']];
PAGES.catalog = async function catalogPage(parts, params) {
  if (parts[1] === 'table' && parts[2]) return tablePage(Number(parts[2]));
  const sid = params.get('s') || '', schema = params.get('schema'), flt = params.get('f') || '', q = params.get('q') || '', domain = params.get('d') || '';
  const offset = Number(params.get('o') || 0);
  const go = patch => { const p = new URLSearchParams({s: sid, f: flt, q, d: domain, ...(schema !== null ? {schema} : {}), ...patch}); for (const [k, v] of [...p]) if (v === '' && k !== 'schema') p.delete(k); if (patch.schema === null) p.delete('schema'); Router.go('catalog' + (p.toString() ? '?' + p : '')); };
  const qs = new URLSearchParams({limit: 50, offset}); if (sid) qs.set('source_id', sid); if (schema !== null) qs.set('schema', schema); if (flt) qs.set('filter', flt); if (q) qs.set('q', q); if (domain) qs.set('domain_id', domain);
  const [sources, data, source] = await Promise.all([list('data_sources'), api('datagov/tables?' + qs), sid ? api(`data_sources/${sid}/context`) : null]);
  setPage('Veri Kataloğu', 'Kaynak → şema → tablo → kolon. Kolon "tanımlı" sayılır: iş adı, iş açıklaması veya sözlük terimi varsa. Satıra tıklayınca tablo, kolona tıklayınca anlamı açılır.', [
    source && source.can_import ? btn('İçe aktar', () => importWizard(source)) : null], [['Veri Yönetişimi', 'datagov']]);
  if (!sources.length) { content(empty('Veri kaynağı yok', 'Önce bir veri kaynağı ekleyin; tablo ve kolonlar kaynağın ekranından dosyayla içeri alınır.', canWrite('data_sources') ? btn('+ Veri kaynağı', () => createRecord('data_sources')) : null)); return; }
  const tree = h('nav', {class: 'cat-tree', 'aria-label': 'Kaynaklar'},
    h('button', {type: 'button', class: 'cat-node' + (!sid ? ' on' : ''), onclick: () => go({s: '', schema: null, o: ''})}, h('strong', {text: 'Tüm kaynaklar'})),
    sources.filter(s => s.status === 'active').map(s => [h('button', {type: 'button', class: 'cat-node' + (String(s.id) === sid && schema === null ? ' on' : ''), onclick: () => go({s: s.id, schema: null, o: ''})},
      h('strong', {text: s.name}), h('span', {class: 'cell-sub', text: META.option('data_sources', 'platform', s.platform)})),
      String(s.id) === sid && source ? source.schemas.map(x => h('button', {type: 'button', class: 'cat-node sub' + (schema === x.schema_name ? ' on' : ''), onclick: () => go({schema: x.schema_name, o: ''})},
        h('span', {text: x.schema_name || '(şemasız)'}), h('span', {class: 'cell-sub', text: `${x.tables} tablo · %${dgPct(x.documented, x.columns) ?? 0} tanımlı`}))) : null]));
  const search = h('input', {type: 'search', class: 'searchbar', placeholder: 'Tablo veya kolon adı, iş adı', value: q, 'aria-label': 'Tablolarda ara'});
  search.addEventListener('keydown', e => { if (e.key === 'Enter') go({q: search.value.trim(), o: ''}); });
  const chips = h('div', {class: 'chips'}, CATALOG_FILTERS.map(([k, label]) => h('button', {type: 'button', class: 'chip' + (flt === k ? ' on' : ''), 'aria-pressed': String(flt === k), text: label, onclick: () => go({f: k, o: ''})})));
  const selected = new Set();
  const bulkBar = h('div', {class: 'bulk-bar hidden'});
  const drawBulk = () => {
    bulkBar.classList.toggle('hidden', !selected.size);
    bulkBar.replaceChildren(h('strong', {text: `${selected.size} tablo seçildi`}),
      btn('Sahip ata', () => bulkTables([...selected], 'owner', 'Veri sahibi'), 'secondary small'), btn('Veri yöneticisi ata', () => bulkTables([...selected], 'steward', 'Veri yöneticisi'), 'secondary small'),
      btn('Teknik sorumlu ata', () => bulkTables([...selected], 'custodian', 'Teknik sorumlu'), 'secondary small'), btn('Sınıf', () => bulkTables([...selected], 'classification', 'Gizlilik sınıfı'), 'secondary small'),
      btn('Veri alanı', () => bulkTables([...selected], 'domain_id', 'Veri alanı'), 'secondary small'), btn('Seçimi temizle', () => { selected.clear(); host.querySelectorAll('input.sel').forEach(x => { x.checked = false; }); drawBulk(); }, 'ghost small'));
  };
  const canBulk = canWrite('data_tables');
  const rowsEl = data.items.map(t => {
    const box = canBulk ? h('input', {type: 'checkbox', class: 'sel', 'aria-label': 'Seç: ' + t.name, onclick: e => e.stopPropagation(), onchange: e => { if (e.target.checked) selected.add(t.id); else selected.delete(t.id); drawBulk(); }}) : null;
    return h('tr', {class: 'link', onclick: () => Router.go('catalog/table/' + t.id)},
      canBulk ? h('td', {class: 'sel-cell'}, box) : null,
      h('td', {}, h('strong', {text: t.name}), h('div', {class: 'cell-sub', text: [t.business_name, sid ? (t.schema_name || null) : `${t.source_name}${t.schema_name ? ' / ' + t.schema_name : ''}`].filter(Boolean).join(' · ')})),
      h('td', {}, pill(META.option('data_tables', 'object_type', t.object_type), 'neutral'), t.certified ? pill('Onaylı', 'good') : null, t.status !== 'active' ? pill(META.option('data_tables', 'status', t.status), tone(t.status)) : null),
      h('td', {}, coverBar(t.documented_count, t.column_count)),
      h('td', {}, t.eff_owner || h('span', {class: 'muted', text: 'Sahipsiz'})),
      h('td', {}, t.classification ? pill(META.option('data_tables', 'classification', t.classification), tone(t.classification)) : h('span', {class: 'muted', text: '—'})),
      h('td', {class: 'num'}, t.personal_count ? pill(String(t.personal_count), 'warn') : h('span', {class: 'muted', text: '—'})));
  });
  const pager = data.total > data.limit ? h('div', {class: 'toolbar'}, h('span', {class: 'muted small', text: `${offset + 1}–${Math.min(offset + data.limit, data.total)} / ${fmt.num(data.total)}`}),
    offset ? btn('‹ Önceki', () => go({o: Math.max(0, offset - data.limit)}), 'secondary small') : null,
    offset + data.limit < data.total ? btn('Sonraki ›', () => go({o: offset + data.limit}), 'secondary small') : null) : null;
  const host = h('div', {}, data.items.length ? h('div', {class: 'tablewrap'}, h('table', {class: 'catalog'}, h('thead', {}, h('tr', {}, [canBulk ? '' : null, 'Tablo', 'Tür', 'Tanımlı kolon', 'Veri sahibi', 'Sınıf', 'Kişisel'].filter(x => x !== null).map(x => h('th', {text: x})))), h('tbody', {}, rowsEl))) :
    empty('Tablo bulunamadı', sid && source && !source.totals.tables ? 'Bu kaynak henüz içe aktarılmadı.' : 'Süzgeci veya aramayı değiştirin.', sid && source && !source.totals.tables && source.can_import ? btn('İçe aktar', () => importWizard(source)) : null), pager);
  content(h('div', {class: 'catalog-layout'}, h('div', {class: 'panel tree-panel'}, tree),
    h('div', {class: 'panel'}, h('div', {class: 'toolbar wrap'}, search, h('span', {class: 'muted small', text: `${fmt.num(data.total)} tablo`})), chips, bulkBar, host)));
};
async function bulkTables(ids, field, label) {
  const f = META.field('data_tables', field); await loadRefs('data_tables', [field]); await ensurePeople();
  const form = h('form', {class: 'formgrid'}, inputFor('data_tables', f, null));
  Modal.open(`${label}: ${ids.length} tablo`, h('div', {}, h('p', {class: 'intro', text: 'Seçilen tabloların tümüne aynı değer yazılır. Boş bırakılırsa tablo değeri temizlenir ve veri alanından/kaynaktan devralınır.'}), form),
    [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Uygula', async () => {
      const {data} = readForm(form, 'data_tables', [f]);
      const r = await api('datagov/bulk', {method: 'POST', body: {table_ids: ids, set: {[field]: data[field]}}});
      Modal.close(); toast(`${r.updated} tablo güncellendi${r.errors.length ? `, ${r.errors.length} atlandı` : ''}`, !r.errors.length); render();
    })]);
}

const TABLE_FIELDS = ['business_name', 'description', 'domain_id', 'owner', 'steward', 'custodian', 'classification', 'retention_rule_id', 'certified', 'status'];
async function tablePage(id) {
  const t = await api(`data_tables/${id}/context`); await list('data_domains');
  const e = t.effective; const reload = () => render();
  setPage(t.business_name ? `${t.name} — ${t.business_name}` : t.name, `${t.source.name}${t.schema_name ? ' / ' + t.schema_name : ''} · ${META.option('data_tables', 'object_type', t.object_type)}`, [
    t.can_edit ? btn('Düzenle', () => recordForm('data_tables', t, {only: TABLE_FIELDS, title: 'Tablo: ' + t.name, onsaved: reload}), 'secondary') : null,
    t.can_edit && t.stats.technical_only ? btn(`Kaynak açıklamalarını benimse (${t.stats.technical_only})`, async () => {
      if (!await confirmDialog('Kaynak açıklamalarını benimse', `İş açıklaması boş olan ${t.stats.technical_only} kolonda kaynaktaki açıklama (ör. SAP metni, veritabanı yorumu) iş açıklaması olarak yazılacak. Sonradan düzenleyebilirsiniz.`, 'Benimse')) return;
      const r = await api(`data_tables/${id}/adopt-descriptions`, {method: 'POST', body: {}}); toast(`${r.adopted} açıklama benimsendi`); reload();
    }, 'ghost') : null, ...TABLE_ACTIONS.map(fn => fn(t, reload))], [['Veri Kataloğu', 'catalog'], [t.source.name, 'datasource/' + t.source.id]]);
  const head = h('div', {class: 'grid wide-left'},
    h('div', {class: 'panel'},
      h('div', {class: 'chips'}, pill(META.option('data_tables', 'object_type', t.object_type), 'neutral'), t.classification ? pill(META.option('data_tables', 'classification', t.classification), tone(t.classification)) : null,
        t.certified ? pill('Onaylı veri seti', 'good') : null, t.status !== 'active' ? pill(META.option('data_tables', 'status', t.status), tone(t.status)) : null),
      t.description ? h('p', {class: 'term-definition', text: t.description}) : t.technical_description ? h('p', {}, h('span', {class: 'muted small', text: 'Kaynaktaki açıklama: '}), t.technical_description) : h('p', {class: 'muted', text: 'İş açıklaması yok.'}),
      statStrip([['Kolon', fmt.num(t.stats.columns)], ['Tanımlı', `%${dgPct(t.stats.documented, t.stats.columns) ?? 0}`, dgPct(t.stats.documented, t.stats.columns) < 50 ? 'warn' : ''],
        ['Kişisel veri', fmt.num(t.stats.personal), t.stats.personal ? 'warn' : ''], ['Kritik', fmt.num(t.stats.critical)], t.row_count !== null ? ['Satır', fmt.num(t.row_count)] : null]),
      t.terms.length ? h('div', {class: 'chips'}, h('span', {class: 'muted small', text: 'Terimler: '}), t.terms.map(g => h('a', {class: 'chip', href: '#/glossary/' + g.id, text: g.name}))) : null),
    h('div', {class: 'panel'}, h('h3', {text: 'Sorumluluk'}), kv([['Veri sahibi', personText(e.owner, e.owner_from)], ['Veri yöneticisi', personText(e.steward, e.steward_from)],
      ['Teknik sorumlu', personText(e.custodian, e.custodian_from)], ['Veri alanı', e.domain ? h('span', {}, e.domain.name, e.domain_from === 'source' ? h('span', {class: 'muted small', text: ' (kaynaktan)'}) : null) : '—'],
      t.ci ? ['CMDB öğesi', h('a', {href: '#/r/cmdb_cis/' + t.ci.id, text: `${t.ci.code} ${t.ci.name}`})] : null,
      t.processes.length ? ['Kullanan süreçler (BİA)', h('span', {class: 'chips'}, t.processes.map(p => h('span', {class: 'chip', text: p.name})))] : null])));
  const colsTab = () => {
    const sel = new Set();
    const bar = h('div', {class: 'bulk-bar hidden'});
    const drawBar = () => { bar.classList.toggle('hidden', !sel.size); bar.replaceChildren(h('strong', {text: `${sel.size} kolon seçildi`}),
      ...[['classification', 'Sınıf'], ['personal_data', 'Kişisel veri'], ['is_critical', 'Kritik']].map(([f, label]) => btn(label, () => bulkColumns([...sel], f, label), 'secondary small'))); };
    const active = t.columns.filter(c => c.status === 'active'), removed = t.columns.filter(c => c.status !== 'active');
    const row = c => h('tr', {class: 'link' + (c.status !== 'active' ? ' removed' : ''), onclick: () => columnPanel(c.id)},
      t.can_edit && c.status === 'active' ? h('td', {class: 'sel-cell'}, h('input', {type: 'checkbox', 'aria-label': 'Seç: ' + c.name, onclick: ev => ev.stopPropagation(), onchange: ev => { if (ev.target.checked) sel.add(c.id); else sel.delete(c.id); drawBar(); }})) : t.can_edit ? h('td') : null,
      h('td', {}, h('span', {class: 'doc-dot ' + (c.documented ? 'on' : c.technical_description ? 'half' : ''), title: c.documented ? 'Tanımlı' : c.technical_description ? 'Yalnızca kaynak açıklaması' : 'Tanımsız'}),
        h('strong', {text: c.name}), c.is_primary_key ? h('span', {class: 'chip key', text: 'PK'}) : null),
      h('td', {}, c.business_name ? h('strong', {class: 'small', text: c.business_name}) : null, h('div', {class: 'cell-sub', text: colSub(c)})),
      h('td', {class: 'small', text: [c.data_type, c.data_length ? `(${c.data_length})` : ''].filter(Boolean).join('')}),
      h('td', {}, c.effective_classification ? pill(META.option('data_tables', 'classification', c.effective_classification), tone(c.effective_classification)) : h('span', {class: 'muted', text: '—'})),
      h('td', {}, c.personal_data && c.personal_data !== 'none' ? personalPill(c.personal_data) : h('span', {class: 'muted', text: c.personal_data === 'none' ? 'Yok' : '—'}), c.is_critical ? pill('Kritik', 'warn') : null),
      h('td', {}, c.terms.length ? h('div', {class: 'chips'}, c.terms.map(g => h('span', {class: 'chip', text: g.name}))) : h('span', {class: 'muted', text: '—'})));
    const headers = [t.can_edit ? '' : null, 'Kolon', 'İş anlamı', 'Tip', 'Sınıf', 'Kişisel', 'Terimler'].filter(x => x !== null);
    return h('div', {}, h('p', {class: 'small muted', text: 'Nokta: dolu = tanımlı, yarım = yalnızca kaynak açıklaması var, boş = tanımsız. Kolona tıklayınca anlamı, sahibi ve ilişkileri açılır.'}), bar,
      h('div', {class: 'tablewrap'}, h('table', {class: 'columns'}, h('thead', {}, h('tr', {}, headers.map(x => h('th', {text: x})))), h('tbody', {}, active.map(row)))),
      removed.length ? section(`Kaynakta kaldırılan kolonlar (${removed.length})`, h('div', {class: 'tablewrap'}, h('table', {class: 'columns'}, h('tbody', {}, removed.map(row))))) : null);
  };
  const refsTab = () => h('div', {}, t.referenced_by.length ? section('Bu tabloya referans veren kolonlar', h('ul', {class: 'mini'}, t.referenced_by.map(r => h('li', {class: 'link', onclick: () => columnPanel(r.id)},
    h('strong', {text: `${dgPath(r.schema_name, r.table_name)}.${r.name}`}), h('span', {class: 'cell-sub', text: r.references_to}))))) : h('div', {class: 'muted small', text: 'Bu kaynakta bu tabloya referans veren kolon görünmüyor (yabancı anahtar, SAP kontrol tablosu veya ServiceNow referansı).'}),
    t.columns.some(c => c.references_to) ? section('Bu tablonun referansları', h('ul', {class: 'mini'}, t.columns.filter(c => c.references_to).map(c => h('li', {class: 'link', onclick: () => columnPanel(c.id)},
      h('strong', {text: c.name}), h('span', {class: 'cell-sub', text: '→ ' + c.references_to}))))) : null);
  const changesTab = () => t.changes.length ? h('ul', {class: 'mini'}, t.changes.map(x => h('li', {}, h('div', {class: 'chips'}, pill(META.option('catalog_changes', 'change', x.change), tone(x.change)), h('strong', {text: x.object_name})),
    h('span', {class: 'cell-sub', text: [x.detail, fmt.datetime(x.created_at)].filter(Boolean).join(' · ')})))) : h('div', {class: 'muted small', text: 'İlk yüklemeden sonra değişiklik görülmedi.'});
  content(head, ...TABLE_EXTRAS.map(fn => fn(t, reload)), tabs([{key: 'cols', label: 'Kolonlar', count: t.stats.columns, render: colsTab}, {key: 'refs', label: 'İlişkiler', count: t.referenced_by.length, render: refsTab},
    {key: 'changes', label: 'Değişiklik geçmişi', count: t.changes.length, render: changesTab}]));
}
function colSub(c) {
  const same = x => x && c.business_name && x.toLocaleLowerCase(TR) === c.business_name.toLocaleLowerCase(TR);
  const term = c.terms[0] && c.terms[0].name;
  const text = c.description || (!same(term) && term) || (!same(c.technical_description) && c.technical_description) || '';
  return text.slice(0, 140);
}
async function bulkColumns(ids, field, label) {
  const f = META.field('data_columns', field);
  const control = field === 'is_critical' ? h('select', {id: 'bulkVal'}, h('option', {value: '1', text: 'Evet'}), h('option', {value: '0', text: 'Hayır'}))
    : h('select', {id: 'bulkVal'}, h('option', {value: '', text: '— Temizle (tablodan devral) —'}), f.options.map(o => h('option', {value: o.value, text: o.label})));
  Modal.open(`${label}: ${ids.length} kolon`, h('label', {class: 'field', for: 'bulkVal'}, h('span', {text: label}), h('div', {class: 'control'}, control)),
    [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Uygula', async () => {
      const v = control.value === '' ? null : field === 'is_critical' ? Number(control.value) : control.value;
      const r = await api('datagov/bulk', {method: 'POST', body: {column_ids: ids, set: {[field]: v}}}); Modal.close(); toast(`${r.updated} kolon güncellendi`); render();
    })]);
}

// ------------------------------------------------------------------ veri kaynağı ve içe aktarım
DETAILS.data_sources = id => Router.go('datasource/' + id);
PAGES.datasource = async function sourcePage(parts) {
  const s = await api(`data_sources/${Number(parts[1])}/context`); const reload = () => render();
  setPage(s.name, `${s.code} · ${META.option('data_sources', 'platform', s.platform)} · ${META.option('data_sources', 'environment', s.environment)}`, [
    s.can_import ? btn('İçe aktar', () => importWizard(s)) : null,
    s.totals.tables ? btn('Excel/CSV\'ye aktar', () => exportDialog(s), 'secondary') : null,
    s.can_import && s.totals.tables ? btn('İş açıklamalarını içe aktar', () => descriptionsDialog(s), 'secondary') : null,
    canWrite('data_sources') ? btn('Düzenle', () => recordForm('data_sources', s, {onsaved: reload}), 'ghost') : null], [['Veri Yönetişimi', 'datagov'], ['Veri Kaynakları', 'r/data_sources']]);
  const docPct = dgPct(s.totals.documented, s.totals.columns);
  const info = kv([['Platform', META.option('data_sources', 'platform', s.platform)], ['Veri alanı', s.domain ? s.domain.name : '—'], ['Sistem sahibi', personText(s.owner)],
    ['Veri yöneticisi', personText(s.steward)], ['Teknik sorumlu', personText(s.custodian)], s.location ? ['Sunucu / örnek', s.location] : null,
    s.ci ? ['CMDB öğesi', h('a', {href: '#/r/cmdb_cis/' + s.ci.id, text: `${s.ci.code} ${s.ci.name}`})] : null, s.supplier ? ['Tedarikçi', s.supplier.name] : null,
    s.processes.length ? ['Kullanan süreçler (BİA)', h('span', {class: 'chips'}, s.processes.map(p => h('span', {class: 'chip', text: p.name})))] : null,
    ['Son içe aktarım', s.last_import_at ? fmt.datetime(s.last_import_at) : 'Henüz yok']]);
  const schemas = s.schemas.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Şema', 'Tablo', 'Kolon', 'Tanımlı kolon', 'Kişisel veri'].map(x => h('th', {text: x})))),
    h('tbody', {}, s.schemas.map(x => h('tr', {class: 'link', onclick: () => Router.go(`catalog?s=${s.id}&schema=${encodeURIComponent(x.schema_name)}`)},
      h('td', {}, h('strong', {text: x.schema_name || '(şemasız)'})), h('td', {class: 'num', text: fmt.num(x.tables)}), h('td', {class: 'num', text: fmt.num(x.columns)}),
      h('td', {}, coverBar(x.documented, x.columns)), h('td', {class: 'num', text: fmt.num(x.personal || 0)})))))) : null;
  const howTo = () => h('div', {}, h('p', {class: 'small', text: 'Bağlayıcılar (Faz 3) gelene kadar kaynak, aşağıdaki hazır sorgunun çıktısıyla içe aktarılır. Sorgu yalnızca tablo ve kolon tanımlarını okur; veri içeriği okunmaz ve platforma gelmez.'}),
    s.queries.map(qy => h('div', {class: 'query-card'}, h('div', {class: 'panel-title'}, h('h4', {text: qy.title}), copyButton(qy.text)), qy.note ? h('p', {class: 'small muted', text: qy.note}) : null, h('pre', {class: 'query', text: qy.text}))));
  const importsTab = () => s.imports.length ? h('ul', {class: 'mini'}, s.imports.map(i => h('li', {}, h('div', {class: 'chips'}, pill(META.option('catalog_imports', 'kind', i.kind), 'neutral'), h('strong', {text: i.filename})),
    h('span', {class: 'cell-sub', text: [fmt.datetime(i.created_at), i.created_by, i.kind === 'structure' ? countText(i.summary.counts) : descText(i.summary.counts)].filter(Boolean).join(' · ')})))) : h('div', {class: 'muted small', text: 'İçe aktarım yok'});
  const changesTab = () => s.changes.length ? h('ul', {class: 'mini'}, s.changes.map(x => h('li', {class: x.table_id ? 'link' : '', onclick: () => x.table_id && Router.go('catalog/table/' + x.table_id)},
    h('div', {class: 'chips'}, pill(META.option('catalog_changes', 'change', x.change), tone(x.change)), h('strong', {text: x.object_name})), h('span', {class: 'cell-sub', text: [x.detail, fmt.datetime(x.created_at)].filter(Boolean).join(' · ')})))) :
    h('div', {class: 'muted small', text: 'İlk yüklemeden sonraki içe aktarımlarda eklenen, kaldırılan ve tipi değişen tablo ve kolonlar burada görünür.'});
  content(
    !s.totals.tables ? h('div', {class: 'notice'}, h('strong', {text: 'Bu kaynak henüz içe aktarılmadı. '}), 'Aşağıdaki "Nasıl içe aktarılır" sekmesindeki sorguyu çalıştırın, sonucu dosya olarak kaydedin ve "İçe aktar" ile yükleyin. Önce ön izleme gösterilir.') : null,
    h('div', {class: 'grid wide-left'},
      h('div', {class: 'panel'}, statStrip([['Şema', fmt.num(s.schemas.length)], ['Tablo', fmt.num(s.totals.tables)], ['Kolon', fmt.num(s.totals.columns)],
        ['Tanımlı', docPct === null ? '—' : `%${docPct}`, docPct !== null && docPct < 50 ? 'warn' : ''], ['Kişisel veri', fmt.num(s.totals.personal), s.totals.personal ? 'warn' : ''],
        s.totals.removed ? ['Kaldırılan tablo', fmt.num(s.totals.removed), 'bad'] : null]), s.description ? h('p', {class: 'small', text: s.description}) : null, schemas),
      h('div', {class: 'panel'}, h('h3', {text: 'Kaynak bilgileri'}), info)),
    tabs([{key: 'how', label: 'Nasıl içe aktarılır', render: howTo}, {key: 'imports', label: 'İçe aktarım geçmişi', count: s.imports.length, render: importsTab},
      {key: 'changes', label: 'Şema değişiklikleri', count: s.changes.length, render: changesTab}], s.totals.tables ? 'imports' : 'how'));
};
const COUNT_LABELS = {table_added: 'tablo eklendi', table_removed: 'tablo kaldırıldı', table_restored: 'tablo geri geldi', column_added: 'kolon eklendi',
  column_removed: 'kolon kaldırıldı', column_restored: 'kolon geri geldi', type_changed: 'tip değişti'};
function countText(counts) { return Object.entries(counts || {}).filter(([, n]) => n).map(([k, n]) => `${fmt.num(n)} ${COUNT_LABELS[k] || k}`).join(', ') || 'değişiklik yok'; }
function descText(counts) { const c = counts || {}; return [c.tables_updated ? `${c.tables_updated} tablo` : null, c.columns_updated ? `${c.columns_updated} kolon` : null, c.terms_linked ? `${c.terms_linked} terim bağı` : null, c.errors ? `${c.errors} hata` : null].filter(Boolean).join(', ') || 'değişiklik yok'; }

function importWizard(s) {
  const queries = s.queries || [];
  let chosen = queries[0];
  const qText = h('pre', {class: 'query'}); const qNote = h('p', {class: 'small muted'}); const qHead = h('div', {class: 'panel-title'});
  const showQuery = () => { qText.textContent = chosen.text; qNote.textContent = chosen.note || ''; qHead.replaceChildren(h('h4', {text: chosen.title}), copyButton(chosen.text)); };
  const qSel = h('select', {id: 'impQuery', onchange: e => { chosen = queries[Number(e.target.value)]; showQuery(); }}, queries.map((x, i) => h('option', {value: i, text: x.title})));
  showQuery();
  const file = h('input', {type: 'file', id: 'impFile', accept: '.csv,.txt,.tsv,.xlsx,.json'});
  const schema = h('input', {type: 'text', id: 'impSchema', placeholder: 'Dosyada şema yoksa (ör. SAPABAP1, model adı)'});
  const scopes = [['tables', 'Yalnızca dosyadaki tablolar', 'Dosyada olmayan tablolara dokunulmaz. Tek tek varlık veya tablo yüklerken seçin.'],
    ['schemas', 'Dosyadaki şemaların tamamı', 'Bu şemalarda olup dosyada bulunmayan tablolar "kaynakta kaldırıldı" olur.'],
    ['full', 'Kaynağın tamamı', 'Dosyada bulunmayan tüm tablolar "kaynakta kaldırıldı" olur. Kaynağın tam dökümünü yüklerken seçin.']];
  const scopeBox = h('div', {class: 'choices'}, scopes.map(([v, label, hint], i) => h('label', {}, h('input', {type: 'radio', name: 'impScope', value: v, checked: i === 0}), h('span', {}, h('strong', {text: label}), h('span', {class: 'cell-sub', text: hint})))));
  const result = h('div');
  const body = async dry => {
    if (!file.files[0]) throw new Error('Dosya seçin');
    const f = file.files[0]; if (f.size > 150 * 1024 * 1024) throw new Error('Dosya 150 MB sınırını aşıyor; kaynağı şemalara bölün');
    return {filename: f.name, ...(await gzipBase64(f)), dry_run: dry, default_schema: schema.value.trim(), scope: (document.querySelector('input[name=impScope]:checked') || {}).value || 'tables'};
  };
  const preview = async () => {
    const r = await api(`data_sources/${s.id}/import`, {method: 'POST', body: await body(true)});
    result.replaceChildren(importPreview(r), h('div', {class: 'toolbar'}, btn('İçe aktar', async () => {
      const done = await api(`data_sources/${s.id}/import`, {method: 'POST', body: await body(false)});
      Modal.close(); toast(`İçe aktarıldı: ${countText(done.counts)}`); invalidate('data_sources'); render();
    })));
  };
  Modal.open('İçe aktar: ' + s.name, h('div', {class: 'wizard'},
    h('div', {class: 'wiz-step'}, h('span', {class: 'dg-num', text: '1'}), h('div', {}, h('strong', {text: 'Kaynakta sorguyu çalıştırın'}),
      queries.length > 1 ? h('label', {class: 'field', for: 'impQuery'}, h('span', {text: 'Yöntem'}), h('div', {class: 'control'}, qSel)) : null,
      h('div', {class: 'query-card'}, qHead, qNote, qText))),
    h('div', {class: 'wiz-step'}, h('span', {class: 'dg-num', text: '2'}), h('div', {}, h('strong', {text: 'Sonucu yükleyin'}),
      h('p', {class: 'small muted', text: 'CSV, Excel veya JSON. Biçim içerikten tanınır; büyük dosyalar tarayıcıda sıkıştırılarak gönderilir.'}),
      h('label', {class: 'field', for: 'impFile'}, h('span', {text: 'Dosya'}), h('div', {class: 'control'}, file)),
      h('label', {class: 'field', for: 'impSchema'}, h('span', {text: 'Varsayılan şema'}), h('div', {class: 'control'}, schema)),
      h('div', {class: 'field'}, h('span', {text: 'Kapsam'}), scopeBox))),
    h('div', {class: 'wiz-step'}, h('span', {class: 'dg-num', text: '3'}), h('div', {}, h('strong', {text: 'Ön izleyip uygulayın'}), h('p', {class: 'small muted', text: 'Ön izleme veri yazmaz. Var olan iş adları, açıklamalar ve terim bağları korunur.'}), result))),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('Ön izle', preview)], true);
}
function importPreview(r) {
  const c = r.counts || {};
  const rowsEl = Object.keys(COUNT_LABELS).filter(k => c[k]).map(k => h('tr', {}, h('td', {}, pill(META.option('catalog_changes', 'change', k), tone(k))), h('td', {class: 'num', text: fmt.num(c[k])}),
    h('td', {class: 'small'}, (r.samples[k] || []).slice(0, 6).map(x => x.object + (x.detail ? ` (${x.detail})` : '')).join(', ') + ((r.samples[k] || []).length > 6 ? ' …' : ''))));
  return h('div', {class: 'notice ' + (rowsEl.length ? '' : 'success')},
    h('strong', {text: `Tanınan biçim: ${{csv: 'CSV', excel: 'Excel', sap_ddic: 'SAP ABAP sözlüğü', servicenow: 'ServiceNow sözlüğü', dynamics365: 'Dynamics 365 varlıkları', 'tedarik.catalog.v1': 'Platform JSON sözleşmesi'}[r.format] || r.format}`}),
    h('div', {class: 'small', text: `Dosyada ${fmt.num(r.tables_in_file)} tablo, ${fmt.num(r.columns_in_file)} kolon. ${r.initial ? 'İlk yükleme: değişiklik geçmişi bundan sonraki yüklemelerde tutulur.' : ''}`}),
    rowsEl.length ? h('div', {class: 'tablewrap plain'}, h('table', {}, h('tbody', {}, rowsEl))) : h('div', {class: 'small', text: 'Katalogla aynı; değişiklik yok.'}));
}
function exportDialog(s) {
  const schemaSel = h('select', {id: 'expSchema'}, h('option', {value: '', text: 'Tüm şemalar'}), s.schemas.map(x => h('option', {value: x.schema_name, text: `${x.schema_name || '(şemasız)'} · ${x.tables} tablo`})));
  const only = h('input', {type: 'checkbox', id: 'expOnly'});
  const path = fmtName => { const p = new URLSearchParams({format: fmtName}); if (schemaSel.value || s.schemas.length === 1) p.set('schema', schemaSel.value || s.schemas[0].schema_name); if (only.checked) p.set('only', 'undocumented'); return `data_sources/${s.id}/export?${p}`; };
  Modal.open('Kataloğu dışa aktar', h('div', {},
    h('p', {class: 'intro', text: 'Dosyada her tablo ve kolon bir satırdır. İş adı, açıklama, sınıf, kişisel veri, terim ve sorumlu sütunlarını doldurup "İş açıklamalarını içe aktar" ile geri yükleyin; boş hücre mevcut değeri değiştirmez.'}),
    h('label', {class: 'field', for: 'expSchema'}, h('span', {text: 'Şema'}), h('div', {class: 'control'}, schemaSel)),
    h('label', {class: 'toggle', for: 'expOnly'}, only, h('span', {text: 'Yalnızca tanımı eksik kolonlar'})),
    h('p', {class: 'small muted', text: 'Excel en çok 5000 satır alır; daha büyük kaynaklarda şema seçin veya CSV kullanın (CSV Excel\'de açılır).'})),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('CSV indir', () => download(path('csv'), `${s.code}.csv`), 'secondary'), btn('Excel indir', () => download(path('xlsx'), `${s.code}.xlsx`))]);
}
function descriptionsDialog(s) {
  const file = h('input', {type: 'file', id: 'descFile', accept: '.csv,.txt,.xlsx'}); const result = h('div');
  const send = async dry => { if (!file.files[0]) throw new Error('Dosya seçin'); return api(`data_sources/${s.id}/import-descriptions`, {method: 'POST', body: {filename: file.files[0].name, ...(await gzipBase64(file.files[0])), dry_run: dry}}); };
  const show = r => h('div', {class: 'notice ' + (r.counts.errors ? 'warn' : 'success')}, h('strong', {text: descText(r.counts)}),
    r.errors.length ? h('ul', {class: 'mini small'}, r.errors.slice(0, 20).map(x => h('li', {text: `Satır ${x.row}: ${x.message}`}))) : null);
  Modal.open('İş açıklamalarını içe aktar: ' + s.name, h('div', {}, h('p', {class: 'intro', text: 'Dışa aktardığınız dosyayı doldurup yükleyin. Yalnızca dolu hücreler yazılır; teknik sütunlar yok sayılır. Önce ön izleme yapılır.'}),
    h('label', {class: 'field', for: 'descFile'}, h('span', {text: 'Dosya'}), h('div', {class: 'control'}, file)), result),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('Ön izle', async () => {
    const r = await send(true);
    result.replaceChildren(show(r), btn('Uygula', async () => { const done = await send(false); Modal.close(); toast('Uygulandı: ' + descText(done.counts)); render(); }));
  })], true);
}

// ------------------------------------------------------------------ sahiplik matrisi
PAGES.stewardship = async function stewardshipPage() {
  const d = await api('datagov/stewardship'); await list('org_units');
  setPage('Sahiplik Matrisi', 'Kim hangi veriden sorumlu. Veri sahibi hesap verir ve terimleri onaylar; veri yöneticisi tanımları yazar ve günceller; teknik sorumlu sistemi işletir. Tabloda sahip yoksa veri alanından, o da yoksa kaynaktan devralınır.', [],
    [['Veri Yönetişimi', 'datagov']]);
  const roleText = r => [r.domains ? `${r.domains} alan` : null, r.sources ? `${r.sources} kaynak` : null, r.tables ? `${fmt.num(r.tables)} tablo` : null, r.terms ? `${r.terms} terim` : null].filter(Boolean).join(' · ') || '—';
  const people = d.people.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kişi', 'Veri sahibi (A)', 'Veri yöneticisi (R)', 'Teknik sorumlu'].map(x => h('th', {text: x})))),
    h('tbody', {}, d.people.map(p => h('tr', {}, h('td', {}, h('strong', {text: p.person})), h('td', {class: 'small', text: roleText(p.owner)}), h('td', {class: 'small', text: roleText(p.steward)}), h('td', {class: 'small', text: roleText(p.custodian)})))))) :
    empty('Atama yok', 'Veri alanlarına, kaynaklara ve tablolara sahip ve veri yöneticisi atayın.');
  const domains = h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Veri alanı', 'Üst alan', 'Sorumlu birim', 'Veri sahibi', 'Veri yöneticisi'].map(x => h('th', {text: x})))),
    h('tbody', {}, d.domains.map(x => h('tr', {class: 'link', onclick: () => openRecord('data_domains', x.id)}, h('td', {}, h('strong', {text: x.name}), h('div', {class: 'cell-sub', text: x.code})), h('td', {text: x.parent_name || '—'}),
      h('td', {text: x.org_unit || '—'}), h('td', {}, personText(x.owner)), h('td', {}, personText(x.steward)))))));
  const sources = h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kaynak', 'Veri alanı', 'Sistem sahibi', 'Veri yöneticisi', 'Teknik sorumlu'].map(x => h('th', {text: x})))),
    h('tbody', {}, d.sources.map(x => h('tr', {class: 'link', onclick: () => Router.go('datasource/' + x.id)}, h('td', {}, h('strong', {text: x.name}), h('div', {class: 'cell-sub', text: META.option('data_sources', 'platform', x.platform)})),
      h('td', {text: x.domain_name || '—'}), h('td', {}, personText(x.owner)), h('td', {}, personText(x.steward)), h('td', {}, personText(x.custodian)))))));
  content(
    h('div', {class: 'grid four'}, metric('Sahibi belirsiz tablo', fmt.num(d.unowned_tables), 'Devralma dahil', d.unowned_tables ? 'bad' : 'good', () => Router.go('catalog?f=unowned')),
      metric('Veri yöneticisi olmayan tablo', fmt.num(d.tables_without_steward), 'Devralma dahil', d.tables_without_steward ? 'warn' : 'good'),
      metric('Sorumlu kişi', fmt.num(d.people.length), 'Doğrudan atanmış'), metric('Veri alanı', fmt.num(d.domains.length), `${d.sources.length} kaynak`)),
    panel('Kişi bazında sorumluluklar', people), panel('Veri alanları', d.domains.length ? domains : empty('Veri alanı yok', ''), canWrite('data_domains') ? btn('+ Veri alanı', () => createRecord('data_domains'), 'ghost small') : null),
    panel('Kaynaklar', d.sources.length ? sources : empty('Kaynak yok', '')));
};

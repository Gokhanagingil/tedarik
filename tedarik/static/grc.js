'use strict';
/* Uyum ve güvence ekranları: standart kütüphanesi ve tarayıcısı, madde seçici, standartlar arası ilişkiler ve
   eşleme çalışma alanı, bulgu etkisi, entegre denetim çalışma alanı. app.js ve pages.js yardımcılarını kullanır;
   dış kütüphane yok, satır içi stil yok (CSP). */

const REL_LABEL = {equivalent: 'Eşdeğer', subset: 'Alt küme', superset: 'Üst küme', intersects: 'Kesişir', related: 'İlgili'};
const REL_HINT = {
  equivalent: 'İki madde aynı gereksinimi tanımlar.',
  subset: 'Bu madde, karşıdakinin bir parçasıdır: bu maddedeki ihlal karşıdakini de ihlal eder.',
  superset: 'Bu madde karşıdakini kapsar ve fazlasını ister: karşıdaki ihlal bu maddeyi de ihlal eder.',
  intersects: 'Kısmen örtüşür: ihlal karşı maddeyi etkileyebilir.',
  related: 'Konu olarak ilgili; bilgi amaçlı.'};
const IMPACT_LABEL = {direct: ['Doğrudan', 'bad'], certain: ['Kesin etkilenir', 'bad'], possible: ['Olası etki', 'warn'], related: ['İlgili', 'neutral']};
const STRUCTURAL = new Set(['family', 'function', 'category']);
function relPill(rel) { return pill(REL_LABEL[rel] || rel, {equivalent: 'good', subset: 'purple', superset: 'purple', intersects: 'warn'}[rel] || 'neutral'); }
function impactPill(level) { const [t, c] = IMPACT_LABEL[level] || [level, 'neutral']; return pill(t, c); }
function stdName(s) { return s ? `${s.code}${s.version ? ' ' + s.version : ''}` : ''; }

// ------------------------------------------------------------------ madde ağacı (önbellekli)
async function clauseTree(standardId, refresh = false) {
  const key = 'tree:' + standardId;
  if (!refresh && S.cache[key]) return S.cache[key];
  const d = await api(`standards/${standardId}/tree`);
  const byId = new Map(d.clauses.map(c => [c.id, {...c, children: []}]));
  const roots = [];
  for (const c of byId.values()) { const p = c.parent_id && byId.get(c.parent_id); if (p) p.children.push(c); else roots.push(c); }
  S.cache[key] = {standard: d.standard, byId, roots, items: [...byId.values()]};
  return S.cache[key];
}
function leaves(node) { return node.children.length ? node.children.flatMap(leaves) : [node]; }

/** Madde seçici: standart seç → ağaçta aile/kategori düzeyinde veya tek tek seç; arama; seçilenlerin özeti.
 *  initial: [{id, standard_id}] · value(): seçili madde kimlikleri. */
function clausePicker(initial = [], {standards = null, hint = ''} = {}) {
  const chosen = new Map(initial.map(c => [c.id, c.standard_id || null]));
  const stdSel = h('select', {'aria-label': 'Standart'});
  const search = h('input', {type: 'search', class: 'searchbar', placeholder: 'Madde kodu veya başlık ara…', 'aria-label': 'Madde ara'});
  const box = h('div', {class: 'tree choices tall'}); const summary = h('div', {class: 'chips picker-summary'});
  const open = new Set(); let tree = null;
  const counts = () => { const m = {}; for (const sid of chosen.values()) m[sid] = (m[sid] || 0) + 1; return m; };
  const drawSummary = () => {
    const m = counts(); const all = S.cache.standards || [];
    summary.replaceChildren(chosen.size ? h('strong', {text: `${chosen.size} madde seçildi`}) : h('span', {class: 'muted small', text: 'Henüz madde seçilmedi'}),
      ...Object.entries(m).map(([sid, n]) => { const st = all.find(x => String(x.id) === sid); return h('span', {class: 'chip', text: `${st ? stdName(st) : 'Diğer'}: ${n}`}); }),
      chosen.size ? h('button', {type: 'button', class: 'btn ghost small', text: 'Seçimi temizle', onclick: () => { chosen.clear(); draw(); }}) : null);
  };
  const toggle = (nodes, on) => { for (const n of nodes) { if (on) chosen.set(n.id, tree.standard.id); else chosen.delete(n.id); } draw(); };
  const row = (node, depth) => {
    const ls = node.children.length ? leaves(node) : [node];
    const picked = ls.filter(l => chosen.has(l.id)).length;
    const cb = h('input', {type: 'checkbox', checked: picked === ls.length, 'aria-label': node.code});
    cb.indeterminate = picked > 0 && picked < ls.length;
    cb.addEventListener('change', () => toggle(ls, cb.checked));
    const label = h('span', {class: 'tree-label'}, h('b', {text: node.code}), ' ', node.title,
      node.children.length ? h('span', {class: 'muted small', text: `  (${picked}/${ls.length})`}) : null,
      node.applicable === 0 ? h('span', {class: 'muted small', text: '  · kapsam dışı'}) : null);
    const caret = node.children.length ? h('button', {type: 'button', class: 'tree-toggle', 'aria-expanded': String(open.has(node.id)), 'aria-label': 'Aç / kapat',
      text: open.has(node.id) ? '▾' : '▸', onclick: () => { if (open.has(node.id)) open.delete(node.id); else open.add(node.id); draw(); }}) : h('span', {class: 'tree-toggle'});
    const el = h('div', {class: 'tree-row d' + Math.min(depth, 4)}, caret, h('label', {}, cb, label));
    const out = [el];
    if (node.children.length && open.has(node.id)) for (const ch of node.children) out.push(...row(ch, depth + 1));
    return out;
  };
  const draw = () => {
    drawSummary(); clear(box);
    if (!tree) { box.append(h('div', {class: 'muted small', text: 'Standart seçin'})); return; }
    const q = search.value.trim().toLocaleLowerCase(TR);
    if (q) {
      const hits = tree.items.filter(c => !c.children.length && (c.code.toLocaleLowerCase(TR).includes(q) || c.title.toLocaleLowerCase(TR).includes(q))).slice(0, 200);
      for (const c of hits) box.append(...row(c, 0));
      if (!hits.length) box.append(h('div', {class: 'muted small', text: 'Eşleşen madde yok'}));
      return;
    }
    const ls = tree.items.filter(c => !c.children.length);
    box.append(h('div', {class: 'tree-row tree-all'}, h('label', {}, h('input', {type: 'checkbox', checked: ls.every(l => chosen.has(l.id)),
      onchange: e => toggle(ls, e.target.checked)}), h('strong', {text: `Bu standardın tüm maddeleri (${ls.length})`}))));
    for (const r of tree.roots) box.append(...row(r, 0));
  };
  const load = async () => { tree = stdSel.value ? await clauseTree(Number(stdSel.value)) : null; draw(); };
  stdSel.addEventListener('change', () => load().catch(e => toast(e.message, false)));
  search.addEventListener('input', debounce(draw, 150));
  (async () => {
    const all = (await list('standards')).filter(st => !standards || standards.includes(st.id))
      .sort((a, b) => (b.active - a.active) || a.code.localeCompare(b.code, TR));
    const missing = [...chosen.entries()].filter(([, sid]) => !sid).map(([id]) => id);
    if (missing.length) for (const c of await api(`clauses?id__in=${missing.slice(0, 900).join(',')}&limit=1000`)) chosen.set(c.id, c.standard_id);
    const first = [...chosen.values()][0] || (all[0] && all[0].id);
    stdSel.replaceChildren(...all.map(st => h('option', {value: st.id, text: `${stdName(st)} · ${st.name}${st.active ? '' : ' (başvuru)'}`, selected: st.id === first})));
    if (!all.length) stdSel.append(h('option', {value: '', text: 'Standart yok'}));
    await load();
  })().catch(e => toast(e.message, false));
  return {node: h('div', {class: 'picker'}, hint ? h('p', {class: 'muted small', text: hint}) : null, h('div', {class: 'picker-bar'}, stdSel, search), box, summary),
    value: () => [...chosen.keys()], standards: () => [...new Set(chosen.values())].filter(Boolean)};
}
function pickClauses(title, initial, {intro, okText = 'Kaydet'} = {}) {
  return new Promise(resolve => {
    const p = clausePicker(initial, {hint: intro});
    Modal.open(title, p.node, [btn('Vazgeç', () => { Modal.close(); resolve(null); }, 'secondary'),
      btn(okText, () => { const v = p.value(); Modal.close(); resolve(v); })], true);
  });
}

// ------------------------------------------------------------------ standart kütüphanesi
PAGES.library = async function libraryPage() {
  const d = await api('standards/library'); invalidate('standards');
  const admin = canWrite('standards');
  setPage('Standart Kütüphanesi', 'Kurulu standartlar, tam metniyle yüklenebilen kütüphane paketleri, lisanslı metin ve çapraz eşleme içe aktarımı.',
    [admin ? btn('Lisanslı metni içe aktar', () => importStandard(), 'secondary') : null, canWrite('clause_links') ? btn('Çapraz eşleme içe aktar', () => importLinks(), 'secondary') : null,
      d.standards.length > 1 ? btn('Eşleme çalışma alanı', () => Router.go('crosswalk')) : null]);
  const packages = d.packages.map(p => h('div', {class: 'panel lib-card'},
    h('div', {class: 'panel-title'}, h('h3', {}, `${p.code} `, h('span', {class: 'sub', text: p.version || ''})),
      p.installed ? pill(p.installed.current ? 'Kurulu · güncel' : 'Kurulu · güncelleme var', p.installed.current ? 'good' : 'warn') : pill('Kurulu değil', 'neutral')),
    h('p', {class: 'muted', text: p.name}), h('p', {class: 'small', text: p.description}),
    statStrip([['Madde', fmt.num(p.clauses, 0)], ['Resmî ilişki', fmt.num(p.links, 0)], ['Yayın', fmt.date(p.published)], ['Dil', (p.language || '').toUpperCase()]]),
    h('p', {class: 'muted small', text: 'Lisans: ' + (p.license || '—')}),
    p.sources.length ? h('details', {class: 'small'}, h('summary', {text: 'Kaynak ve bütünlük'}), h('ul', {class: 'mini'}, p.sources.map(s => h('li', {}, extLink(s.url), h('span', {class: 'cell-sub mono', text: 'SHA-256 ' + s.sha256}))))) : null,
    h('div', {class: 'toolbar'}, admin ? btn(p.installed ? (p.installed.current ? 'Yeniden kur' : 'Güncelle') : 'Kur', async () => {
      const r = await api('standards/library/install', {method: 'POST', body: {key: p.key}});
      invalidate('standards', 'clauses'); delete S.cache['tree:' + r.standard_id];
      toast(`${r.code}: ${r.created} yeni, ${r.updated} güncellenen madde, ${r.links} ilişki`); render();
    }, p.installed ? 'secondary' : '') : null, p.installed ? btn('Aç', () => Router.go('standard/' + p.installed.standard_id), 'secondary') : null)));
  const rows = d.standards.map(s => h('tr', {class: 'clickable', onclick: () => Router.go('standard/' + s.id)},
    h('td', {class: 'cell-primary'}, stdName(s), h('span', {class: 'cell-sub', text: s.name})),
    h('td', {}, s.library_key ? pill('Kütüphane', 'good') : s.installed_at ? pill('İçe aktarım', 'purple') : pill('Elle / demo', 'neutral'), s.active ? null : pill('Başvuru (kapsam dışı)', 'neutral')),
    h('td', {class: 'num', text: fmt.num(s.clauses, 0)}), h('td', {class: 'num'}, fmt.num(s.mapped, 0), h('span', {class: 'cell-sub', text: s.clauses ? fmt.pct(100 * s.mapped / s.clauses) + ' kontrollü' : ''})),
    h('td', {class: 'num', text: fmt.num(s.cross_links, 0)})));
  content(
    h('div', {class: 'notice', text: 'Standart maddeleri birbirine ve kontrollere bağlıdır: bir maddede bulgu çıktığında başka standartlarda etkilenen maddeler, bir kontrol test edildiğinde güvence alan tüm maddeler otomatik görünür.'}),
    panel(`Kurulu standartlar (${d.standards.length})`, d.standards.length ? h('div', {class: 'tablewrap'}, h('table', {},
      h('thead', {}, h('tr', {}, ['Standart', 'Kaynak', 'Madde', 'Kontrole eşli', 'Diğer standartlarla ilişki'].map((t, i) => h('th', {class: i > 1 ? 'num' : '', text: t})))),
      h('tbody', {}, rows))) : empty('Kurulu standart yok', 'Kütüphaneden kurun veya lisanslı metni içe aktarın.')),
    h('h3', {class: 'group-title', text: 'Kütüphane paketleri (tam metin)'}),
    h('div', {class: 'grid two'}, packages),
    panel('Pakete konamayan standartlar', h('div', {}, h('p', {class: 'small', text: 'Bu standartların tam metni telif veya lisans nedeniyle pakete konmaz; kısmi yükleme yapılmadı. Kurumunuzun satın aldığı kopyayı "Lisanslı metni içe aktar" ile yükleyin; ilişkiler ve entegre denetim aynı şekilde çalışır.'}),
      h('ul', {class: 'mini'}, d.unavailable.map(u => h('li', {}, h('strong', {text: u.name}), h('span', {class: 'cell-sub', text: u.reason})))))));
};

async function importStandard() {
  const code = h('input', {id: 'isCode', required: true, placeholder: 'ör. ISO/IEC 27001'}); const name = h('input', {id: 'isName', required: true, placeholder: 'ör. Bilgi güvenliği yönetim sistemleri — Gereksinimler'});
  const version = h('input', {id: 'isVer', placeholder: 'ör. 2022'}); const issuer = h('input', {id: 'isIss', placeholder: 'ör. ISO/IEC'});
  const license = h('input', {id: 'isLic', placeholder: 'ör. Kurum lisansı, 5 kullanıcı'});
  const file = h('input', {type: 'file', id: 'isFile', accept: '.xlsx,.csv,.json'}); const out = h('div');
  const body = () => ({standard: {code: code.value.trim(), name: name.value.trim(), version: version.value.trim(), issuer: issuer.value.trim(), license: license.value.trim()}});
  const send = async dry => {
    if (!file.files[0]) throw new Error('Dosya seçin');
    const r = await api('standards/import', {method: 'POST', body: {...body(), filename: file.files[0].name, content_base64: await fileToBase64(file.files[0]), dry_run: dry}});
    out.replaceChildren(h('div', {class: 'notice ' + (dry ? '' : 'good')}, dry ? `Deneme: ${r.clauses} madde okundu · ${r.created} yeni · ${r.updated_or_unchanged} mevcut${r.standard_exists ? ' (standart zaten var, güncellenir)' : ''}` :
      `${r.code}: ${r.created} yeni, ${r.updated} güncellenen madde`));
    if (!dry) { invalidate('standards', 'clauses'); delete S.cache['tree:' + r.standard_id]; Modal.close(); toast('Standart içe aktarıldı'); Router.go('standard/' + r.standard_id); }
  };
  Modal.open('Lisanslı standart metnini içe aktar', h('div', {class: 'formgrid'},
    h('p', {class: 'intro wide', text: 'Excel veya CSV: "Madde kodu" ve "Başlık" zorunlu; "Üst madde", "Tür", "Metin", "Rehber", "Değerlendirme", "Etiketler", "Uygulanabilir", "Gerekçe" isteğe bağlı. Aynı standart yeniden yüklenirse metinler güncellenir; uygulanabilirlik kararlarınız ve eşlemeler korunur. Paket biçimindeki JSON dosyası da kabul edilir (standart bilgisi dosyadan okunur).'}),
    h('label', {class: 'field', for: 'isCode'}, 'Standart kodu *', h('div', {class: 'control'}, code)), h('label', {class: 'field', for: 'isVer'}, 'Sürüm', h('div', {class: 'control'}, version)),
    h('label', {class: 'field wide', for: 'isName'}, 'Standart adı *', h('div', {class: 'control'}, name)),
    h('label', {class: 'field', for: 'isIss'}, 'Yayımlayan', h('div', {class: 'control'}, issuer)), h('label', {class: 'field', for: 'isLic'}, 'Lisans bilgisi', h('div', {class: 'control'}, license)),
    h('label', {class: 'field wide', for: 'isFile'}, 'Dosya', h('div', {class: 'control'}, file)),
    h('div', {class: 'wide'}, h('a', {href: '#', text: 'Şablonu indir (CSV)', onclick: e => { e.preventDefault(); download('standards/import/template', 'standart-metni-sablonu.csv'); }})), h('div', {class: 'wide'}, out)),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Dene', () => send(true), 'secondary'), btn('İçe aktar', () => send(false))], true);
}

async function importLinks() {
  const file = h('input', {type: 'file', id: 'ilFile', accept: '.xlsx,.csv'}); const out = h('div');
  const send = async dry => {
    if (!file.files[0]) throw new Error('Dosya seçin');
    const r = await api('clause_links/import', {method: 'POST', body: {filename: file.files[0].name, content_base64: await fileToBase64(file.files[0]), dry_run: dry}});
    out.replaceChildren(h('div', {class: 'notice'}, `${dry ? 'Deneme' : 'Sonuç'}: ${r.create || 0} yeni · ${r.update || 0} güncellenen · ${r.skip || 0} değişmeyen · ${r.error || 0} hatalı satır`),
      (r.rows || []).filter(x => x.action === 'error').length ? h('ul', {class: 'mini'}, r.rows.filter(x => x.action === 'error').slice(0, 30).map(x => h('li', {}, h('strong', {text: x.row_no + '. satır'}), h('span', {class: 'cell-sub', text: x.message})))) : null);
    if (!dry) toast('Çapraz eşleme içe aktarıldı');
  };
  Modal.open('Çapraz eşleme içe aktar', h('div', {},
    h('p', {class: 'intro', text: 'Sütunlar: Kaynak standart, Kaynak madde, Hedef standart, Hedef madde, İlişki (Eşdeğer, Alt küme, Üst küme, Kesişir, İlgili), Gerekçe. Standart kod veya adla, madde koduyla bulunur. Yayımlanmış eşleme tablolarını (ör. NIST OLIR, ISO 27001 ↔ 27701 Ek D/E) kurumunuzun kopyasından bu biçime aktarabilirsiniz.'}),
    h('label', {class: 'field', for: 'ilFile'}, 'Dosya', h('div', {class: 'control'}, file)),
    h('p', {}, h('a', {href: '#', text: 'Şablonu indir (CSV)', onclick: e => { e.preventDefault(); download('standards/import/template?kind=links', 'capraz-esleme-sablonu.csv'); }})), out),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('Dene', () => send(true), 'secondary'), btn('İçe aktar', () => send(false))], true);
}

// ------------------------------------------------------------------ standart tarayıcısı
PAGES.standard = async function standardPage(parts, params) {
  const id = Number(parts[1]);
  const t = await clauseTree(id, true); const st = t.standard;
  const q = h('input', {type: 'search', class: 'searchbar', placeholder: 'Madde kodu, başlık veya etiket ara…  ( / )', id: 'tableSearch', value: params.get('q') || '', 'aria-label': 'Maddelerde ara'});
  const only = h('select', {class: 'compact', 'aria-label': 'Süz'}, [['', 'Tüm maddeler'], ['nocontrol', 'Kontrolü olmayanlar'], ['cross', 'Başka standartla ilişkili'], ['na', 'Kapsam dışı']].map(([v, l]) => h('option', {value: v, text: l})));
  const host = h('div', {class: 'tree std-tree'}); const open = new Set(t.roots.length <= 8 ? t.roots.map(r => r.id) : []);
  const leafsAll = t.items.filter(c => !c.children.length);
  setPage(stdName(st), st.name + (st.active ? '' : ' · başvuru amaçlı (uyum kapsamında değil)'), [
    canWrite('standards') ? btn(st.active ? 'Kapsamdan çıkar' : 'Uyum kapsamına al', async () => {
      if (st.active && !await confirmDialog('Kapsamdan çıkar', 'Standart uyum panosu ve sağlık kontrolünde sayılmaz; maddeler, eşlemeler ve ilişkiler korunur.', 'Kapsamdan çıkar')) return;
      await api('standards/' + id, {method: 'PATCH', body: {active: st.active ? 0 : 1}}); invalidate('standards'); toast(st.active ? 'Standart kapsamdan çıkarıldı' : 'Standart uyum kapsamına alındı'); render();
    }, st.active ? 'secondary' : '') : null,
    btn('Uygulanabilirlik bildirimi (SoA)', () => Router.go('soa/' + id), 'secondary'),
    canWrite('standards') ? btn('Standardı düzenle', () => recordForm('standards', st, {onsaved: () => render()}), 'secondary') : null], [['Standart Kütüphanesi', 'library']]);
  const match = (c, text, mode) => (!text || `${c.code} ${c.title} ${c.tags || ''}`.toLocaleLowerCase(TR).includes(text)) &&
    (mode !== 'nocontrol' || (!c.controls && !c.children.length && c.applicable)) && (mode !== 'cross' || c.cross) && (mode !== 'na' || c.applicable === 0);
  const line = (c, depth) => {
    const el = h('div', {class: 'tree-row d' + Math.min(depth, 4) + (STRUCTURAL.has(c.clause_type) ? ' head' : '')},
      c.children.length ? h('button', {type: 'button', class: 'tree-toggle', 'aria-expanded': String(open.has(c.id)), text: open.has(c.id) ? '▾' : '▸',
        onclick: e => { e.stopPropagation(); if (open.has(c.id)) open.delete(c.id); else open.add(c.id); draw(); }}) : h('span', {class: 'tree-toggle'}),
      h('button', {type: 'button', class: 'tree-open', onclick: () => {
        if (STRUCTURAL.has(c.clause_type) && c.children.length) { if (open.has(c.id)) open.delete(c.id); else open.add(c.id); draw(); } else DETAILS.clauses(c.id); }},
        h('b', {text: c.code}), ' ', c.title),
      h('span', {class: 'tree-tags'}, c.applicable === 0 ? pill('Kapsam dışı', 'neutral') : null, c.controls ? pill(`${c.controls} kontrol`, 'good') : null,
        c.cross ? pill('Çapraz ilişki', 'purple') : null, !c.children.length && c.applicable && !c.controls && !STRUCTURAL.has(c.clause_type) ? pill('Kontrol yok', 'warn') : null));
    return el;
  };
  const draw = () => {
    clear(host); const text = q.value.trim().toLocaleLowerCase(TR); const mode = only.value;
    if (text || mode) {
      const hits = t.items.filter(c => match(c, text, mode));
      for (const c of hits.slice(0, 400)) host.append(line(c, 0));
      host.prepend(h('div', {class: 'muted small', text: `${hits.length} madde${hits.length > 400 ? ' (ilk 400 gösteriliyor)' : ''}`}));
      return;
    }
    const walk = (c, depth) => { host.append(line(c, depth)); if (open.has(c.id)) for (const ch of c.children) walk(ch, depth + 1); };
    for (const r of t.roots) walk(r, 0);
  };
  q.addEventListener('input', debounce(draw, 150)); only.addEventListener('change', draw);
  const mapped = leafsAll.filter(c => c.controls).length; const cross = t.items.filter(c => c.cross).length; const na = t.items.filter(c => c.applicable === 0).length;
  content(
    st.license ? h('div', {class: 'notice small', text: `Kaynak: ${st.issuer || ''} · Lisans: ${st.license}${st.published ? ' · Yayın: ' + fmt.date(st.published) : ''}`}) : null,
    statStrip([['Madde', fmt.num(t.items.length, 0)], ['Kontrole eşli', `${fmt.num(mapped, 0)} / ${fmt.num(leafsAll.length, 0)}`, mapped < leafsAll.length ? 'warn' : 'good'],
      ['Başka standartla ilişkili', fmt.num(cross, 0)], ['Kapsam dışı', fmt.num(na, 0)]]),
    h('div', {class: 'panel'}, h('div', {class: 'filters'}, q, only,
      h('button', {type: 'button', class: 'btn ghost small', text: 'Tümünü aç', onclick: () => { t.items.filter(c => c.children.length).forEach(c => open.add(c.id)); draw(); }}),
      h('button', {type: 'button', class: 'btn ghost small', text: 'Tümünü kapat', onclick: () => { open.clear(); draw(); }})), host));
  draw();
  if (params.get('clause')) DETAILS.clauses(Number(params.get('clause')));
};

// ------------------------------------------------------------------ madde detayı (ilişkiler dahil)
DETAILS.clauses = async function clauseDetail(id) {
  let c; try { c = await api(`clauses/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('clauses'); DETAILS.clauses(id); };
  const r = c.relations || {links: [], shared: [], findings: []};
  const longText = (title, text, open = false) => text ? h('details', {class: 'clause-box', open}, h('summary', {text: title}), h('div', {class: 'clause-text', text})) : null;
  const linkRows = r.links.length ? h('ul', {class: 'mini'}, r.links.map(l => h('li', {class: 'link', onclick: () => DETAILS.clauses(l.clause_id)},
    h('strong', {text: `${l.standard} · ${l.code}`}), h('span', {class: 'cell-sub', text: l.title}),
    h('div', {class: 'chips'}, relPill(l.relation), pill(META.option('clause_links', 'source', l.source), 'neutral'), l.rationale ? h('span', {class: 'muted small', text: l.rationale}) : null,
      canWrite('clause_links') && l.source !== 'official' ? h('button', {type: 'button', class: 'btn ghost small', text: 'Pasifleştir', onclick: async e => {
        e.stopPropagation(); if (!await confirmDialog('İlişkiyi pasifleştir', 'İlişki silinmez; pasif ilişki etki hesabında kullanılmaz.', 'Pasifleştir')) return;
        await api('clause_links/' + l.link_id, {method: 'PATCH', body: {active: 0}}); toast('İlişki pasifleştirildi'); reload(); }}) : null)))) :
    h('div', {class: 'muted small', text: 'Başka maddeyle ilişki tanımlı değil.'});
  const groupedShared = {}; for (const x of r.shared) (groupedShared[x.standard] = groupedShared[x.standard] || []).push(x);
  const body = h('div', {},
    h('div', {class: 'chips'}, c.applicable ? pill('Uygulanabilir', 'good') : pill('Kapsam dışı', 'neutral'), c.clause_type ? pill(META.option('clauses', 'clause_type', c.clause_type), 'neutral') : null,
      ...(c.tags ? c.tags.split(',').map(t => h('span', {class: 'chip', text: t.trim()})) : [])), h('br'),
    !c.applicable ? h('div', {class: 'notice', text: 'Kapsam dışı gerekçesi: ' + (c.justification || '—')}) :
      !c.controls.length && !c.children.length && !STRUCTURAL.has(c.clause_type) ? h('div', {class: 'notice warn', text: 'Bu maddeyi karşılayan kontrol yok.' + (r.shared.length ? '' : ' Bir kontrolle eşleyin; aynı kontrol diğer standartların maddelerini de karşılayabilir.')}) : null,
    r.findings.length ? h('div', {class: 'notice bad compact-list'}, h('strong', {text: `Bu maddeyi etkileyen ${r.findings.length} açık bulgu`}),
      h('ul', {class: 'plain'}, r.findings.slice(0, 5).map(f => h('li', {}, h('a', {href: '#', text: `${f.code} · ${f.title}`, onclick: e => { e.preventDefault(); openRecord('findings', f.id); }}),
        ' ', impactPill(f.level), h('span', {class: 'muted small', text: ' ' + f.reasons[0]})))),
      r.findings.length > 5 ? h('div', {class: 'small', text: `+${r.findings.length - 5} bulgu daha (Bulgular listesinde)`}) : null) : null,
    section('Madde', kv([['Standart', c.standard ? h('a', {href: '#/standard/' + c.standard.id, text: `${c.standard.code} ${c.standard.version || ''}`}) : null], ['Madde', c.code], ['Başlık', c.title]])),
    longText('Madde metni', c.description, true), longText('Rehber / uygulama örnekleri', c.guidance), longText('Denetçi için değerlendirme yöntemi', c.assessment),
    section(`Diğer standartlardaki ilişkili maddeler (${r.links.length})`, linkRows, canWrite('clause_links') ? h('span', {class: 'toolbar'},
      btn('+ İlişki', () => addRelation(c, reload), 'ghost small'), btn('Öneriler', () => showSuggestions(c, reload), 'ghost small')) : null),
    r.shared.length ? section(`Ortak kontrolle güvence alan maddeler (${r.shared.length})`, h('div', {}, h('p', {class: 'muted small', text: 'Bu maddeyi karşılayan kontrol(ler) aşağıdaki maddeleri de karşılar; tek test ve tek kanıt hepsine sayılır.'}),
      ...Object.entries(groupedShared).map(([std, items]) => h('div', {}, h('div', {class: 'choice-group', text: std}), h('div', {class: 'chips'}, items.map(x => h('a', {class: 'chip', href: '#/standard/' + x.standard_id + '?clause=' + x.clause_id, title: `${x.title} · kontrol: ${x.controls.join(', ')}`, text: x.code}))))))) : null,
    c.children.length ? section(`Alt maddeler (${c.children.length})`, recordList('clauses', c.children)) : null,
    section(`Karşılayan kontroller (${c.controls.length})`, recordList('controls', c.controls, {chips: k => [k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral')], none: 'Kontrol yok'})),
    c.documents.length ? section(`Dokümanlar (${c.documents.length})`, recordList('documents', c.documents, {chips: d => [display('documents', 'status', d.status)]})) : null,
    c.findings.length ? section(`Bu maddeye bağlı bulgular (${c.findings.length})`, recordList('findings', c.findings, {chips: f => [display('findings', 'severity', f.severity), display('findings', 'status', f.status)]})) : null,
    c.evidence.length ? section(`Kanıtlar (${c.evidence.length})`, recordList('evidence', c.evidence)) : null);
  Drawer.open(`${c.code} · ${c.title}`, body, [btn('Denetim geçmişi', () => { Drawer.close(); Router.go('archive?clause_id=' + c.id); }, 'secondary'),
    canWrite('clauses') ? btn('Uygulanabilirlik', () => recordForm('clauses', c, {only: ['applicable', 'justification'], title: 'Uygulanabilirlik: ' + c.code, onsaved: reload}), 'secondary') : null,
    canWrite('clauses') ? btn('Düzenle', () => recordForm('clauses', c, {onsaved: reload}), 'secondary') : null], c.standard ? stdName(c.standard) : 'Standart maddesi');
};

async function addRelation(clause, done, preset = null) {
  const picker = preset ? null : clausePicker([], {hint: 'İlişkilendirilecek maddeyi seçin (başka bir standarttan).'});
  const rel = h('select', {id: 'relType'}, Object.entries(REL_LABEL).map(([v, l]) => h('option', {value: v, text: l, selected: v === 'intersects'})));
  const hint = h('p', {class: 'muted small', text: REL_HINT.intersects}); rel.addEventListener('change', () => { hint.textContent = REL_HINT[rel.value]; });
  const why = h('textarea', {id: 'relWhy', placeholder: 'Neden ilişkili? (denetçi için kısa açıklama)'});
  Modal.open('İlişki ekle: ' + clause.code, h('div', {},
    preset ? h('p', {class: 'intro', text: `${clause.code} ↔ ${preset.standard} ${preset.code} · ${preset.title}`}) : picker.node,
    h('label', {class: 'field', for: 'relType'}, `İlişki (${clause.code} → seçilen)`, h('div', {class: 'control'}, rel)), hint,
    h('label', {class: 'field', for: 'relWhy'}, 'Gerekçe', h('div', {class: 'control'}, why))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => {
      const targets = preset ? [preset.clause_id] : picker.value().filter(x => x !== clause.id);
      if (!targets.length) throw new Error('Madde seçin');
      for (const t of targets) await api('clause_links', {method: 'POST', body: {from_clause_id: clause.id, to_clause_id: t, relation: rel.value, rationale: why.value.trim() || null, source: preset ? 'suggested' : 'manual'}});
      Modal.close(); toast(`${targets.length} ilişki kaydedildi`); done();
    })], true);
}
async function showSuggestions(clause, done) {
  const standards = (await list('standards')).filter(s => s.id !== clause.standard_id);
  const sel = h('select', {'aria-label': 'Hedef standart'}, h('option', {value: '', text: 'Tüm standartlar'}), standards.map(s => h('option', {value: s.id, text: stdName(s)})));
  const out = h('div', {class: 'muted small', text: 'Yükleniyor…'});
  const load = async () => {
    const d = await api(`clauses/${clause.id}/suggestions` + (sel.value ? '?standard_id=' + sel.value : ''));
    out.replaceChildren(d.suggestions.length ? h('ul', {class: 'mini'}, d.suggestions.map(sg => h('li', {},
      h('strong', {text: `${sg.standard} · ${sg.code}`}), h('span', {class: 'cell-sub', text: sg.title}),
      h('div', {class: 'chips'}, pill('Benzerlik ' + Math.round(sg.score * 100) + '%', sg.score > 0.35 ? 'good' : 'neutral'),
        btn('İlişkilendir…', () => { Modal.close(); addRelation(clause, done, sg); }, 'ghost small'))))) : h('div', {class: 'muted small', text: 'Belirgin benzerlik bulunamadı.'}),
      h('p', {class: 'muted small', text: d.note}));
  };
  sel.addEventListener('change', () => load().catch(e => toast(e.message, false)));
  Modal.open('Eşleme önerileri: ' + clause.code, h('div', {}, h('div', {class: 'filters'}, sel), out), [btn('Kapat', () => Modal.close(), 'secondary')], true);
  await load();
}

// ------------------------------------------------------------------ eşleme çalışma alanı
PAGES.crosswalk = async function crosswalkPage(parts, params) {
  const standards = await list('standards', true);
  setPage('Eşleme Çalışma Alanı', 'İki standardın maddelerini yan yana eşleyin. Öneriler metin benzerliğine dayanır; ilişki yalnızca siz onayladığınızda kaydedilir.', [], [['Standart Kütüphanesi', 'library']]);
  if (standards.length < 2) { content(empty('En az iki standart gerekli', 'Kütüphaneden kurun veya içe aktarın.')); return; }
  const src = h('select', {'aria-label': 'Kaynak standart'}, standards.map(s => h('option', {value: s.id, text: stdName(s), selected: String(s.id) === params.get('source')})));
  const dst = h('select', {'aria-label': 'Hedef standart'}, standards.map((s, i) => h('option', {value: s.id, text: stdName(s), selected: params.get('target') ? String(s.id) === params.get('target') : i === 1})));
  const q = h('input', {type: 'search', class: 'searchbar', placeholder: 'Kaynak maddede ara…', value: params.get('q') || ''});
  const unlinked = h('input', {type: 'checkbox', checked: params.get('unlinked') === '1'});
  const host = h('div'); let offset = Number(params.get('offset') || 0);
  const can = canWrite('clause_links');
  const load = async () => {
    if (src.value === dst.value) { host.replaceChildren(h('div', {class: 'notice warn', text: 'Kaynak ve hedef farklı olmalı'})); return; }
    host.replaceChildren(h('div', {class: 'muted small', text: 'Hesaplanıyor…'}));
    const d = await api(`standards/${src.value}/crosswalk?` + new URLSearchParams({target_id: dst.value, offset, limit: 20, q: q.value.trim(), unlinked: unlinked.checked ? '1' : '0'}));
    const save = async (item, target, relation) => {
      await api('clause_links', {method: 'POST', body: {from_clause_id: item.id, to_clause_id: target.clause_id, relation, source: 'suggested', rationale: 'Eşleme çalışma alanında onaylandı'}});
      toast(`${item.code} ↔ ${target.code}: ${REL_LABEL[relation]}`); load();
    };
    const rows = d.items.map(it => h('tr', {},
      h('td', {class: 'cell-primary'}, h('a', {href: '#', text: it.code, onclick: e => { e.preventDefault(); DETAILS.clauses(it.id); }}), h('span', {class: 'cell-sub', text: it.title})),
      h('td', {}, it.links.length ? h('div', {class: 'chips'}, it.links.map(l => h('span', {class: 'chip', title: l.title}, relPill(l.relation), ' ', l.code))) : h('span', {class: 'muted small', text: '—'})),
      h('td', {}, it.suggestions.length ? h('ul', {class: 'mini'}, it.suggestions.map(sg => h('li', {},
        h('strong', {text: sg.code}), h('span', {class: 'cell-sub', text: sg.title}),
        h('div', {class: 'chips'}, pill(Math.round(sg.score * 100) + '%', sg.score > 0.35 ? 'good' : 'neutral'),
          can ? ['equivalent', 'intersects', 'related'].map(rel => btn(REL_LABEL[rel], () => save(it, sg, rel), 'ghost small')) : null)))) : h('span', {class: 'muted small', text: 'Öneri yok'}))));
    host.replaceChildren(
      h('div', {class: 'tablewrap'}, h('table', {class: 'crosswalk'}, h('thead', {}, h('tr', {}, [`${stdName(d.source)} maddesi`, `Mevcut ilişkiler (${stdName(d.target)})`, 'Öneriler'].map(t => h('th', {text: t})))),
        h('tbody', {}, rows))),
      h('div', {class: 'pager'}, h('span', {class: 'muted small', text: `${d.total ? offset + 1 : 0}–${Math.min(offset + d.limit, d.total)} / ${d.total} madde`}),
        btn('‹ Önceki', () => { offset = Math.max(0, offset - d.limit); load(); }, 'secondary', {disabled: offset === 0}),
        btn('Sonraki ›', () => { offset += d.limit; load(); }, 'secondary', {disabled: offset + d.limit >= d.total})));
  };
  const restart = () => { offset = 0; load().catch(e => toast(e.message, false)); };
  src.addEventListener('change', restart); dst.addEventListener('change', restart); unlinked.addEventListener('change', restart); q.addEventListener('input', debounce(restart, 300));
  content(h('div', {class: 'panel'}, h('div', {class: 'filters'}, h('label', {}, 'Kaynak ', src), h('label', {}, 'Hedef ', dst), q, h('label', {}, unlinked, ' Yalnızca ilişkisi olmayanlar')), host));
  await load();
};

// ------------------------------------------------------------------ bulgu etkisi
function impactSection(imp) {
  if (!imp || !imp.groups.length) return null;
  const others = imp.groups.reduce((n, g) => n + g.clauses.filter(c => c.level !== 'direct').length, 0);
  return section(`Etkilenen standart maddeleri (${imp.standards} standart)`, h('div', {},
    others ? h('p', {class: 'muted small', text: `Bu bulgu ${imp.counts.certain} maddeyi kesin, ${imp.counts.possible} maddeyi olası olarak etkiler (madde ilişkileri ve ortak kontroller üzerinden).`}) : null,
    ...imp.groups.map(g => h('div', {}, h('div', {class: 'choice-group', text: g.standard}), h('ul', {class: 'mini'}, g.clauses.map(c => h('li', {class: 'link', onclick: () => DETAILS.clauses(c.id)},
      h('strong', {text: `${c.code} · ${c.title}`}), h('div', {class: 'chips'}, impactPill(c.level), h('span', {class: 'muted small', text: c.reasons.join(' · ')})))))))));
}

// ------------------------------------------------------------------ entegre test planı
function integratedPanel(plan, audit, {testable, reload}) {
  const s = plan.summary;
  const head = statStrip([['Kapsam maddesi', fmt.num(s.scope_clauses, 0)], ['Standart', fmt.num(s.standards, 0)], ['Test edilecek kontrol', fmt.num(s.tests, 0)],
    ['Kontrolsüz soru grubu', fmt.num(s.groups, 0), s.groups ? 'warn' : ''], ['Tekrar sorulmayan madde', fmt.num(s.saved, 0), s.saved ? 'good' : '']]);
  const tests = plan.tests.map(t => {
    const k = t.control;
    return h('div', {class: 'test-card'},
      h('div', {class: 'test-head'}, h('a', {href: '#/r/controls/' + k.id, class: 'cell-primary', text: `${k.code} · ${k.name}`}),
        h('div', {class: 'chips'}, resultPill(t.status || 'untested'), t.standards.length > 1 ? pill(`${t.standards.length} standart tek testte`, 'purple') : null,
          t.evidence ? pill(`${t.evidence} güncel kanıt`, 'good') : pill('Kanıt yok', 'warn'))),
      k.method || k.expected_result ? h('div', {class: 'muted small', text: [k.method ? 'Test: ' + k.method : null, k.expected_result ? 'Beklenen: ' + k.expected_result : null].filter(Boolean).join(' · ')}) : null,
      h('div', {class: 'test-clauses'}, t.standards.map(st => h('div', {class: 'std-line'}, h('span', {class: 'std-label', text: st.standard}),
        st.clauses.map(c => h('a', {class: 'chip', href: '#', title: c.title, text: c.code, onclick: e => { e.preventDefault(); DETAILS.clauses(c.id); }}))))),
      t.extra.length ? h('div', {class: 'muted small', text: 'Kapsam dışında da güvence verir: ' + t.extra.map(x => `${x.standard} ${x.code}`).join(', ')}) : null,
      h('div', {class: 'toolbar no-print', dataset: {control: k.id}},
        testable && k.active ? btn('Test et', async () => { const ctx = await api(`controls/${k.id}/context`); if (ctx.automation) await runAutomation(ctx, reload, audit.id); else recordResult(ctx, {auditId: audit.id, done: reload}); }, 'ghost small') : null,
        typeof requestEvidence === 'function' && canWrite('evidence_requests') && !['completed', 'closed', 'cancelled'].includes(audit.status) ? btn('Kanıt iste', () => requestEvidence(audit, [k], reload), 'ghost small') : null));
  });
  const groups = plan.groups.map(g => h('div', {class: 'test-card warn'},
    h('div', {class: 'test-head'}, h('strong', {text: g.clauses.length > 1 ? `Ortak soru grubu (${g.clauses.length} madde, ${g.standards} standart)` : 'Kontrolü olmayan madde'})),
    h('div', {class: 'chips'}, g.clauses.map(c => h('a', {class: 'chip', href: '#', title: c.title, text: `${c.standard} ${c.code}`, onclick: e => { e.preventDefault(); DETAILS.clauses(c.id); }}))),
    g.suggested_controls.length ? h('div', {class: 'muted small', text: 'İlişkili maddeyi karşılayan kontrol: ' + g.suggested_controls.map(k => k.code).join(', ') + ' — bu kontrolü gruba eşlemek tek testte güvence sağlar.'}) : null,
    canWrite('controls') ? h('div', {class: 'toolbar no-print'}, btn(g.clauses.length > 1 ? 'Ortak kontrol oluştur' : 'Kontrol oluştur', () => commonControl(g, reload), 'ghost small'),
      g.suggested_controls.length ? btn(`${g.suggested_controls[0].code} kontrolüne ekle`, async () => {
        await api('controls/common', {method: 'POST', body: {control_id: g.suggested_controls[0].id, clause_ids: g.clauses.map(c => c.id)}}); toast('Maddeler kontrole eşlendi'); reload(); }, 'ghost small') : null) : null));
  return h('div', {},
    h('div', {class: 'notice', text: 'Entegre denetim: her kontrol bir kez test edilir ve bir kez kanıt istenir; sonuç, kontrolün eşlendiği tüm standartların maddelerine sayılır. Kontrolü olmayan ilişkili maddeler tek soru grubunda toplanır.'}),
    head, tests.length ? h('div', {class: 'test-list'}, tests) : empty('Kapsamda kontrol yok', 'Kapsam maddelerini kontrollerle eşleyin.'),
    groups.length ? h('div', {}, h('h3', {class: 'group-title', text: `Kontrolü olmayan maddeler (${plan.groups.reduce((n, g) => n + g.clauses.length, 0)})`}), h('div', {class: 'test-list'}, groups)) : null);
}
async function commonControl(group, done) {
  const name = h('input', {id: 'ccName', value: group.clauses.length === 1 ? group.clauses[0].title.slice(0, 120) : ''});
  const method = h('select', {id: 'ccMethod'}, META.field('controls', 'method_type').options.map(o => h('option', {value: o.value, text: o.label, selected: o.value === 'inspection'})));
  Modal.open('Ortak kontrol oluştur', h('div', {},
    h('p', {class: 'intro', text: 'Yeni kontrol aşağıdaki maddelerin hepsine eşlenir; bir kez test edilir ve kanıtı hepsine sayılır.'}),
    h('div', {class: 'chips'}, group.clauses.map(c => h('span', {class: 'chip', title: c.title, text: `${c.standard} ${c.code}`}))),
    h('label', {class: 'field', for: 'ccName'}, 'Kontrol adı *', h('div', {class: 'control'}, name)),
    h('label', {class: 'field', for: 'ccMethod'}, 'Test yöntemi', h('div', {class: 'control'}, method))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Oluştur', async () => {
      if (!name.value.trim()) { name.focus(); throw new Error('Kontrol adı gerekli'); }
      const r = await api('controls/common', {method: 'POST', body: {name: name.value.trim(), method_type: method.value, clause_ids: group.clauses.map(c => c.id)}});
      invalidate('controls'); Modal.close(); toast(`${r.code} oluşturuldu ve ${r.added} maddeye eşlendi`); done();
    })]);
}

DETAILS.standards = id => Router.go('standard/' + id);

// ------------------------------------------------------------------ denetim çalışma alanı (sekmeli)
/** Sekmeler: diğer özellikler AUDIT_TABS dizisine ekler. render(a, ctx) → düğüm veya Promise. */
const AUDIT_TABS = [];
function auditSummary(a) {
  const p = a.progress;
  return h('div', {},
    a.status === 'planned' ? h('div', {class: 'notice', text: 'Denetim planlandı. Başlatınca kontrolleri test edebilirsiniz; başlarken her standart için en az bir kapsam maddesi gerekir.'}) : null,
    ['completed', 'closed'].includes(a.status) && a.plan_captured_at ? h('div', {class: 'notice', text: `Plan ${fmt.datetime(a.plan_captured_at)} tarihinde donduruldu. Kontrol eşlemelerindeki sonraki değişiklikler bu denetimi etkilemez.`}) : null,
    h('div', {class: 'cards'},
      metric('Durum', META.option('audits', 'status', a.status), a.actual_start ? 'Başladı ' + fmt.date(a.actual_start) : 'Başlamadı', ['completed', 'closed', 'cancelled'].includes(a.status) ? '' : 'warn'),
      metric('Planlanan kontrol', fmt.num(p.planned, 0), `${a.clauses.length} madde · ${a.standards.length} standart`),
      metric('Tamamlanma', fmt.pct(p.completion_pct), `${p.completed} test sonuçlandı · ${a.counts.untested} bekliyor`, p.completion_pct === 100 ? 'good' : 'warn'),
      metric('Başarı oranı', fmt.pct(p.pass_pct), `${a.counts.pass} başarılı · ${a.counts.fail} başarısız`, p.pass_pct === null ? '' : p.pass_pct >= 85 ? 'good' : p.pass_pct >= 60 ? 'warn' : 'bad')),
    h('div', {class: 'grid two'},
      h('div', {class: 'panel'}, h('h3', {text: 'Kapsam'}), kv([['Amaç', a.audit_objective], ['Kapsam açıklaması', a.scope],
        ['Standartlar', a.standards.length ? h('div', {class: 'chips'}, a.standards.map(s => h('a', {class: 'chip', href: '#/standard/' + s.id, text: stdName(s)}))) : null],
        ['Maddeler', a.clauses.length ? h('div', {class: 'chips'}, a.clauses.slice(0, 30).map(c => h('a', {class: 'chip', href: '#', title: c.title, text: c.code, onclick: e => { e.preventDefault(); DETAILS.clauses(c.id); }})),
          a.clauses.length > 30 ? h('span', {class: 'muted small', text: ` +${a.clauses.length - 30} (Test planı sekmesinde)`}) : null) : null],
        ['Süreçler', (a.processes || []).length ? h('div', {class: 'chips'}, a.processes.map(p => h('a', {class: 'chip', href: '#/r/processes/' + p.id, text: p.name}))) : null],
        ['Baş denetçi', a.lead_auditor], ['Denetçiler', a.auditors], ['Denetlenenler', a.auditees]])),
      h('div', {class: 'panel'}, h('h3', {text: 'Sonuç dağılımı'}), donut(['pass', 'fail', 'inconclusive', 'not_applicable', 'untested'].map((k, i) => ({label: RESULT_LABEL[k], value: a.counts[k], color: [1, 3, 2, 5, 5][i]}))),
        a.conclusion ? section('Denetim sonucu', kv([['Genel görüş', display('audits', 'opinion', a.opinion)], ['Sonuç', a.conclusion]])) : null)));
}
function findingItems(items) {
  return items.length ? h('ul', {class: 'mini'}, items.map(f => h('li', {class: 'link', onclick: () => openRecord('findings', f.id)},
    h('strong', {text: f.code + ' · ' + f.title}), h('span', {class: 'cell-sub', text: [f.control_code, f.owner, f.due_date ? 'hedef ' + fmt.date(f.due_date) : null].filter(Boolean).join(' · ')}),
    h('div', {class: 'chips'}, display('findings', 'severity', f.severity), display('findings', 'status', f.status),
      f.response_status ? display('findings', 'response_status', f.response_status) : null)))) : h('div', {class: 'muted small', text: 'Yok'});
}
AUDIT_TABS.push(
  {key: 'summary', label: 'Özet', render: a => auditSummary(a)},
  {key: 'plan', label: 'Test planı', count: a => a.progress.planned, render: async (a, ctx) => {
    const [plan, hist] = await Promise.all([api(`audits/${a.id}/integrated`), maybe(api(`audits/${a.id}/history`))]);
    const node = integratedPanel(plan, a, ctx);
    const extra = a.controls.filter(c => !c.planned);
    if (extra.length) node.append(h('h3', {class: 'group-title', text: `Plan dışı test edilen kontroller (${extra.length})`}), h('ul', {class: 'mini'}, extra.map(c => h('li', {class: 'link', onclick: () => c.execution_id && showExecution(c.execution_id)},
      h('strong', {text: `${c.code} · ${c.name}`}), h('div', {class: 'chips'}, resultPill(c.result))))));
    if (hist) node.querySelectorAll('[data-control]').forEach(el => {
      const items = hist.controls[el.dataset.control] || []; if (!items.length) return;
      el.append(btn(`Geçmiş (${items.length})`, () => Modal.open('Önceki sonuçlar: ' + items[0].control_code, h('div', {}, h('p', {class: 'intro', text: items[0].control_name}),
        resultTable(items.map(r => ({...r, clause_codes: r.clause_codes || []})), {showAudit: true})), [], true), 'ghost small'));
    });
    return node;
  }},
  {key: 'findings', label: 'Bulgular', count: a => a.findings.length, render: a => h('div', {class: 'grid two'},
    h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: `Bu denetimin bulguları (${a.findings.length})`}),
      canWrite('findings') && !['closed', 'cancelled'].includes(a.status) ? btn('+ Bulgu', () => createRecord('findings', {audit_id: a.id, source: 'audit', company_id: a.company_id || null}), 'ghost small') : null), findingItems(a.findings)),
    h('div', {class: 'panel'}, h('h3', {text: `Kapsamdaki diğer açık bulgular (${a.other_open_findings.length})`}), findingItems(a.other_open_findings)))},
  {key: 'evidence', label: 'Kanıtlar', count: a => a.evidence.length, render: a => h('div', {class: 'panel'}, h('h3', {text: `Bu denetime bağlı kanıtlar (${a.evidence.length})`}),
    a.evidence.length ? h('ul', {class: 'mini'}, a.evidence.map(e => h('li', {class: 'link', onclick: () => Router.go('r/evidence/' + e.id)},
      h('strong', {text: e.code + ' · ' + e.title}), h('span', {class: 'cell-sub', text: [e.current_version ? 'Sürüm ' + e.current_version : null, e.expires_at ? 'geçerlilik ' + fmt.date(e.expires_at) : null].filter(Boolean).join(' · ')}),
      h('div', {class: 'chips'}, display('evidence', 'status', e.status), display('evidence', 'confidentiality', e.confidentiality))))) : h('div', {class: 'muted small', text: 'Bu denetime bağlı kanıt yok'}))},
  {key: 'history', label: 'Geçmiş', render: a => auditHistoryPanel(a)});

PAGES.audit = async function auditWorkspace(parts, params) {
  const id = Number(parts[1]);
  await Promise.all([list('standards'), list('suppliers')]);
  const a = await api(`audits/${id}/context`);
  const can = META.def('audits').can_write; const closed = ['completed', 'closed', 'cancelled'].includes(a.status);
  const reload = () => { invalidate('audits'); render(); };
  const patch = body => api(`audits/${id}`, {method: 'PATCH', body}).then(() => { toast('Denetim güncellendi'); reload(); });
  const finish = () => {
    const end = h('input', {type: 'date', id: 'auEnd', value: today(), max: today()}); const opinion = h('select', {id: 'auOpinion'}, META.field('audits', 'opinion').options.map(o => h('option', {value: o.value, text: o.label})));
    const concl = h('textarea', {id: 'auConcl', value: a.conclusion || ''});
    const warnings = [a.counts.untested ? `${a.counts.untested} planlı kontrol test edilmedi.` : null, ...(a.blockers || [])].filter(Boolean);
    Modal.open('Denetimi tamamla: ' + a.code, h('div', {},
      warnings.length ? h('div', {class: 'notice warn'}, h('ul', {class: 'plain'}, warnings.map(w => h('li', {text: w})))) : null,
      h('p', {class: 'intro', text: 'Tamamlanınca kapsam ve planlanan kontrol listesi dondurulur; denetim yeniden açılamaz, yeni test eklenemez.'}),
      h('label', {class: 'field', for: 'auEnd'}, 'Gerçekleşen bitiş', h('div', {class: 'control'}, end)),
      h('label', {class: 'field', for: 'auOpinion'}, 'Genel görüş', h('div', {class: 'control'}, opinion)),
      h('label', {class: 'field', for: 'auConcl'}, h('span', {}, 'Denetim sonucu', h('span', {class: 'req', text: ' *'})), h('div', {class: 'control'}, concl))), [
      btn('Vazgeç', () => Modal.close(), 'secondary'),
      btn('Tamamla', async () => { if (!concl.value.trim()) { concl.focus(); throw new Error('Denetim sonucu gerekli'); }
        await patch({status: 'completed', actual_end: end.value, opinion: opinion.value, conclusion: concl.value.trim()}); Modal.close(); })]);
  };
  setPage(a.code + ' · ' + a.name, [META.option('audits', 'kind', a.kind), a.supplier_id ? titleOf(refRecord('suppliers', a.supplier_id)) : null,
    `${fmt.date(a.planned_start)} – ${fmt.date(a.planned_end)}`].filter(Boolean).join(' · '), [
    PAGES['audit-report'] ? btn('Rapor', () => Router.go('audit-report/' + id), 'secondary') : null,
    can && !closed ? btn('Düzenle', () => auditForm(a), 'secondary') : null,
    can && a.status === 'planned' ? btn('Denetimi başlat', () => patch({status: 'in_progress', actual_start: today()})) : null,
    can && a.status === 'in_progress' ? btn('Tamamla', finish) : null,
    can && a.status === 'completed' ? btn('Kapat', () => patch({status: 'closed'}), 'secondary') : null,
    can && a.status === 'planned' ? btn('İptal et', async () => { if (await confirmDialog('Denetimi iptal et', 'İptal edilen denetim yeniden açılamaz.', 'İptal et', 'danger')) await patch({status: 'cancelled'}); }, 'secondary') : null],
    [['Denetimler', 'r/audits']]);
  const ctx = {testable: can && canExecute() && !closed && a.status !== 'planned', reload};
  const items = AUDIT_TABS.filter(t => !t.visible || t.visible(a)).map(t => ({key: t.key, label: t.label, count: t.count ? t.count(a) : undefined,
    render: () => { const r = t.render(a, ctx); return r instanceof Promise ? r.catch(e => h('div', {class: 'notice bad', text: e.message})) : r; }}));
  const initial = items.some(t => t.key === params.get('tab')) ? params.get('tab') : 'summary';
  content(tabs(items, initial, key => history.replaceState(null, '', `#/audit/${id}` + (key === 'summary' ? '' : '?tab=' + key))));
};

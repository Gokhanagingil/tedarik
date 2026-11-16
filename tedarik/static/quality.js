'use strict';
/* Veri kalitesi (K-032): pano (skor kartı, eğilim, başarısız kurallar, anomaliler), kural ekranı (SQL, sonuç girişi, bulgu ve
   DÖF), kural ekleme penceresi, tablo sayfasında kalite bölümü (profil, öneriler) ve kolon panelinde profil. Kurallar verinin
   yanında çalışır; platforma yalnızca sayılar gelir. lineage.js (tablo seçici), datagov.js ve app.js yardımcılarını kullanır. */

const DQ = {
  tone: {pass: 'good', fail: 'bad', error: 'warn'},
  dims: ['completeness', 'validity', 'uniqueness', 'consistency', 'timeliness'],
  needsColumn: new Set(['not_null', 'unique', 'range', 'pattern', 'allowed_values', 'reference', 'freshness', 'format']),
  formats: [['tckn', 'T.C. kimlik numarası'], ['vkn', 'Vergi kimlik numarası'], ['iban', 'IBAN'], ['email', 'E-posta'], ['phone', 'Telefon (TR)'], ['card', 'Kart numarası (Luhn)'], ['ipv4', 'IPv4 adresi']],
};
const dqPill = r => r.last_result ? pill(META.option('dq_rules', 'last_result', r.last_result) + (r.last_pass_rate !== null && r.last_pass_rate !== undefined && r.last_result !== 'error' ? ` · %${fmt.num(r.last_pass_rate)}` : ''), DQ.tone[r.last_result]) : pill('Çalışmadı', 'neutral');
const dqDim = d => META.option('dq_rules', 'dimension', d);
function dqParams(r) {
  const p = r.params || {};
  switch (r.rule_type) {
    case 'range': return `${p.min ?? '—'} ile ${p.max ?? '—'} arası`;
    case 'pattern': return `Desen: ${p.pattern}`;
    case 'allowed_values': return `İzin verilen: ${(p.values || []).join(', ')}`;
    case 'freshness': return `En yeni kayıt en çok ${p.max_age_hours} saat önce`;
    case 'row_count': return `${p.min_rows ?? '—'} – ${p.max_rows ?? '—'} satır`;
    case 'format': return `Biçim: ${(DQ.formats.find(f => f[0] === p.format) || [, p.format])[1]}`;
    case 'reference': return r.ref ? `Referans: ${dgPath(r.ref.schema, r.ref.table)}.${r.ref.column}` : 'Referans';
    case 'not_null': return p.empty_is_null ? 'Boş metin de boş sayılır' : 'NULL değer olmamalı';
    case 'custom_sql': return 'Özel SQL (checked, failed döndürür)';
    default: return '';
  }
}
function sparkline(values, {width = 220, height = 40} = {}) {
  const pts = values.filter(v => v !== null && v !== undefined);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts, 90), hi = 100; const span = Math.max(hi - lo, 1);
  const step = width / (pts.length - 1);
  const coords = pts.map((v, i) => `${(i * step).toFixed(1)},${(height - 4 - (v - lo) / span * (height - 8)).toFixed(1)}`).join(' ');
  return s('svg', {class: 'dq-spark', viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-label': `Geçme oranı eğilimi: son %${fmt.num(pts[pts.length - 1])}`},
    s('polyline', {points: coords, class: 'dq-line'}), s('circle', {cx: ((pts.length - 1) * step).toFixed(1), cy: (height - 4 - (pts[pts.length - 1] - lo) / span * (height - 8)).toFixed(1), r: 3, class: 'dq-dot'}));
}

// ------------------------------------------------------------------ kural ekleme
async function ruleDialog({table, column, preset} = {}) {
  const pick = tablePicker('dqTable', 'Tablo ara (ör. KNA1, fct_satis)', table);
  if (column) setTimeout(() => { pick.colSel.value = String(column); }, 400);
  const kinds = ['not_null', 'unique', 'range', 'pattern', 'allowed_values', 'format', 'reference', 'freshness', 'row_count'].concat(META.can('manage') ? ['custom_sql'] : []);
  const kind = h('select', {id: 'dqKind'}, kinds.map(k => h('option', {value: k, text: META.option('dq_rules', 'rule_type', k)})));
  const box = h('div', {class: 'dq-params'});
  let ref = null; const f = {};
  const input = (key, label, attrs = {}) => { f[key] = h('input', {id: 'dq_' + key, ...attrs}); return h('label', {class: 'field', for: 'dq_' + key}, h('span', {text: label}), h('div', {class: 'control'}, f[key])); };
  const draw = () => {
    const k = kind.value; for (const key of Object.keys(f)) delete f[key]; ref = null;
    const parts = {
      not_null: () => [h('label', {class: 'toggle', for: 'dq_empty'}, (f.empty = h('input', {type: 'checkbox', id: 'dq_empty'})), h('span', {text: 'Boş metni ("") de boş say'}))],
      range: () => [h('div', {class: 'formgrid'}, input('min', 'En küçük', {type: 'number', step: 'any'}), input('max', 'En büyük', {type: 'number', step: 'any'}))],
      pattern: () => [input('pattern', 'Düzenli ifade (değerin tamamı eşleşmeli)', {type: 'text', placeholder: 'Ör. [0-9]{10} veya TR[0-9]{24}'})],
      allowed_values: () => [h('label', {class: 'field', for: 'dq_values'}, h('span', {text: 'İzin verilen değerler (her satıra bir değer)'}), h('div', {class: 'control'}, (f.values = h('textarea', {id: 'dq_values'}))))],
      format: () => [h('label', {class: 'field', for: 'dq_format'}, h('span', {text: 'Biçim'}), h('div', {class: 'control'}, (f.format = h('select', {id: 'dq_format'}, DQ.formats.map(([v, t]) => h('option', {value: v, text: t}))))))],
      reference: () => { ref = tablePicker('dqRef', 'Referans (ana) tablo ara', null); return [h('div', {class: 'field'}, h('span', {text: 'Referans tablo ve kolon (aynı veri kaynağında)'}), ref.node)]; },
      freshness: () => [input('age', 'En yeni kayıt en çok kaç saat önce olmalı', {type: 'number', min: 1, value: 24})],
      row_count: () => [h('div', {class: 'formgrid'}, input('min_rows', 'En az satır', {type: 'number', min: 0}), input('max_rows', 'En çok satır', {type: 'number', min: 0}))],
      custom_sql: () => [h('label', {class: 'field', for: 'dq_sql'}, h('span', {text: 'SQL (checked ve failed kolonlarını döndürmeli)'}), h('div', {class: 'control'}, (f.sql = h('textarea', {id: 'dq_sql', placeholder: 'SELECT COUNT(*) AS checked, SUM(CASE WHEN ... THEN 1 ELSE 0 END) AS failed FROM ...'})))),
        h('p', {class: 'small muted', text: 'Özel SQL, toplayıcının yerel ayarında "allow_custom_sql": true olmadıkça çalışmaz; kurum kendi ağında hangi sorgunun çalışacağına kendisi karar verir.'})],
    };
    box.replaceChildren(...(parts[k] ? parts[k]() : []), h('p', {class: 'small muted', text: DQ.needsColumn.has(k) ? 'Yukarıdan kolon seçin.' : 'Kural tablonun tamamına uygulanır.'}));
  };
  kind.addEventListener('change', draw);
  if (preset) kind.value = preset; draw();
  const threshold = h('input', {type: 'number', id: 'dqThr', min: 0, max: 100, step: 'any', value: 100});
  const severity = h('select', {id: 'dqSev'}, ['low', 'medium', 'high', 'critical'].map(v => h('option', {value: v, text: META.option('dq_rules', 'severity', v), selected: v === 'medium'})));
  const owner = h('input', {type: 'text', id: 'dqOwner', list: 'peopleList', placeholder: 'Boşsa tablonun veri yöneticisi'});
  const finding = h('input', {type: 'checkbox', id: 'dqFinding', checked: true});
  const controls = hasModule('grc') ? (await list('controls').catch(() => [])).filter(k => k.active) : [];
  const control = h('select', {id: 'dqControl'}, h('option', {value: '', text: '— Bağlı değil —'}), controls.map(k => h('option', {value: k.id, text: `${k.code} ${k.name}`})));
  await ensurePeople();
  const error = h('div', {class: 'notice bad hidden', role: 'alert'});
  const params = () => {
    const k = kind.value; const num = el => el && el.value !== '' ? Number(el.value) : null;
    return {not_null: () => ({empty_is_null: !!(f.empty && f.empty.checked)}), range: () => ({min: num(f.min), max: num(f.max)}), pattern: () => ({pattern: f.pattern.value.trim()}),
      allowed_values: () => ({values: f.values.value.split(/\n|,/).map(x => x.trim()).filter(Boolean)}), format: () => ({format: f.format.value}),
      freshness: () => ({max_age_hours: num(f.age)}), row_count: () => ({min_rows: num(f.min_rows), max_rows: num(f.max_rows)}), custom_sql: () => ({sql: f.sql.value}),
      reference: () => ({}), unique: () => ({})}[k]();
  };
  const save = async () => {
    try {
      if (!pick.state.table) throw new Error('Tabloyu listeden seçin');
      const body = {table_id: pick.state.table.id, column_id: Number(pick.colSel.value) || null, rule_type: kind.value, params_json: JSON.stringify(params()),
        threshold_pct: Number(threshold.value || 100), severity: severity.value, owner: owner.value.trim() || null, auto_finding: finding.checked ? 1 : 0,
        control_id: Number(control.value) || null};
      if (kind.value === 'reference') { if (!ref || !Number(ref.colSel.value)) throw new Error('Referans tablo ve kolonu seçin'); body.ref_column_id = Number(ref.colSel.value); }
      const r = await api('dq_rules', {method: 'POST', body});
      Modal.close(); toast('Kural eklendi'); invalidate('dq_rules'); Router.go('dqrule/' + r.id);
    } catch (e) { error.textContent = e.message; error.classList.remove('hidden'); }
  };
  Modal.open('Veri kalitesi kuralı ekle', h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'Kural, toplayıcı çalıştıkça kurum ağında çalışır ve platforma yalnızca kontrol edilen ve hatalı satır sayısı gelir. Toplayıcı yoksa kuralın SQL\'i gösterilir, sonucu elle girersiniz. Eşiğin altında kalan kural başarısız olur; bulgu ve düzeltici faaliyet açılır.'}),
    error, h('div', {class: 'field'}, h('span', {text: 'Tablo ve kolon'}), pick.node),
    h('label', {class: 'field', for: 'dqKind'}, h('span', {text: 'Kural türü'}), h('div', {class: 'control'}, kind)), box,
    h('div', {class: 'formgrid'},
      h('label', {class: 'field', for: 'dqThr'}, h('span', {text: 'Eşik: en düşük geçme oranı (%)'}), h('div', {class: 'control'}, threshold)),
      h('label', {class: 'field', for: 'dqSev'}, h('span', {text: 'Önem'}), h('div', {class: 'control'}, severity)),
      h('label', {class: 'field', for: 'dqOwner'}, h('span', {text: 'Kural sahibi'}), h('div', {class: 'control'}, owner)),
      controls.length ? h('label', {class: 'field', for: 'dqControl'}, h('span', {text: 'Bağlı GRC kontrolü (isteğe bağlı)'}), h('div', {class: 'control'}, control)) : null),
    h('label', {class: 'toggle', for: 'dqFinding'}, finding, h('span', {text: 'Başarısızlıkta bulgu ve düzeltici faaliyet aç'}))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Ekle', save)], true);
}
async function addSuggestion(t, sgt, reload) {
  const body = {table_id: t.id, column_id: sgt.column_id, rule_type: sgt.rule_type, params_json: JSON.stringify(sgt.params || {})};
  if (sgt.ref_column_id) body.ref_column_id = sgt.ref_column_id;
  await api('dq_rules', {method: 'POST', body}); toast('Kural eklendi'); reload();
}

// ------------------------------------------------------------------ sonuç girişi ve anomali
function resultDialog(r, reload) {
  const measured = ['freshness', 'row_count'].includes(r.rule_type);
  const checked = h('input', {type: 'number', id: 'dqChecked', min: 0}); const failed = h('input', {type: 'number', id: 'dqFailed', min: 0});
  const value = r.rule_type === 'freshness' ? h('input', {type: 'datetime-local', id: 'dqMeasured'}) : h('input', {type: 'number', id: 'dqMeasured', min: 0});
  Modal.open('Sonuç gir: ' + r.name, h('div', {},
    h('p', {class: 'intro', text: measured ? (r.rule_type === 'freshness' ? 'Sorgunun döndürdüğü en yeni kayıt zamanını girin.' : 'Sorgunun döndürdüğü satır sayısını girin.') :
      'Sorguyu kaynakta çalıştırın; döndürdüğü kontrol edilen (checked) ve hatalı (failed) satır sayısını girin. Değerleri değil yalnızca sayıları yazın.'}),
    measured ? h('label', {class: 'field', for: 'dqMeasured'}, h('span', {text: r.rule_type === 'freshness' ? 'En yeni kayıt zamanı' : 'Satır sayısı'}), h('div', {class: 'control'}, value)) :
      h('div', {class: 'formgrid'}, h('label', {class: 'field', for: 'dqChecked'}, h('span', {text: 'Kontrol edilen satır'}), h('div', {class: 'control'}, checked)),
        h('label', {class: 'field', for: 'dqFailed'}, h('span', {text: 'Hatalı satır'}), h('div', {class: 'control'}, failed)))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => {
    const body = measured ? {measured: r.rule_type === 'freshness' ? (value.value ? new Date(value.value).toISOString() : null) : Number(value.value)} : {checked: Number(checked.value), failed: Number(failed.value)};
    const res = await api(`dq_rules/${r.id}/results`, {method: 'POST', body});
    Modal.close(); toast(`${META.option('dq_rules', 'last_result', res.result)}: ${res.message}${res.action_id ? ' · bulgu ve DÖF açıldı' : res.finding_id ? ' · açık bulgu güncellendi' : ''}`, res.result === 'pass'); reload();
  })]);
}
function acknowledgeDialog(a, reload) {
  const note = h('textarea', {id: 'dqNote', placeholder: 'Ör. yıl sonu arşivleme işi eski kayıtları taşıdı; beklenen değişiklik.'});
  Modal.open('Anomaliyi değerlendir', h('div', {},
    h('p', {class: 'intro', text: `${dgPath(a.schema_name, a.table_name)}: satır sayısı ${fmt.num(a.measured)}, beklenen yaklaşık ${fmt.num(a.expected)} (sapma %${fmt.num(a.deviation_pct)}).`}),
    h('label', {class: 'field', for: 'dqNote'}, h('span', {text: 'Değerlendirme'}), h('div', {class: 'control'}, note))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => { await api(`dq_anomalies/${a.id}/acknowledge`, {method: 'POST', body: {note: note.value}}); Modal.close(); toast('Kaydedildi'); reload(); })]);
}

// ------------------------------------------------------------------ pano
const ruleItem = r => h('li', {class: 'link', onclick: () => Router.go('dqrule/' + r.id)},
  h('div', {class: 'chips'}, dqPill(r), h('strong', {text: r.name})),
  h('span', {class: 'cell-sub', text: [r.code, `${r.source_name} / ${dgPath(r.schema_name, r.table_name)}${r.column_name ? '.' + r.column_name : ''}`, r.last_message, r.last_run_at ? agoText(r.last_run_at) : null].filter(Boolean).join(' · ')}));
PAGES.quality = async function qualityPage() {
  const d = await api('datagov/quality'); const reload = () => render();
  setPage('Veri Kalitesi', 'Kurallar verinin yanında çalışır, platforma yalnızca sayılar gelir. Başarısız kural bulgu ve düzeltici faaliyet açar; GRC kontrolüne bağlı kural kontrol sonucu yazar.', [
    d.can_edit ? btn('+ Kural', () => ruleDialog()) : null, btn('Toplayıcılar', () => Router.go('collectors'), 'secondary')], [['Veri Yönetişimi', 'datagov']]);
  const sc = d.scorecard; const active = d.counts.active || 0;
  if (!active) {
    const step = (n, title, text, action) => h('div', {class: 'dg-step'}, h('span', {class: 'dg-num', text: n}), h('div', {}, h('strong', {text: title}), h('p', {class: 'small muted', text}), action));
    content(h('div', {class: 'panel'}, h('h3', {text: 'Veri kalitesini üç adımda izlemeye başlayın'}), h('div', {class: 'dg-steps'},
      step(1, 'Kural tanımlayın', 'Kritik tablonun sayfasındaki "Veri kalitesi" bölümünde profilden önerilen kuralları tek tıkla ekleyin veya kodsuz şablondan kural yazın.', d.can_edit ? btn('+ Kural', () => ruleDialog(), 'secondary small') : null),
      step(2, 'Çalıştırın', 'Toplayıcı her çalışmada kuralları kurum ağında çalıştırır; toplayıcı yoksa kuralın SQL\'ini kaynakta çalıştırıp sonucu girersiniz.', btn('Toplayıcılar', () => Router.go('collectors'), 'secondary small')),
      step(3, 'Sonucu yönetin', 'Eşiğin altında kalan kural bulgu ve düzeltici faaliyet açar; skor kartı boyut, kaynak ve veri alanı bazında izlenir.', null))));
    return;
  }
  const gauges = h('div', {class: 'gauges'}, gauge(sc.overall, 'Genel kalite skoru', {suffix: '', good: 95, mid: 85, sub: `${sc.rules} kuralın son sonucu`}),
    DQ.dims.filter(k => sc.dimensions[k] !== undefined).map(k => gauge(sc.dimensions[k], dqDim(k), {suffix: '', good: 95, mid: 85})));
  const spark = sparkline(d.trend.map(x => x.pass_rate), {width: 320, height: 56});
  const groupTable = (items, link) => items.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Ad', 'Skor', 'Kural', 'Başarısız'].map(x => h('th', {text: x})))),
    h('tbody', {}, items.map(g => h('tr', {class: link ? 'link' : '', onclick: () => link && link(g)}, h('td', {}, h('strong', {text: g.name})),
      h('td', {}, pill(g.score === null ? '—' : fmt.num(g.score), g.score >= 95 ? 'good' : g.score >= 85 ? 'warn' : 'bad')), h('td', {class: 'num', text: g.rules}),
      h('td', {class: 'num', text: g.failing || '—'})))))) : h('div', {class: 'muted small', text: 'Sonucu olan kural yok.'});
  content(
    h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Skor kartı'}), h('span', {class: 'muted small', text: 'Etkin kuralların son geçme oranlarının önem ağırlıklı ortalaması'})), gauges,
      spark ? h('div', {class: 'dq-trend'}, h('span', {class: 'small muted', text: `Son ${d.trend.length} günde günlük ortalama geçme oranı`}), spark) : null),
    h('div', {class: 'grid four'}, metric('Etkin kural', fmt.num(active), `${d.counts.draft || 0} taslak`), metric('Başarısız / çalışmadı', fmt.num(d.failing.length), 'son sonuca göre', d.failing.length ? 'bad' : 'good'),
      metric('Uzun süredir çalışmayan', fmt.num(d.stale.length), 'toplayıcı veya elle giriş bekliyor', d.stale.length ? 'warn' : ''),
      metric('Açık hacim anomalisi', fmt.num(d.anomalies.length), 'satır sayısında sıra dışı değişim', d.anomalies.length ? 'warn' : '')),
    h('div', {class: 'grid wide-left'},
      panel('Başarısız ve çalışmayan kurallar', d.failing.length ? h('ul', {class: 'mini'}, d.failing.map(ruleItem)) : empty('Başarısız kural yok', 'Tüm etkin kuralların son sonucu eşiğin üstünde.')),
      h('div', {}, panel('Kaynaklara göre', groupTable(sc.by_source, g => Router.go('datasource/' + g.id))), panel('Veri alanlarına göre', groupTable(sc.by_domain)))),
    h('div', {class: 'grid two'},
      panel('Hacim anomalileri', d.anomalies.length ? h('ul', {class: 'mini'}, d.anomalies.map(a => h('li', {},
        h('div', {class: 'chips'}, pill(`%${fmt.num(a.deviation_pct)} sapma`, 'warn'), h('a', {href: '#/catalog/table/' + a.table_id, text: `${a.source_name} / ${dgPath(a.schema_name, a.table_name)}`})),
        h('span', {class: 'cell-sub', text: `${fmt.num(a.measured)} satır; beklenen ~${fmt.num(a.expected)} · ${fmt.datetime(a.detected_at)}`}),
        d.can_edit ? btn('Değerlendir', () => acknowledgeDialog(a, reload), 'ghost small') : null))) : h('div', {class: 'muted small', text: 'Açık anomali yok. İzlenen tablolar (kuralı olan veya onaylı veri seti) için her içe aktarımda satır sayısı karşılaştırılır.'})),
      panel('Son sonuçlar', d.recent.length ? h('ul', {class: 'mini'}, d.recent.map(x => h('li', {class: 'link', onclick: () => Router.go('dqrule/' + x.rule_id)},
        h('div', {class: 'chips'}, pill(META.option('dq_results', 'result', x.result), DQ.tone[x.result]), h('strong', {text: x.name})),
        h('span', {class: 'cell-sub', text: [x.code, x.table_name, x.message, META.option('dq_results', 'source', x.source), fmt.datetime(x.run_at)].filter(Boolean).join(' · ')})))) : h('div', {class: 'muted small', text: '—'}))),
    d.stale.length ? panel('Uzun süredir çalışmayan kurallar', h('ul', {class: 'mini'}, d.stale.map(ruleItem))) : null);
};

// ------------------------------------------------------------------ kural ekranı
DETAILS.dq_rules = id => Router.go('dqrule/' + id);
PAGES.dqrule = async function dqRulePage(parts) {
  const r = await api(`dq_rules/${Number(parts[1])}/context`); const reload = () => render();
  const target = `${dgPath(r.table.schema_name, r.table.name)}${r.column ? '.' + r.column.name : ''}`;
  setPage(r.name, `${r.code} · ${r.source.name} / ${target} · ${META.option('dq_rules', 'rule_type', r.rule_type)}`, [
    r.can_edit && r.status === 'active' ? btn('Sonuç gir', () => resultDialog(r, reload)) : null,
    r.can_edit ? btn('Düzenle', () => recordForm('dq_rules', r, {only: ['name', 'threshold_pct', 'severity', 'owner', 'dimension', 'control_id', 'auto_finding', 'status', 'description'], onsaved: reload}), 'secondary') : null,
    btn('Tabloya git', () => Router.go('catalog/table/' + r.table.id), 'ghost')], [['Veri Kalitesi', 'quality'], [r.table.name, 'catalog/table/' + r.table.id]]);
  const status = kv([['Son sonuç', dqPill(r)], ['Son çalışma', r.last_run_at ? `${fmt.datetime(r.last_run_at)} (${agoText(r.last_run_at)})` : 'Henüz çalışmadı'], r.last_message ? ['Son ileti', r.last_message] : null,
    ['Boyut', dqDim(r.dimension)], ['Eşik', `%${fmt.num(r.threshold_pct)} geçme`], ['Önem', META.option('dq_rules', 'severity', r.severity)], ['Kural sahibi', personText(r.owner)],
    ['Durum', META.option('dq_rules', 'status', r.status)],
    r.control ? ['GRC kontrolü', h('a', {href: '#/r/controls/' + r.control.id, text: `${r.control.code} ${r.control.name}`})] : ['Başarısızlıkta', r.auto_finding ? 'Bulgu ve DÖF açılır' : 'Yalnızca bildirim'],
    r.finding ? ['Bulgu', h('span', {}, h('a', {href: '#/r/findings/' + r.finding.id, text: `${r.finding.code} ${r.finding.title}`}), h('span', {class: 'muted small', text: ` · ${META.option('findings', 'status', r.finding.status)} · ${r.finding.recurrence}. kez`}))] : null,
    r.actions.length ? ['Düzeltici faaliyet', h('span', {class: 'chips'}, r.actions.map(a => h('a', {class: 'chip', href: '#/r/grc_actions/' + a.id, text: `${a.code} · ${META.option('grc_actions', 'status', a.status)}`})))] : null]);
  const definition = kv([['Tablo', h('a', {href: '#/catalog/table/' + r.table.id, text: dgPath(r.table.schema_name, r.table.name)})], r.column ? ['Kolon', `${r.column.name}${r.column.data_type ? ' (' + r.column.data_type + ')' : ''}`] : null,
    ['Kural', META.option('dq_rules', 'rule_type', r.rule_type)], ['Tanım', dqParams(r)], r.description ? ['Açıklama', r.description] : null]);
  const how = h('div', {},
    r.collectors.length ? h('div', {class: 'notice success small'}, h('strong', {text: 'Toplayıcı var: '}), `${r.collectors.map(c => c.code).join(', ')} her çalışmada bu kuralı kurum ağında çalıştırır ve yalnızca sayıları gönderir.`) :
      h('div', {class: 'notice small'}, h('strong', {text: 'Bu kaynakta toplayıcı yok. '}), 'Aşağıdaki sorguyu kaynakta çalıştırıp sonucu "Sonuç gir" ile yazın veya kaynağa toplayıcı kurun.'),
    r.sql ? h('div', {}, codeBlock(r.sql, `SQL (${({postgres: 'PostgreSQL', tsql: 'SQL Server', oracle: 'Oracle', mysql: 'MySQL', hana: 'SAP HANA', snowflake: 'Snowflake', bigquery: 'BigQuery', ansi: 'ANSI SQL'})[r.dialect] || r.dialect})`),
      h('p', {class: 'small muted', text: r.mode === 'python' ? 'Bu kural değerleri yerelde doğrular (biçim veya düzenli ifade): sorgu değerleri getirir, toplayıcı yalnızca geçersiz sayısını gönderir. Elle girişte kontrol ettiğiniz ve geçersiz bulduğunuz sayıları yazın.' :
        r.mode === 'measured' ? 'Sorgu tek bir ölçüm döndürür; değerlendirme platformda yapılır.' : 'Sorgu yalnızca iki sayı döndürür: checked (kontrol edilen) ve failed (kuralı sağlamayan).'})) :
      h('div', {class: 'notice bad small', text: r.mode}));
  const history = r.results.length ? h('div', {}, sparkline(r.results.slice().reverse().map(x => x.pass_rate)), h('ul', {class: 'mini'}, r.results.map(x => h('li', {},
    h('div', {class: 'chips'}, pill(META.option('dq_results', 'result', x.result), DQ.tone[x.result]), h('strong', {text: x.message || ''})),
    h('span', {class: 'cell-sub', text: [fmt.datetime(x.run_at), META.option('dq_results', 'source', x.source), x.created_by].filter(Boolean).join(' · ')}))))) :
    h('div', {class: 'muted small', text: 'Henüz sonuç yok.'});
  content(h('div', {class: 'grid two'}, panel('Durum', status), panel('Tanım', definition)),
    tabs([{key: 'how', label: 'Nasıl çalışır', render: () => how}, {key: 'history', label: 'Sonuç geçmişi', count: r.results.length, render: () => history}], r.results.length ? 'history' : 'how'));
};

// ------------------------------------------------------------------ tablo sayfası ve kolon paneli
TABLE_EXTRAS.push((t, reload) => {
  const host = h('div', {class: 'panel dq-panel'}, h('div', {class: 'muted small', text: 'Veri kalitesi yükleniyor…'}));
  api(`data_tables/${t.id}/quality`).then(q => {
    const sc = q.score;
    const title = h('h3', {}, 'Veri kalitesi ', sc.overall !== null && sc.overall !== undefined ? pill(fmt.num(sc.overall), sc.overall >= 95 ? 'good' : sc.overall >= 85 ? 'warn' : 'bad') : null,
      h('span', {class: 'sub', text: Object.entries(sc.dimensions || {}).map(([k, v]) => `  ${dqDim(k)} ${fmt.num(v)}`).join(' ·')}));
    const rulesList = q.rules.length ? h('ul', {class: 'mini'}, q.rules.map(r => h('li', {class: 'link', onclick: () => Router.go('dqrule/' + r.id)},
      h('div', {class: 'chips'}, dqPill(r), h('strong', {text: r.name})), h('span', {class: 'cell-sub', text: [r.code, dqDim(r.dimension), r.last_message].filter(Boolean).join(' · ')})))) :
      h('div', {class: 'muted small', text: 'Bu tabloda kalite kuralı yok.'});
    const sugg = q.suggestions.length ? section('Önerilen kurallar', h('ul', {class: 'mini'}, q.suggestions.slice(0, 8).map(sg => h('li', {},
      h('div', {class: 'chips'}, h('strong', {text: `${META.option('dq_rules', 'rule_type', sg.rule_type)}${sg.column ? ': ' + sg.column : ''}`}), btn('Ekle', () => addSuggestion(t, sg, reload), 'ghost small')),
      h('span', {class: 'cell-sub', text: sg.reason}))))) : null;
    const profile = q.profiles.length ? section(`Profil (${fmt.num(q.profiles[0].sample_size)} satırlık örnek, ${fmt.datetime(q.profiles[0].profiled_at)})`, h('div', {class: 'tablewrap plain'}, h('table', {},
      h('thead', {}, h('tr', {}, ['Kolon', 'Boş', 'Farklı', 'Uzunluk', 'En küçük – en büyük'].map(x => h('th', {text: x})))),
      h('tbody', {}, q.profiles.map(p => h('tr', {}, h('td', {text: p.column}), h('td', {class: 'num', text: p.sample_size ? `%${fmt.num(100 * (p.null_count || 0) / p.sample_size)}` : '—'}),
        h('td', {class: 'num', text: fmt.num(p.distinct_count)}), h('td', {class: 'num', text: p.min_length !== null ? `${p.min_length}–${p.max_length}` : '—'}),
        h('td', {class: 'small', text: p.min_value !== null && p.min_value !== undefined ? `${p.min_value} – ${p.max_value}` : '—'}))))))) : null;
    const anomalies = q.anomalies.filter(a => a.status === 'open');
    fillEl(host, h('div', {class: 'panel-title'}, title, h('div', {class: 'toolbar'}, q.can_edit ? btn('+ Kural', () => ruleDialog({table: {...t, source_name: t.source.name}}), 'ghost small') : null)),
      anomalies.length ? h('div', {class: 'notice warn small'}, h('strong', {text: 'Hacim anomalisi: '}), `${fmt.num(anomalies[0].measured)} satır, beklenen ~${fmt.num(anomalies[0].expected)} (sapma %${fmt.num(anomalies[0].deviation_pct)}). `,
        q.can_edit ? btn('Değerlendir', () => acknowledgeDialog({...anomalies[0], table_name: t.name, schema_name: t.schema_name}, reload), 'ghost small') : null) : null,
      h('div', {class: 'grid two'}, h('div', {}, rulesList, sugg), h('div', {}, profile || h('div', {class: 'muted small', text: 'Profil yok. Toplayıcı ayarında "Profil satırı" açıkken her çalışmada boş, farklı değer ve uzunluk istatistiği gelir; değer listesi gelmez.'}),
        q.volumes.length > 1 ? h('div', {class: 'small muted'}, `Satır sayısı (son ${q.volumes.length} ölçüm): `, sparkline(q.volumes.slice().reverse().map(v => v.row_count), {width: 180, height: 30})) : null)));
  }).catch(() => host.remove());
  return host;
});
COLUMN_EXTRAS.push(c => {
  const host = h('div');
  api(`data_columns/${c.id}/quality`).then(q => {
    if (!q.profile && !q.rules.length) return;
    const p = q.profile;
    host.replaceChildren(section('Veri kalitesi', h('div', {},
      p ? kv([['Örnek', `${fmt.num(p.sample_size)} satır · ${fmt.datetime(p.profiled_at)}`], ['Boş', `%${fmt.num(100 * (p.null_count || 0) / p.sample_size)}`], ['Farklı değer', fmt.num(p.distinct_count)],
        p.min_length !== null ? ['Uzunluk', `${p.min_length}–${p.max_length}`] : null, p.min_value !== null && p.min_value !== undefined ? ['En küçük – en büyük', `${p.min_value} – ${p.max_value}`] : null]) : null,
      q.rules.length ? h('ul', {class: 'mini plain'}, q.rules.map(r => h('li', {class: 'small'}, dqPill(r), ' ', h('a', {href: '#/dqrule/' + r.id, text: r.name})))) : null)));
  }).catch(() => {});
  return host;
});

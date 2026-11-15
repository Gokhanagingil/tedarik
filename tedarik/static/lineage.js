'use strict';
/* Soy kütüğü ve etki analizi (K-031): Soy Kütüğü sayfası, bağlantı ekleme, Excel/CSV ve dbt içe aktarımı, OpenLineage
   alıcısı kurulumu, akış şeması (satır içi SVG, dış kütüphane yok) ve etki analizi ekranı; tablo sayfasında ve kolon
   panelinde soy kütüğü bölümü. datagov.js, collect.js ve app.js yardımcılarını kullanır; satır içi stil yok (CSP). */

const LIN = {
  kindTone: {direct: 'neutral', transform: 'purple', aggregate: 'warn', indirect: 'neutral', other: 'neutral'},
  stateTone: {COMPLETE: 'good', RUNNING: 'neutral', START: 'neutral', FAIL: 'bad', ABORT: 'warn', OTHER: 'neutral'},
};
const linKind = k => pill(META.option('lineage_edges', 'kind', k), LIN.kindTone[k] || 'neutral');
const linEnd = (table, schema, column, system) => [system, dgPath(schema, table) + (column ? '.' + column : '')].filter(Boolean).join(' / ');

// ------------------------------------------------------------------ tablo seçici (katalog araması)
function tablePicker(id, placeholder, initial) {
  const state = {table: initial || null, columns: []};
  const input = h('input', {type: 'search', id, placeholder, autocomplete: 'off', value: initial ? dgPath(initial.schema_name, initial.name) : ''});
  const results = h('ul', {class: 'mini pick-results'});
  const colSel = h('select', {id: id + 'Col', disabled: !initial}, h('option', {value: '', text: '— Tablo düzeyi (tablonun tamamı) —'}));
  const loadCols = async t => {
    const ctx = await api(`data_tables/${t.id}/context`);
    state.columns = ctx.columns.filter(c => c.status === 'active');
    colSel.replaceChildren(h('option', {value: '', text: '— Tablo düzeyi (tablonun tamamı) —'}), ...state.columns.map(c => h('option', {value: c.id, text: c.business_name ? `${c.name} — ${c.business_name}` : c.name})));
    colSel.disabled = false;
  };
  const choose = async t => { state.table = t; input.value = `${t.source_name ? t.source_name + ' / ' : ''}${dgPath(t.schema_name, t.name)}`; results.replaceChildren(); await loadCols(t); };
  const run = debounce(async () => {
    const q = input.value.trim(); if (q.length < 2) { results.replaceChildren(); return; }
    const r = await api(`datagov/search?kind=tables&q=${encodeURIComponent(q)}`).catch(() => null); const items = r ? r.tables : [];
    results.replaceChildren(...(items.length ? items.slice(0, 12).map(t => h('li', {class: 'link', onclick: () => choose(t)}, h('strong', {text: dgPath(t.schema_name, t.name)}),
      h('span', {class: 'cell-sub', text: [t.source_name, t.business_name].filter(Boolean).join(' · ')}))) : [h('li', {class: 'muted small', text: 'Eşleşen tablo yok'})]));
  }, 220);
  input.addEventListener('input', () => { state.table = null; colSel.disabled = true; run(); });
  if (initial) loadCols(initial);
  return {state, node: h('div', {}, h('div', {class: 'control'}, input), results, h('div', {class: 'control'}, colSel)), colSel};
}

async function edgeDialog({source, target} = {}, onsaved) {
  const jobs = await list('lineage_jobs').catch(() => []);
  const src = tablePicker('lnSrc', 'Kaynak tablo ara (ör. KNA1, fct_satis)', source); const dst = tablePicker('lnDst', 'Hedef tablo ara', target);
  const kind = h('select', {id: 'lnKind'}, ['direct', 'transform', 'aggregate', 'indirect', 'other'].map(k => h('option', {value: k, text: META.option('lineage_edges', 'kind', k)})));
  const transformation = h('textarea', {id: 'lnTr', placeholder: 'Ör. WAERK alanına göre TRY\'ye çevrilir; SUM(NETWR) müşteri bazında'});
  const job = h('select', {id: 'lnJob'}, h('option', {value: '', text: '— Yok —'}), jobs.filter(j => j.status === 'active').map(j => h('option', {value: j.id, text: `${j.code} ${j.name}`})));
  const error = h('div', {class: 'notice bad hidden', role: 'alert'});
  const save = async () => {
    try {
      if (!src.state.table || !dst.state.table) throw new Error('Kaynak ve hedef tabloyu listeden seçin');
      const sc = Number(src.colSel.value) || null, tc = Number(dst.colSel.value) || null;
      if (!!sc !== !!tc) throw new Error('Kolon düzeyinde bağlantıda iki kolonu da seçin; tablo düzeyinde ikisini de boş bırakın');
      await api('lineage_edges', {method: 'POST', body: {source_table_id: src.state.table.id, target_table_id: dst.state.table.id, source_column_id: sc, target_column_id: tc,
        kind: kind.value, transformation: transformation.value.trim() || null, job_id: Number(job.value) || null}});
      Modal.close(); toast('Bağlantı eklendi'); if (onsaved) onsaved();
    } catch (e) { error.textContent = e.message; error.classList.remove('hidden'); }
  };
  Modal.open('Soy kütüğü bağlantısı ekle', h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'Veri kaynak tablodan hedef tabloya akar. Kolon seçmezseniz bağlantı tablo düzeyindedir: hedefin tamamı kaynaktan etkilenmiş sayılır. Kolon düzeyinde bağlantı etki analizini daraltır.'}),
    error,
    h('div', {class: 'grid two'},
      h('div', {class: 'field'}, h('span', {text: 'Kaynak (nereden)'}), src.node),
      h('div', {class: 'field'}, h('span', {text: 'Hedef (nereye)'}), dst.node)),
    h('div', {class: 'formgrid'},
      h('label', {class: 'field', for: 'lnKind'}, h('span', {text: 'Bağlantı türü'}), h('div', {class: 'control'}, kind)),
      h('label', {class: 'field', for: 'lnJob'}, h('span', {text: 'Veri akış işi (ETL)'}), h('div', {class: 'control'}, job))),
    h('label', {class: 'field', for: 'lnTr'}, h('span', {text: 'Dönüşüm açıklaması'}), h('div', {class: 'control'}, transformation))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Ekle', save)], true);
  setTimeout(() => (source ? $('lnDst') : $('lnSrc')).focus(), 60);
}

// ------------------------------------------------------------------ içe aktarım pencereleri
function lineageImportDialog(onsaved) {
  const file = h('input', {type: 'file', id: 'lnFile', accept: '.csv,.txt,.xlsx'});
  const result = h('div');
  const body = async dry => { if (!file.files[0]) throw new Error('Dosya seçin'); return {filename: file.files[0].name, ...(await gzipBase64(file.files[0])), dry_run: dry}; };
  const show = r => h('div', {class: 'notice ' + (r.errors ? 'warn' : 'success')},
    h('strong', {text: `${r.dry_run ? 'Ön izleme: ' : ''}${r.new} yeni, ${r.seen} zaten var${r.errors ? `, ${r.errors} satırda hata` : ''}`}),
    r.error_rows.length ? h('ul', {class: 'mini plain'}, r.error_rows.slice(0, 15).map(e => h('li', {class: 'small', text: `Satır ${e.row}: ${e.message}`}))) : null);
  const preview = async () => {
    const r = await api('datagov/lineage/import', {method: 'POST', body: await body(true)});
    result.replaceChildren(show(r), r.new ? h('div', {class: 'toolbar'}, btn('İçe aktar', async () => {
      const done = await api('datagov/lineage/import', {method: 'POST', body: await body(false)});
      Modal.close(); toast(`${done.new} bağlantı eklendi${done.errors ? `, ${done.errors} satır atlandı` : ''}`); if (onsaved) onsaved();
    })) : null);
  };
  Modal.open('Soy kütüğünü Excel/CSV ile içe aktar', h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'Her satır bir bağlantıdır: Kaynak sistem, Kaynak şema, Kaynak tablo, Kaynak kolon → Hedef sistem, Hedef şema, Hedef tablo, Hedef kolon; isteğe bağlı Tür, Dönüşüm, Veri akış işi ve Not. Sistem, veri kaynağının kodu (VK-…) veya adıdır. Kolonlar boşsa bağlantı tablo düzeyindedir. Tablolar katalogda olmalıdır.'}),
    h('div', {class: 'toolbar'}, btn('Şablon / mevcut bağlantılar (Excel)', () => download('datagov/lineage/export?format=xlsx', 'soy-kutugu.xlsx'), 'secondary small'),
      btn('CSV', () => download('datagov/lineage/export?format=csv', 'soy-kutugu.csv'), 'ghost small')),
    h('label', {class: 'field', for: 'lnFile'}, h('span', {text: 'Dosya'}), h('div', {class: 'control'}, file)), result),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('Ön izle', preview)]);
}
async function dbtDialog(onsaved) {
  const sources = (await list('data_sources')).filter(s => s.status === 'active');
  const src = h('select', {id: 'dbtSource'}, sources.map(s => h('option', {value: s.id, text: `${s.code} ${s.name}`, selected: ['postgresql', 'snowflake', 'bigquery', 'redshift', 'sql_server'].includes(s.platform)})));
  const file = h('input', {type: 'file', id: 'dbtFile', accept: '.json'});
  const adopt = h('input', {type: 'checkbox', id: 'dbtAdopt', checked: true});
  const result = h('div');
  const body = async dry => { if (!file.files[0]) throw new Error('manifest.json dosyasını seçin'); return {filename: file.files[0].name, ...(await gzipBase64(file.files[0])), source_id: Number(src.value), adopt_descriptions: adopt.checked, dry_run: dry}; };
  const show = r => h('div', {class: 'notice ' + (r.unresolved_count ? 'warn' : 'success')},
    h('strong', {text: `${r.dry_run ? 'Ön izleme — ' : ''}dbt projesi "${r.project}": ${r.nodes} düğüm, ${r.resolved} tanesi katalogda`}),
    h('div', {class: 'small', text: `${r.edges_new} yeni bağlantı, ${r.edges_seen} zaten var${r.edges_removed ? `, ${r.edges_removed} kaldırıldı` : ''}${r.descriptions ? `; ${r.descriptions} boş kaynak açıklaması dbt açıklamasıyla doldurulacak` : ''}.`}),
    r.unresolved_count ? h('div', {class: 'small', text: `Katalogda bulunmayan ${r.unresolved_count} nesne (önce kaynağı içe aktarın): ${r.unresolved.slice(0, 12).join(', ')}${r.unresolved_count > 12 ? ' …' : ''}`}) : null);
  const preview = async () => {
    const r = await api('datagov/lineage/dbt', {method: 'POST', body: await body(true)});
    result.replaceChildren(show(r), h('div', {class: 'toolbar'}, btn('İçe aktar', async () => {
      const done = await api('datagov/lineage/dbt', {method: 'POST', body: await body(false)});
      Modal.close(); toast(`dbt: ${done.edges_new} yeni bağlantı`); if (onsaved) onsaved();
    })));
  };
  Modal.open('dbt manifestini içe aktar', h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'dbt projesinde "dbt compile" veya "dbt docs generate" sonrası oluşan target/manifest.json dosyasını yükleyin. Model, seed, snapshot ve kaynaklar arasındaki bağımlılıklar tablo düzeyinde soy kütüğüne yazılır; manifestte artık olmayan dbt bağlantıları kaldırılır. Kolon düzeyi için SQL ayrıştırıcı onayı beklenmektedir.'}),
    h('label', {class: 'field', for: 'dbtSource'}, h('span', {text: 'dbt modellerinin bulunduğu veri kaynağı (veri ambarı)'}), h('div', {class: 'control'}, src)),
    h('label', {class: 'field', for: 'dbtFile'}, h('span', {text: 'manifest.json'}), h('div', {class: 'control'}, file)),
    h('label', {class: 'toggle', for: 'dbtAdopt'}, adopt, h('span', {text: 'Boş kaynak açıklamalarını dbt açıklamalarıyla doldur'})), result),
  [btn('Kapat', () => Modal.close(), 'secondary'), btn('Ön izle', preview)]);
}
async function openLineageDialog() {
  const sources = (await list('data_sources')).filter(s => s.status === 'active');
  const src = h('select', {id: 'olSource'}, sources.map(s => h('option', {value: s.id, text: `${s.code} ${s.name}`, selected: ['postgresql', 'snowflake', 'bigquery', 'redshift'].includes(s.platform)})));
  Modal.open('OpenLineage alıcısı', h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'Apache Airflow, Spark, dbt ve Flink iş çalıştıkça OpenLineage olayı yayımlar: hangi veri setinden okudu, hangisine yazdı, hangi kolon hangisinden geldi. Alıcı bu olayları toplayıcı anahtarıyla kabul eder; ek program kurulmaz. Olayın yalnızca veri seti adları ve kolon eşlemesi saklanır.'}),
    h('label', {class: 'field', for: 'olSource'}, h('span', {text: 'Varsayılan veri kaynağı (iş çoğunlukla bu ambarda çalışıyorsa)'}), h('div', {class: 'control'}, src)),
    h('p', {class: 'small muted', text: 'Veri setleri kataloğa, kaynağın "Soy kütüğü ad alanı" alanındaki değerle (ör. postgres://dwh-prod:5432, snowflake://hesap) eşlenir; eşlenemeyen veri setleri Soy Kütüğü sayfasında listelenir.'})),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Alıcı oluştur ve anahtarı göster', async () => {
    const r = await api(`data_sources/${src.value}/collectors`, {method: 'POST', body: {connector: 'openlineage', schedule: 'manual'}});
    COLLECT.pending = {id: r.collector.id, col: r.collector, key: r.key, title: 'OpenLineage alıcısı oluşturuldu'};
    Modal.close(); invalidate('data_collectors'); Router.go('collector/' + r.collector.id);
  })]);
}

// ------------------------------------------------------------------ Soy Kütüğü sayfası
PAGES.lineage = async function lineagePage() {
  const d = await api('datagov/lineage'); const reload = () => render();
  setPage('Soy Kütüğü', 'Verinin kaynaktan rapora yolculuğu: tablo ve kolon düzeyinde bağlantılar, veri akış işleri ve "bu değişirse ne etkilenir" analizi.', [
    d.can_edit ? btn('+ Bağlantı', () => edgeDialog({}, reload)) : null,
    d.can_edit ? btn('Excel/CSV içe aktar', () => lineageImportDialog(reload), 'secondary') : null,
    d.can_manage ? btn('dbt manifesti', () => dbtDialog(reload), 'secondary') : null,
    d.can_manage ? btn('OpenLineage alıcısı', openLineageDialog, 'ghost') : null,
    d.stats.edges ? btn('Excel\'e aktar', () => download('datagov/lineage/export?format=xlsx', 'soy-kutugu.xlsx'), 'ghost') : null], [['Veri Yönetişimi', 'datagov']]);
  const st = d.stats;
  if (!st.edges && !d.events.length) {
    const step = (n, title, text, action) => h('div', {class: 'dg-step'}, h('span', {class: 'dg-num', text: n}), h('div', {}, h('strong', {text: title}), h('p', {class: 'small muted', text}), action));
    content(h('div', {class: 'panel'}, h('h3', {text: 'Soy kütüğünü üç yoldan kurun'}), h('div', {class: 'dg-steps'},
      step(1, 'Elle veya Excel ile', 'Bilinen akışları (SAP → veri ambarı → Power BI) tablo veya kolon düzeyinde tanımlayın. Tablolar katalogda olmalıdır.', d.can_edit ? h('div', {class: 'toolbar'}, btn('+ Bağlantı', () => edgeDialog({}, reload), 'secondary small'), btn('Excel/CSV', () => lineageImportDialog(reload), 'ghost small')) : null),
      step(2, 'dbt manifestinden', 'dbt projesinin manifest.json dosyası modeller ve kaynaklar arasındaki bağımlılığı verir.', d.can_manage ? btn('dbt manifesti', () => dbtDialog(reload), 'secondary small') : null),
      step(3, 'OpenLineage ile otomatik', 'Airflow, Spark, dbt ve Flink iş çalıştıkça olay gönderir; kolon eşlemesi dahil soy kütüğü kendiliğinden güncellenir.', d.can_manage ? btn('OpenLineage alıcısı', openLineageDialog, 'secondary small') : null))));
    return;
  }
  const methods = Object.entries(d.by_method).map(([k, n]) => pill(`${META.option('lineage_edges', 'method', k)}: ${fmt.num(n)}`, 'neutral'));
  const edgeItem = e => h('li', {class: 'link', onclick: () => Router.go('flow/' + e.target_table_id)},
    h('div', {class: 'chips'}, linKind(e.kind), h('strong', {text: `${linEnd(e.source_table, e.source_schema, e.source_column)} → ${linEnd(e.target_table, e.target_schema, e.target_column)}`})),
    h('span', {class: 'cell-sub', text: [`${e.source_system} → ${e.target_system}`, e.transformation, e.job_name, META.option('lineage_edges', 'method', e.method)].filter(Boolean).join(' · ')}));
  const jobs = d.jobs.length ? h('ul', {class: 'mini'}, d.jobs.map(j => h('li', {class: 'link', onclick: () => openRecord('lineage_jobs', j.id)},
      h('div', {class: 'chips'}, h('strong', {text: j.name}), j.last_run_at ? pill(META.option('lineage_jobs', 'last_run_state', j.last_run_state), LIN.stateTone[j.last_run_state] || 'neutral') : null),
      h('span', {class: 'cell-sub', text: [j.code, META.option('lineage_jobs', 'system', j.system), `${fmt.num(j.edges)} bağlantı`, j.schedule_note,
        j.last_run_at ? 'son çalışma ' + agoText(j.last_run_at) : null, j.namespace].filter(Boolean).join(' · ')})))) :
    h('div', {class: 'muted small', text: 'Veri akış işi yok. Excel içe aktarımında "Veri akış işi" sütunu, OpenLineage ve dbt işleri buraya ekler.'});
  const unresolved = h('div', {class: 'muted small', text: 'Yükleniyor…'});
  api('datagov/lineage/unresolved').then(u => unresolved.replaceChildren(u.items.length ? h('div', {},
    h('p', {class: 'small', text: 'Bu veri setleri kataloğa eşlenemedi. Kaynağın "Soy kütüğü ad alanı" alanına olaydaki ad alanını yazın (birden çok değer virgülle) ve tablo katalogda yoksa önce içe aktarın; ardından "Yeniden işle".'}),
    h('ul', {class: 'mini'}, u.items.slice(0, 20).map(x => h('li', {}, h('strong', {text: x.name}), h('span', {class: 'cell-sub', text: `${x.namespace} · ${x.events} olay · ${fmt.datetime(x.last_seen)}`})))),
    d.can_manage ? btn('Yeniden işle', async () => { const r = await api('datagov/lineage/reprocess', {method: 'POST', body: {}}); toast(`${r.events} olay işlendi, ${r.edges_new} yeni bağlantı`); reload(); }, 'secondary small') : null) :
    h('div', {class: 'muted small', text: 'Eşlenemeyen veri seti yok.'}))).catch(() => unresolved.remove());
  const ol = h('div', {},
    d.receivers.length ? h('ul', {class: 'mini'}, d.receivers.map(r => h('li', {class: 'link', onclick: () => Router.go('collector/' + r.id)}, h('strong', {text: `${r.code} ${r.name}`}),
      h('span', {class: 'cell-sub', text: [r.source_name, r.status === 'active' ? (r.last_push_at ? 'son olay ' + agoText(r.last_push_at) : 'henüz olay yok') : 'iptal edildi'].join(' · ')})))) :
      h('div', {class: 'muted small', text: 'Alıcı tanımlı değil.'}),
    d.events.length ? section('Son olaylar', h('ul', {class: 'mini'}, d.events.map(e => h('li', {}, h('div', {class: 'chips'}, pill(META.option('lineage_jobs', 'last_run_state', e.event_type), LIN.stateTone[e.event_type] || 'neutral'), h('strong', {text: e.job_name})),
      h('span', {class: 'cell-sub', text: [e.job_namespace, `${e.edges_new} yeni, ${e.edges_seen} görülen bağlantı`, e.unresolved ? `${e.unresolved} eşlenemeyen` : null, fmt.datetime(e.created_at)].filter(Boolean).join(' · ')}))))) : null,
    section('Eşlenemeyen veri setleri', unresolved));
  content(
    h('div', {class: 'grid four'}, metric('Bağlantı', fmt.num(st.edges), `${fmt.num(st.column_edges)} kolon düzeyinde`), metric('Besleyen tablo', fmt.num(st.sources), 'en az bir hedefe akan'),
      metric('Beslenen tablo', fmt.num(st.targets), 'en az bir kaynaktan gelen'), metric('Kopuk bağlantı', fmt.num(d.broken.length), 'kaldırılmış nesneye bağlı', d.broken.length ? 'warn' : '')),
    methods.length ? h('div', {class: 'chips'}, h('span', {class: 'muted small', text: 'Kaynağına göre: '}), methods) : null,
    d.broken.length ? h('div', {class: 'notice warn'}, h('strong', {text: `${d.broken.length} bağlantı kaynakta kaldırılmış tablo veya kolona işaret ediyor. `}), 'Akışı güncelleyin veya bağlantının durumunu "Kaldırıldı" yapın: ',
      d.broken.slice(0, 6).map(b => h('a', {class: 'chip', href: '#/r/lineage_edges/' + b.id, text: `${b.source_table}${b.source_column ? '.' + b.source_column : ''} → ${b.target_table}${b.target_column ? '.' + b.target_column : ''}`}))) : null,
    h('div', {class: 'grid wide-left'},
      panel('Son bağlantılar', d.recent.length ? h('ul', {class: 'mini'}, d.recent.map(edgeItem)) : h('div', {class: 'muted small', text: 'Bağlantı yok'})),
      panel('En çok besleyen tablolar', d.hubs.length ? h('ul', {class: 'mini'}, d.hubs.map(t => h('li', {class: 'link', onclick: () => Router.go('impact/' + t.id)},
        h('strong', {text: dgPath(t.schema_name, t.name)}), h('span', {class: 'cell-sub', text: `${t.source_name} · ${t.downstream} hedef · etki analizi`})))) : h('div', {class: 'muted small', text: '—'}),
        null, 'değişirse en geniş etki')),
    h('div', {class: 'grid two'}, panel('Veri akış işleri', jobs), panel('OpenLineage', ol)));
};

// ------------------------------------------------------------------ akış şeması (SVG)
const FLOW = {w: 200, h: 58, gap: 70, vgap: 18, pad: 14};
PAGES.flow = async function flowPage(parts, params) {
  const tid = Number(parts[1]); const col = params.get('c') || ''; const depth = params.get('d') || '2';
  const [g, t] = await Promise.all([api(`datagov/lineage/graph?table_id=${tid}&depth=${depth}${col ? '&column_id=' + col : ''}`), api(`data_tables/${tid}/context`)]);
  const go = (c, d) => Router.go(`flow/${tid}?d=${d}${c ? '&c=' + c : ''}`);
  setPage(`Akış şeması: ${t.name}`, `${t.source.name}${t.schema_name ? ' / ' + t.schema_name : ''}${g.focus.column ? ' · kolon ' + g.focus.column : ''} — soldan sağa veri akışı`, [
    btn('Etki analizi', () => Router.go(`impact/${tid}${col ? '?c=' + col : ''}`)), btn('Tabloya git', () => Router.go('catalog/table/' + tid), 'secondary')],
    [['Soy Kütüğü', 'lineage'], [t.name, 'catalog/table/' + tid]]);
  const colSel = h('select', {id: 'flowCol', onchange: e => go(e.target.value, depth)}, h('option', {value: '', text: 'Tablonun tamamı'}),
    t.columns.filter(c => c.status === 'active').map(c => h('option', {value: c.id, text: c.name, selected: String(c.id) === col})));
  const depthSel = h('select', {id: 'flowDepth', onchange: e => go(col, e.target.value)}, [1, 2, 3, 4, 6].map(n => h('option', {value: n, text: `${n} adım`, selected: String(n) === depth})));
  const tools = h('div', {class: 'toolbar flow-tools'}, h('label', {class: 'field inline', for: 'flowCol'}, h('span', {text: 'Odak'}), colSel),
    h('label', {class: 'field inline', for: 'flowDepth'}, h('span', {text: 'Derinlik'}), depthSel),
    h('span', {class: 'flow-legend'}, h('i', {class: 'lg lg-focus'}), 'odak', h('i', {class: 'lg lg-report'}), 'rapor / model', h('i', {class: 'lg lg-personal'}), 'kişisel veri',
      h('i', {class: 'lg lg-removed'}), 'kaldırılmış', h('i', {class: 'lg lg-col'}), 'kolon eşlemesi', h('i', {class: 'lg lg-table'}), 'tablo düzeyi'));
  if (g.nodes.length < 2) {
    content(tools, empty('Bu tablonun soy kütüğü yok', 'Bu tablodan beslenen veya bu tabloyu besleyen bağlantı tanımlı değil.', META.can('write') ? btn('+ Bağlantı', () => edgeDialog({source: {...t, source_name: t.source.name}}, () => render())) : null));
    return;
  }
  const levels = [...new Set(g.nodes.map(n => n.level))].sort((a, b) => a - b);
  const byLevel = Object.fromEntries(levels.map(l => [l, g.nodes.filter(n => n.level === l)]));
  const rowsMax = Math.max(...levels.map(l => byLevel[l].length));
  const W = FLOW.pad * 2 + levels.length * FLOW.w + (levels.length - 1) * FLOW.gap;
  const H = FLOW.pad * 2 + rowsMax * FLOW.h + (rowsMax - 1) * FLOW.vgap;
  const pos = {};
  levels.forEach((l, i) => {
    const list = byLevel[l]; const offset = (rowsMax - list.length) * (FLOW.h + FLOW.vgap) / 2;
    list.forEach((n, j) => { pos[n.id] = {x: FLOW.pad + i * (FLOW.w + FLOW.gap), y: FLOW.pad + offset + j * (FLOW.h + FLOW.vgap)}; });
  });
  const detail = h('div', {class: 'panel flow-detail'}, h('div', {class: 'muted small', text: 'Ayrıntı için bir kutuya veya bağlantıya tıklayın.'}));
  const svg = s('svg', {class: 'flow', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `${t.name} akış şeması: ${g.nodes.length} tablo`});
  const nodeOf = Object.fromEntries(g.nodes.map(n => [n.id, n]));
  for (const l of g.links) {
    const a = pos[l.from], b = pos[l.to]; if (!a || !b) continue;
    const x1 = a.x + FLOW.w, y1 = a.y + FLOW.h / 2, x2 = b.x, y2 = b.y + FLOW.h / 2, mx = (x1 + x2) / 2;
    const path = s('path', {d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, class: 'flow-link' + (l.kinds.every(k => k === 'indirect') ? ' indirect' : '') + (l.table_level ? '' : ' column'), tabindex: '0'},
      s('title', {}, `${nodeOf[l.from].name} → ${nodeOf[l.to].name}: ${l.columns.length ? l.columns.length + ' kolon eşlemesi' : 'tablo düzeyi'}${l.jobs.length ? ' · ' + l.jobs.join(', ') : ''}`));
    const showLink = () => detail.replaceChildren(h('h3', {text: `${nodeOf[l.from].name} → ${nodeOf[l.to].name}`}),
      h('div', {class: 'chips'}, l.kinds.map(linKind), l.table_level ? pill('Tablo düzeyi', 'neutral') : null),
      l.jobs.length ? h('p', {class: 'small', text: 'Veri akış işi: ' + l.jobs.join(', ')}) : null,
      l.columns.length ? h('ul', {class: 'mini plain'}, l.columns.map(c => h('li', {class: 'small', text: `${c.from} → ${c.to} (${META.option('lineage_edges', 'kind', c.kind)})`}))) : null);
    path.addEventListener('click', showLink); path.addEventListener('keydown', e => { if (e.key === 'Enter') showLink(); });
    svg.append(path);
  }
  for (const n of g.nodes) {
    const p = pos[n.id];
    const cls = ['flow-node', n.id === tid ? 'focus' : '', n.report ? 'report' : '', n.personal ? 'personal' : '', n.removed ? 'removed' : ''].filter(Boolean).join(' ');
    const label = n.name.length > 24 ? n.name.slice(0, 23) + '…' : n.name;
    const sub = `${n.source}${n.schema ? ' / ' + n.schema : ''}`;
    const cols = n.columns ? 'kolon: ' + n.columns.join(', ') : (n.level ? 'tablonun tamamı' : '');
    const gEl = s('g', {class: cls, tabindex: '0', transform: `translate(${p.x},${p.y})`},
      s('title', {}, `${n.name}${n.business_name ? ' — ' + n.business_name : ''}\n${sub}${n.owner ? '\nSahip: ' + n.owner : ''}`),
      s('rect', {width: FLOW.w, height: FLOW.h, rx: 9}),
      s('text', {x: 12, y: 20, class: 'fn-title'}, label),
      s('text', {x: 12, y: 36, class: 'fn-sub'}, sub.length > 31 ? sub.slice(0, 30) + '…' : sub),
      cols ? s('text', {x: 12, y: 50, class: 'fn-cols'}, cols.length > 33 ? cols.slice(0, 32) + '…' : cols) : null,
      n.personal ? s('circle', {cx: FLOW.w - 14, cy: 14, r: 5, class: 'fn-dot'}) : null);
    const showNode = () => detail.replaceChildren(h('h3', {text: n.business_name ? `${n.name} — ${n.business_name}` : n.name}),
      kv([['Sistem', n.source], ['Tür', META.option('data_tables', 'object_type', n.object_type)], ['Konum', n.level < 0 ? `${-n.level} adım yukarı akışta` : n.level > 0 ? `${n.level} adım aşağı akışta` : 'Odak'],
        ['Veri sahibi', n.owner || '—'], n.columns ? ['Etkilenen kolonlar', n.columns.join(', ')] : null, n.personal ? ['Kişisel veri', `${n.personal} kolon${n.special ? `, ${n.special} özel nitelikli` : ''}`] : null]),
      h('div', {class: 'toolbar'}, btn('Tabloya git', () => Router.go('catalog/table/' + n.id), 'secondary small'), n.id !== tid ? btn('Bu tabloya odaklan', () => Router.go(`flow/${n.id}?d=${depth}`), 'ghost small') : null,
        btn('Etki analizi', () => Router.go('impact/' + n.id), 'ghost small')));
    gEl.addEventListener('click', showNode); gEl.addEventListener('keydown', e => { if (e.key === 'Enter') showNode(); });
    svg.append(gEl);
  }
  content(tools, g.truncated ? h('div', {class: 'notice warn', text: `Şema ${g.nodes.length} tabloyla sınırlandı; derinliği azaltın veya bir kolona odaklanın.`}) : null,
    h('div', {class: 'panel flow-wrap'}, svg), detail);
};

// ------------------------------------------------------------------ etki analizi
PAGES.impact = async function impactPage(parts, params) {
  const tid = Number(parts[1]); const col = params.get('c') || '';
  const [r, t] = await Promise.all([api(`data_tables/${tid}/impact${col ? '?column_id=' + col : ''}`), api(`data_tables/${tid}/context`)]);
  const f = r.focus; const target = dgPath(f.schema, f.name) + (f.column ? '.' + f.column : '');
  const notify = () => {
    const note = h('textarea', {id: 'impNote', placeholder: 'Ör. KUNNR alanı 10 haneden 12 haneye çıkıyor; geçiş hafta sonu yapılacak.'});
    const date = h('input', {type: 'date', id: 'impDate'});
    Modal.open('Planlanan değişikliği bildir', h('div', {},
      h('p', {class: 'intro', text: `${target} üzerindeki planlanan değişiklik, aşağı akıştaki ${r.people.length} kişiye (veri sahibi, veri yöneticisi, teknik sorumlu, kontrol sahibi) etkilenen nesnelerin listesiyle e-posta/Teams kanalından bildirilir.`}),
      h('label', {class: 'field', for: 'impNote'}, h('span', {text: 'Değişiklik'}), h('div', {class: 'control'}, note)),
      h('label', {class: 'field', for: 'impDate'}, h('span', {text: 'Planlanan tarih'}), h('div', {class: 'control'}, date))),
    [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Bildir', async () => {
      const res = await api(`data_tables/${tid}/impact/notify`, {method: 'POST', body: {note: note.value, planned_on: date.value || null, column_id: Number(col) || null}});
      Modal.close(); toast(res.queued ? `${res.queued} bildirim kuyruğa alındı (${res.people} kişi)` : 'Bildirim kuyruğa alınmadı: e-posta/Teams kanalı kapalı veya kişilerin e-posta adresi yok', !!res.queued);
    })]);
  };
  setPage(`Etki analizi: ${target}`, `${f.source} · bu ${f.column ? 'kolon' : 'tablo'} değişirse aşağı akışta etkilenenler`, [
    btn('Akış şeması', () => Router.go(`flow/${tid}${col ? '?c=' + col : ''}`), 'secondary'),
    btn('Etki raporu (CSV)', () => download(`data_tables/${tid}/impact/export${col ? '?column_id=' + col : ''}`, `etki-${f.name}.csv`), 'secondary'),
    r.can_notify && r.people.length ? btn('Sahiplere bildir', notify) : null], [['Soy Kütüğü', 'lineage'], [t.name, 'catalog/table/' + tid]]);
  const colSel = h('select', {id: 'impCol', onchange: e => Router.go(`impact/${tid}${e.target.value ? '?c=' + e.target.value : ''}`)}, h('option', {value: '', text: 'Tablonun tamamı'}),
    t.columns.filter(c => c.status === 'active').map(c => h('option', {value: c.id, text: c.name, selected: String(c.id) === col})));
  const pick = h('div', {class: 'toolbar flow-tools'}, h('label', {class: 'field inline', for: 'impCol'}, h('span', {text: 'Değişecek nesne'}), colSel),
    h('span', {class: 'small muted', text: r.upstream ? `Bu nesneyi besleyen ${r.upstream} tablo var (akış şemasında).` : ''}));
  const sm = r.summary;
  if (!r.affected.length) {
    content(pick, empty('Aşağı akışta etkilenen nesne bulunamadı', 'Bu nesneden beslenen tablo, rapor veya sistem tanımlı değil. Soy kütüğü eksikse bağlantı ekleyin; tablo düzeyindeki bağlantılar tüm kolonları taşır.',
      META.can('write') ? btn('+ Bağlantı', () => edgeDialog({source: {...t, source_name: t.source.name}}, () => render())) : null));
    return;
  }
  const affected = h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Adım', 'Sistem', 'Tablo / rapor', 'Etkilenen kolonlar', 'Sorumlular', 'Yol'].map(x => h('th', {text: x})))),
    h('tbody', {}, r.affected.map(a => h('tr', {class: 'link', onclick: () => Router.go('catalog/table/' + a.id)},
      h('td', {class: 'num', text: a.depth}), h('td', {text: a.source}),
      h('td', {}, h('strong', {text: dgPath(a.schema, a.name)}), a.business_name ? h('div', {class: 'cell-sub', text: a.business_name}) : null,
        h('div', {class: 'chips'}, a.report ? pill(META.option('data_tables', 'object_type', a.object_type), 'purple') : null, a.personal ? pill(`${a.personal} kişisel`, a.special ? 'bad' : 'warn') : null, a.certified ? pill('Onaylı veri seti', 'good') : null)),
      h('td', {class: 'small', text: a.columns ? a.columns.join(', ') : 'tümü (tablo düzeyi)'}),
      h('td', {class: 'small'}, [a.owner ? `Sahip: ${a.owner}` : null, a.steward ? `Veri yön.: ${a.steward}` : null].filter(Boolean).join(' · ') || h('span', {class: 'muted', text: 'Atanmamış'})),
      h('td', {class: 'small muted', text: [f.name, ...a.via, a.name].join(' → ')}))))));
  const simple = (items, render, none) => items.length ? h('ul', {class: 'mini'}, items.map(render)) : h('div', {class: 'muted small', text: none});
  content(pick,
    h('div', {class: 'grid four'}, metric('Etkilenen tablo', fmt.num(sm.tables), `en uzak ${sm.max_depth} adım`), metric('Rapor / anlamsal model', fmt.num(sm.reports), 'Power BI ve raporlar', sm.reports ? 'warn' : ''),
      metric('Sistem', fmt.num(sm.systems), 'odak dahil'), metric('Kişisel veri içeren', fmt.num(sm.personal), 'etkilenen tablo', sm.personal ? 'warn' : '')),
    h('div', {class: 'grid wide-left'},
      panel('Etkilenen tablolar ve raporlar', affected),
      h('div', {},
        panel('Bildirilecek kişiler', simple(r.people, p => h('li', {}, h('strong', {text: p.person}), h('span', {class: 'cell-sub', text: `${p.roles.join(', ')}${p.tables ? ` · ${p.tables} nesne` : ''}`})), 'Etkilenen nesnelerde sahip atanmamış.')),
        panel('Sistemler', simple(r.systems, x => h('li', {class: 'link', onclick: () => Router.go('datasource/' + x.id)}, h('strong', {text: x.name}), h('span', {class: 'cell-sub', text: `${META.option('data_sources', 'platform', x.platform)} · ${x.tables} tablo`})), '—')))),
    h('div', {class: 'grid two'},
      panel('Süreçler (BİA ve işleme faaliyetleri)', simple(r.processes, p => h('li', {}, h('strong', {text: `${p.code} ${p.name}`}), h('span', {class: 'cell-sub', text: p.via})), 'Kaynakların CMDB öğesi BİA\'ya veya tablolar işleme faaliyetine bağlı değil.')),
      panel('Kontroller', simple(r.controls, k => h('li', {class: 'link', onclick: () => openRecord('controls', k.id)}, h('strong', {text: `${k.code} ${k.name}`}), h('span', {class: 'cell-sub', text: [k.owner, k.via].filter(Boolean).join(' · ')})), 'Etkilenen nesnelere veya süreçlerine bağlı kontrol yok.'))),
    h('div', {class: 'grid two'},
      panel('İşleme faaliyetleri (KVKK)', simple(r.activities, a => h('li', {class: 'link', onclick: () => Router.go('activity/' + a.id)}, h('strong', {text: `${a.code} ${a.name}`})), 'Bağlı işleme faaliyeti yok.')),
      panel('Sözlük terimleri ve riskler', h('div', {}, simple(r.terms, g => h('li', {class: 'link', onclick: () => Router.go('glossary/' + g.id)}, h('strong', {text: g.name}), h('span', {class: 'cell-sub', text: [g.code, g.owner].filter(Boolean).join(' · ')})), 'Bağlı terim yok.'),
        r.risks.length ? section('Açık riskler', simple(r.risks, x => h('li', {class: 'link', onclick: () => openRecord('supplier_risks', x.id)}, h('strong', {text: `${x.code} ${x.title}`})), '')) : null))));
};

// ------------------------------------------------------------------ tablo sayfası ve kolon paneli
TABLE_EXTRAS.push((t, reload) => {
  const host = h('div', {class: 'panel lin-panel'}, h('div', {class: 'muted small', text: 'Soy kütüğü yükleniyor…'}));
  api(`data_tables/${t.id}/lineage`).then(l => {
    const chip = (g, dir) => h('button', {type: 'button', class: 'chip link', onclick: () => Router.go('catalog/table/' + g.id),
      text: `${dir === 'up' ? '' : '→ '}${dgPath(g.schema, g.name)}${dir === 'up' ? ' →' : ''}`, title: `${g.system} · ${g.columns ? g.columns + ' kolon eşlemesi' : 'tablo düzeyi'}${g.jobs.length ? ' · ' + g.jobs.join(', ') : ''}`});
    const side = (title, items, dir) => h('div', {}, h('div', {class: 'choice-group', text: `${title} (${items.length})`}),
      items.length ? h('div', {class: 'chips'}, items.slice(0, 12).map(g => chip(g, dir)), items.length > 12 ? h('span', {class: 'muted small', text: `+${items.length - 12}`}) : null) : h('div', {class: 'muted small', text: dir === 'up' ? 'Besleyen tablo tanımlı değil' : 'Beslediği tablo tanımlı değil'}));
    const controls = h('div', {class: 'small'}, 'Kontroller: ', l.controls.length ? l.controls.map(k => h('a', {class: 'chip', href: '#/r/controls/' + k.id, text: k.code})) : h('span', {class: 'muted', text: 'bağlı değil'}),
      l.can_edit && hasModule('grc') ? btn('Düzenle', async () => {
        const all = (await list('controls', true)).filter(k => k.active);
        const chosen = await pickMany('Bu veri varlığına bağlı kontroller: ' + t.name, all, l.controls.map(k => k.id), {label: k => `${k.code} ${k.name}`,
          intro: 'Bu tabloyu koruyan veya doğrulayan kontroller (mutabakat, erişim, kalite). Etki analizinde değişiklikten etkilenen kontroller olarak listelenir.'});
        if (chosen) { await api(`data_tables/${t.id}/controls`, {method: 'POST', body: {control_ids: chosen}}); toast('Kaydedildi'); reload(); }
      }, 'ghost small') : null);
    host.replaceChildren(h('div', {class: 'panel-title'}, h('h3', {text: 'Soy kütüğü'}), h('div', {class: 'toolbar'},
      l.upstream.length || l.downstream.length ? btn('Akış şeması', () => Router.go('flow/' + t.id), 'secondary small') : null,
      btn('Etki analizi', () => Router.go('impact/' + t.id), 'secondary small'),
      l.can_edit ? btn('+ Bağlantı', () => edgeDialog({target: {...t, source_name: t.source.name}}, reload), 'ghost small') : null)),
      h('div', {class: 'grid two'}, side('Besleyen (yukarı akış)', l.upstream, 'up'), side('Beslediği (aşağı akış)', l.downstream, 'down')), controls);
  }).catch(() => host.remove());
  return host;
});
COLUMN_EXTRAS.push(c => {
  const host = h('div');
  api(`data_columns/${c.id}/lineage`).then(l => {
    const line = (e, dir) => h('li', {class: 'small'}, dir === 'up' ? `${linEnd(e.source_table, e.source_schema, e.source_column || '*', e.source_system)} →` : `→ ${linEnd(e.target_table, e.target_schema, e.target_column || '*', e.target_system)}`,
      e.transformation ? h('span', {class: 'cell-sub', text: e.transformation}) : null);
    host.replaceChildren(section('Soy kütüğü', h('div', {},
      l.upstream.length ? h('ul', {class: 'mini plain'}, l.upstream.slice(0, 10).map(e => line(e, 'up'))) : h('div', {class: 'muted small', text: 'Kaynağı tanımlı değil.'}),
      l.downstream.length ? h('ul', {class: 'mini plain'}, l.downstream.slice(0, 10).map(e => line(e, 'down'))) : h('div', {class: 'muted small', text: 'Beslediği kolon tanımlı değil.'}),
      h('div', {class: 'toolbar'}, btn('Etki analizi', () => { Drawer.close(); Router.go(`impact/${c.table_id}?c=${c.id}`); }, 'secondary small'),
        l.upstream.length || l.downstream.length ? btn('Akış şeması', () => { Drawer.close(); Router.go(`flow/${c.table_id}?c=${c.id}`); }, 'ghost small') : null))));
  }).catch(() => {});
  return host;
});

'use strict';
/* Yapay zekâ sistemleri envanteri ve AB Yapay Zekâ Tüzüğü risk sınıflandırması (K-034). app.js, pages.js,
   datagov.js ve lineage.js yardımcılarını kullanır; satır içi stil yok. */

const AI = {
  tone: {prohibited: 'bad', high: 'bad', limited: 'warn', minimal: 'good', unassessed: 'neutral'},
  sev: {critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral'},
  classes: ['prohibited', 'high', 'limited', 'minimal', 'unassessed'],
  fields: ['name', 'purpose', 'description', 'role', 'source_type', 'supplier_id', 'model_type', 'gpai_based', 'deployment', 'lifecycle', 'owner',
    'technical_owner', 'process_id', 'org_unit_id', 'ci_id', 'affected_persons', 'uses_personal_data', 'uses_special_data', 'automated_decision',
    'human_oversight', 'transparency_notice', 'log_retention_months', 'activity_id', 'dpia_id', 'fria_done_on', 'last_evaluated_on', 'evaluation_summary',
    'monitoring', 'review_date'],
};
const aiClassPill = c => pill(META.option('ai_systems', 'risk_class', c), AI.tone[c] || 'neutral');
const aiGapList = gaps => gaps.length ? h('ul', {class: 'mini'}, gaps.map(g => h('li', {},
  h('div', {class: 'chips'}, pill(META.option('findings', 'severity', g.severity), AI.sev[g.severity]), h('strong', {text: g.text})),
  g.ref ? h('span', {class: 'cell-sub', text: 'Dayanak: ' + g.ref}) : null))) : h('div', {class: 'notice success small', text: 'Kural tabanlı açık yok.'});

function aiForm(record, onsaved) {
  return recordForm('ai_systems', record, {only: AI.fields, title: record ? 'Düzenle: ' + record.name : 'Yeni yapay zekâ sistemi',
    onsaved: onsaved || (r => Router.go('aisystem/' + r.id))});
}

function aiClassifyDialog(sys, q, previous, reload) {
  const prev = (previous && previous.answers) || {};
  const box = (key, items, multi = true) => h('div', {class: 'choices ai-choices'}, items.map(it => h('label', {},
    h('input', {type: multi ? 'checkbox' : 'radio', name: 'ai_' + key, value: it.key, checked: multi ? (prev[key] || []).includes(it.key) : prev[key] === it.key}),
    h('span', {}, it.ref ? h('strong', {text: it.ref + ' '}) : null, it.text))));
  const flag = (id, label, value) => h('label', {class: 'toggle', for: id}, h('input', {type: 'checkbox', id, checked: !!value}), label);
  const prohibited = box('prohibited', q.prohibited); const annex = box('annex_iii', q.annex_iii);
  const derog = h('div', {class: 'choices ai-choices'}, [{key: '', text: 'Hiçbiri / bilmiyorum (istisna uygulanmaz)'}, ...q.derogation].map(it => h('label', {},
    h('input', {type: 'radio', name: 'ai_derog', value: it.key, checked: (prev.derogation || '') === it.key}), h('span', {text: it.text}))));
  const transparency = box('transparency', q.transparency);
  const step = (n, title, hint, body) => h('section', {class: 'ai-step'}, h('div', {class: 'ai-step-head'}, h('span', {class: 'dg-num', text: n}), h('div', {}, h('strong', {text: title}), hint ? h('div', {class: 'small muted', text: hint}) : null)), body);
  const picked = name => [...document.querySelectorAll(`input[name="ai_${name}"]:checked`)].map(i => i.value);
  const answers = () => ({prohibited: picked('prohibited'), annex_iii: picked('annex_iii'), derogation: picked('derog')[0] || null,
    product_safety: $('aiProduct').checked, profiling: $('aiProfiling').checked, public_service: $('aiPublic').checked, transparency: picked('transparency'), gpai_provider: $('aiGpai').checked});
  const body = h('div', {class: 'ai-wizard'},
    h('p', {class: 'intro', text: `${sys.code} ${sys.name} için Tüzük (AB) 2024/1689 sorularını yanıtlayın. Sonuç, dayanak maddeler ve kurumun rolüne (${META.option('ai_systems', 'role', sys.role)}) göre yükümlülükler kayda yazılır. Bu bir ön değerlendirmedir; hukuki görüş değildir.`}),
    step(1, 'Yasaklı uygulamalar (md. 5)', 'Herhangi biri işaretlenirse sistem kullanılamaz.', prohibited),
    step(2, 'Ürün güvenliği (md. 6(1), Ek I)', null, flag('aiProduct', 'Sistem, üçüncü taraf uygunluk değerlendirmesine tabi bir ürünün (makine, tıbbi cihaz, oyuncak, asansör, araç…) güvenlik bileşeni veya kendisi', prev.product_safety)),
    step(3, 'Yüksek riskli kullanım alanları (Ek III)', 'Sistemin kullanıldığı alanları işaretleyin.', annex),
    step(4, 'md. 6(3) istisnası', 'Ek III alanında olsa da önemli zarar riski yoksa ve aşağıdakilerden biri geçerliyse yüksek riskli sayılmaz. Gerçek kişilerin profilini çıkaran sistemde istisna uygulanmaz.',
      h('div', {}, derog, flag('aiProfiling', 'Sistem gerçek kişilerin profilini çıkarıyor (kişisel özellik, davranış, tercih, performans değerlendirmesi)', prev.profiling))),
    step(5, 'Kullanıcı (deployer) durumu', null, flag('aiPublic', 'Kurum kamu hukuku tüzel kişisi veya kamu hizmeti sunan özel kuruluş (md. 27: temel haklar etki değerlendirmesi)', prev.public_service)),
    step(6, 'Şeffaflık yükümlülükleri (md. 50)', null, transparency),
    step(7, 'Genel amaçlı model', null, flag('aiGpai', 'Kurum, genel amaçlı bir yapay zekâ modelinin sağlayıcısıdır (modeli kendisi geliştirip başkalarına sunar)', prev.gpai_provider)));
  Modal.open('Risk sınıflandırma sihirbazı', body, [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Sınıflandır ve kaydet', async () => {
    const r = await api(`ai_systems/${sys.id}/classify`, {method: 'POST', body: {answers: answers()}});
    Modal.close(); toast('Risk sınıfı: ' + META.option('ai_systems', 'risk_class', r.risk_class)); reload();
  })], true);
}

function aiTablesDialog(sys, current, reload) {
  const items = current.map(t => ({table_id: t.table_id, usage: t.usage, note: t.note, label: `${t.source_name} / ${dgPath(t.schema_name, t.name)}`}));
  const listBox = h('ul', {class: 'mini'});
  const usageSel = h('select', {id: 'aiUsage'}, ['training', 'fine_tuning', 'input', 'output', 'reference'].map(k => h('option', {value: k, text: META.option('ai_system_tables', 'usage', k)})));
  const picker = tablePicker('aiTable', 'Veri varlığı ara (ör. musteri, kredi_basvuru)');
  picker.colSel.classList.add('hidden');
  const draw = () => fillEl(listBox, items.length ? items.map((it, i) => h('li', {},
    h('div', {class: 'chips'}, h('strong', {text: it.label}), pill(META.option('ai_system_tables', 'usage', it.usage), 'neutral'), btn('Çıkar', () => { items.splice(i, 1); draw(); }, 'ghost small')))) :
    [h('li', {class: 'muted small', text: 'Bağlı veri varlığı yok.'})]);
  draw();
  Modal.open('Veri varlıkları: ' + sys.name, h('div', {},
    h('p', {class: 'intro', text: 'Eğitim, girdi, çıktı ve referans verisini katalogdaki tablolara bağlayın. Bağlı tabloda kişisel veri varsa sistem kişisel veri işliyor sayılır; tablo değişince soy kütüğü etki analizi bu sistemi de listeler.'}),
    h('div', {class: 'formgrid'}, h('div', {class: 'field wide'}, 'Tablo', picker.node), h('label', {class: 'field', for: 'aiUsage'}, 'Kullanım', h('div', {class: 'control'}, usageSel)),
      h('div', {class: 'field'}, ' ', btn('+ Ekle', () => {
        const t = picker.state.table; if (!t) { toast('Önce bir tablo seçin', false); return; }
        if (items.some(x => x.table_id === t.id)) { toast('Bu tablo zaten listede', false); return; }
        items.push({table_id: t.id, usage: usageSel.value, label: `${t.source_name || ''} / ${dgPath(t.schema_name, t.name)}`}); draw();
      }, 'secondary'))),
    section('Bağlı veri varlıkları', listBox)), [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => {
    await api(`ai_systems/${sys.id}/tables`, {method: 'POST', body: {items: items.map(x => ({table_id: x.table_id, usage: x.usage, note: x.note || null}))}});
    Modal.close(); toast('Veri varlıkları kaydedildi'); reload();
  })], true);
}

PAGES.ai = async function aiPage(parts, params) {
  const d = await api('datagov/ai');
  const state = {cls: params.get('s') || '', q: '', gapsOnly: false};
  setPage('Yapay Zekâ Envanteri', 'Kurumun geliştirdiği, satın aldığı veya hizmet olarak kullandığı yapay zekâ sistemleri; AB Yapay Zekâ Tüzüğü risk sınıfı, veri bağlantıları ve KVKK/GDPR açıkları.', [
    d.can_write ? btn('+ Yapay zekâ sistemi', () => aiForm()) : null, btn('CSV indir', () => download('datagov/ai/export', 'yapay-zeka-envanteri.csv'), 'secondary')], [['Veri Yönetişimi', 'datagov']]);
  const q = d.questions;
  const timeline = panel('Uygulama takvimi (Tüzük md. 113)', h('div', {}, h('ul', {class: 'mini plain ai-timeline'}, q.timeline.map(t => h('li', {class: t.date <= today() ? 'past' : ''},
    h('strong', {text: fmt.date(t.date)}), h('span', {text: ' ' + t.text})))), h('div', {class: 'muted small', text: q.timeline_note})));
  if (!d.systems.length) {
    const st = (n, title, text) => h('div', {class: 'dg-step'}, h('span', {class: 'dg-num', text: n}), h('div', {}, h('strong', {text: title}), h('p', {class: 'small muted', text})));
    content(h('div', {class: 'panel'}, h('h3', {text: 'Yapay zekâ envanterini üç adımda kurun'}), h('div', {class: 'dg-steps'},
      st(1, 'Sistemleri kaydedin', 'Sohbet botları, kredi puanlama, aday eleme, belge sınıflandırma, öneri motorları; satın alınanlar dâhil. Tedarikçi seçilince sözleşme ve DPA izlenir.'),
      st(2, 'Sınıflandırın', 'Sihirbaz yasaklı uygulama, Ek III yüksek risk, md. 6(3) istisnası ve md. 50 şeffaflık sorularıyla risk sınıfını ve yükümlülükleri belirler.'),
      st(3, 'Veriye bağlayın', 'Eğitim ve girdi tablolarını katalogdan seçin; kişisel veri, işleme faaliyeti ve VKED açıkları kendiliğinden hesaplanır.')),
      d.can_write ? btn('+ Yapay zekâ sistemi', () => aiForm()) : null), timeline);
    return;
  }
  const bc = d.by_class;
  const top = h('div', {class: 'grid four'},
    metric('Kullanımdaki / planlanan sistem', fmt.num(d.active), `${fmt.num(d.gpai)} tanesi genel amaçlı modele dayanıyor`),
    metric('Yüksek risk', fmt.num(bc.high), bc.prohibited ? `${bc.prohibited} yasaklı uygulama!` : 'Ek III veya ürün güvenliği', bc.prohibited ? 'bad' : bc.high ? 'warn' : '', () => { state.cls = 'high'; draw(); }),
    metric('Sınıflandırılmamış', fmt.num(bc.unassessed), 'sihirbaz bekliyor', bc.unassessed ? 'warn' : 'good', () => { state.cls = 'unassessed'; draw(); }),
    metric('Açık', fmt.num(d.gaps), `${fmt.num(d.personal)} sistem kişisel veri, ${fmt.num(d.automated)} otomatik karar`, d.gaps ? 'warn' : 'good', () => { state.gapsOnly = true; gapBox.checked = true; draw(); }));
  const dist = h('div', {class: 'ai-dist'}, AI.classes.map(k => h('button', {type: 'button', class: 'ai-dist-item ' + k + (state.cls === k ? ' on' : ''), 'aria-pressed': String(state.cls === k),
    onclick: () => { state.cls = state.cls === k ? '' : k; draw(); }}, h('span', {class: 'ai-dist-n', text: fmt.num(bc[k])}), h('span', {class: 'small', text: META.option('ai_systems', 'risk_class', k)}))));
  const search = h('input', {type: 'search', id: 'aiSearch', placeholder: 'Sistem, amaç veya tedarikçi ara', 'aria-label': 'Ara'});
  search.addEventListener('input', () => { state.q = search.value.trim().toLocaleLowerCase(TR); draw(); });
  const gapBox = h('input', {type: 'checkbox', id: 'aiGaps'}); gapBox.addEventListener('change', () => { state.gapsOnly = gapBox.checked; draw(); });
  const tableBox = h('div');
  const draw = () => {
    dist.querySelectorAll('.ai-dist-item').forEach((b, i) => { const on = AI.classes[i] === state.cls; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
    const shown = d.systems.filter(s => (!state.cls || s.risk_class === state.cls) && (!state.gapsOnly || s.gap_count) &&
      (!state.q || `${s.code} ${s.name} ${s.purpose} ${s.supplier_name || ''}`.toLocaleLowerCase(TR).includes(state.q)));
    fillEl(tableBox, shown.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Sistem', 'Risk sınıfı', 'Rol / kaynak', 'Yaşam döngüsü', 'Veri', 'Açık'].map(x => h('th', {text: x})))),
      h('tbody', {}, shown.map(s => { const tr = h('tr', {class: 'clickable' + (s.lifecycle === 'retired' ? ' muted' : ''), tabindex: '0', onclick: () => Router.go('aisystem/' + s.id)},
        h('td', {class: 'cell-primary'}, s.name, h('span', {class: 'cell-sub', text: `${s.code} · ${s.purpose}`})),
        h('td', {}, aiClassPill(s.risk_class)),
        h('td', {class: 'small'}, META.option('ai_systems', 'role', s.role).split(' (')[0], h('span', {class: 'cell-sub', text: [META.option('ai_systems', 'source_type', s.source_type), s.supplier_name, s.gpai_based ? 'genel amaçlı model' : null].filter(Boolean).join(' · ')})),
        h('td', {class: 'small', text: META.option('ai_systems', 'lifecycle', s.lifecycle)}),
        h('td', {}, h('div', {class: 'chips'}, s.personal ? pill('Kişisel veri', 'warn') : null, s.automated_decision ? pill('Otomatik karar', 'purple') : null,
          s.tables ? h('span', {class: 'muted small', text: `${s.tables} tablo`}) : null)),
        h('td', {}, s.gap_count ? pill(`${s.gap_count} açık`, AI.sev[s.top_severity]) : pill('Açık yok', 'good')));
      tr.addEventListener('keydown', e => { if (e.key === 'Enter') Router.go('aisystem/' + s.id); }); return tr; })))) :
      empty('Eşleşen sistem yok', 'Filtreyi değiştirin.'));
  };
  draw();
  content(top, h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Sistemler'}), h('div', {class: 'toolbar pt-tools'}, search, h('label', {class: 'toggle', for: 'aiGaps'}, gapBox, 'Yalnızca açığı olanlar'))),
    dist, tableBox), timeline);
};

DETAILS.ai_systems = id => Router.go('aisystem/' + id);
PAGES.aisystem = async function aiSystemPage(parts) {
  const r = await api(`ai_systems/${Number(parts[1])}/context`); const s = r.system; const reload = () => render();
  setPage(s.name, `${s.code} · ${s.purpose}`, [
    r.can_write ? btn('Sınıflandır', () => aiClassifyDialog(s, r.questions, r.classification, reload)) : null,
    r.can_write ? btn('Düzenle', () => aiForm(s, reload), 'secondary') : null,
    r.can_write ? btn('Veri varlıkları', () => aiTablesDialog(s, r.tables, reload), 'secondary') : null], [['Yapay Zekâ Envanteri', 'ai']]);
  const link = (x, route, text) => x ? h('a', {href: '#/' + route, text}) : null;
  const facts = kv([['Risk sınıfı', aiClassPill(s.risk_class)], s.classified_at ? ['Sınıflandıran', `${s.classified_by} · ${fmt.datetime(s.classified_at)}`] : null,
    ['Kurumun rolü', META.option('ai_systems', 'role', s.role)], ['Kaynağı', META.option('ai_systems', 'source_type', s.source_type)],
    r.supplier ? ['Tedarikçi', link(r.supplier, 'r/suppliers/' + r.supplier.id, r.supplier.name)] : null,
    ['Model', [s.model_type ? META.option('ai_systems', 'model_type', s.model_type) : null, s.gpai_based ? 'genel amaçlı modele dayanıyor' : null].filter(Boolean).join(' · ') || null],
    ['Kurulum', s.deployment ? META.option('ai_systems', 'deployment', s.deployment) : null], ['Yaşam döngüsü', META.option('ai_systems', 'lifecycle', s.lifecycle)],
    ['İş sahibi', personText(s.owner)], ['Teknik sorumlu', personText(s.technical_owner)],
    r.process ? ['Süreç', `${r.process.code || ''} ${r.process.name}`.trim()] : null, r.org_unit ? ['Birim', r.org_unit.name] : null, r.ci ? ['CMDB öğesi', r.ci.name] : null,
    s.affected_persons ? ['Etkilenen kişiler', s.affected_persons] : null, s.description ? ['Açıklama', s.description] : null]);
  const governance = kv([['Kişisel veri', s.uses_personal_data ? (s.uses_special_data ? pill('Özel nitelikli dâhil', 'bad') : pill('İşliyor', 'warn')) : 'İşaretli değil'],
    ['Otomatik karar', s.automated_decision ? pill('Kişi hakkında otomatik karar', 'purple') : 'Yok'], ['İnsan gözetimi', s.human_oversight || null],
    ['Şeffaflık bildirimi', s.transparency_notice ? pill('Bildiriliyor', 'good') : 'İşaretli değil'], ['Kayıt saklama', s.log_retention_months !== null && s.log_retention_months !== undefined ? `${s.log_retention_months} ay` : null],
    ['İşleme faaliyeti', r.activity ? link(r.activity, 'activity/' + r.activity.id, `${r.activity.code} ${r.activity.name}`) : null],
    ['VKED', r.dpia ? h('span', {}, link(r.dpia, 'r/dpias/' + r.dpia.id, `${r.dpia.code} ${r.dpia.title}`), ' ', pill(META.option('dpias', 'status', r.dpia.status), r.dpia.status === 'approved' ? 'good' : 'neutral')) : null],
    ['FRIA', s.fria_done_on ? fmt.date(s.fria_done_on) : null], ['Son değerlendirme', s.last_evaluated_on ? fmt.date(s.last_evaluated_on) : null],
    s.evaluation_summary ? ['Değerlendirme özeti', s.evaluation_summary] : null, s.monitoring ? ['İzleme', s.monitoring] : null,
    ['Gözden geçirme', s.review_date ? fmt.date(s.review_date) : null]]);
  const cls = r.classification;
  const obligations = cls ? h('div', {}, section('Dayanak', h('ul', {class: 'mini plain'}, cls.basis.map(b => h('li', {class: 'small', text: b})))),
    section(`Yükümlülükler (${cls.obligations.length})`, h('ul', {class: 'mini'}, cls.obligations.map(o => h('li', {}, h('strong', {text: o.ref + ' '}), h('span', {text: o.text}))))),
    cls.fria_required ? h('div', {class: 'notice warn small', text: 'Temel haklara etki değerlendirmesi (md. 27) gerekli.'}) : null) :
    h('div', {}, h('p', {class: 'small muted', text: 'Sistem henüz sınıflandırılmadı. Sihirbaz yedi soruyla risk sınıfını, dayanak maddeleri ve kurumun rolüne göre yükümlülükleri belirler.'}),
      r.can_write ? btn('Sınıflandırma sihirbazı', () => aiClassifyDialog(s, r.questions, null, reload)) : null);
  const tables = r.tables.length ? h('div', {class: 'tablewrap plain'}, h('table', {}, h('thead', {}, h('tr', {}, ['Veri varlığı', 'Kullanım', 'Sınıf', 'Kişisel veri'].map(x => h('th', {text: x})))),
    h('tbody', {}, r.tables.map(t => h('tr', {class: 'link', onclick: () => Router.go('catalog/table/' + t.table_id)},
      h('td', {class: 'cell-primary'}, dgPath(t.schema_name, t.name), h('span', {class: 'cell-sub', text: [t.source_name, t.business_name].filter(Boolean).join(' · ')})),
      h('td', {class: 'small', text: META.option('ai_system_tables', 'usage', t.usage)}), h('td', {}, classPill(t.classification)),
      h('td', {}, t.special ? pill('Özel nitelikli', 'bad') : t.personal ? pill(`${t.personal} kolon`, 'warn') : h('span', {class: 'muted', text: 'Yok'}))))))) :
    h('div', {class: 'muted small', text: 'Bağlı veri varlığı yok. "Veri varlıkları" ile eğitim ve girdi tablolarını bağlayın.'});
  content(h('div', {class: 'grid wide-left'},
    h('div', {}, panel('Açıklar', aiGapList(r.gaps), null, r.gaps.length ? `${r.gaps.length} açık` : ''), panel('AB Yapay Zekâ Tüzüğü', obligations, null, 'Tüzük (AB) 2024/1689'),
      panel('Veri varlıkları', tables, r.can_write ? btn('Düzenle', () => aiTablesDialog(s, r.tables, reload), 'ghost small') : null)),
    h('div', {}, panel('Sistem', facts), panel('KVKK / GDPR ve gözetim', governance))));
};

TABLE_EXTRAS.push(t => {
  const host = h('div');
  api(`data_tables/${t.id}/ai-systems`).then(items => {
    if (!items.length) return;
    fillEl(host, h('div', {class: 'notice small ai-notice'}, h('strong', {text: 'Yapay zekâ sistemleri bu tabloyu kullanıyor: '}),
      items.map((x, i) => [i ? ', ' : '', h('a', {href: '#/aisystem/' + x.id, text: `${x.code} ${x.name}`}), ` (${META.option('ai_system_tables', 'usage', x.usage)}, ${META.option('ai_systems', 'risk_class', x.risk_class)})`])));
  }).catch(() => {});
  return host;
});
SUPPLIER_TABS.push({key: 'ai', label: 'Yapay zekâ', visible: () => hasModule('datagov'), render: async id => {
  const items = (await api(`ai_systems?supplier_id=${id}&limit=200`)).items || [];
  return items.length ? h('ul', {class: 'mini'}, items.map(s => h('li', {class: 'link', onclick: () => { Drawer.close(); Router.go('aisystem/' + s.id); }},
    h('div', {class: 'chips'}, h('strong', {text: `${s.code} · ${s.name}`}), aiClassPill(s.risk_class)), h('span', {class: 'cell-sub', text: s.purpose})))) :
    h('div', {class: 'muted small', text: 'Bu tedarikçiden sağlanan kayıtlı yapay zekâ sistemi yok.'});
}});

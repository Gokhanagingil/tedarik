'use strict';
/* GRC platformu ekranları: genel bakış, İşlerim, GRC takvimi, sağlık kontrolü, risk / süreklilik / CMDB panoları,
   süreç haritası, ilişki haritası, komut paleti ve BİA, plan, tatbikat, doküman, CI, KRİ, dönem, süreç, hedef, madde
   detayları. app.js yardımcılarını kullanır; dış kütüphane yok, satır içi stil yok (CSP). */

// ------------------------------------------------------------------ ortak parçalar
const hasModule = m => S.meta.modules.includes(m);
const canWrite = res => !!META.def(res)?.can_write;
async function maybe(promise) { try { return await promise; } catch (e) { return null; } }
function iso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function parseDay(v) { return new Date(String(v).slice(0, 10) + 'T00:00:00'); }
function levelOf(score, bounds) {
  if (score === null || score === undefined) return null;
  const b = bounds || {low: 4, medium: 9, high: 15, critical: 25};
  return score <= b.low ? 'low' : score <= b.medium ? 'medium' : score <= b.high ? 'high' : 'critical';
}
function levelPill(level) { return level ? pill(META.option('supplier_risks', 'risk_level', level), 'level-' + level) : pill('Değerlendirilmedi', 'neutral'); }
function sizeText(n) { if (n === null || n === undefined) return '—'; return n < 1024 ? `${n} bayt` : n < 1048576 ? `${fmt.num(n / 1024, 1)} KB` : `${fmt.num(n / 1048576, 1)} MB`; }
function late(d) { return d && String(d).slice(0, 10) < today(); }
function dueText(d) {
  if (!d) return '';
  const days = Math.round((parseDay(d) - parseDay(today())) / 86400000);
  return days === 0 ? 'bugün' : days < 0 ? `${-days} gün gecikti` : `${days} gün kaldı`;
}
function openAny(resource, id) {
  if (resource === 'audits') return Router.go('audit/' + id);
  if (resource === 'survey_campaigns') return Router.go('surveys/' + id);
  return openRecord(resource, id);
}
/** Kayıt listesi (detay panellerinde): her satır kaydı açar. */
function recordList(res, items, {sub, chips, none = 'Kayıt yok', open} = {}) {
  if (!items || !items.length) return h('div', {class: 'muted small', text: none});
  return h('ul', {class: 'mini'}, items.map(it => {
    const li = h('li', {class: 'link', tabindex: '0'}, h('strong', {text: [it.code, it.name || it.title].filter(Boolean).join(' · ')}),
      sub ? h('span', {class: 'cell-sub', text: sub(it)}) : null, chips ? h('div', {class: 'chips'}, chips(it)) : null);
    const go = () => (open ? open(it) : openRecord(res, it.id));
    li.addEventListener('click', go); li.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
    return li;
  }));
}
function pickMany(title, items, selected, {label = titleOf, group, intro} = {}) {
  return new Promise(resolve => {
    const box = checklist(items, selected, {label, group});
    Modal.open(title, h('div', {}, intro ? h('p', {class: 'intro', text: intro}) : null, box.node), [
      btn('Vazgeç', () => { Modal.close(); resolve(null); }, 'secondary'),
      btn('Kaydet', () => { const v = box.value(); Modal.close(); resolve(v); })], true);
  });
}
function statStrip(items) {
  return h('div', {class: 'stat-strip'}, items.filter(Boolean).map(([label, value, cls]) =>
    h('div', {class: 'stat ' + (cls || '')}, h('span', {class: 'stat-value', text: value}), h('span', {class: 'stat-label', text: label}))));
}
function panel(title, body, action, sub) {
  return h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {}, title, sub ? h('span', {class: 'sub', text: '  ' + sub}) : null), action || null), body);
}
function heatMap(heat, bounds, onclick) {
  const grid = h('div', {class: 'heat', role: 'grid', 'aria-label': 'Risk ısı haritası'});
  for (let l = 5; l >= 1; l--) {
    grid.append(h('span', {class: 'ax', text: l}));
    for (let i = 1; i <= 5; i++) {
      const n = heat[l - 1][i - 1]; const level = levelOf(l * i, bounds);
      const cell = h(onclick && n ? 'button' : 'span', {class: `cell l-${level}${n ? '' : ' zero'}`, type: onclick && n ? 'button' : null,
        title: `Olasılık ${l} × etki ${i} = ${l * i}: ${n} risk`, text: n || '·'});
      if (onclick && n) cell.addEventListener('click', () => onclick(l, i));
      grid.append(cell);
    }
  }
  grid.append(h('span'));
  for (let i = 1; i <= 5; i++) grid.append(h('span', {class: 'ax', text: i}));
  return h('div', {}, grid, h('div', {class: 'heat-caption', text: 'Dikey: olasılık · yatay: etki (içsel risk). Hücreye tıklayarak riskleri listeleyin.'}));
}
function sparkline(values, {amber, red, direction = 'higher_worse', width = 460, height = 120} = {}) {
  const pts = values.filter(v => v.value !== null && v.value !== undefined);
  if (!pts.length) return h('div', {class: 'muted small', text: 'Ölçüm yok'});
  const all = pts.map(p => Number(p.value)).concat([amber, red].filter(x => x !== undefined && x !== null).map(Number));
  let lo = Math.min(...all), hi = Math.max(...all); if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const x = i => 30 + (pts.length === 1 ? (width - 40) / 2 : i * (width - 40) / (pts.length - 1));
  const y = v => 10 + (height - 30) * (1 - (v - lo) / (hi - lo));
  const svg = s('svg', {class: 'chart spark', viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': pts.map(p => `${fmt.date(p.period)}: ${p.value}`).join(', ')});
  for (const [v, cls, text] of [[amber, 'th-amber', 'sarı'], [red, 'th-red', 'kırmızı']]) {
    if (v === undefined || v === null) continue;
    svg.append(s('line', {x1: 26, x2: width - 6, y1: y(v), y2: y(v), class: cls}), s('text', {x: width - 8, y: y(v) - 4, 'text-anchor': 'end', class: 'th-label'}, `${text} ${fmt.num(v, 2)}`));
  }
  svg.append(s('polyline', {points: pts.map((p, i) => `${x(i)},${y(Number(p.value))}`).join(' '), class: 'spark-line'}));
  pts.forEach((p, i) => svg.append(s('circle', {cx: x(i), cy: y(Number(p.value)), r: 3.5, class: 'spark-dot s-' + (p.status || 'none')},
    s('title', {}, `${fmt.date(p.period)}: ${fmt.num(p.value, 2)}`))));
  svg.append(s('text', {x: 30, y: height - 4, class: 'th-label'}, fmt.date(pts[0].period)),
    s('text', {x: width - 10, y: height - 4, 'text-anchor': 'end', class: 'th-label'}, fmt.date(pts[pts.length - 1].period)));
  return svg;
}
const KRI_TONE = {green: 'good', amber: 'warn', red: 'bad'};
function nextPeriod(last) {           // ölçüm dönemi ayın ilk günü; bu ay ölçüldüyse sonraki ay önerilir
  const month = today().slice(0, 8) + '01';
  if (!last || String(last).slice(0, 10) < month) return month;
  const d = parseDay(String(last).slice(0, 10)); return iso(new Date(d.getFullYear(), d.getMonth() + 1, 1));
}
const KRI_TEXT = {green: 'Yeşil', amber: 'Sarı', red: 'Kırmızı'};

// ------------------------------------------------------------------ genel bakış (yönetici özeti)
PAGES.home = async function overview() {
  if (S.me.external) { Router.go('r/audits'); return; }       // dış denetçi: yalnızca atanmış denetimler
  setPage('Genel Bakış', 'Risk, uyum, iş sürekliliği, doküman, varlık ve tedarikçi alanlarının tek ekranda özeti. Kartlar ilgili ekranı açar.');
  content(h('div', {class: 'empty', text: 'Yükleniyor…'}));
  const start = today(); const end = today(30);
  const [sum, risk, grc, bcm, docs, cmdb, health, work, cal] = await Promise.all([
    hasModule('dashboard') ? maybe(api('dashboard/summary')) : null, hasModule('risks') ? maybe(api('risks/overview')) : null,
    hasModule('grc') ? maybe(api('grc/overview')) : null, hasModule('continuity') ? maybe(api('bcm/overview')) : null,
    hasModule('documents') ? maybe(api('documents-overview')) : null, hasModule('cmdb') ? maybe(api('cmdb/status')) : null,
    hasModule('insights') ? maybe(api('health-check')) : null, hasModule('insights') ? maybe(api('my-work')) : null,
    hasModule('insights') ? maybe(api(`calendar?from=${start}&to=${end}`)) : null]);
  const hour = new Date().getHours(); const name = (S.me.display_name || S.me.username).split(' ')[0];
  const hero = h('div', {class: 'hero'},
    h('div', {class: 'hero-text'}, h('div', {class: 'hero-kicker', text: new Date().toLocaleDateString(TR, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'})}),
      h('h2', {text: `${hour < 12 ? 'Günaydın' : hour < 18 ? 'İyi günler' : 'İyi akşamlar'}, ${name}`}),
      h('p', {text: work ? (work.total ? `Size atanmış ${work.total} açık iş var${work.overdue ? `, ${work.overdue} tanesinin tarihi geçti` : ''}.` : 'Size atanmış açık iş yok.') : 'Kurumun GRC durumunun özeti aşağıda.'}),
      h('div', {class: 'filters'}, work ? btn('İşlerim', () => Router.go('my-work'), '') : null, hasModule('insights') ? btn('GRC takvimi', () => Router.go('calendar'), 'secondary') : null,
        btn('Hızlı arama  Ctrl K', () => openPalette(), 'secondary'))),
    health ? h('button', {type: 'button', class: 'hero-score', onclick: () => Router.go('health'), title: 'GRC sağlık kontrolünü aç'},
      gauge(health.score, 'GRC sağlık puanı', {good: 80, mid: 55, sub: `${health.checks.filter(c => c.count).length} kontrolde iyileştirme alanı`})) : null);
  const blocks = [hero];
  const domain = (title, cards) => { const c = cards.filter(Boolean); if (c.length) blocks.push(h('div', {class: 'domain', text: title}), h('div', {class: 'cards'}, c)); };
  if (risk) {
    const high = (risk.levels.high || 0) + (risk.levels.critical || 0); const red = (risk.kri.find(k => k.key === 'red') || {}).count || 0;
    domain('Kurumsal risk', [
      metric('Açık risk', fmt.num(risk.total, 0), `${risk.by_company.length} şirket · ${risk.opportunities} fırsat`, '', () => Router.go('risk')),
      metric('Yüksek ve kritik', fmt.num(high, 0), `${risk.levels.critical || 0} kritik seviyede`, high ? 'bad' : 'good', () => Router.go('r/supplier_risks?risk_level=critical')),
      metric('İştah üstü', fmt.num(risk.above_appetite, 0), `${risk.unassessed} risk değerlendirilmedi`, risk.above_appetite ? 'bad' : 'good', () => Router.go('risk')),
      metric('Kırmızı KRİ', fmt.num(red, 0), `${risk.actions_overdue} işleme faaliyeti gecikti`, red ? 'bad' : 'good', () => Router.go('r/kris?last_status=red'))]);
  }
  if (grc) domain('Uyum ve denetim', [
    metric('Kontrol başarı oranı', fmt.pct(grc.controls.pass_pct), `${grc.controls.completed} test · ${grc.controls.overdue_tests} gecikmiş`,
      grc.controls.pass_pct === null ? '' : grc.controls.pass_pct >= 85 ? 'good' : grc.controls.pass_pct >= 60 ? 'warn' : 'bad', () => Router.go('compliance')),
    metric('Açık bulgu', fmt.num(grc.findings_open, 0), `${grc.findings_overdue} hedef tarihi geçmiş`, grc.findings_open ? 'warn' : 'good', () => Router.go('r/findings')),
    metric('Geciken DÖF', fmt.num(grc.actions_overdue, 0), `${grc.actions_validation} etkinlik doğrulaması bekliyor`, grc.actions_overdue ? 'bad' : 'good', () => Router.go('r/grc_actions')),
    metric('Süren denetim', fmt.num(grc.audits_active.filter(x => x.status === 'in_progress').length, 0), `${grc.audits_active.length} planlı veya süren`, '', () => Router.go('r/audits'))]);
  if (bcm) domain('İş sürekliliği', [
    metric('BİA kapsamı', fmt.pct(bcm.coverage_pct), `${bcm.processes_with_bia} / ${bcm.processes} ana süreç`, bcm.coverage_pct >= 80 ? 'good' : bcm.coverage_pct >= 40 ? 'warn' : 'bad', () => Router.go('bcm')),
    metric('Tatbikatı geciken plan', fmt.num(bcm.plans_not_exercised.length, 0), `Son ${bcm.exercise_months} ayda tatbikat yok`, bcm.plans_not_exercised.length ? 'warn' : 'good', () => Router.go('bcm')),
    metric('RTO açığı', fmt.num(bcm.rto_gaps.length, 0), 'Tatbikatta hedef süre aşıldı', bcm.rto_gaps.length ? 'bad' : 'good', () => Router.go('r/bc_exercises?status=completed')),
    metric('Yaklaşan tatbikat', fmt.num(bcm.exercises_planned.length, 0), bcm.exercises_planned[0] ? `İlki ${fmt.date(bcm.exercises_planned[0].planned_date)}` : 'Planlı tatbikat yok', '', () => Router.go('r/bc_exercises?status=planned'))]);
  const docCount = docs ? Object.fromEntries(docs.by_status.map(x => [x.key, x.count])) : {};
  const exposures = cmdb ? cmdb.exposures.reduce((a, x) => a + x.count, 0) : 0;
  domain('Doküman ve varlık', [
    docs ? metric('Yürürlükteki doküman', fmt.num(docCount.published || 0, 0), `${docCount.draft || 0} taslak · ${docCount.in_review || 0} onayda`, '', () => Router.go('r/documents?status=published')) : null,
    docs ? metric('Gözden geçirmesi geçen', fmt.num(docs.review_overdue.length, 0), 'ISO 9001 7.5.2 gözden geçirme', docs.review_overdue.length ? 'warn' : 'good', () => Router.go(`r/documents?status=published&review_date__lte=${today(-1)}`)) : null,
    cmdb ? metric('Konfigürasyon öğesi', fmt.num(cmdb.total, 0), cmdb.servicenow.configured ? 'ServiceNow bağlı' : 'ServiceNow bağlantısı yapılandırılmadı', '', () => Router.go('cmdb')) : null,
    cmdb ? metric('Açık CI maruziyeti', fmt.num(exposures, 0), 'Destek dışı, yama, yeniden başlatma', exposures ? 'bad' : 'good', () => Router.go('r/ci_exposures?status=open')) : null]);
  if (sum) {
    const tier = Object.fromEntries(sum.suppliers.by_tier.map(x => [x.key, x.count]));
    domain('Tedarikçi yönetimi', [
      metric('Tedarikçiler', fmt.num(sum.suppliers.total, 0), `${tier.critical || 0} kritik · ${tier.important || 0} önemli`, '', () => Router.go('r/suppliers')),
      metric('90 gün içinde biten sözleşme', fmt.num(sum.contracts_ending_90d, 0), 'Yenileme veya çıkış kararı', sum.contracts_ending_90d ? 'warn' : 'good',
        () => Router.go(`r/contracts?status=active&end_date__gte=${today()}&end_date__lte=${today(90)}`)),
      sum.sla_90d ? metric('SLA başarısı (son 3 ay)', sum.sla_90d.rate === null ? '—' : fmt.pct(sum.sla_90d.rate), `${sum.sla_90d.met} / ${sum.sla_90d.total} ölçüm`,
        sum.sla_90d.rate === null ? '' : sum.sla_90d.rate >= 95 ? 'good' : sum.sla_90d.rate >= 85 ? 'warn' : 'bad', () => Router.go('r/sla_measurements')) : null,
      metric('Sahibi olmayan tedarikçi', fmt.num(sum.suppliers.without_owner, 0), 'İlişki sahibi atanmalı', sum.suppliers.without_owner ? 'warn' : 'good', () => Router.go('r/suppliers?owner__null=1&status=active'))]);
  }
  const upcoming = cal ? cal.events.filter(e => (e.start || '') >= start).sort((a, b) => a.start.localeCompare(b.start)).slice(0, 9) : [];
  const agendaPanel = cal ? panel('Önümüzdeki 30 gün', upcoming.length ? h('ul', {class: 'agenda'}, upcoming.map(e => h('li', {onclick: () => openAny(e.resource, e.id)},
    h('span', {class: 'date', text: fmt.date(e.start)}), h('span', {}, h('i', {class: 'dot t-' + e.type}), e.title), h('span', {class: 'muted small', text: e.type_label}))))
    : empty('Yaklaşan iş yok', ''), btn('Takvim', () => Router.go('calendar'), 'ghost small')) : null;
  const checks = health ? health.checks.filter(c => c.count).slice(0, 7) : [];
  const healthPanel = health ? panel('Öncelikli iyileştirme alanları', checks.length ? h('ul', {class: 'attention'}, checks.map(c => h('li', {},
    h('span', {}, h('span', {class: `sevc sevc-${c.severity}`, text: c.count}), ' ', c.title), h('a', {href: '#/health?open=' + c.key, class: 'btn ghost small', text: 'Aç →'}))))
    : h('div', {class: 'notice success', text: 'Sağlık kontrollerinde açık konu yok.'}), btn('Tümü', () => Router.go('health'), 'ghost small')) : null;
  if (agendaPanel || healthPanel) blocks.push(h('div', {class: 'grid two'}, agendaPanel, healthPanel));
  if (risk) blocks.push(h('div', {class: 'grid two'},
    panel('Risk ısı haritası', heatMap(risk.heat, risk.level_bounds, (l, i) => Router.go(`r/supplier_risks?likelihood=${l}&impact=${i}`)), btn('Risk panosu', () => Router.go('risk'), 'ghost small')),
    panel('Şirket bazında açık risk', barChart(risk.by_company.map(c => ({label: c.name, value: c.count, color: c.kind === 'own' ? 0 : 4, id: c.id})),
      {format: v => fmt.num(v, 0), onclick: item => Router.go('risk?company_id=' + item.id)}), null, 'koyu: kendi şirketlerimiz · mor: müşteriler')));
  content(...blocks);
};

// ------------------------------------------------------------------ İşlerim
const WORK_GROUPS = [
  ['risks', 'Gözden geçirmem gereken riskler', 'supplier_risks', r => [levelPill(r.risk_level), r.last_assessed_at ? null : pill('Değerlendirilmedi', 'warn')], 'review_date'],
  ['risk_actions', 'Risk işleme faaliyetlerim', 'risk_actions', r => [display('risk_actions', 'status', r.status)], 'due_date'],
  ['findings', 'Bana atanmış bulgular', 'findings', r => [display('findings', 'severity', r.severity), display('findings', 'status', r.status)], 'due_date'],
  ['capa', 'Düzeltici faaliyetlerim (DÖF)', 'grc_actions', r => [display('grc_actions', 'status', r.status)], 'due_date'],
  ['capa_validation', 'Etkinlik doğrulaması bekleyen DÖF', 'grc_actions', r => [h('span', {class: 'chip', text: 'Sahibi: ' + r.owner})], 'due_date'],
  ['documents_to_approve', 'Onayımı bekleyen dokümanlar', 'documents', r => [h('span', {class: 'chip', text: 'Hazırlayan: ' + (r.prepared_by || '—')})], null],
  ['documents_to_review', 'Gözden geçirme zamanı gelen dokümanlarım', 'documents', () => [], 'review_date'],
  ['bias_to_approve', 'Onay bekleyen İş Etki Analizleri', 'bias', r => [h('span', {class: 'chip', text: 'Sahibi: ' + r.owner})], null],
  ['bias_to_review', 'Gözden geçirme zamanı gelen BİA\'larım', 'bias', () => [], 'review_date'],
  ['evidence_requests', 'Benden istenen kanıtlar', 'evidence_requests', r => [display('evidence_requests', 'status', r.status)], 'due_date'],
  ['finding_responses', 'Yönetim yanıtı beklenen bulgularım', 'findings', r => [display('findings', 'severity', r.severity)], 'due_date'],
  ['crisis_tasks', 'Kriz görevlerim', 'bc_incident_tasks', r => [pill(META.option('bc_incident_tasks', 'phase', r.phase), 'bad')], null],
  ['breaches', 'Sorumlusu olduğum kişisel veri ihlalleri', 'privacy_breaches', () => [pill('72 saat', 'bad')], null],
  ['rcsa', 'Öz değerlendirme yanıtlarım', 'rcsa_items', r => [pill(META.option('rcsa_items', 'item_type', r.item_type), 'neutral')], 'due_date'],
  ['access_reviews', 'Erişim gözden geçirmelerim', 'access_reviews', r => [h('span', {class: 'chip', text: r.system})], 'due_date'],
  ['attestations', 'Okundu beyanı bekleyen politikalar', 'attestations', () => [pill('Beyan bekleniyor', 'warn')], 'due_date'],
  ['evidence_to_review', 'İncelememi bekleyen kanıtlar', 'evidence_requests', r => [h('span', {class: 'chip', text: 'Teslim eden: ' + r.assignee})], 'due_date'],
  ['workpapers_to_review', 'Gözden geçirmemi bekleyen çalışma kâğıtları', 'workpapers', r => [h('span', {class: 'chip', text: 'Hazırlayan: ' + (r.preparer || '—')})], null],
  ['exceptions_to_approve', 'Onayımı bekleyen politika istisnaları', 'policy_exceptions', r => [display('policy_exceptions', 'risk_level', r.risk_level)], 'due_date'],
  ['glossary_to_approve', 'Onayımı bekleyen sözlük terimleri', 'glossary_terms', r => [pill(r.kind === 'change' ? 'Değişiklik önerisi' : 'Yeni terim', 'purple'), h('span', {class: 'chip', text: 'Öneren: ' + (r.proposer || '—')})], null],
  ['glossary_returned', 'İade edilen sözlük terimlerim', 'glossary_terms', r => [h('span', {class: 'chip', text: (r.review_note || '').slice(0, 80)})], null],
  ['glossary_review', 'Gözden geçirme zamanı gelen terimlerim', 'glossary_terms', () => [], 'review_date'],
  ['subject_requests', 'İlgili kişi başvurularım (30 gün)', 'subject_requests', r => [display('subject_requests', 'request_type', r.title)], 'due_date'],
  ['data_requests_to_approve', 'Onayımı bekleyen veri talepleri', 'data_requests', r => [h('span', {class: 'chip', text: 'Talep eden: ' + (r.requested_by || '—')})], null],
  ['data_requests_to_fulfill', 'Uygulamamı bekleyen veri talepleri', 'data_requests', () => [pill('Onaylandı', 'good')], null],
  ['dpias_to_approve', 'Onayımı bekleyen VKED', 'dpias', () => [], null],
  ['disposals', 'Periyodik imha işlerim', 'disposal_runs', () => [], 'due_date'],
  ['pii_suggestions', 'Kişisel veri keşfi', 'pii_suggestions', () => [pill('Karar bekliyor', 'warn')], null],
  ['dq_failing', 'Başarısız veri kalitesi kurallarım', 'dq_rules', r => [pill(r.last_result === 'error' ? 'Çalışmadı' : 'Başarısız', 'bad'), r.last_message ? h('span', {class: 'chip', text: String(r.last_message).slice(0, 80)}) : null], null],
  ['collectors_attention', 'İlgilenmem gereken toplayıcılar', 'data_collectors', r => [pill(r.state === 'error' ? 'Hata' : 'Gecikti', r.state === 'error' ? 'bad' : 'warn')], null],
  ['ai_systems', 'Yapay zekâ sistemlerim', 'ai_systems', r => [h('span', {class: 'chip', text: String(r.detail || '').slice(0, 90)})], null],
  ['exercises', 'Yöneteceğim tatbikatlar', 'bc_exercises', () => [], 'planned_date'],
  ['surveys', 'Yanıt bekleyen anketler', 'survey_campaigns', () => [], 'closes_on'],
  ['controls', 'Sahibi olduğum kontroller', 'controls', () => [], null],
];
PAGES['my-work'] = async function myWork() {
  setPage('İşlerim', 'Size atanmış açık işler: riskler, faaliyetler, bulgular, onaylar ve gözden geçirmeler. Tarihi geçenler kırmızıdır.');
  const w = await api('my-work'); S.myWork = w.total; navigation();
  const groups = WORK_GROUPS.filter(([key]) => (w[key] || []).length);
  const strip = statStrip([['Açık iş', fmt.num(w.total, 0)], ['Tarihi geçen', fmt.num(w.overdue, 0), w.overdue ? 'bad' : 'good'],
    ['Onay bekleyen', fmt.num(['documents_to_approve', 'bias_to_approve', 'capa_validation', 'evidence_to_review', 'workpapers_to_review', 'exceptions_to_approve', 'glossary_to_approve', 'data_requests_to_approve', 'dpias_to_approve'].reduce((n, k) => n + (w[k] || []).length, 0), 0)],
    ['Gözden geçirme', fmt.num((w.risks || []).length + (w.documents_to_review || []).length + (w.bias_to_review || []).length, 0)]]);
  if (!groups.length) { content(strip, empty('Bekleyen işiniz yok', 'Size atanmış açık bir kayıt bulunmuyor.')); return; }
  content(strip, h('div', {class: 'work'}, groups.map(([key, title, res, chips, dateKey]) => panel(title, h('ul', {class: 'mini'}, w[key].map(r => {
    const d = dateKey ? r[dateKey] : null;
    const li = h('li', {class: 'link', tabindex: '0'}, d ? h('span', {class: 'due' + (late(d) ? ' late' : ''), text: fmt.date(d) + ' · ' + dueText(d)}) : null,
      h('strong', {text: [r.code, r.title || r.name].filter(Boolean).join(' · ')}), h('div', {class: 'chips'}, chips(r)));
    const go = () => (res === 'survey_campaigns' ? Router.go('my-surveys') : res === 'attestations' && typeof acknowledgeDialog === 'function' ? acknowledgeDialog(r)
      : res === 'rcsa_items' && typeof rcsaRespond === 'function' ? rcsaRespond(r, render) : res === 'bc_incident_tasks' ? Router.go('crisis/' + r.incident_id)
      : res === 'pii_suggestions' ? Router.go('discovery') : openRecord(res, r.id));
    li.addEventListener('click', go); li.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
    return li;
  })), null, String(w[key].length)))));
};

// ------------------------------------------------------------------ GRC takvimi
S.calHidden = S.calHidden || new Set();
PAGES.calendar = async function calendarPage(parts, params) {
  const month = /^\d{4}-\d{2}$/.test(params.get('m') || '') ? params.get('m') : today().slice(0, 7);
  const view = params.get('v') === 'list' ? 'list' : 'month';
  const [y, m] = month.split('-').map(Number); const first = new Date(y, m - 1, 1);
  const gridStart = addDays(first, -((first.getDay() + 6) % 7)); const gridEnd = addDays(gridStart, 41);
  const go = (mm, v = view) => Router.go(`calendar?m=${mm}${v === 'list' ? '&v=list' : ''}`);
  const shift = n => { const d = new Date(y, m - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; };
  setPage('GRC Takvimi', 'Denetimler, tatbikatlar, risk değerlendirme dönemleri, kontrol testleri, gözden geçirmeler ve hedef tarihler tek takvimde.', [
    btn('Bugün', () => go(today().slice(0, 7)), 'secondary'), btn(view === 'list' ? 'Ay görünümü' : 'Liste görünümü', () => go(month, view === 'list' ? 'month' : 'list'), 'secondary')]);
  const data = await api(`calendar?from=${iso(gridStart)}&to=${iso(gridEnd)}`);
  const title = first.toLocaleDateString(TR, {month: 'long', year: 'numeric'});
  // Yalnızca bu dönemde kaydı olan türler etiket olarak görünür; boş türler kalabalık yapmasın.
  const counts = {}; for (const e of data.events) counts[e.type] = (counts[e.type] || 0) + 1;
  const present = data.types.filter(t => counts[t.key]);
  const chips = h('div', {class: 'chips'});
  const drawChips = () => {
    const anyHidden = present.some(t => S.calHidden.has(t.key));
    chips.replaceChildren(...present.map(t => {
      const on = !S.calHidden.has(t.key);
      return h('button', {type: 'button', class: 'chip type-chip' + (on ? ' on' : ''), 'aria-pressed': String(on),
        onclick: () => { if (on) S.calHidden.add(t.key); else S.calHidden.delete(t.key); drawChips(); draw(); }},
        h('i', {class: 'dot t-' + t.key}), `${t.label} (${counts[t.key]})`);
    }), anyHidden ? btn('Tümünü göster', () => { present.forEach(t => S.calHidden.delete(t.key)); drawChips(); draw(); }, 'ghost small') : null);
  };
  drawChips();
  const host = h('div');
  const head = h('div', {class: 'cal-head'}, h('div', {class: 'filters'}, btn('‹', () => go(shift(-1)), 'secondary small', {'aria-label': 'Önceki ay'}),
    h('h2', {text: title.charAt(0).toLocaleUpperCase(TR) + title.slice(1)}), btn('›', () => go(shift(1)), 'secondary small', {'aria-label': 'Sonraki ay'})),
    h('span', {class: 'muted small', text: present.length ? 'Türe göre süzmek için etiketlere tıklayın' : ''}));
  const evButton = (e, suffix = '') => h('button', {type: 'button', class: 'ev t-' + e.type, title: `${e.type_label}: ${e.title}${e.end && e.end !== e.start ? ` (${fmt.date(e.start)} – ${fmt.date(e.end)})` : ''}`,
    onclick: () => openAny(e.resource, e.id)}, e.title + suffix);
  function draw() {
    const events = data.events.filter(e => !S.calHidden.has(e.type));
    if (view === 'list') {
      const inMonth = events.filter(e => (e.start || '').slice(0, 7) === month || (e.end || '').slice(0, 7) === month || ((e.start || '') < month && (e.end || '') > month))
        .sort((a, b) => a.start.localeCompare(b.start));
      host.replaceChildren(inMonth.length ? h('ul', {class: 'agenda'}, inMonth.map(e => h('li', {onclick: () => openAny(e.resource, e.id)},
        h('span', {class: 'date', text: fmt.date(e.start) + (e.end && e.end !== e.start ? ' –' : '')}),
        h('span', {}, h('i', {class: 'dot t-' + e.type}), e.title, e.end && e.end !== e.start ? h('span', {class: 'cell-sub', text: 'Bitiş ' + fmt.date(e.end)}) : null),
        h('span', {class: 'muted small', text: e.type_label})))) : empty('Bu ayda kayıt yok', 'Önceki veya sonraki aya geçin ya da süzgeci değiştirin.'));
      return;
    }
    const byDay = {};
    for (const e of events) {
      const s0 = parseDay(e.start); const e0 = e.end ? parseDay(e.end) : s0; const span = Math.round((e0 - s0) / 86400000);
      const put = (d, suffix) => { const k = iso(d); (byDay[k] = byDay[k] || []).push([e, suffix]); };
      if (span <= 0) put(s0, '');
      else if (span <= 10) for (let i = 0; i <= span; i++) put(addDays(s0, i), i === 0 ? '' : ' (devam)');
      else { put(s0, ' · başlangıç'); put(e0, ' · bitiş'); }
    }
    const cal = h('div', {class: 'cal'}, ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'].map(d => h('div', {class: 'dow', text: d})));
    for (let i = 0; i < 42; i++) {
      const d = addDays(gridStart, i); const key = iso(d); const items = byDay[key] || [];
      const cell = h('div', {class: 'day' + (d.getMonth() !== m - 1 ? ' other' : '') + (key === today() ? ' today' : '')}, h('span', {class: 'num', text: d.getDate()}));
      items.slice(0, 4).forEach(([e, suffix]) => cell.append(evButton(e, suffix)));
      if (items.length > 4) cell.append(h('button', {type: 'button', class: 'more', text: `+${items.length - 4} daha`, onclick: () =>
        Modal.open(fmt.date(key), h('ul', {class: 'agenda'}, items.map(([e]) => h('li', {onclick: () => { Modal.close(); openAny(e.resource, e.id); }},
          h('span', {class: 'date', text: e.type_label}), h('span', {}, h('i', {class: 'dot t-' + e.type}), e.title), h('span')))))}));
      cal.append(cell);
    }
    host.replaceChildren(h('div', {class: 'cal-scroll'}, cal));
  }
  draw();
  content(h('div', {class: 'panel'}, head, chips, h('br'), host));
};

// ------------------------------------------------------------------ GRC sağlık kontrolü
const SEV_LABEL = {critical: 'Kritik', high: 'Yüksek', medium: 'Orta', low: 'Düşük'};
PAGES.health = async function healthPage(parts, params) {
  setPage('GRC Sağlık Kontrolü', 'Kayıtlar arasındaki ilişkilerin bütünlüğü: kontrolsüz yüksek riskler, BİA\'sı olmayan ana süreçler, eşlenmemiş kontroller, gecikmiş gözden geçirmeler. Her bulgu nedenini ve etkilenen kayıtları gösterir.');
  const d = await api('health-check'); const opened = params.get('open');
  const bySev = sev => d.checks.filter(c => c.count && c.severity === sev).length;
  const summary = h('div', {class: 'grid wide-left'},
    h('div', {class: 'panel'}, h('div', {class: 'health-top'}, gauge(d.score, 'Sağlık puanı', {good: 80, mid: 55, sub: 'Ağırlıklı: kritik konular puanı daha çok düşürür'}),
      statStrip([['Kritik', bySev('critical'), bySev('critical') ? 'bad' : ''], ['Yüksek', bySev('high'), bySev('high') ? 'warn' : ''], ['Orta', bySev('medium')],
        ['Temiz', d.checks.filter(c => !c.count).length, 'good']]))),
    h('div', {class: 'panel'}, h('h3', {text: 'Nasıl okunur?'}), h('p', {class: 'intro', text: 'Her satır bir ilişki kuralıdır (ör. "yüksek risk en az bir kontrol veya işleme faaliyetiyle karşılanmalı"). Sayı, kuralı ihlal eden kayıt sayısıdır. Satırı açıp kayıtlara tıklayarak düzeltin; düzelttikçe puan yükselir.'})));
  const list = h('div');
  for (const c of d.checks.slice().sort((a, b) => (!!b.count - !!a.count) || (['critical', 'high', 'medium', 'low'].indexOf(a.severity) - ['critical', 'high', 'medium', 'low'].indexOf(b.severity)))) {
    const items = h('div', {class: 'items' + (opened === c.key && c.count ? '' : ' hidden')},
      c.items.length ? recordList(c.resource, c.items, {sub: it => it.detail || ''}) : null,
      c.count > c.items.length ? h('div', {class: 'muted small', text: `İlk ${c.items.length} kayıt gösteriliyor (toplam ${c.count}).`}) : null,
      c.link ? h('p', {}, h('a', {class: 'btn ghost small', href: '#/' + c.link, text: 'Listede aç →'})) : null);
    const head = h('button', {type: 'button', 'aria-expanded': String(!items.classList.contains('hidden'))},
      h('span', {class: 'count', text: c.count}), h('span', {class: 'check-text'}, h('strong', {text: c.title}), h('div', {class: 'why', text: c.why}),
        c.population ? h('div', {class: 'check-bar'}, progressBar(100 * (c.population - c.count) / c.population),
          h('span', {class: 'small muted', text: `${c.population - c.count} / ${c.population} uygun`})) : null),
      c.count ? pill(SEV_LABEL[c.severity] || c.severity, {critical: 'bad', high: 'warn', medium: 'neutral'}[c.severity] || 'neutral') : pill('Uygun', 'good'));
    head.addEventListener('click', () => { if (!c.count) return; items.classList.toggle('hidden'); head.setAttribute('aria-expanded', String(!items.classList.contains('hidden'))); });
    list.append(h('div', {class: `check sev-${c.severity}${c.count ? '' : ' ok'}`}, head, items));
  }
  content(summary, list);
  if (opened) list.querySelector('.items:not(.hidden)')?.scrollIntoView({block: 'center'});
};

// ------------------------------------------------------------------ risk panosu
PAGES.risk = async function riskBoard(parts, params) {
  await list('companies');
  const company = params.get('company_id') || ''; const category = params.get('category') || '';
  const q = new URLSearchParams(); if (company) q.set('company_id', company); if (category) q.set('category', category);
  setPage('Risk Panosu', 'ISO 31000: risk profili, iştah ve tolerans, değerlendirme dönemleri ve anahtar risk göstergeleri. Şirket seçerek kendi şirketlerinizin veya müşterilerinizin risklerini ayırın.', [
    canWrite('supplier_risks') ? btn('+ Yeni risk', () => createRecord('supplier_risks', company ? {company_id: Number(company)} : {})) : null,
    btn('Risk kaydı', () => Router.go('r/supplier_risks' + (company ? '?company_id=' + company : '')), 'secondary')]);
  const d = await api('risks/overview?' + q);
  const companies = S.cache.companies || [];
  const filter = h('div', {class: 'filters'},
    h('select', {class: 'compact', 'aria-label': 'Şirket', onchange: e => { const p = new URLSearchParams(q); if (e.target.value) p.set('company_id', e.target.value); else p.delete('company_id'); Router.go('risk?' + p); }},
      h('option', {value: '', text: 'Tüm şirketler'}),
      [['own', 'Kendi şirketlerimiz'], ['customer', 'Müşterilerimiz']].map(([kind, label]) => h('optgroup', {label}, companies.filter(c => c.kind === kind).map(c => h('option', {value: c.id, text: c.name, selected: String(c.id) === company}))))),
    h('select', {class: 'compact', 'aria-label': 'Kategori', onchange: e => { const p = new URLSearchParams(q); if (e.target.value) p.set('category', e.target.value); else p.delete('category'); Router.go('risk?' + p); }},
      h('option', {value: '', text: 'Tüm kategoriler'}), (META.field('supplier_risks', 'category').options).map(o => h('option', {value: o.value, text: o.label, selected: o.value === category}))));
  const base = 'r/supplier_risks?' + q + (q.toString() ? '&' : '');
  const cards = h('div', {class: 'cards five'},
    metric('Açık risk', fmt.num(d.total, 0), `${d.opportunities} fırsat`, '', () => Router.go(base.replace(/[?&]$/, ''))),
    metric('İştah üstü', fmt.num(d.above_appetite, 0), 'Artık risk iştahı aşıyor', d.above_appetite ? 'bad' : 'good'),
    metric('Değerlendirilmemiş', fmt.num(d.unassessed, 0), 'Artık risk hesaplanmadı', d.unassessed ? 'warn' : 'good'),
    metric('Gözden geçirmesi geciken', fmt.num(d.review_overdue, 0), 'Gözden geçirme tarihi geçti', d.review_overdue ? 'warn' : 'good', () => Router.go(base + 'review_date__lte=' + today(-1))),
    metric('Geciken faaliyet', fmt.num(d.actions_overdue, 0), 'İşleme faaliyeti hedef tarihi', d.actions_overdue ? 'bad' : 'good', () => Router.go(`r/risk_actions?due_date__lte=${today(-1)}&status=open`)));
  const levels = Object.entries(d.levels).filter(([, v]) => v).map(([k, v]) => ({label: META.option('supplier_risks', 'risk_level', k), value: v, color: {low: 1, medium: 2, high: 6, critical: 3}[k]}));
  const kri = Object.fromEntries(d.kri.map(k => [k.key, k.count]));
  const cycles = d.cycles.length ? h('ul', {class: 'mini'}, d.cycles.map(c => h('li', {class: 'link', onclick: () => openRecord('risk_cycles', c.id)},
    h('strong', {text: c.code + ' · ' + c.name}), h('span', {class: 'cell-sub', text: `${fmt.date(c.period_start)} – ${fmt.date(c.period_end)} · ${titleOf(refRecord('companies', c.company_id)) || 'Tüm şirketler'}`}),
    h('div', {class: 'progress-row'}, progressBar(c.progress_pct), h('span', {class: 'small', text: c.progress_pct === null ? '—' : `%${fmt.num(c.progress_pct, 0)} · ${c.assessed}/${c.in_scope}`})),
    display('risk_cycles', 'status', c.status)))) : empty('Açık veya planlı dönem yok', 'Dönemsel risk değerlendirmesi için bir dönem açın.',
    canWrite('risk_cycles') ? btn('+ Dönem', () => createRecord('risk_cycles')) : null);
  content(h('div', {class: 'toolbar'}, filter), cards,
    h('div', {class: 'grid two'},
      panel('Isı haritası', heatMap(d.heat, d.level_bounds, (l, i) => Router.go(base + `likelihood=${l}&impact=${i}`)), null, 'içsel risk'),
      panel('Seviye dağılımı', h('div', {}, donut(levels, {center: String(d.total)}), h('p', {class: 'muted small', text: `Seviye sınırları (politika): düşük ≤ ${d.level_bounds.low}, orta ≤ ${d.level_bounds.medium}, yüksek ≤ ${d.level_bounds.high}; değerlendirilmişse artık, değilse içsel puan.`}),
        h('h3', {class: 'sub-title', text: 'Şirket bazında'}), barChart(d.by_company.map(c => ({label: c.name, value: c.count, color: c.kind === 'own' ? 0 : 4, id: c.id})),
          {format: v => fmt.num(v, 0), onclick: item => Router.go('risk?company_id=' + item.id)})), null, 'artık risk')),
    h('div', {class: 'grid two'},
      panel('Değerlendirme dönemleri', cycles, btn('Tümü', () => Router.go('r/risk_cycles'), 'ghost small')),
      panel('Anahtar risk göstergeleri', h('div', {}, statStrip([['Yeşil', kri.green || 0, 'good'], ['Sarı', kri.amber || 0, kri.amber ? 'warn' : ''], ['Kırmızı', kri.red || 0, kri.red ? 'bad' : '']]),
        h('p', {class: 'muted small', text: 'Göstergeler eşik aşımında riskin yeniden değerlendirilmesi gerektiğini erken bildirir. Ölçümler elle veya MCP ile girilir.'})),
      btn('KRİ listesi', () => Router.go('r/kris'), 'ghost small'))),
    h('div', {class: 'grid two'},
      panel('Kategoriye göre', barChart(d.by_category.map(c => ({label: META.option('supplier_risks', 'category', c.key), value: c.count, key: c.key})), {format: v => fmt.num(v, 0),
        onclick: item => { const p = new URLSearchParams(q); p.set('category', item.key); Router.go('risk?' + p); }})),
      panel('Kaynağa göre', barChart(d.by_source.map(c => ({label: META.option('supplier_risks', 'source', c.key), value: c.count, color: 4})), {format: v => fmt.num(v, 0)}), null, 'elle, tedarikçi, anket, CMDB kuralı')),
    panel('En yüksek riskler', d.top.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kod', 'Risk', 'Şirket', 'Seviye', 'İçsel', 'Artık', 'İştah', 'Durum'].map((t, i) => h('th', {class: i >= 4 && i <= 6 ? 'num' : '', text: t})))),
      h('tbody', {}, d.top.map(r => h('tr', {class: 'clickable', onclick: () => openRecord('supplier_risks', r.id)}, h('td', {class: 'cell-primary', text: r.code}), h('td', {text: r.title}),
        h('td', {text: titleOf(refRecord('companies', r.company_id)).replace(/^SRK-\d+ — /, '')}), h('td', {}, levelPill(r.risk_level)), h('td', {class: 'num', text: r.inherent_score}),
        h('td', {class: 'num' + (r.residual_score > r.appetite ? ' over' : ''), text: r.residual_score === null ? '—' : fmt.num(r.residual_score)}), h('td', {class: 'num', text: r.appetite}),
        h('td', {}, display('supplier_risks', 'status', r.status))))))) : empty('Risk yok', '')),
    typeof quantPanel === 'function' ? await quantPanel() : null);
};

// ------------------------------------------------------------------ risk detayı (ISO 31000)
const RISK_FORM = ['title', 'company_id', 'risk_type', 'category', 'process_id', 'org_unit_id', 'supplier_id', 'engagement_id', 'entity_name', 'impact_area',
  'cause', 'risk_event', 'consequence', 'likelihood', 'impact', 'target_likelihood', 'target_impact', 'appetite', 'owner', 'consulted',
  'response_strategy', 'treatment', 'review_date', 'catalog_id', 'description'];
CREATE.supplier_risks = async defaults => {
  await list('companies');
  const own = (S.cache.companies || []).filter(c => c.kind === 'own' && c.active);
  const pre = own.length === 1 ? {company_id: own[0].id} : {};
  return recordForm('supplier_risks', null, {only: RISK_FORM, defaults: {likelihood: 3, impact: 3, owner: S.me.username, risk_type: 'threat', ...pre, ...defaults},
    onsaved: r => { refreshList('supplier_risks'); openRecord('supplier_risks', r.id); },
    extra: h('div', {class: 'notice wide', text: 'Risk ifadesi: "… nedeniyle (neden), … olabilir (olay), bu da … sonucunu doğurur (etki)". Şirket, riskin kime ait olduğunu belirler (kendi şirketimiz veya müşterimiz). İştah boş bırakılırsa kategorinin iştah beyanından gelir. Hedef olasılık ve etki, işleme sonrası ulaşılmak istenen seviyedir.'})});
};
DETAILS.supplier_risks = async function riskDetail(id, tab) {
  await Promise.all(['suppliers', 'engagements', 'companies', 'processes', 'org_units'].map(r => list(r).catch(() => [])));
  let r; try { r = await api(`supplier_risks/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const last = r.assessments[0]; const terminal = ['accepted', 'closed'].includes(r.status); const can = canWrite('supplier_risks');
  const above = last && Number(last.residual) > Number(last.appetite); const reload = t => { refreshList('supplier_risks'); DETAILS.supplier_risks(id, t); };
  const company = refRecord('companies', r.company_id); const tol = r.appetite_statement?.tolerance;
  const scores = statStrip([['İçsel (O×E)', `${r.inherent_score} · ${r.likelihood}×${r.impact}`], ['Artık', last ? fmt.num(last.residual) : '—', !last ? 'warn' : above ? 'bad' : 'good'],
    ['Hedef', r.target_score ? `${r.target_score} · ${r.target_likelihood}×${r.target_impact}` : '—'], ['İştah / tolerans', `${r.appetite}${tol ? ' / ' + tol : ''}`]]);
  const summary = () => h('div', {},
    terminal ? h('div', {class: 'notice', text: 'Karar verilmiş risk değiştirilemez. Değişiklik için önce gerekçeyle yeniden açın.'}) : !last ? h('div', {class: 'notice warn', text: 'Bu risk henüz değerlendirilmedi: artık risk ve seviye içsel puana göre gösterilir.'}) : null,
    above ? h('div', {class: 'notice bad', text: `Artık risk (${fmt.num(last.residual)}) iştah eşiğinin (${last.appetite}) üstünde${tol && Number(last.residual) > tol ? ' ve toleransı da aşıyor' : ''}: işleme planı gerekli veya yetkili istisna kararı verilmeli.`}) : null,
    scores,
    section('Risk ifadesi', kv([['Neden', r.cause], ['Olay', r.risk_event], ['Sonuç / etki', r.consequence], ['Etki alanı', display('supplier_risks', 'impact_area', r.impact_area)]])),
    section('Bağlam (ISO 31000 6.3)', kv([['Şirket', company ? h('span', {}, company.name, ' ', pill(META.option('companies', 'kind', company.kind), company.kind === 'own' ? 'neutral' : 'purple')) : null],
      ['Süreç', r.process_id ? h('a', {href: '#/r/processes/' + r.process_id, text: titleOf(refRecord('processes', r.process_id))}) : null],
      ['Birim', display('supplier_risks', 'org_unit_id', r.org_unit_id)], ['Tedarikçi', display('supplier_risks', 'supplier_id', r.supplier_id)],
      ['Angajman', display('supplier_risks', 'engagement_id', r.engagement_id)], ['Etkilenen varlık / hizmet', r.entity_name],
      ['Risk sahibi', r.owner], ['Danışılan paydaşlar', r.consulted]])),
    section('İşleme (ISO 31000 6.5)', kv([['Yanıt stratejisi', display('supplier_risks', 'response_strategy', r.response_strategy)], ['İşleme planı', r.treatment],
      ['Gözden geçirme', r.review_date ? h('span', {}, fmt.date(r.review_date), late(r.review_date) && !terminal ? h('span', {}, ' ', pill('Gecikti', 'bad')) : null) : null],
      ['Son değerlendirme', fmt.datetime(r.last_assessed_at)], ['Kaynak', display('supplier_risks', 'source', r.source)], ['Açıklama', r.description]])),
    r.appetite_statement ? section('İştah beyanı', h('div', {class: 'notice', text: `${r.appetite_statement.code} · ${r.appetite_statement.statement} (iştah ${r.appetite_statement.appetite}, tolerans ${r.appetite_statement.tolerance})`})) : null);
  const assessments = () => r.assessments.length ? h('ul', {class: 'timeline'}, r.assessments.map(a => h('li', {},
    h('strong', {text: `${fmt.datetime(a.assessed_at)} · ${a.assessor}`}), h('div', {text: `İçsel ${a.inherent} → artık ${fmt.num(a.residual)} (iştah ${a.appetite}) · azaltım %${fmt.num(a.mitigation_pct)}`}),
    h('div', {class: 'muted', text: a.rationale}), (a.snapshot.mitigations || []).length ? h('div', {class: 'chips'}, a.snapshot.mitigations.map(m =>
      h('span', {class: 'chip', text: `${m.title || 'Önlem'} · ${{low: 'düşük', medium: 'orta', high: 'yüksek'}[m.weight] || m.weight} katkı${m.effectiveness === 'partial' ? ' · kısmen etkili' : ''}`}))) : null)))
    : empty('Değerlendirme yok', 'Olasılık ve etkiyi azaltan önlemlerle artık riski hesaplayın.', can && !terminal ? btn('Değerlendir', () => assessRisk(r, () => reload('assess'))) : null);
  const decisions = () => r.decisions.length ? h('ul', {class: 'timeline'}, r.decisions.map(d => h('li', {},
    h('strong', {text: `${META.option('supplier_risks', 'status', d.from_status)} → ${META.option('supplier_risks', 'status', d.to_status)}`}),
    h('div', {class: 'muted', text: `${fmt.datetime(d.decided_at)} · ${d.actor} (${roleLabel(d.actor_role)})`}), h('div', {text: d.rationale}),
    d.exception_rationale ? h('div', {class: 'notice warn', text: 'İştah istisnası: ' + d.exception_rationale}) : null))) : h('div', {class: 'muted small', text: 'Karar yok'});
  const actions = () => h('div', {}, recordList('risk_actions', r.actions, {sub: a => `${a.owner} · ${fmt.date(a.due_date)}${late(a.due_date) && !['completed', 'cancelled'].includes(a.status) ? ' · gecikti' : ''}`,
    chips: a => [display('risk_actions', 'priority', a.priority), display('risk_actions', 'status', a.status)], none: 'İşleme faaliyeti yok'}),
    can && !terminal && META.def('risk_actions')?.can_write ? h('p', {}, btn('+ Faaliyet', () => createRecord('risk_actions', {risk_id: id, owner: r.owner}), 'secondary small')) : null);
  const kris = () => h('div', {}, recordList('kris', r.kris, {sub: k => `${k.last_value === null ? 'Ölçüm yok' : fmt.num(k.last_value, 2) + ' ' + (k.unit || '')} · eşikler ${k.threshold_amber} / ${k.threshold_red}`,
    chips: k => [k.last_status ? pill(KRI_TEXT[k.last_status], KRI_TONE[k.last_status]) : pill('Ölçüm yok', 'neutral')], none: 'Bu riske bağlı gösterge yok'}),
    META.def('kris')?.can_write ? h('p', {}, btn('+ Gösterge (KRİ)', () => createRecord('kris', {risk_id: id, owner: r.owner}), 'secondary small')) : null);
  const controls = () => h('div', {}, recordList('controls', r.controls, {chips: k => [k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral')],
    sub: k => k.last_executed_at ? 'Son test ' + fmt.datetime(k.last_executed_at) : '', none: 'Bağlı kontrol yok. Kontrol eşlemesi kontrol ekranından yapılır.'}));
  const cis = () => h('div', {}, recordList('cmdb_cis', r.cis, {sub: c => [META.option('cmdb_cis', 'ci_class', c.ci_class), c.environment ? META.option('cmdb_cis', 'environment', c.environment) : null].filter(Boolean).join(' · '),
    chips: c => [pill(c.link_source === 'rule' ? 'CMDB kuralı' : 'Elle bağlandı', c.link_source === 'rule' ? 'purple' : 'neutral')], none: 'Bağlı konfigürasyon öğesi yok'}),
    can && hasModule('cmdb') ? h('p', {}, btn('Etkilenen CI\'ları seç', async () => {
      const all = await list('cmdb_cis', true); const manual = r.cis.filter(c => c.link_source !== 'rule').map(c => c.id);
      const ids = await pickMany('Etkilenen konfigürasyon öğeleri', all, manual, {label: c => `${c.code} · ${c.name} (${META.option('cmdb_cis', 'ci_class', c.ci_class)})`,
        intro: 'Bu riskten etkilenen uygulama ve sunucuları seçin. CMDB kuralının bağladıkları otomatik korunur.'});
      if (ids) { await api(`supplier_risks/${id}/cis`, {method: 'POST', body: {ci_ids: ids}}); toast('Bağlantılar kaydedildi'); reload('cis'); }
    }, 'secondary small')) : null);
  const history = () => h('div', {}, section('Değerlendirmeler', assessments()), section('Kararlar (değiştirilemez)', decisions()));
  const items = [{key: 'summary', label: 'Özet', render: summary}, {key: 'assess', label: 'Değerlendirme ve kararlar', count: r.assessments.length + r.decisions.length, render: history},
    {key: 'actions', label: 'İşleme', count: r.actions.length, render: actions}];
  if (META.def('kris')) items.push({key: 'kris', label: 'KRİ', count: r.kris.length, render: kris});
  if (hasModule('grc')) items.push({key: 'controls', label: 'Kontroller', count: r.controls.length, render: controls});
  if (hasModule('cmdb')) items.push({key: 'cis', label: 'Varlıklar', count: r.cis.length, render: cis});
  for (const t of (typeof RISK_TABS === 'undefined' ? [] : RISK_TABS)) items.push({key: t.key, label: t.label, render: () => t.render(r, reload)});
  const body = h('div', {}, h('div', {class: 'chips'}, levelPill(r.risk_level), display('supplier_risks', 'status', r.status), display('supplier_risks', 'category', r.category),
    r.risk_type === 'opportunity' ? pill('Fırsat', 'good') : null, r.source && r.source !== 'manual' ? pill(META.option('supplier_risks', 'source', r.source), 'purple') : null), h('br'), tabs(items, tab));
  Drawer.open(r.code + ' · ' + r.title, body, can ? (terminal ? [btn('Yeniden aç', () => decision(r, 'open', () => reload()), 'secondary')] : [
    btn('Düzenle', () => recordForm('supplier_risks', r, {only: RISK_FORM, onsaved: () => reload()}), 'secondary'),
    typeof riskQuality === 'function' ? btn('İfade kalitesi', () => riskQuality(r, () => reload()), 'ghost', {title: 'Neden–olay–etki yapısını denetle; öneriyi onayla'}) : null,
    last ? btn('Kapat', () => decision(r, 'closed', () => reload()), 'secondary') : null, last ? btn('Kabul et', () => decision(r, 'accepted', () => reload()), 'secondary') : null,
    btn('Değerlendir', () => assessRisk(r, () => reload('assess')))]) : [], (r.supplier_id ? 'Tedarikçi riski' : 'Kurumsal risk') + (company ? ' · ' + company.name : ''));
};

// ------------------------------------------------------------------ KRİ ve risk değerlendirme dönemi
DETAILS.kris = async function kriDetail(id) {
  await list('supplier_risks');
  let k, values; try { [k, values] = await Promise.all([api(`kris/${id}`), api(`kri_values?kri_id=${id}&limit=200`)]); } catch (e) { toast(e.message, false); return; }
  values.sort((a, b) => String(a.period).localeCompare(String(b.period)));
  const reload = () => { refreshList('kris'); DETAILS.kris(id); };
  const body = h('div', {}, h('div', {class: 'chips'}, k.last_status ? pill(KRI_TEXT[k.last_status], KRI_TONE[k.last_status]) : pill('Ölçüm yok', 'neutral'),
    display('kris', 'frequency', k.frequency), k.active ? null : pill('Pasif', 'neutral')), h('br'),
    statStrip([['Son değer', k.last_value === null ? '—' : `${fmt.num(k.last_value, 2)} ${k.unit || ''}`, KRI_TONE[k.last_status]], ['Sarı eşik', fmt.num(k.threshold_amber, 2)],
      ['Kırmızı eşik', fmt.num(k.threshold_red, 2)], ['Yön', k.direction === 'higher_worse' ? 'Yüksek kötü' : 'Düşük kötü']]),
    section('Eğilim', sparkline(values, {amber: k.threshold_amber, red: k.threshold_red, direction: k.direction})),
    section('Bilgiler', kv([['Risk', k.risk_id ? h('a', {href: '#/r/supplier_risks/' + k.risk_id, text: titleOf(refRecord('supplier_risks', k.risk_id))}) : null],
      ['Sahip', k.owner], ['Birim', k.unit], ['Açıklama', k.description]])),
    section(`Ölçümler (${values.length})`, values.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Dönem', 'Değer', 'Durum', 'Kaynak', 'Kaydeden'].map((t, i) => h('th', {class: i === 1 ? 'num' : '', text: t})))),
      h('tbody', {}, values.slice().reverse().map(v => h('tr', {}, h('td', {text: fmt.date(v.period)}), h('td', {class: 'num', text: fmt.num(v.value, 2)}),
        h('td', {}, pill(KRI_TEXT[v.status], KRI_TONE[v.status])), h('td', {}, display('kri_values', 'source', v.source)), h('td', {text: v.recorded_by})))))) : h('div', {class: 'muted small', text: 'Ölçüm yok'})));
  Drawer.open(k.code + ' · ' + k.name, body, [
    META.def('kri_values')?.can_write ? btn('+ Ölçüm', () => recordForm('kri_values', null, {only: ['period', 'value', 'note'], defaults: {kri_id: id, period: nextPeriod(k.last_measured_at)},
      title: 'Yeni ölçüm: ' + k.name, onsaved: reload})) : null,
    canWrite('kris') ? btn('Düzenle', () => recordForm('kris', k, {onsaved: reload}), 'secondary') : null], 'Anahtar risk göstergesi');
};
DETAILS.risk_cycles = async function cycleDetail(id) {
  await list('companies');
  let c; try { c = await api(`risk_cycles/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('risk_cycles'); DETAILS.risk_cycles(id); };
  const pending = c.risks.filter(r => !r.assessed_in_cycle);
  const body = h('div', {}, h('div', {class: 'chips'}, display('risk_cycles', 'status', c.status)), h('br'),
    statStrip([['İlerleme', c.progress_pct === null ? '—' : '%' + fmt.num(c.progress_pct, 0), c.progress_pct >= 90 ? 'good' : c.status === 'closed' ? 'warn' : ''],
      ['Kapsamdaki risk', c.in_scope], ['Değerlendirilen', c.assessed], ['Bekleyen', pending.length, pending.length ? 'warn' : 'good']]),
    h('div', {class: 'progress-row'}, progressBar(c.progress_pct)),
    section('Dönem', kv([['Şirket', c.company_id ? titleOf(refRecord('companies', c.company_id)) : 'Tüm şirketler'], ['Dönem', `${fmt.date(c.period_start)} – ${fmt.date(c.period_end)}`],
      ['Sorumlu', c.owner], ['Kapsam', c.scope], ['Açıklama', c.description]])),
    section(`Değerlendirme bekleyen riskler (${pending.length})`, recordList('supplier_risks', pending.slice(0, 60), {sub: r => r.owner, chips: r => [levelPill(r.risk_level)], none: 'Tüm riskler bu dönemde değerlendirildi'})),
    section(`Bu dönemde değerlendirilenler (${c.assessed})`, recordList('supplier_risks', c.risks.filter(r => r.assessed_in_cycle).slice(0, 60),
      {sub: r => `${r.owner} · ${fmt.datetime(r.assessed_in_cycle)}`, chips: r => [levelPill(r.risk_level)]})));
  Drawer.open(c.code + ' · ' + c.name, body, [canWrite('risk_cycles') ? btn('Düzenle', () => recordForm('risk_cycles', c, {onsaved: reload}), 'secondary') : null], 'Risk değerlendirme dönemi');
};

// ------------------------------------------------------------------ iş sürekliliği panosu
PAGES.bcm = async function bcmBoard() {
  setPage('Süreklilik Panosu', 'ISO 22301: iş etki analizleri (BİA), süreklilik planları ve tatbikatlar. Kritik süreçlerin plan ve tatbikatla karşılanıp karşılanmadığını gösterir.', [
    canWrite('bias') ? btn('+ Yeni BİA', () => createRecord('bias')) : null, canWrite('bc_exercises') ? btn('+ Tatbikat', () => createRecord('bc_exercises'), 'secondary') : null]);
  const d = await api('bcm/overview');
  const count = (arr, key) => (arr.find(x => x.key === key) || {}).count || 0;
  content(
    h('div', {class: 'cards'},
      metric('BİA kapsamı', fmt.pct(d.coverage_pct), `${d.processes_with_bia} / ${d.processes} ana süreç onaylı BİA ile`, d.coverage_pct >= 80 ? 'good' : d.coverage_pct >= 40 ? 'warn' : 'bad', () => Router.go('process-map')),
      metric('Onaylı BİA', fmt.num(count(d.bias, 'approved'), 0), `${count(d.bias, 'in_review')} onayda · ${count(d.bias, 'draft')} taslak`, '', () => Router.go('r/bias')),
      metric('Onaylı plan', fmt.num(d.plans_total, 0), `${d.plan_review_overdue} planın gözden geçirmesi gecikti`, d.plan_review_overdue ? 'warn' : '', () => Router.go('r/bc_plans')),
      metric('Bu yıl tatbikat', fmt.num(d.exercises_year, 0), `${d.exercises_planned.length} planlı tatbikat`, d.exercises_year ? 'good' : 'warn', () => Router.go('r/bc_exercises'))),
    h('div', {class: 'grid two'},
      panel('Kritiklik dağılımı', donut(d.criticality.map(c => ({label: META.option('bias', 'criticality', c.key) || 'Belirlenmedi', value: c.count,
        color: {critical: 3, high: 6, medium: 2, low: 1}[c.key] ?? 5})), {center: String(d.criticality.reduce((a, x) => a + x.count, 0))}), null, 'MTPD\'ye göre'),
      panel('Yaklaşan tatbikatlar', recordList('bc_exercises', d.exercises_planned, {sub: x => `${fmt.date(x.planned_date)} · ${dueText(x.planned_date)}`,
        chips: x => [display('bc_exercises', 'exercise_type', x.exercise_type)], none: 'Planlı tatbikat yok'}))),
    h('div', {class: 'grid two'},
      panel('Tatbikatı yapılmamış veya geciken planlar', recordList('bc_plans', d.plans_not_exercised, {sub: p => p.last_exercise ? 'Son tatbikat ' + fmt.date(p.last_exercise) : 'Hiç tatbikat yapılmadı',
        chips: p => [display('bc_plans', 'status', p.status)], none: 'Tüm planlar son ' + d.exercise_months + ' ayda sınandı'}), null, `ISO 22301 8.5 · ${d.exercise_months} ay`),
      panel('RTO açıkları (tatbikat sonuçları)', recordList('bc_exercises', d.rto_gaps, {sub: x => `Hedef ${x.target_recovery_minutes} dk · gerçekleşen ${x.achieved_recovery_minutes} dk · ${x.plan_code || ''}`,
        chips: x => [pill(`+${x.achieved_recovery_minutes - x.target_recovery_minutes} dk`, 'bad')], none: 'Tatbikatlarda hedef süre aşılmadı'}))),
    h('div', {class: 'grid two'},
      panel('Planı olmayan kritik BİA\'lar', recordList('bias', d.critical_without_plan, {chips: b => [display('bias', 'criticality', b.criticality)], none: 'Kritik BİA\'ların hepsi bir planla karşılanıyor'})),
      panel('Destek dışı veya riskli uygulamaya bağımlı BİA\'lar', recordList('bias', d.eos_applications, {sub: b => `${b.ci_name} · ${META.option('ci_exposures', 'rule', b.rule)}`,
        none: 'Bağımlı uygulamalarda açık CMDB maruziyeti yok'}), null, 'CMDB maruziyetleri')));
};

// ------------------------------------------------------------------ BİA detayı
const WINDOW_LABEL = {h1: '1 saat', h4: '4 saat', h8: '8 saat', d1: '1 gün', d3: '3 gün', w1: '1 hafta', w2: '2 hafta', m1: '1 ay'};
const IMPACT_LEVELS = ['1 · Önemsiz', '2 · Düşük', '3 · Orta', '4 · Yüksek', '5 · Çok yüksek'];
function hours(v) { if (v === null || v === undefined) return '—'; const n = Number(v); return n >= 24 && n % 24 === 0 ? `${n / 24} gün` : `${fmt.num(n, 1)} saat`; }
DETAILS.bias = async function biaDetail(id, tab) {
  await Promise.all(['processes', 'companies', 'org_units'].map(r => list(r).catch(() => [])));
  let b; try { b = await api(`bias/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const can = canWrite('bias'); const editable = can && b.status === 'draft';
  const reload = t => { refreshList('bias'); DETAILS.bias(id, t); };
  const act = (action, note) => api(`bias/${id}/transition`, {method: 'POST', body: {action, note}}).then(() => { toast('Kaydedildi'); reload(); });
  const categories = META.field('bia_impacts', 'category').options; const windows = b.windows.map(w => w.key);
  const mtpdWindow = b.windows.find(w => w.hours === b.mtpd_hours)?.key;
  const level = (cat, win) => (b.impacts.find(i => i.category === cat && i.time_window === win) || {}).level;
  const matrix = (edit) => {
    const table = h('table', {class: 'matrix'}, h('thead', {}, h('tr', {}, h('th', {text: 'Etki kategorisi'}), windows.map(w => h('th', {text: WINDOW_LABEL[w] || w, class: w === mtpdWindow ? 'mtpd-col' : ''})))));
    const tbody = h('tbody');
    for (const c of categories) {
      tbody.append(h('tr', {}, h('th', {text: c.label}), windows.map(w => {
        const v = level(c.value, w);
        if (!edit) return h('td', {}, h('span', {class: `cellv lv${v || 0}${w === mtpdWindow && v >= b.intolerable_level ? ' mtpd' : ''}`, text: v || '—'}));
        const sel = h('select', {class: 'lv' + (v || 1), dataset: {cat: c.value, win: w}, 'aria-label': `${c.label} · ${WINDOW_LABEL[w]}`},
          IMPACT_LEVELS.map((t, i) => h('option', {value: i + 1, text: i + 1, title: t, selected: (v || 1) === i + 1})));
        sel.addEventListener('change', () => {          // etki zamanla azalamaz: sonraki hücreler en az bu değere çıkar, öncekiler en çok bu değere iner
          const row = [...sel.closest('tr').querySelectorAll('select')]; const at = row.indexOf(sel); const v = Number(sel.value);
          row.forEach((other, i) => { const ov = Number(other.value); if ((i > at && ov < v) || (i < at && ov > v)) other.value = String(v); other.className = 'lv' + other.value; });
        });
        return h('td', {}, sel);
      })));
    }
    table.append(tbody);
    return h('div', {class: 'tablewrap plain'}, table);
  };
  const impacts = () => h('div', {},
    h('p', {class: 'intro', text: `Her kategori için kesintinin süresine göre etki seviyesi (1–5). Seviyenin ilk kez ${b.intolerable_level} ve üstüne çıktığı süre MTPD'dir (en uzun katlanılabilir kesinti); RTO bu sürenin altında olmalıdır. Etki zamanla azalamaz.`}),
    matrix(false), h('div', {class: 'legend'}, IMPACT_LEVELS.map((t, i) => h('span', {}, h('i', {class: `cellv-dot lv${i + 1}`}), t))),
    editable ? h('p', {}, btn('Etki matrisini düzenle', () => {
      const m = matrix(true);
      Modal.open('Etki matrisi: ' + b.code, h('div', {}, h('p', {class: 'intro', text: 'Seviyeleri seçin. Kaydettiğinizde MTPD ve kritiklik yeniden hesaplanır.'}), m), [
        btn('Vazgeç', () => Modal.close(), 'secondary'),
        btn('Kaydet', async () => {
          const impacts = [...m.querySelectorAll('select')].map(sel => ({category: sel.dataset.cat, time_window: sel.dataset.win, level: Number(sel.value)}));
          await api(`bias/${id}/impacts`, {method: 'POST', body: {impacts}}); Modal.close(); toast('Etki matrisi kaydedildi'); reload('impacts');
        })], true);
    }, 'secondary small')) : b.status !== 'draft' && can ? h('div', {class: 'muted small', text: 'Onaya gönderilmiş veya onaylı BİA değiştirilmez; değişiklik için revizyona alın.'}) : null);
  const deps = () => h('div', {},
    section(`Uygulama bağımlılıkları (${b.applications.length})`, recordList('cmdb_cis', b.applications, {sub: a => `Gerekli RTO ${hours(a.required_rto_hours)} · ${META.option('cmdb_cis', 'ci_class', a.ci_class)}`,
      chips: a => [a.business_criticality ? display('cmdb_cis', 'business_criticality', a.business_criticality) : null, ...(a.exposures || []).map(x => pill(META.option('ci_exposures', 'rule', x.rule || x), 'bad'))],
      none: 'CMDB\'den uygulama bağlanmadı'}), editable && META.def('bia_applications')?.can_write ? btn('+ Uygulama', () => createRecord('bia_applications', {bia_id: id, required_rto_hours: b.rto_hours}), 'ghost small') : null),
    section(`Tedarikçi bağımlılıkları (${b.suppliers.length})`, recordList('suppliers', b.suppliers, {sub: s => s.note || '', chips: s => [display('suppliers', 'tier', s.tier), s.open_risks ? pill(`${s.open_risks} açık risk`, 'warn') : null],
      none: 'Tedarikçi bağımlılığı yok'}), editable && META.def('bia_suppliers')?.can_write ? btn('+ Tedarikçi', () => createRecord('bia_suppliers', {bia_id: id}), 'ghost small') : null),
    section(`İlgili riskler (${b.risks.length})`, recordList('supplier_risks', b.risks, {chips: r => [levelPill(r.risk_level), display('supplier_risks', 'status', r.status)], none: 'Bağlı risk yok'}),
      editable && META.def('bia_risks')?.can_write ? btn('+ Risk', () => createRecord('bia_risks', {bia_id: id}), 'ghost small') : null));
  const summary = () => h('div', {},
    statStrip([['MTPD', hours(b.mtpd_hours), b.mtpd_hours === null ? 'warn' : ''], ['RTO', hours(b.rto_hours), b.rto_hours === null ? 'warn' : ''], ['RPO', hours(b.rpo_hours)],
      ['Kritiklik', b.criticality ? META.option('bias', 'criticality', b.criticality) : '—', {critical: 'bad', high: 'warn'}[b.criticality] || '']]),
    b.rto_hours !== null && b.mtpd_hours !== null && Number(b.rto_hours) > Number(b.mtpd_hours) ? h('div', {class: 'notice bad', text: 'RTO, MTPD\'den büyük olamaz.'}) : null,
    section('Kapsam', kv([['Süreç', b.process_id ? h('a', {href: '#/r/processes/' + b.process_id, text: titleOf(refRecord('processes', b.process_id))}) : null],
      ['Şirket', display('bias', 'company_id', b.company_id)], ['Birim', display('bias', 'org_unit_id', b.org_unit_id)], ['Sahip', b.owner],
      ['Yoğun dönemler', b.peak_periods], ['Asgari personel', b.min_staff], ['Lokasyonlar', b.locations]])),
    section('Süreklilik gereksinimleri', kv([['Asgari hizmet seviyesi (MBCO)', b.mbco], ['Hayati kayıtlar', b.vital_records], ['Geçici çözüm', b.workaround], ['Açıklama', b.description]])),
    section('Onay', kv([['Hazırlayan', b.prepared_by], ['Onaylayan', b.approved_by], ['Onay zamanı', fmt.datetime(b.approved_at)],
      ['Gözden geçirme', b.review_date ? h('span', {}, fmt.date(b.review_date), late(b.review_date) ? h('span', {}, ' ', pill('Gecikti', 'bad')) : null) : null]])),
    section(`Kapsayan planlar (${b.plans.length})`, recordList('bc_plans', b.plans, {chips: p => [display('bc_plans', 'status', p.status), display('bc_plans', 'plan_type', p.plan_type)],
      none: 'Bu BİA henüz bir süreklilik planında yer almıyor'})));
  const items = [{key: 'summary', label: 'Özet', render: summary}, {key: 'impacts', label: 'Etki matrisi', render: impacts},
    {key: 'deps', label: 'Bağımlılıklar', count: b.applications.length + b.suppliers.length + b.risks.length, render: deps}];
  const managers = ['ADMIN', 'SUPPLIER_MANAGER'].includes(S.me.role);
  Drawer.open(b.code + ' · ' + b.title, h('div', {}, h('div', {class: 'chips'}, display('bias', 'status', b.status), b.criticality ? display('bias', 'criticality', b.criticality) : null), h('br'), tabs(items, tab)), [
    editable ? btn('Düzenle', () => recordForm('bias', b, {onsaved: () => reload()}), 'secondary') : null,
    can && b.status === 'draft' ? btn('Onaya gönder', () => act('submit')) : null,
    managers && b.status === 'in_review' ? btn('Onayla', () => act('approve')) : null,
    can && b.status === 'approved' ? btn('Revizyona al', () => act('revise'), 'secondary') : null,
    META.can('manage') && b.status !== 'archived' ? btn('Arşivle', () => confirmDialog('BİA arşivlensin mi?', 'Arşivlenen BİA kapsam ve raporlardan çıkar.', 'Arşivle', 'danger').then(ok => ok && act('archive')), 'ghost') : null],
  'İş etki analizi');
};
CREATE.bias = defaults => recordForm('bias', null, {defaults: {owner: S.me.username, ...defaults}, skip: ['mtpd_hours'],
  onsaved: r => { refreshList('bias'); openRecord('bias', r.id); },
  extra: h('div', {class: 'notice wide', text: 'Kaydettikten sonra etki matrisini doldurun: MTPD ve kritiklik matristen hesaplanır. RTO, MTPD\'yi aşamaz.'})});

// ------------------------------------------------------------------ süreklilik planı ve tatbikat
const PHASES = [['activation', 'Devreye alma'], ['response', 'Müdahale'], ['recovery', 'Kurtarma'], ['resumption', 'Normale dönüş']];
DETAILS.bc_plans = async function planDetail(id, tab) {
  await list('companies');
  let p; try { p = await api(`bc_plans/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const can = canWrite('bc_plans'); const draft = p.status === 'draft'; const reload = t => { refreshList('bc_plans'); DETAILS.bc_plans(id, t); };
  const act = action => api(`bc_plans/${id}/transition`, {method: 'POST', body: {action}}).then(() => { toast('Kaydedildi'); reload(); });
  const steps = () => h('div', {}, PHASES.map(([phase, label]) => {
    const items = p.steps.filter(x => x.phase === phase);
    return section(`${label} (${items.length})`, items.length ? h('ol', {class: 'steps-list'}, items.map(x => h('li', {class: draft && can ? 'link' : '', onclick: draft && can ? () => recordForm('bc_plan_steps', x, {onsaved: () => reload('steps')}) : null},
      h('strong', {text: x.action}), h('span', {class: 'cell-sub', text: [x.responsible, x.target_minutes ? `hedef ${x.target_minutes} dk` : null].filter(Boolean).join(' · ')}))))
      : h('div', {class: 'muted small', text: 'Adım yok'}), draft && can ? btn('+ Adım', () => createRecord('bc_plan_steps', {plan_id: id, phase, position: items.length + 1}), 'ghost small') : null);
  }), !draft ? h('div', {class: 'muted small', text: 'Onaylı planın adımları değiştirilmez; değişiklik için revizyona alın.'}) : null);
  const scope = () => h('div', {},
    section(`Kapsadığı BİA'lar (${p.bias.length})`, recordList('bias', p.bias, {sub: b => `RTO ${hours(b.rto_hours)} · MTPD ${hours(b.mtpd_hours)}`, chips: b => [b.criticality ? display('bias', 'criticality', b.criticality) : null, display('bias', 'status', b.status)],
      none: 'BİA bağlanmadı'}), draft && can ? btn('BİA seç', async () => {
      const all = await list('bias', true);
      const ids = await pickMany('Planın kapsadığı BİA\'lar', all.filter(x => x.status !== 'archived'), p.bias.map(x => x.id), {label: x => `${x.code} · ${x.title}`});
      if (ids) { await api(`bc_plans/${id}/bias`, {method: 'POST', body: {bia_ids: ids}}); toast('Kapsam kaydedildi'); reload('scope'); }
    }, 'ghost small') : null),
    section(`Kurtarılacak uygulamalar (${p.applications.length})`, p.applications.length ? h('ol', {class: 'steps-list'}, p.applications.map(a => h('li', {class: 'link', onclick: () => openRecord('cmdb_cis', a.id)},
      h('strong', {text: `${a.recovery_order}. ${a.name}`}), h('span', {class: 'cell-sub', text: `${a.code} · hedef RTO ${hours(a.target_rto_hours)}`})))) : h('div', {class: 'muted small', text: 'Uygulama yok'}),
      draft && can && META.def('bc_plan_applications')?.can_write ? btn('+ Uygulama', () => createRecord('bc_plan_applications', {plan_id: id, recovery_order: p.applications.length + 1}), 'ghost small') : null));
  const exercises = () => h('div', {}, recordList('bc_exercises', p.exercises, {sub: x => `${fmt.date(x.actual_date || x.planned_date)} · ${META.option('bc_exercises', 'exercise_type', x.exercise_type)}`,
    chips: x => [display('bc_exercises', 'status', x.status), x.outcome ? display('bc_exercises', 'outcome', x.outcome) : null], none: 'Tatbikat yok'}),
    canWrite('bc_exercises') ? h('p', {}, btn('+ Tatbikat planla', () => createRecord('bc_exercises', {plan_id: id}), 'secondary small')) : null);
  const summary = () => h('div', {},
    statStrip([['Sürüm', p.version], ['Adım', p.steps.length], ['BİA', p.bias.length], ['Son tatbikat', p.last_exercise ? fmt.date(p.last_exercise.actual_date) : 'Yok', p.last_exercise ? '' : 'warn']]),
    p.exercise_due && p.exercise_due < today() ? h('div', {class: 'notice warn', text: `Tatbikat zamanı geçti (${fmt.date(p.exercise_due)}).`}) : null,
    section('Plan', kv([['Tür', display('bc_plans', 'plan_type', p.plan_type)], ['Şirket', display('bc_plans', 'company_id', p.company_id)], ['Sahip', p.owner],
      ['Kapsam', p.scope], ['Devreye alma ölçütü', p.activation_criteria], ['Strateji', p.strategy], ['Ekip', p.team], ['İletişim', p.communication],
      ['Bağlı doküman', p.document ? h('a', {href: '#/r/documents/' + p.document.id, text: `${p.document.code} · ${p.document.title}`}) : null]])),
    section('Onay', kv([['Hazırlayan', p.prepared_by], ['Onaylayan', p.approved_by], ['Onay zamanı', fmt.datetime(p.approved_at)], ['Gözden geçirme', fmt.date(p.review_date)]])));
  const managers = ['ADMIN', 'SUPPLIER_MANAGER'].includes(S.me.role);
  Drawer.open(p.code + ' · ' + p.title, h('div', {}, h('div', {class: 'chips'}, display('bc_plans', 'status', p.status), display('bc_plans', 'plan_type', p.plan_type)), h('br'),
    tabs([{key: 'summary', label: 'Özet', render: summary}, {key: 'steps', label: 'Adımlar', count: p.steps.length, render: steps},
      {key: 'scope', label: 'Kapsam', count: p.bias.length + p.applications.length, render: scope}, {key: 'exercises', label: 'Tatbikatlar', count: p.exercises.length, render: exercises}], tab)), [
    draft && can ? btn('Düzenle', () => recordForm('bc_plans', p, {onsaved: () => reload()}), 'secondary') : null,
    draft && managers ? btn('Onayla', () => act('approve')) : null,
    p.status === 'approved' && can ? btn('Revizyona al', () => act('revise'), 'secondary') : null,
    META.can('manage') && p.status !== 'retired' ? btn('Yürürlükten kaldır', () => confirmDialog('Plan yürürlükten kaldırılsın mı?', 'Kaldırılan plan tatbikat ve kapsam hesaplarından çıkar.', 'Kaldır', 'danger').then(ok => ok && act('archive')), 'ghost') : null],
  'Süreklilik planı');
};
DETAILS.bc_exercises = async function exerciseDetail(id) {
  let x; try { x = await api(`bc_exercises/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const can = canWrite('bc_exercises'); const planned = x.status === 'planned'; const reload = () => { refreshList('bc_exercises'); DETAILS.bc_exercises(id); };
  const body = h('div', {}, h('div', {class: 'chips'}, display('bc_exercises', 'status', x.status), display('bc_exercises', 'exercise_type', x.exercise_type),
    x.outcome ? display('bc_exercises', 'outcome', x.outcome) : null, x.gap_minutes > 0 ? pill(`Hedef ${x.gap_minutes} dk aşıldı`, 'bad') : null), h('br'),
    statStrip([['Tarih', fmt.date(x.actual_date || x.planned_date)], ['Hedef kurtarma', x.target_recovery_minutes ? x.target_recovery_minutes + ' dk' : '—'],
      ['Gerçekleşen', x.achieved_recovery_minutes ? x.achieved_recovery_minutes + ' dk' : '—', x.gap_minutes > 0 ? 'bad' : x.gap_minutes !== null ? 'good' : ''], ['Bulgu', x.findings.length]]),
    section('Tatbikat', kv([['Plan', x.plan ? h('a', {href: '#/r/bc_plans/' + x.plan.id, text: `${x.plan.code} · ${x.plan.title}`}) : null], ['Senaryo', x.scenario], ['Amaçlar', x.objectives],
      ['Yöneten', x.facilitator], ['Katılımcılar', x.participants]])),
    x.status === 'completed' ? section('Sonuç (ISO 22301 8.5)', kv([['Sonuç', display('bc_exercises', 'outcome', x.outcome)], ['Alınan dersler', x.lessons_learned], ['Rapor', x.report]])) : null,
    section(`Bulgular (${x.findings.length})`, recordList('findings', x.findings, {chips: f => [display('findings', 'severity', f.severity), display('findings', 'status', f.status)], none: 'Bulgu yok'}),
      can && canWrite('findings') ? btn('+ Bulgu', () => {
        const form = h('form', {class: 'formgrid'}, ...['title', 'severity', 'owner', 'due_date', 'description'].map(n => inputFor('findings', META.field('findings', n), n === 'severity' ? 'medium' : n === 'due_date' ? today(30) : null)));
        Modal.open('Tatbikat bulgusu: ' + x.code, h('div', {}, h('p', {class: 'intro', text: 'Bulgu uyum modülünde açılır ve DÖF akışına girer; tatbikata bağlı kalır.'}), form), [btn('Vazgeç', () => Modal.close(), 'secondary'),
          btn('Bulgu aç', async () => {
            const {data, errors} = readForm(form, 'findings', ['title', 'severity', 'owner', 'due_date', 'description'].map(n => META.field('findings', n)));
            if (!data.title) { showErrors(form, {title: 'Bu alan zorunlu'}, 'Başlık gerekli'); return; }
            for (const k of Object.keys(data)) if (data[k] === null) delete data[k];
            await api(`bc_exercises/${id}/findings`, {method: 'POST', body: data}); Modal.close(); toast('Bulgu açıldı'); reload();
          })]);
      }, 'ghost small') : null));
  Drawer.open(x.code + ' · ' + x.title, body, [
    can && planned ? btn('Düzenle', () => recordForm('bc_exercises', x, {onsaved: reload}), 'secondary') : null,
    can && planned ? btn('Sonuçlandır', () => completeExercise(x, reload)) : null,
    can && x.status === 'completed' ? btn('Raporu güncelle', () => recordForm('bc_exercises', x, {only: ['report', 'lessons_learned'], onsaved: reload}), 'secondary') : null], 'Tatbikat');
};

function completeExercise(x, done) {
  const names = ['actual_date', 'achieved_recovery_minutes', 'outcome', 'lessons_learned', 'report'];
  const fields = names.map(n => META.field('bc_exercises', n));
  const values = {actual_date: x.planned_date <= today() ? x.planned_date : today(), outcome: 'successful'};
  const form = h('form', {class: 'formgrid'}, fields.map(f => inputFor('bc_exercises', f, values[f.name] ?? x[f.name])), h('div', {class: 'notice bad wide form-error hidden', role: 'alert'}));
  Modal.open('Tatbikatı sonuçlandır: ' + x.code, h('div', {}, h('p', {class: 'intro', text: `Hedef kurtarma süresi ${x.target_recovery_minutes ? x.target_recovery_minutes + ' dakika' : 'tanımlı değil'}. Sonuç ve alınan dersler zorunludur (ISO 22301 8.5); hedef aşıldıysa sonuç "başarılı" olamaz. Tamamlanan tatbikat değiştirilemez.`}), form), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Tatbikatı tamamla', async () => {
      const {data} = readForm(form, 'bc_exercises', fields);
      if (!data.lessons_learned) { showErrors(form, {lessons_learned: 'Bu alan zorunlu'}, 'Alınan dersleri yazın'); return; }
      for (const k of Object.keys(data)) if (data[k] === null) delete data[k];
      try { await api(`bc_exercises/${x.id}`, {method: 'PATCH', body: {...data, status: 'completed'}}); }
      catch (e) { showErrors(form, {}, e.message); throw e; }
      Modal.close(); toast('Tatbikat tamamlandı'); done();
    })], true);
}

// ------------------------------------------------------------------ doküman yönetimi (ISO 9001 7.5)
DETAILS.documents = async function documentDetail(id, tab) {
  await Promise.all(['processes', 'org_units'].map(r => list(r).catch(() => [])));
  let d; try { d = await api(`documents/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const can = canWrite('documents'); const reload = t => { refreshList('documents'); DETAILS.documents(id, t); };
  const act = body => api(`documents/${id}/transition`, {method: 'POST', body}).then(() => { toast('Kaydedildi'); reload(); });
  const status = d.status === 'active' ? 'published' : d.status;
  const isApprover = d.approver ? d.approver === S.me.username || S.me.role === 'ADMIN' : META.can('manage');
  const fileRow = f => h('li', {class: 'file-row'}, h('span', {}, h('strong', {text: f.file_name}), h('span', {class: 'cell-sub mono', text: `${sizeText(f.file_size)} · SHA-256 ${String(f.sha256).slice(0, 16)}…`})),
    btn('İndir', () => download(`documents/${id}/files/${f.id || f.file_id}`, f.file_name), 'ghost small'));
  const summary = () => h('div', {},
    statStrip([['Revizyon', d.current_revision ? 'Rev. ' + d.current_revision : 'Yayımlanmadı'], ['Yürürlük', fmt.date(d.effective_date)],
      ['Gözden geçirme', fmt.date(d.review_date), late(d.review_date) && status === 'published' ? 'bad' : ''], ['Gizlilik', META.option('documents', 'confidentiality', d.confidentiality)]]),
    status === 'in_review' ? h('div', {class: 'notice warn', text: `Onay bekliyor: ${d.pending_change || ''} (onaylayan: ${d.approver || 'Yönetici'})`}) : null,
    status === 'draft' && d.current_revision ? h('div', {class: 'notice', text: `Yeni revizyon hazırlanıyor. Yürürlükteki sürüm Rev. ${d.current_revision} olarak kalır.`}) : null,
    d.current_file ? section('Yürürlükteki dosya', h('ul', {class: 'mini'}, fileRow({...d.current_file, id: d.current_file.file_id}))) : null,
    section('Doküman', kv([['Kategori', display('documents', 'category', d.category)], ['Süreç', d.process_id ? h('a', {href: '#/r/processes/' + d.process_id, text: titleOf(refRecord('processes', d.process_id))}) : null],
      ['Birim', display('documents', 'org_unit_id', d.org_unit_id)], ['Sahip', d.owner], ['Onaylayan (atanmış)', d.approver], ['Hazırlayan', d.prepared_by],
      ['Gözden geçirme sıklığı', d.review_period_months ? d.review_period_months + ' ay' : null], ['Saklama süresi', d.retention_years ? d.retention_years + ' yıl' : null],
      ['Referans bağlantı', extLink(d.reference_url)], ['Açıklama', d.description]])));
  const revisions = () => d.revisions.length ? h('ul', {class: 'timeline'}, d.revisions.map(r => h('li', {},
    h('strong', {text: `Rev. ${r.revision} · ${fmt.date(r.effective_date)}`}), h('div', {text: r.change_summary}),
    h('div', {class: 'muted small', text: `Hazırlayan ${r.prepared_by} · onaylayan ${r.approved_by} · ${fmt.datetime(r.approved_at)}`}),
    r.file_id ? btn('Dosya: ' + r.file_name, () => download(`documents/${id}/files/${r.file_id}`, r.file_name), 'ghost small') : null)))
    : empty('Revizyon yok', 'İlk onayla Rev. 1 oluşur. Revizyon kayıtları değiştirilemez.');
  const files = () => h('div', {}, d.files.length ? h('ul', {class: 'mini'}, d.files.map(fileRow)) : h('div', {class: 'muted small', text: 'Dosya yok'}),
    can && status === 'draft' ? h('p', {}, uploadButton()) : null);
  const relations = () => h('div', {},
    hasModule('grc') ? section(`Karşıladığı standart maddeleri (${d.clauses.length})`, recordList('clauses', d.clauses.map(c => ({...c, title: `${c.title} (${c.standard})`})), {none: 'Madde eşlemesi yok'}),
      can ? btn('Maddeleri seç', async () => {
        const ids = await pickClauses('Dokümanın karşıladığı maddeler', d.clauses.map(c => ({id: c.id, standard_id: c.standard_id})), {intro: 'Dokümanın karşıladığı standart maddelerini seçin.'});
        if (ids) { await api(`documents/${id}/clauses`, {method: 'POST', body: {clause_ids: ids}}); toast('Madde eşlemesi kaydedildi'); reload('relations'); }
      }, 'ghost small') : null) : null,
    hasModule('grc') ? section(`Bağlı kontroller (${d.controls.length})`, recordList('controls', d.controls, {none: 'Kontrol yok. Kontrol eşlemesi kontrol ekranından yapılır.'})) : null,
    hasModule('continuity') ? section(`Süreklilik planları (${d.plans.length})`, recordList('bc_plans', d.plans, {none: 'Plan yok'})) : null);
  function uploadButton() {
    const input = h('input', {type: 'file', accept: '.pdf,.docx,.xlsx,.pptx,.txt,.md,.png,.jpg', class: 'hidden'});
    input.addEventListener('change', async () => {
      const file = input.files[0]; if (!file) return;
      if (file.size > 12 * 1024 * 1024) { toast('Dosya 12 MB sınırını aşıyor', false); return; }
      try { await api(`documents/${id}/files`, {method: 'POST', body: {file_name: file.name, content_base64: await fileToBase64(file)}}); toast('Dosya yüklendi'); reload('files'); }
      catch (e) { toast(e.message, false); }
    });
    return h('span', {}, input, btn('Dosya yükle', () => input.click(), 'secondary small'));
  }
  const buttons = [];
  if (can && status === 'draft') buttons.push(btn('Düzenle', () => recordForm('documents', d, {onsaved: () => reload()}), 'secondary'), uploadButton(),
    btn('Onaya gönder', () => transition('Onaya gönder: ' + d.code, 'Değişiklik özetini yazın (ne değişti, neden). Onaylayan kişi dokümanı inceleyip yayımlar; hazırlayan kendi dokümanını onaylayamaz.',
      'Değişiklik özeti', 'Gönder', note => act({action: 'submit', change_summary: note}))));
  if (status === 'in_review' && isApprover && d.prepared_by !== S.me.username) buttons.push(
    btn('Reddet', () => transition('Reddet: ' + d.code, 'Doküman taslağa döner; gerekçe hazırlayana iletilir.', 'Ret gerekçesi', 'Reddet', note => act({action: 'reject', note})), 'secondary'),
    btn('Onayla ve yayımla', () => confirmDialog('Doküman yayımlansın mı?', 'Yeni revizyon bugünden itibaren yürürlüğe girer; önceki revizyon geçmişte kalır.', 'Yayımla').then(ok => ok && act({action: 'approve'}))));
  if (can && status === 'published') buttons.push(btn('Düzenle', () => recordForm('documents', d, {only: ['owner', 'approver', 'process_id', 'org_unit_id', 'confidentiality', 'review_period_months', 'retention_years', 'review_date', 'description'],
    onsaved: () => reload()}), 'secondary'), btn('Yeni revizyon başlat', () => act({action: 'revise'})));
  if (META.can('manage') && ['published', 'draft', 'in_review'].includes(status)) buttons.push(btn('Geçersiz kıl', () => transition('Geçersiz kıl: ' + d.code,
    'Geçersiz kılınan doküman kullanımdan kalkar; revizyon geçmişi saklanır (ISO 9001 7.5.3).', 'Gerekçe', 'Geçersiz kıl', note => act({action: 'obsolete', note})), 'ghost'));
  Drawer.open(d.code + ' · ' + d.title, h('div', {}, h('div', {class: 'chips'}, display('documents', 'status', status), display('documents', 'category', d.category),
    d.version ? h('span', {class: 'chip', text: d.version}) : null), h('br'),
  tabs([{key: 'summary', label: 'Özet', render: summary}, {key: 'revisions', label: 'Revizyonlar', count: d.revisions.length, render: revisions},
    {key: 'files', label: 'Dosyalar', count: d.files.length, render: files}, {key: 'relations', label: 'İlişkiler', render: relations}], tab)), buttons, 'Doküman');
};

// ------------------------------------------------------------------ CMDB
const RULE_INFO = {os_eos: 'İşletim sistemi destek süresi bitti', app_eos: 'Uygulama / ürün destek süresi bitti', patch: 'Kritik yama eksik veya gecikmiş', uptime: 'Uzun süredir yeniden başlatılmadı'};
PAGES.cmdb = async function cmdbBoard() {
  const admin = S.me.role === 'ADMIN';
  setPage('CMDB Panosu', 'ServiceNow CMDB\'den gelen uygulama ve altyapı öğeleri. Kurallar destek dışı işletim sistemi ve uygulamaları, eksik kritik yamaları ve uzun süredir yeniden başlatılmayan sunucuları bulur, şirket bazında kurumsal risk açar.');
  const d = await api('cmdb/status');
  setPage('CMDB Panosu', 'ServiceNow CMDB\'den gelen uygulama ve altyapı öğeleri. Kurallar destek dışı işletim sistemi ve uygulamaları, eksik kritik yamaları ve uzun süredir yeniden başlatılmayan sunucuları bulur, şirket bazında kurumsal risk açar.', [
    admin ? btn('ServiceNow\'dan senkronize et', async () => { const r = await api('cmdb/sync', {method: 'POST', body: {}}); toast(`Senkron (${r.channel === 'mcp' ? 'MCP' : 'Table API'}): ${r.created || 0} yeni, ${r.updated || 0} güncellendi${r.errors && r.errors.length ? ', ' + r.errors.length + ' hata' : ''}`, r.status !== 'failed'); PAGES.cmdb(); }, '', {disabled: !d.channel, title: d.channel ? '' : 'ServiceNow bağlantısı yapılandırılmadı'}) : null,
    admin && d.mcp && d.mcp.configured ? btn('MCP bağlantısını sına', () => mcpTest(), 'secondary') : null,
    admin ? btn('Kuralları değerlendir', async () => { const r = await api('cmdb/evaluate', {method: 'POST', body: {}}); toast(`${r.opened} yeni maruziyet, ${r.resolved} giderildi, ${r.risks_created} risk açıldı`); PAGES.cmdb(); }, 'secondary') : null]);
  const exp = Object.fromEntries(d.exposures.map(x => [x.key, x.count]));
  const conn = d.servicenow.configured
    ? h('div', {class: 'notice success', text: `ServiceNow bağlı (Table API): ${d.servicenow.instance} (${d.servicenow.auth === 'token' ? 'belirteç' : 'kullanıcı'} ile). Senkron her gece zamanlanmış görevle de çalışır.`})
    : d.mcp && d.mcp.configured
      ? h('div', {class: 'notice success', text: `ServiceNow MCP sunucusu yapılandırıldı: ${d.mcp.host} (${d.mcp.auth === 'oauth' ? 'OAuth istemci kimlik bilgisi' : 'bearer belirteç'}), CMDB aracı "${d.mcp.tool}". Senkron her gece zamanlanmış görevle de çalışır; "MCP bağlantısını sına" sunucudaki araçları gösterir.`})
      : h('div', {class: 'notice warn'}, h('strong', {text: 'ServiceNow bağlantısı yapılandırılmadı. '}),
        'Gösterilen öğeler MCP ile itilen veya elle girilen kayıtlardır. İki bağlantı yolu vardır: ServiceNow Table API (TEDARIK_SN_INSTANCE) veya ServiceNow MCP sunucusu (TEDARIK_SN_MCP_URL). Eşleme ve kurallar Politika Parametreleri\'nde (cmdb.servicenow, cmdb.mcp, cmdb.rules) durur; ayrıntı docs/DAGITIM.md.');
  const runs = d.last_runs.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Başlangıç', 'Kaynak', 'Mod', 'Durum', 'Yeni', 'Güncellenen', 'Değişmeyen', 'Bayat'].map((t, i) => h('th', {class: i > 3 ? 'num' : '', text: t})))),
    h('tbody', {}, d.last_runs.map(r => h('tr', {class: 'clickable', onclick: () => openRecord('cmdb_sync_runs', r.id)}, h('td', {text: fmt.datetime(r.started_at)}), h('td', {}, display('cmdb_sync_runs', 'source', r.source)),
      h('td', {}, display('cmdb_sync_runs', 'mode', r.mode)), h('td', {}, display('cmdb_sync_runs', 'status', r.status)),
      ...['created', 'updated', 'unchanged', 'stale_marked'].map(k => h('td', {class: 'num', text: r[k]}))))))) : empty('Senkron çalıştırması yok', '');
  const rules = d.rules; const env = (rules.environments || []).map(e => META.option('cmdb_cis', 'environment', e)).join(', ');
  content(conn,
    h('div', {class: 'cards'},
      metric('Konfigürasyon öğesi', fmt.num(d.total, 0), `${d.stale} bayat (kaynakta bulunamadı)`, d.stale ? 'warn' : '', () => Router.go('r/cmdb_cis')),
      metric('Açık maruziyet', fmt.num(d.exposures.reduce((a, x) => a + x.count, 0), 0), 'Kurallarla bulunan riskli CI', d.exposures.length ? 'bad' : 'good', () => Router.go('r/ci_exposures?status=open')),
      metric('Şirketi eşlenmemiş', fmt.num(d.unmapped_company, 0), 'Risk açılamaz; şirket eşleyin', d.unmapped_company ? 'warn' : 'good', () => Router.go('r/cmdb_cis?company_id__null=1')),
      metric('Son senkron', d.last_runs[0] ? fmt.date(d.last_runs[0].started_at) : '—', d.last_runs[0] ? META.option('cmdb_sync_runs', 'status', d.last_runs[0].status) : 'Henüz çalışmadı', '', () => Router.go('r/cmdb_sync_runs'))),
    h('div', {class: 'grid two'},
      panel('Kural bazında maruziyet', h('div', {}, ['os_eos', 'app_eos', 'patch', 'uptime'].map(k => h('button', {type: 'button', class: 'rule-row', onclick: () => Router.go(`r/ci_exposures?status=open&rule=${k}`)},
        h('span', {class: 'rule-count' + (exp[k] ? ' bad' : ''), text: exp[k] || 0}), h('span', {}, h('strong', {text: META.option('ci_exposures', 'rule', k)}), h('span', {class: 'cell-sub', text: RULE_INFO[k]})),
        rules[k]?.enabled === false ? pill('Kapalı', 'neutral') : null)),
      h('p', {class: 'muted small', text: `Kapsam: ${env || 'üretim'} ortamı, çalışır durumdaki öğeler. Yama eşiği ${rules.patch?.max_days ?? 35} gün, yeniden başlatma eşiği ${rules.uptime?.max_days ?? 100} gün.`}))),
      panel('Sınıfa göre öğeler', barChart(d.counts.map(c => ({label: META.option('cmdb_cis', 'ci_class', c.key), value: c.count, key: c.key})), {format: v => fmt.num(v, 0),
        onclick: item => Router.go('r/cmdb_cis?ci_class=' + item.key)}))),
    panel('Son senkron çalıştırmaları', runs));
};
async function mcpTest() {
  Modal.open('ServiceNow MCP bağlantı sınaması', h('div', {class: 'empty', text: 'Sunucuya bağlanılıyor…'}));
  let r; try { r = await api('cmdb/mcp/test', {method: 'POST', body: {}}); } catch (e) { Modal.close(); toast(e.message, false); return; }
  Modal.open('ServiceNow MCP bağlantı sınaması', h('div', {},
    h('div', {class: 'notice ' + (r.ok ? 'success' : 'bad'), text: r.ok ? `Bağlantı kuruldu: ${r.url_host}${r.server && r.server.info.name ? ' · ' + r.server.info.name : ''}` : `Bağlantı sınaması başarısız: ${r.url_host}`}),
    h('ul', {class: 'mini'}, r.steps.map(x => h('li', {}, pill(x.ok ? 'Uygun' : 'Hata', x.ok ? 'good' : 'bad'), ' ', h('strong', {text: x.step}), h('span', {class: 'cell-sub', text: x.detail})))),
    r.tools.length ? section(`Sunucudaki araçlar (${r.tools.length})`, h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Araç', 'Parametreler', 'Açıklama'].map(t => h('th', {text: t})))),
      h('tbody', {}, r.tools.map(t => h('tr', {class: t.name === r.tool ? 'selected' : ''}, h('td', {class: 'cell-primary', text: t.name}), h('td', {text: t.parameters.join(', ')}), h('td', {text: t.description}))))))) : null,
    h('p', {class: 'muted small', text: 'Kullanılacak araç, argüman şablonu ve kayıt yolu Politika Parametreleri\'nde cmdb.mcp kaydındadır. Sınama veri yazmaz.'})), [], true);
}
DETAILS.cmdb_cis = async function ciDetail(id) {
  await Promise.all(['companies', 'suppliers'].map(r => list(r).catch(() => [])));
  let c; try { c = await api(`cmdb_cis/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('cmdb_cis'); DETAILS.cmdb_cis(id); };
  const synced = ['servicenow', 'mcp'].includes(c.source);
  const eos = (label, d) => d ? h('span', {}, fmt.date(d), ' ', d < today() ? pill('Destek bitti', 'bad') : pill(dueText(d), 'neutral')) : null;
  const body = h('div', {}, h('div', {class: 'chips'}, display('cmdb_cis', 'ci_class', c.ci_class), c.environment ? display('cmdb_cis', 'environment', c.environment) : null,
    c.business_criticality ? display('cmdb_cis', 'business_criticality', c.business_criticality) : null, display('cmdb_cis', 'operational_status', c.operational_status),
    c.stale ? pill('Kaynakta bulunamadı', 'warn') : null, pill(META.option('cmdb_cis', 'source', c.source), 'purple')), h('br'),
    c.exposures.filter(x => x.status === 'open').length ? h('div', {class: 'notice bad'}, c.exposures.filter(x => x.status === 'open').map(x => h('div', {text: `${META.option('ci_exposures', 'rule', x.rule)}: ${x.detail}`}))) : null,
    section('Kimlik', kv([['Şirket', display('cmdb_cis', 'company_id', c.company_id)], ['Sahip', c.owner], ['Destek grubu', c.support_group], ['Tedarikçi', display('cmdb_cis', 'supplier_id', c.supplier_id)],
      ['FQDN / IP', [c.fqdn, c.ip_address].filter(Boolean).join(' · ')], ['Lokasyon', c.location], ['ServiceNow sys_id', c.sys_id ? h('span', {class: 'mono', text: c.sys_id}) : null], ['Açıklama', c.description]])),
    section('Yaşam döngüsü ve bakım', kv([['İşletim sistemi', [c.os, c.os_version].filter(Boolean).join(' ')], ['İS destek bitişi', eos('İS', c.os_eos_date)],
      ['Ürün / sürüm', [c.vendor, c.version].filter(Boolean).join(' ')], ['Ürün destek bitişi', eos('Ürün', c.eos_date)],
      ['Son yama', c.last_patch_date ? `${fmt.date(c.last_patch_date)} (${-Math.round((parseDay(c.last_patch_date) - parseDay(today())) / 86400000)} gün önce)` : null],
      ['Eksik kritik yama', c.missing_critical_patches], ['Son açılış', c.last_boot_at ? `${fmt.datetime(c.last_boot_at)} (${Math.round((Date.now() - new Date(c.last_boot_at)) / 86400000)} gün)` : null],
      ['Son görülme', fmt.datetime(c.last_seen_at)]])),
    section(`Bağımlılıklar`, h('div', {}, c.parents.length ? h('div', {class: 'small muted', text: 'Bu öğeyi kullananlar'}) : null, recordList('cmdb_cis', c.parents, {sub: x => x.rel_type, none: ''}),
      c.children.length ? h('div', {class: 'small muted', text: 'Bu öğenin bağımlı olduğu öğeler'}) : null, recordList('cmdb_cis', c.children, {sub: x => x.rel_type, none: c.parents.length ? '' : 'İlişki kaydı yok'}))),
    section(`Riskler (${c.risks.length})`, recordList('supplier_risks', c.risks, {chips: r => [levelPill(r.risk_level), pill(r.link_source === 'rule' ? 'CMDB kuralı' : 'Elle', r.link_source === 'rule' ? 'purple' : 'neutral')], none: 'Bağlı risk yok'})),
    section(`Bu uygulamaya bağımlı BİA'lar (${c.bias.length})`, recordList('bias', c.bias, {chips: b => [b.criticality ? display('bias', 'criticality', b.criticality) : null], none: 'BİA bağımlılığı yok'})),
    section(`Maruziyet geçmişi (${c.exposures.length})`, recordList('ci_exposures', c.exposures.map(x => ({...x, title: META.option('ci_exposures', 'rule', x.rule)})),
      {sub: x => `${x.detail || ''} · tespit ${fmt.date(x.detected_at)}${x.resolved_at ? ' · giderildi ' + fmt.date(x.resolved_at) : ''}`, chips: x => [display('ci_exposures', 'status', x.status)], none: 'Maruziyet yok'})));
  Drawer.open(c.code + ' · ' + c.name, body, [canWrite('cmdb_cis') ? btn('Düzenle', () => recordForm('cmdb_cis', c, {only: synced ? ['company_id', 'supplier_id', 'description'] : undefined, onsaved: reload,
    extra: synced ? h('div', {class: 'notice wide', text: 'Kaynaktan gelen alanlar senkronla güncellenir; burada yalnızca yerel alanlar (şirket, tedarikçi, açıklama) değişir.'}) : null}), 'secondary') : null], 'Konfigürasyon öğesi');
};

// ------------------------------------------------------------------ süreç haritası (ISO 9001 4.4)
const BANDS = [['management', 'Yönetim süreçleri', 'Yön verir, izler ve iyileştirir'], ['core', 'Ana (değer) süreçler', 'Müşteriye değer üretir'], ['support', 'Destek süreçleri', 'Kaynak ve altyapı sağlar']];
PAGES['process-map'] = async function processMap() {
  setPage('Süreç Haritası', 'ISO 9001 süreç yaklaşımı: yönetim, ana ve destek süreçleri ile her sürecin riskleri, kontrolleri, dokümanları ve iş etki analizi. Bir sürece tıklayarak ayrıntısını açın.', [
    canWrite('processes') ? btn('+ Süreç', () => createRecord('processes')) : null, btn('Liste', () => Router.go('r/processes'), 'secondary')]);
  const d = await api('processes-map');
  const top = d.processes.filter(p => !p.parent_id && p.active !== 0);
  const children = id => d.processes.filter(p => p.parent_id === id);
  const card = p => {
    const kids = children(p.id);
    const tags = [p.risks ? h('span', {class: 'tag' + (p.high_risks ? ' bad' : ''), text: `${p.risks} risk${p.high_risks ? ` (${p.high_risks} yüksek)` : ''}`}) : null,
      p.controls ? h('span', {class: 'tag' + (p.failing_controls ? ' warn' : ' good'), text: `${p.controls} kontrol${p.failing_controls ? ` · ${p.failing_controls} başarısız` : ''}`}) : null,
      p.documents ? h('span', {class: 'tag', text: `${p.documents} doküman`}) : null,
      p.bia ? h('span', {class: 'tag ' + (p.bia.status !== 'approved' ? 'warn' : {critical: 'bad', high: 'warn'}[p.bia.criticality] || 'good'),
        text: `BİA: ${p.bia.criticality ? META.option('bias', 'criticality', p.bia.criticality) : '—'}${p.bia.status !== 'approved' ? ' (' + META.option('bias', 'status', p.bia.status).toLocaleLowerCase(TR) + ')' : ''}${p.bia.rto_hours !== null ? ' · RTO ' + hours(p.bia.rto_hours) : ''}`})
        : p.process_type === 'core' ? h('span', {class: 'tag warn', text: 'BİA yok'}) : null,
      p.suppliers ? h('span', {class: 'tag', text: `${p.suppliers} tedarikçi`}) : null].filter(Boolean);
    const b = h('button', {type: 'button', class: 'proc', title: [p.description, p.inputs ? 'Girdi: ' + p.inputs : null, p.outputs ? 'Çıktı: ' + p.outputs : null].filter(Boolean).join('\n')},
      h('span', {class: 'proc-code', text: p.code}), h('strong', {text: p.name}), h('span', {class: 'cell-sub', text: p.owner || 'Sahip atanmadı'}),
      kids.length ? h('span', {class: 'cell-sub', text: 'Alt süreçler: ' + kids.map(k => k.name).join(', ')}) : null, h('div', {class: 'meta'}, tags));
    b.addEventListener('click', () => openRecord('processes', p.id));
    return b;
  };
  const bands = BANDS.map(([key, title, hint]) => {
    const items = top.filter(p => p.process_type === key).sort((a, b) => (a.position ?? 99) - (b.position ?? 99) || a.name.localeCompare(b.name, TR));
    return h('div', {class: 'band ' + key}, h('h3', {}, title, h('span', {class: 'band-hint', text: ' · ' + hint})),
      items.length ? h('div', {class: 'row'}, items.map(card)) : h('div', {class: 'muted small', text: 'Bu türde süreç yok'}));
  });
  content(h('div', {class: 'landscape'}, bands[0], h('div', {class: 'flow'}, h('span', {text: '◀ Müşteri ve ilgili taraf gereksinimleri'}), h('span', {text: 'Müşteri memnuniyeti ve çıktılar ▶'})), bands[1], bands[2]),
    h('div', {class: 'legend'}, h('span', {}, h('i', {class: 'c3'}), 'Yüksek risk veya kritik BİA'), h('span', {}, h('i', {class: 'c2'}), 'Başarısız kontrol veya eksik BİA'),
      h('span', {}, h('i', {class: 'c1'}), 'Kontroller başarılı'), h('span', {class: 'muted', text: 'Kart üzerinde durunca girdi ve çıktılar görünür.'})));
};
DETAILS.processes = async function processDetail(id) {
  await list('org_units');
  let p; try { p = await api(`processes/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('processes'); DETAILS.processes(id); };
  const body = h('div', {}, h('div', {class: 'chips'}, display('processes', 'process_type', p.process_type), p.active ? null : pill('Pasif', 'neutral')), h('br'),
    statStrip([['Risk', p.risks.length, p.risks.some(r => ['high', 'critical'].includes(r.risk_level)) ? 'bad' : ''], ['Kontrol', p.controls.length], ['Doküman', p.documents.length],
      ['BİA', p.bias.length, !p.bias.length && p.process_type === 'core' ? 'warn' : '']]),
    section('Süreç', kv([['Sahip', p.owner], ['Birim', display('processes', 'org_unit_id', p.org_unit_id)], ['Üst süreç', p.parent ? h('a', {href: '#/r/processes/' + p.parent.id, text: p.parent.name}) : null],
      ['Girdiler', p.inputs], ['Çıktılar', p.outputs], ['Açıklama', p.description]])),
    p.children.length ? section(`Alt süreçler (${p.children.length})`, recordList('processes', p.children)) : null,
    section(`Kontrol hedefleri (${p.objectives.length})`, recordList('objectives', p.objectives, {none: 'Kontrol hedefi yok'})),
    section(`Kontroller (${p.controls.length})`, recordList('controls', p.controls, {chips: k => [k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral')], none: 'Kontrol yok'})),
    section(`Riskler (${p.risks.length})`, recordList('supplier_risks', p.risks, {chips: r => [levelPill(r.risk_level), display('supplier_risks', 'status', r.status)], none: 'Risk yok'}),
      canWrite('supplier_risks') ? btn('+ Risk', () => createRecord('supplier_risks', {process_id: id, entity_name: p.name}), 'ghost small') : null),
    hasModule('continuity') ? section(`İş etki analizleri (${p.bias.length})`, recordList('bias', p.bias, {chips: b => [b.criticality ? display('bias', 'criticality', b.criticality) : null, display('bias', 'status', b.status)],
      none: p.process_type === 'core' ? 'Ana süreç için BİA yapılmadı (ISO 22301 8.2.2)' : 'BİA yok'}), canWrite('bias') ? btn('+ BİA', () => createRecord('bias', {process_id: id, title: p.name + ' BİA'}), 'ghost small') : null) : null,
    section(`Dokümanlar (${p.documents.length})`, recordList('documents', p.documents, {chips: d => [display('documents', 'status', d.status)], none: 'Doküman yok'})),
    hasModule('grc') ? section(`Denetimler (${p.audits.length})`, recordList('audits', p.audits, {sub: a => fmt.date(a.planned_start), chips: a => [display('audits', 'status', a.status)],
      open: a => Router.go('audit/' + a.id), none: p.process_type === 'core' ? 'Bu ana süreç henüz bir denetimin kapsamında değil (ISO 9001 9.2)' : 'Denetim yok'})) : null,
    p.findings.length ? section(`Bulgular (${p.findings.length})`, recordList('findings', p.findings, {chips: f => [display('findings', 'severity', f.severity), display('findings', 'status', f.status)]})) : null,
    p.engagements.length ? section(`Tedarikçi angajmanları (${p.engagements.length})`, recordList('engagements', p.engagements)) : null);
  Drawer.open(p.code + ' · ' + p.name, body, [canWrite('processes') ? btn('Düzenle', () => recordForm('processes', p, {onsaved: reload}), 'secondary') : null], 'Süreç');
};
DETAILS.objectives = async function objectiveDetail(id) {
  await list('processes');
  let o; try { o = await api(`objectives/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('objectives'); DETAILS.objectives(id); }; const e = o.effectiveness;
  const pct = e.tested ? Math.round(100 * e.passed / e.tested) : null;
  const body = h('div', {},
    statStrip([['Kontrol', e.controls, e.controls ? '' : 'bad'], ['Test edilen', e.tested], ['Başarılı', e.passed, pct === null ? '' : pct >= 85 ? 'good' : 'warn'], ['Etkinlik', pct === null ? '—' : '%' + pct]]),
    !e.controls ? h('div', {class: 'notice bad', text: 'Bu hedefe hizmet eden kontrol yok: hedef karşılanmıyor. Kontrol ekranından eşleyin.'}) : null,
    section('Hedef', kv([['Süreç', o.process ? h('a', {href: '#/r/processes/' + o.process.id, text: `${o.process.code} · ${o.process.name}`}) : null], ['Sahip', o.owner], ['Açıklama', o.description]])),
    section(`Ele aldığı riskler (${o.risks.length})`, recordList('supplier_risks', o.risks, {chips: r => [levelPill(r.risk_level), display('supplier_risks', 'status', r.status)], none: 'Risk eşlemesi yok'}),
      canWrite('objectives') ? btn('Riskleri seç', async () => {
        const all = await list('supplier_risks', true);
        const ids = await pickMany('Kontrol hedefinin ele aldığı riskler', all.filter(r => r.status !== 'closed'), o.risks.map(r => r.id), {label: r => `${r.code} · ${r.title}`});
        if (ids) { await api(`objectives/${id}/risks`, {method: 'POST', body: {risk_ids: ids}}); toast('Risk eşlemesi kaydedildi'); reload(); }
      }, 'ghost small') : null),
    section(`Kontroller (${o.controls.length})`, recordList('controls', o.controls, {sub: k => `${META.option('controls', 'execution_mode', k.execution_mode)} · ${META.option('controls', 'frequency', k.frequency)}`,
      chips: k => [k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral'), k.active ? null : pill('Pasif', 'neutral')], none: 'Kontrol yok'})));
  Drawer.open(o.code + ' · ' + o.name, body, [canWrite('objectives') ? btn('Düzenle', () => recordForm('objectives', o, {onsaved: reload}), 'secondary') : null], 'Kontrol hedefi');
};
// madde detayı: grc.js (ilişkiler, etki, değerlendirme yöntemi)

// ------------------------------------------------------------------ ilişki haritası
PAGES.map = async function relationMap() {
  setPage('İlişki Haritası', 'Platformdaki kayıt türleri ve aralarındaki bağlar: süreç, risk, kontrol, hedef, madde, bulgu, BİA, plan, CI ve tedarikçi. Bir kutunun üzerine gelin veya tıklayın; bağlı olduğu türler vurgulanır. Çift tıklama listeyi açar.');
  const d = await api('model');
  const BOX_W = 158, BOX_H = 48, GAP = 18, ROW_H = 70, LEFT = 150, TOP = 14, PAD = 14;
  const avail = Math.max(720, ($('content').clientWidth || 1100) - (innerWidth > 1280 ? 316 : 0));
  const perRow = Math.max(3, Math.floor((avail - LEFT - 20) / (BOX_W + GAP)));
  const bands = d.groups.map(g => ({...g, items: d.entities.filter(e => e.position[0] === g.key).sort((a, b) => a.position[1] - b.position[1])})).filter(b => b.items.length);
  const pos = {}; let width = 0; let y0 = TOP;
  for (const b of bands) {
    b.y = y0; b.rows = Math.ceil(b.items.length / perRow); b.h = b.rows * ROW_H + PAD;
    b.items.forEach((e, i) => {
      const x = LEFT + (i % perRow) * (BOX_W + GAP); const y = y0 + PAD / 2 + Math.floor(i / perRow) * ROW_H + (ROW_H - BOX_H) / 2;
      pos[e.name] = {x, y, cx: x + BOX_W / 2, cy: y + BOX_H / 2, e}; width = Math.max(width, x + BOX_W + 16);
    });
    y0 += b.h + 8;
  }
  const height = y0 + 4;
  const svg = s('svg', {viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-label': 'Kayıt türleri arasındaki ilişkiler'});
  for (const b of bands) {
    const [main, extra] = b.label.split(' (');
    svg.append(s('rect', {x: 4, y: b.y, width: width - 8, height: b.h, rx: 10, class: 'map-band'}),
      s('text', {x: 16, y: b.y + b.h / 2 - (extra ? 3 : -4), class: 'map-band-label'}, main.toLocaleUpperCase(TR)),
      extra ? s('text', {x: 16, y: b.y + b.h / 2 + 12, class: 'map-band-sub'}, '(' + extra) : null);
  }
  const edgeLayer = s('g'); const boxLayer = s('g'); svg.append(edgeLayer, boxLayer);
  const edges = [];
  for (const r of d.relations) {
    const a = pos[r.from], b = pos[r.to]; if (!a || !b) continue;
    let path;
    if (r.from === r.to) path = `M${a.x + BOX_W} ${a.cy - 8} c 26 -18, 26 34, 0 16`;
    else if (Math.abs(a.cy - b.cy) < 2) { const lift = 26 + Math.abs(a.cx - b.cx) / 9; path = `M${a.cx} ${a.y} C ${a.cx} ${a.y - lift}, ${b.cx} ${b.y - lift}, ${b.cx} ${b.y}`; }
    else { const down = b.cy > a.cy; const y1 = down ? a.y + BOX_H : a.y; const y2 = down ? b.y : b.y + BOX_H; const m = (y1 + y2) / 2; path = `M${a.cx} ${y1} C ${a.cx} ${m}, ${b.cx} ${m}, ${b.cx} ${y2}`; }
    const el = s('path', {d: path, class: 'map-edge' + (r.kind === 'M:N' ? ' mn' : r.kind === 'hierarchy' ? ' hier' : '')}, s('title', {}, `${a.e.label} → ${b.e.label} (${r.kind}${r.via ? ', ' + r.via : ''})`));
    edges.push({el, r}); edgeLayer.append(el);
  }
  const info = h('div', {class: 'map-info'}, h('p', {class: 'muted small', text: 'Bir türü seçin: ilişkileri burada listelenir.'}));
  let selected = null;
  const highlight = name => {
    const near = new Set([name]);
    for (const {el, r} of edges) { const on = name && (r.from === name || r.to === name); el.classList.toggle('on', !!on); el.classList.toggle('dim', !!name && !on); if (on) { near.add(r.from); near.add(r.to); } }
    for (const p of Object.values(pos)) { p.node.classList.toggle('dim', !!name && !near.has(p.e.name)); p.node.classList.toggle('sel', p.e.name === name); }
  };
  const describe = name => {
    if (!name) { info.replaceChildren(h('p', {class: 'muted small', text: 'Bir türü seçin: ilişkileri burada listelenir.'})); return; }
    const e = pos[name].e; const rel = d.relations.filter(r => r.from === name || r.to === name);
    const kindText = {'1:N': 'bire çok', 'M:N': 'çoka çok', hierarchy: 'hiyerarşi'};
    info.replaceChildren(h('h3', {text: e.label}), h('p', {class: 'muted small', text: `${fmt.num(e.count, 0)} kayıt · ${rel.length} ilişki`}),
      h('ul', {class: 'mini'}, rel.map(r => { const other = r.from === name ? r.to : r.from; const o = pos[other]?.e;
        return h('li', {class: 'link', onclick: () => select(other)}, h('strong', {text: o ? o.label : other}),
          h('span', {class: 'cell-sub', text: `${r.from === name ? 'bağlandığı tür' : 'kendisine bağlanan tür'} · ${kindText[r.kind] || r.kind}${r.via ? ' · ' + r.via : ''}`})); })),
      h('p', {}, btn('Listeyi aç', () => Router.go('r/' + name), 'secondary small')));
  };
  const select = name => { selected = selected === name ? null : name; highlight(selected); describe(selected); };
  for (const p of Object.values(pos)) {
    const label = p.e.label.length > 24 ? p.e.label.slice(0, 23) + '…' : p.e.label;
    const g = s('g', {class: 'map-box', tabindex: '0', role: 'button', 'aria-label': `${p.e.label}: ${p.e.count} kayıt`},
      s('rect', {x: p.x, y: p.y, width: BOX_W, height: BOX_H, rx: 8}), s('text', {x: p.x + 12, y: p.y + 21}, label), s('text', {x: p.x + 12, y: p.y + 38, class: 'cnt'}, `${fmt.num(p.e.count, 0)} kayıt`));
    g.addEventListener('mouseenter', () => { if (!selected) highlight(p.e.name); });
    g.addEventListener('mouseleave', () => { if (!selected) highlight(null); });
    g.addEventListener('click', () => select(p.e.name));
    g.addEventListener('dblclick', () => Router.go('r/' + p.e.name));
    g.addEventListener('keydown', ev => { if (ev.key === 'Enter') select(p.e.name); });
    p.node = g; boxLayer.append(g);
  }
  if (pos.supplier_risks) select('supplier_risks');       // açılışta risk kaydının bağlantıları vurgulanır
  content(h('div', {class: 'map-layout'}, h('div', {class: 'map-wrap'}, svg), h('div', {class: 'panel map-side'}, info,
    h('div', {class: 'legend'}, h('span', {}, h('i', {class: 'line solid'}), 'Bire çok (yabancı anahtar)'), h('span', {}, h('i', {class: 'line dashed'}), 'Çoka çok (eşleme tablosu)'),
      h('span', {}, h('i', {class: 'line dotted'}), 'Hiyerarşi (üst kayıt)')))));
};


// ------------------------------------------------------------------ denetim arşivi (geçmiş denetim, sonuç ve kanıt)
function evidenceChip(e) {
  const label = `${e.code}${e.version ? ' · s' + e.version : ''} · ${e.title}`;
  const b = h('button', {type: 'button', class: 'chip ev-chip' + (e.restricted ? ' restricted' : ''), title: e.sha256 ? 'SHA-256 ' + e.sha256 : label,
    text: (e.restricted ? '🔒 ' : '') + label});
  b.addEventListener('click', () => (e.restricted ? toast('Kısıtlı kanıt: yalnızca Yönetici, Denetçi ve yükleyen görebilir', false) : openRecord('evidence', e.id)));
  return b;
}
function resultTable(results, {showAudit = false} = {}) {
  if (!results.length) return h('div', {class: 'muted small', text: 'Bu kapsamda kayıtlı test sonucu yok'});
  return h('div', {class: 'tablewrap'}, h('table', {class: 'archive-table'}, h('thead', {}, h('tr', {}, [showAudit ? 'Denetim' : null, 'Kontrol', 'Madde', 'Sonuç', 'Tarih', 'Sunulan kanıt']
    .filter(Boolean).map(t => h('th', {text: t})))),
  h('tbody', {}, results.map(r => h('tr', {},
    showAudit ? h('td', {}, r.audit_code ? h('a', {href: '#/audit/' + r.audit_id, text: r.audit_code}) : h('span', {class: 'muted', text: 'Denetim dışı'})) : null,
    h('td', {class: 'cell-primary'}, h('a', {href: '#/r/controls/' + r.control_id, text: r.control_code}), h('span', {class: 'cell-sub', text: r.control_name}),
      r.details ? h('span', {class: 'cell-sub detail-text', text: r.details}) : null),
    h('td', {}, r.clause_codes.length ? h('div', {class: 'chips'}, r.clause_codes.map(c => h('span', {class: 'chip', text: c}))) : h('span', {class: 'muted', text: '—'})),
    h('td', {}, resultPill(r.status), h('span', {class: 'cell-sub', text: META.option('executions', 'source', r.source)})),
    h('td', {}, fmt.date(r.executed_at), h('span', {class: 'cell-sub', text: r.recorded_by}), h('button', {type: 'button', class: 'btn ghost small', text: 'Ayrıntı', onclick: () => showExecution(r.execution_id)})),
    h('td', {}, r.evidence.length ? h('div', {class: 'chips'}, r.evidence.map(evidenceChip)) : h('span', {class: 'muted small', text: 'Kanıt bağlanmadı'})))))));
}
function auditCard(a) {
  const counts = Object.entries(a.counts || {}).map(([k, v]) => `${RESULT_LABEL[k] || k}: ${v}`).join(' · ');
  return h('div', {class: 'panel archive-audit'},
    h('div', {class: 'panel-title'}, h('div', {},
      h('h3', {}, h('a', {href: '#/audit/' + a.id, text: `${a.code} · ${a.name}`})),
      h('div', {class: 'chips'}, display('audits', 'status', a.status), display('audits', 'kind', a.kind), a.opinion ? display('audits', 'opinion', a.opinion) : null,
        h('span', {class: 'chip', text: `${fmt.date(a.actual_start || a.planned_start)} – ${fmt.date(a.actual_end || a.planned_end)}`}),
        a.lead_auditor ? h('span', {class: 'chip', text: 'Baş denetçi: ' + a.lead_auditor}) : null)),
      h('span', {class: 'muted small', text: counts})),
    a.conclusion ? h('p', {class: 'intro', text: 'Sonuç: ' + a.conclusion}) : null,
    resultTable(a.results),
    a.evidence.length ? h('div', {class: 'archive-extra'}, h('span', {class: 'muted small', text: 'Denetime bağlı diğer kanıtlar: '}), h('div', {class: 'chips'}, a.evidence.map(evidenceChip))) : null,
    a.findings.length ? h('div', {class: 'archive-extra'}, h('span', {class: 'muted small', text: 'Bulgular: '}), h('div', {class: 'chips'}, a.findings.map(f =>
      h('a', {class: 'chip', href: '#/r/findings/' + f.id, text: `${f.code} · ${f.title}`})))) : null);
}
PAGES.archive = async function archivePage(parts, params) {
  await list('standards');
  const q0 = params.get('q') || ''; const std0 = params.get('standard_id') || ''; const clause0 = params.get('clause_id') || '';
  setPage('Denetim Arşivi', 'Bir standart maddesi (ör. A.5.19, 8.3.4, ISO 27001 5.22) veya konu (ör. yedekleme, erişim, sözleşme) yazın: hangi denetimde hangi kontrol test edildi, sonuç ne oldu ve hangi kanıt (hangi sürüm) sunuldu. Kayıtlar değiştirilemez sonuçlardan gelir.');
  const input = h('input', {type: 'search', class: 'searchbar archive-q', placeholder: 'Madde kodu veya konu…', value: q0, 'aria-label': 'Arşivde ara'});
  const std = h('select', {class: 'compact', 'aria-label': 'Standart'}, h('option', {value: '', text: 'Tüm standartlar'}),
    (S.cache.standards || []).map(x => h('option', {value: x.id, text: `${x.code} ${x.version || ''}`, selected: String(x.id) === std0})));
  const go = () => { const p = new URLSearchParams(); if (input.value.trim()) p.set('q', input.value.trim()); if (std.value) p.set('standard_id', std.value); Router.go('archive' + (p.toString() ? '?' + p : '')); };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  std.addEventListener('change', go);
  const examples = h('div', {class: 'chips'}, h('span', {class: 'muted small', text: 'Örnek: '}), ['A.5.19', 'ISO 27001 5.22', '8.3.4', 'yedekleme', 'erişim', 'sözleşme'].map(x =>
    h('button', {type: 'button', class: 'chip', text: x, onclick: () => { input.value = x; go(); }})));
  const head = h('div', {class: 'panel'}, h('div', {class: 'toolbar'}, h('div', {class: 'filters'}, input, std, btn('Ara', go)), examples));
  if (!q0 && !std0 && !clause0) { content(head, empty('Aramaya başlayın', 'Madde kodu veya konu yazın; geçmiş denetimler, test sonuçları ve sunulan kanıtlar burada listelenir.')); setTimeout(() => input.focus(), 30); return; }
  const query = new URLSearchParams(); if (q0) query.set('q', q0); if (std0) query.set('standard_id', std0); if (clause0) query.set('clause_id', clause0);
  content(head, h('div', {class: 'empty', text: 'Aranıyor…'}));
  const d = await api('assurance/search?' + query);
  const sm = d.summary;
  const blocks = [head, statStrip([['Denetim', sm.audits], ['Test sonucu', sm.results], ['Kanıt', sm.evidence], ['Bulgu', sm.findings]])];
  if (sm.truncated) blocks.push(h('div', {class: 'notice warn', text: 'Çok sayıda sonuç var; en yeni sonuçlar gösteriliyor. Aramayı standart veya madde ile daraltın.'}));
  if (d.clauses.length) blocks.push(h('div', {class: 'panel'}, h('h3', {text: `Eşleşen maddeler (${d.clauses.length})`}), h('div', {class: 'chips'}, d.clauses.map(c =>
    h('a', {class: 'chip' + (c.applicable ? '' : ' muted'), href: '#/r/clauses/' + c.id, title: c.title, text: `${c.standard_code} ${c.code} · ${c.title}`}))),
    d.controls.length ? h('p', {class: 'muted small', text: `Eşli kontroller: ${d.controls.map(k => k.code).join(', ')}`}) : null));
  if (!sm.audits && !d.monitoring.length && !d.evidence.length) blocks.push(empty('Kayıt bulunamadı', 'Başka bir madde kodu veya konu deneyin. Madde kontrollerle eşlenmemişse sonuç görünmez.'));
  if (d.audits.length) blocks.push(h('div', {class: 'domain', text: 'Denetimler (en yeniden eskiye)'}), ...d.audits.map(auditCard));
  if (d.monitoring.length) blocks.push(h('div', {class: 'domain', text: 'Denetim dışı sürekli izleme sonuçları'}), h('div', {class: 'panel'}, resultTable(d.monitoring)));
  if (d.evidence.length) blocks.push(h('div', {class: 'domain', text: 'Kanıt kütüphanesi'}), h('div', {class: 'panel'}, h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kanıt', 'Gizlilik', 'Sürüm', 'Dönem', 'Geçerlilik', 'Kullanıldığı denetimler'].map(t => h('th', {text: t})))),
    h('tbody', {}, d.evidence.map(e => h('tr', {class: 'clickable', onclick: () => openRecord('evidence', e.id)}, h('td', {class: 'cell-primary', text: `${e.code} · ${e.title}`}),
      h('td', {}, display('evidence', 'confidentiality', e.confidentiality)), h('td', {text: e.current_version ? 's' + e.current_version : '—'}),
      h('td', {text: e.period_start ? `${fmt.date(e.period_start)} – ${fmt.date(e.period_end)}` : '—'}),
      h('td', {}, e.expires_at ? h('span', {class: late(e.expires_at) ? 'over' : '', text: fmt.date(e.expires_at)}) : '—'),
      h('td', {}, e.audits.length ? h('div', {class: 'chips'}, e.audits.map(c => h('span', {class: 'chip', text: c}))) : h('span', {class: 'muted small', text: 'Denetimde kullanılmadı'})))))))));
  if (d.findings.length) blocks.push(h('div', {class: 'domain', text: 'Denetim dışı bulgular'}), h('div', {class: 'panel'}, recordList('findings', d.findings, {chips: f => [display('findings', 'severity', f.severity), display('findings', 'status', f.status)]})));
  content(...blocks);
};
async function auditHistoryPanel(audit) {
  const box = h('div', {class: 'panel'}, h('h3', {text: 'Bu kapsamın geçmişi'}), h('div', {class: 'muted small', text: 'Yükleniyor…'}));
  api(`audits/${audit.id}/history`).then(hist => {
    const prev = hist.previous;
    const controls = audit.controls.filter(c => (hist.controls[c.id] || []).length);
    box.replaceChildren(h('div', {class: 'panel-title'}, h('h3', {text: 'Bu kapsamın geçmişi'}),
      h('a', {class: 'btn ghost small', href: '#/archive?' + new URLSearchParams(audit.clauses.length === 1 ? {clause_id: audit.clauses[0].id} : {q: audit.name}), text: 'Arşivde ara →'})),
      prev.length ? h('ul', {class: 'mini'}, prev.map(p => h('li', {class: 'link', onclick: () => Router.go('audit/' + p.id)},
        h('strong', {text: `${p.code} · ${p.name}`}),
        h('span', {class: 'cell-sub', text: `${fmt.date(p.actual_start || p.planned_start)} · ortak: ${[p.overlap.clauses ? p.overlap.clauses + ' madde' : null, p.overlap.processes ? p.overlap.processes + ' süreç' : null, p.overlap.controls ? p.overlap.controls + ' kontrol' : null].filter(Boolean).join(', ')} · ${p.findings} bulgu`}),
        h('div', {class: 'chips'}, display('audits', 'status', p.status), p.opinion ? display('audits', 'opinion', p.opinion) : null,
          ...Object.entries(p.counts).map(([k, v]) => pill(`${RESULT_LABEL[k] || k} ${v}`, {pass: 'good', fail: 'bad'}[k] || 'neutral'))))))
        : h('div', {class: 'muted small', text: 'Bu kapsamı içeren önceki denetim yok.'}),
      controls.length ? h('p', {class: 'muted small', text: `${controls.length} kontrolün önceki sonuçları var; kontrol satırındaki "Geçmiş" düğmesi önceki sonuçları ve sunulan kanıtları gösterir.`}) : null);
    document.querySelectorAll('[data-history]').forEach(b => {
      const items = hist.controls[b.dataset.history] || [];
      b.classList.toggle('hidden', !items.length);
      b.addEventListener('click', () => Modal.open('Önceki sonuçlar: ' + items[0].control_code, h('div', {}, h('p', {class: 'intro', text: items[0].control_name}),
        resultTable(items.map(r => ({...r, clause_codes: r.clause_codes || []})), {showAudit: true})), [], true));
    });
  }).catch(e => box.replaceChildren(h('h3', {text: 'Bu kapsamın geçmişi'}), h('div', {class: 'notice bad', text: e.message})));
  return box;
}

// ------------------------------------------------------------------ komut paleti (Ctrl+K)
function openPalette() {
  if (!S.meta) return;
  const input = h('input', {class: 'pal-input', type: 'search', placeholder: 'Ekran veya kayıt arayın (en az 2 harf)…', 'aria-label': 'Ara', autocomplete: 'off'});
  const listEl = h('ul', {class: 'pal-list', role: 'listbox'});
  const pages = MENU.flatMap(([group, items]) => items.filter(navVisible).map(([key, ico, label]) => ({key, ico, group, label: label || META.def(key.slice(2))?.label || key})));
  let rows = []; let active = 0; let seq = 0;
  const fold = t => t.toLocaleLowerCase(TR).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i');
  const draw = (records = []) => {
    const q = fold(input.value.trim());
    const pageHits = pages.filter(p => !q || fold(p.label + ' ' + p.group).includes(q)).slice(0, q ? 8 : 12);
    rows = [...pageHits.map(p => ({kind: 'page', ...p})), ...records.map(r => ({kind: 'record', ...r}))];
    active = Math.min(active, Math.max(0, rows.length - 1));
    clear(listEl);
    if (pageHits.length) listEl.append(h('li', {class: 'pal-group', text: 'Ekranlar'}));
    rows.forEach((r, i) => {
      if (r.kind === 'record' && (i === 0 || rows[i - 1].kind !== 'record')) listEl.append(h('li', {class: 'pal-group', text: 'Kayıtlar'}));
      const li = h('li', {class: i === active ? 'on' : '', role: 'option', 'aria-selected': String(i === active)},
        r.kind === 'page' ? icon(r.ico) : icon('file'), h('span', {text: r.kind === 'page' ? r.label : [r.code, r.title].filter(Boolean).join(' · ')}),
        h('span', {class: 'kind', text: r.kind === 'page' ? r.group : r.resource_label}));
      li.addEventListener('click', () => choose(r)); li.addEventListener('mousemove', () => { if (active !== i) { active = i; mark(); } });
      listEl.append(li);
    });
    if (!rows.length) listEl.append(h('li', {class: 'pal-group', text: q.length >= 2 ? 'Sonuç yok' : 'Yazmaya başlayın'}));
  };
  const mark = () => listEl.querySelectorAll('li[role=option]').forEach((li, i) => { li.classList.toggle('on', i === active); li.setAttribute('aria-selected', String(i === active)); if (i === active) li.scrollIntoView({block: 'nearest'}); });
  const choose = r => { Modal.close(); if (r.kind === 'page') Router.go(r.key); else Router.go(`r/${r.resource}/${r.id}`); };
  const search = debounce(async () => {
    const q = input.value.trim(); const mine = ++seq;
    if (q.length < 2 || !hasModule('insights')) { draw(); return; }
    const res = await maybe(api('search?q=' + encodeURIComponent(q)));
    if (mine === seq) draw(res ? res.results : []);
  }, 180);
  input.addEventListener('input', () => { active = 0; draw(rows.filter(r => r.kind === 'record')); search(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(rows.length - 1, active + 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); mark(); }
    else if (e.key === 'Enter' && rows[active]) { e.preventDefault(); choose(rows[active]); }
  });
  Modal.open('Hızlı arama', h('div', {id: 'palette'}, input, listEl, h('div', {class: 'pal-foot muted small', text: '↑↓ seç · Enter aç · Esc kapat'})));
  draw();
  setTimeout(() => input.focus(), 40);
}

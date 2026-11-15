'use strict';
/* Güvence ve uyum ekranları (K-026): kanıt talepleri, çalışma kâğıtları, yönetim yanıtı, denetim raporu, yıllık denetim
   planı, yükümlülük envanteri, politika istisnaları, okundu beyanı, uygulanabilirlik bildirimi (SoA), dış denetçi.
   app.js, pages.js ve grc.js yardımcılarını kullanır; satır içi stil yok (CSP). */

const isAssurance = () => ['ADMIN', 'AUDITOR'].includes(S.me.role) && !S.me.external;
const ymd = (n = 0) => today(n);

// ------------------------------------------------------------------ kanıt talepleri
async function requestEvidence(audit, controls, done) {
  const users = await api('directory').catch(() => []);
  const due = h('input', {type: 'date', id: 'erDue', value: ymd(10), min: ymd()});
  const rows = controls.map(k => {
    const sel = h('select', {'aria-label': 'Talep edilen kişi: ' + k.code}, h('option', {value: '', text: '— Kişi seçin —'}),
      users.map(u => h('option', {value: u.username, text: u.display_name || u.username, selected: u.username === k.owner})));
    const box = h('input', {type: 'checkbox', checked: true, 'aria-label': k.code});
    return {k, sel, box, node: h('div', {class: 'tree-row'}, h('label', {}, box, h('span', {}, h('b', {text: k.code}), ' ', k.name)), sel)};
  });
  Modal.open('Kanıt iste: ' + audit.code, h('div', {},
    h('p', {class: 'intro', text: 'Kontrol başına tek talep açılır. Talep metninde kanıtın hangi standart maddelerine sayılacağı yazılır; kişi aynı kanıtı her madde için ayrı ayrı sunmaz.'}),
    h('label', {class: 'field', for: 'erDue'}, 'Teslim tarihi', h('div', {class: 'control'}, due)),
    h('div', {class: 'choices tall'}, rows.map(r => r.node))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Talepleri oluştur', async () => {
      const items = rows.filter(r => r.box.checked).map(r => ({control_id: r.k.id, assignee: r.sel.value || null}));
      if (!items.length) throw new Error('En az bir kontrol seçin');
      const out = await api('evidence_requests/bulk', {method: 'POST', body: {audit_id: audit.id, due_date: due.value, items}});
      Modal.close(); toast(`${out.created.length} talep oluşturuldu` + (out.skipped.length ? `, ${out.skipped.length} kontrolün açık talebi zaten var` : '')); done && done();
    })], true);
}
function requestSteps(status) {
  const steps = ['requested', 'submitted', 'accepted'];
  const at = status === 'rejected' ? 0 : steps.indexOf(status);
  return h('div', {class: 'steps'}, steps.map((st, i) => h('span', {class: 'step' + (i === at ? ' on' : i < at ? ' done' : '')},
    h('b', {text: i < at ? '✓' : String(i + 1)}), META.option('evidence_requests', 'status', st))));
}
async function submitEvidence(req, done) {
  const cands = await api(`evidence_requests/${req.id}/candidates`).catch(() => []);
  const file = h('input', {type: 'file', id: 'erFile'}); const note = h('textarea', {id: 'erNote', placeholder: 'Kanıt neyi gösteriyor, hangi dönemi kapsıyor?'});
  const conf = h('select', {id: 'erConf'}, ['internal', 'confidential', 'restricted'].map(v => h('option', {value: v, text: META.option('evidence', 'confidentiality', v)})));
  let picked = null;
  const list = cands.length ? h('div', {class: 'choices'}, cands.map(e => h('label', {}, h('input', {type: 'radio', name: 'erPick', onchange: () => { picked = e.id; }}),
    h('span', {}, h('b', {text: e.code}), ' ', e.title, h('span', {class: 'muted small', text: e.expires_at ? ` · geçerli ${fmt.date(e.expires_at)}` : ''}))))) : null;
  Modal.open('Kanıtı teslim et: ' + req.code, h('div', {},
    h('div', {class: 'notice small', text: req.description || req.title}),
    list ? section('Mevcut güncel kanıtı kullan (yeniden yüklemeden)', list) : null,
    section(list ? 'veya yeni dosya yükleyin' : 'Dosya', h('div', {class: 'formgrid'},
      h('label', {class: 'field wide', for: 'erFile'}, 'Dosya', h('div', {class: 'control'}, file)),
      h('label', {class: 'field', for: 'erConf'}, 'Gizlilik', h('div', {class: 'control'}, conf)))),
    h('label', {class: 'field', for: 'erNote'}, 'Not', h('div', {class: 'control'}, note))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Teslim et', async () => {
      let body = {note: note.value.trim() || null};
      if (picked && !file.files[0]) body.evidence_id = picked;
      else { if (!file.files[0]) throw new Error('Dosya seçin veya mevcut kanıtı işaretleyin'); body = {...body, file_name: file.files[0].name, content_base64: await fileToBase64(file.files[0]), confidentiality: conf.value}; }
      await api(`evidence_requests/${req.id}/submit`, {method: 'POST', body}); Modal.close(); toast('Kanıt teslim edildi'); done();
    })], true);
}
DETAILS.evidence_requests = async function requestDetail(id) {
  await loadRefs('evidence_requests');
  let r; try { r = await api('evidence_requests/' + id); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('evidence_requests'); DETAILS.evidence_requests(id); };
  const mine = r.assignee === S.me.username; const open = ['requested', 'rejected'].includes(r.status);
  const body = h('div', {}, requestSteps(r.status),
    r.status === 'rejected' ? h('div', {class: 'notice warn', text: 'İade edildi: ' + (r.review_note || '')}) : null,
    open && late(r.due_date) ? h('div', {class: 'notice bad', text: 'Teslim tarihi geçti.'}) : null,
    section('Talep', kv([['İstenen', h('div', {class: 'clause-text', text: r.description || r.title})], ['Talep edilen', r.assignee], ['Talep eden', r.requested_by],
      ['Teslim tarihi', fmt.date(r.due_date)], ['Denetim', r.audit_id ? h('a', {href: '#/audit/' + r.audit_id + '?tab=requests', text: titleOf(refRecord('audits', r.audit_id)) || '#' + r.audit_id}) : null],
      ['Kontrol', r.control_id ? h('a', {href: '#/r/controls/' + r.control_id, text: titleOf(refRecord('controls', r.control_id)) || '#' + r.control_id}) : null]])),
    r.evidence_id ? section('Teslim', kv([['Kanıt', h('a', {href: '#/r/evidence/' + r.evidence_id, text: 'Kanıtı aç'})], ['Not', r.response_note], ['Teslim', fmt.datetime(r.submitted_at)],
      ['İnceleyen', r.reviewed_by], ['İnceleme notu', r.review_note]])) : null);
  const buttons = [
    open && (mine || isAssurance()) ? btn('Kanıtı teslim et', () => submitEvidence(r, reload)) : null,
    r.status === 'submitted' && isAssurance() && !mine ? btn('Kabul et', async () => { await api(`evidence_requests/${id}/review`, {method: 'POST', body: {decision: 'accept'}}); toast('Kanıt kabul edildi'); reload(); }) : null,
    r.status === 'submitted' && isAssurance() && !mine ? btn('İade et', () => transition('Kanıtı iade et: ' + r.code, 'Neyin eksik olduğunu yazın; kişi aynı talebe yeniden teslim eder.', 'İade gerekçesi', 'İade et',
      note => api(`evidence_requests/${id}/review`, {method: 'POST', body: {decision: 'reject', note}}).then(reload)), 'secondary') : null,
    isAssurance() && !['accepted', 'cancelled'].includes(r.status) ? btn('İptal et', () => transition('Talebi iptal et', 'Gerekçe inceleme notuna yazılır.', 'Gerekçe', 'İptal et',
      note => api(`evidence_requests/${id}/cancel`, {method: 'POST', body: {note}}).then(reload), {required: false}), 'ghost') : null];
  Drawer.open(r.code + ' · ' + r.title, body, buttons, 'Kanıt talebi');
};

// ------------------------------------------------------------------ çalışma kâğıtları
const WP_FIELDS = ['title', 'control_id', 'objective', 'procedure', 'sample', 'sample_size', 'exceptions_found', 'result', 'conclusion'];
CREATE.workpapers = defaults => recordForm('workpapers', null, {only: WP_FIELDS.concat(['audit_id']), defaults,
  onsaved: r => { refreshList('workpapers'); openRecord('workpapers', r.id); if (defaults.audit_id) render(); }});
DETAILS.workpapers = async function workpaperDetail(id) {
  await loadRefs('workpapers');
  let w; try { w = await api('workpapers/' + id); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('workpapers'); DETAILS.workpapers(id); };
  const editable = isAssurance() && ['draft', 'returned'].includes(w.status);
  const body = h('div', {}, h('div', {class: 'chips'}, display('workpapers', 'status', w.status), w.result ? resultPill(w.result) : null),
    w.status === 'returned' ? h('div', {class: 'notice warn', text: 'İade: ' + (w.review_note || '')}) : null,
    section('Çalışma kâğıdı', kv([['Denetim', w.audit_id ? h('a', {href: '#/audit/' + w.audit_id + '?tab=workpapers', text: titleOf(refRecord('audits', w.audit_id))}) : null],
      ['Kontrol', display('workpapers', 'control_id', w.control_id)], ['Test amacı', w.objective], ['Test adımları', w.procedure ? h('div', {class: 'clause-text', text: w.procedure}) : null],
      ['Örneklem', w.sample], ['Örnek büyüklüğü', w.sample_size], ['Bulunan istisna', w.exceptions_found], ['Kanaat', w.conclusion]])),
    section('Gözden geçirme (IIA 2340)', kv([['Hazırlayan', w.preparer], ['Gönderilme', fmt.datetime(w.prepared_at)], ['Gözden geçiren', w.reviewer], ['Zaman', fmt.datetime(w.reviewed_at)], ['Not', w.review_note]])));
  const buttons = [
    editable ? btn('Düzenle', () => recordForm('workpapers', w, {only: WP_FIELDS, onsaved: reload}), 'secondary') : null,
    editable ? btn('Gözden geçirmeye gönder', async () => { await api(`workpapers/${id}/submit`, {method: 'POST', body: {}}); toast('Gözden geçirmeye gönderildi'); reload(); }) : null,
    w.status === 'ready' && isAssurance() && w.preparer !== S.me.username ? btn('Onayla', async () => { await api(`workpapers/${id}/review`, {method: 'POST', body: {decision: 'approve'}}); toast('Onaylandı'); reload(); }) : null,
    w.status === 'ready' && isAssurance() && w.preparer !== S.me.username ? btn('İade et', () => transition('Çalışma kâğıdını iade et', 'Neyin düzeltilmesi gerektiğini yazın.', 'Gerekçe', 'İade et',
      note => api(`workpapers/${id}/review`, {method: 'POST', body: {decision: 'return', note}}).then(reload)), 'secondary') : null,
    w.status === 'ready' && w.preparer === S.me.username ? h('span', {class: 'muted small', text: 'Kendi kâğıdınızı başka bir denetçi gözden geçirir'}) : null];
  Drawer.open(w.code + ' · ' + w.title, body, buttons, 'Çalışma kâğıdı');
};

// ------------------------------------------------------------------ denetim çalışma alanı sekmeleri
AUDIT_TABS.splice(2, 0,
  {key: 'requests', label: 'Kanıt talepleri', count: a => (a.requests || []).length, render: (a, ctx) => {
    const r = a.requests || []; const open = ['planned', 'in_progress'].includes(a.status);
    const by = s => r.filter(x => x.status === s).length;
    return h('div', {},
      statStrip([['Toplam', fmt.num(r.length, 0)], ['Bekleniyor', fmt.num(by('requested') + by('rejected'), 0), by('requested') + by('rejected') ? 'warn' : ''],
        ['İncelemede', fmt.num(by('submitted'), 0), by('submitted') ? 'warn' : ''], ['Kabul', fmt.num(by('accepted'), 0), 'good']]),
      h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Talepler'}),
        canWrite('evidence_requests') && open ? btn('Plan kontrolleri için kanıt iste', () => requestEvidence(a, a.controls.filter(c => c.planned && c.active), ctx.reload), 'secondary small') : null),
        r.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kod', 'Kontrol', 'Talep edilen', 'Teslim', 'Durum'].map(t => h('th', {text: t})))),
          h('tbody', {}, r.map(x => h('tr', {class: 'clickable', onclick: () => openRecord('evidence_requests', x.id)}, h('td', {class: 'cell-primary', text: x.code}),
            h('td', {text: x.control_code || '—'}), h('td', {text: x.assignee}), h('td', {class: late(x.due_date) && ['requested', 'rejected'].includes(x.status) ? 'late' : '', text: fmt.date(x.due_date)}),
            h('td', {}, display('evidence_requests', 'status', x.status)))))))
          : empty('Kanıt talebi yok', 'Test planındaki her kontrol için tek talep açın; kanıt kontrolün eşlendiği tüm maddelere sayılır.')));
  }},
  {key: 'workpapers', label: 'Çalışma kâğıtları', count: a => (a.workpapers || []).length, render: a => {
    const w = a.workpapers || []; const open = ['planned', 'in_progress'].includes(a.status);
    return h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Çalışma kâğıtları'}),
      canWrite('workpapers') && open ? btn('+ Çalışma kâğıdı', () => createRecord('workpapers', {audit_id: a.id}), 'secondary small') : null),
      h('p', {class: 'muted small', text: 'Her kâğıt hazırlayandan farklı bir denetçi tarafından gözden geçirilir; gözden geçirilmemiş kâğıt varken denetim tamamlanamaz.'}),
      w.length ? h('ul', {class: 'mini'}, w.map(x => h('li', {class: 'link', onclick: () => openRecord('workpapers', x.id)}, h('strong', {text: `${x.code} · ${x.title}`}),
        h('span', {class: 'cell-sub', text: [x.control_code, 'hazırlayan ' + (x.preparer || '—'), x.reviewer ? 'gözden geçiren ' + x.reviewer : null].filter(Boolean).join(' · ')}),
        h('div', {class: 'chips'}, display('workpapers', 'status', x.status), x.result ? resultPill(x.result) : null)))) : empty('Çalışma kâğıdı yok', ''));
  }});

// ------------------------------------------------------------------ bulgu: yönetim yanıtı
function responseSection(f, reload) {
  const canRespond = f.owner === S.me.username || META.can('manage');
  const status = f.response_status;
  return section('Yönetim yanıtı', h('div', {},
    status ? h('div', {class: 'chips'}, display('findings', 'response_status', status), status === 'pending' && f.response_due ? pill('Son tarih ' + fmt.date(f.response_due), late(f.response_due) ? 'bad' : 'warn') : null) : h('div', {class: 'muted small', text: 'Yanıt istenmedi.'}),
    f.management_response ? h('p', {class: 'small', text: f.management_response}) : null,
    f.responded_by ? h('div', {class: 'muted small', text: `${f.responded_by} · ${fmt.datetime(f.responded_at)}`}) : null),
    h('span', {class: 'toolbar'},
      isAssurance() && !status ? btn('Yanıt iste', async () => { await api(`findings/${f.id}/request-response`, {method: 'POST', body: {}}); toast('Bulgu sahibinden yanıt istendi'); reload(); }, 'ghost small') : null,
      canRespond && ['open', 'in_progress'].includes(f.status) ? btn(f.management_response ? 'Yanıtı güncelle' : 'Yanıt ver', () => respondDialog(f, reload), 'ghost small') : null));
}
function respondDialog(f, done) {
  const st = h('select', {id: 'mrStatus'}, ['agreed', 'partially_agreed', 'disagreed'].map(v => h('option', {value: v, text: META.option('findings', 'response_status', v), selected: v === f.response_status})));
  const text = h('textarea', {id: 'mrText', value: f.management_response || '', placeholder: 'Katılıyorsanız eylem planı ve hedef tarih; katılmıyorsanız gerekçe.'});
  Modal.open('Yönetim yanıtı: ' + f.code, h('div', {}, h('p', {class: 'intro', text: f.title}),
    h('label', {class: 'field', for: 'mrStatus'}, 'Görüş', h('div', {class: 'control'}, st)), h('label', {class: 'field', for: 'mrText'}, 'Yanıt ve eylem planı', h('div', {class: 'control'}, text))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => { await api(`findings/${f.id}/response`, {method: 'POST', body: {response_status: st.value, management_response: text.value.trim()}}); Modal.close(); toast('Yanıt kaydedildi'); done(); })]);
}

// ------------------------------------------------------------------ denetim raporu
PAGES['audit-report'] = async function auditReport(parts) {
  const id = Number(parts[1]);
  const d = await api(`audits/${id}/report`); const a = d.audit; const s = d.summary;
  const summary = h('textarea', {class: 'report-summary', value: a.executive_summary || '', 'aria-label': 'Yönetici özeti'});
  setPage('Denetim raporu', `${a.code} · ${a.name}`, [btn('Yazdır / PDF', () => window.print(), 'secondary'),
    btn('Çalışma alanına dön', () => Router.go('audit/' + id), 'ghost')], [['Denetimler', 'r/audits'], [a.code, 'audit/' + id]]);
  const sev = s.findings_by_severity || {};
  const draftBtn = isAssurance() ? btn('Özet taslağı oluştur', async () => {
    const r = await api(`audits/${id}/report-draft`, {method: 'POST', body: {}});
    summary.value = r.ai ? r.ai.summary + (r.ai.key_messages.length ? '\n\n' + r.ai.key_messages.map(m => '• ' + m).join('\n') : '') : r.rules.summary;
    toast(r.ai ? 'Model taslağı hazır; gözden geçirip kaydedin' : 'Kural tabanlı taslak hazır' + (r.ai_note ? ' (' + r.ai_note + ')' : ''));
  }, 'ghost small') : null;
  content(h('article', {class: 'report'},
    h('header', {class: 'report-head'}, h('div', {}, h('div', {class: 'muted small', text: `${a.kind_label} · ${a.status_label}`}), h('h2', {text: a.name}),
      h('div', {class: 'small', text: `${a.code} · ${fmt.date(a.actual_start || a.planned_start)} – ${fmt.date(a.actual_end || a.planned_end)}`})),
      a.opinion_label ? h('div', {class: 'opinion'}, h('span', {class: 'muted small', text: 'Genel görüş'}), h('strong', {text: a.opinion_label})) : null),
    section('Yönetici özeti', h('div', {}, isAssurance() ? summary : h('p', {text: a.executive_summary || '—'}),
      isAssurance() ? h('div', {class: 'toolbar no-print'}, draftBtn, btn('Özeti kaydet', async () => { await api(`audits/${id}`, {method: 'PATCH', body: {executive_summary: summary.value.trim() || null}}); toast('Özet kaydedildi'); }, 'small')) : null)),
    section('Amaç, kapsam ve ekip', kv([['Amaç', a.audit_objective], ['Kapsam', a.scope], ['Standartlar', d.standards.map(x => `${x.code} ${x.version || ''} (${x.clauses} madde)`).join(' · ')],
      ['Süreçler', d.processes.join(', ')], ['Baş denetçi', a.lead_auditor], ['Denetçiler', a.auditors], ['Denetlenenler', a.auditees]])),
    statStrip([['Test edilen kontrol', fmt.num(s.tests, 0)], ['Başarılı', fmt.num(s.pass, 0), 'good'], ['Başarısız', fmt.num(s.fail, 0), s.fail ? 'bad' : ''],
      ['Test edilmeyen', fmt.num(s.untested, 0), s.untested ? 'warn' : ''], ['Bulgu', `${s.findings} (K${sev.critical || 0} · Y${sev.high || 0} · O${sev.medium || 0} · D${sev.low || 0})`]]),
    section(`Bulgular ve yönetim yanıtları (${d.findings.length})`, d.findings.length ? h('div', {}, d.findings.map(f => h('div', {class: 'report-finding'},
      h('div', {class: 'test-head'}, h('strong', {text: `${f.code} · ${f.title}`}), h('div', {class: 'chips'}, display('findings', 'severity', f.severity), display('findings', 'status', f.status))),
      f.description ? h('p', {class: 'small', text: f.description}) : null,
      kv([['Kök neden', f.root_cause], ['Etkilenen maddeler', f.clauses.join(', ')], ['Sorumlu / hedef', [f.owner, fmt.date(f.due_date)].filter(x => x && x !== '—').join(' · ')],
        ['Yönetim yanıtı', f.response_label ? `${f.response_label}: ${f.management_response || ''}` : 'Bekleniyor'],
        ['Düzeltici faaliyetler', f.actions.map(x => `${x.code} ${x.title} (${META.option('grc_actions', 'status', x.status)}, ${fmt.date(x.due_date)})`).join(' · ')]])))) : h('p', {class: 'muted', text: 'Bulgu yok.'})),
    section('Test sonuçları', h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kontrol', 'Sonuç'].map(t => h('th', {text: t})))),
      h('tbody', {}, d.tests.map(t => h('tr', {}, h('td', {text: `${t.code} · ${t.name}`}), h('td', {}, resultPill(t.result)))))))),
    a.conclusion ? section('Denetim sonucu', h('p', {text: a.conclusion})) : null,
    h('footer', {class: 'muted small', text: `${d.disclaimer} Üretim: ${fmt.datetime(d.generated_at)}.`})));
};

// ------------------------------------------------------------------ yıllık denetim planı
PAGES['audit-plan'] = async function auditPlanPage(parts, params) {
  const [plans, prios] = await Promise.all([api('audit_plans?order=-year'), api('audit_universe/priorities')]);
  const thisYear = new Date().getFullYear();
  const year = Number(params.get('year')) || (plans.some(p => p.year === thisYear) ? thisYear : plans[0] ? plans[0].year : thisYear);
  const plan = plans.find(p => p.year === year);
  const can = canWrite('audit_plans');
  setPage('Denetim Planı', 'Risk bazlı yıllık iç denetim planı: denetim evreni öncelik puanına göre sıralanır; plan kalemleri denetime dönüşür ve gerçekleşme izlenir.', [
    can ? btn('+ Denetlenebilir birim', () => createRecord('audit_universe'), 'secondary') : null,
    can && !plan ? btn(`${year} planını oluştur`, async () => { await api('audit_plans', {method: 'POST', body: {year, title: `${year} yılı iç denetim planı`}}); render(); }) : null]);
  let planNode = empty(`${year} planı yok`, 'Planı oluşturup öncelikli birimleri ekleyin.');
  if (plan) {
    const p = await api(`audit_plans/${plan.id}/context`);
    const PROG = {not_started: ['Başlamadı', 'neutral'], scheduled: ['Denetim açıldı', 'purple'], in_progress: ['Sürüyor', 'warn'], done: ['Tamamlandı', 'good'], deferred: ['Ertelendi', 'neutral'], cancelled: ['İptal', 'neutral']};
    const quarters = ['Q1', 'Q2', 'Q3', 'Q4'].map(q => h('div', {class: 'panel quarter'}, h('h3', {text: META.option('audit_plan_items', 'quarter', q)}),
      h('ul', {class: 'mini'}, p.items.filter(i => i.quarter === q).map(i => h('li', {}, h('strong', {text: i.universe_name}),
        h('span', {class: 'cell-sub', text: (i.rationale || '').slice(0, 160)}),
        h('div', {class: 'chips'}, pill(PROG[i.progress][0], PROG[i.progress][1]), pill('Puan ' + fmt.num(i.priority_score, 0), 'neutral'),
          i.audit_id ? h('a', {class: 'chip', href: '#/audit/' + i.audit_id, text: i.audit_code}) : can && p.status === 'approved' && i.status === 'planned' ? btn('Denetim aç', async () => {
            const r = await api(`audit_plan_items/${i.id}/start`, {method: 'POST', body: {}}); toast('Denetim açıldı; kapsamı seçin'); Router.go('audit/' + r.audit_id); }, 'ghost small') : null))))));
    planNode = h('div', {},
      h('div', {class: 'panel-title'}, h('h3', {}, `${p.code} · ${p.title} `, display('audit_plans', 'status', p.status)),
        h('div', {class: 'toolbar'}, can && p.status === 'draft' ? btn('Öncelikli birimleri ekle', async () => { const r = await api(`audit_plans/${p.id}/generate`, {method: 'POST', body: {limit: 12}}); toast(`${r.added} kalem eklendi`); render(); }, 'secondary') : null,
          S.me.role === 'ADMIN' && p.status === 'draft' && p.items.length ? btn('Planı onayla', async () => { await api(`audit_plans/${p.id}/approve`, {method: 'POST', body: {}}); toast('Plan onaylandı'); render(); }) : null)),
      p.approved_by ? h('div', {class: 'muted small', text: `Onaylayan: ${p.approved_by} · ${fmt.datetime(p.approved_at)}`}) : null,
      statStrip([['Kalem', fmt.num(p.items.length, 0)], ['Tamamlanan', fmt.num(p.counts.done || 0, 0), 'good'], ['Süren', fmt.num((p.counts.in_progress || 0) + (p.counts.scheduled || 0), 0)],
        ['Başlamayan', fmt.num(p.counts.not_started || 0, 0)], ['Gerçekleşme', fmt.pct(p.completion_pct)]]),
      h('div', {class: 'grid four'}, quarters));
  }
  const top = prios.slice(0, 15);
  content(
    h('div', {class: 'filters'}, h('label', {}, 'Yıl ', h('select', {class: 'compact', onchange: e => Router.go('audit-plan?year=' + e.target.value)},
      [...new Set([...plans.map(p => p.year), year, thisYear + 1])].sort().map(y => h('option', {value: y, text: y, selected: y === year}))))),
    h('div', {class: 'panel'}, planNode),
    panel('Denetim evreni — öncelik sırası', top.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Birim', 'Tür', 'Puan', 'Gerekçe'].map((t, i) => h('th', {class: i === 2 ? 'num' : '', text: t})))),
      h('tbody', {}, top.map(u => h('tr', {class: 'clickable', onclick: () => openRecord('audit_universe', u.universe_id)}, h('td', {class: 'cell-primary'}, u.name, u.due ? h('span', {class: 'cell-sub', text: 'Denetim zamanı geldi'}) : null),
        h('td', {}, display('audit_universe', 'entity_type', u.entity_type)), h('td', {class: 'num'}, h('strong', {text: fmt.num(u.score, 0)}), progressBar(u.score)),
        h('td', {class: 'small', text: u.reasons.join(' · ')})))))) : empty('Denetim evreni boş', 'Süreç, şirket, tedarikçi ve uygulamaları denetlenebilir birim olarak ekleyin.'),
      h('a', {class: 'btn ghost small', href: '#/r/audit_universe', text: 'Tümü →'})));
};

// ------------------------------------------------------------------ yükümlülükler
const OBL_STATE = {compliant: ['Uyumlu', 'good'], partial: ['Kısmen', 'warn'], non_compliant: ['Uyumsuz', 'bad'], not_assessed: ['Değerlendirilmedi', 'neutral']};
const oblPill = s => pill(OBL_STATE[s][0], OBL_STATE[s][1]);
PAGES.obligations = async function obligationsPage() {
  const d = await api('obligations/summary');
  setPage('Yükümlülük Envanteri', 'Mevzuat ve sözleşme yükümlülükleri madde bazında; uyum durumu eşlenen kontrollerin son test sonucundan ve açık bulgulardan türetilir.',
    [canWrite('obligations') ? btn('+ Yeni yükümlülük', () => createRecord('obligations')) : null, btn('Liste görünümü', () => Router.go('r/obligations'), 'secondary')]);
  const c = d.counts;
  const regs = Object.entries(d.by_regulator).map(([reg, v]) => h('tr', {}, h('td', {class: 'cell-primary', text: META.option('obligations', 'regulator', reg)}),
    ...['compliant', 'partial', 'non_compliant', 'not_assessed'].map(k => h('td', {class: 'num', text: v[k] || '·'}))));
  content(
    statStrip([['Uyumlu', fmt.num(c.compliant, 0), 'good'], ['Kısmen', fmt.num(c.partial, 0), c.partial ? 'warn' : ''], ['Uyumsuz', fmt.num(c.non_compliant, 0), c.non_compliant ? 'bad' : ''],
      ['Değerlendirilmedi', fmt.num(c.not_assessed, 0), c.not_assessed ? 'warn' : '']]),
    h('div', {class: 'grid two'},
      panel('Düzenleyiciye göre', regs.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Düzenleyici', 'Uyumlu', 'Kısmen', 'Uyumsuz', 'Bekleyen'].map((t, i) => h('th', {class: i ? 'num' : '', text: t})))), h('tbody', {}, regs))) : empty('Yükümlülük yok', '')),
      panel('Dikkat gerektirenler', h('ul', {class: 'mini'}, d.items.filter(o => o.state !== 'compliant').slice(0, 12).map(o => h('li', {class: 'link', onclick: () => openRecord('obligations', o.id)},
        h('strong', {text: `${o.code} · ${o.title}`}), h('span', {class: 'cell-sub', text: `${o.source}${o.article ? ' ' + o.article : ''}`}), h('div', {class: 'chips'}, oblPill(o.state),
          o.findings ? pill(o.findings + ' açık bulgu', 'bad') : null, o.controls ? null : pill('Kontrol yok', 'warn'))))))),
    panel(`Tüm yükümlülükler (${d.items.length})`, h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Kod', 'Yükümlülük', 'Kaynak', 'Düzenleyici', 'Kontrol', 'Durum'].map(t => h('th', {text: t})))),
      h('tbody', {}, d.items.map(o => h('tr', {class: 'clickable', onclick: () => openRecord('obligations', o.id)}, h('td', {class: 'cell-primary', text: o.code}), h('td', {text: o.title}),
        h('td', {class: 'small', text: `${o.source}${o.article ? ' · ' + o.article : ''}`}), h('td', {}, display('obligations', 'regulator', o.regulator)), h('td', {class: 'num', text: o.controls}), h('td', {}, oblPill(o.state)))))))));
};
DETAILS.obligations = async function obligationDetail(id) {
  let o; try { o = await api(`obligations/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('obligations'); DETAILS.obligations(id); };
  const can = canWrite('obligations');
  const editLinks = async () => {
    const controls = await list('controls', true);
    const picker = clausePicker(o.clauses.map(c => ({id: c.id})), {hint: 'Yükümlülüğün karşılığı olan standart maddeleri (ör. KVKK md.12 ↔ ISO/IEC 27701).'});
    const box = checklist(controls.filter(k => k.active), o.controls.map(k => k.id), {label: k => `${k.code} ${k.name}`});
    Modal.open('Eşlemeler: ' + o.code, tabs([{key: 'controls', label: 'Kontroller', render: () => box.node}, {key: 'clauses', label: 'Standart maddeleri', render: () => picker.node}]), [
      btn('Vazgeç', () => Modal.close(), 'secondary'),
      btn('Kaydet', async () => { await api(`obligations/${id}/links`, {method: 'POST', body: {controls: box.value(), clauses: picker.value()}}); Modal.close(); toast('Eşlemeler kaydedildi'); reload(); })], true);
  };
  const body = h('div', {}, h('div', {class: 'chips'}, oblPill(o.state), display('obligations', 'regulator', o.regulator), display('obligations', 'applicability', o.applicability), display('obligations', 'criticality', o.criticality)), h('br'),
    o.applicability === 'under_review' ? h('div', {class: 'notice warn', text: 'Mevzuat değişikliği nedeniyle inceleniyor: etkilenen kontrol, süreç ve dokümanlar aşağıda.'}) : null,
    section('Yükümlülük', kv([['Kaynak', `${o.source}${o.article ? ' · ' + o.article : ''}`], ['Türü', display('obligations', 'source_type', o.source_type)], ['Açıklama', o.description],
      ['Uymamanın sonucu', o.penalty], ['Sahip', o.owner], ['Şirket', display('obligations', 'company_id', o.company_id)], ['Yürürlük', fmt.date(o.effective_date)], ['Gözden geçirme', fmt.date(o.review_date)],
      ['Kaynak bağlantısı', o.reference_url ? extLink(o.reference_url) : null]])),
    section(`Karşılayan kontroller (${o.controls.length})`, recordList('controls', o.controls, {chips: k => [k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral')], none: 'Kontrol eşlenmedi'}),
      can ? btn('Eşlemeler', editLinks, 'ghost small') : null),
    o.clauses.length ? section(`Standart maddeleri (${o.clauses.length})`, h('div', {class: 'chips'}, o.clauses.map(c => h('a', {class: 'chip', href: '#', title: c.title, text: `${c.standard} ${c.code}`, onclick: e => { e.preventDefault(); DETAILS.clauses(c.id); }})))) : null,
    o.findings.length ? section(`Açık bulgular (${o.findings.length})`, recordList('findings', o.findings, {chips: f => [display('findings', 'severity', f.severity)]})) : null,
    o.exceptions.length ? section(`Geçerli istisnalar (${o.exceptions.length})`, recordList('policy_exceptions', o.exceptions, {sub: e => 'Bitiş ' + fmt.date(e.end_date)})) : null,
    o.processes.length ? section('Etkilenen süreçler', h('div', {class: 'chips'}, o.processes.map(p => h('a', {class: 'chip', href: '#/r/processes/' + p.id, text: p.name})))) : null,
    o.documents.length ? section('İlgili dokümanlar', recordList('documents', o.documents)) : null);
  Drawer.open(`${o.code} · ${o.title}`, body, can ? [btn('Değişiklik incelemesi', () => transition('Mevzuat değişikliği: ' + o.code, 'Ne değişti ve ne zaman yürürlüğe giriyor? Yükümlülük "inceleniyor" olur, sahibine bildirilir.', 'Değişiklik',
    'Kaydet', note => api(`obligations/${id}/change-review`, {method: 'POST', body: {note}}).then(reload)), 'ghost'),
    btn('Düzenle', () => recordForm('obligations', o, {onsaved: reload}), 'secondary')] : [], 'Yükümlülük');
};

// ------------------------------------------------------------------ politika istisnaları
CREATE.policy_exceptions = defaults => recordForm('policy_exceptions', null, {skip: ['code'], defaults: {start_date: ymd(), end_date: ymd(90), owner: S.me.username, risk_level: 'medium', ...defaults},
  extra: h('div', {class: 'notice wide', text: 'İstisna süreli ve gerekçelidir; yüksek/kritik istisnada telafi edici kontrol zorunludur. Talep eden onaylayamaz.'}),
  onsaved: r => { refreshList('policy_exceptions'); openRecord('policy_exceptions', r.id); }});
DETAILS.policy_exceptions = async function exceptionDetail(id) {
  await loadRefs('policy_exceptions');
  let x; try { x = await api('policy_exceptions/' + id); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('policy_exceptions'); DETAILS.policy_exceptions(id); };
  const days = Math.round((parseDay(x.end_date) - parseDay(ymd())) / 86400000);
  const body = h('div', {}, h('div', {class: 'chips'}, display('policy_exceptions', 'status', x.status), display('policy_exceptions', 'risk_level', x.risk_level),
    x.status === 'approved' ? pill(days >= 0 ? `${days} gün kaldı` : 'Süresi doldu', days <= 14 ? 'warn' : 'neutral') : null), h('br'),
    section('İstisna', kv([['Kapsam', x.scope], ['Gerekçe', x.justification], ['Telafi edici kontroller', x.compensating_controls],
      ['Politika', display('policy_exceptions', 'document_id', x.document_id)], ['Kontrol', display('policy_exceptions', 'control_id', x.control_id)],
      ['Yükümlülük', display('policy_exceptions', 'obligation_id', x.obligation_id)], ['İlgili risk', display('policy_exceptions', 'risk_id', x.risk_id)],
      ['Sahip', x.owner], ['Süre', `${fmt.date(x.start_date)} – ${fmt.date(x.end_date)}`]])),
    section('Karar', kv([['Talep eden', x.requested_by], ['Onaylayan', x.approver], ['Karar zamanı', fmt.datetime(x.decided_at)], ['Gerekçe', x.decision_note]])));
  const admin = S.me.role === 'ADMIN'; const self = [x.requested_by, x.owner].includes(S.me.username);
  const buttons = [
    x.status === 'requested' && canWrite('policy_exceptions') ? btn('Düzenle', () => recordForm('policy_exceptions', x, {skip: ['code'], onsaved: reload}), 'secondary') : null,
    x.status === 'requested' && admin && !self ? btn('Onayla', () => transition('İstisnayı onayla: ' + x.code, 'Onay gerekçesi değiştirilemez denetim izine yazılır.', 'Gerekçe', 'Onayla',
      note => api(`policy_exceptions/${id}/decide`, {method: 'POST', body: {decision: 'approve', note}}).then(reload))) : null,
    x.status === 'requested' && admin && !self ? btn('Reddet', () => transition('İstisnayı reddet: ' + x.code, '', 'Gerekçe', 'Reddet',
      note => api(`policy_exceptions/${id}/decide`, {method: 'POST', body: {decision: 'reject', note}}).then(reload)), 'secondary') : null,
    x.status === 'requested' && admin && self ? h('span', {class: 'muted small', text: 'Kendi talebinizi onaylayamazsınız'}) : null,
    x.status === 'approved' && admin ? btn('Geri al', () => transition('İstisnayı geri al: ' + x.code, 'İstisna hemen sona erer.', 'Gerekçe', 'Geri al',
      note => api(`policy_exceptions/${id}/revoke`, {method: 'POST', body: {note}}).then(reload)), 'ghost') : null];
  Drawer.open(x.code + ' · ' + x.title, body, buttons, 'Politika istisnası');
};

// ------------------------------------------------------------------ okundu beyanı
DETAILS.attestation_campaigns = async function campaignDetail(id) {
  let k; try { k = await api(`attestation_campaigns/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('attestation_campaigns'); DETAILS.attestation_campaigns(id); };
  const can = canWrite('attestation_campaigns'); const p = k.progress;
  const body = h('div', {}, h('div', {class: 'chips'}, display('attestation_campaigns', 'status', k.status), display('attestation_campaigns', 'audience', k.audience)), h('br'),
    p.total ? statStrip([['Hedef kişi', fmt.num(p.total, 0)], ['Beyan veren', fmt.num(p.acknowledged, 0), 'good'], ['Oran', fmt.pct(p.pct), p.pct >= 95 ? 'good' : 'warn'], ['Son tarih', fmt.date(k.due_date)]]) : null,
    section('Kampanya', kv([['Politika', k.document ? h('a', {href: '#/r/documents/' + k.document.id, text: `${k.document.code} · ${k.document.title}`}) : null], ['Revizyon', k.revision],
      ['Beyan metni', k.statement], ['Hedef birimler', k.units.map(u => u.name).join(', ')], ['Sonuç kanıtı', k.evidence_id ? h('a', {href: '#/r/evidence/' + k.evidence_id, text: 'Kanıtı aç'}) : null]])),
    k.people.length ? section('Kişiler', h('ul', {class: 'mini'}, k.people.slice(0, 200).map(x => h('li', {}, h('strong', {text: x.display_name || x.username}),
      h('div', {class: 'chips'}, display('attestations', 'status', x.status), x.acknowledged_at ? h('span', {class: 'muted small', text: fmt.datetime(x.acknowledged_at)}) : null))))) : null);
  const buttons = !can ? [] : [
    k.status === 'draft' ? btn('Düzenle', () => recordForm('attestation_campaigns', k, {onsaved: reload}), 'secondary') : null,
    k.status === 'draft' && k.audience === 'units' ? btn('Hedef birimler', async () => {
      const units = await list('org_units'); const ids = await pickMany('Hedef birimler', units, k.units.map(u => u.id));
      if (ids) { await api(`attestation_campaigns/${id}/units`, {method: 'POST', body: {org_unit_ids: ids}}); reload(); } }, 'secondary') : null,
    k.status === 'draft' ? btn('Başlat', async () => { if (!await confirmDialog('Kampanyayı başlat', 'Hedef kişilere beyan görevi atanır ve bildirim gider.', 'Başlat')) return;
      await api(`attestation_campaigns/${id}/launch`, {method: 'POST', body: {}}); toast('Kampanya başladı'); reload(); }) : null,
    k.status === 'open' ? btn('Kapat ve kanıt üret', async () => { if (!await confirmDialog('Kampanyayı kapat', 'Sonuç dosyası kanıt olarak kaydedilir ve politikaya eşli kontrollere bağlanır.', 'Kapat')) return;
      await api(`attestation_campaigns/${id}/close`, {method: 'POST', body: {}}); toast('Kampanya kapandı'); reload(); }) : null];
  Drawer.open(k.code + ' · ' + k.title, body, buttons, 'Okundu beyanı');
};
function acknowledgeDialog(item) {
  const box = h('input', {type: 'checkbox', id: 'ackBox'});
  Modal.open('Okundu beyanı', h('div', {}, h('p', {class: 'intro', text: item.title}),
    h('p', {}, h('a', {href: '#/r/documents/' + item.document_id, text: 'Politikayı aç ve oku →', onclick: () => Modal.close()})),
    h('blockquote', {class: 'statement', text: item.statement}), h('label', {class: 'toggle', for: 'ackBox'}, box, h('span', {text: 'Okudum, anladım ve uyacağımı beyan ederim.'}))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Beyan ver', async () => { if (!box.checked) throw new Error('Beyanı onaylayın'); await api(`attestations/${item.id}/acknowledge`, {method: 'POST', body: {confirm: true}}); Modal.close(); toast('Beyanınız kaydedildi'); render(); })]);
}

// ------------------------------------------------------------------ uygulanabilirlik bildirimi (SoA)
const SOA_STATE = {implemented: ['Uygulanıyor', 'good'], partial: ['Kısmen', 'warn'], not_implemented: ['Uygulanmıyor', 'bad'], not_applicable: ['Kapsam dışı', 'neutral']};
PAGES.soa = async function soaPage(parts, params) {
  const id = Number(parts[1]); const d = await api(`standards/${id}/soa`); const st = d.standard;
  const filter = params.get('state') || '';
  setPage('Uygulanabilirlik Bildirimi', `${st.code} ${st.version || ''} · ${st.name}`, [btn('CSV indir', () => download(`standards/${id}/soa?format=csv`, 'soa.csv'), 'secondary'), btn('Yazdır', () => window.print(), 'secondary')],
    [['Standart Kütüphanesi', 'library'], [stdName(st), 'standard/' + id]]);
  const rowsShown = d.rows.filter(r => !filter || r.state === filter);
  content(h('div', {class: 'notice small', text: d.note}),
    h('div', {class: 'stat-strip'}, Object.entries(SOA_STATE).map(([k, [label, cls]]) => h('button', {type: 'button', class: 'stat ' + (filter === k ? 'on ' : '') + cls,
      onclick: () => Router.go(`soa/${id}` + (filter === k ? '' : '?state=' + k))}, h('span', {class: 'stat-value', text: fmt.num(d.counts[k], 0)}), h('span', {class: 'stat-label', text: label})))),
    h('div', {class: 'panel'}, h('div', {class: 'tablewrap'}, h('table', {class: 'soa'}, h('thead', {}, h('tr', {}, ['Madde', 'Uygulanabilir / gerekçe', 'Kontroller ve son sonuç', 'Durum'].map(t => h('th', {text: t})))),
      h('tbody', {}, rowsShown.map(r => h('tr', {class: 'clickable', onclick: () => DETAILS.clauses(r.id)},
        h('td', {class: 'cell-primary'}, r.code, h('span', {class: 'cell-sub', text: r.title})),
        h('td', {}, r.applicable ? 'Evet' : h('span', {}, 'Hayır', h('span', {class: 'cell-sub', text: r.justification || ''}))),
        h('td', {}, r.controls.length ? h('div', {class: 'chips'}, r.controls.map(k => h('span', {class: 'chip', title: k.name}, k.code, ' ', k.last_status ? resultPill(k.last_status) : pill('test yok', 'neutral')))) : h('span', {class: 'muted', text: '—'}),
          r.exceptions.length ? h('div', {class: 'small', text: 'İstisna: ' + r.exceptions.join(', ')}) : null, r.documents.length ? h('div', {class: 'small muted', text: r.documents.join(' · ')}) : null),
        h('td', {}, pill(SOA_STATE[r.state][0], SOA_STATE[r.state][1]), r.open_findings ? h('span', {class: 'cell-sub', text: r.open_findings + ' açık bulgu'}) : null))))))));
};

// ------------------------------------------------------------------ kullanıcı formu: süreli erişim ve dış denetçi
async function accessForm(user, done) {
  const audits = await list('audits', true);
  const exp = h('input', {type: 'date', id: 'acExp', value: user.access_expires || '', min: ymd()});
  const ext = h('input', {type: 'checkbox', id: 'acExt', checked: !!user.external});
  const box = checklist(audits, user.audit_ids || [], {label: a => `${a.code} · ${a.name}`});
  Modal.open('Erişim süresi ve kapsam: ' + (user.display_name || user.username), h('div', {},
    h('p', {class: 'intro', text: 'Erişim sonu verilen hesap o tarihten sonra oturum açamaz. Dış denetçi hesabı salt okunurdur ve yalnızca seçilen denetimleri, onların bulgu ve kanıtlarını görür.'}),
    h('label', {class: 'field', for: 'acExp'}, 'Erişim sonu', h('div', {class: 'control'}, exp)),
    h('label', {class: 'toggle', for: 'acExt'}, ext, h('span', {text: 'Dış denetçi (salt okunur, denetim kapsamlı)'})),
    h('div', {class: 'field'}, 'Görebileceği denetimler', box.node)), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => { await api('users/' + user.id, {method: 'PATCH', body: {access_expires: exp.value || null, external: ext.checked ? 1 : 0, audit_ids: box.value()}}); Modal.close(); toast('Erişim kaydedildi'); done(); })], true);
}

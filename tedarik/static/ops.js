'use strict';
/* Risk, olay ve süreklilik ekranları (K-027): nicel risk (TL), kayıp olayları, KVKK ihlali (72 saat), öz değerlendirme
   (RCSA), erişim gözden geçirme, kriz odası ve üst uyarı bandı, DÖF → ServiceNow. Satır içi stil yok (CSP). */

const TL = v => v === null || v === undefined ? '—' : new Intl.NumberFormat(TR, {style: 'currency', currency: 'TRY', maximumFractionDigits: 0}).format(Number(v));
const TL_SHORT = v => { const n = Number(v || 0); return n >= 1e9 ? fmt.num(n / 1e9, 1) + ' Mr TL' : n >= 1e6 ? fmt.num(n / 1e6, 1) + ' M TL' : n >= 1e3 ? fmt.num(n / 1e3, 0) + ' B TL' : fmt.num(n, 0) + ' TL'; };

// ------------------------------------------------------------------ üst uyarı bandı (etkin kriz, ihlal süresi)
async function alertBand() {
  let band = document.getElementById('alertBand');
  if (!band) { band = h('div', {id: 'alertBand', class: 'alert-band hidden', role: 'alert'}); $('main').prepend(band); }
  const items = [];
  if (hasModule('continuity')) for (const k of await api('bc_incidents/active').catch(() => [])) items.push(h('a', {href: '#/crisis/' + k.id},
    h('strong', {text: 'KRİZ MODU'}), ` ${k.code} · ${k.title} · lider ${k.commander} · ${META.option('bc_incidents', 'status', k.status)}`));
  if (META.def('privacy_breaches')) for (const b of await api('privacy_breaches/open').catch(() => [])) if (b.needs_action) items.push(h('a', {href: '#/r/privacy_breaches/' + b.id},
    h('strong', {text: 'KVKK İHLALİ'}), ` ${b.code} · ${b.title} · ` + (b.remaining_hours < 0 ? `bildirim süresi ${Math.round(-b.remaining_hours)} saat önce doldu` : `bildirim için ${Math.round(b.remaining_hours)} saat kaldı`)));
  band.replaceChildren(...items); band.classList.toggle('hidden', !items.length);
}
document.addEventListener('DOMContentLoaded', () => {
  const wait = setInterval(() => { if (S.meta) { clearInterval(wait); if (!S.me.external) { alertBand(); setInterval(alertBand, 60000); } } }, 200);
});

// ------------------------------------------------------------------ nicel risk sekmesi
function lecChart(curve) {
  const W = 520, H = 180, L = 46, B = 26; const maxX = curve[curve.length - 1][0] || 1;
  const x = v => L + (W - L - 10) * v / maxX; const y = p => 8 + (H - B - 8) * (1 - p);
  const path = curve.map(([v, p], i) => (i ? 'L' : 'M') + x(v).toFixed(1) + ' ' + y(p).toFixed(1)).join(' ');
  return s('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart lec', role: 'img', 'aria-label': 'Kayıp aşım eğrisi'},
    ...[0, 0.25, 0.5, 0.75, 1].map(p => s('g', {}, s('line', {x1: L, x2: W - 10, y1: y(p), y2: y(p), class: 'grid-line'}),
      s('text', {x: L - 6, y: y(p) + 4, 'text-anchor': 'end', class: 'axis'}, Math.round(p * 100) + '%'))),
    ...[0, 0.5, 1].map(f => s('text', {x: x(maxX * f), y: H - 6, 'text-anchor': f === 0 ? 'start' : f === 1 ? 'end' : 'middle', class: 'axis'}, TL_SHORT(maxX * f))),
    s('path', {d: path, class: 'lec-line'}));
}
const RISK_TABS = [{key: 'quant', label: 'Nicel (TL)', render: (r, reload) => {
  const box = h('div', {}, h('div', {class: 'muted small', text: 'Yükleniyor…'}));
  api(`supplier_risks/${r.id}/quant`).then(({run}) => {
    const i = run ? run.inputs : {};
    const field = (key, label, step) => h('label', {class: 'field', for: 'q_' + key}, label, h('div', {class: 'control'}, h('input', {id: 'q_' + key, type: 'number', min: '0', step, value: i[key] ?? ''})));
    const form = h('div', {class: 'formgrid'},
      h('p', {class: 'intro wide', text: 'FAIR yaklaşımı: yılda kaç kez olabilir ve her olayda ne kadar kayıp doğurur? Üç nokta tahmini (en az / en olası / en çok) girin; 10.000 Monte Carlo benzetimiyle yıllık kayıp dağılımı hesaplanır.'}),
      field('freq_min', 'Yıllık sıklık — en az', '0.01'), field('freq_likely', 'Yıllık sıklık — en olası', '0.01'), field('freq_max', 'Yıllık sıklık — en çok', '0.01'),
      field('loss_min', 'Olay başı kayıp (TL) — en az', '1000'), field('loss_likely', 'Olay başı kayıp (TL) — en olası', '1000'), field('loss_max', 'Olay başı kayıp (TL) — en çok', '1000'));
    const result = run ? h('div', {}, statStrip([['Beklenen yıllık kayıp', TL_SHORT(run.mean_loss), 'bad'], ['Medyan yıl', TL_SHORT(run.p50)], ['%90 kötü yıl', TL_SHORT(run.p90)], ['%95 kötü yıl', TL_SHORT(run.p95)]]), lecChart(run.curve),
      h('div', {class: 'muted small', text: `Kayıp aşım eğrisi: yatay eksendeki tutarın bir yılda aşılma olasılığı. Kayıpsız yıl olasılığı ${fmt.pct(100 * run.zero_share)}. ${run.iterations} benzetim · ${run.created_by} · ${fmt.datetime(run.created_at)}`})) :
      h('div', {class: 'muted small', text: 'Henüz nicel analiz yok.'});
    box.replaceChildren(result, canWrite('supplier_risks') ? h('div', {}, form, h('div', {class: 'toolbar'}, btn('Hesapla', async () => {
      const body = {}; for (const k of ['freq_min', 'freq_likely', 'freq_max', 'loss_min', 'loss_likely', 'loss_max']) body[k] = Number($('q_' + k).value);
      await api(`supplier_risks/${r.id}/quantify`, {method: 'POST', body}); toast('Nicel analiz kaydedildi'); reload('quant');
    }))) : null);
  }).catch(e => box.replaceChildren(h('div', {class: 'notice bad', text: e.message})));
  return box;
}}];
const lossesOf = r => {
  const box = h('div', {}, h('div', {class: 'muted small', text: 'Yükleniyor…'}));
  api(`loss_events?risk_id=${r.id}&order=-occurred_on`).then(items => box.replaceChildren(
    items.length ? h('div', {}, statStrip([['Olay', String(items.length)], ['Toplam net kayıp', TL_SHORT(items.reduce((n, x) => n + Number(x.net_loss || 0), 0)), 'bad']]),
      recordList('loss_events', items, {sub: x => `${fmt.date(x.occurred_on)} · ${TL(x.net_loss)}`, chips: x => [display('loss_events', 'event_type', x.event_type)]})) : h('div', {class: 'muted small', text: 'Bu riske bağlı kayıp olayı yok.'}),
    META.def('loss_events')?.can_write ? btn('+ Kayıp olayı', () => createRecord('loss_events', {risk_id: r.id, company_id: r.company_id, process_id: r.process_id, occurred_on: today()}), 'ghost small') : null))
    .catch(e => box.replaceChildren(h('div', {class: 'notice bad', text: e.message})));
  return box;
};
RISK_TABS[0].label = 'Nicel ve kayıplar';
const quantOnly = RISK_TABS[0].render;
RISK_TABS[0].render = (r, reload) => h('div', {}, quantOnly(r, reload), section('Gerçekleşen kayıp olayları', lossesOf(r)));

async function quantPanel() {
  const d = await maybe(api('risks/quant-summary'));
  if (!d || !d.risks.length) return null;
  return panel('TL cinsinden risk (nicel analiz)', h('div', {},
    statStrip([['Portföy beklenen yıllık kayıp', TL_SHORT(d.portfolio.mean), 'bad'], ['Portföy %90', TL_SHORT(d.portfolio.p90)], ['Portföy %95', TL_SHORT(d.portfolio.p95)],
      ['Son 12 ay gerçekleşen kayıp', TL_SHORT(d.actual_losses_12m)]]),
    h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Risk', 'Seviye', 'Beklenen yıllık', '%95'].map((t, i) => h('th', {class: i > 1 ? 'num' : '', text: t})))),
      h('tbody', {}, d.risks.map(r => h('tr', {class: 'clickable', onclick: () => DETAILS.supplier_risks(r.risk_id, 'quant')}, h('td', {class: 'cell-primary'}, r.code, h('span', {class: 'cell-sub', text: r.title})),
        h('td', {}, levelPill(r.risk_level)), h('td', {class: 'num', text: TL_SHORT(r.mean_loss)}), h('td', {class: 'num', text: TL_SHORT(r.p95)})))))),
    h('p', {class: 'muted small', text: `Portföy: en yüksek ${d.portfolio.risks} riskin bağımsız olduğu varsayımıyla birleşik benzetim.`})));
}

// ------------------------------------------------------------------ KVKK ihlali
DETAILS.privacy_breaches = async function breachDetail(id) {
  await loadRefs('privacy_breaches');
  let b; try { b = await api(`privacy_breaches/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('privacy_breaches'); DETAILS.privacy_breaches(id); alertBand(); };
  const patch = body => api('privacy_breaches/' + id, {method: 'PATCH', body}).then(() => { toast('Kaydedildi'); reload(); });
  const can = canWrite('privacy_breaches'); const open = b.status !== 'closed';
  const hours = Math.round(b.remaining_hours);
  const clock = h('div', {class: 'countdown ' + (b.late || hours < 24 ? 'bad' : hours < 48 ? 'warn' : 'good')},
    h('span', {class: 'big', text: b.authority_notified_at ? 'Bildirildi' : b.notify_decision === 'not_required' ? 'Bildirim gerekmiyor' : hours >= 0 ? `${hours} saat` : `${-hours} saat gecikme`}),
    h('span', {text: `Kurula bildirim için son: ${fmt.datetime(b.deadline)} (tespitten itibaren 72 saat)`}));
  const decide = () => {
    const sel = h('select', {id: 'pbDec'}, [['notify', 'Kurula bildirilecek'], ['not_required', 'Bildirim gerekmiyor (risk düşük)']].map(([v, l]) => h('option', {value: v, text: l})));
    const why = h('textarea', {id: 'pbWhy', placeholder: 'Veri türü, kişi sayısı, olası sonuçlar ve alınan önlemlere göre değerlendirme'});
    Modal.open('Bildirim kararı: ' + b.code, h('div', {}, h('label', {class: 'field', for: 'pbDec'}, 'Karar', h('div', {class: 'control'}, sel)), h('label', {class: 'field', for: 'pbWhy'}, 'Gerekçe', h('div', {class: 'control'}, why))),
      [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => { await patch({notify_decision: sel.value, decision_rationale: why.value.trim()}); Modal.close(); })]);
  };
  const notified = () => {
    const at = h('input', {type: 'datetime-local', id: 'pbAt'}); const ref = h('input', {id: 'pbRef', placeholder: 'Kurul bildirim formu / VERBİS referansı'});
    const delay = h('textarea', {id: 'pbDelay', placeholder: '72 saat aşıldıysa gecikme gerekçesi (zorunlu)'});
    Modal.open('Kurula bildirim: ' + b.code, h('div', {}, h('label', {class: 'field', for: 'pbAt'}, 'Bildirim zamanı', h('div', {class: 'control'}, at)),
      h('label', {class: 'field', for: 'pbRef'}, 'Referans', h('div', {class: 'control'}, ref)), h('label', {class: 'field', for: 'pbDelay'}, 'Gecikme gerekçesi', h('div', {class: 'control'}, delay))),
      [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => { if (!at.value) throw new Error('Zaman gerekli');
        await patch({authority_notified_at: new Date(at.value).toISOString(), authority_reference: ref.value.trim() || null, delay_reason: delay.value.trim() || null}); Modal.close(); })]);
  };
  const body = h('div', {}, open ? clock : null,
    h('div', {class: 'steps'}, [['Tespit', true], ['Karar', b.notify_decision !== 'pending'], ['Kurula bildirim', !!b.authority_notified_at || b.notify_decision === 'not_required'], ['Kapanış', b.status === 'closed']]
      .map(([t, done], i) => h('span', {class: 'step' + (done ? ' done' : '')}, h('b', {text: done ? '✓' : String(i + 1)}), t))),
    section('İhlal', kv([['Açıklama', b.description], ['Tespit', fmt.datetime(b.detected_at)], ['İhlal zamanı', fmt.datetime(b.occurred_at)], ['Veri kategorileri', b.data_categories],
      ['Özel nitelikli veri', b.special_categories ? pill('Var', 'bad') : 'Yok'], ['Etkilenen kişi', b.subjects_count], ['Kişi grupları', b.subject_groups], ['Olası sonuçlar', b.consequences],
      ['Alınan önlemler', b.measures], ['Sorumlu', b.owner], ['Şirket', display('privacy_breaches', 'company_id', b.company_id)]])),
    section('Karar ve bildirim', kv([['Karar', display('privacy_breaches', 'notify_decision', b.notify_decision)], ['Gerekçe', b.decision_rationale], ['Karar veren', b.decided_by],
      ['Kurula bildirim', fmt.datetime(b.authority_notified_at)], ['Referans', b.authority_reference], ['Gecikme gerekçesi', b.delay_reason], ['İlgili kişilere bildirim', fmt.datetime(b.subjects_notified_at)]])),
    typeof breachAssetsSection === 'function' && hasModule('datagov') ? breachAssetsSection(b, reload) : null);
  const buttons = !can || !open ? [] : [
    btn('Düzenle', () => recordForm('privacy_breaches', b, {skip: ['code', 'notify_decision', 'decision_rationale', 'authority_notified_at', 'authority_reference', 'delay_reason', 'status'], onsaved: reload}), 'secondary'),
    b.notify_decision === 'pending' ? btn('Bildirim kararı', decide) : null,
    b.notify_decision === 'notify' && !b.authority_notified_at ? btn('Kurula bildirildi', notified) : null,
    b.notify_decision !== 'pending' && !b.subjects_notified_at ? btn('İlgililere bildirildi', () => patch({subjects_notified_at: new Date().toISOString()}), 'ghost') : null,
    b.notify_decision !== 'pending' ? btn('Kapat', () => transition('İhlal kaydını kapat: ' + b.code, 'Alınan önlemleri ve kalıcı iyileştirmeleri yazın.', 'Alınan önlemler', 'Kapat',
      note => patch({status: 'closed', measures: note})), 'secondary') : null];
  Drawer.open(b.code + ' · ' + b.title, body, buttons, 'Kişisel veri ihlali');
};
CREATE.privacy_breaches = defaults => recordForm('privacy_breaches', null, {only: ['title', 'company_id', 'owner', 'detected_at', 'occurred_at', 'description', 'data_categories', 'special_categories', 'subjects_count', 'subject_groups', 'consequences', 'measures', 'loss_event_id'],
  defaults: {detected_at: new Date().toISOString(), owner: S.me.username, ...defaults},
  extra: h('div', {class: 'notice wide warn', text: 'KVKK: ihlal tespitinden itibaren en geç 72 saat içinde Kurula bildirim yapılır. Kayıt açıldığında sorumluya ve yöneticilere bildirim gider.'}),
  onsaved: r => { refreshList('privacy_breaches'); openRecord('privacy_breaches', r.id); alertBand(); }});

// ------------------------------------------------------------------ öz değerlendirme (RCSA)
async function rcsaRespond(item, done) {
  const risk = item.item_type === 'risk';
  const scale = (id, label) => h('label', {class: 'field', for: id}, label, h('div', {class: 'control'}, h('select', {id}, [1, 2, 3, 4, 5].map(v => h('option', {value: v, text: v, selected: v === 3})))));
  const eff = h('select', {id: 'rcEff'}, META.field('rcsa_items', 'effectiveness').options.map(o => h('option', {value: o.value, text: o.label})));
  const comment = h('textarea', {id: 'rcCom', placeholder: risk ? 'Değerlendirmenizin dayanağı' : 'Kontrol nasıl işliyor? Etkin değilse neden?'});
  Modal.open('Öz değerlendirme: ' + item.title, h('div', {}, h('p', {class: 'intro', text: risk ? 'Riskin bugünkü olasılık ve etkisini kendi alanınızdan değerlendirin (1 çok düşük – 5 çok yüksek).' : 'Kontrolün son dönemde gerçekten işleyip işlemediğini değerlendirin.'}),
    risk ? h('div', {class: 'formgrid'}, scale('rcL', 'Olasılık'), scale('rcI', 'Etki')) : h('label', {class: 'field', for: 'rcEff'}, 'Etkinlik', h('div', {class: 'control'}, eff)),
    h('label', {class: 'field', for: 'rcCom'}, 'Açıklama', h('div', {class: 'control'}, comment))), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Gönder', async () => { const body = risk ? {likelihood: Number($('rcL').value), impact: Number($('rcI').value)} : {effectiveness: eff.value};
      await api(`rcsa_items/${item.id}/respond`, {method: 'POST', body: {...body, comment: comment.value.trim()}}); Modal.close(); toast('Yanıtınız kaydedildi'); done && done(); })]);
}
DETAILS.rcsa_campaigns = async function rcsaDetail(id) {
  await loadRefs('rcsa_campaigns');
  let k; try { k = await api(`rcsa_campaigns/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('rcsa_campaigns'); DETAILS.rcsa_campaigns(id); };
  const can = canWrite('rcsa_campaigns'); const p = k.progress;
  const EFF = {effective: 'good', partially_effective: 'warn', ineffective: 'bad', not_operating: 'bad'};
  const body = h('div', {}, h('div', {class: 'chips'}, display('rcsa_campaigns', 'status', k.status), k.period ? h('span', {class: 'chip', text: k.period}) : null), h('br'),
    p.total ? statStrip([['Kalem', fmt.num(p.total, 0)], ['Yanıtlanan', `${p.submitted} (${fmt.pct(p.pct)})`], ['Resmî değerlendirmeden sapan risk', fmt.num(p.divergent, 0), p.divergent ? 'warn' : ''],
      ['Etkin olmayan kontrol', fmt.num(p.ineffective, 0), p.ineffective ? 'bad' : '']]) : h('div', {class: 'notice', text: 'Başlatınca kapsamdaki açık riskler ve manuel kontroller sahiplerine atanır.'}),
    section('Kapsam', kv([['Süreç', display('rcsa_campaigns', 'process_id', k.process_id)], ['Birim', display('rcsa_campaigns', 'org_unit_id', k.org_unit_id)], ['Son tarih', fmt.date(k.due_date)], ['Açıklama', k.instructions]])),
    k.items.length ? section('Kalemler', h('ul', {class: 'mini'}, k.items.map(i => h('li', {},
      h('strong', {text: i.item_type === 'risk' ? `${i.risk_code} · ${i.risk_title}` : `${i.control_code || ''} · ${i.control_name || ''}`}),
      h('span', {class: 'cell-sub', text: `${i.respondent}` + (i.comment ? ' · ' + i.comment : '')}),
      h('div', {class: 'chips'}, display('rcsa_items', 'status', i.status),
        i.item_type === 'risk' && i.status === 'submitted' ? pill(`Öz: ${i.likelihood}×${i.impact} · resmî ${i.official_likelihood}×${i.official_impact}`, Math.abs(i.gap || 0) >= 6 ? 'warn' : 'neutral') : null,
        i.effectiveness ? pill(META.option('rcsa_items', 'effectiveness', i.effectiveness), EFF[i.effectiveness]) : null,
        i.status === 'pending' && k.status === 'open' && (i.respondent === S.me.username || S.me.role === 'ADMIN') ? btn('Yanıtla', () => rcsaRespond({...i, title: i.risk_title || i.control_name}, reload), 'ghost small') : null,
        ['ineffective', 'not_operating', 'partially_effective'].includes(i.effectiveness) && canWrite('findings') ? btn('Bulgu aç', async () => {
          const r = await api(`rcsa_items/${i.id}/finding`, {method: 'POST', body: {}}); toast('Bulgu açıldı'); openRecord('findings', r.finding_id); }, 'ghost small') : null))))) : null);
  const buttons = !can ? [] : [k.status === 'draft' ? btn('Düzenle', () => recordForm('rcsa_campaigns', k, {onsaved: reload}), 'secondary') : null,
    k.status === 'draft' ? btn('Başlat', async () => { await api(`rcsa_campaigns/${id}/launch`, {method: 'POST', body: {}}); toast('Öz değerlendirme başladı'); reload(); }) : null,
    k.status === 'open' ? btn('Kapat', async () => { await api(`rcsa_campaigns/${id}/close`, {method: 'POST', body: {}}); toast('Kapatıldı'); reload(); }, 'secondary') : null];
  Drawer.open(k.code + ' · ' + k.title, body, buttons, 'Risk ve kontrol öz değerlendirmesi');
};

// ------------------------------------------------------------------ erişim gözden geçirme
DETAILS.access_reviews = async function accessReviewDetail(id) {
  await loadRefs('access_reviews');
  let k; try { k = await api(`access_reviews/${id}/context`); } catch (e) { toast(e.message, false); return; }
  const reload = () => { refreshList('access_reviews'); DETAILS.access_reviews(id); };
  const can = canWrite('access_reviews'); const me = k.reviewer === S.me.username || S.me.role === 'ADMIN';
  const c = k.counts;
  const decideItem = (item, decision) => decision === 'keep' ? api(`access_review_items/${item.id}/decide`, {method: 'POST', body: {decision}}).then(reload)
    : transition(`${decision === 'revoke' ? 'Erişimi kaldır' : 'Erişimi değiştir'}: ${item.account}`, 'Kararın gerekçesi kanıt dosyasına yazılır.', 'Gerekçe', 'Kaydet',
      note => api(`access_review_items/${item.id}/decide`, {method: 'POST', body: {decision, comment: note}}).then(reload));
  const load = () => {
    const file = h('input', {type: 'file', id: 'arFile', accept: '.csv,.xlsx'});
    Modal.open('Hesap–yetki listesi', h('div', {}, h('p', {class: 'intro', text: 'Sütunlar: Hesap, Kişi, Yetki (rol), Son giriş. Sistemden alınan dışa aktarımı yükleyin veya bu portalın kendi kullanıcılarını gözden geçirin.'}),
      h('label', {class: 'field', for: 'arFile'}, 'Dosya', h('div', {class: 'control'}, file))), [
      btn('Vazgeç', () => Modal.close(), 'secondary'),
      btn('Portal kullanıcılarını yükle', async () => { await api(`access_reviews/${id}/items`, {method: 'POST', body: {source: 'portal_users'}}); Modal.close(); reload(); }, 'secondary'),
      btn('Dosyayı yükle', async () => { if (!file.files[0]) throw new Error('Dosya seçin');
        await api(`access_reviews/${id}/items`, {method: 'POST', body: {filename: file.files[0].name, content_base64: await fileToBase64(file.files[0])}}); Modal.close(); reload(); })], true);
  };
  const pending = k.items.filter(i => i.decision === 'pending');
  const body = h('div', {}, h('div', {class: 'chips'}, display('access_reviews', 'status', k.status), h('span', {class: 'chip', text: k.system})), h('br'),
    statStrip([['Erişim', fmt.num(k.items.length, 0)], ['Bekleyen', fmt.num(c.pending || 0, 0), c.pending ? 'warn' : ''], ['Kalsın', fmt.num(c.keep || 0, 0), 'good'],
      ['Kaldır / değiştir', fmt.num((c.revoke || 0) + (c.modify || 0), 0), c.revoke || c.modify ? 'bad' : '']]),
    k.open_remediation ? h('div', {class: 'notice warn', text: `${k.open_remediation} kaldırma/değişiklik kararı henüz uygulanmadı.`}) : null,
    section('Gözden geçirme', kv([['Gözden geçiren', k.reviewer], ['Son tarih', fmt.date(k.due_date)], ['Kontrol', display('access_reviews', 'control_id', k.control_id)],
      ['Sonuç kanıtı', k.evidence_id ? h('a', {href: '#/r/evidence/' + k.evidence_id, text: 'Kanıtı aç'}) : null], ['Açıklama', k.instructions]])),
    k.items.length ? section('Erişimler', h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Hesap', 'Yetki', 'Son giriş', 'Karar', ''].map(t => h('th', {text: t})))),
      h('tbody', {}, k.items.map(i => h('tr', {}, h('td', {class: 'cell-primary'}, i.account, i.person ? h('span', {class: 'cell-sub', text: i.person}) : null), h('td', {text: i.entitlement}),
        h('td', {text: i.last_login || '—'}), h('td', {}, display('access_review_items', 'decision', i.decision), i.comment ? h('span', {class: 'cell-sub', text: i.comment}) : null,
          i.remediated ? pill('Uygulandı', 'good') : null),
        h('td', {class: 'no-print row-actions'}, k.status === 'open' && me && i.account !== S.me.username ? [btn('Kalsın', () => decideItem(i, 'keep'), 'ghost small'), btn('Kaldır', () => decideItem(i, 'revoke'), 'ghost small'), btn('Değiştir', () => decideItem(i, 'modify'), 'ghost small')] : null,
          k.status === 'completed' && can && ['revoke', 'modify'].includes(i.decision) && !i.remediated ? btn('Uygulandı', async () => { await api(`access_review_items/${i.id}/remediated`, {method: 'POST', body: {}}); reload(); }, 'ghost small') : null))))))) : h('div', {class: 'muted small', text: 'Henüz erişim listesi yüklenmedi.'}));
  const buttons = [can && k.status === 'draft' ? btn('Liste yükle', load, 'secondary') : null,
    can && k.status === 'draft' && k.items.length ? btn('Başlat', async () => { await api(`access_reviews/${id}/launch`, {method: 'POST', body: {}}); toast('Gözden geçiren bilgilendirildi'); reload(); }) : null,
    k.status === 'open' && me && pending.length ? btn(`Kalanlara "kalsın" (${pending.length})`, async () => { if (!await confirmDialog('Toplu karar', `${pending.length} erişim için "kalsın" kararı verilecek. Listeyi gözden geçirdiğinizi onaylıyor musunuz?`, 'Onaylıyorum')) return;
      await api(`access_reviews/${id}/keep`, {method: 'POST', body: {item_ids: pending.map(i => i.id)}}); reload(); }, 'secondary') : null,
    k.status === 'open' && me && !pending.length ? btn('Tamamla ve kanıt üret', async () => { await api(`access_reviews/${id}/complete`, {method: 'POST', body: {}}); toast('Tamamlandı; kanıt kontrole bağlandı'); reload(); }) : null];
  Drawer.open(k.code + ' · ' + k.title, body, buttons, 'Erişim gözden geçirme');
};

// ------------------------------------------------------------------ kriz odası
PAGES.crisis = async function crisisPage(parts) {
  const id = Number(parts[1]) || null;
  const active = await api('bc_incidents/active');
  const target = id || (active[0] && active[0].id);
  const canManage = META.can('manage');
  const declare = async () => {
    const plans = (await api('bc_plans?status=approved&limit=200')).sort((a, b) => a.code.localeCompare(b.code));
    const title = h('input', {id: 'crT', placeholder: 'ör. Birincil veri merkezine erişim yok'}); const desc = h('textarea', {id: 'crD', placeholder: 'Ne oldu, ne zaman, hangi hizmetler etkileniyor?'});
    const sev = h('select', {id: 'crS'}, ['critical', 'high', 'medium'].map(v => h('option', {value: v, text: META.option('bc_incidents', 'severity', v)})));
    const lead = h('input', {id: 'crL', value: S.me.display_name || S.me.username});
    const box = checklist(plans, [], {label: p => `${p.code} · ${p.title}`});
    Modal.open('Kriz ilan et', h('div', {}, h('div', {class: 'notice warn', text: 'Kriz ilan edilince seçilen planların adımları görev listesine dönüşür, tüm kullanıcılar üst bantta görür ve e-posta/Teams bildirimi gider.'}),
      h('label', {class: 'field', for: 'crT'}, 'Başlık', h('div', {class: 'control'}, title)), h('label', {class: 'field', for: 'crD'}, 'Durum', h('div', {class: 'control'}, desc)),
      h('div', {class: 'formgrid'}, h('label', {class: 'field', for: 'crS'}, 'Önem', h('div', {class: 'control'}, sev)), h('label', {class: 'field', for: 'crL'}, 'Kriz lideri', h('div', {class: 'control'}, lead))),
      h('div', {class: 'field'}, 'Devreye alınacak onaylı planlar', box.node)), [
      btn('Vazgeç', () => Modal.close(), 'secondary'),
      btn('Kriz ilan et', async () => { const r = await api('bc_incidents/declare', {method: 'POST', body: {title: title.value.trim(), description: desc.value.trim(), severity: sev.value, commander: lead.value.trim(), plan_ids: box.value()}});
        Modal.close(); alertBand(); Router.go('crisis/' + r.id); }, 'danger')], true);
  };
  if (!target) {
    const past = await api('bc_incidents?order=-declared_at&limit=50');
    setPage('Kriz Yönetimi', 'Etkin kriz yok. Kriz ilan edildiğinde planların adımları görev listesine dönüşür; kararlar ve iletişim değiştirilemez günlüğe yazılır.', [canManage ? btn('Kriz ilan et', declare, 'danger') : null]);
    content(panel('Geçmiş krizler', past.length ? h('ul', {class: 'mini'}, past.map(k => h('li', {class: 'link', onclick: () => Router.go('crisis/' + k.id)}, h('strong', {text: `${k.code} · ${k.title}`}),
      h('span', {class: 'cell-sub', text: `${fmt.datetime(k.declared_at)} – ${fmt.datetime(k.closed_at)} · lider ${k.commander}`}), h('div', {class: 'chips'}, display('bc_incidents', 'status', k.status), display('bc_incidents', 'severity', k.severity))))) : empty('Kriz kaydı yok', '')));
    return;
  }
  const k = await api(`bc_incidents/${target}/context`); const open = k.status !== 'closed';
  const reload = () => { alertBand(); render(); };
  const post = (path, body) => api(path, {method: 'POST', body});
  setPage(`${k.code} · ${k.title}`, `Lider: ${k.commander} · ilan ${fmt.datetime(k.declared_at)} · ${Math.floor(k.progress.elapsed_minutes / 60)} sa ${k.progress.elapsed_minutes % 60} dk`, [
    open && canManage && k.status === 'active' ? btn('Normale dönüşe geç', () => post(`bc_incidents/${k.id}/transition`, {status: 'recovering'}).then(reload), 'secondary') : null,
    open && canManage ? btn('Krizi kapat', () => {
      const sum = h('textarea', {id: 'ckS', placeholder: 'Olay sonrası rapor: zaman çizelgesi, etki, kök neden, kurtarma'}); const les = h('textarea', {id: 'ckL', placeholder: 'Alınan dersler ve iyileştirmeler'});
      Modal.open('Krizi kapat', h('div', {}, h('p', {class: 'intro', text: 'Kriz, plan bazında "gerçek olay" türünde tatbikat kaydına dönüşür; alınan dersler planın gözden geçirilmesine girdi olur.'}),
        h('label', {class: 'field', for: 'ckS'}, 'Olay sonrası rapor', h('div', {class: 'control'}, sum)), h('label', {class: 'field', for: 'ckL'}, 'Alınan dersler', h('div', {class: 'control'}, les))), [
        btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kapat', async () => { await post(`bc_incidents/${k.id}/transition`, {status: 'closed', summary: sum.value.trim(), lessons_learned: les.value.trim()}); Modal.close(); reload(); })]);
    }, 'danger') : null,
    canManage && !open ? btn('Yeni kriz ilan et', declare, 'secondary') : null]);
  const PH = ['activation', 'response', 'recovery', 'resumption'];
  const phases = PH.map(ph => {
    const tasks = k.tasks.filter(t => t.phase === ph); if (!tasks.length) return null;
    return panel(META.option('bc_incident_tasks', 'phase', ph), h('ul', {class: 'mini crisis-tasks'}, tasks.map(t => {
      const mine = [S.me.username, S.me.display_name].includes(t.responsible) || canManage;
      return h('li', {class: 'task ' + t.status}, h('div', {class: 'test-head'}, h('strong', {text: t.action}), display('bc_incident_tasks', 'status', t.status)),
        h('span', {class: 'cell-sub', text: [t.responsible, t.target_minutes ? `hedef ${t.target_minutes} dk` : null, t.plan_code, t.done_by ? `${t.done_by} · ${fmt.datetime(t.done_at)}` : null, t.note].filter(Boolean).join(' · ')}),
        open && mine ? h('div', {class: 'toolbar'}, t.status === 'todo' ? btn('Başladım', () => post(`bc_incident_tasks/${t.id}/status`, {status: 'doing'}).then(reload), 'ghost small') : null,
          t.status !== 'done' ? btn('Tamamlandı', () => post(`bc_incident_tasks/${t.id}/status`, {status: 'done'}).then(reload), 'ghost small') : null,
          t.status !== 'skipped' && t.status !== 'done' ? btn('Atla', () => transition('Görevi atla', 'Neden atlandığını yazın.', 'Gerekçe', 'Atla', note => post(`bc_incident_tasks/${t.id}/status`, {status: 'skipped', note}).then(reload)), 'ghost small') : null) : null);
    })));
  }).filter(Boolean);
  const text = h('textarea', {id: 'clText', placeholder: 'Karar, iletişim veya durum notu…'}); const kind = h('select', {id: 'clKind', class: 'compact'}, ['decision', 'communication', 'update'].map(v => h('option', {value: v, text: META.option('bc_incident_log', 'kind', v)})));
  content(
    h('div', {class: 'notice ' + (open ? 'bad' : ''), text: k.description}),
    statStrip([['Durum', META.option('bc_incidents', 'status', k.status), open ? 'bad' : 'good'], ['Görev', `${k.progress.done}/${k.progress.total}`], ['İlerleme', fmt.pct(k.progress.pct)],
      ['Planlar', k.plans.map(p => p.code).join(', ') || '—']]),
    k.summary ? panel('Olay sonrası rapor', kv([['Özet', k.summary], ['Alınan dersler', k.lessons_learned], ['Tatbikat kaydı', k.exercise_id ? h('a', {href: '#/r/bc_exercises/' + k.exercise_id, text: 'Aç'}) : null]])) : null,
    h('div', {class: 'grid two crisis'}, h('div', {}, phases.length ? phases : empty('Görev yok', 'Plan seçilmeden ilan edildi; günlüğü kullanın.')),
      panel('Kriz günlüğü', h('div', {}, open && META.can('write') ? h('div', {class: 'log-form'}, kind, text, btn('Ekle', async () => { if (!text.value.trim()) return; await post(`bc_incidents/${k.id}/log`, {kind: kind.value, text: text.value.trim()}); reload(); }, 'small')) : null,
        h('ul', {class: 'timeline'}, k.log.map(l => h('li', {}, h('div', {class: 'chips'}, pill(META.option('bc_incident_log', 'kind', l.kind), {decision: 'purple', communication: 'warn', status: 'bad'}[l.kind] || 'neutral'),
          h('span', {class: 'muted small', text: `${fmt.datetime(l.logged_at)} · ${l.author}`})), h('div', {class: 'small', text: l.text}))))))));
};

// ------------------------------------------------------------------ DÖF → ServiceNow
function serviceNowSection(a, reload) {
  if (!hasModule('cmdb')) return null;
  return section('ServiceNow', a.external_number ? h('div', {}, kv([['Görev no', a.external_number], ['Durum', a.external_status], ['Eşitleme', fmt.datetime(a.external_synced_at)]]),
    btn('Durumu güncelle', async () => { await api(`grc_actions/${a.id}/servicenow/refresh`, {method: 'POST', body: {}}); reload(); }, 'ghost small')) :
    h('div', {}, h('div', {class: 'muted small', text: 'Bu faaliyet ServiceNow\'da açılmadı. (Görev eşlemesi Sistem parametrelerindeki servicenow.tasks ile açılır.)'}),
      canWrite('grc_actions') ? btn('ServiceNow\'da görev aç', async () => { const r = await api(`grc_actions/${a.id}/servicenow`, {method: 'POST', body: {}}); toast('ServiceNow görevi: ' + r.external_number); reload(); }, 'ghost small') : null));
}

'use strict';
/* KVKK ve GDPR boşluk analizi (K-033). Madde metni resmî kaynaktan (standart kütüphanesi); durum platform
   göstergeleri, eşlenen kontroller ve uyum sorumlusunun değerlendirmesinden gelir. app.js, pages.js ve lineage.js
   yardımcılarını kullanır; satır içi stil yok. */

const REG = {
  status: {compliant: ['Uyumlu', 'good'], partial: ['Kısmen uyumlu', 'warn'], non_compliant: ['Uyumsuz', 'bad'], not_assessed: ['Değerlendirilmedi', 'neutral'],
           not_applicable: ['Kapsam dışı', 'neutral']},
  order: ['non_compliant', 'partial', 'not_assessed', 'compliant', 'not_applicable'],
  severity: {high: 'bad', medium: 'warn', low: 'neutral'},
  names: {KVKK: 'KVKK (6698 sayılı Kanun)', GDPR: 'GDPR (AB) 2016/679'},
};
const regPill = st => pill(...(REG.status[st] || [st, 'neutral']));

function regAssessDialog(d, a, reload) {
  const cur = a.assessment || {};
  const status = h('select', {id: 'raStatus'}, ['compliant', 'partial', 'non_compliant', 'not_assessed'].map(k => h('option', {value: k, text: REG.status[k][0], selected: k === (cur.status || a.auto_status)})));
  const note = h('textarea', {id: 'raNote', placeholder: 'Açığı ve dayanağını yazın: ör. "Müşteri iletişim faaliyetinde açık rıza metni güncel değil; pazarlama izni ayrı alınmıyor."'}, cur.note || '');
  const owner = h('input', {id: 'raOwner', type: 'text', list: 'peopleList', value: cur.owner || ''});
  const due = h('input', {id: 'raDue', type: 'date', value: cur.due_date ? String(cur.due_date).slice(0, 10) : ''});
  ensurePeople();
  Modal.open(`${d.code} ${a.code} değerlendirmesi`, h('div', {},
    h('p', {class: 'intro', text: `Platform göstergesi: ${REG.status[a.auto_status][0]}. Değerlendirmeniz madde durumunu belirler; göstergeler yan yana görünmeye devam eder.`}),
    h('div', {class: 'formgrid'},
      h('label', {class: 'field', for: 'raStatus'}, 'Durum', h('div', {class: 'control'}, status)),
      h('label', {class: 'field', for: 'raOwner'}, 'Sorumlu', h('div', {class: 'control'}, owner)),
      h('label', {class: 'field', for: 'raDue'}, 'Hedef tarih', h('div', {class: 'control'}, due)),
      h('label', {class: 'field wide', for: 'raNote'}, 'Açık / gerekçe', h('div', {class: 'control'}, note), h('span', {class: 'hint', text: 'Kısmen veya uyumsuz değerlendirmede zorunlu.'})))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Kaydet', async () => {
    await api('datagov/regulation/assess', {method: 'POST', body: {clause_id: a.id, status: status.value, note: note.value.trim() || null, owner: owner.value.trim() || null, due_date: due.value || null}});
    Modal.close(); toast('Değerlendirme kaydedildi'); reload();
  })]);
}

function regFindingDialog(d, a, reload) {
  const cur = a.assessment || {};
  const gaps = a.indicators.filter(i => i.gaps).map(i => `${i.title}: ${i.gaps} açık`);
  const text = h('textarea', {id: 'rfText'}, cur.note || gaps.join('\n'));
  const severity = h('select', {id: 'rfSev'}, ['low', 'medium', 'high', 'critical'].map(k => h('option', {value: k, text: META.option('findings', 'severity', k), selected: k === (a.status === 'non_compliant' ? 'high' : 'medium')})));
  const owner = h('input', {id: 'rfOwner', type: 'text', list: 'peopleList', value: cur.owner || ''});
  const due = h('input', {id: 'rfDue', type: 'date', value: cur.due_date ? String(cur.due_date).slice(0, 10) : ''});
  ensurePeople();
  Modal.open(`Bulgu aç: ${d.code} ${a.code}`, h('div', {}, h('p', {class: 'intro', text: 'Bulgu maddeye bağlanır (kaynak: öz değerlendirme). Sorumlu ve hedef tarih verilirse düzeltici faaliyet (DÖF) de açılır.'}),
    h('div', {class: 'formgrid'}, h('label', {class: 'field wide', for: 'rfText'}, 'Açık', h('div', {class: 'control'}, text)),
      h('label', {class: 'field', for: 'rfSev'}, 'Önem', h('div', {class: 'control'}, severity)),
      h('label', {class: 'field', for: 'rfOwner'}, 'Sorumlu', h('div', {class: 'control'}, owner)),
      h('label', {class: 'field', for: 'rfDue'}, 'Hedef tarih', h('div', {class: 'control'}, due)))),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Bulgu aç', async () => {
    const r = await api('datagov/regulation/finding', {method: 'POST', body: {clause_id: a.id, description: text.value.trim(), severity: severity.value, owner: owner.value.trim() || null, due_date: due.value || null}});
    Modal.close(); toast(`${r.code} açıldı${r.action_id ? '; DÖF atandı' : ''}`); reload();
  })]);
}

function regIndicator(i, open = false) {
  const head = h('div', {class: 'chips'}, pill(i.gaps ? `${i.gaps} açık` : i.population ? 'Açık yok' : 'Veri yok', i.gaps ? REG.severity[i.severity] : i.population ? 'good' : 'neutral'),
    h('strong', {text: i.title}), h('span', {class: 'muted small', text: i.population ? `${fmt.num(i.population)} kayıt incelendi` : 'Henüz kayıt yok'}));
  if (!i.items.length) return h('div', {class: 'reg-ind'}, head);
  return h('details', {class: 'reg-ind', open}, h('summary', {}, head), h('ul', {class: 'mini'}, i.items.map(x => h('li', {},
    h('a', {href: x.link, text: x.label}), h('span', {class: 'cell-sub', text: x.detail})))),
    i.gaps > i.items.length ? h('div', {class: 'muted small', text: `İlk ${i.items.length} kayıt gösteriliyor.`}) : null);
}

function regArticle(d, a, reload) {
  const cur = a.assessment;
  const body = h('div', {class: 'reg-article'},
    h('div', {class: 'chips'}, regPill(a.status), a.applicable && cur && cur.status !== a.auto_status ? h('span', {class: 'chip', text: 'Platform göstergesi: ' + REG.status[a.auto_status][0]}) : null,
      a.open_findings ? h('a', {class: 'chip', href: '#/r/findings?clause_id=' + a.id, text: `${a.open_findings} açık bulgu`}) : null, a.chapter ? h('span', {class: 'muted small', text: a.chapter}) : null),
    !a.applicable ? h('div', {class: 'notice small'}, h('strong', {text: 'Kapsam dışı: '}), a.justification || 'Kurum yükümlülüğü doğurmayan madde.') : null,
    cur ? section('Değerlendirme', kv([['Durum', regPill(cur.status)], cur.note ? ['Açık / gerekçe', cur.note] : null, ['Sorumlu', personText(cur.owner)], cur.due_date ? ['Hedef tarih', fmt.date(cur.due_date)] : null,
      ['Değerlendiren', `${cur.assessed_by} · ${fmt.datetime(cur.assessed_at)}`]])) : null,
    a.indicators.length ? section('Platform göstergeleri', h('div', {class: 'reg-inds'}, a.indicators.map(i => regIndicator(i, !!i.gaps)))) : null,
    section('Eşlenen kontroller', a.controls.length ? h('ul', {class: 'mini'}, a.controls.map(k => h('li', {class: 'link', onclick: () => openRecord('controls', k.id)},
      h('div', {class: 'chips'}, k.last_status ? resultPill(k.last_status) : pill('Test edilmedi', 'neutral'), h('strong', {text: `${k.code} ${k.name}`})),
      h('span', {class: 'cell-sub', text: k.owner ? 'Sahip: ' + k.owner : ''})))) :
      h('div', {class: 'muted small', text: 'Bu maddeye eşlenmiş kontrol yok. Kontrol ekranında "Madde eşle" ile bağlayın; kontrol testi madde durumunu besler.'})),
    section('Madde metni', h('div', {class: 'reg-text', text: a.text || '—'})));
  Drawer.open(`${a.code} ${a.title}`, body, [
    d.can_edit && a.applicable ? btn('Değerlendir', () => regAssessDialog(d, a, reload)) : null,
    d.can_finding && a.applicable && a.status !== 'compliant' ? btn('Bulgu aç', () => regFindingDialog(d, a, reload), 'secondary') : null,
    btn('Kapat', () => Drawer.close(), 'ghost')], REG.names[d.code]);
}

PAGES.regulation = async function regulationPage(parts, params) {
  const code = params.get('k') === 'GDPR' ? 'GDPR' : 'KVKK';
  const d = await api('datagov/regulation?code=' + code);
  const reload = () => render();
  const switcher = h('div', {class: 'chips reg-switch', role: 'group', 'aria-label': 'Mevzuat'}, ['KVKK', 'GDPR'].map(k =>
    h('button', {type: 'button', class: 'chip' + (k === code ? ' on' : ''), 'aria-pressed': String(k === code), onclick: () => Router.go('regulation?k=' + k), text: REG.names[k]})));
  setPage('KVKK ve GDPR Boşluk Analizi', 'Madde metni resmî kaynaktandır. Durum; KVKK kayıtlarından hesaplanan göstergeler, maddeye eşlenen kontrollerin son testleri ve uyum sorumlusunun değerlendirmesinden gelir. Ön göstergedir, hukuki görüş değildir.',
    [btn('KVKK Panosu', () => Router.go('privacy'), 'secondary')], [['KVKK Panosu', 'privacy']]);
  if (!d.installed) {
    content(switcher, h('div', {class: 'panel'}, h('h3', {text: `${REG.names[code]} metni henüz kurulmadı`}),
      h('p', {class: 'small muted', text: code === 'KVKK' ? 'Kanun metni mevzuat.gov.tr\'deki resmî metinden alınmıştır (7499 sayılı Kanun değişiklikleriyle). Kurulunca maddeler kontrollere eşlenebilir ve boşluk analizi hesaplanır.' :
        'Tüzük metni EUR-Lex\'teki resmî İngilizce metinden alınmıştır (madde ve gerekçeler). Kurulunca maddeler kontrollere eşlenebilir ve boşluk analizi hesaplanır.'}),
      d.can_install ? btn('Kütüphaneden kur', async () => { await api('standards/library/install', {method: 'POST', body: {key: d.library_key}}); toast('Kuruldu'); reload(); }) :
        h('div', {class: 'notice small', text: 'Kurulumu Yönetici yapar (Uyum → Standart kütüphanesi).'})));
    return;
  }
  const state = {status: params.get('d') || '', q: '', showNa: false};
  const counts = d.counts;
  const std = d.standard;
  const info = h('div', {class: 'muted small reg-source'}, `${std.name}${std.version ? ' · ' + std.version : ''} · Kaynak: `,
    std.source_url ? h('a', {href: std.source_url, target: '_blank', rel: 'noopener noreferrer', text: code === 'KVKK' ? 'mevzuat.gov.tr' : 'eur-lex.europa.eu'}) : '—',
    std.source_sha256 ? h('span', {class: 'mono', text: ` · SHA-256 ${std.source_sha256.slice(0, 12)}…`}) : null);
  const cross = d.crosswalk && !d.crosswalk.links ? h('div', {class: 'notice small reg-cross'}, h('strong', {text: 'KVKK ve GDPR birlikte kurulu. '}),
    `Eşdeğer maddeleri (${d.crosswalk.available} ilişki) bağlarsanız bir kontrol iki mevzuatta birden güvence sağlar ve entegre denetimde tek test yapılır.`,
    d.can_library ? btn('Eşlemeyi kur', async () => { const r = await api('datagov/regulation/crosswalk', {method: 'POST', body: {}}); toast(`${r.added} madde ilişkisi eklendi`); reload(); }, 'secondary small') : null) :
    d.crosswalk ? h('div', {class: 'muted small'}, `KVKK–GDPR madde eşlemesi: ${d.crosswalk.links} ilişki (platform önerisi; resmî eşleme değildir).`) : null;
  const top = h('div', {class: 'grid four'},
    h('div', {class: 'panel reg-gauge'}, gauge(d.score, 'Uyum göstergesi', {good: 85, mid: 60, sub: `${d.applicable} uygulanabilir madde`})),
    metric('Uyumsuz', fmt.num(counts.non_compliant || 0), 'madde', counts.non_compliant ? 'bad' : 'good', () => { state.status = 'non_compliant'; draw(); }),
    metric('Kısmen uyumlu', fmt.num(counts.partial || 0), 'madde', counts.partial ? 'warn' : '', () => { state.status = 'partial'; draw(); }),
    metric('Değerlendirilmedi', fmt.num(counts.not_assessed || 0), 'veri veya değerlendirme bekliyor', '', () => { state.status = 'not_assessed'; draw(); }));
  const indicators = d.indicators.length ? panel('Platform göstergeleri', h('div', {class: 'reg-inds'}, d.indicators.slice().sort((x, y) => y.gaps - x.gaps).map(i => regIndicator(i))), null,
    'KVKK kayıtlarından her açılışta hesaplanır') : null;
  const search = h('input', {type: 'search', id: 'regSearch', placeholder: 'Madde ara (ör. aktarım, md. 9, Art. 33)', 'aria-label': 'Madde ara'});
  search.addEventListener('input', () => { state.q = search.value.trim().toLocaleLowerCase(TR); draw(); });
  const naBox = h('input', {type: 'checkbox', id: 'regNa'}); naBox.addEventListener('change', () => { state.showNa = naBox.checked; draw(); });
  const chipsBox = h('div', {class: 'chips'}); const list = h('div');
  const draw = () => {
    fillEl(chipsBox, [['', 'Tümü', d.applicable], ...REG.order.slice(0, 4).map(k => [k, REG.status[k][0], counts[k] || 0])].map(([k, label, n]) =>
      h('button', {type: 'button', class: 'chip' + (state.status === k ? ' on' : ''), 'aria-pressed': String(state.status === k), onclick: () => { state.status = k; draw(); }}, `${label} (${n})`)));
    const shown = d.articles.filter(a => (state.showNa || a.applicable || state.q) && (!state.status || a.status === state.status) &&
      (!state.q || `${a.code} ${a.title} ${a.text || ''}`.toLocaleLowerCase(TR).includes(state.q)));
    const groups = []; let cur = null;
    for (const a of shown) { if (!cur || cur.title !== a.chapter) { cur = {title: a.chapter, items: []}; groups.push(cur); } cur.items.push(a); }
    fillEl(list, groups.length ? groups.map(g => h('div', {class: 'reg-group'}, g.title ? h('h4', {text: g.title}) : null, h('ul', {class: 'reg-list'}, g.items.map(a => {
      const li = h('li', {class: 'reg-item ' + a.status, tabindex: '0', onclick: () => regArticle(d, a, reload)},
        h('div', {class: 'reg-code', text: a.code}),
        h('div', {}, h('strong', {text: a.title}), h('div', {class: 'chips'}, regPill(a.status),
          a.indicators.filter(i => i.gaps).map(i => h('span', {class: 'chip', text: `${i.title.split(' ').slice(0, 4).join(' ')}…: ${i.gaps}`})),
          a.controls.length ? h('span', {class: 'chip', text: `${a.controls.length} kontrol`}) : null,
          a.open_findings ? h('span', {class: 'chip', text: `${a.open_findings} açık bulgu`}) : null,
          a.assessment ? h('span', {class: 'muted small', text: 'Değerlendirildi · ' + fmt.date(a.assessment.assessed_at)}) : null)));
      li.addEventListener('keydown', e => { if (e.key === 'Enter') regArticle(d, a, reload); });
      return li;
    })))) : empty('Eşleşen madde yok', 'Filtreyi veya aramayı değiştirin.'));
  };
  draw();
  content(switcher, info, cross, top, indicators,
    h('div', {class: 'panel'}, h('div', {class: 'panel-title'}, h('h3', {text: 'Maddeler'}), h('div', {class: 'toolbar pt-tools'}, search, h('label', {class: 'toggle', for: 'regNa'}, naBox, 'Kapsam dışı maddeleri göster'))),
      chipsBox, list));
};

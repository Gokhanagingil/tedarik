'use strict';
/* Yönetim ekranları: Entegrasyonlar (e-posta, Teams, Entra/MFA, ServiceNow, MCP, yapay zekâ) ve Bildirimler;
   yapay zekâ önerisi pencereleri (insan onaylı). app.js ve pages.js yardımcılarını kullanır; satır içi stil yok. */

const INTEGRATION_STATE = {off: ['Tanımlı değil', 'neutral'], configured: ['Tanımlı · kapalı', 'warn'], enabled: ['Etkin', 'good'], env: ['Sunucu kurulumundan', 'purple']};

PAGES.integrations = async function integrationsPage() {
  const d = await api('integrations');
  setPage('Entegrasyonlar', 'Bağlantıları buradan tanımlayın ve sınayın. Sırlar şifreli saklanır, bir daha gösterilmez; her değişiklik denetim izine yazılır.');
  const groups = {};
  for (const it of d.integrations) (groups[it.group] = groups[it.group] || []).push(it);
  const card = it => {
    const [label, cls] = INTEGRATION_STATE[it.state] || [it.state, 'neutral'];
    const test = it.last_test_at ? h('div', {class: 'notice small ' + (it.last_test_ok ? 'good' : 'bad')},
      h('strong', {text: (it.last_test_ok ? 'Son sınama başarılı' : 'Son sınama başarısız') + ' · ' + fmt.datetime(it.last_test_at)}), h('div', {text: it.last_test_message || ''})) : null;
    const extra = [];
    if (it.kind === 'entra') extra.push(h('p', {class: 'small'}, h('strong', {text: 'Giriş modu: '}), it.active_login ? 'Entra ID (MFA zorunlu)' : 'Yerel parola',
      it.active_login ? null : h('span', {class: 'muted', text: ' — Ayarları sınadıktan sonra kurulum işinde giriş modunu Entra olarak seçin (auth_mode=entra). Ortam dosyası yoksa bu tanım kullanılır.'})));
    if (it.kind === 'ai' && !it.sdk) extra.push(h('div', {class: 'notice warn small', text: 'Claude SDK paketi (anthropic) sunucuda kurulu değil; kurulumu onay bekliyor. Bu sürede kural tabanlı öneriler çalışır.'}));
    if (it.env) extra.push(h('div', {class: 'notice small', text: 'Bu bağlantı sunucudaki kurulum dosyasıyla yapılandırılmış; burada yalnızca sınanabilir.'}));
    return h('div', {class: 'panel integration'},
      h('div', {class: 'panel-title'}, h('h3', {text: it.title}), pill(label, cls)),
      h('p', {class: 'small muted', text: it.description}), ...extra, test,
      it.updated_by ? h('div', {class: 'muted small', text: `Son değişiklik: ${it.updated_by} · ${fmt.datetime(it.updated_at)}`}) : null,
      h('div', {class: 'toolbar'},
        !it.env ? btn(it.state === 'off' ? 'Tanımla' : 'Ayarlar', () => integrationForm(it, d), it.state === 'off' ? '' : 'secondary') : null,
        it.state !== 'off' || it.env ? btn('Sına', async () => {
          const r = await api('integrations/test', {method: 'POST', body: {kind: it.kind}});
          Modal.open('Sınama: ' + it.title, h('ul', {class: 'mini'}, r.steps.map(s => h('li', {}, h('strong', {text: s.title}), ' ',
            pill({ok: 'Tamam', fail: 'Hata', info: 'Bilgi'}[s.status] || s.status, {ok: 'good', fail: 'bad'}[s.status] || 'neutral'), h('div', {class: 'small', text: s.detail})))),
          [btn('Kapat', () => { Modal.close(); render(); }, 'secondary')], true);
        }, 'secondary') : null,
        !it.env && it.state !== 'off' ? btn(it.enabled ? 'Kapat' : 'Etkinleştir', async () => {
          await api('integrations/save', {method: 'POST', body: {kind: it.kind, enabled: it.enabled ? 0 : 1}}); toast(it.enabled ? 'Kapatıldı' : 'Etkinleştirildi'); render();
        }, it.enabled ? 'ghost' : '') : null));
  };
  content(
    d.secrets_available ? null : h('div', {class: 'notice warn', text: 'Sır saklama anahtarı yapılandırılmamış (TEDARIK_SECRET_KEY_FILE): ayarlar kaydedilir ama parola, belirteç ve web kancası girilemez. Kurulum betiği anahtarı kendiliğinden üretir.'}),
    ...Object.entries(groups).map(([g, items]) => h('div', {}, h('h3', {class: 'group-title', text: g}), h('div', {class: 'grid two'}, items.map(card)))));
};

function integrationForm(it, d) {
  const form = h('form', {class: 'formgrid', novalidate: true});
  const inputs = {};
  for (const f of it.fields) {
    const id = 'ig_' + f.name; const value = it.settings[f.name] ?? '';
    const control = f.type === 'select' ? h('select', {id}, f.required ? null : h('option', {value: '', text: '—'}), f.options.map(o => h('option', {value: o.value, text: o.label, selected: String(o.value) === String(value)})))
      : h('input', {id, type: f.type === 'number' ? 'number' : f.type === 'email' ? 'email' : f.type === 'url' ? 'url' : 'text', value, placeholder: f.placeholder || '', autocomplete: 'off'});
    inputs[f.name] = control;
    form.append(h('label', {class: 'field', for: id}, h('span', {}, f.label, f.required ? h('span', {class: 'req', text: ' *'}) : null), h('div', {class: 'control'}, control),
      f.help ? h('span', {class: 'muted small', text: f.help}) : null));
  }
  const secrets = {};
  for (const sct of it.secrets) {
    const id = 'is_' + sct.name;
    const input = h('input', {id, type: 'password', autocomplete: 'new-password', placeholder: sct.set ? 'Kayıtlı — değiştirmek için yeni değer yazın' : 'Girilmedi', disabled: !d.secrets_available});
    const clearBox = sct.set ? h('input', {type: 'checkbox'}) : null;
    secrets[sct.name] = {input, clearBox};
    form.append(h('label', {class: 'field wide', for: id}, h('span', {}, sct.label, ' ', sct.set ? pill('Kayıtlı', 'good') : pill('Yok', 'neutral')), h('div', {class: 'control'}, input),
      sct.help ? h('span', {class: 'muted small', text: sct.help}) : null, clearBox ? h('label', {class: 'small'}, clearBox, ' Kayıtlı değeri sil') : null));
  }
  if (it.kind === 'entra' && !it.settings.redirect_uri) form.append(h('p', {class: 'wide muted small', text: `Dönüş adresi boşsa ${d.public_url ? d.public_url + '/auth/entra/callback' : 'uygulama adresinden'} kullanılır. Entra uygulama kaydında "Web" platformuna aynı adresi ekleyin; uygulama rollerini (KS.TDR.Admin, KS.TDR.Auditor …) ve MFA isteyen Koşullu Erişim kimlik doğrulama bağlamını tanımlayın.`}));
  const err = h('div', {class: 'notice bad wide hidden', role: 'alert'}); form.prepend(err);
  Modal.open(it.title, h('div', {}, h('p', {class: 'intro', text: it.description}), form), [
    btn('Vazgeç', () => Modal.close(), 'secondary'),
    btn('Kaydet', async () => {
      const settings = {}; for (const [k, el] of Object.entries(inputs)) settings[k] = el.value.trim() === '' ? null : (el.type === 'number' ? Number(el.value) : el.value.trim());
      const sec = {}; for (const [k, s] of Object.entries(secrets)) { if (s.clearBox && s.clearBox.checked) sec[k] = null; else if (s.input.value) sec[k] = s.input.value; }
      try { await api('integrations/save', {method: 'POST', body: {kind: it.kind, settings, secrets: sec}}); }
      catch (e) { err.textContent = e.message; err.classList.remove('hidden'); throw e; }
      Modal.close(); toast('Kaydedildi; "Sına" ile bağlantıyı doğrulayın'); render();
    })], true);
}

PAGES.notifications = async function notificationsPage(parts, params) {
  const [cfg, items] = await Promise.all([api('notifications/settings'), api('notifications?limit=200')]);
  const status = params.get('status') || '';
  setPage('Bildirimler', 'E-posta ve Teams bildirim kutusu. İletiler zamanlanmış görevle gönderilir (10 dakikada bir; günlük iş özeti her sabah).', [
    btn('Şimdi gönder', async () => { const r = await api('notifications/deliver', {method: 'POST', body: {}}); toast(`${r.sent} gönderildi, ${r.failed} hata, ${r.waiting} bekliyor`); render(); })]);
  const c = cfg.counts;
  const rowsTable = items.filter(n => !status || n.status === status);
  const table = rowsTable.length ? h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Zaman', 'Kanal', 'Alıcı', 'Konu', 'Durum', 'Not'].map(t => h('th', {text: t})))),
    h('tbody', {}, rowsTable.map(n => h('tr', {class: 'clickable', onclick: () => openRecord('notifications', n.id)}, h('td', {text: fmt.datetime(n.created_at)}), h('td', {}, display('notifications', 'channel', n.channel)),
      h('td', {text: n.recipient || '—'}), h('td', {class: 'cell-primary', text: n.subject}), h('td', {}, display('notifications', 'status', n.status)),
      h('td', {class: 'small muted', text: n.last_error || (n.attempts > 1 ? n.attempts + ' deneme' : '')})))))) : empty('İleti yok', 'Olaylar oluştukça burada görünür.');
  const draft = cfg.events.map(e => ({...e}));
  const matrix = h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Olay', 'E-posta', 'Teams'].map((t, i) => h('th', {class: i ? 'num' : '', text: t})))),
    h('tbody', {}, draft.map(e => h('tr', {}, h('td', {text: e.label}), ...['email', 'teams'].map(ch => h('td', {class: 'num'}, h('input', {type: 'checkbox', checked: e[ch], 'aria-label': `${e.label} — ${ch}`,
      onchange: ev => { e[ch] = ev.target.checked; }}))))))));
  content(
    !cfg.channels.email && !cfg.channels.teams ? h('div', {class: 'notice warn'}, 'E-posta ve Teams kapalı: olaylar kuyruğa yazılmaz. ', h('a', {href: '#/integrations', text: 'Entegrasyonlar →'})) : null,
    statStrip([['Kuyrukta', fmt.num(c.queued || 0, 0), c.queued ? 'warn' : ''], ['Gönderildi', fmt.num(c.sent || 0, 0), 'good'], ['Gönderilemedi', fmt.num(c.failed || 0, 0), c.failed ? 'bad' : ''],
      ['Atlandı', fmt.num(c.skipped || 0, 0)], ['E-posta', cfg.channels.email ? 'Açık' : 'Kapalı'], ['Teams', cfg.channels.teams ? 'Açık' : 'Kapalı']]),
    h('div', {class: 'grid two'},
      panel('Bildirim kutusu', h('div', {}, h('div', {class: 'filters'}, h('select', {class: 'compact', 'aria-label': 'Durum', onchange: e => Router.go('notifications' + (e.target.value ? '?status=' + e.target.value : ''))},
        h('option', {value: '', text: 'Tüm durumlar'}), ['queued', 'sent', 'failed', 'skipped'].map(v => h('option', {value: v, text: META.option('notifications', 'status', v), selected: v === status})))), table)),
      panel('Hangi olay hangi kanala', h('div', {}, h('p', {class: 'muted small', text: 'Kişiye özel olaylar e-postayla kişiye, Teams işaretli olaylar kanala kart olarak gider. Günlük iş özeti açık işi olan herkese bir kez gönderilir.'}), matrix,
        h('div', {class: 'toolbar'}, btn('Kaydet', async () => { await api('notifications/settings', {method: 'POST', body: {events: draft}}); toast('Bildirim ayarları kaydedildi'); }))))));
};

// ------------------------------------------------------------------ yapay zekâ önerileri (insan onaylı)
function aiNotice(out) {
  return out.ai ? h('div', {class: 'notice small', text: 'Model önerisi (Claude). Uygulamadan önce gözden geçirin; uygulanan değişiklik denetim izine sizin adınızla yazılır.'})
    : h('div', {class: 'muted small', text: 'Kural tabanlı değerlendirme. ' + (out.ai_note || '')});
}
async function riskQuality(risk, done) {
  const out = await api('ai/risk-quality', {method: 'POST', body: {risk_id: risk.id}});
  const r = out.rules; const ai = out.ai;
  const apply = ai && canWrite('supplier_risks') ? btn('Model önerisini uygula', async () => {
    await api('supplier_risks/' + risk.id, {method: 'PATCH', body: {cause: ai.cause, risk_event: ai.risk_event, consequence: ai.consequence}});
    Modal.close(); toast('Risk ifadesi güncellendi'); done && done();
  }) : null;
  Modal.open('Risk ifadesi kalite denetimi', h('div', {},
    statStrip([['Kural puanı', String(r.score), r.score >= 80 ? 'good' : r.score >= 60 ? 'warn' : 'bad'], ai ? ['Model puanı', String(ai.score), ai.score >= 80 ? 'good' : ai.score >= 60 ? 'warn' : 'bad'] : null]),
    section('Eksikler', h('ul', {class: 'plain'}, (ai ? ai.issues : r.issues).map(i => h('li', {text: '• ' + i})))),
    ai ? section('Önerilen ifade', kv([['Neden', ai.cause], ['Risk olayı', ai.risk_event], ['İş etkisi', ai.consequence]])) : section('Kalıp', h('p', {class: 'small', text: r.template})),
    aiNotice(out)), [btn('Kapat', () => Modal.close(), 'secondary'), apply], true);
}
async function evidenceSuggestions(evidence, done) {
  const out = await api('ai/evidence-controls', {method: 'POST', body: {evidence_id: evidence.id}});
  const items = out.ai || out.rules;
  const link = async k => {
    const ctx = await api(`evidence/${evidence.id}/context`);
    const ids = [...new Set([...(ctx.controls || []).map(x => x.id), k.control_id])];
    await api(`evidence/${evidence.id}/links`, {method: 'POST', body: {controls: ids}}); toast(`${k.code} kontrolüne bağlandı`); Modal.close(); done && done();
  };
  Modal.open('Kanıt için kontrol önerisi', h('div', {},
    items.length ? h('ul', {class: 'mini'}, items.map(k => h('li', {}, h('strong', {text: `${k.code} · ${k.name}`}), h('span', {class: 'cell-sub', text: k.reason || ('Benzerlik ' + Math.round((k.score || 0) * 100) + '%')}),
      canWrite('evidence') ? btn('Bağla', () => link(k), 'ghost small') : null))) : h('div', {class: 'muted small', text: 'Uygun kontrol bulunamadı.'}),
    aiNotice(out)), [btn('Kapat', () => Modal.close(), 'secondary')], true);
}

'use strict';
/* Otomatik toplama (K-030): kaynağın "Otomatik toplama" sekmesi, toplayıcı ekranı (kurulum, zamanlama, çalışma geçmişi)
   ve tüm toplayıcılar listesi. Anahtar yalnızca oluşturma ve yenilemede bir kez gösterilir; platform anahtarın yalnızca
   özetini saklar. datagov.js ve app.js yardımcılarını kullanır; dış kütüphane ve satır içi stil yok (CSP). */

const COLLECT = {
  pending: null,     // yeni anahtar: toplayıcı ekranı çizildikten sonra bir kez gösterilir
  tone: {ok: 'good', overdue: 'warn', error: 'bad', waiting: 'neutral', revoked: 'neutral'},
  event: {push: 'good', preview: 'neutral', error: 'bad', rejected: 'bad'},
  connectors: [
    ['postgresql', 'PostgreSQL', 'Katalog doğrudan okunur: tablo, görünüm, kolon, açıklama, birincil ve yabancı anahtar, tahmini satır sayısı. psycopg sürücüsü toplayıcı makinesine kurulur.'],
    ['sql', 'SQL sürücüsü', 'SAP HANA (hdbcli), SQL Server (pyodbc), Oracle (oracledb), MySQL, Snowflake: kaynağın hazır katalog sorgusu kurumun kurduğu sürücüyle çalışır.'],
    ['sqlite', 'SQLite', 'Veritabanı dosyası salt okunur açılır; ek paket gerekmez.'],
    ['files', 'CSV klasörü', 'Paylaşımdaki her CSV bir tablo, başlık satırı kolonlardır; tipler yerelde örnekten çıkarılır.'],
    ['file', 'Hazır dışa aktarım', 'Kaynak sistemin kendi zamanlanmış dışa aktarımı (CSV, Excel, JSON) olduğu gibi gönderilir.'],
    ['custom', 'Kurumun bağlayıcısı', 'Python ile yazılan tek bir Connector sınıfı (bağlayıcı geliştirme kiti, docs/TOPLAYICI.md).']],
};
function collectorPill(st) { return pill(st.label, COLLECT.tone[st.state] || 'neutral'); }
function agoText(v) {
  if (!v) return '';
  const mins = Math.round((Date.now() - new Date(v)) / 60000);
  if (mins < 1) return 'az önce'; if (mins < 60) return `${mins} dk önce`;
  const hours = Math.round(mins / 60); if (hours < 48) return `${hours} saat önce`;
  return `${Math.round(hours / 24)} gün önce`;
}
function whenText(v, empty = 'Henüz yok') { return v ? `${fmt.datetime(v)} (${agoText(v)})` : empty; }
function codeBlock(text, title) {
  return h('div', {class: 'query-card'}, h('div', {class: 'panel-title'}, h('h4', {text: title || ''}), copyButton(text)), h('pre', {class: 'query', text}));
}
const downloadCollector = () => download('datagov/collector.pyz', 'tedarik-toplayici.pyz');

// ------------------------------------------------------------------ oluşturma ve anahtar
function collectorDialog(s) {
  const name = h('input', {type: 'text', id: 'tplName', value: `${s.name} toplayıcısı`, autocomplete: 'off'});
  const preferred = {sap_hana: 'sql', sql_server: 'sql', oracle: 'sql', mysql: 'sql', snowflake: 'sql', redshift: 'sql', postgresql: 'postgresql', file: 'files'}[s.platform] || 'file';
  const kinds = h('div', {class: 'choices'}, COLLECT.connectors.map(([v, label, hint]) => h('label', {}, h('input', {type: 'radio', name: 'tplConnector', value: v, checked: v === preferred}),
    h('span', {}, h('strong', {text: label}), h('span', {class: 'cell-sub', text: hint})))));
  const schedule = h('select', {id: 'tplSchedule'}, [['daily', 'Günde bir (önerilen)'], ['hourly', 'Saatte bir'], ['weekly', 'Haftada bir'], ['monthly', 'Ayda bir'], ['manual', 'Elle (zamanlanmamış)']]
    .map(([v, t]) => h('option', {value: v, text: t})));
  const scope = h('select', {id: 'tplScope'}, [['schemas', 'Gönderilen şemaların tamamı (önerilen)'], ['full', 'Kaynağın tamamı'], ['tables', 'Yalnızca gönderilen tablolar']]
    .map(([v, t]) => h('option', {value: v, text: t})));
  const sample = h('input', {type: 'number', id: 'tplSample', min: 0, max: 10000, step: 100, value: 0});
  const error = h('div', {class: 'notice bad hidden', role: 'alert'});
  const save = async () => {
    const connector = (document.querySelector('input[name=tplConnector]:checked') || {}).value;
    try {
      const r = await api(`data_sources/${s.id}/collectors`, {method: 'POST', body: {name: name.value.trim(), connector, schedule: schedule.value, scope: scope.value,
        sample_rows: Number(sample.value || 0)}});
      // Ekran değişince açık pencere kapanır: anahtar, toplayıcı ekranı çizildikten sonra gösterilir.
      COLLECT.pending = {id: r.collector.id, col: r.collector, key: r.key, title: 'Toplayıcı oluşturuldu'};
      Modal.close(); invalidate('data_collectors'); Router.go('collector/' + r.collector.id);
    } catch (e) { error.textContent = e.message; error.classList.remove('hidden'); }
  };
  Modal.open('Toplayıcı ekle: ' + s.name, h('div', {class: 'wizard'},
    h('p', {class: 'intro', text: 'Toplayıcı kaynağın bulunduğu ağda, kurumun sunucusunda çalışır. Kaynağa salt okunur hesapla bağlanır, yalnızca meta veriyi (tablo, kolon, tip, açıklama) okur ve platforma gönderir. Kaynağın parolası platforma gelmez; ham veri gönderilmez.'}),
    error,
    h('label', {class: 'field', for: 'tplName'}, h('span', {text: 'Ad'}), h('div', {class: 'control'}, name)),
    h('div', {class: 'field'}, h('span', {text: 'Bağlayıcı'}), kinds),
    h('div', {class: 'formgrid'},
      h('label', {class: 'field', for: 'tplSchedule'}, h('span', {text: 'Beklenen çalışma sıklığı'}), h('div', {class: 'control'}, schedule)),
      h('label', {class: 'field', for: 'tplScope'}, h('span', {text: 'Kapsam'}), h('div', {class: 'control'}, scope))),
    h('p', {class: 'small muted', text: 'Sıklık, toplayıcının kurum tarafında zamanlanacağı aralıktır; platform bu sürede gönderim gelmezse teknik sorumluya bildirir. Kapsamdaki tablo gönderimde yoksa "kaynakta kaldırıldı" olur (silinmez); gönderim etkin tabloların %30\'undan fazlasını kaldıracaksa reddedilir.'}),
    h('label', {class: 'field', for: 'tplSample'}, h('span', {text: 'Örnek doğrulama (tablo başına satır, 0: kapalı)'}), h('div', {class: 'control'}, sample)),
    h('p', {class: 'small muted', text: 'Açıksa toplayıcı her tablodan bu kadar satırı yerelde okur; T.C. kimlik, IBAN, kart, e-posta, telefon ve IP doğrulayıcılarını çalıştırır ve platforma yalnızca sayıları gönderir. Değerler ağdan çıkmaz.'})),
  [btn('Vazgeç', () => Modal.close(), 'secondary'), btn('Oluştur ve anahtarı göster', save)], true);
}
function keyDialog(col, key, title) {
  const input = h('input', {type: 'text', id: 'tplKey', value: key, readonly: true, class: 'mono'});
  input.addEventListener('focus', () => input.select());
  Modal.open(title || 'Yeni anahtar', h('div', {},
    h('div', {class: 'notice warn'}, h('strong', {text: 'Anahtar yalnızca şimdi gösteriliyor. '}), 'Platform anahtarın kendisini saklamaz; kaydetmeden kapatırsanız toplayıcı ekranından yenisini üretmeniz gerekir.'),
    h('label', {class: 'field', for: 'tplKey'}, h('span', {text: `${col.code} anahtarı`}), h('div', {class: 'control inline'}, input, copyButton(key))),
    h('p', {class: 'small', text: 'Anahtarı toplayıcının çalışacağı makinede bir dosyaya yapıştırın ve yalnızca toplayıcıyı çalıştıran hesabın okumasına izin verin: Linux\'ta /etc/tedarik/anahtar (chmod 600), Windows\'ta C:\\tedarik\\anahtar.txt (yalnızca hizmet hesabına okuma izni). Anahtarı komut satırına, betiğe veya e-postaya yazmayın.'}),
    h('p', {class: 'small muted', text: 'Anahtar yalnızca bu kaynağa katalog gönderebilir; platformdaki başka hiçbir kaydı okuyamaz veya değiştiremez. Sunucu değişirse veya anahtarın sızdığından şüphelenirseniz yenileyin ya da toplayıcıyı iptal edin.'})),
  [btn('Anahtarı kaydettim', () => Modal.close())]);
}

// ------------------------------------------------------------------ kaynak ekranındaki sekme
function sourceCollectors(s) {
  const add = s.can_import ? btn('+ Toplayıcı ekle', () => collectorDialog(s), 'small') : null;
  if (!s.collectors.length) return empty('Bu kaynak için toplayıcı yok', 'Toplayıcı meta veriyi zamanlanmış olarak gönderir; şema değişince veri sahibine ve veri yöneticisine bildirim gider. Kurulumu kurumun sunucusunda birkaç dakikalık iştir.', add);
  return h('div', {},
    h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Toplayıcı', 'Bağlayıcı', 'Sıklık', 'Son gönderim', 'Durum'].map(x => h('th', {text: x})))),
      h('tbody', {}, s.collectors.map(c => h('tr', {class: 'link', onclick: () => Router.go('collector/' + c.id)},
        h('td', {}, h('strong', {text: c.name}), h('div', {class: 'cell-sub', text: [c.code, c.client_host].filter(Boolean).join(' · ')})),
        h('td', {text: META.option('data_collectors', 'connector', c.connector)}), h('td', {text: META.option('data_collectors', 'schedule', c.schedule)}),
        h('td', {text: whenText(c.last_push_at, 'Hiç göndermedi')}), h('td', {}, collectorPill(c.state))))))),
    add ? h('div', {class: 'toolbar'}, add, btn('Toplayıcıyı indir (.pyz)', downloadCollector, 'secondary small')) : null);
}
SOURCE_TABS.push(s => ({key: 'collectors', label: 'Otomatik toplama', count: s.collectors.length, render: () => sourceCollectors(s)}));

// ------------------------------------------------------------------ toplayıcı ekranı
DETAILS.data_collectors = id => Router.go('collector/' + id);
PAGES.collector = async function collectorPage(parts) {
  const c = await api(`data_collectors/${Number(parts[1])}/context`); const reload = () => render();
  const active = c.status === 'active';
  const rotate = async () => {
    if (!await confirmDialog('Anahtarı yenile', 'Eski anahtar hemen geçersiz olur; toplayıcı makinesindeki anahtar dosyasını yeni anahtarla değiştirmeniz gerekir.', 'Yenile')) return;
    const r = await api(`data_collectors/${c.id}/rotate-key`, {method: 'POST', body: {}});
    COLLECT.pending = {id: c.id, col: r.collector, key: r.key, title: 'Anahtar yenilendi'}; reload();
  };
  const revoke = async () => {
    if (!await confirmDialog('Toplayıcıyı iptal et', 'Anahtar hemen geçersiz olur ve toplayıcı yeniden etkinleştirilemez. Geçmiş ve içe aktarımlar korunur.', 'İptal et', 'danger')) return;
    await api(`data_collectors/${c.id}/revoke`, {method: 'POST', body: {}}); toast('Toplayıcı iptal edildi'); invalidate('data_collectors'); reload();
  };
  setPage(c.name, `${c.code} · ${c.source.name} · ${META.option('data_collectors', 'connector', c.connector)}`, [
    btn('Toplayıcıyı indir (.pyz)', downloadCollector, 'secondary'),
    c.can_manage && active ? btn('Düzenle', () => recordForm('data_collectors', c, {only: ['name', 'schedule', 'scope', 'sample_rows', 'max_removal_pct', 'connector', 'description'], onsaved: reload}), 'ghost') : null,
    c.can_manage && active ? btn('Anahtarı yenile', rotate, 'ghost') : null,
    c.can_manage && active ? btn('İptal et', revoke, 'ghost') : null], [['Veri Yönetişimi', 'datagov'], ['Toplayıcılar', 'collectors'], [c.source.name, 'datasource/' + c.source.id]]);
  const st = c.state;
  const alertBox = !active ? h('div', {class: 'notice', text: `Bu toplayıcı ${fmt.datetime(c.revoked_at)} tarihinde ${c.revoked_by || ''} tarafından iptal edildi. Anahtarı geçersizdir.`}) :
    st.state === 'error' ? h('div', {class: 'notice bad'}, h('strong', {text: `${st.label}: `}), c.last_message || 'Toplayıcının çalıştığı makinedeki çıktıyı inceleyin.') :
    st.state === 'overdue' ? h('div', {class: 'notice warn'}, h('strong', {text: 'Toplayıcı gecikti. '}), `Beklenen son gönderim ${fmt.datetime(st.due_at)} idi. Zamanlanmış görevi ve toplayıcı çıktısını denetleyin.`) :
    st.state === 'waiting' ? h('div', {class: 'notice'}, h('strong', {text: 'İlk gönderim bekleniyor. '}), 'Aşağıdaki kurulum adımlarını toplayıcının çalışacağı makinede uygulayın.') : null;
  const status = kv([['Durum', collectorPill(st)], ['Son gönderim', whenText(c.last_push_at, 'Hiç göndermedi')], st.due_at ? ['Sonraki beklenen (en geç)', fmt.datetime(st.due_at)] : null,
    ['Son bağlantı', whenText(c.last_seen_at)], ['Çalıştığı makine', c.client_host || '—'], ['Toplayıcı sürümü', c.client_version || '—'],
    c.last_message && st.state !== 'error' ? ['Son ileti', c.last_message] : null]);
  const settings = kv([['Kaynak', h('a', {href: '#/datasource/' + c.source.id, text: `${c.source.code} ${c.source.name}`})],
    ['Bağlayıcı', META.option('data_collectors', 'connector', c.connector)], ['Beklenen sıklık', META.option('data_collectors', 'schedule', c.schedule)],
    ['Kapsam', META.option('data_collectors', 'scope', c.scope)],
    ['Örnek doğrulama', c.sample_rows ? `Tablo başına ${fmt.num(c.sample_rows)} satır yerelde; yalnızca sayılar gönderilir` : 'Kapalı'],
    ['Kaldırma eşiği', c.max_removal_pct === null || c.max_removal_pct === undefined ? `%${c.removal_default} (politika)` : `%${c.max_removal_pct}`],
    ['Anahtar', `${c.key_hint || '—'} · ${fmt.datetime(c.key_created_at)}`], ['Teknik sorumlu', personText(c.source.custodian)]]);
  const su = c.setup;
  const step = (n, title, ...body) => h('div', {class: 'wiz-step'}, h('span', {class: 'dg-num', text: String(n)}), h('div', {}, h('strong', {text: title}), ...body));
  const setup = h('div', {class: 'wizard'},
    step(1, 'Toplayıcıyı indirin', h('p', {class: 'small muted', text: 'Tek dosya; Python 3.9 veya üstü yeterli, ek paket gerekmez. Kaynağa erişebilen bir sunucuya kopyalayın (ör. /opt/tedarik/ veya C:\\tedarik\\). Kaynağın Python sürücüsü (gerekiyorsa) aynı makineye kurulur.'}),
      h('div', {class: 'toolbar'}, btn('tedarik-toplayici.pyz indir', downloadCollector, 'secondary small'))),
    step(2, 'Anahtarı kaydedin', h('p', {class: 'small muted', text: `Anahtar oluşturulurken bir kez gösterildi (${c.key_hint || '…'}). /etc/tedarik/anahtar dosyasına yazın; yalnızca toplayıcıyı çalıştıran hesap okuyabilsin (chmod 600). Elinizde yoksa "Anahtarı yenile".`})),
    step(3, 'Ayar dosyasını oluşturun', h('p', {class: 'small muted', text: su.note}), codeBlock(su.config, 'toplayici.json'),
      h('p', {class: 'small muted', text: 'Parola ve bağlantı dizesi ayar dosyasına yazılmaz; ayarda yalnızca ortam değişkeninin adı durur. Toplayıcı hesabı kaynakta yalnızca katalog okuma yetkisiyle açılır.'})),
    step(4, 'Bağlantıyı sınayın', codeBlock(su.check, 'Platform ve kaynak bağlantısı'), h('p', {class: 'small muted', text: 'İsterseniz önce "gonder --on-izleme" ile veri yazmadan sonucu görün; "topla --cikti katalog.json" gönderilecek dosyayı yalnızca yerelde yazar.'})),
    step(5, 'Zamanlayın', su.cron ? codeBlock(su.cron, 'Linux (crontab -e)') : h('p', {class: 'small', text: 'Bu toplayıcı elle çalıştırılır:'}),
      su.schtasks ? codeBlock(su.schtasks, 'Windows Görev Zamanlayıcı') : codeBlock(su.run, 'Çalıştır')));
  const events = c.events.length ? h('ul', {class: 'mini'}, c.events.map(e => h('li', {},
    h('div', {class: 'chips'}, pill(META.option('collector_events', 'kind', e.kind), COLLECT.event[e.kind] || 'neutral'), h('strong', {text: e.message || ''})),
    h('span', {class: 'cell-sub', text: [fmt.datetime(e.created_at), e.counts ? countText(e.counts) : null, e.client_host, e.client_version ? 'sürüm ' + e.client_version : null].filter(Boolean).join(' · ')})))) :
    h('div', {class: 'muted small', text: 'Toplayıcı henüz çalışmadı. Gönderim, ön izleme ve hata bildirimleri burada görünür.'});
  content(alertBox,
    h('div', {class: 'grid two'}, panel('Durum', status), panel('Ayarlar', settings)),
    tabs([{key: 'setup', label: 'Kurulum ve zamanlama', render: () => setup}, {key: 'events', label: 'Çalıştırma geçmişi', count: c.events.length, render: () => events}],
      c.last_push_at ? 'events' : 'setup'));
  if (COLLECT.pending && COLLECT.pending.id === c.id) { const p = COLLECT.pending; COLLECT.pending = null; keyDialog(p.col, p.key, p.title); }
};

// ------------------------------------------------------------------ tüm toplayıcılar
PAGES.collectors = async function collectorsPage() {
  const d = await api('datagov/collectors');
  setPage('Toplayıcılar', 'Kaynakların meta verisini kurum ağında toplayıp platforma gönderen programlar. Platform kaynaklara bağlanmaz; ham veri gelmez.', [
    btn('Toplayıcıyı indir (.pyz)', downloadCollector, 'secondary')], [['Veri Yönetişimi', 'datagov']]);
  const sm = d.summary;
  if (!d.items.length) {
    content(empty('Henüz toplayıcı yok', 'Toplayıcı bir veri kaynağının ekranındaki "Otomatik toplama" sekmesinden eklenir.', btn('Veri kaynakları', () => Router.go('r/data_sources'), 'secondary')));
    return;
  }
  content(
    h('div', {class: 'grid four'}, metric('Etkin toplayıcı', fmt.num(sm.active), `${sm.ok} çalışıyor`), metric('Gecikmiş', fmt.num(sm.overdue), 'beklenen sürede göndermedi', sm.overdue ? 'warn' : ''),
      metric('Hata', fmt.num(sm.error), 'hata bildirdi veya reddedildi', sm.error ? 'bad' : ''), metric('İlk gönderim bekleniyor', fmt.num(sm.waiting), 'kurulum sürüyor')),
    h('div', {class: 'panel'}, h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, h('tr', {}, ['Toplayıcı', 'Kaynak', 'Bağlayıcı', 'Sıklık', 'Son gönderim', 'Durum'].map(x => h('th', {text: x})))),
      h('tbody', {}, d.items.map(c => h('tr', {class: 'link', onclick: () => Router.go('collector/' + c.id)},
        h('td', {}, h('strong', {text: c.name}), h('div', {class: 'cell-sub', text: [c.code, c.client_host].filter(Boolean).join(' · ')})),
        h('td', {}, h('span', {text: c.source_name}), h('div', {class: 'cell-sub', text: META.option('data_sources', 'platform', c.platform)})),
        h('td', {text: META.option('data_collectors', 'connector', c.connector)}), h('td', {text: META.option('data_collectors', 'schedule', c.schedule)}),
        h('td', {text: whenText(c.last_push_at, 'Hiç göndermedi')}), h('td', {}, collectorPill(c.state)))))))));
};

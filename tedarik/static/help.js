'use strict';
/* Kullanım kılavuzları (Yardım). Sunucu kılavuz metnini blok yapısına çevirir; burada yalnızca DOM düğümleri ve metin
   düğümleriyle çizilir (HTML yorumlanmaz). Üst çubuktaki "?" düğmesi ve "?" tuşu açık ekranın yardımına gider.
   app.js ve pages.js yardımcılarını kullanır; satır içi stil yok. */

const HELP = {index: null, guides: {}};
async function helpIndex() { if (!HELP.index) HELP.index = await api('help'); return HELP.index; }
async function helpGuide(key) { if (!HELP.guides[key]) HELP.guides[key] = await api('help/guide?key=' + encodeURIComponent(key)); return HELP.guides[key]; }

function helpInline(nodes) {
  return (nodes || []).map(n => n.t === 'text' ? document.createTextNode(n.v)
    : n.t === 'b' ? h('strong', {}, helpInline(n.c))
    : n.t === 'code' ? h('code', {text: n.v})
    : n.t === 'a' ? h('a', {href: n.href}, helpInline(n.c)) : null);
}
function helpBlocks(blocks, prefix = '') {
  return blocks.map(b => {
    if (b.type === 'heading') return h('h' + Math.min(6, b.level + 1), {id: prefix + b.id, class: 'help-h'}, b.text);
    if (b.type === 'p') return h('p', {}, helpInline(b.c));
    if (b.type === 'quote') return h('div', {class: 'help-note'}, helpInline(b.c));
    if (b.type === 'code') return h('pre', {class: 'help-code'}, h('code', {text: b.text}));
    if (b.type === 'list') return h(b.ordered ? 'ol' : 'ul', {class: 'help-list'}, b.items.map(it => h('li', {}, helpInline(it.c),
      it.children.length ? h('ul', {}, it.children.map(ch => h('li', {}, helpInline(ch)))) : null)));
    if (b.type === 'table') return h('div', {class: 'tablewrap plain'}, h('table', {class: 'help-table'},
      h('thead', {}, h('tr', {}, b.header.map(c => h('th', {}, helpInline(c))))),
      h('tbody', {}, b.rows.map(r => h('tr', {}, r.map(c => h('td', {}, helpInline(c))))))));
    return null;
  });
}
function helpSummary(text) {
  const t = String(text || '').replace(/^Kimler için:\s*/, '');
  return t ? t.charAt(0).toLocaleUpperCase(TR) + t.slice(1) : '';
}
function helpScroll(id) {
  const el = id && document.getElementById(id);
  if (el) { el.scrollIntoView({block: 'start'}); el.classList.add('help-flash'); setTimeout(() => el.classList.remove('help-flash'), 1600); }
}

async function openHelp() {
  const parts = Router.parse().parts;
  if (parts[0] === 'help') { Router.go('help'); return; }
  const route = parts[0] === 'r' ? 'r/' + (parts[1] || '') : (parts[0] || 'home');
  const idx = await helpIndex().catch(() => null);
  const target = idx && idx.context[route];
  Router.go(target ? `help/${target[0]}?b=${target[1]}` : 'help');
}

function helpSearchBox(onresults) {
  const input = h('input', {type: 'search', id: 'helpSearch', placeholder: 'Kılavuzlarda ara (ör. geçici parola, kanıt teslim, 72 saat)', 'aria-label': 'Kılavuzlarda ara', autocomplete: 'off'});
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { onresults(null); return; }
    const r = await api('help/search?q=' + encodeURIComponent(q)).catch(() => ({results: []}));
    onresults(r.results, q);
  }, 250);
  input.addEventListener('input', run);
  return input;
}
function helpResults(results, q) {
  if (!results) return null;
  return h('div', {class: 'panel help-results'}, h('div', {class: 'panel-title'}, h('h3', {text: `"${q}" için ${results.length} sonuç`})),
    results.length ? h('ul', {class: 'mini'}, results.map(r => h('li', {class: 'link', onclick: () => Router.go(`help/${r.key}${r.anchor ? '?b=' + r.anchor : ''}`)},
      h('div', {class: 'chips'}, h('strong', {text: r.section}), h('span', {class: 'muted small', text: r.guide})), h('span', {class: 'cell-sub', text: r.snippet})))) :
      h('div', {class: 'muted small', text: 'Eşleşen bölüm yok. Daha kısa veya farklı bir kelime deneyin.'}));
}

PAGES.help = async function helpPage(parts, params) {
  const key = parts[1];
  if (key === 'all') return helpAll();
  if (key) return helpGuidePage(key, params.get('b'));
  const idx = await helpIndex();
  setPage('Kullanım Kılavuzu', 'Rolünüze ve modüllere göre adım adım kılavuzlar. Her ekranda sağ üstteki "?" düğmesi (veya ? tuşu) o ekranın yardımını açar.', [
    btn('Tümünü yazdır / PDF', () => Router.go('help/all'), 'secondary')]);
  const resultsHost = h('div');
  const search = helpSearchBox((results, q) => fillEl(resultsHost, helpResults(results, q)));
  const card = g => h('button', {type: 'button', class: 'help-card' + (g.recommended ? ' rec' : ''), onclick: () => Router.go('help/' + g.key)},
    h('strong', {text: g.title}), g.summary ? h('span', {class: 'small muted', text: helpSummary(g.summary)}) : null,
    h('span', {class: 'help-card-foot small', text: `${g.sections.length} bölüm`}));
  const recommended = idx.guides.filter(g => g.recommended);
  content(h('div', {class: 'panel help-search'}, search), resultsHost,
    recommended.length ? section('Sizin için', h('div', {class: 'help-cards'}, recommended.map(card))) : null,
    idx.groups.map(group => {
      const items = idx.guides.filter(g => g.group === group);
      return items.length ? section(group, h('div', {class: 'help-cards'}, items.map(card))) : null;
    }));
  setTimeout(() => search.focus(), 30);
};

async function helpGuidePage(key, anchor) {
  const [idx, g] = await Promise.all([helpIndex(), helpGuide(key)]);
  const order = idx.guides.map(x => x.key); const at = order.indexOf(key);
  const prev = at > 0 ? idx.guides[at - 1] : null; const next = at >= 0 && at < order.length - 1 ? idx.guides[at + 1] : null;
  setPage(g.title, g.summary.replace(/^Kimler için:\s*/, 'Kimler için: '), [btn('Yazdır / PDF', () => window.print(), 'secondary'), btn('Tüm kılavuzlar', () => Router.go('help'), 'ghost')],
    [['Kullanım Kılavuzu', 'help']]);
  const toc = h('details', {class: 'help-toc no-print', open: !window.matchMedia('(max-width: 900px)').matches}, h('summary', {class: 'help-toc-title', text: 'İçindekiler'}),
    g.sections.filter(s => s.level <= 3).map(s => h('button', {type: 'button', class: 'help-toc-item' + (s.level === 3 ? ' sub' : ''), onclick: () => helpScroll(s.id), text: s.title})));
  const article = h('article', {class: 'help-article panel'}, helpBlocks(g.blocks.filter(b => b.type !== 'quote' || b !== g.blocks.find(x => x.type === 'quote'))),
    h('div', {class: 'help-pager no-print'},
      prev ? h('a', {href: '#/help/' + prev.key, class: 'help-prev'}, h('span', {class: 'small muted', text: '‹ Önceki'}), h('strong', {text: prev.title})) : h('span'),
      next ? h('a', {href: '#/help/' + next.key, class: 'help-next'}, h('span', {class: 'small muted', text: 'Sonraki ›'}), h('strong', {text: next.title})) : h('span')));
  content(h('div', {class: 'help-layout'}, toc, article));
  if (anchor) requestAnimationFrame(() => helpScroll(anchor));
}

async function helpAll() {
  const idx = await helpIndex();
  setPage('Kullanım Kılavuzu (tamamı)', 'Tüm kılavuzlar tek sayfada; yazdırırken her kılavuz yeni sayfada başlar. Tarayıcının yazdırma penceresinde "PDF olarak kaydet" seçin.', [
    btn('Yazdır / PDF', () => window.print()), btn('Kılavuzlar', () => Router.go('help'), 'ghost')], [['Kullanım Kılavuzu', 'help']]);
  const guides = await Promise.all(idx.guides.map(g => helpGuide(g.key)));
  const cover = h('div', {class: 'panel help-cover'}, h('h2', {text: (S.meta?.app_name || 'GRC Platformu') + ' — Kullanım Kılavuzu'}),
    h('p', {class: 'muted', text: 'Sürüm tarihi: ' + fmt.date(today())}),
    h('ol', {class: 'help-list'}, guides.map(g => h('li', {}, g.title))));
  content(cover, guides.map(g => h('article', {class: 'help-article panel help-print-page'}, h('h2', {class: 'help-guide-title', text: g.title}),
    helpBlocks(g.blocks, g.key + '-'))));
}

document.getElementById('helpOpen')?.addEventListener('click', () => openHelp());
document.addEventListener('keydown', e => {
  if (e.key === '?' && !e.ctrlKey && !e.metaKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !Modal.isOpen()) { e.preventDefault(); openHelp(); }
});

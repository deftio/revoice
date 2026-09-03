/* Shared site chrome for revoice pages — bitwrench TACO components.
   Every page: bw.loadStyles(THEME); bw.mount('#app', sitePage(active, [...])); */

var THEME = { primary: '#4a6fa5', secondary: '#3d8b52' };

/* ---- analytics: GoatCounter — unsampled, no cookies, no consent banner.
   Change the site code when the account exists; localhost hits are ignored. */
var GOATCOUNTER_CODE = 'deftio';
(function () {
  var s = document.createElement('script');
  s.async = true;
  s.src = '//gc.zgo.at/count.js';
  s.setAttribute('data-goatcounter', 'https://' + GOATCOUNTER_CODE + '.goatcounter.com/count');
  document.head.appendChild(s);
})();

/* ---- favicon: the r< mark (placeholder until the real icon lands) ---- */
(function () {
  var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>" +
    "<rect width='64' height='64' rx='12' fill='%234a6fa5'/>" +
    "<text x='32' y='44' font-family='Menlo,Consolas,monospace' font-size='34' " +
    "font-weight='bold' fill='white' text-anchor='middle'>r&lt;</text></svg>";
  var l = document.createElement('link');
  l.rel = 'icon';
  l.href = 'data:image/svg+xml,' + svg;
  document.head.appendChild(l);
})();

/* ---- site styles: clean lines, one place, bitwrench-idiomatic ---- */
bw.injectCSS(bw.css({
  'html': { fontSize: '16px' },
  'body': { background: '#fbfbfa', color: '#23262b', lineHeight: '1.55' },
  '.rv_topbar': { position: 'sticky', top: '0', zIndex: '50', background: '#fffffffa',
                  borderBottom: '1px solid #e3e4e2', backdropFilter: 'blur(4px)' },
  '.rv_topbar_inner': { maxWidth: '1280px', margin: '0 auto', padding: '0.55em 3rem',
                        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.2em 1.1em' },
  '.rv_mark': { display: 'inline-block', background: '#4a6fa5', color: '#fff',
                fontFamily: 'Menlo,Consolas,monospace', fontWeight: '700', fontSize: '1.05em',
                borderRadius: '7px', padding: '0.12em 0.42em', letterSpacing: '-0.03em' },
  '.rv_brand': { display: 'inline-flex', alignItems: 'center', gap: '0.5em',
                 textDecoration: 'none', color: 'inherit' },
  '.rv_brand b': { fontSize: '1.18em', fontWeight: '700', letterSpacing: '0.01em' },
  '.rv_nav': { display: 'flex', flexWrap: 'wrap', gap: '0 1.15em', marginLeft: 'auto' },
  '.rv_nav a': { textDecoration: 'none', color: '#4b5260', fontSize: '0.95em',
                 padding: '0.5em 0.1em', borderBottom: '2px solid transparent' },
  '.rv_nav a:hover': { color: '#4a6fa5' },
  '.rv_nav a.rv_active': { color: '#4a6fa5', borderBottomColor: '#4a6fa5', fontWeight: '600' },
  /* bitwrench-site geometry: 1280px wide cap, 3rem gutters (1rem on small screens) */
  '.rv_wrap': { maxWidth: '1280px', margin: '0 auto', padding: '0 3rem' },
  '@media (max-width: 768px)': {
    '.rv_wrap': { padding: '0 1rem' },
    '.rv_topbar_inner': { padding: '0.55em 1rem' }
  },
  '.rv_hero': { padding: '1.3em 0 0 0' },
  'h1': { fontSize: '1.7em', letterSpacing: '-0.01em', margin: '0.5em 0 0.25em 0', fontWeight: '650' },
  'h2': { margin: '2.3em 0 0.55em 0', paddingBottom: '0.25em',
          borderBottom: '1px solid #e6e7e5', fontSize: '1.12em', fontWeight: '650',
          color: '#39414d' },
  'h3': { margin: '1em 0 0.35em 0', fontSize: '1.02em' },
  'p': { margin: '0.55em 0' },
  'ul': { margin: '0.5em 0', paddingLeft: '1.4em' },
  'li': { margin: '0.3em 0' },
  'section': { marginBottom: '0.4em' },
  'pre.bw_card': { background: '#22262c', color: '#e8eaed', border: 'none',
                   borderLeft: '4px solid #4a6fa5', borderRadius: '8px',
                   padding: '0.8em 1em', margin: '0.7em 0', overflowX: 'auto',
                   fontSize: '0.86em', lineHeight: '1.5' },
  '.bw_row': { margin: '0.6em 0' },
  '.bw_card': { border: '1px solid #e3e4e2', borderRadius: '10px', background: '#fff' },
  '.bw_row .bw_card': { transition: 'box-shadow 0.15s, transform 0.15s', height: '100%' },
  '.bw_row .bw_card:hover': { boxShadow: '0 3px 14px #0000000f', transform: 'translateY(-1px)' },
  '.bw_table th': { borderBottom: '2px solid #4a6fa5', textAlign: 'left' },
  '.bw_table td': { borderBottom: '1px solid #ececea' },
  '.bw_table tr:hover td': { background: '#f4f6f9' },
  'footer.rv_footer': { borderTop: '1px solid #e6e7e5', marginTop: '2em',
                        padding: '1em 0 1.6em 0', opacity: '0.75', fontSize: '0.88em' },
  /* buttons: explicit treatment (theme's bare .bw_btn is minimal) */
  'button.bw_btn, a.bw_btn': { display: 'inline-block', font: 'inherit', fontSize: '0.93em',
    padding: '0.42em 1em', margin: '0 0.35em 0.35em 0', cursor: 'pointer',
    background: '#fff', color: '#3c4350', border: '1px solid #d5d7db', borderRadius: '8px',
    textDecoration: 'none', transition: 'border-color 0.12s, color 0.12s, background 0.12s' },
  'button.bw_btn:hover, a.bw_btn:hover': { borderColor: '#4a6fa5', color: '#4a6fa5' },
  '.bw_btn.bw_primary': { background: '#4a6fa5', color: '#fff', border: '1px solid #4a6fa5' },
  '.bw_btn.bw_primary:hover': { background: '#3d5d8c', color: '#fff' },
  '.rv_chip': { fontSize: '0.85em', padding: '0.28em 0.85em', borderRadius: '1em',
                background: '#f2f4f7' },
  '.rv_chip:hover': { background: '#e8edf4' }
}));

var NAV = [
  ['index.html', 'Overview'],
  ['how-it-works.html', 'How it works'],
  ['getting-started.html', 'Getting started'],
  ['background.html', 'Background'],
  ['demo.html', 'Demo'],
  ['compare.html', 'Compare'],
  ['https://github.com/deftio/revoice', 'GitHub']
];

function siteHeader(active) {
  return { t: 'div', a: { class: 'rv_topbar' }, c: { t: 'div', a: { class: 'rv_topbar_inner' }, c: [
    { t: 'a', a: { class: 'rv_brand', href: 'index.html' }, c: [
      { t: 'span', a: { class: 'rv_mark', title: 'revoice' }, c: 'r<' },
      { t: 'b', c: 'revoice' }
    ]},
    { t: 'nav', a: { class: 'rv_nav' },
      c: NAV.map(function (item) {
        return { t: 'a', a: { href: item[0], class: item[0] === active ? 'rv_active' : '' },
                 c: item[1] };
      }) }
  ]}};
}

function siteFooter() {
  return { t: 'footer', a: { class: 'rv_footer' }, c: [
    { t: 'span', a: { class: 'rv_mark', style: bw.s({ fontSize: '0.8em', marginRight: '0.6em' }) }, c: 'r<' },
    'BSD-2-Clause © M. A. Chatterjee / ',
    { t: 'a', a: { href: 'https://github.com/deftio' }, c: 'deftio' },
    ' · built with ',
    { t: 'a', a: { href: 'https://github.com/deftio/bitwrench' }, c: 'bitwrench' },
    ' · no cookies · privacy-preserving analytics (GoatCounter)'
  ]};
}

function codeBlock(s) {
  return { t: 'pre', a: { class: 'bw_card' }, c: { t: 'code', c: s } };
}

function section(title, kids) {
  return { t: 'section', c: [{ t: 'h2', c: title }].concat(kids) };
}

function cardRow(cards) {
  return { t: 'div', a: { class: 'bw_row' },
    c: cards.map(function (c) {
      return { t: 'div', a: { class: 'bw_col' }, c: bw.makeCard(c) };
    }) };
}

function sitePage(active, contentKids) {
  return { t: 'div', c: [
    siteHeader(active),
    { t: 'div', a: { class: 'rv_wrap' },
      c: [{ t: 'div', a: { class: 'rv_hero' } }].concat(contentKids).concat([siteFooter()]) }
  ]};
}

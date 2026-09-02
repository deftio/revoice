/* Shared site chrome for revoice pages — bitwrench TACO components.
   Every page: bw.loadStyles(THEME); bw.mount('#app', page(...)); */

var THEME = { primary: '#4a6fa5', secondary: '#3d8b52' };

var NAV = [
  ['index.html', 'Overview'],
  ['how-it-works.html', 'How it works'],
  ['getting-started.html', 'Getting started'],
  ['background.html', 'Background'],
  ['demo.html', 'Demo'],
  ['https://github.com/deftio/revoice', 'GitHub']
];

function siteHeader(active) {
  return { t: 'header', a: { style: bw.s({ padding: '1.6em 0 0.6em 0' }) }, c: [
    { t: 'div', c: [
      { t: 'a', a: { href: 'index.html', style: bw.s({ textDecoration: 'none' }) },
        c: { t: 'span', a: { style: bw.s({ fontSize: '1.5em', fontWeight: '700' }) }, c: 'revoice' } },
      { t: 'span', a: { style: bw.s({ opacity: '0.65', marginLeft: '0.8em', fontSize: '0.95em' }) },
        c: 'rewrite documents in your own voice' }
    ]},
    { t: 'nav', a: { style: bw.s({ margin: '0.7em 0' }) },
      c: NAV.map(function (item) {
        var isActive = item[0] === active;
        return { t: 'a', a: { href: item[0],
          class: isActive ? 'bw_btn bw_primary' : 'bw_btn',
          style: bw.s({ marginRight: '0.4em', marginBottom: '0.3em', display: 'inline-block' }) },
          c: item[1] };
      }) }
  ]};
}

function siteFooter() {
  return { t: 'footer', a: { style: bw.s({ padding: '2.5em 0 1.5em 0', opacity: '0.7', fontSize: '0.88em' }) }, c: [
    'BSD-2-Clause © M. A. Chatterjee / ',
    { t: 'a', a: { href: 'https://github.com/deftio' }, c: 'deftio' },
    ' · built with ',
    { t: 'a', a: { href: 'https://github.com/deftio/bitwrench' }, c: 'bitwrench' },
    ' · no trackers, no cookies'
  ]};
}

function codeBlock(s) {
  return { t: 'pre', a: { class: 'bw_card', style: bw.s({ overflowX: 'auto', fontSize: '0.87em', lineHeight: '1.45' }) },
           c: { t: 'code', c: s } };
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
  return { t: 'div', a: { class: 'bw_container', style: bw.s({ maxWidth: '900px' }) },
    c: [siteHeader(active)].concat(contentKids).concat([siteFooter()]) };
}

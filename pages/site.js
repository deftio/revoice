/* Shared site chrome for revoice pages.
 *
 * bitwrench owns the DOM, the palette, and the components. Pages do:
 *     bw.mount('#app', sitePage('demo.html', [ ...tacos... ]));
 * and never call loadStyles themselves — theming happens here, once.
 *
 * Rule of thumb followed throughout (bitwrench's own "common mistakes" list):
 *   - never hand-build a component that BCCL already ships (bw.makeCard,
 *     bw.makeTable, bw.makeAlert, bw.makeProgress, ...)
 *   - never hard-code a colour; derive it from STYLES.palette so the whole site
 *     re-themes from the two seeds below and dark mode works for free
 *   - never hand-write @media; use bw.responsive()
 */

var THEME = { primary: '#4a6fa5', secondary: '#3d8b52' };

/* One call: generates the full palette (hover/active/focus/border/textOn for
   every colour) plus structural CSS for all 47 BCCL components. */
var STYLES = bw.loadStyles(THEME);
var P = STYLES.palette;      // primary, secondary, success, danger, warning, info, light, dark, surface, surfaceAlt, background
var L = STYLES.layout;       // spacing, radius, typeScale, elevation, motion

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
    "<rect width='64' height='64' rx='12' fill='" + encodeURIComponent(P.primary.base) + "'/>" +
    "<text x='32' y='44' font-family='Menlo,Consolas,monospace' font-size='34' " +
    "font-weight='bold' fill='white' text-anchor='middle'>r&lt;</text></svg>";
  var l = document.createElement('link');
  l.rel = 'icon';
  l.href = 'data:image/svg+xml,' + svg;
  document.head.appendChild(l);
})();

/* ---- site chrome only: things BCCL does not ship (topbar, brand mark, prose
   rhythm). Every value comes from the palette or the layout tokens. ---- */
bw.injectCSS(bw.css({
  'html': { fontSize: '16px' },
  'body': { background: P.background, color: P.dark.base, lineHeight: '1.55' },

  '.rv_topbar': { position: 'sticky', top: '0', zIndex: '50', background: P.surface,
                  borderBottom: '1px solid ' + P.light.border },
  '.rv_topbar_inner': { maxWidth: '1280px', margin: '0 auto', padding: '0.55em 3rem',
                        display: 'flex', alignItems: 'center', flexWrap: 'wrap',
                        gap: '0.2em 1.1em' },
  '.rv_mark': { display: 'inline-block', background: P.primary.base, color: P.primary.textOn,
                fontFamily: 'Menlo,Consolas,monospace', fontWeight: '700', fontSize: '1.05em',
                borderRadius: L.radius.btn, padding: '0.12em 0.42em', letterSpacing: '-0.03em' },
  '.rv_brand': { display: 'inline-flex', alignItems: 'center', gap: '0.5em',
                 textDecoration: 'none', color: 'inherit' },
  '.rv_brand b': { fontSize: '1.18em', fontWeight: '700', letterSpacing: '0.01em' },
  '.rv_nav': { display: 'flex', flexWrap: 'wrap', gap: '0 1.15em', marginLeft: 'auto' },
  '.rv_nav a': { textDecoration: 'none', color: P.light.darkText, fontSize: '0.95em',
                 padding: '0.5em 0.1em', borderBottom: '2px solid transparent',
                 transition: 'color ' + L.motion.fast + ' ' + L.motion.easing },
  '.rv_nav a:hover': { color: P.primary.base },
  '.rv_nav a.rv_active': { color: P.primary.base, borderBottomColor: P.primary.base,
                           fontWeight: '600' },

  '.rv_version': { fontFamily: 'Menlo,Consolas,monospace', fontSize: '0.72em',
                   color: P.light.darkText, marginLeft: '1.1em', whiteSpace: 'nowrap',
                   alignSelf: 'center', cursor: 'help' },
  /* the overlap rail — every reading on one scale, so overlapping intervals are the
     first thing seen rather than something reconstructed from separate pictures */
  '.rv_rail': { background: P.surfaceAlt, border: '1px solid ' + P.light.border,
                borderRadius: L.radius.card, padding: '1.1em 1.2em 0.9em',
                display: 'flex', flexDirection: 'column', gap: '0.75em' },
  '.rv_rrow': { display: 'grid', gridTemplateColumns: 'minmax(0,13rem) 1fr 5rem',
                gap: '0.9em', alignItems: 'center' },
  '.rv_rlabel': { display: 'flex', flexDirection: 'column', minWidth: '0' },
  '.rv_rsub': { fontSize: '0.78em', color: P.light.darkText },
  '.rv_rtrack': { position: 'relative', height: '20px', background: P.background,
                  border: '1px solid ' + P.light.border, borderRadius: '3px' },
  '.rv_rband': { position: 'absolute', top: '0', bottom: '0', background: P.primary.border,
                 opacity: '0.9', borderRadius: '2px' },
  '.rv_rpoint': { position: 'absolute', top: '-3px', bottom: '-3px', width: '2.5px',
                  background: P.dark.base },
  '.rv_rnum': { fontFamily: 'Menlo,Consolas,monospace', textAlign: 'right',
                lineHeight: '1.25', fontVariantNumeric: 'tabular-nums' },
  '.rv_rnum b': { fontSize: '1em', fontWeight: '600' },
  '.rv_rnum span': { display: 'block', fontSize: '0.72em', color: P.light.darkText },
  '.rv_rscale': { display: 'grid', gridTemplateColumns: 'minmax(0,13rem) 1fr 5rem',
                  gap: '0.9em', fontFamily: 'Menlo,Consolas,monospace',
                  fontSize: '0.68em', color: P.light.darkText },
  '.rv_rticks': { display: 'flex', justifyContent: 'space-between' },
  '.rv_verdict': { marginTop: '0.8em', paddingTop: '0.75em',
                   borderTop: '1px solid ' + P.light.border,
                   display: 'flex', gap: '0.7em', alignItems: 'baseline', flexWrap: 'wrap' },
  '.rv_flag': { fontFamily: 'Menlo,Consolas,monospace', fontSize: '0.72em',
                letterSpacing: '0.08em', textTransform: 'uppercase', color: P.warning.base,
                border: '1px solid ' + P.warning.base, borderRadius: '3px',
                padding: '0.1em 0.45em', whiteSpace: 'nowrap' },
  '.rv_verdict p': { margin: '0', fontSize: '0.9em', color: P.light.darkText,
                     maxWidth: '58ch' },
  /* the paired grade — the strongest reading the page can give, so it leads, and the
     two axes sit side by side rather than collapsing into one number */
  '.rv_grade': { background: P.surfaceAlt, border: '1px solid ' + P.light.border,
                 borderRadius: L.radius.card, padding: '1.1em 1.2em 1em',
                 display: 'flex', flexDirection: 'column', gap: '0.85em',
                 marginBottom: '1.1em' },
  '.rv_grade h3': { margin: '0', fontSize: '1.02em', fontWeight: '650' },
  '.rv_fams': { display: 'flex', flexWrap: 'wrap', gap: '0.5em' },
  '.rv_fam': { display: 'flex', gap: '0.5em', alignItems: 'baseline',
               fontFamily: 'Menlo,Consolas,monospace', fontSize: '0.78em',
               fontVariantNumeric: 'tabular-nums', background: P.background,
               border: '1px solid ' + P.light.border, borderRadius: '3px',
               padding: '0.2em 0.55em' },
  '.rv_fam span': { color: P.light.darkText },
  '.rv_fam_bad': { borderColor: P.danger.base, color: P.danger.base },
  '.rv_fam_bad span': { color: P.danger.base },
  /* the multi-sample report page */
  '.rv_samples': { display: 'flex', flexDirection: 'column', gap: '0.8em' },
  '.rv_samplehead': { display: 'flex', gap: '0.6em', alignItems: 'center',
                      marginBottom: '0.55em' },
  '.rv_samplehead input': { flex: '1 1 auto', minWidth: '0' },
  '.rv_exportbar': { display: 'flex', gap: '0.6em', alignItems: 'center',
                     flexWrap: 'wrap', margin: '1em 0' },
  '.rv_lede': { color: P.light.darkText, maxWidth: '68ch', margin: '0 0 0.9em 0' },
  '.rv_mdsource': { background: P.surfaceAlt, border: '1px solid ' + P.light.border,
                    borderRadius: L.radius.card, padding: '1em', overflowX: 'auto',
                    fontSize: '0.78em', lineHeight: '1.5', whiteSpace: 'pre',
                    maxHeight: '22em' },
  '.rv_wrap': { maxWidth: '1280px', margin: '0 auto', padding: '0 3rem' },
  '.rv_hero': { padding: '1.3em 0 0 0' },

  'h1': { fontSize: '1.7em', letterSpacing: '-0.01em', margin: '0.5em 0 0.25em 0',
          fontWeight: '650' },
  'h2': { margin: '2.3em 0 0.55em 0', paddingBottom: '0.25em',
          borderBottom: '1px solid ' + P.light.border, fontSize: '1.12em',
          fontWeight: '650', color: P.dark.base },
  'h3': { margin: '1em 0 0.35em 0', fontSize: '1.02em' },
  'p': { margin: '0.55em 0' },
  'ul': { margin: '0.5em 0', paddingLeft: '1.4em' },
  'li': { margin: '0.3em 0' },
  'section': { marginBottom: '0.4em' },

  '.rv_code': { background: P.dark.base, color: P.light.base, border: 'none',
                borderLeft: '4px solid ' + P.primary.base, borderRadius: L.radius.card,
                padding: '0.8em 1em', margin: '0.7em 0', overflowX: 'auto',
                fontSize: '0.86em', lineHeight: '1.5' },

  /* light touch on BCCL's own components — extend, never re-implement */
  '.bw_bccl_card': { height: '100%' },
  '.rv_cards .bw_bccl_card': { transition: 'box-shadow ' + L.motion.normal + ', transform ' + L.motion.normal },
  '.rv_cards .bw_bccl_card:hover': { boxShadow: L.elevation.md, transform: 'translateY(-1px)' },
  '.bw_bccl_table': { width: '100%' },
  '.rv_scroll': { overflowX: 'auto' },

  'footer.rv_footer': { borderTop: '1px solid ' + P.light.border, marginTop: '2em',
                        padding: '1em 0 1.6em 0', opacity: '0.75', fontSize: '0.88em' }
}));

/* responsive rules belong to bw.responsive(), not hand-written @media */
bw.injectCSS(bw.responsive('.rv_wrap', {
  base: { padding: '0 1rem' },
  md: { padding: '0 3rem' }
}));
bw.injectCSS(bw.responsive('.rv_topbar_inner', {
  base: { padding: '0.55em 1rem' },
  md: { padding: '0.55em 3rem' }
}));
/* one grid definition every page reuses: stacks on phones, columns on desktop */
bw.injectCSS(bw.responsive('.rv_cards', {
  base: { display: 'grid', gap: '0.9em', gridTemplateColumns: '1fr' },
  md: { gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }
}));
bw.injectCSS(bw.responsive('.rv_split', {
  base: { display: 'grid', gap: '0.9em', gridTemplateColumns: '1fr' },
  md: { gridTemplateColumns: '1fr 1fr' }
}));

var NAV = [
  ['index.html', 'Overview'],
  ['how-it-works.html', 'How it works'],
  ['getting-started.html', 'Getting started'],
  ['background.html', 'Background'],
  ['demo.html', 'Demo'],
  ['compare.html', 'Compare'],
  ['report.html', 'Report'],
  ['https://github.com/deftio/revoice', 'GitHub']
];

/* Version, in small print. Generated into version.js by
   scripts/export_demo_baselines.py, so it cannot drift from the package it names; the
   guard keeps the page working if that file has not been generated yet. */
function versionTag() {
  if (typeof REVOICE_VERSION === 'undefined') return '';
  return { t: 'span', a: { class: 'rv_version',
                           title: 'voicemetric ' + REVOICE_VERSION.voicemetric +
                                  ' (' + REVOICE_VERSION.voicemetric_signature + ') · rubric ' +
                                  REVOICE_VERSION.rubric },
           c: 'revoice ' + REVOICE_VERSION.revoice };
}


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
      }) },
    versionTag()
  ]}};
}

function siteFooter() {
  return { t: 'footer', a: { class: 'rv_footer' }, c: [
    { t: 'span', a: { class: 'rv_mark', style: bw.s({ fontSize: '0.8em', marginRight: '0.6em' }) }, c: 'r<' },
    'BSD-2-Clause © M. A. Chatterjee / ',
    { t: 'a', a: { href: 'https://github.com/deftio' }, c: 'deftio' },
    ' · built with ',
    { t: 'a', a: { href: 'https://github.com/deftio/bitwrench' }, c: 'bitwrench' },
    ' · no cookies · privacy-preserving analytics (GoatCounter)',
    (typeof REVOICE_VERSION === 'undefined') ? '' :
      { t: 'span', c: ' · revoice ' + REVOICE_VERSION.revoice +
                      ' · voicemetric ' + REVOICE_VERSION.voicemetric +
                      ' · rubric ' + REVOICE_VERSION.rubric }
  ]};
}

function codeBlock(s) {
  return { t: 'pre', a: { class: 'rv_code' }, c: { t: 'code', c: s } };
}

function section(title, kids) {
  return { t: 'section', c: [{ t: 'h2', c: title }].concat(kids) };
}

/* cards in a responsive grid — bw.makeCard does the card, .rv_cards does the grid */
function cardRow(cards) {
  return { t: 'div', a: { class: 'rv_cards' }, c: cards.map(bw.makeCard) };
}

/* a table that scrolls rather than squashing on a phone */
function scrollTable(props) {
  return { t: 'div', a: { class: 'rv_scroll' }, c: bw.makeTable(props) };
}

function sitePage(active, contentKids) {
  return { t: 'div', c: [
    siteHeader(active),
    { t: 'div', a: { class: 'rv_wrap' },
      c: [{ t: 'div', a: { class: 'rv_hero' } }].concat(contentKids).concat([siteFooter()]) }
  ]};
}

bw.injectCSS(bw.responsive('.rv_rrow', {
  base: { gridTemplateColumns: '1fr', gap: '0.25em' },
  md: { gridTemplateColumns: 'minmax(0,13rem) 1fr 5rem', gap: '0.9em' }
}));

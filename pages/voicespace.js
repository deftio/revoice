/* Browser port of revoice/voicemetric/space.py + chart.py.
 *
 * The compare page builds its reference from text the reader pastes in, so this has to
 * run client-side; there is no server to ask. Every formula here mirrors the Python,
 * and tests/test_pages_parity.py asserts the two agree to 3 decimal places on shared
 * fixtures — a silent drift between them would mean the page and the tool quietly
 * disagree about the same document, which is worse than having no page.
 *
 * The reference POPULATION ships as demo/population.json (17 axes x mean/sd, ~1 KB,
 * fitted on the 1,594-document benchmark corpus). Without it the page would have to
 * treat whatever was pasted in as its own definition of typical prose, which puts every
 * coordinate near zero and makes the chart say nothing.
 */

var VS_AXES = [
  { name: 'sentence_length',         low: 'clipped',              high: 'long-breathed',            family: 'rhythm' },
  { name: 'sentence_variance',       low: 'metronomic',           high: 'varied',                   family: 'rhythm' },
  { name: 'paragraph_length',        low: 'short paragraphs',     high: 'long paragraphs',          family: 'structure' },
  { name: 'sentences_per_paragraph', low: 'one-idea paragraphs',  high: 'developed paragraphs',     family: 'structure' },
  { name: 'word_length',             low: 'plain words',          high: 'long words',               family: 'lexis' },
  { name: 'lexical_richness',        low: 'repetitive',           high: 'wide vocabulary',          family: 'lexis' },
  { name: 'readability',             low: 'demanding',            high: 'easy',                     family: 'lexis' },
  { name: 'subordination',           low: 'coordinate',           high: 'subordinate-heavy',        family: 'syntax' },
  { name: 'nominalization',          low: 'verbal',               high: 'abstract-nouny',           family: 'syntax' },
  { name: 'passivity',               low: 'active',               high: 'passive',                  family: 'syntax' },
  { name: 'adverbial',               low: 'spare',                high: '-ly heavy',                family: 'syntax' },
  { name: 'comma_density',           low: 'unpunctuated',         high: 'comma-heavy',              family: 'punctuation' },
  { name: 'punctuation_variety',     low: 'commas only',          high: 'semicolons/dashes/colons', family: 'punctuation' },
  { name: 'conjunction_openings',    low: 'formal openings',      high: 'and/but openings',         family: 'stance' },
  { name: 'contraction',             low: 'formal',               high: 'conversational',           family: 'stance' },
  { name: 'first_person',            low: 'impersonal',           high: 'first-person',             family: 'stance' },
  { name: 'second_person',           low: 'no address',           high: 'addresses the reader',     family: 'stance' }
];
var VS_AXIS_NAMES = VS_AXES.map(function (a) { return a.name; });

var VS_SUBORDINATORS = ('if when while because although though since unless until whereas ' +
  'whether after before as').split(' ');
var VS_CONJUNCTIONS = 'and but or nor yet so for'.split(' ');
var VS_ARTICLES = 'the a an'.split(' ');
var VS_PRONOUNS = ('i you he she it we they his her its our their my your this that these ' +
  'those there').split(' ');
var VS_PREPOSITIONS = ('of in to on at by with from into over under about through between ' +
  'against upon among').split(' ');
var VS_FIRST = 'i me my mine we us our ours'.split(' ');
var VS_SECOND = 'you your yours'.split(' ');
var VS_MIN_SPREAD = 0.15;   // mirrors voicemetric.space.MIN_SPREAD

function vsSet(list) { var o = {}; list.forEach(function (w) { o[w] = 1; }); return o; }
var VS_SUB = vsSet(VS_SUBORDINATORS), VS_CONJ = vsSet(VS_CONJUNCTIONS),
    VS_ART = vsSet(VS_ARTICLES), VS_PRON = vsSet(VS_PRONOUNS),
    VS_PREP = vsSet(VS_PREPOSITIONS), VS_1P = vsSet(VS_FIRST), VS_2P = vsSet(VS_SECOND);

function vsSyllables(w) {
  var count = 0, prev = false, i, v;
  for (i = 0; i < w.length; i++) {
    v = 'aeiouy'.indexOf(w[i]) >= 0;
    if (v && !prev) count++;
    prev = v;
  }
  if (w.charAt(w.length - 1) === 'e' && count > 1) count--;
  return Math.max(count, 1);
}

/* Yule's K — length-stable vocabulary richness. Lower means richer, which is why the
   axis negates it: every axis must point the way its name says. */
function vsYulesK(words) {
  var counts = {}, n = words.length, w, spectrum = {}, m2 = 0, k;
  if (n < 2) return 0;
  words.forEach(function (x) { counts[x] = (counts[x] || 0) + 1; });
  for (w in counts) spectrum[counts[w]] = (spectrum[counts[w]] || 0) + 1;
  for (k in spectrum) m2 += (k * k) * spectrum[k];
  return 10000 * (m2 - n) / (n * n);
}

function vsOpenerClass(w) {
  if (VS_ART[w]) return 'article';
  if (VS_PRON[w]) return 'pronoun';
  if (VS_CONJ[w]) return 'conjunction';
  if (VS_SUB[w]) return 'subordinator';
  if (VS_PREP[w]) return 'preposition';
  return 'other';
}

/* Absolute coordinates. Units differ per axis by design; standardisation is what makes
   them comparable — see vsStandardize. */
function vsCoordinates(text) {
  var words = (text.toLowerCase().match(/[a-zA-Z']+/g) || []);
  var sents = text.split(/(?<=[.!?])\s+|\n{2,}/).filter(function (s) { return s.trim(); });
  var n = Math.max(words.length, 1), ns = Math.max(sents.length, 1);

  var sentLens = sents.map(function (s) { return (s.match(/[a-zA-Z']+/g) || []).length; });
  if (!sentLens.length) sentLens = [0];
  var meanLen = sentLens.reduce(function (a, b) { return a + b; }, 0) / sentLens.length;
  var variance = sentLens.reduce(function (a, x) { return a + (x - meanLen) * (x - meanLen); }, 0) / sentLens.length;

  var paras = text.split(/\n\s*\n/).filter(function (p) { return p.trim(); });
  var paraLens = paras.map(function (p) { return (p.match(/[a-zA-Z']+/g) || []).length; });
  if (!paraLens.length) paraLens = [n];
  var sentsPerPara = paras.map(function (p) {
    return Math.max(p.split(/(?<=[.!?])\s+/).filter(function (x) { return x.trim(); }).length, 1);
  });
  if (!sentsPerPara.length) sentsPerPara = [1];

  var wordLens = words.map(function (w) { return w.length; });
  if (!wordLens.length) wordLens = [0];
  var syll = words.reduce(function (a, w) { return a + vsSyllables(w); }, 0);
  var flesch = 206.835 - 1.015 * (n / ns) - 84.6 * (syll / n);

  var lyRate = words.filter(function (w) { return w.length > 4 && /ly$/.test(w); }).length / n;
  var nominal = words.filter(function (w) { return /(tion|ment|ness|ity)s?$/.test(w); }).length / n;
  var passive = (text.toLowerCase().match(/\b(?:was|were|been|being|is|are)\s+\w+ed\b/g) || []).length / ns;
  var subord = words.filter(function (w) { return VS_SUB[w]; }).length / n;

  var openers = {}, total = 0;
  sents.forEach(function (s) {
    var first = (s.toLowerCase().match(/[a-zA-Z']+/g) || [])[0];
    if (first) { var c = vsOpenerClass(first); openers[c] = (openers[c] || 0) + 1; total++; }
  });
  var conjStart = (openers.conjunction || 0) / Math.max(total, 1);

  var contraction = (text.match(/\b\w+(?:n't|'s|'re|'ll|'ve|'d|'m)\b/gi) || []).length / n;
  var per = function (ch) { return (text.split(ch).length - 1) / ns; };

  var mean = function (xs) { return xs.reduce(function (a, b) { return a + b; }, 0) / xs.length; };
  /* Rounded exactly where the Python fingerprint rounds. Not cosmetic: without it the
     two implementations disagree in the third decimal and a parity test can only be
     written loosely, which is the same as not having one. */
  var r = function (x, places) { var f = Math.pow(10, places); return Math.round(x * f) / f; };
  return {
    sentence_length: r(meanLen, 2),
    sentence_variance: meanLen ? r(variance / meanLen, 2) : 0,
    paragraph_length: mean(paraLens),
    sentences_per_paragraph: r(mean(sentsPerPara), 2),
    word_length: r(mean(wordLens), 2),
    lexical_richness: -r(vsYulesK(words), 2),
    readability: r(flesch, 1),
    subordination: r(subord, 5) * 100,
    nominalization: r(nominal, 5) * 100,
    passivity: r(passive, 4),
    adverbial: r(lyRate, 5) * 100,
    comma_density: r(per(','), 4),
    punctuation_variety: r(per(';'), 4) + r(per(':'), 4) + r(per('—'), 4) + r(per('–'), 4),
    conjunction_openings: r(conjStart, 4) * 100,
    contraction: contraction * 100,
    first_person: words.filter(function (w) { return VS_1P[w]; }).length / n * 100,
    second_person: words.filter(function (w) { return VS_2P[w]; }).length / n * 100
  };
}

function vsMeanStd(xs) {
  var m = xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
  var v = xs.reduce(function (a, x) { return a + (x - m) * (x - m); }, 0) / xs.length;
  return [m, Math.sqrt(v)];
}

/* population: {stats: {axis: [mean, sd]}} — z-scores against real prose, not self. */
function vsStandardize(population, textOrCoords) {
  var c = (typeof textOrCoords === 'string') ? vsCoordinates(textOrCoords) : textOrCoords;
  var z = {};
  VS_AXIS_NAMES.forEach(function (a) {
    var st = population.stats[a] || [0, 1];
    z[a] = (c[a] - st[0]) / Math.max(st[1], 1e-9);
  });
  return z;
}

/* A voice is a region — centroid and spread — not a point. */
function vsFitRegion(name, texts, population) {
  var zs = texts.map(function (t) { return vsStandardize(population, t); });
  var centroid = {}, spread = {};
  VS_AXIS_NAMES.forEach(function (a) {
    var ms = vsMeanStd(zs.map(function (z) { return z[a]; }));
    centroid[a] = ms[0];
    spread[a] = Math.max(ms[1], VS_MIN_SPREAD);
  });
  return { name: name, centroid: centroid, spread: spread, n: zs.length };
}

function vsAxisSimilarity(z, region) {
  var out = {};
  VS_AXIS_NAMES.forEach(function (a) {
    out[a] = Math.exp(-Math.abs(z[a] - region.centroid[a]) / region.spread[a]);
  });
  return out;
}

function vsWindows(text, targetWords) {
  targetWords = targetWords || 220;
  var paras = text.split(/\n\s*\n/).map(function (p) { return p.trim(); })
                  .filter(function (p) { return p; });
  if (!paras.length) return [];
  var out = [], cur = [], count = 0;
  paras.forEach(function (p) {
    cur.push(p); count += p.split(/\s+/).length;
    if (count >= targetWords) { out.push(cur.join('\n\n')); cur = []; count = 0; }
  });
  if (cur.length) {
    var tail = cur.join('\n\n');
    if (out.length && count < targetWords / 2) out[out.length - 1] += '\n\n' + tail;
    else out.push(tail);
  }
  return out;
}

function vsPercentile(sorted, q) {
  if (!sorted.length) return NaN;
  var idx = q * (sorted.length - 1), lo = Math.floor(idx), hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

/* Deterministic PRNG so a given text always yields the same interval. Mirrors the
   Python's seeded random.Random rather than using Math.random. */
function vsRng(seed) {
  var s = seed >>> 0;
  return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

/* Overall and per-axis similarity, each with a bootstrap interval over the document's
   own paragraphs. Mirrors voicemetric.space.similarity_report. */
function vsSimilarityReport(text, region, population, replicates, confidence, seed) {
  replicates = replicates || 400; confidence = confidence || 0.9;
  var ws = vsWindows(text);
  var zs = ws.length ? ws.map(function (w) { return vsStandardize(population, w); })
                     : [vsStandardize(population, text)];
  var pointZ = {};
  VS_AXIS_NAMES.forEach(function (a) {
    pointZ[a] = zs.reduce(function (acc, z) { return acc + z[a]; }, 0) / zs.length;
  });
  var pointAxis = vsAxisSimilarity(pointZ, region);
  var pointOverall = 100 * VS_AXIS_NAMES.reduce(function (acc, a) {
    return acc + pointAxis[a]; }, 0) / VS_AXIS_NAMES.length;

  var rnd = vsRng(seed || 17), bootOverall = [], bootAxis = {}, i, j;
  VS_AXIS_NAMES.forEach(function (a) { bootAxis[a] = []; });
  var reliable = zs.length >= 3;
  if (reliable) {
    for (i = 0; i < replicates; i++) {
      var pick = [];
      for (j = 0; j < zs.length; j++) pick.push(zs[Math.floor(rnd() * zs.length)]);
      var zbar = {};
      VS_AXIS_NAMES.forEach(function (a) {
        zbar[a] = pick.reduce(function (acc, z) { return acc + z[a]; }, 0) / pick.length;
      });
      var sims = vsAxisSimilarity(zbar, region);
      bootOverall.push(100 * VS_AXIS_NAMES.reduce(function (acc, a) {
        return acc + sims[a]; }, 0) / VS_AXIS_NAMES.length);
      VS_AXIS_NAMES.forEach(function (a) { bootAxis[a].push(sims[a]); });
    }
  }
  var loQ = (1 - confidence) / 2, hiQ = 1 - loQ;
  var interval = function (vals, point) {
    if (vals.length < 2) return [point, point];
    var v = vals.slice().sort(function (a, b) { return a - b; });
    return [vsPercentile(v, loQ), vsPercentile(v, hiQ)];
  };
  var o = interval(bootOverall, pointOverall), axes = {};
  VS_AXIS_NAMES.forEach(function (a) {
    var b = interval(bootAxis[a], pointAxis[a]);
    axes[a] = { similarity: pointAxis[a], low: b[0], high: b[1],
                deviation: (pointZ[a] - region.centroid[a]) / region.spread[a] };
  });
  return { voice: region.name, overall: pointOverall, low: o[0], high: o[1],
           confidence: confidence, windows: zs.length,
           words: (text.match(/\S+/g) || []).length,
           interval_reliable: reliable, axes: axes };
}

/* ---- the chart, mirroring revoice/voicemetric/chart.py ----
   Colours are CSS custom properties with literal fallbacks, so the same markup works
   inline in a themed page and as a standalone file. Every value is printed as well as
   drawn: nothing here depends on colour alone. */

function vsVerdict(r) {
  var width = r.high - r.low;
  if (!r.interval_reliable)
    return ['no interval — too short to resample',
            'Under three paragraphs there is nothing to bootstrap, so this number has no ' +
            'measured uncertainty. Treat it as an impression.'];
  if (width > 25)
    return ['wide interval — inconclusive',
            'The score moves ' + width.toFixed(0) + ' points depending on which part of the ' +
            'document is sampled. That is a property of the text, not a rounding error.'];
  if (r.low >= 55) return ['consistently close', 'Every resample stays close to this voice.'];
  if (r.high <= 40) return ['consistently distant', 'No resample comes close to this voice.'];
  return ['moderate, with real uncertainty',
          'The interval spans the range where this measure cannot separate two authors of ' +
          'the same genre. Read the axes, not the headline.'];
}

function vsEsc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function vsRenderChart(r, title, subtitle) {
  var INK = 'var(--vc-ink, #23262b)', MUTED = 'var(--vc-muted, #6b7280)',
      RULE = 'var(--vc-rule, #d9dce1)', PANEL = 'var(--vc-panel, #f6f7f9)',
      NEAR = 'var(--vc-near, #2f6f9f)', FAR = 'var(--vc-far, #c98a2b)',
      BAND = 'var(--vc-band, #9fc0da)';
  var ROW = 22, GAP = 12, PLOT = 300, LABEL = 168, VALUE = 150, M = 18, MAXSD = 3;

  var families = [];
  VS_AXES.forEach(function (a) { if (families.indexOf(a.family) < 0) families.push(a.family); });
  var headerH = 128, bodyH = VS_AXES.length * ROW + families.length * (GAP + 14) + 16;
  var footerH = 52, W = M * 2 + LABEL + PLOT + VALUE, H = headerH + bodyH + footerH;
  var cx = M + LABEL + PLOT / 2, scale = (PLOT / 2) / MAXSD, p = [];

  p.push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H + '" ' +
         'width="' + W + '" height="' + H + '" role="img" aria-label="' +
         vsEsc(title || 'voice similarity') + '">');
  p.push('<text x="' + M + '" y="24" font-size="14" font-weight="650" fill="' + INK + '">' +
         vsEsc(title || 'Voice similarity') + '</text>');
  if (subtitle)
    p.push('<text x="' + M + '" y="42" font-size="10.5" fill="' + MUTED + '">' +
           vsEsc(subtitle) + '</text>');

  var bx = M, by = 58, bw = W - M * 2, bh = 15;
  p.push('<rect x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh +
         '" rx="4" fill="' + PANEL + '"/>');
  if (r.interval_reliable) {
    var lo = bx + bw * r.low / 100, hi = bx + bw * r.high / 100;
    p.push('<rect x="' + lo.toFixed(1) + '" y="' + by + '" width="' +
           Math.max(hi - lo, 1).toFixed(1) + '" height="' + bh + '" rx="4" fill="' + BAND + '"/>');
  }
  var pt = bx + bw * r.overall / 100;
  p.push('<line x1="' + pt.toFixed(1) + '" y1="' + (by - 4) + '" x2="' + pt.toFixed(1) +
         '" y2="' + (by + bh + 4) + '" stroke="' + INK + '" stroke-width="2.5"/>');
  [0, 25, 50, 75, 100].forEach(function (t) {
    var tx = bx + bw * t / 100;
    p.push('<text x="' + tx.toFixed(1) + '" y="' + (by + bh + 13) + '" font-size="8.5" fill="' +
           MUTED + '" text-anchor="middle">' + t + '</text>');
  });
  var v = vsVerdict(r);
  var head = r.interval_reliable
    ? r.overall.toFixed(1) + '  (' + Math.round(r.confidence * 100) + '% interval ' +
      r.low.toFixed(1) + '–' + r.high.toFixed(1) + ')'
    : r.overall.toFixed(1) + '  (no interval)';
  p.push('<text x="' + M + '" y="' + (by + bh + 30) + '" font-size="11.5" font-weight="600" fill="' +
         INK + '">' + vsEsc(head) + '</text>');
  p.push('<text x="' + (M + 205) + '" y="' + (by + bh + 30) + '" font-size="11.5" fill="' +
         MUTED + '">' + vsEsc(v[0]) + '</text>');

  var y = headerH;
  families.forEach(function (fam) {
    p.push('<text x="' + M + '" y="' + y + '" font-size="9.5" font-weight="650" fill="' + MUTED +
           '" letter-spacing="0.06em">' + fam.toUpperCase() + '</text>');
    y += 10;
    VS_AXES.filter(function (a) { return a.family === fam; }).forEach(function (axis) {
      var d = r.axes[axis.name];
      var dev = Math.max(-MAXSD, Math.min(MAXSD, d.deviation));
      var col = d.similarity >= 0.5 ? NEAR : FAR, mid = y + ROW / 2;
      p.push('<text x="' + M + '" y="' + (mid + 3.5) + '" font-size="10.5" fill="' + INK + '">' +
             axis.name + '</text>');
      p.push('<rect x="' + (M + LABEL) + '" y="' + (y + 3) + '" width="' + PLOT + '" height="' +
             (ROW - 6) + '" fill="' + PANEL + '"/>');
      p.push('<line x1="' + cx + '" y1="' + (y + 2) + '" x2="' + cx + '" y2="' + (y + ROW - 2) +
             '" stroke="' + RULE + '"/>');
      var bwid = Math.abs(dev) * scale, bxx = dev >= 0 ? cx : cx - bwid;
      p.push('<rect x="' + bxx.toFixed(1) + '" y="' + (y + 6) + '" width="' +
             Math.max(bwid, 1).toFixed(1) + '" height="' + (ROW - 12) + '" rx="2" fill="' + col +
             '" opacity="0.85"/>');
      if (r.interval_reliable) {
        var half = Math.min((d.high - d.low) * 1.5, MAXSD) * scale / 2;
        var c0 = bxx + bwid / 2;
        p.push('<line x1="' + Math.max(cx - PLOT / 2, c0 - half).toFixed(1) + '" y1="' + mid +
               '" x2="' + Math.min(cx + PLOT / 2, c0 + half).toFixed(1) + '" y2="' + mid +
               '" stroke="' + INK + '" stroke-width="1" opacity="0.45"/>');
      }
      p.push('<text x="' + (M + LABEL + PLOT + 8) + '" y="' + (mid + 3.5) + '" font-size="9.5" fill="' +
             MUTED + '">' + d.similarity.toFixed(2) + '  ' +
             vsEsc(dev > 0 ? axis.high : axis.low) + '</text>');
      y += ROW;
    });
    y += GAP;
  });

  var fy = H - footerH + 14;
  p.push('<line x1="' + M + '" y1="' + (fy - 12) + '" x2="' + (W - M) + '" y2="' + (fy - 12) +
         '" stroke="' + RULE + '"/>');
  p.push('<text x="' + M + '" y="' + (fy + 2) + '" font-size="9" fill="' + MUTED + '">' +
         vsEsc(v[1]) + '</text>');
  p.push('<text x="' + M + '" y="' + (fy + 15) + '" font-size="9" fill="' + MUTED + '">' +
         'Bars: signed deviation in the voice&#8217;s own standard deviations (left = less, ' +
         'right = more); whiskers are the bootstrap interval over ' + r.windows + ' windows.</text>');
  p.push('</svg>');
  return p.join('');
}

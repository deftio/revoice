/* Browser port of revoice/voicemetric/features.py + baseline.py.
 *
 * This is one half of the engine; pages/voicespace.js is the other (space.py,
 * chart.py, transfer.py). Together they are the whole of `revoice.voicemetric` as it
 * runs in a browser, and they mirror the Python module split one-for-one so that a
 * reader can hold the two side by side.
 *
 * ---------------------------------------------------------------------------------
 * WHY THIS EXISTS TWICE, AND WHAT KEEPS THE TWO HONEST
 *
 * The compare page is served off GitHub Pages with no server to ask, so the engine has
 * to run client-side. Python cannot; a 10 MB Pyodide payload could, but it would be
 * slower to start and heavier to ship than this file. So the engine exists twice.
 *
 * Two implementations of anything drift. The only question is what you do about it.
 * The file this replaces — pages/stylometry.js — is the cautionary case: it began as
 * "a JS port of the demo subset", the Python was then refitted three times and grew
 * six components, and nothing tested the JS. By the time anyone measured, the page was
 * scoring with `ngram` weighted 0.600 against a fitted 0.181, `rhythm` at 0.1 against a
 * fitted 0.0, and no `richness` or `structure` at all. On 112 trials across 28 authors
 * it reached AUC 0.688 where Python reached 0.793 — and its headline sigma reached
 * 0.662. It ranked Twain's own other work as LESS like Twain than Bret Harte was.
 *
 * The split that prevents a repeat:
 *
 *   DATA      generated. Every word list, bin edge, component weight and axis name
 *             comes from pages/engine-constants.js, which scripts/export_demo_baselines.py
 *             writes out of the Python. Nothing here is hand-typed, so nothing here can
 *             be edited into disagreement. That is what actually went wrong last time.
 *   ALGORITHM duplicated, and tested. tests/test_pages_parity.py runs this file under
 *             node against the real Python on shared fixtures on every test run, and
 *             fails the build on divergence.
 *
 * ---------------------------------------------------------------------------------
 * HOW CLOSE "MATCHING" MEANS
 *
 * Agreement is to a few decimal places per quantity, not bit-for-bit, and the parity
 * test states a tolerance per family rather than asserting equality. The residual is
 * rounding, not arithmetic:
 *
 *   - Python's round() breaks exact ties to even; JavaScript's Math.round() breaks them
 *     away from zero. fingerprint() rounds ~25 values to 4-6 places, and a ratio like
 *     1/32 is an exact tie at four places (0.03125 -> 0.0312 in Python, 0.0313 here).
 *   - Counter.most_common() and Array.sort() are both stable, so equal-frequency
 *     n-grams keep insertion order in both — but a tie at the 300th position can still
 *     select a different gram, worth ~1e-6 of a cosine over 300 terms.
 *
 * Neither is worth emulating: the cost is real complexity in the hot path, and the
 * effect is invisible against a composite reported to one decimal of 100. What is NOT
 * acceptable, and what the tests forbid, is a difference in what is computed.
 *
 * One thing here IS exact rather than tolerant: n-gram counting uses Map, not a plain
 * object. Object keys that look like array indices ("123" is a real char 3-gram) are
 * enumerated before string keys, which would reorder the whole top-N selection. That is
 * not a rounding difference, so it is not allowed to be one.
 */

/* ---- runtime version support ------------------------------------------------
   Same shape as the rest of the family: a string to print, a tuple to compare, and an
   everything-at-once accessor. `vmVersions()` is the one worth reaching for — this file
   is a PORT of the Python engine, so "which engine produced this number" is exactly the
   question a surprising result turns on, and the signature answers whether two results
   are comparable at all even when the version has not moved.

   All of it is generated from revoice.versions() into engine-constants.js, so the page
   cannot claim a version the package does not have. */

var VM_VERSION = VM_CONST.VERSIONS.voicemetric;
var VM_VERSION_INFO = VM_VERSION.split('.').map(Number);

function vmVersion() { return VM_VERSION; }
function vmVersionInfo() { return VM_VERSION_INFO.slice(); }
function vmSignature() { return VM_CONST.VERSIONS.voicemetric_signature; }

/* Every component, one call — what a bug report should carry. */
function vmVersions() {
  var out = {};
  for (var k in VM_CONST.VERSIONS) out[k] = VM_CONST.VERSIONS[k];
  return out;
}

/* ---- small helpers, mirroring the Python exactly ---- */

function vmRound(x, nd) {
  /* Python rounds half-to-even, JS half-away-from-zero. See the header: the difference
     is left in place deliberately, and the parity tolerance covers it. Rounding is kept
     rather than dropped because the Python fingerprint rounds, and those rounded values
     feed the baseline — dropping it here would be a real arithmetic difference. */
  var m = Math.pow(10, nd);
  return Math.round(x * m) / m;
}

function vmSet(list) { var o = Object.create(null); for (var i = 0; i < list.length; i++) o[list[i]] = 1; return o; }

var VM_FW = VM_CONST.FUNCTION_WORDS;
var VM_FW_SET = vmSet(VM_FW);
var VM_ART = vmSet(VM_CONST.ARTICLES), VM_PRON = vmSet(VM_CONST.PRONOUNS);
var VM_CONJ = vmSet(VM_CONST.CONJUNCTIONS), VM_SUB = vmSet(VM_CONST.SUBORDINATORS);
var VM_PREP = vmSet(VM_CONST.PREPOSITIONS), VM_STOP = vmSet(VM_CONST.STOP);
var VM_VOWELS = 'aeiouy';

function vmSyllables(word) {
  var w = word.toLowerCase(), count = 0, prev = false, i, v;
  for (i = 0; i < w.length; i++) {
    v = VM_VOWELS.indexOf(w[i]) >= 0;
    if (v && !prev) count++;
    prev = v;
  }
  if (w.charAt(w.length - 1) === 'e' && count > 1) count--;
  return Math.max(count, 1);
}

/* features.tokenize -> [words, sentences] */
function vmTokenize(text) {
  var words = text.toLowerCase().match(/[a-zA-Z']+/g) || [];
  var sentences = text.split(/(?<=[.!?])\s+|\n{2,}/).filter(function (s) { return s.trim(); });
  return [words, sentences];
}

function vmWordsIn(s) { return (s.match(/[a-zA-Z']+/g) || []).length; }

function vmHist(values, bins) {
  var counts = [], i, j, total = 0;
  for (i = 0; i < bins.length - 1; i++) counts.push(0);
  for (i = 0; i < values.length; i++) {
    for (j = 0; j < bins.length - 1; j++) {
      if (values[i] >= bins[j] && values[i] < bins[j + 1]) { counts[j]++; break; }
    }
  }
  for (i = 0; i < counts.length; i++) total += counts[i];
  total = Math.max(total, 1);
  return counts.map(function (c) { return vmRound(c / total, 4); });
}

/* Counting uses Map throughout: see the header on integer-like object keys. */
function vmCount(items) {
  var m = new Map(), i;
  for (i = 0; i < items.length; i++) m.set(items[i], (m.get(items[i]) || 0) + 1);
  return m;
}

function vmSumValues(m) { var t = 0; m.forEach(function (v) { t += v; }); return t; }

/* Counter.most_common(n): sort by count descending, ties keeping insertion order.
   Python's nlargest and JS's Array.sort are both stable, so this matches. */
function vmMostCommon(counter, top) {
  var entries = Array.from(counter.entries());
  entries.sort(function (a, b) { return b[1] - a[1]; });
  return entries.slice(0, top);
}

function vmYulesK(counts) {
  var n = vmSumValues(counts);
  if (n < 2) return 0.0;
  var spectrum = new Map(), m2 = 0;
  counts.forEach(function (c) { spectrum.set(c, (spectrum.get(c) || 0) + 1); });
  spectrum.forEach(function (v, i) { m2 += i * i * v; });
  return 10000.0 * (m2 - n) / (n * n);
}

function vmMtld(words, threshold) {
  threshold = threshold === undefined ? 0.72 : threshold;
  function pass(seq) {
    var factors = 0, types = Object.create(null), nTypes = 0, tokens = 0, i, w;
    for (i = 0; i < seq.length; i++) {
      w = seq[i];
      if (!types[w]) { types[w] = 1; nTypes++; }
      tokens++;
      if (tokens && nTypes / tokens <= threshold) {
        factors++; types = Object.create(null); nTypes = 0; tokens = 0;
      }
    }
    if (tokens) {                       // partial trailing factor, scaled by how far it got
      var ttr = nTypes / tokens;
      factors += ttr < 1.0 ? (1 - ttr) / (1 - threshold) : 0.0;
    }
    return factors ? seq.length / factors : seq.length;
  }
  if (words.length < 20) return 0.0;
  return vmRound((pass(words) + pass(words.slice().reverse())) / 2, 3);
}

function vmOpenerClass(w) {
  if (VM_ART[w]) return 'article';
  if (VM_PRON[w]) return 'pronoun';
  if (VM_CONJ[w]) return 'conjunction';
  if (VM_SUB[w]) return 'subordinator';
  if (VM_PREP[w]) return 'preposition';
  return 'other';
}

/* ---- profiles: char n-grams, word bigrams, function-word bigrams ---- */

function vmCharNgramProfile(text, n, top) {
  n = n || VM_CONST.CHAR_NGRAM_N; top = top || VM_CONST.TOP_CHAR_NGRAMS;
  var s = text.toLowerCase().replace(/\s+/g, ' '), grams = new Map(), i, g;
  for (i = 0; i <= s.length - n; i++) {
    g = s.substr(i, n);
    grams.set(g, (grams.get(g) || 0) + 1);
  }
  var total = Math.max(vmSumValues(grams), 1), out = Object.create(null);
  vmMostCommon(grams, top).forEach(function (e) { out[e[0]] = vmRound(e[1] / total, 6); });
  return out;
}

function vmWordBigramProfile(text, top) {
  top = top || VM_CONST.TOP_WORD_BIGRAMS;
  var words = vmTokenize(text)[0], grams = new Map(), i, g;
  for (i = 0; i < words.length - 1; i++) {
    g = words[i] + ' ' + words[i + 1];
    grams.set(g, (grams.get(g) || 0) + 1);
  }
  var total = Math.max(vmSumValues(grams), 1), out = Object.create(null);
  vmMostCommon(grams, top).forEach(function (e) { out[e[0]] = vmRound(e[1] / total, 6); });
  return out;
}

/* Bigrams where BOTH words are function words — content-free joinery habits. The plain
   word-bigram profile mixes these with topical pairs; this one cannot. */
function vmFunctionWordBigramProfile(text, top) {
  top = top || 150;
  var words = vmTokenize(text)[0], grams = new Map(), i, g;
  for (i = 0; i < words.length - 1; i++) {
    if (VM_FW_SET[words[i]] && VM_FW_SET[words[i + 1]]) {
      g = words[i] + ' ' + words[i + 1];
      grams.set(g, (grams.get(g) || 0) + 1);
    }
  }
  var total = Math.max(vmSumValues(grams), 1), out = Object.create(null);
  vmMostCommon(grams, top).forEach(function (e) { out[e[0]] = vmRound(e[1] / total, 6); });
  return out;
}

function vmContentTerms(text) {
  var words = vmTokenize(text)[0], m = new Map(), i, w;
  for (i = 0; i < words.length; i++) {
    w = words[i];
    if (!VM_STOP[w] && w.length > 2) m.set(w, (m.get(w) || 0) + 1);
  }
  return m;
}

function vmTfidfVector(terms, df, nDocs) {
  var total = Math.max(vmSumValues(terms), 1), vec = Object.create(null);
  terms.forEach(function (c, t) {
    var idf = Math.log((nDocs + 1) / ((df[t] || 0) + 1)) + 1;
    vec[t] = (c / total) * idf;
  });
  return vec;
}

function vmCosine(a, b) {
  if (!a || !b) return 0.0;
  var dot = 0, na = 0, nb = 0, k;
  for (k in a) { dot += a[k] * (b[k] || 0); na += a[k] * a[k]; }
  for (k in b) { nb += b[k] * b[k]; }
  if (!na || !nb) return 0.0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/* ---- features.fingerprint: the full 29-field vector ---- */

function vmFingerprint(text) {
  var tk = vmTokenize(text), words = tk[0], sentences = tk[1];
  var nWords = Math.max(words.length, 1), nSents = Math.max(sentences.length, 1), i;

  var sentLens = sentences.map(vmWordsIn);
  if (!sentLens.length) sentLens = [0];
  var meanLen = sentLens.reduce(function (a, b) { return a + b; }, 0) / sentLens.length;
  var varr = sentLens.reduce(function (a, x) { return a + (x - meanLen) * (x - meanLen); }, 0)
             / sentLens.length;

  var counts = vmCount(words);
  var hapax = 0; counts.forEach(function (c) { if (c === 1) hapax++; });
  var punctChars = VM_CONST.PUNCTS, punct = new Map();
  for (i = 0; i < text.length; i++) {
    if (punctChars.indexOf(text[i]) >= 0) punct.set(text[i], (punct.get(text[i]) || 0) + 1);
  }
  var wordLens = words.map(function (w) { return w.length; });
  if (!wordLens.length) wordLens = [0];

  var lyCount = 0, nominalCount = 0;
  for (i = 0; i < words.length; i++) {
    if (words[i].slice(-2) === 'ly' && words[i].length > 4) lyCount++;
    if (/(tion|ment|ness|ity)s?$/.test(words[i])) nominalCount++;
  }
  var lyRate = lyCount / nWords, nominalRate = nominalCount / nWords;
  var passiveRate = (text.toLowerCase().match(/\b(?:was|were|been|being|is|are)\s+\w+ed\b/g) || []).length
                    / nSents;

  var syll = 0;
  for (i = 0; i < words.length; i++) syll += vmSyllables(words[i]);
  var flesch = 206.835 - 1.015 * (nWords / nSents) - 84.6 * (syll / nWords);

  /* structural: paragraph shape — one of the most habitual things about a writer
     (Writeprints calls this the structural family) */
  var paras = text.split(/\n\s*\n/).filter(function (p) { return p.trim(); });
  var paraLens = paras.map(vmWordsIn);
  if (!paraLens.length) paraLens = [0];
  var sentsPerPara = paras.map(function (p) {
    return Math.max(p.split(/(?<=[.!?])\s+/).filter(function (x) { return x.trim(); }).length, 1);
  });
  if (!sentsPerPara.length) sentsPerPara = [1];

  /* syntactic proxies, no parser required */
  var openers = Object.create(null);
  VM_CONST.OPENER_CLASSES.forEach(function (k) { openers[k] = 0; });
  var nOpen = 0;
  sentences.forEach(function (s) {
    var first = s.toLowerCase().match(/[a-zA-Z']+/g);
    if (first && first.length) { openers[vmOpenerClass(first[0])]++; nOpen++; }
  });
  nOpen = Math.max(nOpen, 1);
  var subCount = 0;
  for (i = 0; i < words.length; i++) if (VM_SUB[words[i]]) subCount++;
  var subordinatorRate = subCount / nWords;
  var conjunctionStart = openers.conjunction / nOpen;

  var contractionRate = (text.match(/\b\w+(?:n't|'s|'re|'ll|'ve|'d|'m)\b/gi) || []).length / nWords;
  var hyphenRate = (text.match(/\w-\w/g) || []).length / nWords;

  /* punctuation RATIOS: how marks are traded off against each other — far more personal
     than any single rate, and scale-free by construction */
  var nComma = Math.max(punct.get(',') || 0, 1);
  var semicolonPerComma = (punct.get(';') || 0) / nComma;
  var dashPerComma = ((punct.get('—') || 0) + (punct.get('–') || 0)) / nComma;
  var colonPerComma = (punct.get(':') || 0) / nComma;

  var sum = function (xs) { return xs.reduce(function (a, b) { return a + b; }, 0); };
  var openerDist = Object.create(null);
  VM_CONST.OPENER_CLASSES.forEach(function (k) { openerDist[k] = vmRound(openers[k] / nOpen, 4); });
  var fwFreq = Object.create(null);
  VM_FW.forEach(function (w) { fwFreq[w] = vmRound((counts.get(w) || 0) / nWords, 5); });
  var punctPer = Object.create(null);
  punct.forEach(function (c, p) { punctPer[p] = vmRound(c / nSents, 4); });

  return {
    words: words.length,
    sentences: sentences.length,
    mean_sentence_len: vmRound(meanLen, 2),
    sentence_len_std: vmRound(Math.sqrt(varr), 2),
    burstiness: meanLen ? vmRound(varr / meanLen, 2) : 0.0,
    sent_len_hist: vmHist(sentLens, VM_CONST.SENT_HIST_BINS),
    word_len_hist: vmHist(wordLens, VM_CONST.WORD_HIST_BINS),
    para_len_hist: vmHist(paraLens, VM_CONST.PARA_HIST_BINS),
    mean_para_len: vmRound(sum(paraLens) / paraLens.length, 2),
    mean_sents_per_para: vmRound(sum(sentsPerPara) / sentsPerPara.length, 2),
    mean_word_len: vmRound(sum(wordLens) / wordLens.length, 2),
    type_token_ratio: vmRound(counts.size / nWords, 4),
    hapax_ratio: vmRound(hapax / nWords, 4),
    yules_k: vmRound(vmYulesK(counts), 2),
    mtld: vmMtld(words),
    adverb_ly_rate: vmRound(lyRate, 5),
    nominalization_rate: vmRound(nominalRate, 5),
    passive_rate: vmRound(passiveRate, 4),
    subordinator_rate: vmRound(subordinatorRate, 5),
    conjunction_start_rate: vmRound(conjunctionStart, 4),
    contraction_rate: vmRound(contractionRate, 5),
    hyphen_rate: vmRound(hyphenRate, 5),
    semicolon_per_comma: vmRound(semicolonPerComma, 4),
    dash_per_comma: vmRound(dashPerComma, 4),
    colon_per_comma: vmRound(colonPerComma, 4),
    flesch: vmRound(flesch, 1),
    opener_dist: openerDist,
    function_word_freq: fwFreq,
    punct_per_sentence: punctPer
  };
}

/* ================================================================================
   baseline.py — corpus baselines and the composite voice-match score.

   The weights below are NOT in this file. They come from VM_CONST.WEIGHTS, generated
   out of Python, because they are fitted by `revoice bench --fit` and have been
   refitted three times. Hand-copying them here is precisely the mistake that left the
   old page scoring `ngram` at 0.6 against a fitted 0.181.
   ================================================================================ */

function vmMeanStd(xs) {
  if (!xs.length) return [0.0, 0.0];
  var m = xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
  var v = xs.reduce(function (a, x) { return a + (x - m) * (x - m); }, 0) / xs.length;
  return [m, Math.sqrt(v)];
}

/* Insertion-ordered accumulate-then-rank, matching Python's dict + stable sorted().
   A Map because char 3-grams like "123" are integer-like object keys and would jump
   the queue — see the file header. */
function vmAccumulate(maps, nTexts, top, decimals) {
  var cent = new Map();
  maps.forEach(function (prof) {
    for (var k in prof) cent.set(k, (cent.get(k) || 0) + prof[k]);
  });
  var entries = Array.from(cent.entries()).map(function (e) { return [e[0], e[1] / nTexts]; });
  entries.sort(function (a, b) { return b[1] - a[1]; });
  var out = Object.create(null);
  entries.slice(0, top).forEach(function (e) { out[e[0]] = vmRound(e[1], decimals); });
  return out;
}

/* baseline.baseline_from_texts — the unit of aggregation is the DOCUMENT. */
function vmBaselineFromTexts(texts) {
  var fps = texts.map(vmFingerprint);
  if (!fps.length) return {};
  var i;

  var fw = Object.create(null);
  VM_FW.forEach(function (w) {
    var ms = vmMeanStd(fps.map(function (fp) { return fp.function_word_freq[w] || 0.0; }));
    fw[w] = [vmRound(ms[0], 6), vmRound(Math.max(ms[1], 1e-6), 6)];
  });

  var scalars = Object.create(null);
  VM_CONST.SCALARS.forEach(function (k) {
    var ms = vmMeanStd(fps.map(function (fp) { return fp[k] === undefined ? 0.0 : fp[k]; }));
    scalars[k] = [vmRound(ms[0], 4), vmRound(Math.max(ms[1], 1e-6), 4)];
  });

  var histCentroid = function (key) {
    var hs = fps.map(function (fp) { return fp[key]; }), out = [], j;
    for (j = 0; j < hs[0].length; j++) {
      var s = 0;
      for (i = 0; i < hs.length; i++) s += hs[i][j];
      out.push(vmRound(s / hs.length, 4));
    }
    return out;
  };

  var opener = Object.create(null);
  VM_CONST.OPENER_CLASSES.forEach(function (k) {
    var ms = vmMeanStd(fps.map(function (fp) { return (fp.opener_dist || {})[k] || 0.0; }));
    opener[k] = [vmRound(ms[0], 4), vmRound(Math.max(ms[1], 1e-4), 4)];
  });

  var punct = Object.create(null);
  VM_CONST.PUNCTS.forEach(function (p) {
    var ms = vmMeanStd(fps.map(function (fp) { return fp.punct_per_sentence[p] || 0.0; }));
    punct[p] = [vmRound(ms[0], 4), vmRound(Math.max(ms[1], 1e-6), 4)];
  });

  var df = Object.create(null), docTerms = [];
  var charProfiles = [], bigramProfiles = [], fwbiProfiles = [];
  texts.forEach(function (text) {
    var terms = vmContentTerms(text);
    docTerms.push(terms);
    terms.forEach(function (_c, t) { df[t] = (df[t] || 0) + 1; });
    charProfiles.push(vmCharNgramProfile(text));
    bigramProfiles.push(vmWordBigramProfile(text));
    fwbiProfiles.push(vmFunctionWordBigramProfile(text));
  });
  var nTexts = Math.max(texts.length, 1), nDocs = Math.max(docTerms.length, 1);

  var centroid = new Map();
  docTerms.forEach(function (terms) {
    var vec = vmTfidfVector(terms, df, nDocs);
    for (var k in vec) centroid.set(k, (centroid.get(k) || 0) + vec[k] / nDocs);
  });
  var centEntries = Array.from(centroid.entries());
  centEntries.sort(function (a, b) { return b[1] - a[1]; });
  var tfidfCentroid = Object.create(null);
  centEntries.slice(0, 400).forEach(function (e) { tfidfCentroid[e[0]] = vmRound(e[1], 6); });

  return {
    doc_count: texts.length,
    function_words: fw,
    scalars: scalars,
    sent_len_hist: histCentroid('sent_len_hist'),
    para_len_hist: histCentroid('para_len_hist'),
    opener: opener,
    punct: punct,
    df: df,
    n_docs: nDocs,
    tfidf_centroid: tfidfCentroid,
    char_ngrams: vmAccumulate(charProfiles, nTexts, 400, 6),
    word_bigrams: vmAccumulate(bigramProfiles, nTexts, 300, 6),
    fw_bigrams: vmAccumulate(fwbiProfiles, nTexts, 200, 6)
  };
}

/* Mean z-similarity over a group of scalar features, exp(-|z|) each.
   The variance floor matters: with a handful of reference documents an unlucky feature
   can have near-zero measured spread, which would turn a trivial difference into an
   infinite z. */
function vmScalarSimilarity(fp, baseline, keys) {
  var sims = [];
  keys.forEach(function (k) {
    var stat = (baseline.scalars || {})[k];
    if (!stat) return;
    var m = stat[0], sd = stat[1], f = fp[k] === undefined ? 0.0 : fp[k];
    sims.push(Math.exp(-Math.abs(f - m) / Math.max(sd, Math.abs(m) * 0.25 + 1e-6)));
  });
  return sims.length ? sims.reduce(function (a, b) { return a + b; }, 0) / sims.length : 0.0;
}

/* L1 histogram similarity, 1 = identical distribution. */
function vmHistSimilarity(a, b) {
  if (!a || !b || !a.length || !b.length) return 0.0;
  var s = 0, n = Math.min(a.length, b.length), i;
  for (i = 0; i < n; i++) s += Math.abs(a[i] - b[i]);
  return Math.max(0.0, 1 - s / 2);
}

/* baseline.score_text — every component is a similarity in [0,1] over ONE family of
   habits, so the bench can ablate them independently and the weights can be fitted
   rather than guessed. */
function vmScoreText(text, baseline) {
  var fp = vmFingerprint(text), i;

  /* delta: Burrows' Delta on function-word z-scores. The variance floor prevents
     blow-ups on small or homogeneous corpora. */
  var zs = [];
  for (var w in baseline.function_words) {
    var st = baseline.function_words[w], m = st[0], sd = st[1];
    var f = fp.function_word_freq[w] || 0.0;
    zs.push(Math.abs(f - m) / Math.max(sd, 0.15 * m + 5e-4));
  }
  var delta = zs.length ? zs.reduce(function (a, b) { return a + b; }, 0) / zs.length : 99.0;
  var deltaSim = Math.exp(-delta / 1.5);     // 0..1, ~0.5 at delta ~ 1

  /* ngram: char 3-gram + word bigram cosine against the register centroids */
  var cn = vmCosine(vmCharNgramProfile(text), baseline.char_ngrams || {});
  var wb = vmCosine(vmWordBigramProfile(text), baseline.word_bigrams || {});
  var ngram = 0.6 * cn + 0.4 * wb;

  var fwbigram = vmCosine(vmFunctionWordBigramProfile(text), baseline.fw_bigrams || {});

  /* opener: how sentences are started, as a class distribution */
  var bOpen = baseline.opener || {}, opener = 0.0;
  if (Object.keys(bOpen).length) {
    var osims = [];
    VM_CONST.OPENER_CLASSES.forEach(function (k) {
      var st2 = bOpen[k] || [0.0, 1e-4];
      var v = (fp.opener_dist || {})[k] || 0.0;
      osims.push(Math.exp(-Math.abs(v - st2[0]) / Math.max(st2[1], 0.03)));
    });
    opener = osims.reduce(function (a, b) { return a + b; }, 0) / osims.length;
  }

  var syntax = vmScalarSimilarity(fp, baseline, VM_CONST.SYNTAX_SCALARS);
  var richness = vmScalarSimilarity(fp, baseline, VM_CONST.RICHNESS_SCALARS);
  var structure = 0.5 * vmHistSimilarity(fp.para_len_hist, baseline.para_len_hist || [])
                + 0.5 * vmScalarSimilarity(fp, baseline, VM_CONST.STRUCTURE_SCALARS);
  var rhythm = vmHistSimilarity(fp.sent_len_hist, baseline.sent_len_hist || []);

  /* punct: per-sentence rates plus the scale-free ratios between marks */
  var psims = [];
  for (var p in (baseline.punct || {})) {
    var st3 = baseline.punct[p];
    var fv = fp.punct_per_sentence[p] || 0.0;
    psims.push(Math.exp(-Math.abs(fv - st3[0]) / Math.max(st3[1], 0.05)));
  }
  var rateSim = psims.length ? psims.reduce(function (a, b) { return a + b; }, 0) / psims.length : 0.0;
  var punct = 0.5 * rateSim + 0.5 * vmScalarSimilarity(fp, baseline, VM_CONST.PUNCT_RATIO_SCALARS);

  /* vocab: tf-idf cosine. Topical — kept for retrieval, weighted 0 for voice. */
  var vec = vmTfidfVector(vmContentTerms(text), baseline.df || {}, baseline.n_docs || 1);
  var vocab = vmCosine(vec, baseline.tfidf_centroid || {});

  var comps = { delta: deltaSim, ngram: ngram, fwbigram: fwbigram, opener: opener,
                syntax: syntax, structure: structure, rhythm: rhythm,
                richness: richness, punct: punct, vocab: vocab };
  var composite = 0;
  VM_CONST.COMPONENTS.forEach(function (k) { composite += (VM_CONST.WEIGHTS[k] || 0.0) * comps[k]; });
  composite *= 100;

  var rounded = Object.create(null);
  VM_CONST.COMPONENTS.forEach(function (k) { rounded[k] = vmRound(comps[k], 3); });
  return {
    fingerprint: fp,
    burrows_delta: vmRound(delta, 3),
    components: rounded,
    composite: vmRound(composite, 1),
    reliable: fp.words >= 150
  };
}

/* ================================================================================
   PAGE-ONLY, NO PYTHON COUNTERPART.

   Everything above this line is a port and is held to tests/test_pages_parity.py.
   Below it is one convenience the browser needs and the library does not: building a
   baseline live from text a reader pasted, with a self-calibration band.

   Python's nearest equivalent, `baseline.calibration_from_texts`, answers a different
   question — it buckets by span length so a paragraph is judged against a band measured
   on paragraphs. That matters to `revoice run`, which scores spans of wildly different
   sizes. The page scores one pasted document against another, so a single band is the
   honest shape, and pretending otherwise would mean shipping calibration machinery the
   page cannot use.

   The parity test knows this function is unpaired and does not look for a Python twin.
   Anything ADDED above the line without a counterpart will fail that test.
   ================================================================================ */

var VM_LOO_MAX = 8;   // cap the O(n^2) leave-one-out passes; 8 is plenty for a mean±sd

function vmTextWindows(text, target, minLen) {
  target = target || 1200; minLen = minLen || 300;
  var paras = text.split(/\n\s*\n/).filter(function (p) { return p.trim(); });
  var out = [], cur = [], size = 0;
  paras.forEach(function (p) {
    cur.push(p); size += p.length;
    if (size >= target) { out.push(cur.join('\n\n')); cur = []; size = 0; }
  });
  if (cur.length) out.push(cur.join('\n\n'));
  return out.filter(function (w) { return w.length > minLen; });
}

function vmBuildLiveBaseline(text) {
  var wins = vmTextWindows(text);
  if (wins.length < 2) wins = [text];
  var base = vmBaselineFromTexts(wins);
  base.windows = wins.length;

  /* Self-calibration, LEAVE-ONE-OUT. Scoring a window against a baseline it helped
     build is contaminated — the window pulls the mean toward itself, so the band comes
     out too tight and too high, and every candidate then looks worse than it is. Hold
     the window out, rebuild, score it. */
  var step = Math.max(1, Math.floor(wins.length / VM_LOO_MAX));
  var selfs = [], i, j;
  for (i = 0; i < wins.length && selfs.length < VM_LOO_MAX; i += step) {
    var rest = [];
    for (j = 0; j < wins.length; j++) if (j !== i) rest.push(wins[j]);
    if (rest.length < 2) continue;
    selfs.push(vmScoreText(wins[i], vmBaselineFromTexts(rest)).composite);
  }
  base.looSamples = selfs.length;
  if (!selfs.length) {                      // 1-2 windows: nothing to hold out
    selfs = wins.map(function (w) { return vmScoreText(w, base).composite; });
    base.contaminated = true;               // the caller is expected to warn
  }
  var ms = vmMeanStd(selfs);
  base.self = [ms[0], Math.max(ms[1], 1.0)];
  return base;
}

/* The page's headline number: distance from the reference's own variation band, in
   standard deviations. 0 means "as typical of the reference as its own passages are";
   negative means further away. Unlike a raw ratio it does not saturate. */
function vmScoreAgainstLive(text, base) {
  var r = vmScoreText(text, base);
  r.z = base.self ? (r.composite - base.self[0]) / Math.max(base.self[1], 1.0) : 0;
  r.rel = base.self ? Math.min(100 * r.composite / base.self[0], 115) : r.composite;
  return r;
}

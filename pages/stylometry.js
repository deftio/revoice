/* Shared in-browser stylometry — JS port of revoice.core.stylometry (demo subset).
   Used by demo.html (fixed corpus baselines) and compare.html (baseline built
   live from a reference text). Keep score() in sync with scripts/export_demo_baselines.py. */

var FW = ("the of and a to in is that it for on with as at by this but not are from or an be have has had " +
"was were will would could should so if then than which who what when where how all any both each " +
"few more most other some such no nor only own same too very can just don now about into over after").split(" ");
var BINS = [0,5,10,15,20,25,30,40,60,10000];

function fingerprint(text){
  var words = (text.toLowerCase().match(/[a-z']+/g)) || [];
  var sents = text.split(/(?<=[.!?])\s+|\n{2,}/).filter(function(s){return s.trim();});
  var n = Math.max(words.length,1), ns = Math.max(sents.length,1);
  var counts = {}; words.forEach(function(w){ counts[w]=(counts[w]||0)+1; });
  var fw = {}; FW.forEach(function(w){ fw[w]=(counts[w]||0)/n; });
  var lens = sents.map(function(s){ return ((s.match(/[a-z']+/gi))||[]).length; });
  var hist = BINS.slice(0,-1).map(function(){return 0;});
  lens.forEach(function(L){ for(var i=0;i<BINS.length-1;i++) if(L>=BINS[i]&&L<BINS[i+1]){hist[i]++;break;} });
  var th = Math.max(lens.length,1); hist = hist.map(function(c){return c/th;});
  var punct = {}; ",;:—–()!?\"'".split("").forEach(function(p){
    punct[p] = (text.split(p).length-1)/ns; });
  var s = text.toLowerCase().replace(/\s+/g,' ');
  var grams = {}; for(var i=0;i<s.length-2;i++){ var g=s.substr(i,3); grams[g]=(grams[g]||0)+1; }
  var tot = Math.max(s.length-2,1); var ng={};
  Object.keys(grams).sort(function(a,b){return grams[b]-grams[a];}).slice(0,300)
    .forEach(function(g){ ng[g]=grams[g]/tot; });
  var bg = {}; var nb = Math.max(words.length-1,1);
  for(var j=0;j<words.length-1;j++){ var b2=words[j]+" "+words[j+1]; bg[b2]=(bg[b2]||0)+1; }
  var big = {};
  Object.keys(bg).sort(function(a,b){return bg[b]-bg[a];}).slice(0,200)
    .forEach(function(b2){ big[b2]=bg[b2]/nb; });
  return { words:n, fw:fw, hist:hist, punct:punct, ngrams:ng, bigrams:big };
}

function cosine(a,b){ var d=0,na=0,nb=0,k;
  for(k in a){ na+=a[k]*a[k]; if(b[k])d+=a[k]*b[k]; } for(k in b){ nb+=b[k]*b[k]; }
  return (na&&nb)? d/Math.sqrt(na*nb) : 0; }

function score(fp, base){
  var zs=[], w, m, sd;
  for(w in base.function_words){ m=base.function_words[w][0]; sd=base.function_words[w][1];
    zs.push(Math.abs((fp.fw[w]||0)-m)/Math.max(sd, 0.15*m+5e-4)); }
  var delta = zs.reduce(function(a,b){return a+b;},0)/zs.length;
  var deltaSim = Math.exp(-delta/1.5);
  var l1=0; base.sent_len_hist.forEach(function(v,i){ l1+=Math.abs((fp.hist[i]||0)-v); });
  var rhythm = 1-l1/2;
  var ngram = cosine(fp.ngrams, base.char_ngrams);
  if (base.word_bigrams && fp.bigrams)   // bigram habits are more author-specific than char 3-grams
    ngram = 0.5*ngram + 0.5*cosine(fp.bigrams, base.word_bigrams);
  var ps=[], p; for(p in base.punct){ m=base.punct[p][0]; sd=base.punct[p][1];
    ps.push(Math.exp(-Math.abs((fp.punct[p]||0)-m)/Math.max(sd,0.05))); }
  var punct = ps.reduce(function(a,b){return a+b;},0)/ps.length;
  var composite = 100*(0.3*deltaSim + 0.3*ngram + 0.2*rhythm + 0.2*punct);
  var rel = base.self ? Math.min(100*composite/base.self[0], 115) : composite;
  return { composite: composite, rel: rel, delta: delta,
           parts:{delta:deltaSim, ngram:ngram, rhythm:rhythm, punct:punct} };
}

/* ---- live baseline building (compare.html): the reference text becomes the
   corpus, in miniature — windowed, aggregated, self-calibrated. ---- */

function textWindows(text, target, minLen){
  target = target || 1200; minLen = minLen || 300;
  var paras = text.split(/\n\s*\n/).filter(function(p){return p.trim();});
  var out=[], cur=[], size=0;
  paras.forEach(function(p){
    cur.push(p); size += p.length;
    if(size >= target){ out.push(cur.join("\n\n")); cur=[]; size=0; }
  });
  if(cur.length) out.push(cur.join("\n\n"));
  var ws = out.map(function(w){return w.trim();}).filter(function(w){return w.length >= minLen;});
  return ws.length ? ws : [text.trim()];
}

function meanStd(xs){
  var m = xs.reduce(function(a,b){return a+b;},0)/xs.length;
  var v = xs.reduce(function(a,x){return a+(x-m)*(x-m);},0)/xs.length;
  return [m, Math.sqrt(v)];
}

function buildBaseline(text){
  var wins = textWindows(text);
  var fps = wins.map(fingerprint);
  var base = { function_words:{}, sent_len_hist:[], punct:{}, char_ngrams:{}, windows:wins.length };
  FW.forEach(function(w){
    var ms = meanStd(fps.map(function(fp){return fp.fw[w]||0;}));
    base.function_words[w] = [ms[0], Math.max(ms[1], 1e-6)];
  });
  for(var i=0;i<BINS.length-1;i++){
    base.sent_len_hist.push(fps.reduce(function(a,fp){return a+(fp.hist[i]||0);},0)/fps.length);
  }
  ",;:—–()!?\"'".split("").forEach(function(p){
    var ms = meanStd(fps.map(function(fp){return fp.punct[p]||0;}));
    base.punct[p] = [ms[0], Math.max(ms[1], 1e-6)];
  });
  var cent = {};
  fps.forEach(function(fp){ var k; for(k in fp.ngrams){ cent[k]=(cent[k]||0)+fp.ngrams[k]/fps.length; } });
  var top = Object.keys(cent).sort(function(a,b){return cent[b]-cent[a];}).slice(0,400);
  top.forEach(function(k){ base.char_ngrams[k]=cent[k]; });
  var bcent = {};
  fps.forEach(function(fp){ var k; for(k in fp.bigrams){ bcent[k]=(bcent[k]||0)+fp.bigrams[k]/fps.length; } });
  base.word_bigrams = {};
  Object.keys(bcent).sort(function(a,b){return bcent[b]-bcent[a];}).slice(0,300)
    .forEach(function(k){ base.word_bigrams[k]=bcent[k]; });
  // self-calibration: each window scored against the baseline it helped build
  var selfs = wins.map(function(w){ return score(fingerprint(w), base).composite; });
  var ms = meanStd(selfs);
  base.self = [ms[0], Math.max(ms[1], 1.0)];
  return base;
}

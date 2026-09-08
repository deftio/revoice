"""Build the REGISTER corpus: modern functional prose, labelled by document type.

Why this is separate from the authorship corpus
-----------------------------------------------
`fetch_bench_corpus.py` builds an *authorship* benchmark, which needs a reliable
single author per document. The document types revoice's users actually work with —
web copy, scientific articles, regulatory notices, technical reports, press releases —
are institutional or multi-author. They cannot be authorship positives without lying
about who wrote them.

They are exactly right for the other half of the problem. revoice's stated job is
"register transfer within one author", and until now every register measurement came
from 19th-century books. This corpus supplies the modern functional registers, labelled
by document type rather than author, and it is used for:

  * the voice-space dimensions (`revoice.voicemetric.space`) — what the axes look like
    across real document types, and how far apart the registers actually sit
  * register attribution benchmarking
  * a background distribution for calibration

Sources, all openly licensed. Provenance and licence are recorded per document in
`manifest.json` so the corpus is auditable rather than merely convenient:

  encyclopedic       Wikipedia REST API                CC BY-SA
  scientific_article Europe PMC open-access subset     CC BY (filtered)
  regulatory         US Federal Register API           public domain (17 USC 105)
  technical_report   NASA NTRS API                     public domain (17 USC 105)
  press_release      NASA news releases                public domain (17 USC 105)

On "marketing brief": there is no public-domain corpus of modern marketing copy, and
inventing one would be worse than not having it. Government press releases are the
closest honest analogue — institutional promotional prose written to persuade a general
audience — and they are labelled as what they are.

    python scripts/fetch_register_corpus.py
    python scripts/fetch_register_corpus.py --docs 40 --register encyclopedic
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "bench-corpus-registers"
CACHE = OUT / ".cache"

UA = {"User-Agent": "revoice-register-corpus/1.0 (research; +https://github.com/deftio/revoice)"}

DOCS_PER_REGISTER = 30
MAX_CHARS = 12000
# Per-register length floor. One global minimum silently emptied `technical_report`:
# NASA abstracts run 400-1500 characters, so an 1800-char floor discarded almost all of
# them and the register quietly shrank to three documents. A register that is present
# but short is honest; a register that vanished because of a constant is a bug.
MIN_CHARS = 1800
MIN_CHARS_BY_REGISTER = {"technical_report": 700, "press_release": 1200}

# Encyclopedic prose. Topics are spread deliberately across domains so the register's
# own spread is measured, not one subject area's vocabulary.
WIKI_TITLES = [
    "Antenna (radio)", "Photosynthesis", "Byzantine Empire", "Monetary policy",
    "Reinforced concrete", "Immune system", "Jazz", "Plate tectonics",
    "Machine learning", "Coffee", "Suspension bridge", "Vaccine",
    "Impressionism", "Supply chain", "Volcano", "Antibiotic",
    "Semiconductor", "Baroque music", "Ocean current", "Neuron",
    "Wind power", "Roman law", "Diesel engine", "Coral reef",
    "Cartography", "Inflation", "Sleep", "Bridge (graph theory)",
    "Lighthouse", "Fermentation", "Radar", "Glacier",
    "Opera", "Public health", "Steam locomotive", "Soil",
]


def _get(url: str, retries: int = 3, timeout: int = 40) -> bytes | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == retries - 1:
                print(f"      giving up on {url[:70]}: {e}", file=sys.stderr)
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def _cached(name: str, url: str) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]
    if f.is_file():
        return f.read_text(errors="replace")
    raw = _get(url)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    f.write_text(text)
    return text


def clean(text: str) -> str:
    """Strip markup, reference clutter and boilerplate; keep paragraphs."""
    text = re.sub(r"<[^>]+>", " ", text)                      # html/jats tags
    text = re.sub(r"&[a-z]+;|&#\d+;", " ", text)
    text = re.sub(r"\[\d+(?:[,-]\s*\d+)*\]", "", text)        # [1], [2,3]
    text = re.sub(r"^\s*(==+.*?==+)\s*$", "", text, flags=re.M)  # wiki headings
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # keep only paragraphs that read as prose: some length, and ending in a stop
    paras = [p.strip() for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if len(p) > 180 and p.rstrip().endswith((".", "?", "!", '"'))]
    return "\n\n".join(paras).strip()


def trim(text: str, minimum: int | None = None) -> str | None:
    if len(text) < (minimum if minimum is not None else MIN_CHARS):
        return None
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    return cut[: cut.rfind("\n\n")] or cut


# ---------- per-source fetchers: each yields (slug, text, provenance) ----------


def fetch_encyclopedic(n: int):
    for title in WIKI_TITLES[: n * 2]:
        url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=extracts"
               "&explaintext=1&redirects=1&titles=" + urllib.parse.quote(title))
        body = _cached(f"wiki-{title}.json", url)
        if not body:
            continue
        try:
            pages = json.loads(body)["query"]["pages"]
        except (KeyError, json.JSONDecodeError):
            continue
        extract = next(iter(pages.values())).get("extract", "")
        text = trim(clean(extract))
        if text:
            yield re.sub(r"\W+", "-", title.lower()).strip("-"), text, {
                "source": "Wikipedia", "title": title, "license": "CC BY-SA 4.0"}


def fetch_scientific_article(n: int):
    """Europe PMC open-access subset, CC BY only — the least restrictive licence there."""
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
           "query=" + urllib.parse.quote('OPEN_ACCESS:Y AND LICENSE:"cc by" AND HAS_FT:Y') +
           f"&format=json&pageSize={n * 3}&resultType=core")
    body = _cached(f"pmc-search-{n}.json", url)
    if not body:
        return
    try:
        results = json.loads(body).get("resultList", {}).get("result", [])
    except json.JSONDecodeError:
        return
    for r in results:
        pmcid, lic = r.get("pmcid"), (r.get("license") or "").lower()
        if not pmcid or lic != "cc by":
            continue  # be strict: only the fully permissive licence
        full = _cached(f"pmc-{pmcid}.xml",
                       f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
        if not full:
            continue
        body_xml = full.split("<body>", 1)[-1].split("</body>", 1)[0]
        text = trim(clean(body_xml))
        if text:
            yield pmcid.lower(), text, {"source": "Europe PMC", "id": pmcid,
                                        "title": (r.get("title") or "")[:120], "license": "CC BY"}


def fetch_regulatory(n: int):
    """US Federal Register — regulations and notices. Public domain (17 USC 105)."""
    q = urllib.parse.urlencode({"per_page": n * 2, "order": "newest"}) + \
        "&fields[]=title&fields[]=raw_text_url&fields[]=document_number&conditions[type][]=RULE"
    body = _cached(f"fedreg-{n}.json", f"https://www.federalregister.gov/api/v1/documents.json?{q}")
    if not body:
        return
    try:
        results = json.loads(body).get("results", [])
    except json.JSONDecodeError:
        return
    for r in results:
        raw_url, num = r.get("raw_text_url"), r.get("document_number")
        if not raw_url or not num:
            continue
        raw = _cached(f"fedreg-{num}.txt", raw_url)
        if not raw:
            continue
        text = trim(clean(raw))
        if text:
            yield str(num), text, {"source": "US Federal Register", "id": num,
                                   "title": (r.get("title") or "")[:120],
                                   "license": "public domain (17 USC 105)"}


def fetch_technical_report(n: int):
    """NASA technical reports. Public domain (17 USC 105)."""
    for topic in ("propulsion", "aerodynamics", "thermal control", "guidance navigation",
                  "materials", "structures", "avionics", "life support", "combustion",
                  "spacecraft power", "telemetry", "heat transfer", "flight test",
                  "orbital mechanics", "composite materials", "wind tunnel"):
        body = _cached(f"ntrs-{topic}.json",
                       "https://ntrs.nasa.gov/api/citations/search?q="
                       + urllib.parse.quote(topic) + "&size=25")
        if not body:
            continue
        try:
            results = json.loads(body).get("results", [])
        except json.JSONDecodeError:
            continue
        for r in results:
            abstract = r.get("abstract") or ""
            text = trim(clean(abstract), MIN_CHARS_BY_REGISTER["technical_report"])
            if text:
                yield f"{topic.replace(' ', '-')}-{r.get('id')}", text, {
                    "source": "NASA NTRS", "id": str(r.get("id")),
                    "title": (r.get("title") or "")[:120],
                    "license": "public domain (17 USC 105)"}


def fetch_press_release(n: int):
    """NASA news releases: institutional promotional prose. Public domain.

    The closest honest analogue to a marketing brief that exists in the public domain —
    written to persuade a general audience, by an organisation, about its own work.
    """
    body = _cached("nasa-news.json",
                   "https://www.nasa.gov/wp-json/wp/v2/posts?per_page=60&_fields=slug,title,content")
    if not body:
        return
    try:
        posts = json.loads(body)
    except json.JSONDecodeError:
        return
    for p in posts:
        html = (p.get("content") or {}).get("rendered", "")
        text = trim(clean(html.replace("</p>", "</p>\n\n")),
                    MIN_CHARS_BY_REGISTER["press_release"])
        if text:
            yield str(p.get("slug", ""))[:40], text, {
                "source": "NASA news", "slug": p.get("slug"),
                "title": ((p.get("title") or {}).get("rendered") or "")[:120],
                "license": "public domain (17 USC 105)"}


REGISTERS = {
    "encyclopedic": fetch_encyclopedic,
    "scientific_article": fetch_scientific_article,
    "regulatory": fetch_regulatory,
    "technical_report": fetch_technical_report,
    "press_release": fetch_press_release,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", type=int, default=DOCS_PER_REGISTER, help="documents per register")
    ap.add_argument("--register", choices=sorted(REGISTERS), help="fetch only this one")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".gitignore").write_text("# fetched register corpus — rebuildable, not ours to vendor\n*\n")

    targets = {args.register: REGISTERS[args.register]} if args.register else REGISTERS
    manifest: dict = {}
    if (OUT / "manifest.json").is_file():
        manifest = json.loads((OUT / "manifest.json").read_text())

    total = 0
    for register, fetch in targets.items():
        dest = OUT / register / "training-data"
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for slug, text, prov in fetch(args.docs):
            if written >= args.docs:
                break
            written += 1
            name = f"{register}-{slug or written}-{written}.md"
            (dest / name).write_text(text)
            manifest[f"{register}/{name}"] = prov
        print(f"  {register:<20} {written:>3} documents")
        total += written

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"\n{total} documents under {OUT}")
    print(f"provenance + licence for every document: {OUT / 'manifest.json'}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())

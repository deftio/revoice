"""Build the topic-controlled evaluation corpus for `revoice bench`.

Why this exists
---------------
The bundled example packs (Twain, Darwin) are confounded four ways — author, genre,
topic AND era all differ at once — so a measure can post a good AUC on them by
detecting "humour vs natural history" and never touching authorship. Fitting weights
on that contrast would bake the confound into the metric.

This script assembles the corpus docs/metrics.md 4.1 asks for, entirely from public
domain Project Gutenberg texts:

  * positives      several distinct works per author, on different subjects, so
                   work-level leave-one-out actually removes the query's topic
  * hard negatives different authors writing in the SAME era and genre. The test that
                   matters is Twain vs Bret Harte, not Twain vs Darwin.

As built: ~1,600 samples, 70 authors, 11 genres. Standard authorship corpora
(CCAT50, IMDb62, Blogs50) are modern, short-form and topically noisy, and none of
them contain instructional or product literature — the register revoice's users
actually write in — which is why the `technical` group is here.

Output is a voice-pack-shaped tree that `revoice bench` reads directly:

    bench-corpus/<author>/training-data/<register>-<work>-<n>.md

It is written to a gitignored directory rather than committed: the texts are large,
freely re-fetchable, and derived data does not belong in the repo (same reasoning as
voice packs). Re-running is cheap — downloads are cached under bench-corpus/.cache/.

    python scripts/fetch_bench_corpus.py           # build it
    revoice bench bench-corpus                     # measure against it
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "bench-corpus"
CACHE = OUT / ".cache"

# One catalogue download instead of one API call per author. Gutendex is convenient
# but flaky — it went fully unreachable mid-build — and 66 authors is 66 chances to
# fail. The catalogue is a single static CSV (~20 MB, ~79k rows) served from the same
# host as the texts, so author lookup becomes an offline join and the whole build
# becomes reproducible.
CATALOG = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
MIRROR = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
UA = {"User-Agent": "revoice-bench-corpus/1.0 (research; +https://github.com/deftio/revoice)"}

# Genre groups. Within a group the authors share era, language and broad genre, so
# telling them apart is authorship and nothing else — that is the contrast that matters
# (Twain vs Bret Harte, not Twain vs Darwin). Across groups you get the easy
# cross-genre contrast for comparison, plus the background pool that likelihood-ratio
# calibration and General-Imposters verification both need.
#
# Every author writes in ENGLISH. Translations are excluded on purpose: in a translated
# text the surface features this measures belong to the translator, so a "Nietzsche"
# or "Tolstoy" label would be a lie about who produced the prose.
#
# `technical` is the practical/product literature group — manuals, engineering,
# medicine, household and cookery instruction. Instructional prose has its own
# conventions and is badly under-represented in literary stylometry corpora, which is
# precisely why revoice needs it: it is the register most of its users actually write in.
GROUPS = {
    "humor": [
        ("twain", "Mark Twain"),
        ("harte", "Bret Harte"),
        ("ade", "George Ade"),
        ("dunne", "Finley Peter Dunne"),
        ("nye", "Bill Nye"),
        ("jerome", "Jerome K. Jerome"),
        ("leacock", "Stephen Leacock"),
    ],
    "science": [
        ("darwin", "Charles Darwin"),
        ("wallace", "Alfred Russel Wallace"),
        ("huxley", "Thomas Henry Huxley"),
        ("gosse", "Philip Henry Gosse"),
        ("tyndall", "John Tyndall"),
        ("lyell", "Charles Lyell"),
    ],
    # Practical / product literature: manuals, trade primers, field guides, cookery.
    # Instructional prose has its own conventions and is almost absent from literary
    # stylometry corpora — which is exactly the register revoice's users write in.
    "technical": [
        ("morgan_ap", "Alfred Powell Morgan"),      # maker/electronics construction
        ("hawkins_n", "Nehemiah Hawkins"),          # electrical engineering guides
        ("hamilton_fw", "Frederick William Hamilton"),  # printing-trade primers
        ("wheatley", "Henry Benjamin Wheatley"),    # library/indexing manuals
        ("harding_ar", "Arthur Robert Harding"),    # trapping and fur-farming manuals
        ("parloa", "Maria Parloa"),                 # cookery instruction
        ("leslie_e", "Eliza Leslie"),               # cookery + etiquette manuals
        ("rorer", "Sarah Tyson Rorer"),             # cookery instruction
        ("osler", "William Osler"),                 # clinical medicine
    ],
    "philosophy": [
        ("james_w", "William James"),
        ("mill", "John Stuart Mill"),
        ("russell", "Bertrand Russell"),
        ("spencer", "Herbert Spencer"),
        ("hume", "David Hume"),
        ("dewey", "John Dewey"),
    ],
    "history": [
        ("macaulay", "Thomas Babington Macaulay"),
        ("parkman", "Francis Parkman"),
        ("prescott", "William Hickling Prescott"),
        ("motley", "John Lothrop Motley"),
        ("froude", "James Anthony Froude"),
        ("freeman", "Edward Augustus Freeman"),
    ],
    "economics": [
        ("smith_a", "Adam Smith"),
        ("veblen", "Thorstein Veblen"),
        ("bagehot", "Walter Bagehot"),
        ("malthus", "Thomas Robert Malthus"),
        ("hobson", "John Atkinson Hobson"),
        ("mill_pe", "John Stuart Mill"),
    ],
    "fiction": [
        ("austen", "Jane Austen"),
        ("dickens", "Charles Dickens"),
        ("eliot_g", "George Eliot"),
        ("james_h", "Henry James"),
        ("hardy", "Thomas Hardy"),
        ("wharton", "Edith Wharton"),
    ],
    "adventure": [
        ("doyle", "Arthur Conan Doyle"),
        ("stevenson", "Robert Louis Stevenson"),
        ("wells", "H. G. Wells"),
        ("haggard", "H. Rider Haggard"),
        ("kipling", "Rudyard Kipling"),
        ("london", "Jack London"),
    ],
    "essay": [
        ("emerson", "Ralph Waldo Emerson"),
        ("chesterton", "Gilbert Keith Chesterton"),
        ("arnold", "Matthew Arnold"),
        ("hazlitt", "William Hazlitt"),
        ("carlyle", "Thomas Carlyle"),
        ("burroughs", "John Burroughs"),
    ],
    "travel": [
        ("stanley", "Henry Morton Stanley"),
        ("bird", "Isabella Bird"),
        ("burton", "Richard Francis Burton"),
        ("taylor_b", "Bayard Taylor"),
        ("davis_r", "Richard Harding Davis"),
        ("whymper", "Edward Whymper"),
    ],
    "childrens": [
        ("baum", "Lyman Frank Baum"),
        ("alcott", "Louisa May Alcott"),
        ("burnett", "Frances Hodgson Burnett"),
        ("nesbit", "Edith Nesbit"),
        ("carroll", "Lewis Carroll"),
        ("grahame", "Kenneth Grahame"),
    ],
}

# Titles that are compilations, correspondence, or books ABOUT someone else. Their
# prose is not reliably the named author's: "Life and Letters of Charles Darwin" is
# edited by Francis Darwin and opens with a family genealogy table, and Huxley's
# "Hume" is a biography. Contaminated positives depress the score for reasons that
# have nothing to do with the metric, which is worse than having fewer works.
# NB: these are PREFIXES with a trailing \w* — "\bautobiograph\b" never matches
# "Autobiography", because there is no word boundary between "autobiograph" and "y".
TITLE_BLOCKLIST = re.compile(
    r"\b(?:letters?|correspondence|life and|memoir\w*|biograph\w*|autobiograph\w*"
    r"|english men of letters|reminiscen\w*|selections? from|edited by|antholog\w*"
    r"|translat\w*|complete works|complete writings)\b", re.I)

WORKS_PER_AUTHOR = 3        # >= 2 so work-level leave-one-out has something to hold out
CHUNKS_PER_WORK = 8
MIN_CHUNK_CHARS = 2500
MAX_CHUNK_CHARS = 9000


def _get(url: str, retries: int = 4, timeout: int = 45) -> bytes | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == retries - 1:
                print(f"      giving up on {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def _cached(name: str, url: str) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / name
    if f.is_file():
        return f.read_text(errors="replace")
    raw = _get(url)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    f.write_text(text)
    return text


_CATALOG_CACHE: list[dict] = []


def load_catalog() -> list[dict]:
    """The Gutenberg catalogue as a list of rows, downloaded once and cached on disk."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE:
        return _CATALOG_CACHE
    body = _cached("pg_catalog.csv", CATALOG)
    if not body:
        return []
    _CATALOG_CACHE = [
        r for r in csv.DictReader(body.splitlines())
        if r.get("Type") == "Text" and r.get("Language") == "en"
    ]
    return _CATALOG_CACHE


def _name_matches(field: str, author: str) -> bool:
    """Catalogue names are 'Surname, Given Names, dates'. Match the SURNAME FIELD exactly.

    Substring matching anywhere in the record is not safe. Searching "John Richard
    Green" that way pulls in "Whittier, John Greenleaf" — 58 works by the wrong man,
    silently filed under one author label, which would poison every trial that author
    appears in. Anchoring the surname to the part before the first comma removes that
    whole class of collision; a given name is still required so "Henry Walter Bates"
    does not match Walter Bates.
    """
    surname_field = field.split(",")[0].strip().lower()
    parts = author.lower().replace(".", " ").split()
    if not parts:
        return False
    surname, givens = parts[-1], parts[:-1]
    if surname_field != surname:
        return False
    if not givens:
        return True
    # Compare the first given name POSITIONALLY against the catalogue's first given
    # name. Anything looser collides: "Smith, George Adam" (the biblical scholar)
    # contains "Adam" and would be filed as Adam Smith the economist, and
    # "Bates, Walter" contains "Walter" and would be filed as Henry Walter Bates.
    # Either mistake puts one man's prose under another man's label, which is not a
    # metric problem — it is a corpus that cannot measure anything.
    given_field = field.split(",")[1] if "," in field else ""
    cat_tokens = re.findall(r"[a-z]+", given_field.lower())
    if not cat_tokens:
        return False
    ours, theirs = givens[0], cat_tokens[0]
    if len(ours) == 1 or len(theirs) == 1:   # an initial on either side
        return ours[0] == theirs[0]
    return ours == theirs


def search_author(author: str) -> list[dict]:
    """Candidate works for one author: single credited author, not a compilation."""
    out = []
    for row in load_catalog():
        authors = [a.strip() for a in row["Authors"].split(";") if a.strip()]
        if len(authors) != 1:
            continue  # co-authored, edited or compiled: prose is not reliably one hand
        if not _name_matches(authors[0], author):
            continue
        title = row["Title"].replace("\n", " ").strip()
        if TITLE_BLOCKLIST.search(title):
            continue
        out.append({"id": row["Text#"], "title": title})
    return out


PG_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG[^*]*\*\*\*", re.I)
PG_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG[^*]*\*\*\*", re.I)


def strip_boilerplate(text: str) -> str:
    m = PG_START.search(text)
    if m:
        text = text[m.end():]
    m = PG_END.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # drop transcriber notes, all-caps headings, and illustration markers
    text = re.sub(r"^\s*\[Illustration[^\]]*\]\s*$", "", text, flags=re.M)
    text = re.sub(r"^\s*(?:CHAPTER|PART|BOOK|SECTION)\b.*$", "", text, flags=re.M | re.I)
    return text.strip()


def chunk(text: str, n: int) -> list[str]:
    """Split into up to n prose chunks on paragraph boundaries, skipping front matter."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 120]
    paras = paras[3:]  # title pages, dedications, tables of contents
    if not paras:
        return []
    chunks, cur, size = [], [], 0
    for p in paras:
        cur.append(p)
        size += len(p)
        if size >= MAX_CHUNK_CHARS:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0
        if len(chunks) >= n:
            break
    if cur and len(chunks) < n:
        chunks.append("\n\n".join(cur))
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS][:n]


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:28].strip("-") or "work"


_VOLUME_RX = re.compile(
    r"\s*[,:—-]?\s*\b(?:vol(?:ume)?\.?|v\.|part|pt\.|book|no\.)\s*[ivxlc\d]+\b.*$", re.I)


def work_family(title: str) -> str:
    """Collapse 'Complete Writings, Volume 3' and '... Volume 4' to one key.

    Work-level leave-one-out holds out a work to remove the query's topic. Volumes of
    a single work share their subject completely, so counting them as separate works
    would quietly reinstate the topic leak the protocol exists to prevent.
    """
    t = _VOLUME_RX.sub("", title)
    t = re.sub(r"\s*\((?:of\s+)?\d+\)\s*$", "", t)
    return slug(t)[:22]


def build_author(key: str, author: str, register: str, works: int, verbose: bool) -> int:
    books = search_author(author)
    if not books:
        print(f"  {key:<10} no works found (gutendex unreachable or no plain text)")
        return 0
    dest = OUT / key / "training-data"
    dest.mkdir(parents=True, exist_ok=True)
    written, used = 0, 0
    seen_slugs: set[str] = set()
    seen_families: set[str] = set()
    for b in books:
        if used >= works:
            break
        family = work_family(b["title"])
        if family in seen_families:
            continue  # another volume of a work we already took
        raw = _cached(f"{b['id']}.txt", MIRROR.format(id=b["id"]))
        if not raw:
            continue
        body = strip_boilerplate(raw)
        pieces = chunk(body, CHUNKS_PER_WORK)
        if len(pieces) < 3:
            continue
        # the work slug is what work-level leave-one-out holds out, so it must be
        # distinct per work or the topic control silently stops working
        w = slug(b["title"])
        if w in seen_slugs:
            w = f"{w}-{b['id']}"
        seen_slugs.add(w)
        seen_families.add(family)
        for i, piece in enumerate(pieces, 1):
            (dest / f"{register}-{w}-{i}.md").write_text(piece)
            written += 1
        used += 1
        if verbose:
            print(f"  {key:<10} {b['title'][:44]:<46} {len(pieces)} chunks")
    print(f"  {key:<10} {used} works, {written} files")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--works", type=int, default=WORKS_PER_AUTHOR,
                    help="works per author (>=2 for work-level leave-one-out)")
    ap.add_argument("--group", choices=sorted(GROUPS) + ["all"], default="all")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    # the corpus is derived data: re-fetchable, large, and not ours to vendor
    (OUT / ".gitignore").write_text("# fetched public-domain eval corpus — rebuildable\n*\n")

    groups = GROUPS if args.group == "all" else {args.group: GROUPS[args.group]}
    total = 0
    for register, authors in groups.items():
        print(f"[{register}]")
        for key, author in authors:
            total += build_author(key, author, register, args.works, not args.quiet)
    print(f"\n{total} files under {OUT}")
    print(f"next: revoice bench {OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())

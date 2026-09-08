"""The evaluation-corpus builder's pure logic.

Nothing here touches the network. What is tested is the filtering that decides *which*
prose ends up labelled with *which* author — the part where a mistake silently poisons
every benchmark run downstream and looks like a metric failure rather than a data bug.
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fetch_bench_corpus", Path(__file__).parent.parent / "scripts" / "fetch_bench_corpus.py")
fbc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fbc)


# ---------- author matching ----------


def test_name_matches_requires_surname_field_not_substring():
    """The collision that motivated this: 'Whittier, John Greenleaf' is not John Green.

    Substring matching pulled 58 works by the wrong author under one label.
    """
    assert not fbc._name_matches("Whittier, John Greenleaf, 1807-1892", "John Richard Green")
    assert fbc._name_matches("Green, John Richard, 1837-1883", "John Richard Green")


def test_name_matches_requires_a_given_name():
    """'Henry Walter Bates' must not match Walter Bates."""
    assert not fbc._name_matches("Bates, Walter", "Henry Walter Bates")
    assert fbc._name_matches("Bates, Henry Walter, 1825-1892", "Henry Walter Bates")


def test_name_matches_handles_initials_and_punctuation():
    assert fbc._name_matches("Jerome, Jerome K., 1859-1927", "Jerome K. Jerome")
    assert fbc._name_matches("Wells, H. G. (Herbert George), 1866-1946", "H. G. Wells")


def test_name_matches_rejects_a_different_surname():
    assert not fbc._name_matches("Twain, Mark", "Bret Harte")


def test_name_matches_empty_author():
    assert not fbc._name_matches("Twain, Mark", "")


# ---------- work families ----------


def test_work_family_collapses_volumes_of_one_work():
    """Volumes share a subject completely, so counting them as separate works would
    reinstate exactly the topic leak work-level leave-one-out exists to prevent."""
    a = fbc.work_family("The Complete Writings of Charles Dudley Warner, Volume 1")
    b = fbc.work_family("The Complete Writings of Charles Dudley Warner, Volume 2")
    assert a == b


def test_work_family_handles_several_volume_spellings():
    base = fbc.work_family("Hawkins Electrical Guide")
    for variant in ("Hawkins Electrical Guide v. 01 (of 10)",
                    "Hawkins Electrical Guide Vol. 2",
                    "Hawkins Electrical Guide, Part 3",
                    "Hawkins Electrical Guide Book IV"):
        assert fbc.work_family(variant) == base, variant


def test_work_family_keeps_genuinely_different_works_apart():
    assert fbc.work_family("The Adventures of Tom Sawyer") != \
        fbc.work_family("Adventures of Huckleberry Finn")


def test_work_family_of_an_empty_title():
    assert fbc.work_family("") == "work"


# ---------- boilerplate + chunking ----------


def test_strip_boilerplate_removes_the_gutenberg_wrapper():
    raw = ("header junk\n*** START OF THE PROJECT GUTENBERG EBOOK SOMETHING ***\n"
           "Real prose here.\n\n*** END OF THE PROJECT GUTENBERG EBOOK SOMETHING ***\nlicence")
    out = fbc.strip_boilerplate(raw)
    assert out == "Real prose here."


def test_strip_boilerplate_without_markers_is_a_passthrough():
    assert fbc.strip_boilerplate("Just prose.") == "Just prose."


def test_strip_boilerplate_drops_chapter_headings_and_illustrations():
    raw = "CHAPTER IV\n\n[Illustration: a plate]\n\nThe prose survives."
    assert "CHAPTER" not in fbc.strip_boilerplate(raw)
    assert "Illustration" not in fbc.strip_boilerplate(raw)
    assert "The prose survives." in fbc.strip_boilerplate(raw)


def test_chunk_skips_front_matter_and_respects_the_cap():
    para = "A paragraph of ordinary prose, long enough to survive the length filter. " * 40
    body = "\n\n".join(para for _ in range(20))
    chunks = fbc.chunk(body, 4)
    assert len(chunks) <= 4
    assert all(len(c) >= fbc.MIN_CHUNK_CHARS for c in chunks)


def test_chunk_of_too_little_text_is_empty():
    assert fbc.chunk("short\n\nalso short", 4) == []


def test_title_blocklist_excludes_compilations_and_biographies():
    for title in ("Life and Letters of Charles Darwin", "More Letters of Charles Darwin",
                  "Hume: (English Men of Letters Series)", "Selections from Emerson",
                  "The Autobiography of Benjamin Franklin"):
        assert fbc.TITLE_BLOCKLIST.search(title), title
    for title in ("The Origin of Species", "Hawkins Electrical Guide", "Miss Parloa's New Cook Book"):
        assert not fbc.TITLE_BLOCKLIST.search(title), title


def test_slug_is_filesystem_safe_and_bounded():
    s = fbc.slug("The Luck of Roaring Camp & Other Tales: With Condensed Novels!")
    assert s and " " not in s and "&" not in s and len(s) <= 28


# ---------- roster sanity ----------


def test_every_group_has_at_least_two_authors():
    """A group with one author has no same-genre rival, so it cannot form hard negatives."""
    for genre, authors in fbc.GROUPS.items():
        assert len(authors) >= 2, genre


def test_author_keys_are_unique_across_the_whole_roster():
    keys = [k for authors in fbc.GROUPS.values() for k, _ in authors]
    assert len(keys) == len(set(keys)), "duplicate key would overwrite another author's directory"


def test_technical_group_exists_and_is_substantial():
    """Instructional prose is the register revoice's users write in, and it is absent
    from every standard authorship corpus — so it must not quietly drop out of ours."""
    assert len(fbc.GROUPS["technical"]) >= 5

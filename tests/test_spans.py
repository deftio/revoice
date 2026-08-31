from revoice.core.spans import parse, reassemble, rewritable

DOC = """# Title

A paragraph of prose here.

```c
int x = 1;  // untouchable
```

- item one
- item two

> a quote line

| a | b |
|---|---|
| 1 | 2 |
"""


def test_roundtrip_identity():
    assert reassemble(parse(DOC)) == DOC.rstrip("\n") + "" or reassemble(parse(DOC)) == DOC


def test_protected_blocks_never_rewritable():
    spans = parse(DOC)
    rw = rewritable(spans)
    kinds = {s.kind for s in rw}
    assert "protected" not in kinds
    joined = " ".join(s.text for s in rw)
    assert "int x = 1" not in joined      # code protected
    assert "| a | b |" not in joined      # table protected


def test_structure_survives_text_change():
    spans = parse(DOC)
    for s in rewritable(spans):
        s.text = "REPLACED."
    out = reassemble(spans)
    assert "```c" in out and "int x = 1;  // untouchable" in out
    assert out.count("REPLACED.") == len(rewritable(parse(DOC)))
    assert "# Title" in out
    assert "- REPLACED." in out

# Example voice: Charles Darwin

A small demonstration corpus in two registers — memoir (first-person recollection,
candid and self-deprecating) and science (careful argumentative prose, evidence
marshalled toward a thesis). Both works are in the public domain:

- *The Autobiography of Charles Darwin* (1887, ed. Francis Darwin) — Project Gutenberg #2010
- *On the Origin of Species by Means of Natural Selection* (6th ed.) — Project Gutenberg #2009

Text courtesy of [Project Gutenberg](https://www.gutenberg.org); PG boilerplate and
chapter headings removed, content unmodified. The memoir files cover the autobiography
from Darwin's opening through his reflections on his working life; the science files
cover the Introduction, Chapter I (Variation Under Domestication), and the opening of
Chapter II of the Origin.

## Try it

```bash
cp -r examples/voices/darwin data/darwin
revoice learn darwin           # needs a real classifier provider (ollama/anthropic/openrouter)
revoice status darwin
revoice stats some-draft.md --voice darwin
revoice run some-draft.md --voice darwin -r science -s 1.0   # make anything sound like Darwin
```

Note: this corpus is deliberately tiny (a demo, not a serious voice). Real voice packs
want dozens-to-hundreds of documents. It exists so you can exercise the full pipeline
before committing your own writing.

# Example voice: Mark Twain

A demonstration corpus (20 files) in two registers — essay (rhetorical, first-person argument)
and fiction (comic narrative). All works are in the public domain:

- *On the Decay of the Art of Lying* (1882) — Project Gutenberg #2572
- *Extracts from Adam's Diary* (1893) — Project Gutenberg #1892
- *A Dog's Tale* (1903) — Project Gutenberg #3174

See also the second example voice, a scientist: `examples/voices/darwin/` (22 files:
*Autobiography* memoir register + *On the Origin of Species* scientific register).

Text courtesy of [Project Gutenberg](https://www.gutenberg.org); PG boilerplate removed,
content unmodified.

## Try it

```bash
cp -r examples/voices/twain data/twain
revoice learn twain            # needs a real classifier provider (ollama/anthropic/openrouter)
revoice status twain
revoice stats some-draft.md --voice twain
revoice run some-draft.md --voice twain -r essay -s 1.0   # make anything sound like Twain
```

Note: this corpus is deliberately tiny (a demo, not a serious voice). Real voice packs
want dozens-to-hundreds of documents. It exists so you can exercise the full pipeline
before committing your own writing.

# Algorithm and engineering decisions

## Problem definition

Detect local reused wording, not whole-document topic similarity. Each result is an evidence-bearing pair of original text spans. We distinguish normalized exact matches, near matches with word edits, and semantic suggestions (a separately reviewed offline extension).

Example:

```
A: the —     king entered the city before sunrise
B: the young king entered the city before sunrise
```

The shared words anchor the region; local alignment identifies the inserted word and passage boundaries. The same technique is used in text-reuse research: [Passim](https://github.com/dasmiq/passim) indexes character n-grams then aligns candidate regions. This implementation uses word seeds and a small in-process engine instead of Spark/Java. [BLAST text-reuse research](https://aclanthology.org/W17-0510/) is another example of seed-and-extend detection.

## Tokenization and coordinate contract

`Token(value, start, end)` stores a normalized word and its original code-point range. Unicode letters/digits and interior straight/curly apostrophes are accepted. NFKC then casefold handles case and compatibility variants. Punctuation is excluded from matching but preserved inside returned original spans. No stopwords are removed: doing so would erase sequence evidence and make source alignment harder.

This is a word-oriented tokenizer, suitable for this English corpus. It does not implement language-specific segmentation for languages without word spaces, or canonical combining-mark handling for all scripts. The browser uses `Array.from(text)` to preserve the code-point convention even for supplementary characters. Offsets are not UTF-8 byte positions or JavaScript UTF-16 indices.

## Candidate generation

Build `word triple → list of token positions` for both documents. Enumerate positions for shared triples; skip a triple if its occurrence count exceeds 60 in either document. This cap limits common-phrase explosions, at the cost of recall. It is not a guarantee to detect every exact passage.

Exact detection extends each indexed seed left and right while normalized words match. Already extended runs on the same positional diagonal are skipped.

Near-match seeds chain if they preserve order, lie within 40 tokens of the last seed in each document, and displacement differs by at most 12 tokens. Diagonal buckets of width 8 make candidate lookup practical. Chains split before their span exceeds the candidate bound. Add 32 words of context on each side. Candidate windows are deduplicated before alignment.

The diagonal bucket/last-eight-chain lookup is a heuristic, not an optimal global chain finder. Reordering and long insertions can split or lose evidence. A passage without an allowed ordered triple never enters this path. The additional bounded skip route is described below.

## Additional bounded skip retrieval

Version lexical-1.1.0 also indexes triples with zero or one intervening word per step. Plain and gapped patterns can share a key. Full anchor spans retain skipped words, which are included in subsequent alignment and scoring. This route is separate from contiguous exact extension and the established window chains. Existing contiguous result ranges take priority during deduplication. See SKIP_SEEDS.md for the implementation, before/after measurements, and limitations.

## Local alignment

`Bio.Align.PairwiseAligner` receives integer arrays of word identities:

- matched word: +2
- substituted word: −1
- gap opening: −2
- gap extension: −0.6

Affine gap penalties model a run of inserted words more gently than many separate insertions. The aligner chooses a local region instead of forcing unrelated openings/endings to align. Its coordinates map token indices to original character ranges.

We retrieve one best alignment per candidate window; multiple candidate windows and an independent exact detector cover different local regions. This is not exhaustive enumeration of every local alignment. Multiple nearby competing near matches can still be missed. Windows may limit long near matches; exact runs can extend beyond this bound.

Implementation reference: [Biopython alignment documentation](https://biopython.org/docs/latest/Tutorial/chapter_pairwise.html).

## Scoring and reporting

The alignment score finds a region; it is **not** the displayed percentage. On the discovered spans, uniform word Levenshtein distance computes:

`similarity = 1 − edits / max(words_A, words_B)`

Edits are substitutions, insertions, and deletions. RapidFuzz computes distance and edit opcodes. These opcodes provide original-span difference highlighting. [RapidFuzz documentation](https://rapidfuzz.github.io/RapidFuzz/Usage/distance/Levenshtein.html).

Require at least 12 words for exact or 16 for near, and similarity ≥0.62. Lengths are measured in both passages, not just the shorter one. A short perfect phrase may be less interesting than a long imperfect passage; the UI exposes both score and length.

The 0.62 threshold was selected using 18 known corpus locations as a **development set**. Threshold sensitivity is included in `evaluation.json`. Those locations are not a held-out test set, and the observed coverage is not corpus recall.

## Redundant matches

Sort longer matches before shorter ones, then by score and coordinates. If a proposed result overlaps a kept result by ≥85% of the shorter range in both documents, suppress it. Both sides matter: a passage that appears twice in one text should retain two distinct matches.

Contiguous results are suppressed first; additional skip matches are then suppressed against them, preserving prior result identities. This rule yields a navigable result list but is a heuristic. It can suppress a useful shorter exact run inside a larger near match or combine a shared core with context. Underlying word diff and original spans remain visible for review.

## Complexity and scale

For a pair with N and M words, indexing is approximately O(N+M) for fixed seed length. Shared seed enumeration costs `Σ occurrences_A(seed) × occurrences_B(seed)` for retained seeds. Local dynamic programming costs O(W_A × W_B) per window, with windows bounded to about 220 tokens per side. Exact-run checks and result suppression add overhead; suppression is quadratic in the number of accepted raw candidates in this implementation.

All document pairs are considered: D(D−1)/2 pairs. The bundled three documents produce three pairs. This is appropriate for this small corpus, not a design for millions of documents. At scale, use a global inverted index, better chaining and interval deduplication, a background job queue, and measured candidate-retrieval recall. [Winnowing](https://theory.stanford.edu/~aiken/publications/papers/sigmod03.pdf) offers efficient local fingerprint selection for larger exact-reuse workloads.

## Why embeddings are optional

A sentence embedding can retrieve differently worded similar ideas. It can also rank two same-topic passages highly without reused wording. A chunk score does not determine a localized span. This implementation keeps lexical matches and semantic suggestions in separate tables and screens. Strong semantic-only matches require their own review type rather than a mandatory lexical gate that rejects the very paraphrases embeddings were meant to find.

This app fulfills exact and near textual matching without downloading a model. The optional semantic pipeline searches verse windows across all documents and imports a reproducible offline cache; see SEMANTIC.md. Neither path establishes historical dependence.

## Persistence contract

Document IDs are canonicalized so A < B. Passage IDs hash document IDs, content hashes and both ranges. `UNIQUE(document_a,document_b,start_a,end_a,start_b,end_b)` is enforced in SQLite. One transaction deactivates prior results and upserts the complete new set. Review rows are inserted only if missing. Failed detection never publishes a partial active set.

A changed algorithm can produce changed boundaries and therefore a new passage identity; review migration for changed spans is intentionally not automatic. Old inactive reviews remain available in the database. Changes to bundled corpus hashes fail explicitly and require a new database, avoiding silent coordinate corruption.

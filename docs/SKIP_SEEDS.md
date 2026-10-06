# Bounded skip anchors

Version `lexical-1.1.0` adds a second candidate-retrieval route. Exact detection and the established contiguous matches retain their source ranges and review identities.

## Simple explanation

```text
A: the       king         entered
B: the young king quickly entered
```

A contiguous triple cannot connect these fragments. A skip triple selects the same ordered words while allowing at most one intervening word between consecutive selected words. At each starting position the default three-word index tries four patterns of token advances: `(1,1)`, `(1,2)`, `(2,1)`, `(2,2)`. It does not guess which words are additions and does not use their meanings.

The index maps the three selected word values to full original token spans `(start,end)`. Contiguous patterns are included so a plain triple can match a gapped one. Same-key same-span choices are deduplicated. Shared keys generate pairs of spans; keys with more than 60 distinct spans in either document are skipped. Pairs with a gap on at least one side enter this additional route.

Ordered nearby skip anchors are chained using the existing 40-word proximity and 12-word displacement rules. Windows keep the ends of all selected anchors, including intervening words, add 32 words of context, and stay within the candidate-window bound. Diagonal buckets and last-eight-chain lookup remain heuristics.

Local alignment compares the complete original windows. Skipped words are still present and counted as edits. Exact matches still extend only contiguous seeds: a skip triple alone never asserts exact wording. Minimum lengths and the 0.62 lexical similarity threshold are unchanged.

The original contiguous windows are aligned first. Their suppressed result set is retained. Additional skip results are deduplicated against that set, so new longer alternatives cannot displace existing reviewed ranges. This favors stable evidence over replacing a result with a broader overlapping alternative.

## Measured comparison

Same corpus, machine, thresholds, and deterministic fixtures; only skip retrieval enabled/disabled:

| Check | Contiguous only | With skip anchors |
|---|---:|---:|
| Dense-edit positives localized (36 fixtures) | 1/36 | 36/36 |
| Reversed-order controls incorrectly detected | 0/12 | 0/12 |
| Earlier synthetic positives localized | 181/192 | 181/192 |
| Earlier synthetic negative detections | 0/26 | 0/26 |
| Known development passages covered | 18/18 | 18/18 |
| Corpus results | 257 | 265 |
| Exact / near | 58 / 199 | 58 / 207 |
| Corpus analysis time, local CPU | ~2.2 s | ~5.6 s |
| Earlier result ranges preserved | — | 257/257 |

Of the 36 densely edited positive fixtures, 35 have no shared contiguous trigram. One deletion fixture happens to share a repeated triple. A positive counts as localized when the smaller boundary IoU across the two sources is at least 0.6. All result offsets and exact word sequences were verified; duplicate ranges were zero.

These are author-generated stress tests and a previously used development passage list, not a blinded corpus precision/recall benchmark. The improvement is demonstrated for this specific failure mode, not every paraphrase. More candidates and more alignment work are the measured cost. Full data: `skip-seed-evaluation.json`; reproducible fixtures: `skip-seed-cases.json`.

```sh
.venv/bin/python scripts/evaluate_skip_seeds.py
```

## Remaining limits

- More than one intervening word per selected-word gap may prevent an anchor, unless another allowed triple exists nearby.
- No shared ordered selected words means no skip candidate. Semantic suggestions remain a separate route.
- Many additions can pass retrieval but fail the unchanged similarity threshold. Unit tests explicitly cover this case.
- Frequent anchors are pruned; reordered passages, distant chains, and competing local alignments can be missed.
- Shared words do not prove shared meaning, borrowing, or historical dependence.

For default triples the index generates at most four patterns per starting word: approximately linear indexing with a larger constant. Pair enumeration depends on occurrence counts; alignment remains quadratic per bounded window. Whole-system complexity includes chaining, exact extension, and result deduplication; it is not simply linear.

The approach is related to the skip-ngram tokenization and local alignment available in the open-source [textreuse package](https://docs.ropensci.org/textreuse/). Our small Python implementation uses the existing Biopython aligner and adds no runtime dependency.

# Validation report

Current release: `lexical-1.1.0`, verified on 2026-10-06. These are engineering checks and development diagnostics, not a claim of general text-reuse accuracy.

## System verification

- Production React/TypeScript build and Docker Compose build/start: passed.
- Backend suite: 85 tests passed locally on macOS / Python 3.14. GitHub Actions verifies the suite in Linux x86-64 / Python 3.12. A Starlette/httpx adapter deprecation warning does not affect the passing results.
- Browser suite: 8 Chrome scenarios passed against the Docker image in approximately 18 seconds.
- Responsive coverage: all four workspace views checked at widths 320, 390, 768, 1024, 1440, 1920, 2560, and 3440 pixels. No page-level horizontal overflow; the main workspace fills the available width. Passage columns are side by side on large screens and stacked on compact screens. Researcher review controls remain reachable.
- Browser runtime error inspection: none reported.
- Rerun verification: result count and saved reviews preserved, without duplicate results.
- Docker restart checks preserve reviews and notes. On the cleaned corpus, the skip-anchor comparison retains all 257 contiguous-only source ranges.

Browser scenarios exercise exact/near filtering, word highlights, difference toggling, document pairs, pagination, empty states, text search, accepted/rejected reviews, notes, reload persistence, analysis reruns, CSV export, unsaved-note protection, deep links, API failure/recovery, corpus provenance, run statistics, semantic suggestions, and skip-seed evidence.

Backend coverage includes Unicode offsets, edit operations, repeated/separated passages, short/weak rejection, frequent-anchor pruning, diff ranges, corpus checksums/references, canonical pairs, unique ranges, query escaping, CSV formula escaping, concurrency rejection, interrupted runs, atomic rollback, semantic cache validation, and persistent reviews.

## Full-corpus lexical analysis

The bundled corpus contains 61,540 words across three complete texts. Every document pair is analyzed.

| Pair | Parallels | Candidate windows | Contiguous / skip anchors |
|---|---:|---:|---:|
| Luke / Mark | 67 | 27,152 | 16,121 / 24,439 |
| Luke / Matthew | 94 | 40,285 | 23,894 / 37,461 |
| Mark / Matthew | 104 | 26,386 | 20,604 / 27,814 |

Total: **265 candidates, including 58 exact and 207 near matches**. The latest local evaluation took approximately 5.6 seconds, excluding dependency installation and image build. Timings depend on machine and runtime.

All returned source spans, token counts, and normalized word equality for exact results were verified. Duplicate range pairs: zero. The previously selected 18 development passages remain covered under the documented criterion of at least 40% overlap in both annotated spans. This is not exhaustive recall.

## Targeted algorithm diagnostics

The original synthetic set has 192 positive and 26 negative cases. Default detection localizes 181 positives, misses 11, and detects none of the negative controls. Mean boundary IoU is approximately 0.859. The negatives are artificial and cannot establish precision on natural text.

The skip-anchor study compares the same detector with skip retrieval enabled and disabled. On 36 dense-edit positive fixtures, localization improves from 1/36 to 36/36; neither configuration detects the 12 reversed-order negative controls. On the cleaned corpus, all 257 contiguous-only ranges remain and eight additional near candidates appear. Runtime increases from approximately 2.2 to 5.6 seconds in that comparison. See [bounded skip anchors](SKIP_SEEDS.md).

Similarity thresholds and fixtures were explored during development. Neither the known-passage list nor the synthetic tests are independent held-out quality benchmarks. A blinded, representative human review would be needed to estimate usefulness and corpus precision.

## Semantic diagnostics

The exported cache contains 833 suggestions from the pinned `paraphrase-MiniLM-L6-v2` model. At cosine 0.65, it detects 3/6 small challenge paraphrases, versus 1/6 for the earlier baseline. Neither model produces false positives among six ordinary negative controls, but difficult role reversals and negations remain problematic. These samples are too small for a general quality claim.

The model now runs automatically on a runtime cache miss. The cleaned-corpus study encoded 5,694 windows and produced 833 suggestions using the pinned local CPU model. The application validates cached results and imports suggestions with independent reviews. Warm startup reused the generated cache without loading the model; the measured preparation step took about 0.02 seconds, excluding server process startup. See [semantic method and evaluation](SEMANTIC.md).

## Reproduction and artifacts

The README contains backend and browser commands. `scripts/evaluate.py` generates the current lexical report; `scripts/evaluate_skip_seeds.py` performs the controlled skip comparison. Machine-readable reports and deterministic fixtures are included in this directory. `evaluation.json` describes the current release; `skip-seed-evaluation.json` records the controlled before/after study; embedding reports record separate experiments.

GitHub Actions runs backend tests, the frontend production build, and all browser scenarios against a fresh SQLite workspace on Linux, including real first-time model inference and cache reuse.

## Automatic model preparation checks

The corrected release is verified in a fresh Docker container with no database, model files, or generated suggestions. See the release verification below for measured preparation and cache-reuse results. CPU-only PyTorch is used; no GPU is required.

Additional unit tests verify first-run generation, cache hits that never load a model, invalidation of stale model/pipeline revisions and changed lexical/reference inputs, corrupted cache recovery, actual batch completion counters, token-limit rejection, concurrent preparation rejection, failure/retry readiness states, atomic-file failure recovery, and review preservation. Nonfinite scores and duplicate semantic identities are rejected before publication.

A browser scenario exercises the indeterminate download state, determinate encoding progress, compact layout, failure/retry, and automatic transition into the workspace. Real first-run preparation was also visually inspected. The existing rerun scenario asserts that the progress bar appears.

Before the corpus cleanup, all 1,096 existing lexical/semantic result identities, review statuses, and notes were compared across a container replacement and remained unchanged. That check used the earlier corpus; changed source coordinates require a fresh database for the cleaned release. Latest completed lexical configuration is checked during startup, so changes to lexical settings trigger analysis rather than relying on an older completed run.

## Corpus-cleanup regression

Chapter-footer navigation is excluded by the extractor. A regression fixture verifies that the last verse is preserved while navigation is removed; bundled-text checks reject navigation markers. The source archive was fetched again, and all cleaned verse wording was verified against the previous corpus with only its 68 navigation suffixes removed. Checksums, verse coordinates, lexical diagnostics, skip fixtures, and both-model retrieval reports were regenerated together. Historical experiments and screenshots remain identified as development artifacts.

## Clean-release Docker verification

A fresh Linux ARM64 container with no database, model weights, or generated cache completed real first-time preparation in 84.19 seconds, producing 265 lexical parallels and 833 semantic suggestions. After a Docker restart, validated cache reuse completed preparation in 0.02 seconds without model loading. These timings exclude image build and server process startup.

All eight browser scenarios passed against the corrected Docker image in 17.8 seconds. The 85-test backend suite passed on the exact public repository snapshot.

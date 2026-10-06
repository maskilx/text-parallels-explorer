# Validation report

Current release: `lexical-1.1.0`, verified on 2026-10-06. These are engineering checks and development diagnostics, not a claim of general text-reuse accuracy.

## System verification

- Production React/TypeScript build and Docker Compose build/start: passed.
- Backend suite: 66 tests passed locally on macOS / Python 3.14. The same algorithm release was also verified on Linux ARM64 / Python 3.12. A Starlette/httpx adapter deprecation warning does not affect the passing results.
- Browser suite: 7 Chrome scenarios passed against the Docker image in approximately 14 seconds.
- Responsive coverage: all four workspace views checked at widths 320, 390, 768, 1024, 1440, 1920, 2560, and 3440 pixels. No page-level horizontal overflow; the main workspace fills the available width. Passage columns are side by side on large screens and stacked on compact screens. Researcher review controls remain reachable.
- Browser runtime error inspection: none reported.
- Rerun verification: result count and saved reviews preserved, without duplicate results.
- Docker restart and algorithm upgrade checks: reviews and notes preserved; all 260 pre-upgrade passage identities and ranges retained.

Browser scenarios exercise exact/near filtering, word highlights, difference toggling, document pairs, pagination, empty states, text search, accepted/rejected reviews, notes, reload persistence, analysis reruns, CSV export, unsaved-note protection, deep links, API failure/recovery, corpus provenance, run statistics, semantic suggestions, and skip-seed evidence.

Backend coverage includes Unicode offsets, edit operations, repeated/separated passages, short/weak rejection, frequent-anchor pruning, diff ranges, corpus checksums/references, canonical pairs, unique ranges, query escaping, CSV formula escaping, concurrency rejection, interrupted runs, atomic rollback, semantic cache validation, and persistent reviews.

## Full-corpus lexical analysis

The bundled corpus contains 61,676 words across three complete texts. Every document pair is analyzed.

| Pair | Parallels | Candidate windows | Contiguous / skip anchors |
|---|---:|---:|---:|
| Luke / Mark | 67 | 27,099 | 16,108 / 24,355 |
| Luke / Matthew | 95 | 40,191 | 23,887 / 37,317 |
| Mark / Matthew | 105 | 26,339 | 20,599 / 27,746 |

Total: **267 candidates, including 59 exact and 208 near matches**. The latest local evaluation took approximately 5.3 seconds, excluding dependency installation and image build. Timings depend on machine and runtime.

All returned source spans, token counts, and normalized word equality for exact results were verified. Duplicate range pairs: zero. The previously selected 18 development passages remain covered under the documented criterion of at least 40% overlap in both annotated spans. This is not exhaustive recall.

## Targeted algorithm diagnostics

The original synthetic set has 192 positive and 26 negative cases. Default detection localizes 180 positives, misses 12, and detects none of the negative controls. Mean boundary IoU is approximately 0.849. The negatives are artificial and cannot establish precision on natural text.

The skip-anchor study compares the same detector with skip retrieval enabled and disabled. On 36 dense-edit positive fixtures, localization improves from 1/36 to 36/36; neither configuration detects the 12 reversed-order negative controls. All 260 prior corpus ranges remain, and seven additional near candidates appear. Runtime increases from approximately 2.2 to 5.6 seconds in that comparison. See [bounded skip anchors](SKIP_SEEDS.md).

Similarity thresholds and fixtures were explored during development. Neither the known-passage list nor the synthetic tests are independent held-out quality benchmarks. A blinded, representative human review would be needed to estimate usefulness and corpus precision.

## Semantic diagnostics

The exported cache contains 829 suggestions from the pinned `paraphrase-MiniLM-L6-v2` model. At cosine 0.65, it detects 3/6 small challenge paraphrases, versus 1/6 for the earlier baseline. Neither model produces false positives among six ordinary negative controls, but difficult role reversals and negations remain problematic. These samples are too small for a general quality claim.

The model runs offline during artifact generation. The application validates corpus checksums and imports suggestions with independent reviews; lexical analysis does not run inference. See [semantic method and evaluation](SEMANTIC.md).

## Reproduction and artifacts

The README contains backend and browser commands. `scripts/evaluate.py` generates the current lexical report; `scripts/evaluate_skip_seeds.py` performs the controlled skip comparison. Machine-readable reports and deterministic fixtures are included in this directory. `evaluation.json` describes the current release; `skip-seed-evaluation.json` records the controlled before/after study; embedding reports record separate experiments.

GitHub Actions runs backend tests, the frontend production build, and all browser scenarios against a fresh SQLite workspace on Linux.

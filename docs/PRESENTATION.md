# Workspace walkthrough

## Five-minute walkthrough

1. Start with `docker compose up --build`. Explain the bundled corpus and why synoptic texts are useful for lexical parallels.
2. Open an exact match. Show the percentage, original spans, verse references and source links. Distinguish normalized equality from literal original equality.
3. Filter to near matches. Explain additions, omissions and substitutions using the highlighted word differences.
4. Add a researcher note and accept a result. Filter accepted results and export CSV.
5. Run analysis again. Show unchanged result count and preserved review. Visit Method & runs to demonstrate coverage of all three pairs.
6. Present the measured evaluation and one known failure. Explain why development-set coverage is not exhaustive recall or precision.

## Design decisions

- Why local rather than global alignment? Local matches occur inside otherwise different documents.
- Why 3-word seeds? They tolerate modest edits but produce more incidental candidates; seed length is measured in the ablation study.
- What does 62% mean? Normalized word edit similarity, selected on a small development set; not a confidence probability.
- Why not embeddings alone? They compare meaning at the chunk level, and do not supply exact localized textual evidence.
- What happens after punctuation/case normalization? Source offsets remain attached to original tokens.
- Can the detector find all parallels? No. Candidate retrieval, common-seed pruning, windowing, and one-best alignment can miss matches.
- How are duplicates prevented? Canonical pairs, deterministic ranges, stable hashes, a UNIQUE constraint, and upsert.
- What if the run fails? Previous active results remain; an analysis-run record reports failure.
- What if algorithm boundaries change? New ranges are new identities; inactive reviews are retained, without speculative migration.
- How would it scale? Better global candidate retrieval, bounded alignment, worker jobs, and evaluation of recall before optimizing.
- How did AI contribute? Disclose Codex assistance and explain what you reviewed and what remains limited.

The examples demonstrate both useful matches and the limits of the retrieval methods.


## Semantic extension

Explain: verse windows → 384-dimensional vectors → cosine → mutual best neighbor above 0.65 → human review. No model training or vector database. The required algorithm still runs live; the optional semantic screen imports reproducible local results for the fixed corpus. Compare the model study honestly: at 0.65, 3/6 versus 1/6 challenge paraphrases, with 0/6 ordinary negative false positives for both; role reversals still fail. Small author-written development diagnostics do not prove general accuracy. See SEMANTIC.md.


## Skip anchors

Use the example `the king entered` versus `the young king quickly entered`. Enumerate four allowed advance patterns per starting word. Matching selected words only retrieve a candidate; intervening words remain in the full alignment and edit score. Existing contiguous ranges keep priority. Explain the measured cost: ~2.2 to ~5.6 seconds for this corpus, and the targeted gain: 1/36 to 36/36 dense-edit development fixtures, with 0/12 reversed-order detections. No new dependency or model training. See SKIP_SEEDS.md.

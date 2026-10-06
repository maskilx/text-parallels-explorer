# Semantic suggestions: a small, reproducible extension

The required lexical detector remains the primary system. Semantic suggestions provide an additional route for related passages with different wording and no shared three-word anchor. They have their own screen, cosine score, and persistent accept/reject review. They are not promoted to exact/near lexical evidence automatically.

## Explain it in five steps

1. Split each source into one verse and two adjacent verses within the same chapter. Keep original character offsets. Exclude windows shorter than 8 or longer than 90 words.
2. A pretrained model turns each window into 384 numbers. Normalize each vector to length one.
3. Multiply vectors to get cosine similarity for each cross-document pair. This is a semantic ranking score, not a percentage of matching words.
4. Keep mutual top-one neighbors above cosine 0.65. Remove overlapping alternatives and candidates substantially covered by the lexical detector. Mutual neighbors reduce one-sided generic matches but can miss repeated or one-to-many parallels.
5. Display the original source windows and let the researcher decide. The highlighted window is coarse localization; it does not assert that every word corresponds.

There is no training, LLM, reranker, paid service, or vector database. The largest matrix is roughly 4.8 million float32 scores (~19 MB). The model encodes 5,694 windows once. The word cap prevents oversized inputs in this corpus; the recorded run checked model-token lengths and found zero truncations. Future corpus changes must recheck this.

## Models compared

Both models are Apache-2.0 licensed, have approximately 22.7 million parameters, and produce 384-dimensional vectors:

- [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), the earlier baseline; maximum 256 model tokens.
- [paraphrase-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/paraphrase-MiniLM-L6-v2), the selected small paraphrase model; maximum 128 model tokens.

This is symmetric passage comparison, as described in the [Sentence Transformers semantic search documentation](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html). The names of models alone do not establish which works better.

## What the evaluation actually established

The earlier experiment only scored preselected pairs. The new study searches all three complete documents without an oracle supplying the matching passage boundaries. It also uses 8 author-written calibration pairs and 16 new challenge pairs with different topics, fixed before the first run. Selecting a model and operational threshold after inspecting the challenge makes these development diagnostics, not independent final-test results.

At cosine 0.65, the paraphrase model found 3 of the 6 challenge paraphrases, compared with 1 of 6 for the baseline. Neither returned a false positive among the 6 ordinary negative pairs at that threshold. Lowering the threshold recovers more paraphrases and adds false positives. These sample sizes are too small to establish corpus precision or general superiority.

Both models still confuse subject/object reversals; contradictions also receive high scores. Such pairs may nevertheless be textual parallels: different meaning does not imply different wording or absence of textual reuse. The interface deliberately calls them suggestions and leaves interpretation to the researcher.

At each model's lower calibration threshold and mutual top-three retrieval, 17 of 18 previously selected known corpus passages were located. This is a coverage diagnostic using coarse windows and a previously used development list, not independent recall. It is separate from the exported operational cache, which uses 0.65 and mutual top-one. Raw candidates are unannotated; their count is not a quality metric.

A deterministic spot check of three candidates in each of three score bands found seven plausible shared passages and two unconvincing topic-only suggestions (both in the 0.65–0.75 band). This was AI-assisted author inspection, not blinded expert annotation or a corpus precision estimate; see `semantic-candidate-audit.json`.

All scores, model revisions, timings, pair counts, examples, threshold sensitivity, and caveats are in `semantic-retrieval-results.json`. The older `embedding-results.json` is retained as the initial experiment.

## Runtime and regeneration

The app imports `app/assets/semantic.json` into a separate SQLite `semantic_suggestions` table. This is an explicitly precomputed artifact for the fixed bundled corpus, not an online model inference feature. Import verifies corpus hashes, original-source substrings, and stable range identities. Upsert preserves reviews; invalid offsets cannot publish a partial import. Corpus hash mismatches deactivate stale suggestions.

This keeps the required one-command startup fast and independent of model downloads. The existing **Run analysis** button reruns the lexical detector. To regenerate the semantic cache locally:

```sh
python3 -m venv .embeddings-venv
.embeddings-venv/bin/pip install -r requirements.txt -r requirements-embeddings.txt
.embeddings-venv/bin/python scripts/semantic_retrieval.py --export
docker compose up --build
```

The first regeneration downloads public model weights; subsequent runs can use the Hugging Face cache. Known model revisions are pinned in the script. No credentials or paid API are needed. The generated artifact stores model provenance and document checksums, and is included in the repository and Docker image. Live lexical analysis and this reproducible offline extension are separate processing paths.


After the lexical-1.1.0 skip-anchor upgrade, the cache was regenerated against the updated detector. Model and cosine settings remain unchanged; `lexical_version` records which detector excluded already-covered candidates. The earlier nine-example spot audit remains a historical sample of the prior cache.

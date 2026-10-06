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

## One-command runtime

`docker compose up --build` prepares both the lexical detector and the embedding model. The server opens immediately after validating the corpus; preparation runs in a background thread so the browser can display progress.

1. Analyze all document pairs if a current lexical run is missing.
2. Check `data/semantic-cache.json` against the pinned model revision, pipeline version/settings, corpus hashes, reference hashes, and active lexical range identities.
3. On a cache miss, load the CPU model (downloading public weights on first use), validate token lengths, and encode windows in batches of 64. Progress reports actual completed windows.
4. Retrieve mutual top-one matches above 0.65, suppress overlaps and lexical coverage, validate source ranges, and save the complete artifact with an atomic rename.
5. Import suggestions transactionally into SQLite while preserving existing reviews, then mark the workspace ready.

The same Docker volume retains the database, generated artifact, and Hugging Face model cache. A warm launch does not load the model when the artifact is valid. **Run analysis** refreshes lexical results and checks/rebuilds semantic results as necessary. A model or pipeline revision, reference change, changed lexical ranges, or corrupt artifact invalidates reuse. A changed corpus requires a fresh database to preserve the meaning of existing review coordinates.

During model download/loading the bar is indeterminate: the application cannot honestly report a complete download percentage. During encoding it advances by completed batches; other phases report their measured completion. Percentages allocate progress across phases and are not an estimate of remaining wall-clock time. Readiness is reached only after validated results are published.

Failures are visible, logged, and retryable; earlier database reviews are preserved. Missing internet on first use cannot silently fall back to a precomputed artifact. The repository's `app/assets/semantic.json` is retained as a historical evaluation/test fixture and is not the normal runtime cache.

The first launch requires internet, disk space for CPU dependencies/model files, and additional preparation time. There is no paid API or remote inference. The default container uses CPU-only PyTorch; no GPU is required.

`GET /api/startup` exposes progress. `GET /api/ready` returns 200 only after completion and 503 otherwise. `POST /api/startup/retry` retries failed preparation. `/api/health` is a liveness check so the server can remain available to show progress or a failure.

## Reproducing the historical model comparison

The model-comparison script remains a separate development experiment, using the same shared windowing/retrieval functions as the runtime:

```sh
python3 -m venv .embeddings-venv
.embeddings-venv/bin/pip install -r requirements.txt -r requirements-embeddings.txt
.embeddings-venv/bin/python scripts/semantic_retrieval.py --export
```

This records evaluation results and can refresh the historical bundled fixture; it is not required to start the application. Model revisions are pinned. The earlier nine-example spot audit remains a historical sample, not a current accuracy estimate.

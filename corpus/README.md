# Bundled corpus

Three complete Gospel texts from the World English Bible Classic, eBible.org.

- Source archive: https://ebible.org/Scriptures/eng-web_html.zip
- Rights statement: https://ebible.org/eng-web/copyright.htm
- Retrieved: 2026-10-05
- The translation is in the public domain; its name is a trademark of eBible.org.

`manifest.json` contains URLs and SHA-256 checksums. `.txt` files contain verse text with standardized whitespace, no headings, footnotes, navigation or verse numbers. `.refs.json` contains verse identifiers and exact code-point ranges in the corresponding `.txt` file. Multi-paragraph quotations and poetry are included.

Rebuild with `python scripts/fetch_corpus.py` after installing `requirements-dev.txt`. This network-dependent maintenance script is not required to run the app. Source updates can change checksums. Use a new database after a corpus change.

Luke 17:36 has no main verse text in this edition and is represented in a footnote, so the bundled Luke file contains 1,150 nonempty verse entries. The app intentionally excludes footnotes.

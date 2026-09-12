"""Task 8 step 4: stamp real silo labels onto the extracted corpus.

`Document.silo` has been `()` on every document since T9 -- this is the
script that fills it in, from `data/silos.yaml`'s path-prefix rules. Rewrites
`corpus/extracted/documents.jsonl` in place (same file, same format,
`ExtractedCorpus.write`'s sort-by-url order) and reports the per-silo
breakdown and the `other` rate PLAN Sec 2c flags at >10%.

Chunking and indexing must be re-run after this (`scripts/chunk_corpus.py`,
`scripts/build_indexes.py`) since `Chunk.silo` is stamped from `Document.silo`
at chunk time. Content hashes are untouched by this script, so
`incremental_reindex`'s diff would treat every page as unchanged and skip
re-embedding -- delete `indexes/` before rebuilding rather than relying on the
incremental path here, this is a metadata-only change the hash was never
meant to track.

    python scripts/map_silos.py
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.extract.pipeline import ExtractedCorpus  # noqa: E402
from mcrag.silo_mapper import SiloMapper  # noqa: E402

BASE = "https://www.maryvillecollege.edu"


def main() -> int:
    corpus = ExtractedCorpus(Path("corpus/extracted/documents.jsonl"))
    documents = corpus.read()
    mapper = SiloMapper.from_yaml()

    stamped = [replace(doc, silo=mapper.assign(doc.url, BASE)) for doc in documents]
    corpus.write(stamped)

    counts: Counter[str] = Counter()
    for doc in stamped:
        for silo in doc.silo:
            counts[silo] += 1

    total = len(stamped)
    print(f"{total} documents stamped\n")
    for silo, n in counts.most_common():
        print(f"{n:5d}  {n / total:6.1%}  {silo}")
    other_rate = counts.get("other", 0) / total
    print(f"\nother rate: {other_rate:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""
Dedupe a candidate JSONL dataset against an existing base JSONL and within itself
using sentence-transformer embeddings, then write the filtered candidates.

Example:
python utils/scripts/dedupe_new_facts.py ^
  --base data/alexandra_hospital_chroma_merged.jsonl ^
  --candidates data/alexandra_hospital_chroma_facts_10k.jsonl ^
  --output data/alexandra_hospital_chroma_facts_10k_filtered.jsonl ^
  --threshold 0.9
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict, List, Sequence, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer


def read_jsonl(path: pathlib.Path) -> List[Dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: pathlib.Path, rows: Sequence[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def encode(model: SentenceTransformer, texts: List[str], batch_size: int = 64) -> np.ndarray:
    return model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )


def dedupe(
    base_texts: List[str],
    candidate_items: List[Tuple[str, Dict]],
    *,
    threshold: float,
    model: SentenceTransformer,
    batch_size: int = 64,
) -> List[Dict]:
    seen_texts = set(t.lower().strip() for t in base_texts)
    kept: List[Dict] = []

    base_embs = encode(model, base_texts, batch_size=batch_size) if base_texts else np.zeros((0, 384))
    accepted_embs = base_embs

    # process candidates in batches for speed
    for idx in range(0, len(candidate_items), batch_size):
        chunk = candidate_items[idx : idx + batch_size]
        texts = [t for t, _ in chunk]
        embs = encode(model, texts, batch_size=batch_size)

        for (text, obj), emb in zip(chunk, embs):
            key = text.lower().strip()
            if key in seen_texts:
                continue
            if accepted_embs.shape[0]:
                sims = accepted_embs @ emb
                if sims.max() >= threshold:
                    continue
            kept.append(obj)
            seen_texts.add(key)
            accepted_embs = np.vstack([accepted_embs, emb])

    return kept


def main() -> None:
    ap = argparse.ArgumentParser(description="Dedupe candidate JSONL against base using semantic similarity.")
    ap.add_argument("--base", required=True, help="Existing JSONL to protect (already ingested).")
    ap.add_argument("--candidates", required=True, help="New JSONL to filter.")
    ap.add_argument("--output", required=True, help="Filtered JSONL output.")
    ap.add_argument("--threshold", type=float, default=0.9, help="Cosine similarity threshold for dupes.")
    ap.add_argument("--batch-size", type=int, default=64, help="Batch size for embeddings.")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model.")
    args = ap.parse_args()

    base_path = pathlib.Path(args.base)
    cand_path = pathlib.Path(args.candidates)
    out_path = pathlib.Path(args.output)

    base_rows = read_jsonl(base_path)
    cand_rows = read_jsonl(cand_path)

    base_texts = [r.get("text", "") for r in base_rows]
    candidate_items = [(r.get("text", ""), r) for r in cand_rows]

    print(f"Loaded base={len(base_rows)} candidates={len(candidate_items)}")

    model = SentenceTransformer(args.model)
    kept = dedupe(
        base_texts=base_texts,
        candidate_items=candidate_items,
        threshold=args.threshold,
        model=model,
        batch_size=args.batch_size,
    )

    write_jsonl(out_path, kept)
    print(f"Kept {len(kept)} / {len(candidate_items)} candidates; wrote {out_path}")


if __name__ == "__main__":
    main()

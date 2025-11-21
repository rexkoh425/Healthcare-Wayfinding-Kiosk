#!/usr/bin/env python
"""
Normalize/merge JSONL datasets for the Alexandra Hospital chatbot and (optionally)
push them into a Chroma vector store.

Usage examples:
python utils/scripts/prepare_chroma_data.py ^
  --input data/alexandra_hospital_chroma_facts_only.jsonl data/alexandra_hospital_chroma_input.jsonl ^
  --output data/alexandra_hospital_chroma_merged.jsonl ^
  --ascii-fallback

python utils/scripts/prepare_chroma_data.py ^
  --input data/alexandra_hospital_chroma_merged.jsonl ^
  --chroma-dir .chroma/ah ^
  --collection alexandra_hospital ^
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import unicodedata
from typing import Dict, Iterable, List, Sequence


def normalize_text(text: str, ascii_fallback: bool = False) -> str:
    """Clean up text (trim, normalize unicode, optionally force ASCII-friendly punctuation)."""
    cleaned = unicodedata.normalize("NFKC", text or "").strip()

    if not ascii_fallback:
        return cleaned

    replacements = {
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2015": "-",  # horizontal bar
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2212": "-",  # minus sign
        "\u00b7": "-",  # middle dot
        "\u00a0": " ",  # non-breaking space
        "\u2022": "-",  # bullet
        "\u2194": "<->",  # left-right arrow
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for bad, good in replacements.items():
        cleaned = cleaned.replace(bad, good)

    return cleaned


def coerce_tags(tags: Iterable | None) -> List[str]:
    """Ensure tags is a list of strings."""
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags]
    return [str(t) for t in tags]


def normalize_record(
    record: Dict,
    source_name: str,
    ascii_fallback: bool = False,
) -> Dict:
    """Produce a consistent shape for vector ingestion."""
    meta = record.get("metadata") or {}
    hospital = meta.get("hospital") or meta.get("entity") or "Alexandra Hospital"
    doc_type = meta.get("doc_type") or meta.get("chunk_type") or "fact"
    section = (
        meta.get("section")
        or meta.get("source_title")
        or meta.get("location_name")
        or meta.get("question")
    )

    normalized_meta = {
        "hospital": hospital,
        "entity": meta.get("entity", hospital),
        "doc_type": doc_type,
        "chunk_type": meta.get("chunk_type"),
        "section": section,
        "tags": coerce_tags(meta.get("tags")),
        "as_of": meta.get("as_of"),
        "created_on": meta.get("created_on"),
        "language": meta.get("language") or "en",
        "version": meta.get("version"),
        "source_id": meta.get("source_id"),
        "source_title": meta.get("source_title"),
        "source_url": meta.get("source_url"),
        "question": meta.get("question"),
        "location_name": meta.get("location_name"),
        "variants": meta.get("variants"),
        "ingest_source": source_name,
    }

    def normalize_meta_value(key: str, value):
        if value is None:
            return None
        if key == "source_url":
            return value
        if isinstance(value, str):
            return normalize_text(value, ascii_fallback=ascii_fallback)
        if isinstance(value, list):
            # Chroma metadata must be scalar; join lists into a string
            return "; ".join(normalize_text(str(v), ascii_fallback=ascii_fallback) for v in value)
        return value

    normalized_meta = {k: normalize_meta_value(k, v) for k, v in normalized_meta.items()}
    normalized_meta = {k: v for k, v in normalized_meta.items() if v not in (None, [], {})}

    return {
        "id": record["id"],
        "text": normalize_text(record.get("text", ""), ascii_fallback=ascii_fallback),
        "metadata": normalized_meta,
    }


def read_jsonl(path: pathlib.Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} JSON decode error: {exc}") from exc
    return rows


def write_jsonl(path: pathlib.Path, rows: Sequence[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_collection(
    records: Sequence[Dict],
    persist_dir: pathlib.Path,
    collection_name: str,
    embedding_model: str,
    batch_size: int = 64,
) -> None:
    """Create/update a Chroma collection with provided records."""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "chromadb (and sentence-transformers for the embedding function) is required "
            "to push data into a vector store. Install with: pip install 'chromadb>=0.5.0' "
            "'sentence-transformers>=3.0.0'"
        ) from exc

    client = chromadb.PersistentClient(path=str(persist_dir))
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
    collection = client.get_or_create_collection(name=collection_name, embedding_function=embed_fn)

    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        collection.upsert(
            ids=[r["id"] for r in chunk],
            documents=[r["text"] for r in chunk],
            metadatas=[r["metadata"] for r in chunk],
        )

    print(f"Chroma collection '{collection_name}' updated with {len(records)} records at {persist_dir}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unify AH JSONL data and optionally build a Chroma store.")
    parser.add_argument("--input", nargs="+", required=True, help="Input JSONL files.")
    parser.add_argument("--output", default="data/alexandra_hospital_chroma_merged.jsonl", help="Normalized JSONL output path.")
    parser.add_argument("--ascii-fallback", action="store_true", help="Replace curly quotes/dashes/arrows with ASCII equivalents.")
    parser.add_argument("--chroma-dir", help="If set, also persist to this Chroma directory.")
    parser.add_argument("--collection", default="alexandra_hospital", help="Chroma collection name.")
    parser.add_argument("--embedding-model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model for Chroma.")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size for Chroma upserts.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])
    seen_ids = set()
    normalized: List[Dict] = []

    for input_path in args.input:
        path = pathlib.Path(input_path)
        source_name = path.name
        raw_rows = read_jsonl(path)
        for row in raw_rows:
            if row["id"] in seen_ids:
                # Skip exact duplicate ids to keep Chroma happy.
                continue
            normalized.append(
                normalize_record(
                    record=row,
                    source_name=source_name,
                    ascii_fallback=bool(args.ascii_fallback),
                )
            )
            seen_ids.add(row["id"])

    output_path = pathlib.Path(args.output)
    write_jsonl(output_path, normalized)
    print(f"Wrote {len(normalized)} normalized records to {output_path}")

    if args.chroma_dir:
        build_collection(
            records=normalized,
            persist_dir=pathlib.Path(args.chroma_dir),
            collection_name=args.collection,
            embedding_model=args.embedding_model,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()

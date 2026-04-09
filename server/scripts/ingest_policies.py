#!/usr/bin/env python3
"""
Ingest policy documents into admin_documents (pgvector) for RAG.

- Reads server/policies/policies.md
- Chunks into smaller pieces (good retrieval)
- Embeds with local Sentence Transformers (BAAI/bge-m3, 1024 dims)
- Inserts into admin_documents with source='policy'

Usage:
  cd server
  source .venv/bin/activate
  pip install "sentence-transformers>=3.0.0"
  # optional: pip install torch --extra-index-url https://download.pytorch.org/whl/cpu

  python scripts/ingest_policies.py
  python scripts/ingest_policies.py --no-rebuild
"""

import os
import sys
import json
import argparse
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text, MetaData, Table
from sqlalchemy.orm import Session

from database import SessionLocal, engine


# -----------------------------
# Local embeddings: BAAI/bge-m3 (1024 dims)
# -----------------------------
class LocalEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "Install sentence-transformers: pip install sentence-transformers"
            ) from e

        # Use Apple Silicon MPS if available, else CPU
        device = "cpu"
        try:
            import torch
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
        except Exception:
            pass

        self.model = SentenceTransformer(model_name, device=device)

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        # normalize_embeddings=True is good for cosine distance
        import numpy as np
        out: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            vecs = self.model.encode(batch, convert_to_numpy=True, normalize_embeddings=True)
            out.extend(vecs.tolist() if isinstance(vecs, np.ndarray) else [list(v) for v in vecs])
        return out


# -----------------------------
# Reflect admin_documents (we insert with explicit CAST)
# -----------------------------
metadata = MetaData()
admin_documents = Table("admin_documents", metadata, autoload_with=engine)

def _embedding_to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

def insert_docs(db: Session, rows: List[Dict]):
    if not rows:
        return
    sql = text("""
        INSERT INTO admin_documents
            (source, product_id, title, content, metadata, embedding)
        VALUES
            (:source, :product_id, :title, :content,
             CAST(:metadata AS jsonb), CAST(:embedding AS vector))
    """)
    for r in rows:
        if isinstance(r.get("embedding"), list):
            r["embedding"] = _embedding_to_vector_literal(r["embedding"])
    db.execute(sql, rows)

def purge_policies(db: Session):
    db.execute(text("DELETE FROM admin_documents WHERE source='policy'"))


# -----------------------------
# Chunking helpers (simple + robust)
# -----------------------------
def _normalize_md(md: str) -> str:
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    return md.strip()

def chunk_markdown(md: str, max_chars: int = 1400, overlap_chars: int = 200) -> List[str]:
    """
    Simple chunker for markdown:
    - split on headings and blank lines, then pack into chunks of ~max_chars
    - add overlap to avoid losing context at boundaries
    """
    md = _normalize_md(md)
    if not md:
        return []

    lines = md.split("\n")
    blocks: List[str] = []
    buf: List[str] = []

    def flush():
        nonlocal buf
        if buf:
            blocks.append("\n".join(buf).strip())
            buf = []

    for line in lines:
        # start a new block when we hit a heading
        if line.strip().startswith("#") and buf:
            flush()
        buf.append(line)
        # break blocks on large gaps
        if line.strip() == "" and len("\n".join(buf)) > 800:
            flush()

    flush()

    # pack blocks into chunks
    chunks: List[str] = []
    current = ""

    for b in blocks:
        if not b:
            continue
        if len(current) + len(b) + 2 <= max_chars:
            current = (current + "\n\n" + b).strip() if current else b
        else:
            if current:
                chunks.append(current.strip())
            # if block itself is too big, split it hard
            if len(b) > max_chars:
                start = 0
                while start < len(b):
                    end = min(len(b), start + max_chars)
                    chunks.append(b[start:end].strip())
                    start = end - overlap_chars if end - overlap_chars > start else end
                current = ""
            else:
                current = b

    if current:
        chunks.append(current.strip())

    # add overlap between chunks (optional, light)
    if overlap_chars > 0 and len(chunks) > 1:
        overlapped: List[str] = []
        for i, c in enumerate(chunks):
            if i == 0:
                overlapped.append(c)
            else:
                prev = chunks[i-1]
                overlap = prev[-overlap_chars:]
                overlapped.append((overlap + "\n" + c).strip())
        chunks = overlapped

    # final cleanup
    return [c for c in chunks if c]


# -----------------------------
# Main ingest
# -----------------------------
def ingest_policies(
    path: str,
    rebuild: bool = True,
    model_name: str = "BAAI/bge-m3",
) -> int:
    """
    Returns number of chunks inserted.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Policy file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        md = f.read()

    chunks = chunk_markdown(md, max_chars=1400, overlap_chars=200)
    if not chunks:
        return 0

    embedder = LocalEmbedder(model_name=model_name)
    embeddings = embedder.embed_batch(chunks)

    # Each chunk becomes one row. policy docs don’t map to product_id.
    title = os.path.basename(path)
    rows: List[Dict] = []

    for idx, (content, emb) in enumerate(zip(chunks, embeddings), start=1):
        meta = {
            "doc": title,
            "chunk": idx,
            "path": path,
        }
        rows.append({
            "source": "policy",
            "product_id": None,
            "title": f"Policy: {title} (chunk {idx})",
            "content": content,
            "metadata": json.dumps(meta),
            "embedding": emb,
        })

    db: Session = SessionLocal()
    try:
        if rebuild:
            purge_policies(db)
            db.commit()

        insert_docs(db, rows)
        db.commit()
        return len(rows)
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Ingest policies.md into admin_documents (pgvector).")
    ap.add_argument("--path", type=str, default="policies/policies.md", help="Path to policies markdown file (relative to server/).")
    ap.add_argument("--no-rebuild", action="store_true", help="Append-only; do not delete existing policy rows.")
    ap.add_argument("--model", type=str, default="BAAI/bge-m3", help="Local embedding model id.")
    args = ap.parse_args()

    # run from server/ directory typically
    chunks = ingest_policies(path=args.path, rebuild=(not args.no_rebuild), model_name=args.model)
    print(f"\nDone. policy_chunks_inserted={chunks}")


if __name__ == "__main__":
    main()

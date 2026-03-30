#!/usr/bin/env python3
"""
Ingest Products into admin_documents for admin search (pgvector).

- Reads products from the DB
- Chunks text (~450 tokens, ~60 overlap)
- Embeds with a provider:
    * Local default: BAAI/bge-m3 (1024 dims)
    * Optional: OpenAI embeddings (e.g., text-embedding-3-small, 1536 dims)
- Upserts rows into admin_documents with source='product' and JSON metadata
- Inserts embeddings with explicit CAST(:embedding AS vector) so SQLAlchemy
  doesn't need to know pgvector's custom type.

USAGE (macOS):
  cd server
  source .venv/bin/activate

  # Local embeddings (default, BAAI/bge-m3, 1024 dims)
  pip install "sentence-transformers>=3.0.0"
  pip install torch --extra-index-url https://download.pytorch.org/whl/cpu
  python scripts/ingest_products.py --provider local --model "BAAI/bge-m3" --limit 10

  # OpenAI embeddings (optional):
  pip install openai tiktoken
  export OPENAI_API_KEY="sk-..."
  python scripts/ingest_products.py --provider openai --model "text-embedding-3-small" --limit 10

DB expectations:
- admin_documents.embedding is vector(1024) for BGE-M3 (we migrated earlier).
- If you switch to OpenAI embeddings (e.g., 1536 dims), change the column:
    ALTER TABLE admin_documents ALTER COLUMN embedding TYPE vector(1536);
    -- and recreate the HNSW index
"""

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import json
import math
import time
import argparse
from typing import List, Dict, Optional, Tuple

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import text, MetaData, Table
from sqlalchemy.orm import Session

# Reuse your app's DB setup & models
from database import SessionLocal, engine
from models import Product

print("[INFO] Using explicit CAST(:embedding AS vector) inserts (no SQLAlchemy pgvector registration).")

# ---------- Optional token-aware chunking ----------
_HAS_TIKTOKEN = False
try:
    import tiktoken  # better token estimation if available
    _HAS_TIKTOKEN = True
except Exception:
    pass

# ---------- Optional: OpenAI embeddings ----------
try:
    from openai import OpenAI  # only used when --provider openai
except Exception:
    OpenAI = None


# =====================================================
# Chunking helpers
# =====================================================
def _approx_token_count(s: str) -> int:
    """Rough fallback: ~4 chars per token (very rough; ok as a fallback)."""
    return max(1, math.ceil(len(s) / 4))


def _encode_tokens(text: str, model_hint: str) -> List[int]:
    """
    Try to tokenize with tiktoken. If the model name is unknown to tiktoken,
    fall back to a baseline encoding; else fall back to naive counting.
    """
    if not _HAS_TIKTOKEN:
        return []

    try:
        # Works for OpenAI models
        enc = tiktoken.encoding_for_model(model_hint)
    except Exception:
        # Fallback to a common base encoding (ok for estimating chunk sizes)
        try:
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            return []
    try:
        return enc.encode(text)
    except Exception:
        return []


def split_into_chunks(
    text: str,
    target_tokens: int = 450,
    overlap_tokens: int = 60,
    model_hint: str = "BAAI/bge-m3",
) -> List[str]:
    """
    Split text into chunks (~target_tokens) with (~overlap_tokens).
    Uses tiktoken if available; otherwise simple paragraph/word accumulation.
    """
    text = text.strip()
    if not text:
        return []

    tokens = _encode_tokens(text, model_hint)
    if tokens:
        # Token-aware chunking
        try:
            enc = tiktoken.encoding_for_model(model_hint)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")

        chunks = []
        start = 0
        while start < len(tokens):
            end = min(len(tokens), start + target_tokens)
            chunk_tokens = tokens[start:end]
            chunks.append(enc.decode(chunk_tokens))
            # Prepare next window with overlap
            nxt = end - overlap_tokens
            start = nxt if nxt > start else end
        return chunks

    # Fallback: paragraph-based accumulation, with rough token estimate
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], []
    cur_tokens = 0

    for p in paras:
        p_tokens = _approx_token_count(p)
        if cur_tokens + p_tokens > target_tokens and buf:
            chunks.append("\n\n".join(buf))
            # naive overlap: keep last paragraph
            overlap = buf[-1] if buf else ""
            buf = [overlap] if overlap else []
            cur_tokens = _approx_token_count(overlap)

        buf.append(p)
        cur_tokens += p_tokens

    if buf:
        chunks.append("\n\n".join(buf))

    # If still too long, do a word-split fallback
    final = []
    for c in chunks:
        if _approx_token_count(c) <= target_tokens * 1.5:
            final.append(c)
        else:
            words = c.split()
            step = max(1, int(target_tokens * 4))  # ~4 chars per token
            for i in range(0, len(words), step):
                sub = " ".join(words[i : i + step])
                final.append(sub)
    return final


# =====================================================
# Embedders
# =====================================================
class LocalEmbedder:
    """
    CPU-friendly local embedder using sentence-transformers.
    Default model: BAAI/bge-m3 (1024 dims, multilingual, strong retrieval).
    """
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "Install sentence-transformers to use LocalEmbedder: pip install sentence-transformers"
            ) from e
        self.model_name = model_name
        # dev-friendly CPU
        self.model = SentenceTransformer(model_name, device="cpu")

    def embed_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        import numpy as np
        out: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embs = self.model.encode(
                batch,
                batch_size=len(batch),         # single pass for small batches
                convert_to_numpy=True,
                normalize_embeddings=True      # cosine-friendly
            )
            out.extend(embs.tolist() if isinstance(embs, np.ndarray) else [list(v) for v in embs])
        return out


class OpenAIEmbedder:
    """
    OpenAI embeddings provider (optional).
    Requires: export OPENAI_API_KEY=...
    """
    def __init__(self, model: str = "text-embedding-3-small"):
        if OpenAI is None:
            raise RuntimeError("openai package not installed. pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Set OPENAI_API_KEY to use OpenAI embeddings.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = self.client.embeddings.create(model=self.model, input=batch)
            for datum in resp.data:
                out.append(datum.embedding)
            time.sleep(0.03)  # be polite on local dev
        return out


# =====================================================
# admin_documents (reflect) + helpers
# =====================================================
metadata = MetaData()
admin_documents = Table("admin_documents", metadata, autoload_with=engine)


def purge_product_docs(db: Session, product_id: int):
    db.execute(
        admin_documents.delete().where(
            (admin_documents.c.source == "product")
            & (admin_documents.c.product_id == product_id)
        )
    )


def _embedding_to_vector_literal(vec: List[float]) -> str:
    """Python list[float] -> pgvector literal like: [0.12345678,-0.23456789,...]"""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _json_default(o):
    """Serialize non-JSON-native objects (e.g., datetime, Decimal)."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def insert_docs(db: Session, rows: List[Dict]):
    """Insert using explicit CASTs so SQLAlchemy doesn't need pgvector type info."""
    if not rows:
        return
    sql = text(
        """
        INSERT INTO admin_documents
            (source, product_id, title, content, metadata, embedding)
        VALUES
            (:source, :product_id, :title, :content,
             CAST(:metadata AS jsonb), CAST(:embedding AS vector))
        """
    )
    for r in rows:
        emb = r.get("embedding")
        if isinstance(emb, list):
            r["embedding"] = _embedding_to_vector_literal(emb)
        # metadata is a JSON string (we use json.dumps(..., default=_json_default) when building rows)
    db.execute(sql, rows)


# =====================================================
# Product -> text & metadata
# =====================================================
def build_product_text(prod: Product) -> str:
    """Compose a single text blob from product fields."""
    lines = []
    lines.append(prod.name or "")
    if prod.category:
        lines.append(f"Category: {prod.category}")

    if prod.price_cents is not None:
        try:
            rupees = prod.price_cents / 100.0
            lines.append(f"Price: ₹{rupees:,.2f}")
        except Exception:
            lines.append(f"Price (paise): {prod.price_cents}")

    if prod.description:
        lines.append("Description:")
        lines.append(prod.description.strip())

    # Pretty print specs_json if present
    if getattr(prod, "specs_json", None):
        try:
            obj = json.loads(prod.specs_json) if isinstance(prod.specs_json, str) else prod.specs_json
            if isinstance(obj, dict) and obj:
                lines.append("Specs:")
                for k, v in obj.items():
                    lines.append(f"- {k}: {v}")
        except Exception:
            pass

    return "\n\n".join([line for line in lines if line])


def product_metadata(prod: Product) -> Dict:
    return {
        "category": prod.category,
        "price_cents": prod.price_cents,
        "image_url": prod.image_url,
        "created_at": getattr(prod, "created_at", None),
        "updated_at": getattr(prod, "updated_at", None),
    }


# =====================================================
# Main ingest
# =====================================================
def ingest_products(
    rebuild: bool = True,
    max_products: Optional[int] = None,
    target_tokens: int = 450,
    overlap_tokens: int = 60,
    embed_model: str = "BAAI/bge-m3",     # default local model
    provider: str = "local",              # 'local' | 'openai'
) -> Tuple[int, int]:
    """
    Returns: (num_products_processed, num_chunks_inserted)
    """
    db: Session = SessionLocal()

    # select embedder
    if provider == "local":
        embedder = LocalEmbedder(model_name=embed_model)
    elif provider == "openai":
        embedder = OpenAIEmbedder(model=embed_model)
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'local' or 'openai'.")

    try:
        # Pull products
        q = db.query(Product).order_by(Product.id.asc())
        if max_products:
            q = q.limit(max_products)
        products = q.all()

        total_chunks = 0
        processed = 0

        for prod in products:
            base_text = build_product_text(prod)
            if not base_text.strip():
                continue

            chunks = split_into_chunks(
                base_text,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
                model_hint=embed_model,       # used only for token estimation
            )
            if not chunks:
                continue

            # (re)build mode: remove previous docs for this product
            if rebuild:
                purge_product_docs(db, prod.id)
                db.commit()

            # Embed chunks
            embeddings = embedder.embed_batch(chunks)

            # Prepare rows
            meta = product_metadata(prod)
            rows = []
            for content, emb in zip(chunks, embeddings):
                rows.append({
                    "source": "product",
                    "product_id": prod.id,
                    "title": prod.name,
                    "content": content,
                    # NOTE: default=_json_default fixes datetime serialization
                    "metadata": json.dumps(meta, default=_json_default),
                    "embedding": emb
                })

            insert_docs(db, rows)
            db.commit()

            processed += 1
            total_chunks += len(rows)

            print(f"[OK] product_id={prod.id} name='{prod.name}' chunks={len(rows)}")

        return processed, total_chunks

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest Products into admin_documents (pgvector).")
    parser.add_argument("--no-rebuild", action="store_true", help="Do not purge existing product chunks; append only.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of products processed.")
    parser.add_argument("--target", type=int, default=450, help="Target tokens per chunk.")
    parser.add_argument("--overlap", type=int, default=60, help="Overlap tokens per chunk.")
    parser.add_argument("--model", type=str, default="BAAI/bge-m3",
                        help="Embedding model id (local or provider-specific).")
    parser.add_argument("--provider", type=str, default="local", choices=["local", "openai"],
                        help="Embedding provider: 'local' (default) or 'openai'.")
    args = parser.parse_args()

    rebuild = not args.no_rebuild
    processed, chunks = ingest_products(
        rebuild=rebuild,
        max_products=args.limit,
        target_tokens=args.target,
        overlap_tokens=args.overlap,
        embed_model=args.model,
        provider=args.provider,
    )
    print(f"\nDone. products={processed}, chunks_inserted={chunks}")


if __name__ == "__main__":
    main()
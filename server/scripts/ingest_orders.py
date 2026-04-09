#!/usr/bin/env python3
"""
Ingest Orders into admin_documents (pgvector) for admin search (PII-safe).

- Reads orders & items from the DB
- Builds a concise non‑PII summary per order
- Embeds with local Sentence Transformers (BAAI/bge-m3, 1024 dims)
- Inserts a single chunk/row per order into admin_documents with source='order'

Usage (macOS):
  cd server
  source .venv/bin/activate
  pip install "sentence-transformers>=3.0.0"
  # (optional for macOS CPU) pip install torch --extra-index-url https://download.pytorch.org/whl/cpu

  # First smoke test
  python scripts/ingest_orders.py --limit 50

  # Full ingest (rebuild = delete & reinsert)
  python scripts/ingest_orders.py

Notes:
- PII guard: we do NOT index email/phone/address/payment tokens. Only order_id, status,
  total_cents, user_id, product names & quantities, and updated_at.
- admin_documents.embedding must be vector(1024) (BGE-M3) and HNSW index created already.
"""

import os
import sys
import json
import argparse
from typing import List, Dict, Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text, MetaData, Table
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models import Order, OrderItem, Product

# -----------------------------
# Local embeddings: BAAI/bge-m3 (1024 dims)
# -----------------------------
class LocalEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "Install sentence-transformers to use LocalEmbedder: pip install sentence-transformers"
            ) from e

        # Try Apple Silicon MPS if available, else CPU
        device = "cpu"
        try:
            import torch
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
        except Exception:
            pass

        self.model = SentenceTransformer(model_name, device=device)

    def embed(self, text: str) -> List[float]:
        vec = self.model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
        return vec.tolist()

# -----------------------------
# Reflect admin_documents (insert via explicit CAST)
# -----------------------------
metadata = MetaData()
admin_documents = Table("admin_documents", metadata, autoload_with=engine)

def _embedding_to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

def insert_doc(db: Session, row: Dict):
    sql = text("""
        INSERT INTO admin_documents
            (source, product_id, title, content, metadata, embedding)
        VALUES
            (:source, :product_id, :title, :content,
             CAST(:metadata AS jsonb), CAST(:embedding AS vector))
    """)
    # Convert embedding list -> pgvector literal
    emb = row.get("embedding")
    if isinstance(emb, list):
        row["embedding"] = _embedding_to_vector_literal(emb)
    db.execute(sql, row)

def purge_order_doc(db: Session, order_id: int):
    # Delete existing rows for this order (source='order'), matched via metadata->>'order_id'
    sql = text("""
        DELETE FROM admin_documents
         WHERE source='order'
           AND (metadata ? 'order_id')
           AND ((metadata->>'order_id')::int = :oid)
    """)
    db.execute(sql, {"oid": order_id})

# -----------------------------
# Build non‑PII order summary
# -----------------------------
def _status_str(st) -> str:
    try:
        return st.name if hasattr(st, "name") else str(st)
    except Exception:
        return str(st)

def build_order_summary(db: Session, order: Order) -> Dict[str, str]:
    """
    Return (title, content, metadata_json) for the order (no PII).
    """
    # Title
    title = f"Order #{order.id}"

    # Items — names + quantities; use relationship if present, else fetch
    item_lines: List[str] = []
    for it in (order.items or []):
        qty = it.quantity or 0
        p_name = None
        try:
            if getattr(it, "product", None):
                p_name = it.product.name
            else:
                p = db.query(Product).filter(Product.id == it.product_id).first()
                p_name = p.name if p else f"Product {it.product_id}"
        except Exception:
            p_name = f"Product {it.product_id}"
        item_lines.append(f"- {p_name} x{qty}")

    # Totals & status
    status = _status_str(getattr(order, "status", "UNKNOWN"))
    total_cents = getattr(order, "total_amount_cents", None)
    total_str = f"₹{(total_cents or 0)/100:.2f}" if total_cents is not None else "N/A"
    user_id = getattr(order, "user_id", None)

    # Compose content (single chunk)
    lines = []
    lines.append(f"Order #{order.id} • Status: {status} • Total: {total_str}")
    if user_id is not None:
        lines.append(f"User ID: {user_id}")
    if item_lines:
        lines.append("Items:")
        lines.extend(item_lines)
    content = "\n".join(lines)

    # Metadata (no PII)
    meta = {
        "order_id": order.id,
        "status": status,
        "total_cents": total_cents,
        "user_id": user_id,
        "updated_at": str(getattr(order, "updated_at", "") or "")
    }

    return {"title": title, "content": content, "metadata_json": json.dumps(meta)}

# -----------------------------
# Main ingest
# -----------------------------
def ingest_orders(
    limit: Optional[int] = None,
    rebuild: bool = True,
    model_name: str = "BAAI/bge-m3"
) -> int:
    """
    Insert one row per order into admin_documents with source='order'.
    Returns the count of orders processed.
    """
    db: Session = SessionLocal()
    embedder = LocalEmbedder(model_name=model_name)
    processed = 0
    try:
        q = db.query(Order).order_by(Order.id.asc())
        if limit:
            q = q.limit(limit)
        orders = q.all()

        for order in orders:
            summary = build_order_summary(db, order)

            if rebuild:
                purge_order_doc(db, order.id)
                db.commit()

            emb = embedder.embed(summary["content"])
            row = {
                "source": "order",
                "product_id": None,
                "title": summary["title"],
                "content": summary["content"],
                "metadata": summary["metadata_json"],
                "embedding": emb
            }
            insert_doc(db, row)
            db.commit()
            processed += 1
            print(f"[OK] order_id={order.id} status={getattr(order, 'status', '')} row=1")

        return processed
    finally:
        db.close()

def main():
    ap = argparse.ArgumentParser(description="Ingest Orders into admin_documents (pgvector, PII-safe).")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of orders processed.")
    ap.add_argument("--no-rebuild", action="store_true", help="Append only; do not delete existing order rows.")
    ap.add_argument("--model", type=str, default="BAAI/bge-m3", help="Local embedding model id.")
    args = ap.parse_args()

    cnt = ingest_orders(limit=args.limit, rebuild=(not args.no_rebuild), model_name=args.model)
    print(f"\nDone. orders_processed={cnt}")

if __name__ == "__main__":
    main()

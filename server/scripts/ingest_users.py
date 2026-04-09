#!/usr/bin/env python3
"""
Ingest Users into admin_documents (pgvector) for admin search (PII-safe).

- Creates one row per user (no email/phone/addresses)
- Local embeddings (BAAI/bge-m3, 1024 dims)
- Inserts with explicit CAST(:embedding AS vector)

Usage:
  cd server
  source .venv/bin/activate
  pip install "sentence-transformers>=3.0.0"
  # (optional, macOS CPU) pip install torch --extra-index-url https://download.pytorch.org/whl/cpu

  # Smoke test
  python scripts/ingest_users.py --limit 50

  # Full ingest (rebuild = delete & reinsert)
  python scripts/ingest_users.py
"""

import os, sys, json, argparse
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text, MetaData, Table
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models import User, UserRole  # if role enum exists in your models

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
# Reflect admin_documents
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
    if isinstance(row.get("embedding"), list):
        row["embedding"] = _embedding_to_vector_literal(row["embedding"])
    db.execute(sql, row)

def purge_user_doc(db: Session, user_id: int):
    sql = text("""
        DELETE FROM admin_documents
         WHERE source='user'
           AND (metadata ? 'user_id')
           AND ((metadata->>'user_id')::int = :uid)
    """)
    db.execute(sql, {"uid": user_id})

# -----------------------------
# Build minimal user card (no PII)
# -----------------------------
def _role_str(role_val) -> str:
    try:
        # enum -> name, else string
        return getattr(role_val, "name", str(role_val))
    except Exception:
        return str(role_val)

def build_user_card(u: User) -> Dict[str, str]:
    title = f"User #{u.id}"
    role = _role_str(getattr(u, "role", "user"))
    name = getattr(u, "name", "") or "(no name)"
    lines = [
        f"User #{u.id} — Name: {name}",
        f"Role: {role}",
    ]
    content = "\n".join(lines)

    meta = {
        "user_id": u.id,
        "role": role,
        "updated_at": str(getattr(u, "updated_at", "") or "")
    }
    return {"title": title, "content": content, "metadata_json": json.dumps(meta)}

# -----------------------------
# Main ingest
# -----------------------------
def ingest_users(limit: Optional[int] = None, rebuild: bool = True, model_name: str = "BAAI/bge-m3") -> int:
    db: Session = SessionLocal()
    embedder = LocalEmbedder(model_name=model_name)
    processed = 0
    try:
        q = db.query(User).order_by(User.id.asc())
        if limit:
            q = q.limit(limit)
        users = q.all()

        for u in users:
            card = build_user_card(u)

            if rebuild:
                purge_user_doc(db, u.id)
                db.commit()

            emb = embedder.embed(card["content"])
            row = {
                "source": "user",
                "product_id": None,
                "title": card["title"],
                "content": card["content"],
                "metadata": card["metadata_json"],
                "embedding": emb
            }
            insert_doc(db, row)
            db.commit()
            processed += 1
            print(f"[OK] user_id={u.id} name='{getattr(u, 'name', '')}' row=1")

        return processed
    finally:
        db.close()

def main():
    ap = argparse.ArgumentParser(description="Ingest Users into admin_documents (pgvector, PII-safe).")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of users processed.")
    ap.add_argument("--no-rebuild", action="store_true", help="Append only; do not delete existing user rows.")
    ap.add_argument("--model", type=str, default="BAAI/bge-m3", help="Local embedding model id.")
    args = ap.parse_args()

    cnt = ingest_users(limit=args.limit, rebuild=(not args.no_rebuild), model_name=args.model)
    print(f"\nDone. users_processed={cnt}")

if __name__ == "__main__":
    main()

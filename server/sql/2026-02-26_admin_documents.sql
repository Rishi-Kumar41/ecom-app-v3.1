-- server/sql/2026-02-26_admin_documents.sql
-- Enable pgvector (one-time per database)
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table for admin search (products, policies, etc.)
-- NOTE: embedding dimension must match the embedding model you choose.
-- 1536 = OpenAI text-embedding-3-small/large. Adjust if you change models.  ──>  cite
-- Fields:
--   source       : 'product' | 'policy' (use a simple text check now; can convert to ENUM later)
--   product_id   : int (nullable; set for product chunks)
--   title        : short label for UI
--   content      : the chunk text we search over (required)
--   metadata     : jsonb for extra facets (category, price, updated_at, etc.)
--   embedding    : pgvector column
--   tsv          : generated tsvector for full-text (BM25-ish) hybrid
CREATE TABLE IF NOT EXISTS admin_documents (
  id           bigserial PRIMARY KEY,
  source       text NOT NULL CHECK (source IN ('product','policy')),
  product_id   integer NULL,
  title        text NULL,
  content      text NOT NULL,
  metadata     jsonb NULL,
  embedding    vector(1536),  -- adjust dimension if you pick a different embedder
  tsv          tsvector GENERATED ALWAYS AS (
                 to_tsvector('english', coalesce(title,'') || ' ' || content)
               ) STORED,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Basic filters for fast lookups (optional but useful in practice)
CREATE INDEX IF NOT EXISTS admin_documents_source_idx    ON admin_documents (source);
CREATE INDEX IF NOT EXISTS admin_documents_product_idx   ON admin_documents (product_id);

-- Full-text (BM25-like) index for hybrid queries
CREATE INDEX IF NOT EXISTS admin_documents_tsv_gin_idx   ON admin_documents USING GIN (tsv);

-- HNSW ANN index on the embedding (vector_cosine_ops is a common choice for semantic search)
-- You can use vector_l2_ops for L2 distance or vector_ip_ops for inner product, depending on the embedder.  ──>  cite
CREATE INDEX IF NOT EXISTS admin_documents_embedding_hnsw_idx
ON admin_documents
USING hnsw (embedding vector_cosine_ops);

-- Optional trigger to maintain updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

DROP TRIGGER IF EXISTS trg_admin_documents_updated ON admin_documents;
CREATE TRIGGER trg_admin_documents_updated
BEFORE UPDATE ON admin_documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
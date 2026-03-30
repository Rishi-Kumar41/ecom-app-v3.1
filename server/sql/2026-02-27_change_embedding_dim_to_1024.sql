-- server/sql/2026-02-27_change_embedding_dim_to_1024.sql

-- 1) Drop vector index (required before altering the vector dimension)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND indexname = 'admin_documents_embedding_hnsw_idx'
  ) THEN
    EXECUTE 'DROP INDEX admin_documents_embedding_hnsw_idx';
  END IF;
END $$;

-- 2) Alter column to 1024 dims (bge-m3 output size)
ALTER TABLE admin_documents
  ALTER COLUMN embedding TYPE vector(1024);

-- 3) Recreate HNSW index (cosine distance)
CREATE INDEX admin_documents_embedding_hnsw_idx
ON admin_documents
USING hnsw (embedding vector_cosine_ops);
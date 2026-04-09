-- server/sql/2026-03-31_extend_sources.sql
-- Make source accept: 'product','policy','order','user'

BEGIN;

ALTER TABLE admin_documents
  DROP CONSTRAINT IF EXISTS admin_documents_source_check;

ALTER TABLE admin_documents
  ADD CONSTRAINT admin_documents_source_check
  CHECK (source IN ('product','policy','order','user'));

COMMIT;

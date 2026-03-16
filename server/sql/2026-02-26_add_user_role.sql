-- server/sql/2026-02-26_add_user_role.sql

-- 1) Create enum type if it doesn't already exist
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
    CREATE TYPE user_role AS ENUM ('user', 'admin');
  END IF;
END $$;

-- 2) Add column `role` on users (default 'user'), if missing
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS role user_role;

-- 3) Ensure a default at the DB level (future inserts)
ALTER TABLE users
  ALTER COLUMN role SET DEFAULT 'user';

-- 4) Backfill existing NULLs
UPDATE users
SET role = 'user'
WHERE role IS NULL;

-- 5) Enforce NOT NULL
ALTER TABLE users
  ALTER COLUMN role SET NOT NULL;

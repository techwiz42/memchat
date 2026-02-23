-- Google OAuth 2.0 support: allow password-less users, add Google profile fields
-- Run: docker compose exec postgres psql -U memchat -d memchat -f /dev/stdin < migrations/002_google_oauth.sql

ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(512);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id) WHERE google_id IS NOT NULL;

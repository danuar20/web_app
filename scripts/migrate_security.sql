-- =============================================================================
-- Security Hardening Migration
-- Database: webapp_db
-- Run once. All statements are idempotent (safe to re-run).
-- =============================================================================

-- ── 1. ALTER TABLE users — add security columns ───────────────────────────────

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role            VARCHAR(20)                      NOT NULL DEFAULT 'viewer',
    ADD COLUMN IF NOT EXISTS is_active       BOOLEAN                          NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS failed_attempts INTEGER                          NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until    TIMESTAMP WITH TIME ZONE         NULL,
    ADD COLUMN IF NOT EXISTS max_session     INTEGER                          NOT NULL DEFAULT 5;

-- Ensure existing users (created before migration) get sensible defaults.
-- First user created with create_user.py is typically the admin; update manually if needed.
-- Example: UPDATE users SET role = 'admin' WHERE username = 'your_admin_username';

-- ── 2. CREATE TABLE user_sessions ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Random token sent to browser
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ip_address   VARCHAR(45)                      NOT NULL,   -- Supports IPv4 and IPv6
    user_agent   TEXT                             NOT NULL,   -- e.g. Chrome, Edge, etc.
    created_at   TIMESTAMP WITH TIME ZONE         DEFAULT CURRENT_TIMESTAMP,
    expires_at   TIMESTAMP WITH TIME ZONE         NOT NULL
);

-- ── 3. CREATE TABLE login_logs ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS login_logs (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(50)                      NOT NULL,
    ip_address   VARCHAR(45)                      NOT NULL,
    user_agent   TEXT                             NOT NULL,
    status       VARCHAR(20)                      NOT NULL,   -- 'SUCCESS', 'FAILED_PASSWORD', 'LOCKED', 'INACTIVE'
    attempted_at TIMESTAMP WITH TIME ZONE         DEFAULT CURRENT_TIMESTAMP
);

-- ── 4. Indexes for query performance ─────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id    ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_login_logs_username      ON login_logs(username);
CREATE INDEX IF NOT EXISTS idx_login_logs_attempted_at  ON login_logs(attempted_at);

-- =============================================================================
-- Done. Verify with:
--   \d users
--   \d user_sessions
--   \d login_logs
-- =============================================================================

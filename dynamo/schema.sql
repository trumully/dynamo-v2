PRAGMA foreign_keys = ON;
PRAGMA journal_mode = 'wal';
PRAGMA synchronous = 'NORMAL';

CREATE TABLE IF NOT EXISTS discord_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE,
    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_tags (
    user_id INTEGER NOT NULL REFERENCES discord_users (user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, tag_name)
) STRICT, WITHOUT ROWID;
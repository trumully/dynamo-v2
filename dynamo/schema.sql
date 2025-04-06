PRAGMA foreign_keys = ON;
PRAGMA journal_mode = 'wal';
PRAGMA synchronous = 'NORMAL';

CREATE TABLE IF NOT EXISTS discord_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE,
    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT, WITHOUT ROWID;
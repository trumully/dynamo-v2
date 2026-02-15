PRAGMA foreign_keys = ON;
PRAGMA journal_mode = 'wal';
PRAGMA synchronous = 'NORMAL';

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE,
    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS guilds (
    guild_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE   
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS guild_archive_category (
    guild_id INTEGER PRIMARY KEY NOT NULL REFERENCES guilds(guild_id) ON UPDATE CASCADE ON DELETE CASCADE,
    category_id INTEGER NOT NULL
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS identicons (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    seed TEXT NOT NULL,
    PRIMARY KEY (user_id, seed)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER IF NOT EXISTS identicon_cap BEFORE INSERT ON identicons BEGIN
SELECT
    CASE WHEN (
        SELECT
            COUNT(1) >= 25
        FROM
            identicons
        WHERE
            user_id = new.user_id
    ) THEN RAISE(ABORT, 'too many identicons') END;
END;
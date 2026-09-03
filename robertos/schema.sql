-- Robert-OS Datenbankstruktur.
-- Jede Tabelle hat eine eigene, unveraenderliche id als Primaerschluessel.
-- Zeilennummern werden NIRGENDS als Identitaet benutzt.

CREATE TABLE IF NOT EXISTS current_states (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT    NOT NULL,
    UNIQUE (agent, key)
);

CREATE TABLE IF NOT EXISTS state_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT    NOT NULL,
    snapshot    TEXT    NOT NULL,
    changed_at  TEXT    NOT NULL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_state_history_agent
    ON state_history (agent, changed_at);

CREATE TABLE IF NOT EXISTS handoffs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_agent  TEXT    NOT NULL,
    target_agent  TEXT    NOT NULL,
    thread_key    TEXT,
    type          TEXT,
    status        TEXT    NOT NULL DEFAULT 'open',
    facts         TEXT,
    decision      TEXT,
    next_step     TEXT,
    created_at    TEXT    NOT NULL,
    processed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_handoffs_target
    ON handoffs (target_agent, status);

CREATE TABLE IF NOT EXISTS checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE (agent, date)
);

CREATE TABLE IF NOT EXISTS metrics_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT    NOT NULL,
    metric     TEXT    NOT NULL,
    value      REAL    NOT NULL,
    note       TEXT,
    timestamp  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_agent
    ON metrics_log (agent, metric, timestamp);

CREATE TABLE IF NOT EXISTS goals_projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open',
    due         TEXT,
    detail      TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE (agent, title)
);

CREATE TABLE IF NOT EXISTS execution_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    result     TEXT    NOT NULL,
    detail     TEXT,
    timestamp  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_log_time
    ON execution_log (timestamp);

-- Nachrichten, die Robert selbst per Telegram an das System schickt.
CREATE TABLE IF NOT EXISTS inbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    consumed_at  TEXT
);

-- Interne Merkzettel des Systems (z.B. bis wohin Telegram gelesen wurde).
CREATE TABLE IF NOT EXISTS kv (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

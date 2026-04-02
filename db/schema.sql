-- Second Brain AI — Database Schema
-- Version: 10

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA journal_size_limit = 67108864;  -- 64MB

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    description TEXT
);

-- Core items table: every ingested piece of content
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,  -- SHA-256 of file content
    title           TEXT NOT NULL,
    content_type    TEXT NOT NULL,     -- MIME type
    content_text    TEXT,              -- extracted text content
    file_extension  TEXT,
    file_size       INTEGER NOT NULL,
    source_path     TEXT,              -- original path in Team Inbox
    stored_path     TEXT,              -- path after processing (processed/)
    domain          TEXT DEFAULT NULL,     -- primary domain: fitness, finance, wellness, productivity, learning, daily, personal
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'quarantined')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Tags table with canonical normalization
CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,  -- lowercase, stripped
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Junction table: many-to-many items <-> tags
CREATE TABLE IF NOT EXISTS item_tags (
    item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (item_id, tag_id)
);

-- Source file metadata
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    original_path   TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    mime_type       TEXT,
    file_hash       TEXT NOT NULL,     -- SHA-256
    file_size       INTEGER NOT NULL,
    metadata_json   TEXT,              -- EXIF, frontmatter, etc. as JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Processing log: tracks every pipeline operation
CREATE TABLE IF NOT EXISTS processing_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT REFERENCES items(id) ON DELETE SET NULL,
    file_path   TEXT NOT NULL,
    action      TEXT NOT NULL,         -- 'ingested', 'quarantined', 'skipped', 'duplicate', 'error'
    stage       TEXT,                  -- 'extract', 'classify', 'store', 'move'
    message     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title,
    content_text,
    content='items',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync with items table
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, content_text)
    VALUES (new.rowid, new.title, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, content_text)
    VALUES ('delete', old.rowid, old.title, old.content_text);
END;

CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, content_text)
    VALUES ('delete', old.rowid, old.title, old.content_text);
    INSERT INTO items_fts(rowid, title, content_text)
    VALUES (new.rowid, new.title, new.content_text);
END;

-- Trigger to auto-update updated_at on items
CREATE TRIGGER IF NOT EXISTS items_updated_at AFTER UPDATE ON items BEGIN
    UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = new.id;
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_items_content_type ON items(content_type);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_item_tags_tag_id ON item_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_sources_item_id ON sources(item_id);
CREATE INDEX IF NOT EXISTS idx_sources_file_hash ON sources(file_hash);
CREATE INDEX IF NOT EXISTS idx_processing_log_item_id ON processing_log(item_id);
CREATE INDEX IF NOT EXISTS idx_processing_log_action ON processing_log(action);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

-- ============================================================
-- Domain Column Index (v3)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_items_domain ON items(domain);

-- ============================================================
-- Financial Snapshots (v3)
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,           -- ISO date YYYY-MM-DD
    period          TEXT NOT NULL DEFAULT 'daily'
                    CHECK (period IN ('daily', 'weekly', 'monthly')),
    total_balance   REAL,                    -- sum of all wallets
    total_expenses  REAL,                    -- expenses in this period
    total_income    REAL,                    -- income in this period
    savings_rate    REAL,                    -- (income - expenses) / income
    top_categories  TEXT,                    -- JSON: [{"name": "Food", "amount": 1234.56}, ...]
    wallet_balances TEXT,                    -- JSON: [{"name": "BDO", "balance": 5000}, ...]
    debt_total      REAL,                    -- total outstanding debt
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(snapshot_date, period)
);

CREATE INDEX IF NOT EXISTS idx_financial_snapshots_date ON financial_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_financial_snapshots_period ON financial_snapshots(period);

CREATE TRIGGER IF NOT EXISTS financial_snapshots_updated_at
    AFTER UPDATE ON financial_snapshots BEGIN
    UPDATE financial_snapshots
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.id;
END;

-- ============================================================
-- Wellness Snapshots (v3)
-- ============================================================

CREATE TABLE IF NOT EXISTS wellness_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,           -- ISO date YYYY-MM-DD
    mood_score      INTEGER,                 -- 1-10 scale
    sleep_hours     REAL,                    -- hours slept
    energy_level    INTEGER,                 -- 1-10 scale
    sleep_quality   TEXT,                    -- 'poor', 'fair', 'good', 'great'
    diary_summary   TEXT,                    -- 2-3 sentence extracted summary
    gratitude       TEXT,                    -- JSON array of gratitude items
    tags            TEXT,                    -- JSON array: ["low-energy", "good-sleep", ...]
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_wellness_snapshots_date ON wellness_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wellness_snapshots_mood ON wellness_snapshots(mood_score);

CREATE TRIGGER IF NOT EXISTS wellness_snapshots_updated_at
    AFTER UPDATE ON wellness_snapshots BEGIN
    UPDATE wellness_snapshots
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.id;
END;

-- ============================================================
-- Daily Briefings Index (v3)
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_briefings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_date   TEXT NOT NULL UNIQUE,    -- ISO date YYYY-MM-DD
    file_path       TEXT NOT NULL,           -- path to the HTML file
    sections        TEXT,                    -- JSON: which sections were included
    highlights      TEXT,                    -- 2-3 sentence summary of key points
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_daily_briefings_date ON daily_briefings(briefing_date);

-- ============================================================
-- Productivity Cache (v4) — Gawin MCP display cache
-- ============================================================

CREATE TABLE IF NOT EXISTS productivity_cache (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    tasks_json      TEXT,                    -- JSON: full task list from Gawin
    projects_json   TEXT,                    -- JSON: full project list from Gawin
    stats_json      TEXT,                    -- JSON: {tasks_due_today, overdue_tasks, completed_this_week, active_projects}
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================
-- Calendar Cache (v4) — Google Calendar MCP display cache
-- ============================================================

CREATE TABLE IF NOT EXISTS calendar_cache (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    events_json     TEXT,                    -- JSON: event list from Google Calendar
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================
-- Calendar Event Intents (v4) — queued create/update requests
-- ============================================================

CREATE TABLE IF NOT EXISTS calendar_event_intents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_type     TEXT NOT NULL CHECK (intent_type IN ('create', 'update', 'delete')),
    payload_json    TEXT NOT NULL,           -- JSON: event data for the agent to execute
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'failed')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    executed_at     TEXT
);

-- ============================================================
-- Memory System (v5) — Agent memories, lessons, session logs
-- ============================================================

-- Agent memories: preferences, observations, patterns, context
CREATE TABLE IF NOT EXISTS agent_memories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name          TEXT NOT NULL,
    category            TEXT NOT NULL CHECK (category IN ('preference', 'observation', 'pattern', 'context')),
    memory_type         TEXT NOT NULL DEFAULT 'user'
                        CHECK (memory_type IN ('user', 'feedback', 'project', 'reference')),
    content             TEXT NOT NULL,
    content_hash        TEXT,                       -- SHA-256 of agent_name+content for dedup
    reinforcement_count INTEGER NOT NULL DEFAULT 1, -- how many times this fact was re-confirmed
    relevance_tags      TEXT,                       -- JSON array
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at          TEXT DEFAULT NULL,
    UNIQUE(agent_name, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_name ON agent_memories(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_memories_category ON agent_memories(category);
CREATE INDEX IF NOT EXISTS idx_agent_memories_memory_type ON agent_memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_agent_memories_created_at ON agent_memories(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_memories_content_hash ON agent_memories(content_hash);

CREATE TRIGGER IF NOT EXISTS agent_memories_updated_at AFTER UPDATE ON agent_memories BEGIN
    UPDATE agent_memories SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = new.id;
END;

-- Agent lessons: what worked, what didn't, confidence tracking
CREATE TABLE IF NOT EXISTS agent_lessons (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name        TEXT NOT NULL,
    tool_name         TEXT,
    context           TEXT NOT NULL,
    action_taken      TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    correction        TEXT,
    confidence_score  REAL DEFAULT 0.5 CHECK (confidence_score BETWEEN 0.0 AND 1.0),
    tags              TEXT,                  -- JSON array
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_lessons_agent_name ON agent_lessons(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_lessons_tool_name ON agent_lessons(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_lessons_outcome ON agent_lessons(outcome);
CREATE INDEX IF NOT EXISTS idx_agent_lessons_confidence ON agent_lessons(confidence_score);

CREATE TRIGGER IF NOT EXISTS agent_lessons_updated_at AFTER UPDATE ON agent_lessons BEGIN
    UPDATE agent_lessons SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = new.id;
END;

-- Session logs: track delegated tasks across agent sessions
CREATE TABLE IF NOT EXISTS session_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    task_description TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'delegated'
                    CHECK (status IN ('delegated', 'in_progress', 'completed', 'failed', 'pending')),
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at    TEXT DEFAULT NULL,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_logs_session_id ON session_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_session_logs_agent_name ON session_logs(agent_name);
CREATE INDEX IF NOT EXISTS idx_session_logs_status ON session_logs(status);
CREATE INDEX IF NOT EXISTS idx_session_logs_started_at ON session_logs(started_at);

-- Session summaries: structured recap of each session
CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    request TEXT,          -- what Kenneth asked / the session goal
    investigated TEXT,     -- what was researched or explored
    learned TEXT,          -- key discoveries or insights
    completed TEXT,        -- deliverables produced
    next_steps TEXT,       -- follow-ups or open items
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_id ON session_summaries(session_id);

-- FTS5 for lesson content search
CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    context,
    action_taken,
    correction,
    content='agent_lessons',
    content_rowid='rowid'
);

-- Triggers to keep lessons_fts in sync with agent_lessons
CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON agent_lessons BEGIN
    INSERT INTO lessons_fts(rowid, context, action_taken, correction)
    VALUES (new.rowid, new.context, new.action_taken, new.correction);
END;

CREATE TRIGGER IF NOT EXISTS lessons_ad AFTER DELETE ON agent_lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, context, action_taken, correction)
    VALUES ('delete', old.rowid, old.context, old.action_taken, old.correction);
END;

CREATE TRIGGER IF NOT EXISTS lessons_au AFTER UPDATE ON agent_lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, context, action_taken, correction)
    VALUES ('delete', old.rowid, old.context, old.action_taken, old.correction);
    INSERT INTO lessons_fts(rowid, context, action_taken, correction)
    VALUES (new.rowid, new.context, new.action_taken, new.correction);
END;

-- FTS5 for memory content search
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='agent_memories',
    content_rowid='rowid'
);

-- Triggers to keep memories_fts in sync with agent_memories
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON agent_memories BEGIN
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON agent_memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON agent_memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

-- ============================================================
-- Embeddings Layer (v7) — Semantic search via local LLM embeddings
-- ============================================================

-- Stores vector embeddings for any content in the system.
-- source_table + source_id identify the origin record.
-- content_hash prevents re-embedding unchanged content.
CREATE TABLE IF NOT EXISTS embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table    TEXT NOT NULL,               -- e.g. 'wellness_snapshots', 'agent_memories'
    source_id       TEXT NOT NULL,               -- PK of the source row (cast to TEXT)
    content_hash    TEXT NOT NULL,               -- SHA-256 of the text that was embedded
    embedding       BLOB NOT NULL,              -- 768-dim float32 vector (3072 bytes)
    model_name      TEXT NOT NULL,               -- model used to generate the embedding
    dimensions      INTEGER NOT NULL DEFAULT 768,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(source_table, source_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_content_hash ON embeddings(content_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_name);

-- ============================================================
-- Obsidian Notes (v10) — Ingested markdown from Obsidian vaults
-- ============================================================

CREATE TABLE IF NOT EXISTS obsidian_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vault           TEXT NOT NULL,               -- vault name: Ideaverse, Obsidian, SecondBrain
    file_path       TEXT NOT NULL,               -- relative path within vault
    title           TEXT NOT NULL,               -- filename without .md
    content         TEXT,                        -- full markdown text
    tags            TEXT,                        -- JSON array of tags (frontmatter + inline)
    folder          TEXT,                        -- parent folder path within vault
    word_count      INTEGER DEFAULT 0,
    content_hash    TEXT NOT NULL,               -- SHA-256 of content for dedup
    frontmatter_json TEXT,                       -- JSON: parsed frontmatter metadata
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    file_modified_at TEXT,                       -- filesystem mtime
    UNIQUE(vault, file_path)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_notes_vault ON obsidian_notes(vault);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_folder ON obsidian_notes(folder);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_content_hash ON obsidian_notes(content_hash);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_title ON obsidian_notes(title);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_created_at ON obsidian_notes(created_at);

-- FTS5 for full-text search on Obsidian notes
CREATE VIRTUAL TABLE IF NOT EXISTS obsidian_notes_fts USING fts5(
    title,
    content,
    tags,
    content='obsidian_notes',
    content_rowid='rowid'
);

-- FTS sync triggers for obsidian_notes
CREATE TRIGGER IF NOT EXISTS obsidian_notes_fts_ai AFTER INSERT ON obsidian_notes BEGIN
    INSERT INTO obsidian_notes_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS obsidian_notes_fts_ad AFTER DELETE ON obsidian_notes BEGIN
    INSERT INTO obsidian_notes_fts(obsidian_notes_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS obsidian_notes_fts_au AFTER UPDATE ON obsidian_notes BEGIN
    INSERT INTO obsidian_notes_fts(obsidian_notes_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
    INSERT INTO obsidian_notes_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS obsidian_notes_updated_at AFTER UPDATE ON obsidian_notes BEGIN
    UPDATE obsidian_notes SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.id;
END;

-- ============================================================
-- Workspace File Review Status (v11) — Track new/reviewed for Owner's Inbox
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace_file_status (
    path        TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'reviewed')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

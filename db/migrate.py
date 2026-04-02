"""Schema migration runner for AI Team System database."""

import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).parent
PROJECT_ROOT = DB_DIR.parent
DB_PATH = DB_DIR / "brain.db"
SCHEMA_PATH = DB_DIR / "schema.sql"

CURRENT_VERSION = 10


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a database connection with proper PRAGMAs."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA journal_size_limit = 67108864")
    conn.row_factory = sqlite3.Row
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version, 0 if no schema exists."""
    try:
        row = conn.execute(
            "SELECT MAX(version) as v FROM schema_version"
        ).fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the full schema from schema.sql."""
    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (1, "Initial schema: items, tags, sources, processing_log, FTS5"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (3, "Domain column on items, financial_snapshots, wellness_snapshots, daily_briefings"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (4, "Productivity and calendar cache tables for MCP-mediated architecture"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (5, "Memory system: agent_memories, agent_lessons, session_logs, memories_fts"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (6, "Memory dedup: content_hash, reinforcement_count on agent_memories; lessons_fts"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (8, "Typed memory taxonomy: memory_type column (user, feedback, project, reference) on agent_memories"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (10, "Obsidian notes table: vault ingestion with FTS5 and dedup"),
    )
    conn.commit()


def migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add domain column, financial_snapshots, wellness_snapshots, daily_briefings."""
    v3_ddl = """
    ALTER TABLE items ADD COLUMN domain TEXT DEFAULT NULL;

    CREATE INDEX IF NOT EXISTS idx_items_domain ON items(domain);

    CREATE TABLE IF NOT EXISTS financial_snapshots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date   TEXT NOT NULL,
        period          TEXT NOT NULL DEFAULT 'daily'
                        CHECK (period IN ('daily', 'weekly', 'monthly')),
        total_balance   REAL,
        total_expenses  REAL,
        total_income    REAL,
        savings_rate    REAL,
        top_categories  TEXT,
        wallet_balances TEXT,
        debt_total      REAL,
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

    CREATE TABLE IF NOT EXISTS wellness_snapshots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date   TEXT NOT NULL,
        mood_score      INTEGER,
        sleep_hours     REAL,
        energy_level    INTEGER,
        sleep_quality   TEXT,
        diary_summary   TEXT,
        gratitude       TEXT,
        tags            TEXT,
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

    CREATE TABLE IF NOT EXISTS daily_briefings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        briefing_date   TEXT NOT NULL UNIQUE,
        file_path       TEXT NOT NULL,
        sections        TEXT,
        highlights      TEXT,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE INDEX IF NOT EXISTS idx_daily_briefings_date ON daily_briefings(briefing_date);
    """
    conn.executescript(v3_ddl)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (3, "Domain column on items, financial_snapshots, wellness_snapshots, daily_briefings"),
    )
    conn.commit()


def migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add productivity_cache, calendar_cache, calendar_event_intents tables."""
    v4_ddl = """
    CREATE TABLE IF NOT EXISTS productivity_cache (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        tasks_json      TEXT,
        projects_json   TEXT,
        stats_json      TEXT,
        synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE IF NOT EXISTS calendar_cache (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        events_json     TEXT,
        synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE IF NOT EXISTS calendar_event_intents (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        intent_type     TEXT NOT NULL CHECK (intent_type IN ('create', 'update', 'delete')),
        payload_json    TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'failed')),
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        executed_at     TEXT
    );
    """
    conn.executescript(v4_ddl)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (4, "Productivity and calendar cache tables for MCP-mediated architecture"),
    )
    conn.commit()


def migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Add agent_memories, agent_lessons, session_logs, memories_fts tables."""
    v5_ddl = """
    CREATE TABLE IF NOT EXISTS agent_memories (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_name      TEXT NOT NULL,
        category        TEXT NOT NULL CHECK (category IN ('preference', 'observation', 'pattern', 'context')),
        content         TEXT NOT NULL,
        relevance_tags  TEXT,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        expires_at      TEXT DEFAULT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_name ON agent_memories(agent_name);
    CREATE INDEX IF NOT EXISTS idx_agent_memories_category ON agent_memories(category);
    CREATE INDEX IF NOT EXISTS idx_agent_memories_created_at ON agent_memories(created_at);

    CREATE TRIGGER IF NOT EXISTS agent_memories_updated_at AFTER UPDATE ON agent_memories BEGIN
        UPDATE agent_memories SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = new.id;
    END;

    CREATE TABLE IF NOT EXISTS agent_lessons (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_name        TEXT NOT NULL,
        tool_name         TEXT,
        context           TEXT NOT NULL,
        action_taken      TEXT NOT NULL,
        outcome           TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
        correction        TEXT,
        confidence_score  REAL DEFAULT 0.5 CHECK (confidence_score BETWEEN 0.0 AND 1.0),
        tags              TEXT,
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
    """
    conn.executescript(v5_ddl)

    # FTS5 and sync triggers must be created outside executescript
    # because CREATE VIRTUAL TABLE can conflict with executescript batching
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            content='agent_memories',
            content_rowid='rowid'
        )
    """)

    conn.executescript("""
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
    """)

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (5, "Memory system: agent_memories, agent_lessons, session_logs, memories_fts"),
    )
    conn.commit()


def migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Add content_hash, reinforcement_count to agent_memories; add lessons_fts."""
    # Add new columns (ALTER TABLE ADD COLUMN is safe -- no-op if already exists not supported,
    # so we catch the error)
    for stmt in [
        "ALTER TABLE agent_memories ADD COLUMN content_hash TEXT",
        "ALTER TABLE agent_memories ADD COLUMN reinforcement_count INTEGER NOT NULL DEFAULT 1",
    ]:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Create index on content_hash
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memories_content_hash ON agent_memories(content_hash)")

    # Create unique index for deduplication (agent_name + content_hash)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_memories_dedup ON agent_memories(agent_name, content_hash)"
    )

    # Backfill content_hash for any existing rows
    import hashlib
    rows = conn.execute("SELECT id, agent_name, content FROM agent_memories WHERE content_hash IS NULL").fetchall()
    for row in rows:
        h = hashlib.sha256((row["agent_name"] + row["content"]).encode()).hexdigest()
        conn.execute("UPDATE agent_memories SET content_hash = ? WHERE id = ?", (h, row["id"]))

    # Create lessons_fts virtual table
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
            context,
            action_taken,
            correction,
            content='agent_lessons',
            content_rowid='rowid'
        )
    """)

    # Create sync triggers for lessons_fts
    conn.executescript("""
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
    """)

    # Backfill lessons_fts for any existing lessons
    conn.execute("""
        INSERT OR IGNORE INTO lessons_fts(rowid, context, action_taken, correction)
        SELECT rowid, context, action_taken, correction FROM agent_lessons
    """)

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (6, "Memory dedup: content_hash, reinforcement_count on agent_memories; lessons_fts"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (7, "Embeddings table for semantic search via local LLM embeddings"),
    )
    conn.commit()


def migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Add memory_type column to agent_memories for typed memory taxonomy."""
    # Add memory_type column (default 'user' for backwards compatibility)
    try:
        conn.execute(
            "ALTER TABLE agent_memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'user'"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create index on memory_type
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_memories_memory_type ON agent_memories(memory_type)"
    )

    # Backfill: all existing memories default to 'user'
    conn.execute(
        "UPDATE agent_memories SET memory_type = 'user' WHERE memory_type IS NULL"
    )

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (8, "Typed memory taxonomy: memory_type column (user, feedback, project, reference) on agent_memories"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (9, "Anime list table: MAL tracking data with genres, scores, status"),
    )
    conn.commit()


def migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Add embeddings table for semantic search via local LLM embeddings."""
    v7_ddl = """
    CREATE TABLE IF NOT EXISTS embeddings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_table    TEXT NOT NULL,
        source_id       TEXT NOT NULL,
        content_hash    TEXT NOT NULL,
        embedding       BLOB NOT NULL,
        model_name      TEXT NOT NULL,
        dimensions      INTEGER NOT NULL DEFAULT 768,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE(source_table, source_id, model_name)
    );

    CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_table, source_id);
    CREATE INDEX IF NOT EXISTS idx_embeddings_content_hash ON embeddings(content_hash);
    CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_name);
    """
    conn.executescript(v7_ddl)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (7, "Embeddings table for semantic search via local LLM embeddings"),
    )
    conn.commit()


def migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    """Add obsidian_notes table for ingested Obsidian vault markdown."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS obsidian_notes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vault           TEXT NOT NULL,
            file_path       TEXT NOT NULL,
            title           TEXT NOT NULL,
            content         TEXT,
            tags            TEXT,
            folder          TEXT,
            word_count      INTEGER DEFAULT 0,
            content_hash    TEXT NOT NULL,
            frontmatter_json TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            file_modified_at TEXT,
            UNIQUE(vault, file_path)
        );

        CREATE INDEX IF NOT EXISTS idx_obsidian_notes_vault ON obsidian_notes(vault);
        CREATE INDEX IF NOT EXISTS idx_obsidian_notes_folder ON obsidian_notes(folder);
        CREATE INDEX IF NOT EXISTS idx_obsidian_notes_content_hash ON obsidian_notes(content_hash);
        CREATE INDEX IF NOT EXISTS idx_obsidian_notes_title ON obsidian_notes(title);
        CREATE INDEX IF NOT EXISTS idx_obsidian_notes_created_at ON obsidian_notes(created_at);
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS obsidian_notes_fts USING fts5(
            title,
            content,
            tags,
            content='obsidian_notes',
            content_rowid='rowid'
        )
    """)

    conn.executescript("""
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
    """)

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (10, "Obsidian notes table: vault ingestion with FTS5 and dedup"),
    )
    conn.commit()


def migrate(db_path: Path | None = None) -> sqlite3.Connection:
    """Run migrations and return a ready connection."""
    conn = get_connection(db_path)
    current = get_schema_version(conn)

    if current == 0:
        print(f"Initializing database to v{CURRENT_VERSION}...")
        apply_schema(conn)
        print("Migration complete.")
    elif current < CURRENT_VERSION:
        print(f"Migrating database from v{current} to v{CURRENT_VERSION}...")
        if current < 3:
            migrate_v2_to_v3(conn)
        if current < 4:
            migrate_v3_to_v4(conn)
        if current < 5:
            migrate_v4_to_v5(conn)
        if current < 6:
            migrate_v5_to_v6(conn)
        if current < 7:
            migrate_v6_to_v7(conn)
        if current < 8:
            migrate_v7_to_v8(conn)
        if current < 10:
            migrate_v9_to_v10(conn)
        print("Migration complete.")
    else:
        print(f"Database already at v{current}. No migration needed.")

    return conn


def reset(db_path: Path | None = None) -> sqlite3.Connection:
    """Drop and recreate the database. Destructive."""
    path = db_path or DB_PATH
    if path.exists():
        path.unlink()
        print(f"Deleted {path}")
    return migrate(path)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset()
    else:
        migrate()

"""Obsidian Vault Ingestion Pipeline.

Walks configured Obsidian vaults, parses frontmatter and inline tags,
deduplicates by content hash, and upserts into the obsidian_notes table.

Configuration:
    Set vault paths in config/config.json:
    {
      "vault_paths": {
        "MyVault": "/path/to/your/obsidian/vault"
      }
    }

Usage:
    python3 db/pipeline/ingest_obsidian.py
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.migrate import get_connection, DB_PATH

# ---------------------------------------------------------------------------
# Configuration — load from config/config.json
# ---------------------------------------------------------------------------

def _load_vault_paths() -> dict[str, Path]:
    """Load vault paths from config/config.json.

    Falls back to scanning the Areas/ directory within the project root
    if no config file exists.
    """
    config_path = PROJECT_ROOT / "config" / "config.json"
    vault_paths: dict[str, Path] = {}

    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        for name, path in cfg.get("vault_paths", {}).items():
            vault_paths[name] = Path(path)

    # Always include the local Areas/ and Team/ directories
    vault_paths["LocalAreas"] = PROJECT_ROOT / "Areas"
    vault_paths["LocalTeam"] = PROJECT_ROOT / "Team"
    vault_paths["LocalInbox"] = PROJECT_ROOT / "Owner's Inbox"

    return vault_paths


VAULT_PATHS: dict[str, Path] = _load_vault_paths()

SKIP_DIRS = {".obsidian", ".trash", "node_modules", ".git"}

# Subdirectories under repo vaults to skip
SKIP_SUBPATHS: set[str] = {
    "Areas/App",       # App code, not notes
    "Areas/Daily",     # HTML briefings, not markdown notes
}

# Regex for inline #tags (but not inside code blocks or frontmatter)
INLINE_TAG_RE = re.compile(r"(?<!\w)#([a-zA-Z][\w/\-]*)", re.UNICODE)

# Frontmatter delimiter
FM_DELIM = "---"


# ---------------------------------------------------------------------------
# Frontmatter Parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_without_frontmatter).
    If no frontmatter found, returns ({}, full_text).
    """
    stripped = text.lstrip("\ufeff")  # strip BOM
    if not stripped.startswith(FM_DELIM):
        return {}, text

    lines = stripped.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == FM_DELIM:
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    fm_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])

    try:
        import yaml
        metadata = yaml.safe_load(fm_text) or {}
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}

    return metadata, body


def extract_frontmatter_tags(metadata: dict) -> list[str]:
    """Extract tags from frontmatter 'tags' field."""
    raw_tags = metadata.get("tags", [])
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if not isinstance(raw_tags, list):
        return []

    cleaned = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        t = tag.strip().lstrip("#").strip()
        if t:
            cleaned.append(t.lower())
    return cleaned


def extract_inline_tags(body: str) -> list[str]:
    """Extract #tags from the markdown body, excluding code blocks."""
    no_code = re.sub(r"```[\s\S]*?```", "", body)
    no_code = re.sub(r"`[^`]+`", "", no_code)
    tags = INLINE_TAG_RE.findall(no_code)
    return [t.lower() for t in tags if len(t) > 1]


def extract_dates_from_metadata(metadata: dict) -> tuple[str | None, str | None]:
    """Extract created/updated dates from frontmatter."""
    created = metadata.get("created") or metadata.get("date") or metadata.get("created_at")
    updated = metadata.get("updated") or metadata.get("modified") or metadata.get("updated_at")

    def normalize_date(d) -> str | None:
        if d is None:
            return None
        if isinstance(d, datetime):
            return d.isoformat()
        s = str(d).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).isoformat()
            except ValueError:
                continue
        return s if s else None

    return normalize_date(created), normalize_date(updated)


# ---------------------------------------------------------------------------
# File Processing
# ---------------------------------------------------------------------------

def compute_content_hash(content: str) -> str:
    """SHA-256 of the content for deduplication."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def get_relative_path(file_path: Path, vault_root: Path) -> str:
    return str(file_path.relative_to(vault_root))


def get_folder(relative_path: str) -> str:
    parent = str(Path(relative_path).parent)
    return parent if parent != "." else ""


def count_words(text: str) -> int:
    return len(text.split())


def process_file(file_path: Path, vault_name: str, vault_root: Path) -> dict | None:
    """Process a single markdown file and return a record dict."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as e:
        return {"error": str(e), "file_path": str(file_path)}

    metadata, body = parse_frontmatter(content)

    fm_tags = extract_frontmatter_tags(metadata)
    inline_tags = extract_inline_tags(body)
    all_tags = sorted(set(fm_tags + inline_tags))

    created_date, updated_date = extract_dates_from_metadata(metadata)

    try:
        stat = file_path.stat()
        file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        file_mtime = None

    rel_path = get_relative_path(file_path, vault_root)
    title = file_path.stem

    aliases = metadata.get("alias", metadata.get("aliases", []))
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        aliases = []

    links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)

    fm_json = {}
    for key in ("up", "related", "category", "cssclasses", "type", "status"):
        if key in metadata and metadata[key] is not None:
            fm_json[key] = metadata[key]
    if aliases:
        fm_json["aliases"] = aliases
    if links:
        fm_json["links"] = links

    return {
        "vault": vault_name,
        "file_path": rel_path,
        "title": title,
        "content": content,
        "body": body,
        "tags": json.dumps(all_tags) if all_tags else None,
        "folder": get_folder(rel_path),
        "word_count": count_words(content),
        "content_hash": compute_content_hash(content),
        "created_at": created_date,
        "updated_at": updated_date,
        "file_modified_at": file_mtime,
        "frontmatter_json": json.dumps(fm_json) if fm_json else None,
    }


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------

def ensure_table(conn: sqlite3.Connection) -> None:
    """Create the obsidian_notes table and FTS index if they don't exist."""
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
    conn.commit()


def upsert_note(conn: sqlite3.Connection, record: dict, seen_hashes: dict) -> str:
    """Insert or update a note. Returns action: 'inserted', 'updated', 'unchanged', 'duplicate'."""
    content_hash = record["content_hash"]
    vault = record["vault"]
    file_path = record["file_path"]

    if content_hash in seen_hashes and seen_hashes[content_hash] != vault:
        return "duplicate"

    existing = conn.execute(
        "SELECT id, content_hash FROM obsidian_notes WHERE vault = ? AND file_path = ?",
        (vault, file_path),
    ).fetchone()

    if existing:
        if existing["content_hash"] == content_hash:
            seen_hashes[content_hash] = vault
            return "unchanged"
        conn.execute(
            """UPDATE obsidian_notes
               SET title = ?, content = ?, tags = ?, folder = ?,
                   word_count = ?, content_hash = ?, frontmatter_json = ?,
                   file_modified_at = ?
               WHERE id = ?""",
            (
                record["title"], record["content"], record["tags"], record["folder"],
                record["word_count"], content_hash, record["frontmatter_json"],
                record["file_modified_at"], existing["id"],
            ),
        )
        seen_hashes[content_hash] = vault
        return "updated"

    dup_check = conn.execute(
        "SELECT vault FROM obsidian_notes WHERE content_hash = ? AND vault != ?",
        (content_hash, vault),
    ).fetchone()
    if dup_check:
        seen_hashes[content_hash] = dup_check["vault"]
        return "duplicate"

    conn.execute(
        """INSERT INTO obsidian_notes
           (vault, file_path, title, content, tags, folder, word_count,
            content_hash, frontmatter_json, created_at, file_modified_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), ?)""",
        (
            vault, file_path, record["title"], record["content"], record["tags"],
            record["folder"], record["word_count"], content_hash,
            record["frontmatter_json"], record["created_at"], record["file_modified_at"],
        ),
    )
    seen_hashes[content_hash] = vault
    return "inserted"


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_ingestion() -> dict:
    """Run the full Obsidian ingestion pipeline. Returns summary dict."""
    conn = get_connection()
    ensure_table(conn)

    stats = {
        "total_scanned": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "duplicates": 0,
        "errors": 0,
        "per_vault": {},
        "error_details": [],
        "duplicate_details": [],
    }

    seen_hashes: dict[str, str] = {}

    for row in conn.execute("SELECT content_hash, vault FROM obsidian_notes").fetchall():
        seen_hashes[row["content_hash"]] = row["vault"]

    for vault_name, vault_path in VAULT_PATHS.items():
        if not vault_path.exists():
            print(f"  WARNING: Vault path does not exist: {vault_path}")
            continue

        vault_stats = {"scanned": 0, "inserted": 0, "updated": 0, "unchanged": 0, "duplicates": 0, "errors": 0}
        print(f"\n  Processing vault: {vault_name} ({vault_path})")

        md_files = []
        for root, dirs, files in os.walk(vault_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            root_path = Path(root)
            try:
                rel_to_project = root_path.relative_to(PROJECT_ROOT)
                if any(str(rel_to_project).startswith(sp) for sp in SKIP_SUBPATHS):
                    dirs.clear()
                    continue
            except ValueError:
                pass

            for f in files:
                if f.endswith(".md"):
                    md_files.append(Path(root) / f)

        print(f"    Found {len(md_files)} markdown files")

        for i, fpath in enumerate(md_files, 1):
            stats["total_scanned"] += 1
            vault_stats["scanned"] += 1

            if i % 100 == 0:
                print(f"    Progress: {i}/{len(md_files)}")

            record = process_file(fpath, vault_name, vault_path)

            if record is None:
                stats["errors"] += 1
                vault_stats["errors"] += 1
                continue

            if "error" in record:
                stats["errors"] += 1
                vault_stats["errors"] += 1
                stats["error_details"].append(f"  {vault_name}: {record['file_path']}: {record['error']}")
                continue

            try:
                action = upsert_note(conn, record, seen_hashes)
                key_map = {"inserted": "inserted", "updated": "updated",
                           "unchanged": "unchanged", "duplicate": "duplicates"}
                stat_key = key_map.get(action, action)
                stats[stat_key] += 1
                vault_stats[stat_key] += 1

                if action == "duplicate":
                    stats["duplicate_details"].append(
                        f"  {vault_name}/{record['file_path']} == {seen_hashes.get(record['content_hash'], '?')}"
                    )
            except Exception as e:
                stats["errors"] += 1
                vault_stats["errors"] += 1
                stats["error_details"].append(f"  {vault_name}: {record['file_path']}: {e}")

        conn.commit()
        stats["per_vault"][vault_name] = vault_stats
        print(f"    Done: {vault_stats}")

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (10, "Obsidian notes table: vault ingestion with FTS5 and dedup"),
    )
    conn.commit()
    conn.close()

    return stats


def print_summary(stats: dict) -> None:
    print("\n" + "=" * 60)
    print("  OBSIDIAN INGESTION SUMMARY")
    print("=" * 60)
    print(f"  Total files scanned:  {stats['total_scanned']}")
    print(f"  Inserted (new):       {stats['inserted']}")
    print(f"  Updated (changed):    {stats['updated']}")
    print(f"  Unchanged (skipped):  {stats['unchanged']}")
    print(f"  Duplicates:           {stats['duplicates']}")
    print(f"  Errors:               {stats['errors']}")

    print("\n  Per Vault:")
    for vault, vs in stats["per_vault"].items():
        print(f"    {vault}: scanned={vs['scanned']}, inserted={vs['inserted']}, "
              f"updated={vs['updated']}, unchanged={vs['unchanged']}, "
              f"duplicates={vs['duplicates']}, errors={vs['errors']}")

    if stats["error_details"]:
        print(f"\n  Errors ({len(stats['error_details'])}):")
        for e in stats["error_details"][:10]:
            print(f"    {e}")


if __name__ == "__main__":
    print("Starting Obsidian vault ingestion...")
    start = time.time()
    stats = run_ingestion()
    elapsed = time.time() - start
    print_summary(stats)
    print(f"\n  Ingestion completed in {elapsed:.1f}s")

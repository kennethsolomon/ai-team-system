"""Query interface for the Memory System — agent memories, lessons, session logs."""

import hashlib
import json
import math
import struct
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from db.migrate import get_connection


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------


def search_memories(
    query: str,
    agent_name: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search on agent_memories via memories_fts. Filters expired rows."""
    conn = get_connection()
    try:
        where = ["(m.expires_at IS NULL OR m.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"]
        params: list = []

        if agent_name:
            where.append("m.agent_name = ?")
            params.append(agent_name)
        if category:
            where.append("m.category = ?")
            params.append(category)

        where_sql = "AND " + " AND ".join(where) if where else ""

        rows = conn.execute(
            f"""SELECT m.*, fts.rank
                FROM memories_fts fts
                JOIN agent_memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
                {where_sql}
                ORDER BY fts.rank
                LIMIT ?""",
            [query, *params, limit],
        ).fetchall()

        return [_memory_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_memories(
    agent_name: str | None = None,
    category: str | None = None,
    memory_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List recent non-expired memories, newest first."""
    conn = get_connection()
    try:
        where = ["(expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"]
        params: list = []

        if agent_name:
            where.append("agent_name = ?")
            params.append(agent_name)
        if category:
            where.append("category = ?")
            params.append(category)
        if memory_type:
            where.append("memory_type = ?")
            params.append(memory_type)

        where_sql = "WHERE " + " AND ".join(where)

        rows = conn.execute(
            f"""SELECT *
                FROM agent_memories
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()

        return [_memory_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_memory(
    agent_name: str,
    category: str,
    content: str,
    tags: list[str] | None = None,
    expires_at: str | None = None,
    memory_type: str = "user",
) -> int:
    """Insert a new memory or reinforce an existing one if content is identical.

    Uses SHA-256 of (agent_name + content) for deduplication.
    If the same content_hash exists for the agent, increments reinforcement_count
    and updates the timestamp instead of creating a duplicate.

    Args:
        agent_name: Which agent owns this memory.
        category: One of 'preference', 'observation', 'pattern', 'context'.
        content: The memory text.
        tags: Optional relevance tags (JSON-serialized).
        expires_at: Optional ISO-8601 expiry timestamp.
        memory_type: One of 'user', 'feedback', 'project', 'reference'. Default 'user'.

    Returns the row id (new or existing).
    """
    _validate_category(category)
    _validate_memory_type(memory_type)
    content_hash = hashlib.sha256((agent_name + content).encode()).hexdigest()
    conn = get_connection()
    try:
        tags_json = json.dumps(tags) if tags else None
        cursor = conn.execute(
            """INSERT INTO agent_memories
                   (agent_name, category, memory_type, content, content_hash, reinforcement_count, relevance_tags, expires_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(agent_name, content_hash) DO UPDATE SET
                   reinforcement_count = reinforcement_count + 1,
                   relevance_tags = COALESCE(excluded.relevance_tags, relevance_tags),
                   category = excluded.category,
                   memory_type = excluded.memory_type""",
            (agent_name, category, memory_type, content, content_hash, tags_json, expires_at),
        )
        conn.commit()
        # Return the id of the inserted or updated row
        row = conn.execute(
            "SELECT id FROM agent_memories WHERE agent_name = ? AND content_hash = ?",
            (agent_name, content_hash),
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


def update_memory(
    memory_id: int,
    content: str | None = None,
    tags: list[str] | None = None,
    expires_at: str | None = None,
) -> bool:
    """Partial update of a memory. Returns True if a row was modified."""
    conn = get_connection()
    try:
        sets: list[str] = []
        params: list = []

        if content is not None:
            sets.append("content = ?")
            params.append(content)
        if tags is not None:
            sets.append("relevance_tags = ?")
            params.append(json.dumps(tags))
        if expires_at is not None:
            sets.append("expires_at = ?")
            params.append(expires_at)

        if not sets:
            return False

        params.append(memory_id)
        cursor = conn.execute(
            f"UPDATE agent_memories SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_memory(memory_id: int) -> bool:
    """Delete a memory. Returns True if a row was removed."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Typed Memory Retrieval
# ---------------------------------------------------------------------------


def get_memories_by_type(
    memory_type: str,
    agent_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return non-expired memories filtered by memory_type.

    Args:
        memory_type: One of 'user', 'feedback', 'project', 'reference'.
        agent_name: Optional filter by agent.
        limit: Max results.

    Returns list of memory dicts sorted by created_at DESC.
    """
    _validate_memory_type(memory_type)
    conn = get_connection()
    try:
        where = [
            "memory_type = ?",
            "(expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        ]
        params: list = [memory_type]

        if agent_name:
            where.append("agent_name = ?")
            params.append(agent_name)

        where_sql = "WHERE " + " AND ".join(where)

        rows = conn.execute(
            f"""SELECT *
                FROM agent_memories
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()

        return [_memory_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Relevance-Based Memory Retrieval
# ---------------------------------------------------------------------------

_LMSTUDIO_URL = "http://localhost:1234/v1/embeddings"
_DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"


def _call_embed_api(texts: list[str], model: str = _DEFAULT_EMBED_MODEL) -> list[list[float]]:
    """Call LM Studio embedding endpoint. Returns list of float vectors."""
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        _LMSTUDIO_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    sorted_data = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in sorted_data]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _blob_to_vector(blob: bytes, dim: int = 768) -> list[float]:
    """Unpack a BLOB into a float32 list."""
    return list(struct.unpack(f"<{dim}f", blob))


def get_relevant_memories(
    task_description: str,
    agent_name: str | None = None,
    top_n: int = 5,
    model: str | None = None,
) -> list[dict]:
    """Return the top N most semantically relevant memories for a task.

    Uses LM Studio embeddings to score each memory against the task description.
    Falls back to returning all recent memories if LM Studio is unreachable.

    Args:
        task_description: Natural language description of the current task.
        agent_name: Optional filter by agent.
        top_n: Number of memories to return.
        model: Embedding model name. Auto-uses default if None.

    Returns list of memory dicts with an added 'relevance_score' field,
    sorted by score descending.
    """
    resolved_model = model or _DEFAULT_EMBED_MODEL

    # Try embedding the query
    try:
        query_vector = _call_embed_api([task_description], resolved_model)[0]
    except (urllib.error.URLError, ConnectionError, OSError, json.JSONDecodeError):
        # LM Studio offline -- fall back to returning all recent memories
        return get_recent_memories(agent_name=agent_name, limit=top_n)

    conn = get_connection()
    try:
        # Fetch all memory embeddings from the embeddings table
        where = ["e.source_table = 'agent_memories'"]
        params: list = []

        if agent_name:
            where.append("m.agent_name = ?")
            params.append(agent_name)

        where.append(
            "(m.expires_at IS NULL OR m.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )

        where_sql = "WHERE " + " AND ".join(where)

        rows = conn.execute(
            f"""SELECT m.*, e.embedding, e.dimensions
                FROM agent_memories m
                JOIN embeddings e
                  ON e.source_table = 'agent_memories'
                  AND e.source_id = CAST(m.id AS TEXT)
                {where_sql}""",
            params,
        ).fetchall()

        if not rows:
            # No embeddings for memories yet -- fall back to recent
            return get_recent_memories(agent_name=agent_name, limit=top_n)

        # Score each memory
        scored: list[tuple[float, dict]] = []
        for row in rows:
            dim = row["dimensions"] or 768
            stored_vector = _blob_to_vector(bytes(row["embedding"]), dim)
            score = _cosine_similarity(query_vector, stored_vector)
            mem_dict = _memory_row_to_dict(row)
            # Remove raw embedding data from output
            mem_dict.pop("embedding", None)
            mem_dict.pop("dimensions", None)
            mem_dict["relevance_score"] = round(score, 4)
            scored.append((score, mem_dict))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:top_n]]

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------


def get_lessons(
    tool_name: str | None = None,
    agent_name: str | None = None,
    outcome: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> list[dict]:
    """List lessons with optional filters, sorted by confidence DESC then recency."""
    conn = get_connection()
    try:
        where: list[str] = []
        params: list = []

        if tool_name:
            where.append("tool_name = ?")
            params.append(tool_name)
        if agent_name:
            where.append("agent_name = ?")
            params.append(agent_name)
        if outcome:
            where.append("outcome = ?")
            params.append(outcome)
        if min_confidence > 0.0:
            where.append("confidence_score >= ?")
            params.append(min_confidence)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        rows = conn.execute(
            f"""SELECT *
                FROM agent_lessons
                {where_sql}
                ORDER BY confidence_score DESC, created_at DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()

        return [_lesson_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_lesson(
    agent_name: str,
    context: str,
    action_taken: str,
    outcome: str,
    tool_name: str | None = None,
    correction: str | None = None,
    confidence_score: float = 0.5,
    tags: list[str] | None = None,
) -> int:
    """Insert a new lesson. Returns the new row id."""
    _validate_outcome(outcome)
    conn = get_connection()
    try:
        tags_json = json.dumps(tags) if tags else None
        cursor = conn.execute(
            """INSERT INTO agent_lessons
                   (agent_name, tool_name, context, action_taken, outcome,
                    correction, confidence_score, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_name, tool_name, context, action_taken, outcome,
             correction, confidence_score, tags_json),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def search_lessons(
    query: str,
    agent_name: str | None = None,
    outcome: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search on agent_lessons via lessons_fts."""
    conn = get_connection()
    try:
        where: list[str] = []
        params: list = []

        if agent_name:
            where.append("l.agent_name = ?")
            params.append(agent_name)
        if outcome:
            where.append("l.outcome = ?")
            params.append(outcome)

        where_sql = "AND " + " AND ".join(where) if where else ""

        rows = conn.execute(
            f"""SELECT l.*, fts.rank
                FROM lessons_fts fts
                JOIN agent_lessons l ON l.rowid = fts.rowid
                WHERE lessons_fts MATCH ?
                {where_sql}
                ORDER BY fts.rank
                LIMIT ?""",
            [query, *params, limit],
        ).fetchall()

        return [_lesson_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def reinforce_lesson(lesson_id: int, new_confidence: float | None = None) -> bool:
    """Bump lesson confidence. If new_confidence given, set it. Otherwise +0.1 capped at 1.0."""
    conn = get_connection()
    try:
        if new_confidence is not None:
            cursor = conn.execute(
                "UPDATE agent_lessons SET confidence_score = ? WHERE id = ?",
                (min(max(new_confidence, 0.0), 1.0), lesson_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE agent_lessons SET confidence_score = MIN(confidence_score + 0.1, 1.0) WHERE id = ?",
                (lesson_id,),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Logs
# ---------------------------------------------------------------------------


def log_session_task(
    session_id: str,
    agent_name: str,
    task_description: str,
    status: str = "delegated",
    notes: str | None = None,
) -> int:
    """Insert a session log entry. Returns the new row id."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO session_logs (session_id, agent_name, task_description, status, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, agent_name, task_description, status, notes),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_session_task(
    log_id: int,
    status: str,
    notes: str | None = None,
) -> bool:
    """Update a session log status. Auto-sets completed_at for terminal states."""
    conn = get_connection()
    try:
        completed_at = None
        if status in ("completed", "failed"):
            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        sets = ["status = ?"]
        params: list = [status]

        if completed_at:
            sets.append("completed_at = ?")
            params.append(completed_at)
        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)

        params.append(log_id)
        cursor = conn.execute(
            f"UPDATE session_logs SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_session_log(
    session_id: str | None = None,
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """List session log entries with optional filters."""
    conn = get_connection()
    try:
        where: list[str] = []
        params: list = []

        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if agent_name:
            where.append("agent_name = ?")
            params.append(agent_name)
        if status:
            where.append("status = ?")
            params.append(status)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        rows = conn.execute(
            f"""SELECT *
                FROM session_logs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Summaries
# ---------------------------------------------------------------------------


def save_session_summary(
    session_id: str,
    request: str = "",
    investigated: str = "",
    learned: str = "",
    completed: str = "",
    next_steps: str = "",
) -> int:
    """Save a structured session summary. Returns the new row id."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO session_summaries
                   (session_id, request, investigated, learned, completed, next_steps)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, request, investigated, learned, completed, next_steps),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_session_summary(session_id: str) -> dict | None:
    """Get the most recent summary for a session_id."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM session_summaries
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_recent_summaries(limit: int = 7) -> list[dict]:
    """Get the N most recent session summaries, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM session_summaries
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Context Loader
# ---------------------------------------------------------------------------


def load_context_for_session(
    agent_name: str | None = None,
    tool_names: list[str] | None = None,
    memory_limit: int = 15,
    lesson_limit: int = 10,
) -> dict:
    """Load a combined context dict with memories, lessons, and pending tasks."""
    memories = get_recent_memories(agent_name=agent_name, limit=memory_limit)

    lessons: list[dict] = []
    if tool_names:
        for tool in tool_names:
            lessons.extend(get_lessons(tool_name=tool, agent_name=agent_name, limit=lesson_limit))
        # Deduplicate by id, sort by confidence
        seen: set[int] = set()
        unique: list[dict] = []
        for lesson in lessons:
            if lesson["id"] not in seen:
                seen.add(lesson["id"])
                unique.append(lesson)
        lessons = sorted(unique, key=lambda x: x["confidence_score"], reverse=True)[:lesson_limit]
    else:
        lessons = get_lessons(agent_name=agent_name, limit=lesson_limit)

    # Pending tasks from last 7 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn = get_connection()
    try:
        where = ["status IN ('delegated', 'in_progress', 'pending')", "started_at >= ?"]
        params: list = [cutoff]

        if agent_name:
            where.append("agent_name = ?")
            params.append(agent_name)

        where_sql = "WHERE " + " AND ".join(where)

        rows = conn.execute(
            f"""SELECT *
                FROM session_logs
                {where_sql}
                ORDER BY started_at DESC""",
            params,
        ).fetchall()

        pending_tasks = [dict(r) for r in rows]
    finally:
        conn.close()

    return {
        "memories": memories,
        "lessons": lessons,
        "pending_tasks": pending_tasks,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"preference", "observation", "pattern", "context"}
VALID_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
VALID_OUTCOMES = {"success", "failure"}


def _validate_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {VALID_CATEGORIES}")


def _validate_memory_type(memory_type: str) -> None:
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"Invalid memory_type '{memory_type}'. Must be one of: {VALID_MEMORY_TYPES}")


def _validate_outcome(outcome: str) -> None:
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Invalid outcome '{outcome}'. Must be one of: {VALID_OUTCOMES}")


def _parse_json_field(value: str | None) -> list | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _memory_row_to_dict(row) -> dict:
    d = dict(row)
    d["relevance_tags"] = _parse_json_field(d.get("relevance_tags"))
    return d


def _lesson_row_to_dict(row) -> dict:
    d = dict(row)
    d["tags"] = _parse_json_field(d.get("tags"))
    return d

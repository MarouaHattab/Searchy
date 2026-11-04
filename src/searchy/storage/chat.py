import json
import time
from uuid import uuid4

from searchy.core import SearchyError

MAX_MESSAGES = 400
MAX_AGE_SECONDS = 7 * 86400


class ChatStore:
    """Durable conversation history, keyed by conversation id.

    Each turn keeps the user's question, the assistant's answer, and the cited
    sources, so a follow-up can be resolved against what was already said
    without replaying retrieval for every earlier turn.
    """

    def __init__(self, metadata):
        self.metadata = metadata
        with metadata.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_conversations ("
                "id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, "
                "title TEXT NOT NULL DEFAULT '')"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_messages ("
                "id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created REAL NOT NULL, "
                "role TEXT NOT NULL, content TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}')"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS chat_message_conversation "
                "ON chat_messages(conversation_id, created)"
            )

    def create(self, title: str = "") -> str:
        identifier = str(uuid4())
        now = time.time()
        with self.metadata.connect() as db:
            db.execute(
                "INSERT INTO chat_conversations(id, created, updated, title) VALUES(?,?,?,?)",
                (identifier, now, now, title[:120]),
            )
        return identifier

    def exists(self, conversation_id: str) -> bool:
        with self.metadata.connect() as db:
            row = db.execute(
                "SELECT 1 FROM chat_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        return row is not None

    def ensure(self, conversation_id: str | None, title: str = "") -> str:
        if conversation_id and self.exists(conversation_id):
            return conversation_id
        return self.create(title)

    def history(self, conversation_id: str, limit: int = 12) -> list[dict]:
        with self.metadata.connect() as db:
            rows = db.execute(
                "SELECT role, content, data FROM chat_messages WHERE conversation_id=? "
                "ORDER BY created DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [
            {"role": row["role"], "content": row["content"], "data": json.loads(row["data"] or "{}")}
            for row in reversed(rows)
        ]

    def messages(self, conversation_id: str) -> list[dict]:
        with self.metadata.connect() as db:
            rows = db.execute(
                "SELECT id, created, role, content, data FROM chat_messages "
                "WHERE conversation_id=? ORDER BY created",
                (conversation_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created": row["created"],
                "role": row["role"],
                "content": row["content"],
                "data": json.loads(row["data"] or "{}"),
            }
            for row in rows
        ]

    def append(
        self, conversation_id: str, role: str, content: str, data: dict | None = None
    ) -> str:
        if role not in {"user", "assistant"}:
            raise SearchyError("Unsupported chat role", 422)
        identifier = str(uuid4())
        now = time.time()
        with self.metadata.connect() as db:
            db.execute(
                "INSERT INTO chat_messages(id, conversation_id, created, role, content, data) "
                "VALUES(?,?,?,?,?,?)",
                (identifier, conversation_id, now, role, content, json.dumps(data or {})),
            )
            db.execute(
                "UPDATE chat_conversations SET updated=? WHERE id=?", (now, conversation_id)
            )
            db.execute(
                "DELETE FROM chat_messages WHERE conversation_id=? AND id NOT IN "
                "(SELECT id FROM chat_messages WHERE conversation_id=? "
                "ORDER BY created DESC LIMIT ?)",
                (conversation_id, conversation_id, MAX_MESSAGES),
            )
            db.execute(
                "DELETE FROM chat_conversations WHERE updated < ?",
                (time.time() - MAX_AGE_SECONDS,),
            )
        return identifier

    def list_conversations(self, limit: int = 30) -> list[dict]:
        with self.metadata.connect() as db:
            rows = db.execute(
                "SELECT c.id, c.created, c.updated, c.title, "
                "(SELECT content FROM chat_messages m WHERE m.conversation_id=c.id "
                " AND m.role='user' ORDER BY m.created LIMIT 1) AS first_question, "
                "(SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id=c.id) AS turns "
                "FROM chat_conversations c ORDER BY c.updated DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conversations = [dict(row) for row in rows]
        # Several chats commonly open with the same question. Suffix the repeats
        # so the list is navigable instead of showing one title four times.
        seen: dict[str, int] = {}
        for item in conversations:
            base = (item.get("first_question") or item.get("title") or "Untitled").strip()
            base = " ".join(base.split())[:70]
            seen[base] = seen.get(base, 0) + 1
            item["title"] = base if seen[base] == 1 else f"{base} ({seen[base]})"
        return conversations

    def delete(self, conversation_id: str) -> None:
        with self.metadata.connect() as db:
            db.execute("DELETE FROM chat_messages WHERE conversation_id=?", (conversation_id,))
            db.execute("DELETE FROM chat_conversations WHERE id=?", (conversation_id,))

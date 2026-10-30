from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from searchy.core.errors import InvalidInput, SearchyError


class CharacterStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    collection_id TEXT NOT NULL, video_id TEXT, revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'unprocessed',
                    recognition_status TEXT NOT NULL DEFAULT 'unprocessed',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS character_scope ON characters(collection_id,video_id);
                CREATE TABLE IF NOT EXISTS character_references (
                    id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id)
                        ON DELETE CASCADE,
                    digest TEXT NOT NULL, path TEXT NOT NULL, width INTEGER NOT NULL,
                    height INTEGER NOT NULL, validation TEXT NOT NULL DEFAULT 'image_validated',
                    error TEXT, embedding TEXT, model_id TEXT,
                    UNIQUE(character_id,digest)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _record(db, row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["references"] = [
            dict(reference)
            for reference in db.execute(
                "SELECT * FROM character_references WHERE character_id=? ORDER BY rowid",
                (row["id"],),
            )
        ]
        return result

    def get(self, character_id: str) -> dict | None:
        with self.connect() as db:
            return self._record(
                db, db.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
            )

    def list(self, collection_id: str | None = None, video_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            return [
                self._record(db, row)
                for row in db.execute(
                    """SELECT * FROM characters WHERE (? IS NULL OR collection_id=?)
                       AND (? IS NULL OR video_id IS NULL OR video_id=?) ORDER BY name,id""",
                    (collection_id, collection_id, video_id, video_id),
                ).fetchall()
            ]

    def create(self, name: str, description: str, collection_id: str, video_id: str | None) -> dict:
        identifier, now = str(uuid4()), time.time()
        with self.connect() as db:
            db.execute(
                """INSERT INTO characters(id,name,description,collection_id,video_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (identifier, name, description, collection_id, video_id, now, now),
            )
        return self.get(identifier)

    def update(self, character_id: str, values: dict, revision: int | None = None) -> bool:
        allowed = {"name", "description", "revision", "status", "recognition_status"}
        if not values or set(values) - allowed:
            raise ValueError("Unsupported character update")
        changes = {**values, "updated_at": time.time()}
        with self.connect() as db:
            result = db.execute(
                f"UPDATE characters SET {','.join(f'{key}=?' for key in changes)} "
                "WHERE id=? AND (? IS NULL OR revision=?)",
                (*changes.values(), character_id, revision, revision),
            )
            return result.rowcount == 1

    def add_references(self, character_id: str, references: list[dict]) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
            if row is None:
                raise SearchyError("Character not found", 404)
            existing = {
                r[0]
                for r in db.execute(
                    "SELECT digest FROM character_references WHERE character_id=?", (character_id,)
                )
            }
            fresh = {r["digest"]: r for r in references if r["digest"] not in existing}
            if len(existing) + len(fresh) > 5:
                raise InvalidInput("A character can have at most five reference images")
            for reference in fresh.values():
                db.execute(
                    """INSERT INTO character_references(id,character_id,digest,path,width,height)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        reference["id"],
                        character_id,
                        reference["digest"],
                        reference["path"],
                        reference["width"],
                        reference["height"],
                    ),
                )
            if fresh:
                db.execute(
                    """UPDATE characters SET revision=revision+1,status='queued',
                       recognition_status='unprocessed',updated_at=? WHERE id=?""",
                    (time.time(), character_id),
                )
        return self.get(character_id)

    def remove_reference(self, character_id: str, reference_id: str) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "DELETE FROM character_references WHERE id=? AND character_id=?",
                (reference_id, character_id),
            )
            if result.rowcount:
                db.execute(
                    """UPDATE characters SET revision=revision+1,status='unprocessed',
                       recognition_status='unprocessed',updated_at=? WHERE id=?""",
                    (time.time(), character_id),
                )
            return result.rowcount == 1

    def save_prepared(self, character_id: str, revision: int, references: list[dict]) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM characters WHERE id=?", (character_id,)
            ).fetchone()
            if row is None or row[0] != revision:
                return False
            for reference in references:
                db.execute(
                    """UPDATE character_references SET validation=?,error=?,embedding=?,model_id=?
                       WHERE id=? AND character_id=?""",
                    (
                        reference["validation"],
                        reference.get("error"),
                        json.dumps(reference["embedding"]) if reference.get("embedding") else None,
                        reference.get("model_id"),
                        reference["id"],
                        character_id,
                    ),
                )
            ready = any(
                ref["validation"] in {"image_validated", "face_ready"} for ref in references
            )
            db.execute(
                "UPDATE characters SET status=?,updated_at=? WHERE id=?",
                ("ready" if ready else "failed", time.time(), character_id),
            )
            return True

    def replace_reference(self, character_id: str, reference_id: str, replacement: dict) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM character_references WHERE character_id=? AND id=?",
                (character_id, reference_id),
            ).fetchone()
            if row is None:
                raise SearchyError("Character reference not found", 404)
            if db.execute(
                "SELECT 1 FROM character_references WHERE character_id=? AND digest=? AND id<>?",
                (character_id, replacement["digest"], reference_id),
            ).fetchone():
                raise InvalidInput("This image is already registered for the character")
            db.execute("DELETE FROM character_references WHERE id=?", (reference_id,))
            db.execute(
                "INSERT INTO character_references(id,character_id,digest,path,width,height) VALUES(?,?,?,?,?,?)",
                (
                    replacement["id"],
                    character_id,
                    replacement["digest"],
                    replacement["path"],
                    replacement["width"],
                    replacement["height"],
                ),
            )
            db.execute(
                "UPDATE characters SET revision=revision+1,status='queued',recognition_status='unprocessed',updated_at=? WHERE id=?",
                (time.time(), character_id),
            )
        return self.get(character_id)

    def delete(self, character_id: str) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM characters WHERE id=?", (character_id,)).rowcount == 1

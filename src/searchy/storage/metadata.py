import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from searchy.domain import Scene, Video


class MetadataStore:
    def __init__(self, path: Path, index_signature: str = ""):
        self.path = path
        self.index_signature = index_signature
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenes (
                    scene_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id),
                    collection_id TEXT NOT NULL, data TEXT NOT NULL, indexed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS scene_video ON scenes(video_id);
                CREATE INDEX IF NOT EXISTS scene_collection ON scenes(collection_id);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT 'queued', error TEXT, result TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0
                );
            """)
            if "index_signature" not in {r[1] for r in db.execute("PRAGMA table_info(scenes)")}:
                db.execute("ALTER TABLE scenes ADD COLUMN index_signature TEXT NOT NULL DEFAULT ''")

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

    def save_video(self, video: Video):
        with self.connect() as db:
            db.execute(
                "INSERT INTO videos VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET data=excluded.data",
                (video.video_id, video.collection_id, video.model_dump_json()),
            )

    def save_scene(self, scene: Scene):
        with self.connect() as db:
            db.execute(
                """INSERT INTO scenes(scene_id,video_id,collection_id,data) VALUES(?,?,?,?)
                   ON CONFLICT(scene_id) DO UPDATE SET data=excluded.data,indexed=0,index_signature=''""",
                (scene.scene_id, scene.video_id, scene.collection_id, scene.model_dump_json()),
            )

    def mark_indexed(self, scene_id: str):
        with self.connect() as db:
            db.execute(
                "UPDATE scenes SET indexed=1,index_signature=? WHERE scene_id=?",
                (self.index_signature, scene_id),
            )

    def scene_ids(self, video_id: str) -> set[str]:
        with self.connect() as db:
            return {
                r[0]
                for r in db.execute("SELECT scene_id FROM scenes WHERE video_id=?", (video_id,))
            }

    def delete_scenes(self, scene_ids: list[str]):
        with self.connect() as db:
            db.executemany("DELETE FROM scenes WHERE scene_id=?", [(s,) for s in scene_ids])

    def is_indexed(self, scene_id: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT indexed FROM scenes WHERE scene_id=? AND index_signature=?",
                (scene_id, self.index_signature),
            ).fetchone()
            return bool(row and row[0])

    def get_scene(self, scene_id: str) -> Scene | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM scenes WHERE scene_id=?", (scene_id,)).fetchone()
            return Scene.model_validate_json(row[0]) if row else None

    def get_video(self, video_id: str) -> Video | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM videos WHERE video_id=?", (video_id,)).fetchone()
            return Video.model_validate_json(row[0]) if row else None

    def list_videos(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT v.data,COUNT(s.scene_id) scene_count,
                   COALESCE(SUM(CASE WHEN s.index_signature=? THEN s.indexed ELSE 0 END),0) indexed_scenes
                   FROM videos v LEFT JOIN scenes s ON s.video_id=v.video_id
                   GROUP BY v.video_id ORDER BY v.video_id LIMIT ? OFFSET ?""",
                (self.index_signature, limit, offset),
            ).fetchall()
        return [
            dict(
                video=Video.model_validate_json(r["data"]),
                scene_count=r["scene_count"],
                indexed_scenes=r["indexed_scenes"],
            )
            for r in rows
        ]

    def list_scenes(self, video_id: str, limit: int = 100, offset: int = 0) -> list[Scene]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT data FROM scenes WHERE video_id=?
                   ORDER BY json_extract(data,'$.start') IS NULL,
                   CAST(json_extract(data,'$.start') AS REAL),scene_id LIMIT ? OFFSET ?""",
                (video_id, limit, offset),
            ).fetchall()
        return [Scene.model_validate_json(r[0]) for r in rows]

    def collections(self) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """
                SELECT v.collection_id,COUNT(DISTINCT v.video_id) video_count,
                COUNT(s.scene_id) scene_count,
                COALESCE(SUM(CASE WHEN s.index_signature=? THEN s.indexed ELSE 0 END),0) indexed_scenes
                FROM videos v LEFT JOIN scenes s ON s.video_id=v.video_id GROUP BY v.collection_id
            """,
                    (self.index_signature,),
                )
            ]

    def characters(self, collection_id: str | None) -> list[str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT data FROM scenes WHERE indexed=1 AND index_signature=? AND (? IS NULL OR collection_id=?)",
                (self.index_signature, collection_id, collection_id),
            ).fetchall()
        return sorted({c for r in rows for c in Scene.model_validate_json(r[0]).characters})

    def catalog_records(self) -> tuple[list[Video], list[tuple[Scene, bool]], list[dict]]:
        with self.connect() as db:
            db.execute("BEGIN")
            videos = [
                Video.model_validate_json(row[0]) for row in db.execute("SELECT data FROM videos")
            ]
            scenes = [
                (
                    Scene.model_validate_json(row["data"]),
                    bool(row["indexed"] and row["index_signature"] == self.index_signature),
                )
                for row in db.execute("SELECT data,indexed,index_signature FROM scenes")
            ]
            jobs = []
            for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC"):
                job = dict(row)
                job["payload"] = json.loads(job["payload"])
                job["result"] = json.loads(job["result"]) if job["result"] else None
                jobs.append(job)
        return videos, scenes, jobs

    def create_job(self, kind: str, payload: dict) -> dict:
        now = time.time()
        job_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(job_id,kind,payload,created_at,updated_at) VALUES(?,?,?,?,?)",
                (job_id, kind, json.dumps(payload), now, now),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            ids = [r[0] for r in rows]
        return [self.get_job(job_id) for job_id in ids]

    def claim_job(self, owner: str, lease_seconds: int) -> dict | None:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE jobs SET status='failed',error='Worker lease expired after three attempts',
                   stage='failed',updated_at=? WHERE status='running' AND lease_until<? AND attempts>=3""",
                (now, now),
            )
            row = db.execute(
                """SELECT job_id FROM jobs WHERE status='queued' OR
                   (status='running' AND lease_until<? AND attempts<3) ORDER BY created_at LIMIT 1""",
                (now,),
            ).fetchone()
            if not row:
                return None
            db.execute(
                """UPDATE jobs SET status='running',owner=?,lease_until=?,updated_at=?,
                   attempts=attempts+1,error=NULL WHERE job_id=?""",
                (owner, now + lease_seconds, now, row[0]),
            )
        return self.get_job(row[0])

    def update_job(
        self,
        job_id: str,
        owner: str,
        *,
        progress: float | None = None,
        stage: str | None = None,
        status: str | None = None,
        result: dict | None = None,
        error: str | None = None,
        lease_seconds: int = 120,
    ) -> bool:
        values = {"updated_at": time.time(), "lease_until": time.time() + lease_seconds}
        for key, value in dict(
            progress=progress,
            stage=stage,
            status=status,
            result=json.dumps(result) if result is not None else None,
            error=error,
        ).items():
            if value is not None:
                values[key] = value
        assignment = ",".join(f"{key}=?" for key in values)
        with self.connect() as db:
            updated = db.execute(
                f"UPDATE jobs SET {assignment} WHERE job_id=? AND owner=? AND status='running'",
                (*values.values(), job_id, owner),
            )
            return updated.rowcount == 1

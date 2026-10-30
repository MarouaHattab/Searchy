import hashlib
import json
import time
from uuid import uuid4

from searchy.core.errors import SearchyError


class SearchSessions:
    def __init__(self, metadata):
        self.metadata = metadata
        with metadata.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS search_sessions (id TEXT PRIMARY KEY, created REAL NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL)"
            )

    def _fingerprint(self, response):
        digest = hashlib.sha256(self.metadata.index_signature.encode())
        for result in response.get("results", []):
            scene = self.metadata.get_scene(result["scene_id"])
            if scene is None or not self.metadata.is_indexed(scene.scene_id):
                raise SearchyError("Search evidence changed or expired; run this search again", 409)
            digest.update(scene.model_dump_json().encode())
        return digest.hexdigest()

    def create(self, request, response):
        identifier = str(uuid4())
        response["search_id"] = identifier
        data = {"request": request, "response": response, "answer": None}
        fingerprint = self._fingerprint(response)
        with self.metadata.connect() as db:
            db.execute("DELETE FROM search_sessions WHERE created < ?", (time.time() - 86400,))
            db.execute(
                "INSERT INTO search_sessions VALUES(?,?,?,?)",
                (identifier, time.time(), fingerprint, json.dumps(data)),
            )
            db.execute(
                "DELETE FROM search_sessions WHERE id IN (SELECT id FROM search_sessions ORDER BY created DESC LIMIT -1 OFFSET 200)"
            )
        return identifier

    def get(self, identifier):
        with self.metadata.connect() as db:
            row = db.execute("SELECT * FROM search_sessions WHERE id=?", (identifier,)).fetchone()
        if row is None or row["created"] < time.time() - 86400:
            raise SearchyError("This search session expired; run this search again", 404)
        data = json.loads(row["data"])
        if row["fingerprint"] != self._fingerprint(data["response"]):
            raise SearchyError("Search evidence changed or expired; run this search again", 409)
        from searchy.retrieval.search import playback

        for result in data["response"].get("results", []):
            result["playback"] = playback(self.metadata.get_scene(result["scene_id"]))
        if data.get("answer"):
            for citation in data["answer"].get("citations", []):
                scene = self.metadata.get_scene(citation["scene_id"])
                citation["available"] = bool(scene and playback(scene)["available"])
        return data

    def save_answer(self, identifier, answer):
        data = self.get(identifier)
        data["answer"] = answer
        with self.metadata.connect() as db:
            db.execute(
                "UPDATE search_sessions SET data=? WHERE id=?", (json.dumps(data), identifier)
            )

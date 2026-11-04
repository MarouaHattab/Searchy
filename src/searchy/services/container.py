from searchy.core import Settings
from searchy.domain import stable_id
from searchy.graph import GraphStore
from searchy.models import LocalEmbeddings, VisualEmbeddings
from searchy.retrieval import SearchEngine
from searchy.storage import (
    CharacterStore,
    ChatStore,
    MetadataStore,
    SearchSessions,
    VectorStore,
)
from .characters import CharacterService
from .recognition import RecognitionService


class Services:
    def __init__(self, settings: Settings):
        self.settings = settings
        signature = stable_id(
            repr(
                (
                    settings.neo4j_uri,
                    settings.neo4j_database,
                    settings.qdrant_url,
                    settings.qdrant_collection_name,
                    settings.embedding_provider,
                    settings.embedding_model_id,
                    settings.visual_enabled,
                    settings.visual_model_id,
                )
            )
        )
        self.metadata = MetadataStore(settings.database_path, signature)
        self.sessions = SearchSessions(self.metadata)
        self.chat = ChatStore(self.metadata)
        self.characters = CharacterService(settings, self.metadata)
        self.embeddings = LocalEmbeddings(settings)
        self.visual = VisualEmbeddings(settings) if settings.visual_enabled else None
        self.graph = GraphStore(settings)
        self.vectors = VectorStore(settings, self.embeddings, self.visual)
        self.recognition = RecognitionService(
            settings, self.metadata, self.characters, self.graph, self.vectors
        )
        self.search = SearchEngine(settings, self.metadata, self.graph, self.vectors)

    def close(self):
        self.graph.close()
        self.vectors.close()

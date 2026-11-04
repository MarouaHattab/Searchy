from .core import InvalidInput, SearchyError, Settings
from .domain import (
    Candidate,
    Dialogue,
    EpisodeSummary,
    Observation,
    ObservationKind,
    Provenance,
    Record,
    Scene,
    SummaryEvent,
    Video,
    stable_id,
)

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "Dialogue",
    "EpisodeSummary",
    "InvalidInput",
    "Observation",
    "ObservationKind",
    "Provenance",
    "Record",
    "Scene",
    "SearchyError",
    "Settings",
    "SummaryEvent",
    "Video",
    "__version__",
    "stable_id",
]

# Backward compatibility mapping for legacy imports from root package
_COMPAT_EXPORTS = {
    "AnswerService": "searchy.services",
    "CharacterStore": "searchy.storage",
    "ChatService": "searchy.services",
    "ChatStore": "searchy.storage",
    "ClaimVerificationResult": "searchy.models",
    "ClaimVerifier": "searchy.models",
    "EpisodeSummaryBuilder": "searchy.summaries",
    "MetadataStore": "searchy.storage",
    "SearchEngine": "searchy.retrieval",
    "SearchSessions": "searchy.storage",
    "Services": "searchy.services",
    "SpeakerAligner": "searchy.ingestion",
    "VectorStore": "searchy.storage",
    "VideoProcessor": "searchy.processing",
    "import_chunks": "searchy.ingestion",
    "inspect_chunks": "searchy.ingestion",
    "understand": "searchy.retrieval",
}


def __getattr__(name: str):
    if name in _COMPAT_EXPORTS:
        from importlib import import_module

        target_mod = import_module(_COMPAT_EXPORTS[name])
        val = getattr(target_mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

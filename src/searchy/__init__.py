from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.core.config import Settings as Settings
    from searchy.core.errors import InvalidInput as InvalidInput
    from searchy.core.errors import SearchyError as SearchyError
    from searchy.domain import Candidate as Candidate
    from searchy.domain import Dialogue as Dialogue
    from searchy.domain import Observation as Observation
    from searchy.domain import ObservationKind as ObservationKind
    from searchy.domain import Provenance as Provenance
    from searchy.domain import Scene as Scene
    from searchy.domain import Video as Video
    from searchy.domain import stable_id as stable_id

_EXPORTS = {
    "Settings": "searchy.core.config",
    "SearchyError": "searchy.core.errors",
    "InvalidInput": "searchy.core.errors",
    "Scene": "searchy.domain",
    "Video": "searchy.domain",
    "Candidate": "searchy.domain",
    "Dialogue": "searchy.domain",
    "Observation": "searchy.domain",
    "ObservationKind": "searchy.domain",
    "Provenance": "searchy.domain",
    "stable_id": "searchy.domain",
}

__all__ = list(_EXPORTS)
__version__ = "0.1.0"


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted([*globals(), *__all__])

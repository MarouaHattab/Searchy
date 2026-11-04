
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.storage.characters import CharacterStore as CharacterStore
    from searchy.storage.chat import ChatStore as ChatStore
    from searchy.storage.metadata import MetadataStore as MetadataStore
    from searchy.storage.sessions import SearchSessions as SearchSessions
    from searchy.storage.vectors import VectorStore as VectorStore

_EXPORTS = {
    "CharacterStore": "searchy.storage.characters",
    "ChatStore": "searchy.storage.chat",
    "MetadataStore": "searchy.storage.metadata",
    "SearchSessions": "searchy.storage.sessions",
    "VectorStore": "searchy.storage.vectors",
}

__all__ = list(_EXPORTS)


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

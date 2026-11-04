
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.ingestion.importer import ImportResult as ImportResult
    from searchy.ingestion.importer import import_chunks as import_chunks
    from searchy.ingestion.importer import inspect_chunks as inspect_chunks

_EXPORTS = {
    "ImportResult": "searchy.ingestion.importer",
    "import_chunks": "searchy.ingestion.importer",
    "inspect_chunks": "searchy.ingestion.importer",
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

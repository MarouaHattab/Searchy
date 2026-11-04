

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.graph.explorer import GraphExplorer as GraphExplorer
    from searchy.graph.store import GraphStore as GraphStore

_EXPORTS = {
    "GraphExplorer": "searchy.graph.explorer",
    "GraphStore": "searchy.graph.store",
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

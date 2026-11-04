from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.retrieval.search import SearchEngine as SearchEngine
    from searchy.retrieval.search import scene_view as scene_view
    from searchy.retrieval.understanding import QueryUnderstanding as QueryUnderstanding
    from searchy.retrieval.understanding import understand as understand

_EXPORTS = {
    "SearchEngine": "searchy.retrieval.search",
    "scene_view": "searchy.retrieval.search",
    "QueryUnderstanding": "searchy.retrieval.understanding",
    "understand": "searchy.retrieval.understanding",
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

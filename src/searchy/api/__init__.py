
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.api.answers import create_answers_router as create_answers_router
    from searchy.api.catalog import create_catalog_router as create_catalog_router
    from searchy.api.characters import create_character_router as create_character_router
    from searchy.api.chat import create_chat_router as create_chat_router
    from searchy.api.exploration import create_exploration_router as create_exploration_router

_EXPORTS = {
    "create_answers_router": "searchy.api.answers",
    "create_catalog_router": "searchy.api.catalog",
    "create_character_router": "searchy.api.characters",
    "create_chat_router": "searchy.api.chat",
    "create_exploration_router": "searchy.api.exploration",
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

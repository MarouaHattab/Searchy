
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.services.answers import AnswerService as AnswerService
    from searchy.services.catalog import CatalogService as CatalogService
    from searchy.services.characters import CharacterService as CharacterService
    from searchy.services.chat import ChatService as ChatService
    from searchy.services.container import Services as Services
    from searchy.services.media import MediaService as MediaService
    from searchy.services.recognition import RecognitionService as RecognitionService

_EXPORTS = {
    "AnswerService": "searchy.services.answers",
    "CatalogService": "searchy.services.catalog",
    "CharacterService": "searchy.services.characters",
    "ChatService": "searchy.services.chat",
    "Services": "searchy.services.container",
    "MediaService": "searchy.services.media",
    "RecognitionService": "searchy.services.recognition",
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

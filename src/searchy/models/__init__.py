

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.models.answers import AnswerProvider as AnswerProvider
    from searchy.models.embeddings import LocalEmbeddings as LocalEmbeddings
    from searchy.models.embeddings import VisualEmbeddings as VisualEmbeddings
    from searchy.models.faces import OpenCVFaces as OpenCVFaces
    from searchy.models.vision import GeminiVision as GeminiVision
    from searchy.models.vision import GroqVision as GroqVision
    from searchy.models.vision import IdentityReference as IdentityReference
    from searchy.models.vision import get_vision_provider as get_vision_provider

_EXPORTS = {
    "AnswerProvider": "searchy.models.answers",
    "LocalEmbeddings": "searchy.models.embeddings",
    "VisualEmbeddings": "searchy.models.embeddings",
    "OpenCVFaces": "searchy.models.faces",
    "GeminiVision": "searchy.models.vision",
    "GroqVision": "searchy.models.vision",
    "IdentityReference": "searchy.models.vision",
    "get_vision_provider": "searchy.models.vision",
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

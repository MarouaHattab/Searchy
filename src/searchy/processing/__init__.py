from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.processing.captioning import Captioner as Captioner
    from searchy.processing.captioning import build_captioner as build_captioner
    from searchy.processing.chunking import process_episode as process_episode
    from searchy.processing.video import Media as Media
    from searchy.processing.video import VideoMetadata as VideoMetadata
    from searchy.processing.video import VideoProcessor as VideoProcessor

_EXPORTS = {
    "Captioner": "searchy.processing.captioning",
    "build_captioner": "searchy.processing.captioning",
    "process_episode": "searchy.processing.chunking",
    "VideoMetadata": "searchy.processing.video",
    "VideoProcessor": "searchy.processing.video",
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

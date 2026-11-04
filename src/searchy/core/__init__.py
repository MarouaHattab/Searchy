

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from searchy.core.config import Settings as Settings
    from searchy.core.errors import InvalidInput as InvalidInput
    from searchy.core.errors import SearchyError as SearchyError

_EXPORTS = {
    "Settings": "searchy.core.config",
    "SearchyError": "searchy.core.errors",
    "InvalidInput": "searchy.core.errors",
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

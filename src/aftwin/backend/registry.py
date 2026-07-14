"""Static registry resolving renderer names to platform backends."""

from collections.abc import Mapping
from typing import Final

from aftwin.backend.contract import PlatformBackend
from aftwin.backend.frr import FrrBackend
from aftwin.backend.linux_endpoint import LinuxEndpointBackend

_BACKENDS: Final[Mapping[str, PlatformBackend]] = {
    backend.name: backend for backend in (FrrBackend(), LinuxEndpointBackend())
}


def registered_renderers() -> frozenset[str]:
    """Return every renderer name the compiler may dispatch to."""
    return frozenset(_BACKENDS)


def get_backend(renderer: str) -> PlatformBackend:
    """Resolve one renderer name or fail with the supported set."""
    backend = _BACKENDS.get(renderer)
    if backend is None:
        supported = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"unsupported renderer: {renderer!r}; supported renderers: {supported}")
    return backend
